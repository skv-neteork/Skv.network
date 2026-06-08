"""Pattern Separation — prevent memory interference."""

import numpy as np

def should_merge_cubes(cube1, cube2, threshold=0.95):
    """Проверить не слишком ли похожи два куба."""
    if not hasattr(cube1, 'vector') or not hasattr(cube2, 'vector'):
        return False
    
    v1 = cube1.vector if isinstance(cube1.vector, np.ndarray) else np.array(cube1.vector)
    v2 = cube2.vector if isinstance(cube2.vector, np.ndarray) else np.array(cube2.vector)
    
    cosine = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
    return cosine > threshold

def separate_patterns(cube, noise_level=0.01):
    """Добавить небольшой шум к вектору куба для разделения паттернов."""
    if hasattr(cube, 'vector') and isinstance(cube.vector, np.ndarray):
        noise = np.random.normal(0, noise_level, cube.vector.shape)
        cube.vector = cube.vector + noise
        # Нормализуем
        cube.vector = cube.vector / (np.linalg.norm(cube.vector) + 1e-8)
    return cube
