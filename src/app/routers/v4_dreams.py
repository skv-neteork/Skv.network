"""
SKV v4.5 — Dream Generator (Night Sleep Phase)
"""
import numpy as np
import time

async def generate_dreams(_v4_graph, top_n=3):
    pairs = []
    seen = set()
    for cid_a, cube_a in _v4_graph.items():
        for cid_b, weight in cube_a.connections.items():
            if cid_b in _v4_graph and cid_b != cid_a:
                key = tuple(sorted([cid_a, cid_b]))
                if key not in seen:
                    seen.add(key)
                    pairs.append((cid_a, cid_b, weight))
    
    pairs.sort(key=lambda x: x[2], reverse=True)
    top_pairs = pairs[:top_n]
    
    if not top_pairs:
        print("[DREAMS] No strong pairs found")
        return 0
    
    created = 0
    for cid_a, cid_b, weight in top_pairs:
        cube_a = _v4_graph[cid_a]
        cube_b = _v4_graph[cid_b]
        title_a = cube_a.metadata.get('title', cid_a[:30])
        title_b = cube_b.metadata.get('title', cid_b[:30])
        meta_name = f"Bridge: {title_a[:20]} + {title_b[:20]}"
        
        vec_a = np.array(cube_a.vector)
        vec_b = np.array(cube_b.vector)
        meta_vec = (vec_a + vec_b) / 2.0
        norm = np.linalg.norm(meta_vec)
        if norm > 0:
            meta_vec = (meta_vec / norm).tolist()
        
        meta_id = f"dream_{int(time.time())}_{cid_a[:8]}"
        from app.routers.v4_graph import TensorCube
        meta_cube = TensorCube(
            cube_id=meta_id, vector=meta_vec,
            metadata={"title": f"🧬 {meta_name}", "content": f"Bridge: {title_a} + {title_b}",
                      "importance": 0.6, "dream_generated": True, "parents": [cid_a, cid_b]}
        )
        meta_cube.energy = 0.5
        meta_cube.connections[cid_a] = 0.8
        meta_cube.connections[cid_b] = 0.8
        _v4_graph[cid_a].connections[meta_id] = 0.7
        _v4_graph[cid_b].connections[meta_id] = 0.7
        _v4_graph[meta_id] = meta_cube
        
        print(f"[DREAM] Created: {meta_id} — {meta_name}")
        created += 1
    
    print(f"[DREAMS] Generated {created} meta-concepts")
    return created
