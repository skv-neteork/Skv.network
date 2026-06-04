"""SKV v4.0 — Tensor API endpoints"""
from fastapi import APIRouter, HTTPException
import numpy as np
from app.routers.tensor_cube import TensorCube, spread_activation, hebbian_update

router = APIRouter(prefix="/api/v4", tags=["tensor"])

# In-memory cube storage (будет заменено на Qdrant)
import httpx, json as _json
_cubes = {}

async def _save_to_qdrant(cube):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.put(f"http://skv_qdrant:6333/collections/skv_v4/points",
                json={"points": [{"id": cube.cube_id, "vector": cube.vector.tolist(), "payload": {"connections": cube.connections, "metadata": cube.metadata}}]})
    except: pass

async def _load_from_qdrant(cube_id):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"http://skv_qdrant:6333/collections/skv_v4/points/{cube_id}")
            if r.status_code == 200:
                data = r.json()
                payload = data.get("result",{}).get("payload",{})
                return payload
    except: pass
    return None

@router.post("/cube")
async def create_cube(cube_id: str = None):
    cube = TensorCube(cube_id)
    _cubes[cube.cube_id] = cube
    return {"status": "created", "cube_id": cube.cube_id}

@router.get("/cube/{cube_id}")
async def get_cube(cube_id: str):
    cube = _cubes.get(cube_id)
    if not cube:
        raise HTTPException(404, "Cube not found")
    return {
        "cube_id": cube.cube_id,
        "connections": cube.get_top_connections(10),
        "stability": cube.metadata['stability'],
        "usage_count": cube.metadata['usage_count']
    }

@router.post("/search")
async def tensor_search(cube_id: str, max_depth: int = 3):
    cube = _cubes.get(cube_id)
    if not cube:
        raise HTTPException(404, "Cube not found")
    activated = spread_activation(cube, lambda id: _cubes.get(id), max_depth=max_depth)
    return {"activated": sorted(activated.items(), key=lambda x: -x[1])[:10]}

@router.post("/learn")
async def tensor_learn(payload: dict):
    active_ids = payload.get("active_ids", []) if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
    hebbian_update(_cubes, active_ids)
    return {"status": "learned", "active_cubes": len(active_ids)}
