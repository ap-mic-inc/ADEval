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
            
            return {
                "tools": "\n".join(tools_called) if tools_called else "None",
                "answer": " ".join(answer_parts).strip(),
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
            # Flexible mapping for column names
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
            # Simple tools match logic for export status
            expected_tools_list = set([t.strip() for t in c.expectedTools.split("\n") if t.strip()])
            actual_tools_list = set([t.strip() for t in (c.actualTools or "").split("\n") if t.strip()])
            status = "PASS" if expected_tools_list == actual_tools_list else "FAIL"
            if not c.actualTools: status = "PENDING"

            writer.writerow({
                'Question': c.q,
                'Expected Tools': c.expectedTools,
                'Actual Tools': c.actualTools or "",
                'Expected Answer': c.expectedAnswer,
                'Actual Answer': c.actualAnswer or "",
                'Status': status,
                'App Name': c.appName
            })
