"""
SKV v4.5 — Neural Cycle (Hebbian + Decay + Auto-save)
Uses Oja's Rule (anti-explosion) + Background Tasks
"""
import asyncio
from app.routers.v4_graph import _v4_graph, save_graph_to_pg
from app.routers.v4_hebbian import oja_update, hebbian_update_batch, background_hebbian


def run_hebbian_cycle():
    """Быстрый цикл Hebbian с Oja's Rule (каждые 30 сек)"""
    if not _v4_graph:
        return
    
    updates_count = 0
    for cid, cube in _v4_graph.items():
        if not cube.connections:
            continue
        for tid, weight in list(cube.connections.items()):
            if tid in _v4_graph:
                # Оба куба активны — применяем Oja
                new_w = oja_update(weight, act_a=1.0, act_b=1.0)
                if abs(new_w - weight) > 0.001:
                    cube.connections[tid] = new_w
                    updates_count += 1
    
    if updates_count > 0:
        print(f"[V4] Hebbian (Oja) updated {updates_count} connections", flush=True)


def run_decay_cycle():
    """Применяет Lazy Decay ко всем кубам (каждые 5 мин)"""
    if not _v4_graph:
        return
    
    dead = 0
    for cid, cube in list(_v4_graph.items()):
        energy = cube._apply_lazy_entropy()
        if energy < 0.01:
            dead += 1
    
    if dead > 0:
        print(f"[V4] Decay: {dead} cubes with low energy", flush=True)


async def run_auto_save():
    """Авто-сохранение графа в PostgreSQL (каждые 30 мин)"""
    try:
        await save_graph_to_pg()
    except Exception as e:
        print(f"[V4] Auto-save error: {e}", flush=True)
