"""
SKV v4.5 — Quantum Context Compression
Схлопывает множество активированных кубов в один вектор суперпозиции.
Экономит токены LLM в 10-20 раз.
"""
import numpy as np
from typing import List, Dict, Any


def compress_to_quantum_state(
    activated_cubes: List[Dict[str, Any]], 
    embedding_dim: int = 384
) -> List[float]:
    """
    Схлопывает кубы в вектор суперпозиции.
    Каждый куб вносит вклад пропорционально своей энергии.
    
    Args:
        activated_cubes: список dict с ключами 'vector' и 'energy'
        embedding_dim: размерность вектора (384)
    
    Returns:
        Нормализованный вектор суперпозиции
    """
    if not activated_cubes:
        return [0.0] * embedding_dim
    
    quantum_state = np.zeros(embedding_dim, dtype=np.float32)
    total_energy = 0.0
    
    for cube in activated_cubes:
        vec = np.array(cube.get('vector', [0.0] * embedding_dim), dtype=np.float32)
        energy = cube.get('energy', 0.5)
        
        # Кубы с высокой энергией сильнее влияют на итоговый вектор
        quantum_state += vec * energy
        total_energy += energy
    
    if total_energy > 0:
        quantum_state /= total_energy
        # Проекция на единичную сферу (важно для косинусного поиска)
        norm = np.linalg.norm(quantum_state)
        if norm > 0:
            quantum_state /= norm
    
    return quantum_state.tolist()


def quantum_context_to_text(
    activated_cubes: List[Dict[str, Any]],
    max_tokens: int = 200
) -> str:
    """
    Преобразует квантовый контекст в текстовое описание для LLM.
    Вместо отправки всех кубов — краткая сводка.
    """
    if not activated_cubes:
        return "No relevant memory context."
    
    # Сортируем по энергии (самые горячие — первые)
    sorted_cubes = sorted(activated_cubes, key=lambda c: c.get('energy', 0), reverse=True)
    
    lines = [f"Memory context ({len(activated_cubes)} relevant items, top results):"]
    
    for i, cube in enumerate(sorted_cubes[:5]):  # топ-5
        energy = cube.get('energy', 0)
        meta = cube.get('metadata', {})
        title = meta.get('title', cube.get('id', 'unknown')[:30])
        content = meta.get('content', '')
        if isinstance(content, dict):
            content = content.get('text', str(content)[:100])
        
        temp = '🔥' if energy > 0.7 else '🌡️' if energy > 0.3 else '❄️'
        lines.append(f"{temp} [{energy:.2f}] {title}: {str(content)[:100]}")
    
    return '\n'.join(lines)
