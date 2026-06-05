"""V4 Hybrid Search: Qdrant (Stage 1) → TensorCube (Stage 2)."""
import numpy as np
from app.routers.v4_graph import get_graph
from app.routers.tensor_cube import spread_activation

def hybrid_search(query_vector, top_k=50, max_depth=5):
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="skv_qdrant", port=6333)
        results = client.query_points(
            collection_name="skv_rules_v2",
            query=query_vector.tolist() if hasattr(query_vector, 'tolist') else query_vector,
            limit=top_k
        )
        
        _graph = get_graph()
        if not _graph:
            return []
        
        candidate_ids = [str(r.id) for r in results.points if hasattr(r, 'score') and r.score > 0.2]
        if not candidate_ids:
            return []
        
        best_id = candidate_ids[0]
        if best_id in _graph:
            activated = spread_activation(_graph[best_id], lambda cid: _graph.get(cid), max_depth=max_depth)
            top = sorted(activated.items(), key=lambda x: -x[1])[:5]
            return [{"id": cid, "title": _graph[cid].metadata.get("title", cid)[:60], "energy": round(energy, 3)} for cid, energy in top if cid in _graph]
        return []
    except Exception as e:
        print(f"[V4] Hybrid search error: {e}", flush=True)
        return []
