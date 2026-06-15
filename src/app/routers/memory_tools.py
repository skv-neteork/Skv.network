"""Memory Tools API — агент сам управляет памятью (как Letta)."""

from fastapi import APIRouter, HTTPException
import json, os, time

router = APIRouter(prefix="/api/v4/memory", tags=["memory_tools"])

@router.post("/save")
async def core_memory_save(request: dict):
    """Агент решает: 'Это важно, сохранить в ядро'."""
    user_id = request.get("user_id", "anonymous")
    content = request.get("content", "")
    importance = request.get("importance", 0.8)
    
    # Сохраняем как важный куб
    from app.routers.v4_graph import _v4_graph, get_graph
    from app.routers.v4_graph import TensorCube
    from app.routers.v4_middleware import get_embedding_cached
    import numpy as np
    
    get_graph()
    
    cube_id = request.get("cube_id") or f"core_{user_id}_{int(time.time())}"
    vector = get_embedding_cached(content[:500])
    
    tc = TensorCube(cube_id, np.array(vector, dtype=np.float32), metadata={
        "title": content[:80],
        "rules": [content],
        "importance": importance,
        "cube_type": "OBJECT",
        "source": "agent-self-save",
        "pinned": True
    })
    
    _v4_graph[cube_id] = tc
    
    # Сохраняем в PostgreSQL
    try:
        import asyncpg, asyncio
        async def _save():
            conn = await asyncpg.connect("postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db")
            await conn.execute("""INSERT INTO cubes (cube_id, title, content, type, importance, embedding)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (cube_id) DO UPDATE SET content=$3, importance=$5, embedding=$6""" ,
                cube_id, content[:80], json.dumps({"text": content, "importance": importance, "is_constitutional": request.get("is_constitutional", False)}),
                request.get("type", "experience"), importance, vector)
            await conn.close()
        asyncio.run(_save())
    except Exception as e:
        print(f"[MEMORY] DB save error: {e}", flush=True)
    return {"status": "saved", "cube_id": cube_id}

@router.post("/update")
async def core_memory_update(request: dict):
    """Агент решает: 'Этот факт устарел, обновить'."""
    cube_id = request.get("cube_id", "")
    new_content = request.get("content", "")
    
    from app.routers.v4_graph import _v4_graph, get_graph
    get_graph()
    
    if cube_id not in _v4_graph:
        raise HTTPException(status_code=404, detail="Cube not found")
    
    # Обновляем куб (reconsolidation)
    cube = _v4_graph[cube_id]
    cube.metadata["rules"] = [new_content]
    cube.metadata["updated_at"] = time.time()
    cube.metadata["update_count"] = cube.metadata.get("update_count", 0) + 1
    
    return {"status": "updated", "cube_id": cube_id}

@router.post("/forget")
async def core_memory_forget(request: dict):
    """Агент решает: 'Это больше не актуально, забыть'."""
    cube_id = request.get("cube_id", "")
    
    from app.routers.v4_graph import _v4_graph, get_graph
    from app.routers.tensor_cube import cascade_delete_cube
    get_graph()
    
    if cube_id not in _v4_graph:
        raise HTTPException(status_code=404, detail="Cube not found")
    
    cascade_delete_cube(_v4_graph, cube_id)
    return {"status": "forgotten", "cube_id": cube_id}

@router.get("/search")
async def core_memory_search(user_id: str, query: str):
    """Агент ищет в своей памяти."""
    from app.routers.v4_personal_memory import load_context
    
    memory = await load_context(user_id, query)
    return memory

# ═══════════════════════════════════════════
# GET-эндпоинты для агентов без POST (web_extractor)
# ═══════════════════════════════════════════

@router.get("/save")
async def core_memory_save_get(user_id: str = "anonymous", content: str = "", importance: float = 0.8, cube_id: str = None):
    """GET-версия save для агентов без POST (web_extractor)"""
    from app.routers.v4_graph import _v4_graph, get_graph
    from app.routers.v4_middleware import get_embedding_cached
    from app.routers.tensor_cube import TensorCube
    import numpy as np, time
    
    get_graph()
    cid = cube_id or f"core_{user_id}_{int(time.time())}"
    vector = get_embedding_cached(content[:500])
    
    tc = TensorCube(cid, np.array(vector, dtype=np.float32), metadata={
        "title": content[:80],
        "content": content,
        "importance": importance,
        "source": "agent-get-save",
        "pinned": True
    })
    
    _v4_graph[cid] = tc
    return {"status": "saved", "cube_id": cid}


@router.get("/forget")
async def core_memory_forget_get(cube_id: str = ""):
    """GET-версия forget"""
    from app.routers.v4_graph import _v4_graph, get_graph
    get_graph()
    if cube_id in _v4_graph:
        del _v4_graph[cube_id]
        return {"status": "forgotten", "cube_id": cube_id}
    return {"status": "not_found", "cube_id": cube_id}

@router.get("/feedback")
async def core_memory_feedback_get(cube_id: str = "", vote: str = "up", comment: str = ""):
    """GET-версия feedback для агентов без POST"""
    from app.routers.v4_graph import _v4_graph, get_graph
    get_graph()
    
    if cube_id not in _v4_graph:
        return {"status": "not_found", "cube_id": cube_id}
    
    cube = _v4_graph[cube_id]
    feedback_list = cube.metadata.get("feedback", [])
    feedback_list.append({
        "vote": vote,
        "comment": comment,
        "timestamp": __import__("time").time()
    })
    cube.metadata["feedback"] = feedback_list
    
    # Нагрев/остужение куба
    if vote == "up":
        cube.activate(impulse=0.2)
    elif vote == "down":
        cube.activate(impulse=-0.15)
    
    return {
        "status": "feedback_added",
        "cube_id": cube_id,
        "vote": vote,
        "total_feedback": len(feedback_list)
    }
