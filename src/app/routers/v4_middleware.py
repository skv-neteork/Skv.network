"""SKV v4.0 Middleware — embedding cache only (no text memory)"""
import numpy as np
from fastapi import APIRouter

router = APIRouter()
_embedding_cache = {}

def get_embedding_cached(query):
    """Get embedding with cache."""
    cache_key = query[:100]
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]
    import json, urllib.request as req
    body = json.dumps({"model": "text-embedding-3-small", "input": query[:500]}).encode()
    r = req.Request("https://api.polza.ai/v1/embeddings", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"})
    resp = json.loads(req.urlopen(r, timeout=10).read())
    emb = np.array(resp["data"][0]["embedding"], dtype=np.float32)
    _embedding_cache[cache_key] = emb
    return emb

@router.get("/api/v4/stats")
async def v4_stats():
    return {'cache_size': len(_embedding_cache)}

@router.post("/api/v4/cache/clear")
async def clear_cache():
    _embedding_cache.clear()
    return {'cleared': True}

# Автоматический Hebbian cycle при импорте
from app.routers.v4_graph import get_graph
from app.routers.tensor_cube import hebbian_update

def run_hebbian_cycle():
    try:
        _graph = get_graph()
        if _graph:
            active_ids = list(_graph.keys())[:5]
            hebbian_update(_graph, active_ids)
            print(f"[V4] Hebbian updated {len(active_ids)} cubes", flush=True)
    except Exception as e:
        print(f"[V4] Hebbian error: {e}", flush=True)

run_hebbian_cycle()

