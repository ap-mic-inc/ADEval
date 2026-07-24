import os
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
        response = request_with_retry("POST", f"{req.api_url}/run", json=payload, timeout=120)
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
                            arg_str = ", ".join([f"{k}={v}" for k, v in args.items()])
                            tools_called.append(f"{name}({arg_str})")
                        if "text" in part and event.get("author") != "user":
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
                            if isinstance(item, str): tools_called.append(item)
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

    # Clean up arguments
    args_content = arg_part.replace(")", "").strip()
    if not args_content:
        return name

    # Split by comma and strip quotes from values
    def normalize_arg(a: str) -> str:
        a = a.strip().lower()
        if '=' in a:
            k, v = a.split('=', 1)
            v = v.strip().strip('"\'')
            return f"{k.strip()}={v}"
        return a

    args = [normalize_arg(a) for a in args_content.split(",") if a.strip()]
    args.sort()

    return f"{name}({', '.join(args)})"

def compare_tools(expected_str: str, actual_str: str, verify_args: bool = True) -> bool:
    """
    Compare two sets of tool calls.
    """
    expected_list = [t.strip() for t in expected_str.split("\n") if t.strip()]
    actual_list = [t.strip() for t in actual_str.split("\n") if t.strip()]
    
    if not verify_args:
        exp_names = {t.split("(")[0].strip().lower() for t in expected_list}
        act_names = {t.split("(")[0].strip().lower() for t in actual_list}
        return exp_names == act_names
    
    exp_normalized = {normalize_tool(t) for t in expected_list}
    act_normalized = {normalize_tool(t) for t in actual_list}

    return exp_normalized == act_normalized

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

def compute_metrics(exp: Experiment) -> Dict[str, Any]:
    """
    Tool-use metrics for an experiment, scored with SUBSET semantics: a case
    counts as a hit when every expected tool appears among the actual calls.
    Extra calls (e.g. list_containers to resolve a name before acting) do not
    fail the case -- that is legitimate agent behaviour, not an error.

    This deliberately differs from compare_tools(), which requires set equality
    and therefore penalises correct-but-exploratory tool use.
    """
    evaluated = [c for c in exp.testCases if c.status]
    called = [c for c in evaluated if has_tool_call(c)]
    scorable = [c for c in evaluated if _split_tools(c.expectedTools)]

    name_hits = 0
    arg_hits = 0
    for case in scorable:
        expected = _split_tools(case.expectedTools)
        actual = _split_tools(case.actualTools)

        actual_names = {t.split("(")[0].strip().lower() for t in actual}
        if all(e.split("(")[0].strip().lower() in actual_names for e in expected):
            name_hits += 1

        actual_full = {normalize_tool(t) for t in actual}
        if all(normalize_tool(e) in actual_full for e in expected):
            arg_hits += 1

    def pct(n: int, d: int) -> float:
        return round((n / d) * 100, 1) if d else 0.0

    judged = [c.judgeScore for c in exp.testCases if c.judgeScore is not None]

    return {
        "total": len(exp.testCases),
        "evaluated": len(evaluated),
        "scorable": len(scorable),
        "passed": sum(1 for c in evaluated if c.status == "PASS"),
        "pass_rate": pct(sum(1 for c in evaluated if c.status == "PASS"), len(evaluated)),
        "called": len(called),
        "call_rate": pct(len(called), len(evaluated)),
        "name_hits": name_hits,
        "name_rate": pct(name_hits, len(scorable)),
        "arg_hits": arg_hits,
        "arg_rate": pct(arg_hits, len(scorable)),
        "judged": len(judged),
        "judge_avg": round(sum(judged) / len(judged), 1) if judged else None,
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

def judge_test_case(case: TestCase, api_key: str, model: str = "gemini-3-flash-preview") -> Dict[str, Any]:
    """
    Uses Gemini as a judge to evaluate if the Agent's actual tools and answer
    effectively solved the user's question.
    """
    if not api_key:
        return {"score": 0, "explanation": "Judge API key missing"}

    prompt = f"""
    You are an expert AI Quality Auditor focusing on 'Tool Use' and 'Presentation Logic'.
    Your task is to judge if an AI Agent correctly acted on a user request based on its tool-calling behavior.

    [User's Question]
    {case.q}

    [Agent's Actual Tool Calls]
    {case.actualTools}

    [Agent's Final Text Answer]
    {case.actualAnswer}

    [CRITICAL PRE-CHECK — Evaluate this FIRST before anything else]
    Does the Agent's Final Text Answer contain any of the following?
    - An error message (e.g., "Error", "Exception", "failed", "timeout")
    - A refusal or inability to answer (e.g., "無法", "抱歉我不知道", "I cannot", "I don't know", "sorry", "無法回答", "無法提供")
    - An empty or near-empty response

    If YES → This is a CRITICAL FAILURE. Assign a score of 0-20 regardless of tool calls.
    The reason MUST start with "【需排查】" and explain what went wrong and what should be investigated
    (e.g., tool misconfiguration, API error, missing permissions, or agent logic issue).

    [Evaluation Task — only if pre-check passes]
    Analyze the Agent's performance focusing ONLY on the following two criteria:

    1. Tool Selection (60%): Did the Agent choose the most appropriate tool(s) for the user's request? Are the parameters logically derived from the question?
    2. Presentation Logic (40%): Did the Agent present the result in a clear, professional, and helpful format (e.g., using tables, lists, or summaries as requested)?

    CRITICAL INSTRUCTION: Ignore the 'Factual Correctness' of the data. Since the model's internal knowledge might be outdated, focus ONLY on whether it TRIED to call the right tools and if it FORMATTED the response correctly.

    [Rubric]
    - Score 0-20:  CRITICAL FAILURE — agent returned an error or refused to answer. Reason must start with "【需排查】".
    - Score 21-49: Called wrong/no tools, or completely ignored formatting requests.
    - Score 50-79: Correct tool choice but poor presentation, or slightly suboptimal tool choice.
    - Score 80-100: Perfect tool choice and excellent presentation format.

    [Output Format]
    Return ONLY a JSON object:
    {{
      "score": (integer 0-100),
      "reason": "Concise explanation in Traditional Chinese (zh-tw) focusing on tool logic and presentation style."
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
