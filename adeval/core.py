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
    fieldnames = ['Question', 'Expected Tools', 'Actual Tools', 'Expected Answer', 'Actual Answer', 'Status', 'App Name']
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
                'App Name': c.appName
            })

def normalize_tool(tool_str: str) -> str:
    """
    Normalize a tool call string for comparison.
    Example: 'Add(b=1, a=2)' -> 'add(a=1, b=2)'
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
    
    # Split by comma
    args = [a.strip().lower() for a in args_content.split(",") if a.strip()]
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

# --- Generation Logic ---

def fetch_mcp_context(url: str) -> str:
    """
    Fetch tool definitions from an MCP server using the "Streamable HTTP" protocol.
    Correctly handles JSON-RPC responses returned via SSE stream in POST body.
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

    try:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"
        }
        
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
            session_id = r.headers.get("Mcp-Session-Id")
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            
            # For some servers, the init result might be useful, 
            # but we mostly need the session ID or to just complete the handshake.
            init_res = parse_sse_response(r)
        
        # 2. Request tools list
        list_rpc = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {}}
        
        with session.post(url, json=list_rpc, headers=headers, timeout=30, stream=True) as r:
            list_res = parse_sse_response(r)
            if list_res and "result" in list_res:
                return json.dumps(list_res["result"], indent=2, ensure_ascii=False)
            elif list_res and "error" in list_res:
                return f"MCP RPC Error: {json.dumps(list_res['error'])}"

        # 3. Fallback: Legacy SSE discovery
        with session.get(url, headers={"Accept": "text/event-stream"}, stream=True, timeout=10) as r:
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
        
        return f"Failed to get tools from {url}."

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
            return [TestCase(appName="DefaultAgent", q=f"API Error {response.status_code}: {response.text[:200]}", expectedTools="None")]
        
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
