import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
import requests
import os
import json
from .core import (
    Experiment, EvalRequest, list_experiments, save_experiment_data, 
    delete_experiment_data, run_single_test, request_with_retry, 
    BASE_DIR, ensure_dirs
)

app = FastAPI(title="ADEval Server")

@app.get("/api/experiments")
def get_experiments():
    return list_experiments()

@app.post("/api/experiments")
def save_experiment(exp: Experiment):
    try:
        save_experiment_data(exp)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/experiments/{exp_id}")
def delete_experiment(exp_id: str):
    if delete_experiment_data(exp_id):
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
    return run_single_test(req)

@app.post("/api/run-sse-proxy")
async def run_sse_proxy(request: Request):
    data = await request.json()
    api_url = data.pop("apiUrl", "http://localhost:8000").rstrip("/")
    app_name = data.get("appName")
    user_id = data.get("userId")
    session_id = data.get("sessionId")
    
    target_url = f"{api_url}/run_sse"

    if app_name and user_id and session_id:
        create_session_url = f"{api_url}/apps/{app_name}/users/{user_id}/sessions/{session_id}"
        try:
            request_with_retry("POST", create_session_url, json={}, timeout=5)
        except: pass

    def generate():
        try:
            with requests.post(target_url, json=data, stream=True, timeout=60, verify=False) as r:
                if r.status_code == 200:
                    for line in r.iter_lines():
                        if line:
                            yield line + b"\n"
                else:
                    error_body = r.text[:200]
                    yield f"data: {json.dumps({'error': f'HTTP {r.status_code}: {error_body}'})}\n\n".encode()
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()

    return StreamingResponse(generate(), media_type="text/event-stream")

# Static files
static_path = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

ensure_dirs()
