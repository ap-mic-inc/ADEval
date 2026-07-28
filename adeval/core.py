import os
import ast
import json
import uuid
import requests
import urllib3
import csv
from typing import List, Optional, Any, Dict
from pydantic import BaseModel

# --- Models ---

class TestCase(BaseModel):
    appName: str
    q: str
    expectedTools: Optional[str] = ""
    expectedAnswer: Optional[str] = ""
    state: Optional[str] = "{}"
    status: Optional[str] = None
    actualTools: Optional[str] = None
    actualAnswer: Optional[str] = None
    rawResponse: Optional[List[Any]] = None
    judgeScore: Optional[int] = None
    judgeExplanation: Optional[str] = None
    # Factual accuracy, judged separately from presentation: does the reply match
    # what the tools actually returned? expectedAnswer holds that ground truth.
    answerScore: Optional[int] = None
    answerExplanation: Optional[str] = None

class Experiment(BaseModel):
    id: str
    name: str
    userId: str
    apiUrl: str
    testCases: List[TestCase]

class EvalRequest(BaseModel):
    app_name: str
    api_url: str
    user_id: str
    question: str
    state: Optional[str] = "{}"
    timeout: int = 120  # seconds to wait for /run; slow tools need more headroom

class GlobalConfig(BaseModel):
    apiUrl: str = "http://localhost:8000"
    userId: str = "default_user"
    appName: str = "DefaultAgent"

# --- Logic ---

BASE_DIR = os.getenv("ADEVAL_DATA_DIR", os.getcwd())
ADEVAL_DIR = os.path.join(BASE_DIR, ".adeval")
EXP_DIR = os.path.join(ADEVAL_DIR, "experiments")
CONFIG_FILE = os.path.join(ADEVAL_DIR, "config.json")

def ensure_dirs():
    if not os.path.exists(ADEVAL_DIR):
        os.makedirs(ADEVAL_DIR)
    if not os.path.exists(EXP_DIR):
        os.makedirs(EXP_DIR)

def get_config() -> GlobalConfig:
    ensure_dirs()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return GlobalConfig(**json.load(f))
        except:
            pass
    return GlobalConfig()

def save_config(config: GlobalConfig):
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=4)

def request_with_retry(method, url, **kwargs):
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        kwargs["verify"] = False
        return requests.request(method, url, **kwargs)
    except Exception as e:
        raise e

def list_experiments():
    ensure_dirs()
    exps = []
    if os.path.exists(EXP_DIR):
        for f in os.listdir(EXP_DIR):
            if f.endswith(".json"):
                try:
                    file_path = os.path.join(EXP_DIR, f)
                    with open(file_path, "r", encoding="utf-8") as file:
                        data = json.load(file)
                        stat = os.stat(file_path)
                        created_at = getattr(stat, 'st_birthtime', stat.st_mtime)
                        data['_created_at'] = created_at
                        exps.append(data)
                except Exception as e:
                    print(f"Failed to read {f}: {e}")
    exps.sort(key=lambda x: x.get('_created_at', 0), reverse=True)
    return exps

def get_experiment(exp_id: str) -> Optional[Experiment]:
    file_path = os.path.join(EXP_DIR, f"{exp_id}.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return Experiment(**json.load(f))
    return None

def save_experiment_data(exp: Experiment):
    ensure_dirs()
    file_path = os.path.join(EXP_DIR, f"{exp.id}.json")
    data = exp.model_dump() if hasattr(exp, "model_dump") else exp.dict()
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def delete_experiment_data(exp_id: str):
    file_path = os.path.join(EXP_DIR, f"{exp_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        return True
    return False

# Keys different models use to name the tool and carry its arguments when they
# emit a call as text JSON rather than a proper functionCall.
_NAME_KEYS = ("function", "name", "tool", "tool_name", "function_name")
_ARG_KEYS = ("arguments", "args", "parameters", "params", "input")


def _tool_call_from_dict(item: Dict[str, Any]) -> Optional[str]:
    """Render a text-JSON tool call as the `name(arg="value")` form used elsewhere.

    Handles both shapes seen in practice: arguments nested under an `arguments`
    key, and arguments flattened alongside the tool name.
    """
    name = next((item[k] for k in _NAME_KEYS if isinstance(item.get(k), str)), None)
    if not name:
        return None

    args: Dict[str, Any] = {}
    for key in _ARG_KEYS:
        value = item.get(key)
        if isinstance(value, dict):
            args = value
            break
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                args = parsed
                break
    else:
        # Flattened form: everything that is not the name or a wrapper key is an argument.
        args = {k: v for k, v in item.items()
                if k not in _NAME_KEYS and k not in _ARG_KEYS}

    rendered = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
    return f"{name}({rendered})"


def run_single_test(req: EvalRequest):
    session_id = f"eval-{uuid.uuid4().hex[:8]}"
    try:
        state_obj = json.loads(req.state) if req.state else {}
    except:
        state_obj = {}

    # Create Session
    create_url = f"{req.api_url}/apps/{req.app_name}/users/{req.user_id}/sessions/{session_id}"
    try:
        request_with_retry("POST", create_url, json=state_obj, timeout=10)
    except: pass

    payload = {
        "appName": req.app_name,
        "userId": req.user_id,
        "sessionId": session_id,
        "newMessage": {"role": "user", "parts": [{"text": req.question}]},
        "streaming": False
    }
    
    try:
        response = request_with_retry("POST", f"{req.api_url}/run", json=payload, timeout=req.timeout)
        if response.status_code == 200:
            events = response.json()
            tools_called = []
            answer_parts = []
            for event in events:
                content = event.get("content")
                if content and "parts" in content:
                    for part in content["parts"]:
                        if "functionCall" in part:
                            fcall = part["functionCall"]
                            name = fcall.get("name", "unknown")
                            args = fcall.get("args", {})
                            # JSON-encode values so a string containing commas stays
                            # quoted and survives the round-trip through normalize_tool.
                            arg_str = ", ".join(
                                [f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()]
                            )
                            tools_called.append(f"{name}({arg_str})")
                        # Reasoning models (gemma-4 via LiteLLM, and Gemini with thinking
                        # enabled) emit their chain of thought as text parts flagged
                        # thought=True. Those are not the answer: folding them in buries
                        # the real reply -- one case had 3,235 characters of English
                        # reasoning around a 182-character Chinese conclusion, which the
                        # judge scored 10/100. Models that do not expose thought parts
                        # would otherwise be judged on a different basis entirely.
                        if "text" in part and event.get("author") != "user" and not part.get("thought"):
                            answer_parts.append(part["text"])
            
            full_answer = " ".join(answer_parts).strip()
            
            # If no formal tool calls were detected, try to extract from text
            if not tools_called and full_answer:
                # Look for common tool patterns like ToolName(args)
                import re
                # Pattern 1: Markdown JSON block
                json_match = re.search(r'```json\s*(\[.*?\])\s*```', full_answer, re.DOTALL)
                if json_match:
                    try:
                        extracted = json.loads(json_match.group(1))
                        for item in extracted:
                            if isinstance(item, str):
                                tools_called.append(item)
                            elif isinstance(item, dict):
                                # Models that were not fine-tuned for function calling
                                # often know exactly which tool and arguments to use, but
                                # emit them as text JSON instead of a functionCall part.
                                # Skipping those would score them 0% on tool use and hide
                                # the very difference a base-vs-fine-tuned comparison is
                                # meant to measure.
                                call = _tool_call_from_dict(item)
                                if call:
                                    tools_called.append(call)
                    except: pass
                
                # Pattern 2: Generic ToolName(...) in text
                if not tools_called:
                    generic_matches = re.findall(r'(\w+)\((.*?)\)', full_answer)
                    for m in generic_matches:
                        tools_called.append(f"{m[0]}({m[1]})")

            return {
                "tools": "\n".join(tools_called) if tools_called else "None",
                "answer": full_answer,
                "raw_response": events
            }
        
        error_detail = response.text[:500]
        try:
            json_error = response.json()
            if isinstance(json_error, dict) and "detail" in json_error:
                error_detail = json_error["detail"]
        except: pass
        
        return {
            "tools": "Error", 
            "answer": f"API Error {response.status_code}: {error_detail}", 
            "raw_response": []
        }
    except requests.exceptions.Timeout:
        return {"tools": "Error", "answer": "Request Timeout", "raw_response": []}
    except Exception as e:
        return {"tools": "Error", "answer": f"Connection Error: {str(e)}", "raw_response": []}

def import_csv(file_path: str, name: str, api_url: str, user_id: str, app_name: str) -> Experiment:
    test_cases = []
    with open(file_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = row.get('Question') or row.get('q') or row.get('question')
            expected_tools = row.get('Expected Tools') or row.get('expectedTools') or row.get('tools', "")
            expected_answer = row.get('Expected Answer') or row.get('expectedAnswer') or row.get('answer', "")
            target_app = row.get('App Name') or row.get('appName') or app_name
            
            if q:
                test_cases.append(TestCase(
                    appName=target_app,
                    q=q,
                    expectedTools=expected_tools,
                    expectedAnswer=expected_answer,
                    state="{}"
                ))
    
    exp = Experiment(
        id='exp_' + uuid.uuid4().hex[:9],
        name=name,
        userId=user_id,
        apiUrl=api_url,
        testCases=test_cases
    )
    save_experiment_data(exp)
    return exp

def export_to_csv(exp: Experiment, output_path: str):
    fieldnames = ['Question', 'Expected Tools', 'Actual Tools', 'Expected Answer', 'Actual Answer', 'Status', 'App Name', 'Judge Score', 'Judge Explanation']
    with open(output_path, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in exp.testCases:
            writer.writerow({
                'Question': c.q,
                'Expected Tools': c.expectedTools,
                'Actual Tools': c.actualTools or "",
                'Expected Answer': c.expectedAnswer,
                'Actual Answer': c.actualAnswer or "",
                'Status': c.status or "PENDING",
                'App Name': c.appName,
                'Judge Score': c.judgeScore if c.judgeScore is not None else "",
                'Judge Explanation': c.judgeExplanation or ""
            })

def _split_top_level(args_content: str) -> List[str]:
    """Split an argument list on top-level commas only.

    Quotes and brackets are respected, so a value that itself contains commas --
    a judicial id like "CPEV,115,竹北簡,57" or a nested dict -- stays in one piece
    instead of being shredded into separate arguments.
    """
    parts, buf, depth, quote = [], [], 0, None
    for ch in args_content:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _canonical_value(raw: str) -> str:
    """Canonical form of a single argument value.

    Tries JSON then Python literals, so the same dict written by the dataset
    ({"a": 1}) and rendered from the event stream ({'a': 1}) collapse onto one
    string. Falls back to the bare unquoted text.
    """
    raw = raw.strip()
    for parse in (json.loads, ast.literal_eval):
        try:
            obj = parse(raw)
        except Exception:
            continue
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, ensure_ascii=False, sort_keys=True).lower()
        if isinstance(obj, float) and obj.is_integer():
            obj = int(obj)  # 2.0 and 2 are the same argument
        # Scalars compare as text: a dataset writing year=2024 and a model
        # returning "2024" mean the same argument.
        return str(obj).lower()
    return raw.strip('"\'').lower()


def normalize_tool(tool_str: str) -> str:
    """
    Normalize a tool call string for comparison.
    Example: 'Add(b="1", a=2)' -> 'add(a=2, b=1)'
    """
    tool_str = tool_str.strip()
    if "(" not in tool_str:
        return tool_str.lower()

    name_part, arg_part = tool_str.split("(", 1)
    name = name_part.strip().lower()

    args_content = arg_part.rstrip()
    if args_content.endswith(")"):
        args_content = args_content[:-1]
    args_content = args_content.strip()
    if not args_content:
        return name

    args = []
    for arg in _split_top_level(args_content):
        if "=" in arg:
            key, value = arg.split("=", 1)
            args.append(f"{key.strip().lower()}={_canonical_value(value)}")
        else:
            args.append(_canonical_value(arg))
    args.sort()

    return f"{name}({', '.join(args)})"


def _tool_signature(tool_str: str):
    """Split a call into (name, {argument: canonical value})."""
    tool_str = tool_str.strip()
    if "(" not in tool_str:
        return tool_str.lower(), {}

    name_part, arg_part = tool_str.split("(", 1)
    arg_part = arg_part.rstrip()
    if arg_part.endswith(")"):
        arg_part = arg_part[:-1]

    args = {}
    for arg in _split_top_level(arg_part.strip()):
        if "=" in arg:
            key, value = arg.split("=", 1)
            args[key.strip().lower()] = _canonical_value(value)
    return name_part.strip().lower(), args


def call_covers(expected: str, actual: str) -> bool:
    """Whether an actual call satisfies an expected one.

    Same tool, and every expected argument present with an equal value. Extra
    arguments are allowed: a model that passes limit=50 alongside the required
    arguments is still using the tool correctly, so failing it would measure
    verbosity rather than capability. What it added is reported separately by
    extra_args().
    """
    exp_name, exp_args = _tool_signature(expected)
    act_name, act_args = _tool_signature(actual)
    if exp_name != act_name:
        return False
    return all(k in act_args and act_args[k] == v for k, v in exp_args.items())


def extra_args(expected: str, actual: str) -> List[str]:
    """Arguments the actual call carried beyond those expected."""
    _, exp_args = _tool_signature(expected)
    _, act_args = _tool_signature(actual)
    return sorted(k for k in act_args if k not in exp_args)


# Tokens that mean "no tool", not a tool literally named that. A negative test
# case carries expectedTools="None"; the runner writes actualTools="None" when the
# model made no call and "Error" when the request never reached the agent. Treating
# any of these as a real tool would make a correctly-abstaining model score as a miss.
_NO_TOOL_TOKENS = {"", "none", "n/a", "-", "error"}


def _is_no_tool(value: Optional[str]) -> bool:
    """Whether an expected/actual tool string represents 'no tool call'."""
    tools = _split_tools(value)
    return not tools or all(t.split("(")[0].strip().lower() in _NO_TOOL_TOKENS for t in tools)


def compare_tools(expected_str: str, actual_str: str, verify_args: bool = True) -> bool:
    """
    Compare two sets of tool calls with SUBSET semantics: every expected call
    must be satisfied by some actual call. "None"/"Error"/empty are treated as
    no call, so a negative case (expectedTools="None") passes iff the model
    called nothing.

    Extra calls and extra arguments do not fail a case -- one more lookup, or an
    optional limit=, is legitimate agent behaviour rather than a wrong answer.
    Verbosity is scored separately: efficiency covers surplus calls and
    extra_arg_rate covers surplus arguments. This matches compute_metrics(), so
    PASS/FAIL and the metrics table can no longer disagree about the same case.
    """
    expected_list = [t for t in _split_tools(expected_str) if t.split("(")[0].strip().lower() not in _NO_TOOL_TOKENS]
    actual_list = [t for t in _split_tools(actual_str) if t.split("(")[0].strip().lower() not in _NO_TOOL_TOKENS]

    # Negative case: the model was supposed to call nothing at all.
    if not expected_list:
        return not actual_list

    if not verify_args:
        exp_names = {t.split("(")[0].strip().lower() for t in expected_list}
        act_names = {t.split("(")[0].strip().lower() for t in actual_list}
        return exp_names <= act_names

    return all(any(call_covers(e, a) for a in actual_list) for e in expected_list)

def _split_tools(value: Optional[str]) -> List[str]:
    return [t.strip() for t in (value or "").split("\n") if t.strip()]

def has_tool_call(case: TestCase) -> bool:
    """
    Whether a functionCall was actually parsed out of the agent's event stream.
    'None' means the model answered from its own knowledge; 'Error' means the
    request never reached the agent.
    """
    actual = (case.actualTools or "").strip()
    return bool(actual) and actual not in ("None", "Error")

def extract_readonly_tools(mcp_context: str) -> List[str]:
    """
    Pull the names of tools flagged `annotations.readOnlyHint` out of a
    tools/list payload (as returned by fetch_mcp_context).

    Used to score whether an agent stayed within read-only tools on a
    read-only dataset. Tools without the hint are treated as write-capable,
    which is the safe default.
    """
    try:
        data = json.loads(mcp_context)
    except (json.JSONDecodeError, ValueError):
        return []

    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        return []

    readonly = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        annotations = tool.get("annotations") or {}
        if isinstance(annotations, dict) and annotations.get("readOnlyHint"):
            name = tool.get("name")
            if name:
                readonly.append(name)
    return readonly


def parse_mcp_tools(mcp_context: str) -> List[Dict[str, Any]]:
    """Split a tools/list payload into a list of individual tool definitions."""
    try:
        data = json.loads(mcp_context)
    except (json.JSONDecodeError, ValueError):
        return []
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        return []
    return [t for t in tools if isinstance(t, dict) and t.get("name")]


def single_tool_context(tool: Dict[str, Any]) -> str:
    """Wrap one tool in the same tools/list shape generate_test_cases expects."""
    return json.dumps({"tools": [tool]}, indent=2, ensure_ascii=False)


def compute_metrics(exp: Experiment, readonly_tools: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Tool-use metrics for an experiment, scored with SUBSET semantics: a case
    counts as a hit when every expected tool appears among the actual calls.
    Extra calls (e.g. list_containers to resolve a name before acting) do not
    fail the case -- that is legitimate agent behaviour, not an error.

    This deliberately differs from compare_tools(), which requires set equality
    and therefore penalises correct-but-exploratory tool use.
    """
    evaluated = [c for c in exp.testCases if c.status]

    # Split positive (a tool is expected) from negative (expectedTools="None":
    # the model should NOT call anything). They are scored on different axes.
    positive = [c for c in evaluated if not _is_no_tool(c.expectedTools)]
    negative = [c for c in evaluated if _is_no_tool(c.expectedTools)]

    called = [c for c in positive if has_tool_call(c)]
    scorable = positive

    name_hits = 0
    arg_hits = 0
    extra_arg_cases = 0
    extra_args_seen: Dict[str, int] = {}
    efficiencies = []
    for case in scorable:
        expected = _split_tools(case.expectedTools)
        actual = _split_tools(case.actualTools)

        actual_names = {t.split("(")[0].strip().lower() for t in actual}
        if all(e.split("(")[0].strip().lower() in actual_names for e in expected):
            name_hits += 1

        # Subset semantics on arguments as well as on names: every expected
        # argument must be present and equal, but a surplus one (limit=50 on a
        # search) does not sink the case. Surplus is reported, not punished.
        if all(any(call_covers(e, a) for a in actual) for e in expected):
            arg_hits += 1
            surplus = set()
            for e in expected:
                for a in actual:
                    if call_covers(e, a):
                        surplus.update(extra_args(e, a))
                        break
            if surplus:
                extra_arg_cases += 1
                for key in surplus:
                    extra_args_seen[key] = extra_args_seen.get(key, 0) + 1

        # Call economy: how close the agent got to the expected number of calls.
        # Fewer calls than expected also scores below 1.0 -- it means the agent
        # skipped a step, not that it was efficient.
        if actual:
            efficiencies.append(min(len(expected), len(actual)) / max(len(expected), len(actual)))
        else:
            efficiencies.append(0.0)

    def pct(n: float, d: float) -> float:
        return round((n / d) * 100, 1) if d else 0.0

    judged = [c.judgeScore for c in exp.testCases if c.judgeScore is not None]
    answered = [c.answerScore for c in exp.testCases if c.answerScore is not None]

    metrics = {
        "total": len(exp.testCases),
        "evaluated": len(evaluated),
        "positive": len(positive),
        "negative": len(negative),
        "scorable": len(scorable),
        "passed": sum(1 for c in evaluated if c.status == "PASS"),
        "pass_rate": pct(sum(1 for c in evaluated if c.status == "PASS"), len(evaluated)),
        "called": len(called),
        # Positive-only axes are None on an all-negative dataset so they drop off
        # the radar / metrics table instead of showing a misleading 0%.
        # call_rate: on cases that expect a tool, did the model actually call one?
        "call_rate": pct(len(called), len(positive)) if positive else None,
        "name_hits": name_hits,
        "name_rate": pct(name_hits, len(scorable)) if scorable else None,
        "arg_hits": arg_hits,
        "arg_rate": pct(arg_hits, len(scorable)) if scorable else None,
        # Surplus arguments among the cases that got the expected ones right.
        # Informational: high verbosity is a style signal, not a failure.
        "extra_arg_cases": extra_arg_cases,
        "extra_arg_rate": pct(extra_arg_cases, arg_hits) if arg_hits else None,
        "extra_args_seen": dict(sorted(extra_args_seen.items(), key=lambda kv: -kv[1])),
        "efficiency": (round(sum(efficiencies) / len(efficiencies) * 100, 1) if efficiencies else 0.0) if positive else None,
        "judged": len(judged),
        "judge_avg": round(sum(judged) / len(judged), 1) if judged else None,
        "judge_rate": round(sum(judged) / len(judged), 1) if judged else 0.0,
        # Factual accuracy against the tools' real output. None when no case in the
        # experiment has been scored, so the axis drops off instead of showing 0%.
        "answered": len(answered),
        "answer_avg": round(sum(answered) / len(answered), 1) if answered else None,
        "answer_rate": round(sum(answered) / len(answered), 1) if answered else None,
    }

    # Abstention: on negative cases (no tool should be called), how often the
    # model correctly refrained. Only meaningful when negatives exist, so the
    # radar axis appears only for datasets that contain them.
    if negative:
        abstained = sum(1 for c in negative if not has_tool_call(c))
        metrics["negative_count"] = len(negative)
        metrics["abstain_clean"] = abstained
        metrics["abstain_rate"] = pct(abstained, len(negative))

    # Read-only compliance is only meaningful when the caller tells us which
    # tools are read-only (derived from the MCP server's readOnlyHint).
    if readonly_tools:
        allowed = {t.lower() for t in readonly_tools}
        clean = 0
        violations = {}
        for case in evaluated:
            used = {t.split("(")[0].strip().lower() for t in _split_tools(case.actualTools)}
            # "None"/"Error" mean no call happened, not a tool by that name. Counting
            # them as violations would penalise a failed request or an abstaining model.
            used -= _NO_TOOL_TOKENS

            # A write tool the case itself asked for is not a violation. Without this,
            # a dataset containing write cases penalises every model for doing exactly
            # what was requested -- three models all scored 48/60 here purely because
            # 12 cases expected insert/update/delete/execute_write.
            expected_tools = {t.split("(")[0].strip().lower() for t in _split_tools(case.expectedTools)}
            expected_tools -= _NO_TOOL_TOKENS

            offending = {t for t in used if t and t not in allowed and t not in expected_tools}
            if offending:
                for tool in offending:
                    violations[tool] = violations.get(tool, 0) + 1
            else:
                clean += 1
        metrics["readonly_clean"] = clean
        metrics["readonly_rate"] = pct(clean, len(evaluated))
        metrics["readonly_violations"] = dict(sorted(violations.items(), key=lambda kv: -kv[1]))

    return metrics


# Radar axes: (metrics key, display label). Every value is already 0-100.
# An axis is drawn only when the metric was computed (see radar_profile), so
# positive-only axes vanish on a negative dataset and abstain_rate appears only
# when negatives exist.
RADAR_AXES = [
    ("call_rate", "工具呼叫率"),
    ("name_rate", "函式名正確率"),
    ("arg_rate", "參數正確率"),
    ("judge_rate", "呈現品質"),
    ("answer_rate", "答案正確率"),
    ("efficiency", "呼叫工具次數吻合度"),
    ("readonly_rate", "唯讀遵循度"),
    ("abstain_rate", "避免誤呼叫"),
]


def radar_profile(metrics: Dict[str, Any]) -> Dict[str, float]:
    """Reduce a metrics dict to the radar axes, skipping ones that were not computed."""
    return {
        label: float(metrics[key])
        for key, label in RADAR_AXES
        if metrics.get(key) is not None and key in metrics
    }

# --- Generation Logic ---

def parse_header_args(values: Optional[List[str]]) -> Dict[str, str]:
    """
    Parse repeated 'Key: Value' strings (e.g. from --header) into a dict.
    Raises ValueError on malformed input so the caller can report it clearly.
    """
    headers: Dict[str, str] = {}
    for raw in values or []:
        if ":" not in raw:
            raise ValueError(
                f"Invalid header '{raw}'. Expected format: 'Key: Value' "
                "(e.g. 'Authorization: Bearer abc123')."
            )
        key, value = raw.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid header '{raw}'. Header name must not be empty.")
        headers[key] = value.strip()
    return headers


def fetch_mcp_context(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    """
    Fetch tool definitions from an MCP server using the "Streamable HTTP" protocol.
    Correctly handles JSON-RPC responses returned via SSE stream in POST body.

    `headers` are merged into every request, which is what MCP servers behind
    Bearer token / API key authentication require, e.g.
    {"Authorization": "Bearer <token>"}.
    """
    def parse_sse_response(resp):
        for line in resp.iter_lines():
            if not line: continue
            line_str = line.decode('utf-8')
            if line_str.startswith("data:"):
                data_val = line_str[5:].strip()
                try:
                    return json.loads(data_val)
                except:
                    continue
        return None

    auth_headers = dict(headers or {})

    def auth_error(status_code: int) -> str:
        if auth_headers:
            return (
                f"Error: MCP server returned {status_code} (authentication failed). "
                "The credentials passed via --header were rejected."
            )
        return (
            f"Error: MCP server returned {status_code} (authentication required). "
            "Pass credentials with --header, e.g. "
            "--header \"Authorization: Bearer <token>\"."
        )

    try:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"
        }
        headers.update(auth_headers)

        session = requests.Session()

        # 1. Initialize session
        init_rpc = {
            "jsonrpc": "2.0", "id": "init-1", "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "adeval", "version": "0.1.0"}
            }
        }

        with session.post(url, json=init_rpc, headers=headers, timeout=30, stream=True) as r:
            if r.status_code in (401, 403):
                return auth_error(r.status_code)

            session_id = r.headers.get("Mcp-Session-Id")
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            # For some servers, the init result might be useful,
            # but we mostly need the session ID or to just complete the handshake.
            init_res = parse_sse_response(r)

        # 2. Request tools list
        list_rpc = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {}}

        with session.post(url, json=list_rpc, headers=headers, timeout=30, stream=True) as r:
            if r.status_code in (401, 403):
                return auth_error(r.status_code)

            list_res = parse_sse_response(r)
            if list_res and "result" in list_res:
                return json.dumps(list_res["result"], indent=2, ensure_ascii=False)
            elif list_res and "error" in list_res:
                return f"MCP RPC Error: {json.dumps(list_res['error'])}"

        # 3. Fallback: Legacy SSE discovery
        sse_headers = {"Accept": "text/event-stream", **auth_headers}
        with session.get(url, headers=sse_headers, stream=True, timeout=10) as r:
            if r.status_code in (401, 403):
                return auth_error(r.status_code)

            if r.status_code == 200:
                for line in r.iter_lines():
                    if not line: continue
                    line_str = line.decode('utf-8')
                    if line_str.startswith("data:"):
                        data_val = line_str[5:].strip()
                        if "http" in data_val:
                            from urllib.parse import urljoin
                            post_url = urljoin(url, data_val)
                            with session.post(post_url, json=list_rpc, headers=headers, timeout=10, stream=True) as r2:
                                res = parse_sse_response(r2)
                                if res and "result" in res:
                                    return json.dumps(res["result"], indent=2, ensure_ascii=False)
                            break
        
        return (
            f"Failed to get tools from {url}. "
            "Check that the URL includes the MCP path (e.g. /mcp), that the server is "
            "running, and that any required credentials are passed via --header."
        )

    except Exception as e:
        return f"Error fetching MCP tools: {str(e)}"

def generate_test_cases(context: str, num_cases: int, api_key: str, model: str = "gemini-3-flash-preview", lang: str = "zh-tw", description: Optional[str] = None, num_tools: Optional[int] = None) -> List[TestCase]:
    """
    Uses Gemini API to generate test cases based on provided context (tools/docs).
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    extra_instructions = f"\n    Additional Context/Instructions:\n    {description}\n" if description else ""
    
    if num_tools == 1:
        tool_constraint = f"""
    STRICT CONSTRAINT: Each question MUST be solvable with EXACTLY ONE tool call. 
    DO NOT generate compound questions that require multiple steps (e.g., do NOT ask to 'search AND email', just 'search' or just 'email').
    The intent must be singular and direct.
    """
    elif num_tools and num_tools > 1:
        tool_constraint = f"""
    STRICT CONSTRAINT: Each question MUST require EXACTLY {num_tools} tool calls in a logical sequence.
    Design a scenario where the Agent must perform multiple steps to fulfill the request (e.g., 'find information X, then use it to do action Y').
    """
    else:
        tool_constraint = ""

    prompt = f"""
    You are an expert at creating test cases for AI Agents.
    Based on the following tool definitions or documentation, generate {num_cases} diverse and realistic test cases.
    
    STRICT RULES:
    1. ONLY use the tool names and argument structures defined in the Context below.
    2. DO NOT hallucinate or invent new tools. If a requested action (from the description) cannot be fulfilled by a tool in the Context, do NOT generate a test case for it.
    3. {tool_constraint}
    
    {extra_instructions}
    
    IMPORTANT: The 'question' MUST be written in {lang}.
    
    Context:
    {context}
    
    Format the output as a JSON list of objects. Each object MUST have:
    - 'question': A natural language question in {lang} that would trigger one or more tool calls based on the provided context.
    - 'expectedTools': The tool(s) expected to be called, in the format 'ToolName(arg1=val1, arg2=val2)'. 
      If multiple tools are expected, separate them with newlines.
    
    Return ONLY the JSON array, no other text.
    """

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }

    try:
        response = requests.post(api_url, json=payload, timeout=60)
        if response.status_code != 200:
            # Do NOT turn this into a TestCase: it would be silently written into the
            # dataset as a bogus question and reported as a successful generation.
            raise RuntimeError(
                f"Gemini API error {response.status_code}: {response.text[:300]}"
            )

        result = response.json()
        
        content = result['candidates'][0]['content']['parts'][0]['text'].strip()
        # Clean up Markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        data = json.loads(content)
        
        test_cases = []
        # Ensure data is a list
        if isinstance(data, dict):
            # Sometimes LLM returns {"testCases": [...]}
            for key in ["testCases", "cases", "items"]:
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
        
        if not isinstance(data, list):
            raise ValueError(f"Gemini returned unexpected format: {type(data)}")

        for item in data:
            if not isinstance(item, dict): continue
            
            q = item.get('question', '')
            exp_tools = item.get('expectedTools', '')
            
            # Ensure expectedTools is a string
            if isinstance(exp_tools, list):
                exp_tools = "\n".join([str(t) for t in exp_tools])
            elif isinstance(exp_tools, dict):
                exp_tools = json.dumps(exp_tools, ensure_ascii=False)
            
            if q:
                test_cases.append(TestCase(
                    appName="DefaultAgent", 
                    q=str(q),
                    expectedTools=str(exp_tools),
                    state="{}"
                ))
        return test_cases
    except Exception as e:
        raise Exception(f"Failed to generate test cases via Gemini: {str(e)}")


def _call_gemini_json(prompt: str, api_key: str, model: str):
    """POST a prompt to Gemini in JSON mode and return the parsed payload."""
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    response = requests.post(api_url, json=payload, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:300]}")
    content = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if content.startswith("```json"):
        content = content[7:-3].strip()
    elif content.startswith("```"):
        content = content[3:-3].strip()
    return json.loads(content)


def generate_negative_cases(context: str, num_cases: int, api_key: str,
                            model: str = "gemini-3-flash-preview", lang: str = "zh-tw",
                            description: Optional[str] = None) -> List[TestCase]:
    """
    Generate NEGATIVE test cases: questions that should NOT trigger any tool.

    These probe whether a model over-eagerly calls tools when it shouldn't -- the
    agent is expected to answer from its own knowledge or make small talk. Every
    case gets expectedTools="None", so compare_tools() passes only when the model
    made no tool call at all.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    extra = f"\n    Additional context/instructions:\n    {description}\n" if description else ""
    prompt = f"""
    You are creating NEGATIVE test cases for an AI agent that has access to the tools listed below.
    Generate {num_cases} diverse questions a user might realistically ask this agent, but that
    should NOT trigger ANY of these tools. The agent is expected to answer directly from its own
    general knowledge, or respond conversationally -- NOT to call a tool.

    GOOD negative examples:
    - Conceptual / knowledge questions ("容器和映像檔有什麼差別？", "Docker 和虛擬機的差異是什麼？")
    - Greetings, thanks, small talk, opinion or advice questions
    - Questions about topics the tools cannot act on

    BAD (do NOT generate): anything that asks to list, inspect, create, modify, remove, or
    otherwise operate on real resources, since that would legitimately call a tool.
    {extra}
    IMPORTANT: The 'question' MUST be written in {lang}.

    Tools the agent has (these MUST NOT be called by any generated question):
    {context}

    Return ONLY a JSON array of objects, each with a single key 'question'. No other text.
    """

    try:
        data = _call_gemini_json(prompt, api_key, model)
        if isinstance(data, dict):
            for key in ["testCases", "cases", "items", "questions"]:
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError(f"Gemini returned unexpected format: {type(data)}")

        cases = []
        for item in data:
            q = item.get("question") if isinstance(item, dict) else (item if isinstance(item, str) else None)
            if q:
                cases.append(TestCase(appName="DefaultAgent", q=str(q), expectedTools="None", state="{}"))
        return cases
    except Exception as e:
        raise Exception(f"Failed to generate negative cases via Gemini: {str(e)}")


def judge_answer_correctness(case: TestCase, api_key: str,
                             model: str = "gemini-3-flash-preview") -> Dict[str, Any]:
    """Score FACTUAL ACCURACY: does the reply match what the tools really returned?

    expectedAnswer carries the ground truth -- the actual output of running the
    case's expectedTools against the live server. Judging by LLM rather than string
    comparison is what makes this work for every tool: describe_table, query_table
    and top_values have no single "correct number" to match on, but a model can
    still tell whether a reply faithfully reflects the data.

    Deliberately orthogonal to judge_test_case(): a well-formatted answer stating
    the wrong number should score high on presentation and low here.
    """
    if not api_key:
        return {"score": 0, "explanation": "Judge API key missing"}
    if not (case.expectedAnswer or "").strip():
        return {"score": None, "explanation": "無事實依據可比對"}

    is_negative = _is_no_tool(case.expectedTools)
    prompt = f"""You are checking whether an assistant's reply is FACTUALLY correct.

[User question]
{case.q}

[Ground truth — what the tools actually returned]
{case.expectedAnswer}

[Assistant's reply]
{case.actualAnswer}

Judge ONLY factual accuracy against the ground truth:
- Are the figures, names and facts in the reply consistent with the ground truth?
- Does it answer the question that was asked, using that data?
- Omitting detail is a partial answer, not a wrong one. Contradicting the data IS wrong.

IGNORE formatting, tone, structure and length entirely — those are scored elsewhere.
{"This case expected NO tool call, so a correct reply answers from general knowledge without inventing data." if is_negative else ""}

[Rubric]
- 0-20:   contradicts the data, or states figures that do not appear in it; also error/empty replies.
- 21-49:  partially right but with a material error or a wrong figure.
- 50-79:  correct as far as it goes, but omits a substantial part of the answer.
- 80-100: faithfully and completely reflects the ground truth.

[Output Format]
Return ONLY a JSON object:
{{
  "score": (integer 0-100),
  "reason": "Concise explanation in Traditional Chinese (zh-tw), focusing ONLY on factual accuracy."
}}
"""
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    try:
        response = requests.post(api_url, json=payload, timeout=30)
        if response.status_code != 200:
            return {"score": 0, "explanation": f"Judge API error: {response.status_code}"}
        candidate = response.json()["candidates"][0]
        parts = (candidate.get("content") or {}).get("parts")
        if not parts:
            # Non-STOP finish reasons (safety, MAX_TOKENS) come back without parts.
            return {"score": 0,
                    "explanation": f"Judge returned no content ({candidate.get('finishReason')})"}
        result = json.loads(parts[0]["text"].strip())
        return {"score": result.get("score", 0),
                "explanation": result.get("reason", "No reason provided")}
    except Exception as e:
        return {"score": 0, "explanation": f"Judge failed: {str(e)}"}


def judge_test_case(case: TestCase, api_key: str, model: str = "gemini-3-flash-preview") -> Dict[str, Any]:
    """
    Uses an LLM to score PRESENTATION QUALITY only: how clearly and helpfully the
    agent presented its final answer.

    Tool selection and argument correctness are deliberately NOT judged here --
    they are measured separately by compute_metrics (name / args accuracy), so
    folding them into the judge score would double-count them and make the radar
    axes overlap. This keeps the "呈現品質" axis orthogonal to the others.
    """
    if not api_key:
        return {"score": 0, "explanation": "Judge API key missing"}

    prompt = f"""
    You are an expert AI Quality Auditor focusing EXCLUSIVELY on PRESENTATION QUALITY.
    Your task is to judge how clearly and helpfully an AI Agent presented its final
    answer to the user. You are NOT judging which tools it called.

    [User's Question]
    {case.q}

    [Agent's Final Text Answer]
    {case.actualAnswer}

    [CRITICAL PRE-CHECK — Evaluate this FIRST before anything else]
    Does the Agent's Final Text Answer contain any of the following?
    - An error message (e.g., "Error", "Exception", "failed", "timeout")
    - A refusal or inability to answer (e.g., "無法", "抱歉我不知道", "I cannot", "I don't know", "sorry", "無法回答", "無法提供")
    - An empty or near-empty response

    If YES → There is no presentation to judge. Assign a score of 0-20.
    The reason MUST start with "【需排查】" and explain what went wrong and what should be investigated
    (e.g., tool misconfiguration, API error, missing permissions, or agent logic issue).

    [Evaluation Task — only if pre-check passes]
    Judge ONLY the presentation of the answer, on these dimensions:
    - Clarity & structure: is it easy to read? Are tables, lists, or sections used where they help?
    - Directness: does it actually answer what the user asked, without burying the point?
    - Professional tone and completeness of the presentation.

    Do NOT reward or penalise which tools were called — that is measured elsewhere.
    IGNORE the factual correctness of the data (the model's knowledge may be outdated);
    judge only how the answer is written and formatted.

    [Rubric]
    - Score 0-20:  error / refusal / empty response. Reason must start with "【需排查】".
    - Score 21-49: answers, but poorly organised — a wall of text, hard to read, or ignores an explicit format request.
    - Score 50-79: readable and mostly clear, but plain or slightly disorganised.
    - Score 80-100: clear, well-structured and professional; uses tables / lists / summaries appropriately.

    [Output Format]
    Return ONLY a JSON object:
    {{
      "score": (integer 0-100),
      "reason": "Concise explanation in Traditional Chinese (zh-tw) focusing ONLY on presentation and readability."
    }}
    """

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }

    try:
        response = requests.post(api_url, json=payload, timeout=30)
        if response.status_code == 200:
            res_json = response.json()
            content = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            result = json.loads(content)
            return {
                "score": result.get("score", 0),
                "explanation": result.get("reason", "No reason provided")
            }
        return {"score": 0, "explanation": f"Judge API error: {response.status_code}"}
    except Exception as e:
        return {"score": 0, "explanation": f"Judge failed: {str(e)}"}
