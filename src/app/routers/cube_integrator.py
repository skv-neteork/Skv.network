"""Auto-integration: новый куб → Qdrant → связи с существующими."""
import numpy as np

def integrate_new_cube(cube_id: str, vector, graph: dict, qdrant_client, score_threshold=0.4, top_k=5):
    """Создать связи для нового куба через Qdrant."""
    if cube_id not in graph:
        return 0
    
    try:
        results = qdrant_client.query_points(
            collection_name="skv_rules_v2",
            query=vector.tolist() if hasattr(vector, 'tolist') else vector,
            limit=top_k + 1
        )
        
        if "connections" not in graph[cube_id]:
            graph[cube_id]["connections"] = {}
        
        links = 0
        for hit in results.points:
            target_id = str(hit.id)
            if target_id == cube_id or hit.score < score_threshold or target_id not in graph:
                continue
            
            weight = round(0.1 + (hit.score * 0.25), 3)
            graph[cube_id]["connections"][target_id] = weight
            
            if "connections" not in graph[target_id]:
                graph[target_id]["connections"] = {}
            graph[target_id]["connections"][cube_id] = round(weight * 0.5, 3)
            links += 1
        
        return links
    except Exception as e:
        print(f"[INTEGRATOR] Error: {e}")
        return 0
