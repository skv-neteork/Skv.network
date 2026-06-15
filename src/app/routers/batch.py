"""
SKV v4.5 — Batch endpoint (multiple actions in one request)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import time, uuid

router = APIRouter(prefix="/api/v4", tags=["batch"])

class BatchAction(BaseModel):
    type: str
    data: dict = {}

@router.post("/batch")
async def batch_execute(actions: List[BatchAction]):
    """Выполняет несколько действий за один запрос"""
    results = []
    
    for i, action in enumerate(actions):
        try:
            if action.type == "save_session":
                # Сохраняем сессию
                from app.routers.v4_personal_memory import save_session
                d = action.data; result = await save_session(user_id=d.get("user_id","unknown"), session_id=d.get("session_id","unknown"), data=d.get("data",{}), project_ref=d.get("project_ref","general"))
                results.append({"index": i, "status": "ok", "result": result})
                
            elif action.type == "create_cube":
                # Создаём куб
                from app.routers.memory_tools import core_memory_save
                result = await core_memory_save(action.data)
                results.append({"index": i, "status": "ok", "result": result})
                
            elif action.type == "feedback":
                # Ставим фидбэк
                cube_id = action.data.get("cube_id", "")
                vote = action.data.get("vote", "up")
                comment = action.data.get("comment", "")
                from app.routers.v4_graph import get_graph, _v4_graph
                get_graph()
                if cube_id in _v4_graph:
                    cube = _v4_graph[cube_id]
                    fb_list = cube.metadata.get("feedback", [])
                    fb_list.append({"vote": vote, "comment": comment, "timestamp": time.time()})
                    cube.metadata["feedback"] = fb_list
                    results.append({"index": i, "status": "ok", "result": {"feedback_added": cube_id}})
                else:
                    results.append({"index": i, "status": "error", "error": "Cube not found"})
                    
            elif action.type == "search":
                # Поиск кубов
                query = action.data.get("query", "")
                from app.routers.entries import search_cubes
                result = await search_cubes(query=query)
                results.append({"index": i, "status": "ok", "result": result})
                
            else:
                results.append({"index": i, "status": "error", "error": f"Unknown action type: {action.type}"})
                
        except Exception as e:
            results.append({"index": i, "status": "error", "error": str(e)})
    
    return {"executed": len(results), "results": results}
