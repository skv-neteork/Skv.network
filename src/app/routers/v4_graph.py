"""
SKV v4.5 — TensorCube Graph Engine
Primary storage: PostgreSQL (cubes + graph_edges)
Fallback: Qdrant (vector search + recovery)
Legacy: JSON file (export only)
"""
import numpy as np
import threading
import asyncpg
import asyncio
import json
import os
import time
import shutil
from app.routers.tensor_cube import TensorCube

_v4_graph = {}
_pg_pool = None

# ═══════════════════════════════════════════
# POSTGRESQL CONNECTION POOL
# ═══════════════════════════════════════════

async def _get_pool():
    global _pg_pool
    if _pg_pool is None:
        db_url = os.environ.get('DATABASE_URL', 
            'postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db')
        _pg_pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)
    return _pg_pool


# ═══════════════════════════════════════════
# GRAPH LOADING (PostgreSQL → Memory)
# ═══════════════════════════════════════════

async def _load_graph():
    """Загрузка графа из PostgreSQL"""
    global _v4_graph
    if _v4_graph:
        return
    
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 1. Загружаем кубы
        rows = await conn.fetch(
            'SELECT cube_id, embedding, content FROM cubes WHERE embedding IS NOT NULL'
        )
        for row in rows:
            cid = row['cube_id']
            vec = row['embedding']
            meta = {}
            if row['content']:
                try:
                    meta = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
                except:
                    meta = {}
            _v4_graph[cid] = TensorCube(cube_id=cid, vector=vec, metadata=meta)
        
        # 2. Загружаем связи
        edges = await conn.fetch('SELECT source_id, target_id, weight FROM graph_edges')
        for e in edges:
            if e['source_id'] in _v4_graph and e['target_id'] in _v4_graph:
                _v4_graph[e['source_id']].connections[e['target_id']] = e['weight']
    
    conns = sum(len(c.connections) for c in _v4_graph.values())
    print(f"[V4] Loaded from PostgreSQL: {len(_v4_graph)} cubes, {conns} connections", flush=True)


def get_graph():
    """Возвращает граф, загружая из БД при необходимости"""
    global _v4_graph
    if _v4_graph:
        return _v4_graph
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
        loop.run_until_complete(_load_graph())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_load_graph())
    
    return _v4_graph


# ═══════════════════════════════════════════
# GRAPH SAVING (Memory → PostgreSQL)
# ═══════════════════════════════════════════

async def save_graph_to_pg():
    """Сохраняет текущее состояние графа в PostgreSQL (batch insert)"""
    if not _v4_graph:
        return False
    
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Сохраняем связи пачками по 100
            batch = []
            for cid, cube in _v4_graph.items():
                for tid, weight in cube.connections.items():
                    batch.append((cid, tid, weight))
                    if len(batch) >= 100:
                        await conn.executemany(
                            'INSERT INTO graph_edges (source_id, target_id, weight) '
                            'VALUES ($1, $2, $3) ON CONFLICT (source_id, target_id) '
                            'DO UPDATE SET weight = $3',
                            batch
                        )
                        batch = []
            if batch:
                await conn.executemany(
                    'INSERT INTO graph_edges (source_id, target_id, weight) '
                    'VALUES ($1, $2, $3) ON CONFLICT (source_id, target_id) '
                    'DO UPDATE SET weight = $3',
                    batch
                )
    
    conns = sum(len(c.connections) for c in _v4_graph.values())
    print(f"[V4] Saved to PostgreSQL: {len(_v4_graph)} cubes, {conns} connections", flush=True)
    return True


# ═══════════════════════════════════════════
# SAFE SHUTDOWN
# ═══════════════════════════════════════════

async def shutdown_save():
    """Вызывается при остановке сервера"""
    conns = sum(len(c.connections) for c in _v4_graph.values())
    if conns < 1000:
        print(f"[SHUTDOWN] Graph NOT saved: only {conns} edges (protection)", flush=True)
        return
    await save_graph_to_pg()
    print(f"[SHUTDOWN] Graph saved: {conns} edges", flush=True)


# ═══════════════════════════════════════════
# JSON EXPORT (backup only)
# ═══════════════════════════════════════════

def export_to_json(filepath="/data/skv/graph_export.json"):
    """Экспорт графа в JSON (только для бэкапа)"""
    if not _v4_graph:
        return
    
    conns = sum(len(c.connections) for c in _v4_graph.values())
    if conns < 1000:
        print(f"[EXPORT] Refused: only {conns} edges", flush=True)
        return
    
    data = {}
    for cid, c in _v4_graph.items():
        data[cid] = {
            'vector': c.vector.tolist() if hasattr(c.vector, 'tolist') else c.vector,
            'connections': c.connections,
            'metadata': c.metadata
        }
    
    # Атомарная запись
    tmp = filepath + '.tmp'
    bak = filepath + '.bak'
    try:
        with open(tmp, 'w') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(filepath):
            shutil.copy2(filepath, bak)
        os.rename(tmp, filepath)
        print(f"[EXPORT] {len(data)} cubes, {conns} edges → {filepath}", flush=True)
    except Exception as e:
        print(f"[EXPORT] Error: {e}", flush=True)


# ═══════════════════════════════════════════
# AUTO-SAVE LOOP (background)
# ═══════════════════════════════════════════

async def _auto_save_loop():
    """Фоновое сохранение графа каждые 5 минут"""
    while True:
        await asyncio.sleep(300)
        try:
            await save_graph_to_pg()
        except Exception as e:
            print(f"[AUTO-SAVE] Error: {e}", flush=True)


def start_auto_save():
    """Запуск фонового автосохранения"""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_auto_save_loop())
    except:
        pass


# ═══════════════════════════════════════════
# RECOVERY FROM QDRANT (if PostgreSQL empty)
# ═══════════════════════════════════════════

async def recover_from_qdrant():
    """Восстановление графа из Qdrant если PostgreSQL пуст"""
    from qdrant_client import QdrantClient
    
    pool = await _get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval('SELECT count(*) FROM cubes WHERE embedding IS NOT NULL')
        if count > 0:
            print(f"[RECOVERY] PostgreSQL has {count} cubes, skipping Qdrant recovery", flush=True)
            return
    
    print("[RECOVERY] PostgreSQL empty, loading from Qdrant...", flush=True)
    client = QdrantClient(host="skv_qdrant", port=6333)
    
    all_points = []
    offset = None
    while True:
        result = client.scroll(collection_name="skv_rules_v2", limit=100, offset=offset,
                               with_vectors=True, with_payload=True)
        points, offset = result
        all_points.extend(points)
        if offset is None: break
    
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('DELETE FROM graph_edges')
            for point in all_points:
                cid = str(point.id)
                meta = point.payload.get('metadata', {}) if point.payload else {}
                await conn.execute(
                    'UPDATE cubes SET embedding = $1, content = $2 WHERE cube_id = $3',
                    point.vector, json.dumps(meta), cid
                )
            
            conn_count = 0
            batch = []
            for point in all_points:
                cid = str(point.id)
                results = client.query_points(collection_name="skv_rules_v2", query=point.vector, limit=6)
                for hit in results.points:
                    tid = str(hit.id)
                    if tid != cid and hit.score > 0.4:
                        batch.append((cid, tid, round(0.1 + (hit.score * 0.25), 3)))
                        conn_count += 1
                if len(batch) >= 100:
                    await conn.executemany(
                        'INSERT INTO graph_edges VALUES ($1,$2,$3) ON CONFLICT DO NOTHING', batch)
                    batch = []
            if batch:
                await conn.executemany(
                    'INSERT INTO graph_edges VALUES ($1,$2,$3) ON CONFLICT DO NOTHING', batch)
    
    print(f"[RECOVERY] Restored: {len(all_points)} cubes, {conn_count} edges from Qdrant", flush=True)
