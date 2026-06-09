"""SKV v4.0 — TensorCube: Neural Knowledge Unit"""
import numpy as np
import time as _time

# STDP temporal windows (seconds)
STDP_WINDOW = 0.1   # 100ms — strong LTP
STDP_LATE = 0.5     # 500ms — weak LTD-like
from typing import Dict, Optional, Set
from datetime import datetime
import uuid

MAX_CONNECTIONS = 100

MAX_CONNECTIONS = 100

class TensorCube:
    """Core semantic memory unit for SKV v4.0 neural graph."""
    
    def __init__(self, cube_id: str = None, vector: np.ndarray = None, metadata: Optional[Dict] = None):
        self.cube_id = cube_id or str(uuid.uuid4())[:8]
        if vector is None:
            self.vector = np.random.randn(1536).astype(np.float32)
        else:
            self.vector = np.array(vector, dtype=np.float32)
        self.vector = self._normalize(self.vector)
        self.connections: Dict[str, float] = {}
        self.metadata = {
            'usage_count': 0, 'success_count': 0, 'stability': 0.5,
            'created_at': datetime.now().isoformat(),
            'last_accessed': datetime.now().isoformat()
        }
        if metadata: self.metadata.update(metadata)
        self.directed_edges = {"next": {}, "triggered_by": {}}
    
    def _normalize(self, v: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(v)
        return v / norm if norm > 1e-12 else np.random.randn(1536).astype(np.float32) / np.sqrt(1536)
    
    def record_usage(self):
        """Записать использование куба."""
        self.metadata['usage_count'] += 1
        self.metadata['last_accessed'] = __import__('datetime').datetime.now().isoformat()
    
    def update_embedding(self, new_vector: np.ndarray, lr: float = 0.1, decay: float = 0.01) -> None:
        new_vector = np.array(new_vector, dtype=np.float32)
        self.vector = self._normalize((1 - decay) * self.vector + lr * new_vector)
        self.metadata['usage_count'] += 1
        self.metadata['last_accessed'] = datetime.now().isoformat()
        change = np.linalg.norm(new_vector - self.vector)
        self.metadata['stability'] = 0.9 * self.metadata['stability'] + 0.1 * (1.0 - min(change, 1.0))
    
    def add_connection(self, cube_id: str, strength: float = 0.5) -> None:
        self.connections[cube_id] = max(0.0, min(1.0, strength))
    
    def strengthen_connection(self, cube_id: str, delta: float = 0.1) -> None:
        current = self.connections.get(cube_id, 0.0)
        self.connections[cube_id] = min(1.0, current + delta)
    
    def decay_connections(self, rate: float = 0.99, threshold: float = 0.01) -> int:
        pruned, to_remove = 0, []
        for cid, strength in self.connections.items():
            ns = strength * rate
            if ns < threshold: to_remove.append(cid); pruned += 1
            else: self.connections[cid] = ns
        for cid in to_remove: del self.connections[cid]
        return pruned
    
    def add_connection(self, cube_id: str, weight: float = 0.3, time_delta: float = None):
        """STDP: closer in time = stronger connection."""
        if time_delta is not None:
            if time_delta <= STDP_WINDOW:
                weight *= 1.5
            elif time_delta >= STDP_LATE:
                weight *= 0.5
        self.connections[cube_id] = min(1.0, weight)
        self.connection_timestamps[cube_id] = _time.time()
    
    def add_directed_edge(self, target_id: str, weight: float = 0.3, rel_type: str = "next"):
        if rel_type not in self.directed_edges:
            self.directed_edges[rel_type] = {}
        self.directed_edges[rel_type][target_id] = weight
    
    def remove_all_connections(self):
        """Удалить все связи куба (исходящие и входящие)."""
        self.connections = {}
        self.directed_edges = {"next": {}, "triggered_by": {}}
    
    def get_top_connections(self, n: int = 5) -> list:
        return sorted(self.connections.items(), key=lambda x: -x[1])[:n]
    
    def fitness(self) -> float:
        return self.metadata['usage_count'] * self.metadata['stability']
    
    def to_dict(self) -> dict:
        return {'cube_id': self.cube_id, 'vector': self.vector.tolist(), 'connections': self.connections, 'metadata': self.metadata}
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TensorCube':
        cube = cls(cube_id=data['cube_id'], vector=np.array(data['vector'], dtype=np.float32), metadata=data.get('metadata', {}))
        cube.connections = data.get('connections', {})
        return cube
    
    def __repr__(self) -> str:
        return f"TensorCube({self.cube_id}, connections={len(self.connections)}, used={self.metadata['usage_count']}x)"


def spread_activation(start_cube: TensorCube, get_cube_fn: callable, energy: float = 1.0, max_depth: int = 3, decay: float = 0.85, threshold: float = 0.1) -> Dict[str, float]:
    activated = {start_cube.cube_id: energy}
    visited: Set[str] = set()
    frontier = [(start_cube, energy)]
    for _ in range(max_depth):
        new_frontier = []
        for cube, curr_e in frontier:
            if cube.cube_id in visited: continue
            visited.add(cube.cube_id)
            for nid, strength in cube.connections.items():
                if strength < threshold: continue
                new_e = curr_e * strength * decay
                if nid not in activated or new_e > activated[nid]:
                    activated[nid] = new_e
                    try:
                        nc = get_cube_fn(nid)
                        if nc: new_frontier.append((nc, new_e))
                    except: pass
        frontier = new_frontier
    return activated


def deprecate_cube(cube) -> None:
    cube.metadata["deprecated"] = True
    cube.metadata["deprecated_at"] = __import__('datetime').datetime.now().isoformat()

def rollback_cube(cube) -> None:
    cube.metadata.pop("deprecated", None)
    cube.metadata.pop("deprecated_at", None)

def is_active(cube) -> bool:
    return not cube.metadata.get("deprecated", False)

def cascade_delete_cube(cubes: dict, cube_id: str) -> int:
    """Удалить куб и все его связи (включая обратные)."""
    if cube_id not in cubes:
        return 0
    
    removed = 0
    # Удаляем обратные связи от соседей
    for neighbor_id in list(cubes[cube_id].connections.keys()):
        if neighbor_id in cubes and cube_id in cubes[neighbor_id].connections:
            del cubes[neighbor_id].connections[cube_id]
            removed += 1
    
    # Удаляем directed edges от соседей
    for rel_type in ["next", "triggered_by"]:
        for neighbor_id in list(cubes[cube_id].directed_edges.get(rel_type, {}).keys()):
            if neighbor_id in cubes:
                for nrel in ["next", "triggered_by"]:
                    cubes[neighbor_id].directed_edges.get(nrel, {}).pop(cube_id, None)
    
    # Удаляем сам куб
    del cubes[cube_id]
    removed += 1
    return removed

def hebbian_update(cubes: Dict[str, TensorCube], active_ids: list, lr: float = 0.1, decay: float = 0.99, order: list = None, negative_ids: list = None, neg_lr: float = 0.05) -> None:
    """Hebbian update с STDP и Contrastive Hebbian (negative sampling)."""
    # STDP: направленные связи по порядку активации
    if order and len(order) > 1:
        for i in range(len(order) - 1):
            s, t = order[i], order[i+1]
            if s in cubes and t in cubes:
                cubes[s].add_directed_edge(t, 0.3, "next")
    
    # Positive Hebbian: усиливаем связи между активными кубами
    for i in range(len(active_ids)):
        for j in range(i+1, len(active_ids)):
            a, b = active_ids[i], active_ids[j]
            if a in cubes and b in cubes:
                # Усиление обычных связей
                if b not in cubes[a].connections:
                    cubes[a].connections[b] = 0.1
                    print(f"[HEBBIAN] NEW: {a[:16]} <-> {b[:16]}", flush=True)
                    print(f"[HEBBIAN] NEW: {a[:16]} <-> {b[:16]}", flush=True)
                if b not in cubes[a].connections: cubes[a].connections[b] = 0.1
                cubes[a].connections[b] = min(1.0, cubes[a].connections[b] + lr)
                
                if a not in cubes[b].connections:
                    cubes[b].connections[a] = 0.1
                if a not in cubes[b].connections: cubes[b].connections[a] = 0.1
                cubes[b].connections[a] = min(1.0, cubes[b].connections[a] + lr)
    
    # Contrastive Hebbian: ослабляем связи с negative_ids
    if negative_ids:
        for nid in negative_ids:
            if nid not in cubes:
                continue
            for aid in active_ids:
                if aid not in cubes:
                    continue
                # Ослабляем связь в обе стороны
                if nid in cubes[aid].connections:
                    cubes[aid].connections[nid] = max(0.0, cubes[aid].connections[nid] - neg_lr)
                if aid in cubes[nid].connections:
                    cubes[nid].connections[aid] = max(0.0, cubes[nid].connections[aid] - neg_lr)
    
    # Decay всех связей
    for cube in cubes.values(): 
        cube.decay_connections(rate=decay)
    # STDP: направленные связи по порядку активации
    if order and len(order) > 1:
        for i in range(len(order) - 1):
            s, t = order[i], order[i+1]
            if s in cubes and t in cubes:
                cubes[s].add_directed_edge(t, 0.3, "next")
    for i, id1 in enumerate(active_ids):
        if id1 not in cubes: continue
        for id2 in active_ids[i+1:]:
            if id2 not in cubes: continue
            cubes[id1].strengthen_connection(id2, lr)
            cubes[id2].strengthen_connection(id1, lr)
    for cube in cubes.values(): cube.decay_connections(rate=decay)
    
    # Авто-сохранение графа после обучения
    try:
        import json
        _data = {}
        for _cid, _c in cubes.items():
            _data[_cid] = {'vector': _c.vector.tolist(), 'connections': _c.connections, 'outgoing_connections': _c.directed_edges.get('next', {}), 'metadata': _c.metadata}
        with open('/data/skv/graph.json', 'w') as _f:
            json.dump(_data, _f)
    except:
        pass


def evolve_cubes(parent1: TensorCube, parent2: TensorCube, mutation_rate: float = 0.1) -> TensorCube:
    child_vector = (parent1.vector + parent2.vector) / 2.0
    if np.random.random() < mutation_rate:
        child_vector += np.random.normal(0, 0.05, 1536).astype(np.float32)
    child = TensorCube(vector=child_vector)
    all_conns = set(parent1.connections.keys()) | set(parent2.connections.keys())
    for cid in all_conns:
        s1, s2 = parent1.connections.get(cid, 0.0), parent2.connections.get(cid, 0.0)
        child.connections[cid] = (s1 + s2) / 2.0
    child.metadata['stability'] = (parent1.metadata['stability'] + parent2.metadata['stability']) / 2.0
    return child
