"""
SKV v4.5 — TensorCube Graph Engine
Primary storage: PostgreSQL (cubes + graph_edges)
Thermodynamic memory: Lazy Decay (entropy on access)
"""
import numpy as np
import asyncio
import asyncpg
import json
import os
import time
import math
import shutil

_v4_graph = {}
_pg_pool = None
_graph_lock = asyncio.Lock()

# Агрессивность остывания: 0.0001 = куб остывает за ~3 часа простоя
LAMBDA_DECAY = 0.0001


# ═══════════════════════════════════════════
# THERMODYNAMIC TENSOR CUBE
# ═══════════════════════════════════════════

class TensorCube:
    """Куб памяти с термодинамической энергией"""
    
    def __init__(self, cube_id, vector, metadata=None, energy=1.0, last_active=None):
        self.cube_id = cube_id
        self.vector = np.array(vector, dtype=np.float32) if not isinstance(vector, np.ndarray) else vector.astype(np.float32)
        self.metadata = metadata or {}
        self.connections = {}
        self.energy = float(energy)
        self.last_active = last_active or time.time()
        
        # Нормализуем вектор для косинусного сходства
        norm = np.linalg.norm(self.vector)
        if norm > 0:
            self.vector = self.vector / norm
    
    def _apply_lazy_entropy(self) -> float:
        """Экспоненциальное остывание энергии"""
        now = time.time()
        dt = now - self.last_active
        if dt > 0:
            # Конституционные кубы остывают в 10 раз медленнее
            importance = self.metadata.get('importance', 0.5)
            rate = LAMBDA_DECAY * (0.1 if importance > 0.8 else 1.0)
            self.energy *= math.exp(-rate * dt)
        self.last_active = now
        
        # Ослабление связей при низком энергии
        if self.energy < 0.01:
            self.energy = 0.0
            for tid in list(self.connections.keys()):
                self.connections[tid] *= 0.9
                if self.connections[tid] < 0.001:
                    del self.connections[tid]
        
        return self.energy
    
    def activate(self, impulse: float = 0.3):
        """Нагрев куба при использовании"""
        self._apply_lazy_entropy()
        self.energy = min(1.0, self.energy + impulse)
        self.metadata['usage_count'] = self.metadata.get('usage_count', 0) + 1
        self.metadata['last_used'] = time.time()
    
    def cosine_similarity(self, other_vector) -> float:
        """Косинусное сходство (вектор уже нормализован)"""
        other = np.array(other_vector, dtype=np.float32)
        norm = np.linalg.norm(other)
        if norm > 0:
            other = other / norm
        return float(np.dot(self.vector, other))


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
    global _v4_graph
    if _v4_graph:
        return
    
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Проверяем, есть ли колонки energy и last_active
        cols = await conn.fetch("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'cubes'
        """)
        col_names = [c['column_name'] for c in cols]
        
        if 'energy' not in col_names:
            await conn.execute('ALTER TABLE cubes ADD COLUMN energy REAL DEFAULT 1.0')
            print("[V4] Added column 'energy' to cubes")
        if 'last_active' not in col_names:
            await conn.execute('ALTER TABLE cubes ADD COLUMN last_active BIGINT')
            print("[V4] Added column 'last_active' to cubes")
        
        # Загружаем кубы
        rows = await conn.fetch(
            'SELECT cube_id, embedding, content, energy, last_active FROM cubes WHERE embedding IS NOT NULL'
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
            
            energy = row['energy'] if row['energy'] is not None else 1.0
            last_active = row['last_active'] if row['last_active'] else time.time()
            
            _v4_graph[cid] = TensorCube(
                cube_id=cid, vector=vec, metadata=meta,
                energy=energy, last_active=last_active
            )
        
        # Загружаем связи
        edges = await conn.fetch('SELECT source_id, target_id, weight FROM graph_edges')
        for e in edges:
            if e['source_id'] in _v4_graph and e['target_id'] in _v4_graph:
                _v4_graph[e['source_id']].connections[e['target_id']] = e['weight']
    
    conns = sum(len(c.connections) for c in _v4_graph.values())
    avg_energy = sum(c.energy for c in _v4_graph.values()) / len(_v4_graph) if _v4_graph else 0
    print(f"[V4] Loaded: {len(_v4_graph)} cubes, {conns} connections, avg_energy={avg_energy:.3f}", flush=True)


def get_graph():
    global _v4_graph
    if _v4_graph:
        return _v4_graph
    
    import threading as _thr
    _result = {}
    
    def _load_sync():
        try:
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _loop.run_until_complete(_load_graph())
            _result['ok'] = True
        except Exception as e:
            _result['err'] = e
    
    _t = _thr.Thread(target=_load_sync)
    _t.start()
    _t.join(timeout=60)
    
    if 'err' in _result:
        raise _result['err']
    return _v4_graph


# ═══════════════════════════════════════════

# ═══════════════════════════════════════════
# ACCESS & MUTATION (нагрев при любом обращении)
# ═══════════════════════════════════════════

async def get_cube(cube_id: str):
    """Прямое получение куба с нагревом"""
    graph = get_graph()
    async with _graph_lock:
        cube = graph.get(cube_id)
        if cube:
            cube.activate(impulse=0.1)
        return cube

async def record_feedback(cube_id: str, vote: str):
    """Обратная связь: upvote греет, downvote остужает"""
    graph = get_graph()
    async with _graph_lock:
        cube = graph.get(cube_id)
        if cube:
            impulse = 0.2 if vote == "up" else -0.15
            cube.activate(impulse=impulse)

async def update_connection(source_id: str, target_id: str, weight: float):
    """Обновление связи с лёгким нагревом обоих кубов"""
    graph = get_graph()
    async with _graph_lock:
        if source_id in graph and target_id in graph:
            graph[source_id].connections[target_id] = weight
            graph[source_id].activate(impulse=0.05)
            graph[target_id].activate(impulse=0.05)

# SPREADING ACTIVATION WITH LAZY DECAY
# ═══════════════════════════════════════════

async def spreading_activation(query_vector, threshold=0.15, max_hops=3):
    """Волна активации с термодинамической энтропией"""
    graph = get_graph()
    if not graph:
        return []
    
    activated = []
    
    async with _graph_lock:
        for cid, cube in graph.items():
            cube._apply_lazy_entropy()
            if cube.energy < 0.01:
                continue
            
            similarity = cube.cosine_similarity(query_vector)
            if similarity > threshold:
                cube.activate(impulse=similarity * 0.5)
                activated.append(cid)
        
        for hop in range(max_hops):
            new_activated = []
            for src_id in list(activated):
                src = graph[src_id]
                for tgt_id, weight in list(src.connections.items()):
                    if tgt_id in graph and tgt_id not in activated and tgt_id not in new_activated:
                        wave = src.energy * weight * (0.3 ** (hop + 1))
                        if wave > threshold:
                            graph[tgt_id]._apply_lazy_entropy()
                            graph[tgt_id].activate(impulse=wave)
                            new_activated.append(tgt_id)
            activated.extend(new_activated)
    
    return [{"id": cid, "energy": graph[cid].energy, "metadata": graph[cid].metadata} 
            for cid in activated]


# ═══════════════════════════════════════════
# GRAPH SAVING (UPSERT — безопасно)
# ═══════════════════════════════════════════

async def save_graph_to_pg():
    if not _v4_graph:
        return False
    
    conns = sum(len(c.connections) for c in _v4_graph.values())
    if conns < 100:
        print(f"[SAVE] Refused: only {conns} edges", flush=True)
        return False
    
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Сохраняем энергию
            for cid, cube in _v4_graph.items():
                await conn.execute(
                    'UPDATE cubes SET energy = $1, last_active = $2 WHERE cube_id = $3',
                    cube.energy, int(cube.last_active), cid
                )
            
            # Сохраняем связи (UPSERT, без DELETE)
            batch = []
            for cid, cube in _v4_graph.items():
                for tid, weight in cube.connections.items():
                    batch.append((cid, tid, weight))
                    if len(batch) >= 100:
                        await conn.executemany(
                            'INSERT INTO graph_edges (source_id, target_id, weight) '
                            'VALUES ($1, $2, $3) '
                            'ON CONFLICT (source_id, target_id) DO UPDATE SET weight = $3',
                            batch
                        )
                        batch = []
            if batch:
                await conn.executemany(
                    'INSERT INTO graph_edges (source_id, target_id, weight) '
                    'VALUES ($1, $2, $3) '
                    'ON CONFLICT (source_id, target_id) DO UPDATE SET weight = $3',
                    batch
                )
    
    print(f"[V4] Saved: {len(_v4_graph)} cubes, {conns} edges", flush=True)
    return True


# ═══════════════════════════════════════════
# AUTO-SAVE LOOP
# ═══════════════════════════════════════════

async def _auto_save_loop():
    while True:
        await asyncio.sleep(300)
        try:
            await save_graph_to_pg()
        except Exception as e:
            print(f"[AUTO-SAVE] Error: {e}", flush=True)


def start_auto_save():
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_auto_save_loop())
        print("[V4] Auto-save started (every 5 min)")
    except Exception as e:
        print(f"[V4] Auto-save error: {e}")


# ═══════════════════════════════════════════
# SAFE SHUTDOWN
# ═══════════════════════════════════════════

async def shutdown_save():
    conns = sum(len(c.connections) for c in _v4_graph.values())
    if conns < 100:
        print(f"[SHUTDOWN] Not saved: only {conns} edges", flush=True)
        return
    await save_graph_to_pg()
    print(f"[SHUTDOWN] Graph saved: {conns} edges", flush=True)


# ═══════════════════════════════════════════
# JSON EXPORT (backup only)
# ═══════════════════════════════════════════

def export_to_json(filepath="/data/skv/graph_export.json"):
    if not _v4_graph:
        return
    
    data = {}
    for cid, c in _v4_graph.items():
        data[cid] = {
            'vector': c.vector.tolist(),
            'connections': c.connections,
            'metadata': c.metadata,
            'energy': c.energy,
            'last_active': c.last_active
        }
    
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
        print(f"[EXPORT] {len(data)} cubes → {filepath}", flush=True)
    except Exception as e:
        print(f"[EXPORT] Error: {e}", flush=True)
