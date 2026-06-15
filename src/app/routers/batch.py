"""
SKV v4.5 — Batch endpoint (multiple actions in one request)
Accepts both: [...] and {"actions": [...]}
"""
from fastapi import APIRouter, HTTPException, Request
import time

router = APIRouter(prefix="/api/v4", tags=["batch"])

@router.post("/batch")
async def batch_execute(request: Request):
    body = await request.json()
    
    # Поддержка двух форматов
    if isinstance(body, list):
        actions = body
    elif isinstance(body, dict) and "actions" in body:
        actions = body["actions"]
    else:
        raise HTTPException(status_code=422, detail="Expected a list of actions or {\"actions\": [...]}")
    
    if not isinstance(actions, list):
        raise HTTPException(status_code=422, detail="'actions' must be a list")
    
    results = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            results.append({"index": i, "status": "error", "error": "Action must be an object"})
            continue
        
        action_type = action.get("type", "")
        data = action.get("data", {})
        
        try:
            if action_type == "save_session":
                from app.routers.v4_personal_memory import save_session
                result = await save_session(
                    user_id=data.get("user_id", "unknown"),
                    session_id=data.get("session_id", "unknown"),
                    data=data.get("data", {}),
                    project_ref=data.get("project_ref", "general")
                )
                results.append({"index": i, "status": "ok", "result": result})
                
            elif action_type == "search":
                query = data.get("query", "")
                from app.routers.entries import search_cubes
                result = await search_cubes(query=query)
                results.append({"index": i, "status": "ok", "result": result})
                
            elif action_type == "feedback":
                cube_id = data.get("cube_id", "")
                vote = data.get("vote", "up")
                comment = data.get("comment", "")
                from app.routers.v4_graph import get_graph, _v4_graph
                get_graph()
                if cube_id in _v4_graph:
                    cube = _v4_graph[cube_id]
                    fb = cube.metadata.get("feedback", [])
                    fb.append({"vote": vote, "comment": comment, "timestamp": time.time()})
                    cube.metadata["feedback"] = fb
                    results.append({"index": i, "status": "ok", "result": {"feedback_added": cube_id}})
                else:
                    results.append({"index": i, "status": "error", "error": "Cube not found"})
                    
            elif action_type == "create_cube":
                from app.routers.memory_tools import core_memory_save
                result = await core_memory_save(data)
                results.append({"index": i, "status": "ok", "result": result})
                
            else:
                results.append({"index": i, "status": "error", "error": f"Unknown action type: {action_type}"})
                
        except Exception as e:
            results.append({"index": i, "status": "error", "error": str(e)})
    
    return {"executed": len(results), "results": results}
