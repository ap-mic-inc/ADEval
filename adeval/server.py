import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
import uuid
import os
import json
import urllib3
from typing import List, Optional, Any

app = FastAPI(title="ADEval Server")

def request_with_retry(method, url, **kwargs):
    """
    Perform an HTTP request with automatic SSL verification retry.
    If it fails due to SSL certificate verification, it retries with verify=False.
    """
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        # Suppress insecure request warnings only when we actually skip verification
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        kwargs["verify"] = False
        return requests.request(method, url, **kwargs)
    except Exception as e:
        raise e

# Data Directory Management
BASE_DIR = os.getcwd()
ADEVAL_DIR = os.path.join(BASE_DIR, ".adeval")
EXP_DIR = os.path.join(ADEVAL_DIR, "experiments")

def ensure_dirs():
    if not os.path.exists(ADEVAL_DIR):
        os.makedirs(ADEVAL_DIR)
    if not os.path.exists(EXP_DIR):
        os.makedirs(EXP_DIR)

ensure_dirs()

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

@app.get("/api/experiments")
def list_experiments():
    ensure_dirs()
    exps = []
    if os.path.exists(EXP_DIR):
        for f in os.listdir(EXP_DIR):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(EXP_DIR, f), "r", encoding="utf-8") as file:
                        exps.append(json.load(file))
                except Exception as e:
                    print(f"Failed to read {f}: {e}")
    return exps

@app.post("/api/experiments")
def save_experiment(exp: Experiment):
    ensure_dirs()
    file_path = os.path.join(EXP_DIR, f"{exp.id}.json")
    try:
        # Explicitly convert to dict and dump with ensure_ascii=False
        data = exp.model_dump() if hasattr(exp, "model_dump") else exp.dict()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Saved experiment {exp.id} successfully.")
        return {"status": "ok"}
    except Exception as e:
        print(f"Save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/experiments/{exp_id}")
def delete_experiment(exp_id: str):
    file_path = os.path.join(EXP_DIR, f"{exp_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Not found")

@app.get("/api/list-apps")
def list_apps(api_url: str):
    try:
        res = request_with_retry("GET", f"{api_url}/list-apps", timeout=5)
        data = res.json()
        return {"apps": data} if isinstance(data, list) else data
    except Exception as e:
        return {"apps": []}

@app.post("/api/run-test")
def run_test(req: EvalRequest):
    session_id = f"eval-{uuid.uuid4().hex[:8]}"
    
    # Parse state JSON string
    try:
        state_obj = json.loads(req.state) if req.state else {}
    except:
        state_obj = {}

    # 1. Create Session with State
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
        response = request_with_retry("POST", f"{req.api_url}/run", json=payload, timeout=45)
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
        return {"tools": "Error", "answer": f"API Error {response.status_code}", "raw_response": []}
    except Exception as e:
        return {"tools": "Error", "answer": str(e), "raw_response": []}

# Static files
static_path = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")