"""Memory Reconsolidation v4.4 — Update cubes when accessed."""

import time
import numpy as np

def reconsolidate_cube(cube, new_context_vector=None, new_rules=None):
    """Обновить куб при доступе — как в гиппокампе при воспоминании."""
    
    # 1. Помечаем что куб был accessed
    cube.metadata["last_reconsolidated"] = time.time()
    cube.metadata["access_count"] = cube.metadata.get("access_count", 0) + 1
    
    # 2. Если есть новый контекст — обновляем вектор (лабильность)
    if new_context_vector is not None:
        old_vector = cube.vector if isinstance(cube.vector, np.ndarray) else np.array(cube.vector)
        new_vector = np.array(new_context_vector)
        
        # Интерполяция: 80% старого + 20% нового
        cube.vector = (0.8 * old_vector + 0.2 * new_vector).tolist()
        cube.metadata["vector_updated_at"] = time.time()
    
    # 3. Если есть новые правила — добавляем (без дубликатов)
    if new_rules:
        existing = cube.metadata.get("rules", [])
        for rule in new_rules:
            if rule not in existing:
                existing.append(rule)
        cube.metadata["rules"] = existing[-10:]  # Максимум 10 правил
        cube.metadata["rules_updated_at"] = time.time()
    
    # 4. Усиливаем важность при частом доступе
    access_count = cube.metadata.get("access_count", 0)
    cube.metadata["importance"] = min(1.0, 0.3 + (access_count * 0.05))
    
    return cube

def get_cube_with_reconsolidation(graph, cube_id, new_context=None):
    """Получить куб с автоматической реконсолидацией."""
    if cube_id not in graph:
        return None
    
    cube = graph[cube_id]
    
    # Реконсолидация при доступе
    if new_context:
        cube = reconsolidate_cube(cube, new_context_vector=new_context.get("vector"))
    
    # Если куб старый и часто используется — усилить связи
    if cube.metadata.get("access_count", 0) > 10:
        for neighbor_id in list(cube.connections.keys()):
            if neighbor_id in graph:
                cube.connections[neighbor_id] = min(1.0, cube.connections[neighbor_id] * 1.05)
    
    return cube
