import typer
import unicodedata
import uvicorn
import webbrowser
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
from .server import app
from .core import (
    BASE_DIR, list_experiments, get_experiment, run_single_test,
    delete_experiment_data, EvalRequest, save_experiment_data,
    get_config, save_config, import_csv, export_to_csv, GlobalConfig, request_with_retry,
    compare_tools, fetch_mcp_context, generate_test_cases, Experiment, uuid,
    judge_test_case, judge_answer_correctness, parse_header_args, compute_metrics, extract_readonly_tools,
    radar_profile, RADAR_AXES, TestCase, generate_negative_cases,
    parse_mcp_tools, single_tool_context
)


def _run_case(case, exp, verify_args, judge, judge_model, api_key, timeout=120):
    """Execute one test case, mutate it in place, and report whether tools matched."""
    req = EvalRequest(
        app_name=case.appName, api_url=exp.apiUrl, user_id=exp.userId,
        question=case.q, state=case.state, timeout=timeout
    )
    result = run_single_test(req)

    case.actualTools = result.get("tools", "")
    case.actualAnswer = result.get("answer", "")
    case.rawResponse = result.get("raw_response")

    # 1. Traditional Match
    tools_match = compare_tools(case.expectedTools, case.actualTools, verify_args=verify_args)
    case.status = 'PASS' if tools_match else 'FAIL'

    # 2. LLM Judging — 呈現品質與事實正確性分開評，兩者刻意正交：
    #    格式漂亮但數字錯的回覆，前者高分、後者低分。
    if judge:
        judgement = judge_test_case(case, api_key, model=judge_model)
        case.judgeScore = judgement["score"]
        case.judgeExplanation = judgement["explanation"]

        correctness = judge_answer_correctness(case, api_key, model=judge_model)
        case.answerScore = correctness["score"]
        case.answerExplanation = correctness["explanation"]

    return tools_match


def _execute_experiment(exp, verify_args, judge, judge_model, api_key, quiet=False, concurrency=1, timeout=120):
    """Run every test case in an experiment, mutate it in place, and persist it.

    Shared by `run` and `benchmark`; `quiet` collapses the per-case output to a
    single progress line, which is what the multi-model runs need.

    `concurrency` > 1 runs cases in a thread pool. Each case mints its own
    session, so they are independent. Keep it at 1 for backends that serialise
    requests -- a self-hosted model that queues will time out every case after
    the first one blocks.
    """
    total = len(exp.testCases)
    passed = 0

    if concurrency > 1:
        lock = threading.Lock()
        done = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(_run_case, case, exp, verify_args, judge, judge_model, api_key, timeout): case
                for case in exp.testCases
            }
            for fut in as_completed(futures):
                try:
                    matched = fut.result()
                except Exception as exc:
                    case = futures[fut]
                    case.status, case.actualTools = 'FAIL', 'Error'
                    case.actualAnswer = f"Error: {exc}"
                    matched = False
                with lock:
                    done += 1
                    if matched:
                        passed += 1
                    mark = typer.style("●", fg=typer.colors.GREEN if matched else typer.colors.RED)
                    typer.echo(f"\r  [{done}/{total}] {mark} ", nl=False)
        typer.echo()
        save_experiment_data(exp)
        return passed

    for i, case in enumerate(exp.testCases):
        if not quiet:
            typer.echo(f"[{i+1}/{total}] Q: {case.q}")

        tools_match = _run_case(case, exp, verify_args, judge, judge_model, api_key, timeout)
        if tools_match:
            passed += 1

        if quiet:
            mark = typer.style("●", fg=typer.colors.GREEN if tools_match else typer.colors.RED)
            typer.echo(f"\r  [{i+1}/{total}] {mark} ", nl=False)
            continue

        if tools_match:
            typer.secho("  ✅ Tools Match", fg=typer.colors.GREEN)
        else:
            typer.secho("  ❌ Tools Mismatch", fg=typer.colors.RED)

        if judge:
            color = typer.colors.GREEN if case.judgeScore >= 80 else (
                typer.colors.YELLOW if case.judgeScore >= 50 else typer.colors.RED)
            typer.secho(f"  ⚖️ Judge Score: {case.judgeScore}/100", fg=color, bold=True)
            typer.echo(f"     Reason: {case.judgeExplanation}")

        answer = case.actualAnswer or ""
        typer.echo(f"  A: {answer[:100]}..." if len(answer) > 100 else f"  A: {answer}")
        typer.echo("-" * 40)

    if quiet:
        typer.echo()

    save_experiment_data(exp)
    return passed


def _display_width(text):
    """Terminal columns a string occupies -- CJK glyphs take two."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text, width, align="<"):
    """Pad to a display width, so CJK labels line up in the tables below."""
    padding = " " * max(0, width - _display_width(text))
    return text + padding if align == "<" else padding + text


def _rate_color(rate):
    return typer.colors.GREEN if rate >= 80 else (
        typer.colors.YELLOW if rate >= 50 else typer.colors.RED
    )


def _print_metrics(exp, readonly_tools=None):
    """Render the tool-use metrics block shared by `run` and `stats`."""
    m = compute_metrics(exp, readonly_tools=readonly_tools)
    if not m["evaluated"]:
        typer.secho("尚未執行任何測試案例，無指標可計算。", fg=typer.colors.YELLOW)
        return m

    typer.secho("🛠️  TOOL-USE METRICS", fg=typer.colors.CYAN, bold=True)
    typer.secho(
        f"  正向題 {m['positive']}／負向題 {m['negative']}（共 {m['evaluated']} 已執行）",
        fg=typer.colors.BRIGHT_BLACK,
    )
    # Positive-only axes are None on an all-negative dataset; skip them.
    rows = []
    if m["call_rate"] is not None:
        rows.append(("有工具呼叫率", m["call_rate"], f"{m['called']}/{m['positive']}"))
    if m["name_rate"] is not None:
        rows.append(("函式名正確率", m["name_rate"], f"{m['name_hits']}/{m['scorable']}"))
    if m["arg_rate"] is not None:
        rows.append(("名稱+參數全對率", m["arg_rate"], f"{m['arg_hits']}/{m['scorable']}"))
    if m["efficiency"] is not None:
        rows.append(("呼叫工具次數吻合度", m["efficiency"], "步數貼近預期"))
    if m.get("abstain_rate") is not None:
        rows.append(("避免誤呼叫", m["abstain_rate"], f"{m['abstain_clean']}/{m['negative_count']} 負向題未誤呼叫"))
    if "readonly_rate" in m:
        rows.append(("唯讀遵循度", m["readonly_rate"], f"{m['readonly_clean']}/{m['evaluated']}"))
    if m["judge_avg"] is not None:
        rows.append(("呈現品質（judge）", m["judge_avg"], f"{m['judged']} 題已評分"))
    if m.get("answer_avg") is not None:
        rows.append(("答案正確率（judge）", m["answer_avg"], f"{m['answered']} 題已比對事實"))

    for label, rate, note in rows:
        bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
        typer.echo(f"  {_pad(label, 18)} ", nl=False)
        typer.secho(f"{bar} {rate:>5.1f}%", fg=_rate_color(rate), nl=False)
        typer.echo(f"  ({note})")

    # Surplus arguments are style, not error: shown as a note rather than a bar.
    if m.get("extra_arg_rate"):
        seen = ", ".join(f"{k}×{v}" for k, v in list(m["extra_args_seen"].items())[:5])
        typer.secho(
            f"  ℹ️  額外參數率 {m['extra_arg_rate']}%"
            f"（{m['extra_arg_cases']}/{m['arg_hits']} 題答對但多帶了參數：{seen}）",
            fg=typer.colors.BRIGHT_BLACK,
        )

    if m.get("readonly_violations"):
        offenders = ", ".join(f"{k}×{v}" for k, v in m["readonly_violations"].items())
        typer.secho(f"  ⚠️  呼叫到非唯讀工具：{offenders}", fg=typer.colors.YELLOW)

    typer.secho(
        "  正確率採子集判定：預期工具全部出現即算命中，額外的偵察呼叫不扣分。",
        fg=typer.colors.BRIGHT_BLACK,
    )
    return m


def _resolve_readonly_tools(mcp, header, token):
    """Fetch the MCP tool list and return the names flagged readOnlyHint."""
    if not mcp:
        return None

    headers = parse_header_args(header)
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")

    context = fetch_mcp_context(mcp, headers=headers)
    if context.startswith("Error") or context.startswith("Failed"):
        typer.secho(f"⚠️  無法取得 MCP 工具清單，略過唯讀遵循度：{context}", fg=typer.colors.YELLOW)
        return None

    readonly = extract_readonly_tools(context)
    typer.echo(f"🔒 從 MCP 取得 {len(readonly)} 個唯讀工具，將計算唯讀遵循度。")
    return readonly

# Create the Typer app
cli = typer.Typer(
    help="🤖 [bold cyan]ADEval - Agent Evaluation System for Google ADK[/bold cyan]",
    rich_markup_mode="rich"
)

@cli.command(name="ui")
def launch_ui(
    port: int = typer.Option(8080, "--port", "-p", help="Port to run the UI on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind the server to")
):
    """
    🚀 [bold green]Launch the ADEval Web Interface.[/bold green]
    """
    url = f"http://{host}:{port}"
    typer.secho(f"🚀 Starting ADEval UI at {url}", fg=typer.colors.CYAN, bold=True)
    uvicorn.run(app, host=host, port=port, log_level="info")

@cli.command(name="config")
def manage_config(
    url: str = typer.Option(None, "--url", help="Set default Agent API URL"),
    user: str = typer.Option(None, "--user", help="Set default User ID"),
    app: str = typer.Option(None, "--app", help="Set default App Name")
):
    """
    ⚙️  [bold]Manage global configuration.[/bold]
    """
    config = get_config()
    if url: config.apiUrl = url
    if user: config.userId = user
    if app: config.appName = app
    
    if url or user or app:
        save_config(config)
        typer.secho("✅ Configuration updated.", fg=typer.colors.GREEN)
    
    typer.echo("\n[ Current Configuration ]")
    typer.echo(f"  API URL:  {config.apiUrl}")
    typer.echo(f"  User ID:  {config.userId}")
    typer.echo(f"  App Name: {config.appName}")

@cli.command(name="list")
def list_exps():
    """
    📋 [bold blue]List all stored experiments.[/bold blue]
    """
    exps = list_experiments()
    if not exps:
        typer.echo("No experiments found.")
        return
    
    header = f"{'ID':<20} {'Name':<40} {'Cases':<8}"
    typer.secho(header, fg=typer.colors.MAGENTA, bold=True)
    typer.echo("-" * len(header))
    for exp in exps:
        case_count = len(exp.get('testCases', []))
        typer.echo(f"{exp['id']:<20} {exp['name']:<40} {case_count:<8}")

@cli.command(name="inspect")
def inspect_exp(exp_id: str):
    """
    🔍 [bold cyan]Inspect experiment details.[/bold cyan]
    """
    exp = get_experiment(exp_id)
    if not exp:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED)
        return
    
    typer.secho(f"Experiment: {exp.name} ({exp.id})", bold=True)
    typer.echo(f"API URL: {exp.apiUrl} | User: {exp.userId}")
    typer.echo("-" * 60)
    for i, c in enumerate(exp.testCases):
        typer.echo(f"{i+1}. Q: {c.q}")
        tools_str = c.expectedTools.replace('\n', ', ')
        typer.echo(f"   Expected Tools: {tools_str}")
        if c.status:
            color = typer.colors.GREEN if c.status == 'PASS' else typer.colors.RED
            typer.secho(f"   Status: {c.status}", fg=color)
        typer.echo("")

@cli.command(name="import")
def import_exp(
    file: str = typer.Argument(..., help="Path to the CSV file"),
    name: str = typer.Option(None, "--name", "-n", help="Name of the experiment")
):
    """
    📥 [bold green]Import an experiment from a CSV file.[/bold green]
    """
    if not os.path.exists(file):
        typer.secho(f"❌ Error: File '{file}' not found.", fg=typer.colors.RED)
        return
    
    config = get_config()
    exp_name = name or os.path.basename(file).split('.')[0]
    
    try:
        exp = import_csv(file, exp_name, config.apiUrl, config.userId, config.appName)
        typer.secho(f"✅ Imported experiment: {exp.name} ({exp.id})", fg=typer.colors.GREEN)
        typer.echo(f"   Total test cases: {len(exp.testCases)}")
    except Exception as e:
        typer.secho(f"❌ Import failed: {str(e)}", fg=typer.colors.RED)

@cli.command(name="export")
def export_exp(
    exp_id: str = typer.Argument(..., help="ID of the experiment"),
    output: str = typer.Option(None, "--output", "-o", help="Output CSV path")
):
    """
    📤 [bold blue]Export experiment results to CSV.[/bold blue]
    """
    exp = get_experiment(exp_id)
    if not exp:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED)
        return
    
    out_path = output or f"{exp.id}_results.csv"
    try:
        export_to_csv(exp, out_path)
        typer.secho(f"✅ Exported to: {out_path}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Export failed: {str(e)}", fg=typer.colors.RED)

@cli.command(name="test")
def quick_test(
    question: str = typer.Argument(..., help="The question to ask the agent"),
    app: str = typer.Option(None, "--app", help="Target App Name"),
    url: str = typer.Option(None, "--url", help="Agent API URL")
):
    """
    ⚡ [bold yellow]Quickly test a single question.[/bold yellow]
    """
    config = get_config()
    req = EvalRequest(
        app_name=app or config.appName,
        api_url=url or config.apiUrl,
        user_id=config.userId,
        question=question,
        state="{}"
    )
    
    typer.secho(f"🚀 Testing: {question}", fg=typer.colors.CYAN)
    result = run_single_test(req)
    
    typer.echo("-" * 40)
    typer.secho(f"🛠️  Tools Called:", bold=True)
    typer.echo(result.get("tools"))
    typer.echo("")
    typer.secho(f"📝 Agent Answer:", bold=True)
    typer.echo(result.get("answer"))

@cli.command(name="run")
def run_exp(
    exp_id: str = typer.Argument(..., help="The ID of the experiment to run"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full raw response on failure"),
    verify_args: bool = typer.Option(True, "--verify-args/--no-verify-args", help="Whether to verify tool arguments"),
    judge: bool = typer.Option(False, "--judge", help="Use Gemini as a judge to evaluate performance"),
    judge_model: str = typer.Option("gemini-3-flash-preview", "--judge-model", help="Gemini model to use for judging"),
    api_key: str = typer.Option(None, "--key", envvar="GEMINI_API_KEY", help="Gemini API Key for judging"),
    concurrency: int = typer.Option(1, "--concurrency", "-c", min=1, help="Cases to run in parallel. Keep at 1 for backends that serialise requests"),
    timeout: int = typer.Option(120, "--timeout", min=1, help="Seconds to wait for each /run call before giving up")
):
    """
    ▶️  [bold yellow]Run a specific experiment by ID.[/bold yellow]
    """
    exp = get_experiment(exp_id)
    if not exp:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)
    
    typer.secho(f"▶️  Running Experiment: {exp.name} ({exp.id})", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"🔗 API URL: {exp.apiUrl}")
    if judge:
        typer.secho(f"⚖️  LLM Judging enabled ({judge_model})", fg=typer.colors.MAGENTA)
    typer.echo("=" * 60)
    
    total = len(exp.testCases)
    passed = _execute_experiment(exp, verify_args, judge, judge_model, api_key, concurrency=concurrency, timeout=timeout)

    typer.echo("\n" + "=" * 60)
    typer.secho("📊 EXPERIMENT SUMMARY", fg=typer.colors.MAGENTA, bold=True)
    typer.echo(f"Total: {total} | Passed: {passed} | Failed: {total-passed}")
    pass_rate = (passed / total) * 100 if total > 0 else 0
    typer.secho(f"Pass Rate: {pass_rate:.2f}%", bold=True, reverse=True)
    typer.echo("-" * 60)
    _print_metrics(exp)
    typer.echo("=" * 60)

@cli.command(name="rejudge")
def rejudge_exp(
    exp_ids: List[str] = typer.Argument(..., help="One or more experiment IDs to re-judge"),
    judge_model: str = typer.Option("gemini-3-flash-preview", "--judge-model", help="Gemini model to use for judging"),
    api_key: str = typer.Option(None, "--key", envvar="GEMINI_API_KEY", help="Gemini API Key for judging")
):
    """
    ⚖️  [bold magenta]Re-run the LLM judge on stored answers, without calling the agents again.[/bold magenta]

    Useful after changing the judge prompt: it re-scores the answers already saved
    in each experiment, so the whole set can be brought onto one rubric cheaply.
    """
    if not api_key:
        typer.secho("❌ GEMINI_API_KEY is not set. Use --key or the environment variable.", fg=typer.colors.RED)
        raise typer.Exit(1)

    for exp_id in exp_ids:
        exp = get_experiment(exp_id)
        if not exp:
            typer.secho(f"❌ Experiment '{exp_id}' not found, skipping.", fg=typer.colors.RED)
            continue

        scored = [c for c in exp.testCases if c.actualAnswer is not None]
        if not scored:
            typer.secho(f"⚠️  {exp_id} 尚未執行過（沒有 actualAnswer），跳過。", fg=typer.colors.YELLOW)
            continue

        typer.secho(f"⚖️  Re-judging {exp.name} ({exp.id}) — {len(scored)} 題", fg=typer.colors.CYAN, bold=True)
        for i, case in enumerate(scored):
            judgement = judge_test_case(case, api_key, model=judge_model)
            case.judgeScore = judgement["score"]
            case.judgeExplanation = judgement["explanation"]
            color = typer.colors.GREEN if case.judgeScore >= 80 else (
                typer.colors.YELLOW if case.judgeScore >= 50 else typer.colors.RED)
            typer.echo(f"  [{i+1}/{len(scored)}] ", nl=False)
            typer.secho(f"{case.judgeScore:>3}/100", fg=color, nl=False)
            typer.echo(f"  {case.q[:50]}")

        save_experiment_data(exp)
        m = compute_metrics(exp)
        typer.secho(f"  → 呈現品質平均：{m['judge_avg']}/100\n", fg=typer.colors.MAGENTA, bold=True)


@cli.command(name="rescore")
def rescore_exp(
    exp_ids: List[str] = typer.Argument(..., help="One or more experiment IDs to re-score"),
    verify_args: bool = typer.Option(True, "--verify-args/--no-verify-args", help="Whether tool-arg equality decides PASS/FAIL")
):
    """
    ♻️  [bold magenta]Re-apply PASS/FAIL to stored answers, without calling the agents again.[/bold magenta]

    Useful after changing the comparison rules: the agents' recorded calls are
    re-compared, so an experiment run under older semantics can be brought onto
    the current ones without paying for another run.
    """
    for exp_id in exp_ids:
        exp = get_experiment(exp_id)
        if not exp:
            typer.secho(f"❌ Experiment '{exp_id}' not found, skipping.", fg=typer.colors.RED)
            continue

        scored = [c for c in exp.testCases if c.status]
        if not scored:
            typer.secho(f"⚠️  {exp_id} 尚未執行過，跳過。", fg=typer.colors.YELLOW)
            continue

        flipped = 0
        for case in scored:
            before = case.status
            case.status = 'PASS' if compare_tools(case.expectedTools, case.actualTools, verify_args=verify_args) else 'FAIL'
            if case.status != before:
                flipped += 1

        save_experiment_data(exp)
        passed = sum(1 for c in scored if c.status == 'PASS')
        typer.secho(
            f"♻️  {exp.name} ({exp.id}): {passed}/{len(scored)} PASS"
            f"（{flipped} 題判定改變）",
            fg=typer.colors.CYAN, bold=True,
        )


@cli.command(name="rescore-answers")
def rescore_answers(
    exp_ids: List[str] = typer.Argument(..., help="One or more experiment IDs to score for factual accuracy"),
    dataset: str = typer.Option(..., "--dataset", "-d", help="測資實驗 ID，提供 expectedAnswer 這份事實依據"),
    judge_model: str = typer.Option("gemini-3-flash-preview", "--judge-model", help="Gemini model to use for judging"),
    api_key: str = typer.Option(None, "--key", envvar="GEMINI_API_KEY", help="Gemini API Key for judging")
):
    """
    🎯  [bold magenta]Score factual accuracy on stored answers, without calling the agents again.[/bold magenta]

    跑分結果不帶 expectedAnswer（那是測資的欄位），所以先從 --dataset 指定的測資
    以題目文字對回去，再逐題比對模型回覆與工具真實回傳是否一致。
    """
    if not api_key:
        typer.secho("❌ GEMINI_API_KEY is not set. Use --key or the environment variable.", fg=typer.colors.RED)
        raise typer.Exit(1)

    source = get_experiment(dataset)
    if not source:
        typer.secho(f"❌ Dataset '{dataset}' not found.", fg=typer.colors.RED)
        raise typer.Exit(1)
    truth = {c.q: c.expectedAnswer for c in source.testCases if (c.expectedAnswer or "").strip()}
    typer.secho(f"📚 事實依據：{source.name}（{len(truth)}/{len(source.testCases)} 題有 expectedAnswer）",
                fg=typer.colors.BRIGHT_BLACK)

    for exp_id in exp_ids:
        exp = get_experiment(exp_id)
        if not exp:
            typer.secho(f"❌ Experiment '{exp_id}' not found, skipping.", fg=typer.colors.RED)
            continue

        scored = [c for c in exp.testCases if c.q in truth and c.actualAnswer is not None]
        if not scored:
            typer.secho(f"⚠️  {exp_id} 沒有可比對的題目，跳過。", fg=typer.colors.YELLOW)
            continue

        typer.secho(f"🎯 {exp.name} ({exp.id}) — {len(scored)} 題", fg=typer.colors.CYAN, bold=True)
        for i, case in enumerate(scored):
            case.expectedAnswer = truth[case.q]
            result = judge_answer_correctness(case, api_key, model=judge_model)
            case.answerScore = result["score"]
            case.answerExplanation = result["explanation"]
            score = case.answerScore if case.answerScore is not None else 0
            color = typer.colors.GREEN if score >= 80 else (
                typer.colors.YELLOW if score >= 50 else typer.colors.RED)
            typer.echo(f"  [{i+1}/{len(scored)}] ", nl=False)
            typer.secho(f"{score:>3}/100", fg=color, nl=False)
            typer.echo(f"  {case.q[:46]}")

        save_experiment_data(exp)
        m = compute_metrics(exp)
        typer.secho(f"  → 答案正確率：{m['answer_avg']}/100\n", fg=typer.colors.MAGENTA, bold=True)


@cli.command(name="stats")
def stats_exp(
    exp_id: str = typer.Argument(..., help="ID of the experiment"),
    mcp: str = typer.Option(None, "--mcp", "-m", help="MCP server URL, used to score read-only compliance"),
    header: Optional[List[str]] = typer.Option(None, "--header", "-H", help="Extra MCP header as 'Key: Value'"),
    token: str = typer.Option(None, "--token", envvar="MCP_AUTH_TOKEN", help="Bearer token for the MCP server"),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON instead of a table")
):
    """
    📊 [bold magenta]Show tool-use metrics for an already-executed experiment.[/bold magenta]
    """
    exp = get_experiment(exp_id)
    if not exp:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    readonly_tools = _resolve_readonly_tools(mcp, header, token)

    if json_out:
        typer.echo(json.dumps(compute_metrics(exp, readonly_tools), indent=2, ensure_ascii=False))
        return

    typer.secho(f"Experiment: {exp.name} ({exp.id})", bold=True)
    typer.echo("-" * 60)
    _print_metrics(exp, readonly_tools)


@cli.command(name="benchmark")
def benchmark_exp(
    exp_id: str = typer.Argument(..., help="ID of the experiment holding the dataset"),
    app: Optional[List[str]] = typer.Option(
        None, "--app", "-a",
        help="App (model) to benchmark. Repeat for each model; defaults to every app the Agent API exposes."
    ),
    verify_args: bool = typer.Option(False, "--verify-args/--no-verify-args", help="Whether tool-arg equality decides PASS/FAIL"),
    judge: bool = typer.Option(True, "--judge/--no-judge", help="Score presentation quality with an LLM judge"),
    judge_model: str = typer.Option("gemini-3-flash-preview", "--judge-model", help="Gemini model used for judging"),
    mcp: str = typer.Option(None, "--mcp", "-m", help="MCP server URL, used to score read-only compliance"),
    header: Optional[List[str]] = typer.Option(None, "--header", "-H", help="Extra MCP header as 'Key: Value'"),
    token: str = typer.Option(None, "--token", envvar="MCP_AUTH_TOKEN", help="Bearer token for the MCP server"),
    api_key: str = typer.Option(None, "--key", envvar="GEMINI_API_KEY", help="Gemini API Key for judging"),
    concurrency: int = typer.Option(1, "--concurrency", "-c", min=1, help="Cases to run in parallel. Keep at 1 for backends that serialise requests"),
    timeout: int = typer.Option(120, "--timeout", min=1, help="Seconds to wait for each /run call before giving up")
):
    """
    🕸️  [bold magenta]Run one dataset against several models and compare them.[/bold magenta]

    Each model runs as its own experiment named '<dataset> @ <app>', so the
    per-case traces stay inspectable in the UI and the radar chart can overlay them.
    """
    source = get_experiment(exp_id)
    if not source:
        typer.secho(f"❌ Error: Experiment '{exp_id}' not found.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    apps = list(app or [])
    if not apps:
        try:
            res = request_with_retry("GET", f"{source.apiUrl}/list-apps", timeout=10)
            apps = res.json()
        except Exception as e:
            typer.secho(f"❌ 無法從 {source.apiUrl}/list-apps 取得 app 清單：{e}", fg=typer.colors.RED)
            raise typer.Exit(1)

    if len(apps) < 2:
        typer.secho("⚠️  只有一個 app，比較意義有限。", fg=typer.colors.YELLOW)

    readonly_tools = _resolve_readonly_tools(mcp, header, token)

    typer.secho(f"🕸️  Benchmark: {source.name} ({len(source.testCases)} cases)", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"🔗 API URL: {source.apiUrl}")
    typer.echo(f"🤖 受測 app：{', '.join(apps)}")
    typer.echo("=" * 72)

    results = []
    for app_name in apps:
        # Fresh experiment per model: same questions, same expectations, new appName.
        run = Experiment(
            id='exp_' + uuid.uuid4().hex[:9],
            name=f"{source.name} @ {app_name}",
            userId=source.userId,
            apiUrl=source.apiUrl,
            testCases=[
                TestCase(
                    appName=app_name,
                    q=c.q,
                    expectedTools=c.expectedTools,
                    expectedAnswer=c.expectedAnswer,
                    state=c.state,
                )
                for c in source.testCases
            ],
        )

        typer.secho(f"\n▶️  {app_name}", fg=typer.colors.CYAN, bold=True)
        _execute_experiment(run, verify_args, judge, judge_model, api_key, quiet=True, concurrency=concurrency, timeout=timeout)
        metrics = compute_metrics(run, readonly_tools=readonly_tools)
        results.append({"app": app_name, "exp": run, "metrics": metrics})
        typer.echo(f"  → {run.id}  pass {metrics['pass_rate']}%  名稱 {metrics['name_rate']}%  參數 {metrics['arg_rate']}%")

    _print_benchmark_table(results)
    return results


def _print_benchmark_table(results):
    """Comparison table plus the radar profile each model scored."""
    typer.echo("\n" + "=" * 72)
    typer.secho("🕸️  MODEL COMPARISON", fg=typer.colors.MAGENTA, bold=True)
    typer.echo("=" * 72)

    axes = [(key, label) for key, label in RADAR_AXES
            if any(key in r["metrics"] for r in results)]

    width = max(len(r["app"]) for r in results) + 3
    label_w = 20
    header = _pad("指標", label_w) + "".join(f"{r['app']:>{width}}" for r in results)
    typer.secho(header, bold=True)
    typer.echo("-" * len(header))

    for key, label in axes:
        row = _pad(label, label_w)
        best = max((r["metrics"].get(key, 0) for r in results), default=0)
        typer.echo(row, nl=False)
        for r in results:
            val = r["metrics"].get(key)
            cell = "—" if val is None else f"{val:.1f}%"
            style = typer.style(f"{cell:>{width}}", fg=typer.colors.GREEN, bold=True) \
                if val is not None and val == best and len(results) > 1 else f"{cell:>{width}}"
            typer.echo(style, nl=False)
        typer.echo()

    typer.echo("-" * len(header))
    typer.echo(_pad("綜合（軸平均）", label_w), nl=False)
    scores = []
    for r in results:
        profile = radar_profile(r["metrics"])
        avg = sum(profile.values()) / len(profile) if profile else 0
        scores.append(avg)
    best_avg = max(scores) if scores else 0
    for r, avg in zip(results, scores):
        cell = f"{avg:.1f}%"
        style = typer.style(f"{cell:>{width}}", fg=typer.colors.GREEN, bold=True) \
            if avg == best_avg and len(results) > 1 else f"{cell:>{width}}"
        typer.echo(style, nl=False)
    typer.echo("\n")

    for r in results:
        if r["metrics"].get("readonly_violations"):
            offenders = ", ".join(f"{k}×{v}" for k, v in r["metrics"]["readonly_violations"].items())
            typer.secho(f"⚠️  {r['app']} 呼叫到非唯讀工具：{offenders}", fg=typer.colors.YELLOW)

    typer.secho("\n在 UI 的 BENCHMARK 分頁可以把這些實驗疊成雷達圖。", fg=typer.colors.BRIGHT_BLACK)

@cli.command(name="gendata")
def gendata(
    mcp: str = typer.Option(None, "--mcp", "-m", help="URL of an MCP server to fetch tools from"),
    header: Optional[List[str]] = typer.Option(
        None, "--header", "-H",
        help="Extra HTTP header for the MCP request, as 'Key: Value'. Repeatable."
    ),
    token: str = typer.Option(
        None, "--token", envvar="MCP_AUTH_TOKEN",
        help="Bearer token for the MCP server (shorthand for --header 'Authorization: Bearer ...')"
    ),
    num: int = typer.Option(5, "--num", "-n", help="Number of test cases to generate"),
    per_tool: int = typer.Option(None, "--per-tool", help="Generate N cases PER tool, covering every tool the MCP exposes"),
    no_tools: bool = typer.Option(False, "--no-tools", help="Generate NEGATIVE cases that should NOT trigger any tool"),
    name: str = typer.Option(None, "--name", help="Name of the experiment"),
    app: str = typer.Option(None, "--app", help="Target App Name for the experiment"),
    model: str = typer.Option("gemini-3-flash-preview", "--model", help="Gemini model to use for generation"),
    lang: str = typer.Option("zh-tw", "--lang", help="Language for generated questions (e.g., zh-tw, en)"),
    desc: str = typer.Option(None, "--desc", "--description", help="Additional description or instructions for generation"),
    tools: int = typer.Option(None, "--tools", help="Target number of tool calls per test case"),
    api_key: str = typer.Option(None, "--key", envvar="GEMINI_API_KEY", help="Gemini API Key")
):
    """
    🧠 [bold magenta]Generate test data using Gemini.[/bold magenta]

    Three modes:
      * default    — --num diverse cases across all tools
      * --per-tool — N cases for EACH tool, so every tool is covered
      * --no-tools — --num negative cases that should NOT call any tool
    """
    if not mcp:
        typer.secho("❌ Error: You must provide --mcp as a basis for generation.", fg=typer.colors.RED)
        raise typer.Exit(1)

    if not api_key:
        typer.secho("❌ Error: GEMINI_API_KEY is not set. Use --key or set the environment variable.", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        mcp_headers = parse_header_args(header)
    except ValueError as e:
        typer.secho(f"❌ {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)

    if token:
        mcp_headers.setdefault("Authorization", f"Bearer {token}")

    typer.echo(f"🌐 Fetching tools from MCP: {mcp}...")
    if mcp_headers:
        typer.echo(f"   Using headers: {', '.join(sorted(mcp_headers))}")
    context = fetch_mcp_context(mcp, headers=mcp_headers)

    if context.startswith("Error") or context.startswith("Failed"):
        typer.secho(f"❌ Failed to fetch tools from MCP: {context}", fg=typer.colors.RED)
        raise typer.Exit(1)

    config = get_config()
    target_app = app or config.appName

    try:
        if no_tools:
            typer.secho(f"🤖 Generating {num} NEGATIVE cases (should not call any tool)...", fg=typer.colors.CYAN)
            test_cases = generate_negative_cases(context, num, api_key, model=model, lang=lang, description=desc)
            default_name = "Generated negative cases"

        elif per_tool:
            mcp_tools = parse_mcp_tools(context)
            if not mcp_tools:
                typer.secho("❌ 無法從 MCP 解析出工具清單。", fg=typer.colors.RED)
                raise typer.Exit(1)
            typer.secho(
                f"🤖 Generating {per_tool} cases per tool × {len(mcp_tools)} tools "
                f"= {per_tool * len(mcp_tools)} cases...", fg=typer.colors.CYAN)
            test_cases = []
            for i, tool in enumerate(mcp_tools):
                tname = tool.get("name", f"tool_{i}")
                typer.echo(f"  [{i+1}/{len(mcp_tools)}] {tname} ", nl=False)
                try:
                    cases = generate_test_cases(
                        single_tool_context(tool), per_tool, api_key,
                        model=model, lang=lang, description=desc, num_tools=1)
                    # Pin the expected tool name so an occasional hallucination is caught.
                    for c in cases:
                        if tname.lower() not in c.expectedTools.lower():
                            c.expectedTools = f"{tname}()"
                    test_cases.extend(cases)
                    typer.secho(f"→ {len(cases)} 題", fg=typer.colors.GREEN)
                except Exception as e:
                    typer.secho(f"→ 失敗（{str(e)[:60]}）", fg=typer.colors.RED)
            default_name = "Generated per-tool coverage"

        else:
            typer.secho(f"🤖 Generating {num} cases ({model}, lang: {lang}, tools: {tools or 'auto'})...", fg=typer.colors.CYAN)
            test_cases = generate_test_cases(context, num, api_key, model=model, lang=lang, description=desc, num_tools=tools)
            default_name = "Generated from MCP"

        for tc in test_cases:
            tc.appName = target_app

        if not test_cases:
            typer.secho("❌ 沒有生成任何題目。", fg=typer.colors.RED)
            raise typer.Exit(1)

        exp = Experiment(
            id='exp_' + uuid.uuid4().hex[:9],
            name=name or default_name,
            userId=config.userId,
            apiUrl=config.apiUrl,
            testCases=test_cases
        )

        save_experiment_data(exp)
        typer.secho(f"✅ Successfully generated experiment: {exp.name} ({exp.id})", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"   Total test cases: {len(test_cases)}")

    except typer.Exit:
        raise
    except Exception as e:
        typer.secho(f"❌ Generation failed: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)

@cli.command(name="delete")
def delete_exp(exp_id: str):
    """
    🗑️  [bold red]Delete an experiment.[/bold red]
    """
    if delete_experiment_data(exp_id):
        typer.secho(f"🗑️ Deleted experiment: {exp_id}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"❌ Error: Experiment not found.", fg=typer.colors.RED)

@cli.callback()
def main():
    """
    🤖 **ADEval CLI Tool** - Agent Evaluation System for Google ADK.
    """
    pass

if __name__ == "__main__":
    cli()
