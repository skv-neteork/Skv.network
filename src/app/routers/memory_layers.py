"""Multi-Layer Memory v4.5 — User / Project / Global separation."""

import json
import numpy as np
from datetime import datetime, timezone

MEMORY_LAYERS = {
    "user": {"prefix": "user_", "priority": 1, "decay": 0.999},
    "project": {"prefix": "proj_", "priority": 2, "decay": 0.99},
    "global": {"prefix": "glob_", "priority": 3, "decay": 0.95}
}

def get_layer(cube_id: str) -> str:
    """Определить слой куба по префиксу."""
    if cube_id.startswith("user_"):
        return "user"
    elif cube_id.startswith("proj_"):
        return "project"
    return "global"

def create_cube_in_layer(graph: dict, layer: str, title: str, rules: list, 
                         vector: list, user_id: str = None, project_id: str = None) -> str:
    """Создать куб в правильном слое."""
    import time
    
    prefix = MEMORY_LAYERS[layer]["prefix"]
    cube_id = f"{prefix}{user_id or 'anon'}_{project_id or 'gen'}_{int(time.time())}"
    
    graph[cube_id] = {
        "vector": vector,
        "connections": {},
        "metadata": {
            "title": title,
            "rules": rules,
            "layer": layer,
            "priority": MEMORY_LAYERS[layer]["priority"],
            "user_id": user_id,
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    }
    
    # Связываем с кубами из того же слоя + глобальными
    for other_id, other_data in graph.items():
        other_layer = other_data.get("metadata", {}).get("layer", "global")
        
        # Внутри слоя или global → сильная связь
        if other_layer == layer or other_layer == "global":
            if other_id != cube_id:
                cosine = np.dot(vector, other_data["vector"]) / (
                    np.linalg.norm(vector) * np.linalg.norm(other_data["vector"]) + 1e-8
                )
                if cosine > 0.5:
                    graph[cube_id]["connections"][other_id] = round(cosine * 0.3, 3)
    
    return cube_id

def filter_by_layer(graph: dict, layer: str, user_id: str = None) -> dict:
    """Отфильтровать кубы по слою."""
    filtered = {}
    for cube_id, cube_data in graph.items():
        cube_layer = cube_data.get("metadata", {}).get("layer", "global")
        cube_user = cube_data.get("metadata", {}).get("user_id")
        
        if layer == "user" and cube_layer == "user" and cube_user == user_id:
            filtered[cube_id] = cube_data
        elif layer == "project" and cube_layer in ["project", "user"]:
            filtered[cube_id] = cube_data
        elif layer == "global" and cube_layer == "global":
            filtered[cube_id] = cube_data
    
    return filtered

def get_memory_context(graph: dict, user_id: str, project_id: str, query_vector: list) -> dict:
    """Получить контекст из всех трёх слоёв памяти."""
    
    # 1. User layer — персональные кубы
    user_cubes = filter_by_layer(graph, "user", user_id)
    
    # 2. Project layer — кубы проекта
    project_cubes = filter_by_layer(graph, "project", user_id)
    
    # 3. Global layer — общие кубы (конституция, опыт)
    global_cubes = filter_by_layer(graph, "global")
    
    return {
        "user_memory": len(user_cubes),
        "project_memory": len(project_cubes),
        "global_memory": len(global_cubes),
        "total": len(user_cubes) + len(project_cubes) + len(global_cubes)
    }
