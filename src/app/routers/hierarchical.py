"""Hierarchical Clustering v4.3 — Meta-cubes for scalable graph."""

import numpy as np
from collections import defaultdict

def compute_clusters(graph: dict, similarity_threshold: float = 0.7):
    """Группирует кубы в кластеры по cosine similarity."""
    clusters = defaultdict(list)
    cluster_vectors = {}
    visited = set()
    
    for cube_id, cube_data in graph.items():
        if cube_id in visited:
            continue
        
        vector = np.array(cube_data.get("vector", [0]*384))
        visited.add(cube_id)
        cluster_id = f"cluster_{len(clusters)}"
        clusters[cluster_id].append(cube_id)
        cluster_vectors[cluster_id] = [vector]
        
        # Ищем похожие кубы
        for other_id, other_data in graph.items():
            if other_id in visited:
                continue
            
            other_vector = np.array(other_data.get("vector", [0]*384))
            try:
                cosine = np.dot(vector, other_vector) / (np.linalg.norm(vector) * np.linalg.norm(other_vector) + 1e-8)
            except ValueError:
                continue  # Skip incompatible dimensions
            
            if cosine > similarity_threshold:
                clusters[cluster_id].append(other_id)
                cluster_vectors[cluster_id].append(other_vector)
                visited.add(other_id)
    
    return clusters, cluster_vectors

def create_meta_cubes(graph: dict, clusters: dict, cluster_vectors: dict):
    """Создаёт meta-кубы для каждого кластера."""
    meta_cubes = {}
    
    for cluster_id, member_ids in clusters.items():
        if len(member_ids) < 3:  # Слишком маленький кластер
            continue
        
        # Вычисляем центроид кластера
        centroid = np.mean(cluster_vectors[cluster_id], axis=0)
        
        # Собираем общие trigger_intents
        all_triggers = []
        for mid in member_ids:
            triggers = graph[mid].get("metadata", {}).get("trigger_intent", [])
            all_triggers.extend(triggers)
        
        # Топ-5 самых частых триггеров
        from collections import Counter
        top_triggers = [t for t, _ in Counter(all_triggers).most_common(5)]
        
        # Находим самое частое слово в названиях
        titles = [graph[mid].get("metadata", {}).get("title", "") for mid in member_ids]
        words = " ".join(titles).lower().split()
        top_word = Counter(words).most_common(1)[0][0] if words else cluster_id
        
        meta_id = f"meta_{top_word}_{cluster_id}"
        meta_cubes[meta_id] = {
            "vector": centroid.tolist(),
            "connections": {mid: 0.5 for mid in member_ids[:10]},  # Связи с членами
            "metadata": {
                "title": f"Meta: {top_word} ({len(member_ids)} cubes)",
                "cube_type": "META",
                "members": member_ids,
                "trigger_intent": top_triggers,
                "priority": 0,
                "stability": 0.8
            }
        }
        
        print(f"  Meta-cube: {top_word} — {len(member_ids)} members")
    
    return meta_cubes

def apply_hierarchical_clustering(graph_path: str = "/data/skv/graph.json"):
    """Применить иерархическую кластеризацию к графу."""
    import json
    
    print("[HIERARCHY] Starting clustering...", flush=True)
    
    with open(graph_path) as f:
        graph = json.load(f)
    
    # 1. Кластеризация
    clusters, cluster_vectors = compute_clusters(graph)
    print(f"[HIERARCHY] Found {len(clusters)} clusters", flush=True)
    
    # 2. Создание meta-кубов
    meta_cubes = create_meta_cubes(graph, clusters, cluster_vectors)
    print(f"[HIERARCHY] Created {len(meta_cubes)} meta-cubes", flush=True)
    
    # 3. Добавляем meta-кубы в граф
    graph.update(meta_cubes)
    
    with open(graph_path, 'w') as f:
        json.dump(graph, f)
    
    print(f"[HIERARCHY] Graph updated: {len(graph)} total cubes", flush=True)
    return len(meta_cubes)
