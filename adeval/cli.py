import typer
import uvicorn
import webbrowser
import os
import json
from .server import app
from .core import (
    BASE_DIR, list_experiments, get_experiment, run_single_test, 
    delete_experiment_data, EvalRequest, save_experiment_data,
    get_config, save_config, import_csv, export_to_csv, GlobalConfig,
    compare_tools
)

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
    verify_args: bool = typer.Option(True, "--verify-args/--no-verify-args", help="Whether to verify tool arguments")
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
    typer.echo("=" * 60)
    
    total = len(exp.testCases)
    passed = 0
    
    for i, case in enumerate(exp.testCases):
        typer.echo(f"[{i+1}/{total}] Q: {case.q}")
        req = EvalRequest(
            app_name=case.appName, api_url=exp.apiUrl, user_id=exp.userId,
            question=case.q, state=case.state
        )
        result = run_single_test(req)
        
        case.actualTools = result.get("tools", "")
        case.actualAnswer = result.get("answer", "")
        case.rawResponse = result.get("raw_response")
        
        # Use the new compare_tools logic
        tools_match = compare_tools(case.expectedTools, case.actualTools, verify_args=verify_args)
        
        if tools_match:
            typer.secho("  ✅ Tools Match", fg=typer.colors.GREEN)
            passed += 1
            case.status = 'PASS'
        else:
            typer.secho(f"  ❌ Tools Mismatch", fg=typer.colors.RED)
            typer.echo(f"     Expected: {case.expectedTools.splitlines()}")
            typer.echo(f"     Actual:   {case.actualTools.splitlines()}")
            case.status = 'FAIL'
        
        typer.echo(f"  A: {case.actualAnswer[:100]}..." if len(case.actualAnswer) > 100 else f"  A: {case.actualAnswer}")
        typer.echo("-" * 40)
    
    save_experiment_data(exp)
    
    typer.echo("\n" + "=" * 60)
    typer.secho("📊 EXPERIMENT SUMMARY", fg=typer.colors.MAGENTA, bold=True)
    typer.echo(f"Total: {total} | Passed: {passed} | Failed: {total-passed}")
    pass_rate = (passed / total) * 100 if total > 0 else 0
    typer.secho(f"Pass Rate: {pass_rate:.2f}%", bold=True, reverse=True)
    typer.echo("=" * 60)

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
