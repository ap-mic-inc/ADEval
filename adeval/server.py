import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import requests
import os
import json
import uuid

load_dotenv()
from typing import List, Optional, Any, Dict
from .core import (
    Experiment, EvalRequest, list_experiments, save_experiment_data,
    delete_experiment_data, run_single_test, request_with_retry,
    BASE_DIR, ensure_dirs, TestCase, get_config, fetch_mcp_context,
    generate_test_cases, judge_test_case, get_experiment, compute_metrics,
    extract_readonly_tools, radar_profile, RADAR_AXES
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

@app.post("/api/generate")
async def generate_exp_api(req: Dict[str, Any]):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY not set on server")
    
    mcp_url = req.get("mcpUrl")
    num = req.get("num", 5)
    tools = req.get("tools")
    lang = req.get("lang", "zh-tw")
    desc = req.get("desc")
    app_name = req.get("appName")
    name = req.get("name")

    if not mcp_url:
        raise HTTPException(status_code=400, detail="mcpUrl is required")

    # Headers for MCP servers behind authentication. Accepts either an explicit
    # header map, or a bearer token shorthand (also readable from the environment
    # so the token never has to travel through the browser).
    mcp_headers = dict(req.get("mcpHeaders") or {})
    mcp_token = req.get("mcpToken") or os.getenv("MCP_AUTH_TOKEN")
    if mcp_token:
        mcp_headers.setdefault("Authorization", f"Bearer {mcp_token}")

    context = fetch_mcp_context(mcp_url, headers=mcp_headers)
    if context.startswith("Error") or context.startswith("Failed"):
        raise HTTPException(status_code=400, detail=context)
    
    try:
        test_cases = generate_test_cases(
            context, num, api_key, 
            lang=lang, description=desc, num_tools=tools
        )
        
        config = get_config()
        target_app = app_name or config.appName
        for tc in test_cases:
            tc.appName = target_app
            
        exp_name = name or f"Generated from UI ({uuid.uuid4().hex[:4]})"
        exp = Experiment(
            id='exp_' + uuid.uuid4().hex[:9],
            name=exp_name,
            userId=config.userId,
            apiUrl=config.apiUrl,
            testCases=test_cases
        )
        save_experiment_data(exp)
        return exp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/metrics")
def experiment_metrics(req: Dict[str, Any]):
    """
    Tool-use metrics for one or more experiments, computed by core.compute_metrics
    so the UI radar and the CLI can never disagree.

    Body: {"expIds": [...], "mcpUrl": optional, "mcpToken": optional}
    """
    exp_ids = req.get("expIds") or []
    if not exp_ids:
        raise HTTPException(status_code=400, detail="expIds is required")

    readonly_tools = None
    mcp_url = req.get("mcpUrl")
    if mcp_url:
        headers = dict(req.get("mcpHeaders") or {})
        mcp_token = req.get("mcpToken") or os.getenv("MCP_AUTH_TOKEN")
        if mcp_token:
            headers.setdefault("Authorization", f"Bearer {mcp_token}")
        context = fetch_mcp_context(mcp_url, headers=headers)
        if not (context.startswith("Error") or context.startswith("Failed")):
            readonly_tools = extract_readonly_tools(context)

    results = []
    for exp_id in exp_ids:
        exp = get_experiment(exp_id)
        if not exp:
            continue
        metrics = compute_metrics(exp, readonly_tools=readonly_tools)
        results.append({
            "id": exp.id,
            "name": exp.name,
            "appName": exp.testCases[0].appName if exp.testCases else "",
            "metrics": metrics,
            "radar": radar_profile(metrics),
        })

    return {
        "axes": [label for _, label in RADAR_AXES],
        "readonlyToolCount": len(readonly_tools) if readonly_tools else 0,
        "results": results,
    }


@app.post("/api/run-test")
def run_test(req: Dict[str, Any]):
    # Extract eval_req from data
    if "app_name" in req:
        # It's a direct EvalRequest
        eval_req = EvalRequest(**req)
        judge = False
        expected_tools = ""
    else:
        # It's a wrapped request with judge options
        eval_req_data = req.get("eval_req")
        if not eval_req_data:
            raise HTTPException(status_code=400, detail="Missing eval_req")
        eval_req = EvalRequest(**eval_req_data)
        judge = req.get("judge", False)
        expected_tools = req.get("expected_tools", "")
    
    result = run_single_test(eval_req)
    
    # Handle Judge logic
    api_key = os.getenv("GEMINI_API_KEY")
    if judge and api_key:
        case = TestCase(
            appName=eval_req.app_name,
            q=eval_req.question,
            actualTools=result.get("tools"),
            actualAnswer=result.get("answer"),
            expectedTools=expected_tools
        )
        judgement = judge_test_case(case, api_key)
        result["judgeScore"] = judgement["score"]
        result["judgeExplanation"] = judgement["explanation"]
        
    return result

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
