"""
SKV v4.5 — Hebbian Learning with Oja's Rule
Prevents weight explosion, auto-normalizes to [0, 1]
"""
import asyncio
import asyncpg
import os

async def _get_pool():
    """Lazy pool (совместимость с v4_graph)"""
    from app.routers.v4_graph import _get_pool as _gp
    return await _gp()


def oja_update(current_weight: float, act_a: float, act_b: float, 
               lr: float = 0.05, decay: float = 0.001) -> float:
    """
    Oja's Rule — предотвращает бесконечный рост весов.
    Если кубы не активны вместе — связь затухает.
    """
    if act_a == 0.0 or act_b == 0.0:
        return max(0.0, current_weight - decay)
    
    delta = lr * (act_a * act_b - (act_b ** 2) * current_weight)
    new_weight = current_weight + delta
    return min(1.0, max(0.0, new_weight))


def hebbian_update_batch(activated_cubes: list, _v4_graph: dict, lr: float = 0.05) -> list:
    """
    Обновляет связи между всеми активированными кубами.
    Возвращает список изменений для batch-сохранения в БД.
    """
    updates = []
    for i, cube_a in enumerate(activated_cubes):
        if cube_a not in _v4_graph:
            continue
        for cube_b in activated_cubes[i+1:]:
            if cube_b not in _v4_graph:
                continue
            
            old_w = _v4_graph[cube_a].connections.get(cube_b, 0.0)
            new_w = oja_update(old_w, act_a=1.0, act_b=1.0, lr=lr)
            
            if abs(new_w - old_w) > 0.001:
                _v4_graph[cube_a].connections[cube_b] = new_w
                updates.append((cube_a, cube_b, new_w))
    
    return updates


async def background_hebbian(activated_cubes: list, _v4_graph: dict):
    """Фоновое обновление Hebbian — не блокирует ответ пользователю"""
    try:
        updates = hebbian_update_batch(activated_cubes, _v4_graph)
        if not updates:
            return
        
        # Сохраняем в БД пачкой
        db_url = os.environ.get('DATABASE_URL',
            'postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db')
        conn = await asyncpg.connect(db_url)
        try:
            batch = [(s, t, w) for s, t, w in updates]
            await conn.executemany('''
                INSERT INTO graph_edges (source_id, target_id, weight) 
                VALUES ($1, $2, $3) 
                ON CONFLICT (source_id, target_id) DO UPDATE SET weight = $3
            ''', batch)
        finally:
            await conn.close()
        
        print(f"[HEBBIAN BG] Updated {len(updates)} connections", flush=True)
    except Exception as e:
        print(f"[HEBBIAN BG] Error: {e}", flush=True)
