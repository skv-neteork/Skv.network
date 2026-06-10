"""Sleep Cycle v4.2 — Nightly graph replay and reconsolidation."""

import asyncio
import random
import numpy as np
from datetime import datetime, timezone

async def nightly_sleep_cycle():
    """Ночной цикл: replay, pruning, reconsolidation, clustering."""
    print("[SLEEP] Starting nightly consolidation cycle...", flush=True)
    
    from app.routers.v4_graph import _v4_graph, get_graph
    get_graph()
    
    stats = {"replayed": 0, "pruned": 0, "reconsolidated": 0, "clustered": 0}
    
    for cube_id, cube in _v4_graph.items():
        # Пропускаем конституционные кубы
        if cube.metadata.get("is_constitutional"):
            continue
        
        # 1. REPLAY: усилить связи которые использовались сегодня
        usage = cube.metadata.get("usage_count", 0)
        if usage > 5:
            for neighbor_id in list(cube.connections.keys()):
                if neighbor_id in _v4_graph:
                    cube.connections[neighbor_id] = min(1.0, cube.connections[neighbor_id] * 1.1)
            stats["replayed"] += 1
        
        # 2. PRUNING: удалить слабые связи
        weak = [nid for nid, w in cube.connections.items() if w < 0.01]
        for nid in weak:
            del cube.connections[nid]
            stats["pruned"] += len(weak)
        
        # 3. RECONSOLIDATION: обновить старые кубы через random walk
        if cube.metadata.get("update_count", 0) > 3:
            # Найти новый контекст через Qdrant
            try:
                from qdrant_client import QdrantClient
                client = QdrantClient(host="skv_qdrant", port=6333)
                results = client.query_points(
                    collection_name="skv_rules_v2",
                    query=cube.vector.tolist() if hasattr(cube.vector, 'tolist') else cube.vector,
                    limit=3
                )
                for hit in results.points:
                    target_id = str(hit.id)
                    if target_id != cube_id and target_id in _v4_graph and hit.score > 0.6:
                        if target_id not in cube.connections:
                            cube.connections[target_id] = 0.2
                            stats["reconsolidated"] += 1
            except Exception as e:
                pass
        
        # 4. Обнуляем счётчик использования для следующего дня
        cube.metadata["usage_count"] = 0
    
    # Сохраняем граф
    import json
    data = {}
    for cid, c in _v4_graph.items():
        data[cid] = {
            'vector': c.vector.tolist() if hasattr(c.vector, 'tolist') else c.vector,
            'connections': c.connections,
            'metadata': c.metadata
        }
    with open('/data/skv/graph.json', 'w') as f:
        json.dump(data, f)
    
    # 5. HIERARCHICAL CLUSTERING
    try:
        from app.routers.hierarchical import apply_hierarchical_clustering
        meta_count = apply_hierarchical_clustering()
        stats["clustered"] = meta_count
    except Exception as e:
        print(f"[SLEEP] Clustering error: {e}", flush=True)
    
    # 5. HIERARCHICAL CLUSTERING
    try:
        from app.routers.hierarchical import apply_hierarchical_clustering
        meta_count = apply_hierarchical_clustering()
        stats["clustered"] = meta_count
        print(f"[SLEEP] Clustering: {meta_count} meta-cubes", flush=True)
    except Exception as e:
        print(f"[SLEEP] Clustering error: {e}", flush=True)
    
    # 6. PATTERN SEPARATION
    try:
        from app.routers.pattern_separator import separate_patterns
        for cube_id, cube in _v4_graph.items():
            if cube.metadata.get("is_constitutional"):
                continue
            if len(cube.connections) > 50:  # хаб — проверяем на дубликаты
                for neighbor_id in list(cube.connections.keys())[:10]:
                    if neighbor_id in _v4_graph:
                        neighbor = _v4_graph[neighbor_id]
                        if hasattr(cube, 'vector') and hasattr(neighbor, 'vector'):
                            import numpy as np
                            cosine = np.dot(cube.vector, neighbor.vector) / (np.linalg.norm(cube.vector) * np.linalg.norm(neighbor.vector) + 1e-8)
                            if cosine > 0.95:
                                separate_patterns(cube)
                                stats["separated"] = stats.get("separated", 0) + 1
        print(f"[SLEEP] Pattern separation: {stats.get('separated', 0)} cubes", flush=True)
    except Exception as e:
        print(f"[SLEEP] Pattern separation error: {e}", flush=True)
    
    # 7. EMOTIONAL CONSOLIDATION
    try:
        for cube_id, cube in _v4_graph.items():
            importance = cube.metadata.get("importance", 0.5)
            if importance > 0.7:  # важные кубы усиливаем
                for neighbor_id in cube.connections:
                    cube.connections[neighbor_id] = min(1.0, cube.connections[neighbor_id] * 1.1)
        stats["emotional"] = sum(1 for c in _v4_graph.values() if c.metadata.get("importance", 0) > 0.7)
        print(f"[SLEEP] Emotional consolidation: {stats['emotional']} important cubes", flush=True)
    except Exception as e:
        print(f"[SLEEP] Emotional error: {e}", flush=True)
    
    # 8. DEAD CUBES CLEANUP
    try:
        dead = []
        for cube_id, cube in _v4_graph.items():
            if cube.metadata.get("is_constitutional"):
                continue
            if len(cube.connections) == 0 and cube.metadata.get("usage_count", 0) == 0:
                dead.append(cube_id)
        for cube_id in dead:
            del _v4_graph[cube_id]
        stats["cleaned"] = len(dead)
        print(f"[SLEEP] Dead cubes removed: {len(dead)}", flush=True)
    except Exception as e:
        print(f"[SLEEP] Cleanup error: {e}", flush=True)
    
    print(f"[SLEEP] Cycle complete: replayed={stats['replayed']}, pruned={stats['pruned']}, "
          f"reconsolidated={stats['reconsolidated']}", flush=True)
    return stats

async def run_sleep_cycle():
    """Запускать каждые 12 часов при простое (нагрузка < 30%)."""
    import os
    while True:
        await asyncio.sleep(43200)  # Ждём 12 часов
        
        # Проверяем загрузку системы
        try:
            load = os.getloadavg()[0]  # Средняя загрузка за 1 минуту
            cpu_count = os.cpu_count() or 1
            load_percent = (load / cpu_count) * 100
            
            if load_percent < 30:
                print(f"[SLEEP] System idle ({load_percent:.0f}% load). Starting consolidation...", flush=True)
                await nightly_sleep_cycle()
            else:
                print(f"[SLEEP] System busy ({load_percent:.0f}% load). Skipping cycle, retry in 12h.", flush=True)
        except Exception as e:
            print(f"[SLEEP] Load check failed: {e}. Running cycle anyway.", flush=True)
            await nightly_sleep_cycle()
