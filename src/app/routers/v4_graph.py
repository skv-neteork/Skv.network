"""SKV v4.0 — Shared neural graph."""
import asyncio
import json, os, numpy as np
from app.routers.tensor_cube import TensorCube

_v4_graph = {}

def get_graph():
    global _v4_graph
    if not _v4_graph:
        _path = '/data/skv/graph.json'
        if os.path.exists(_path):
            with open(_path, 'r') as _f:
                _data = json.load(_f)
            for _cid, _cube_data in _data.items():
                _tc = TensorCube(_cid, np.array(_cube_data['vector'], dtype=np.float32))
                _tc.connections = _cube_data.get('connections', {})
                _tc.connections.update(_cube_data.get('outgoing_connections', {}))
                _tc.connections.update(_cube_data.get('outgoing_connections', {}))
                _tc.connections.update(_cube_data.get('outgoing_connections', {}))
                _tc.metadata = _cube_data.get('metadata', {})
                _v4_graph[_cid] = _tc
            _conns = sum(len(_c.connections) for _c in _v4_graph.values())
            print(f"[V4] Loaded from JSON: {len(_v4_graph)} cubes, {_conns} connections", flush=True)
    # Validate constitutional cubes
    try:
        from app.routers.constitution_guard import validate_and_repair
        _repaired = validate_and_repair(_v4_graph)
        if _repaired > 0:
            print(f"[GUARD] Repaired {_repaired} constitutional cubes", flush=True)
    except Exception as _ge:
        pass
    return _v4_graph

import threading, time, json, os

def auto_save_loop(interval_sec=3600):
    """Save graph to JSON every hour."""
    while True:
        time.sleep(interval_sec)
        try:
            _path = '/data/skv/graph.json'
            _data = {}
            for _cid, _cube in _v4_graph.items():
                _data[_cid] = {'vector': _cube.vector.tolist(), 'connections': _cube.connections, 'outgoing_connections': _cube.outgoing_connections if hasattr(_cube, 'outgoing_connections') else {}, 'metadata': _cube.metadata}
            # Защита от сброса: не сохранять если связей < 100
            _total_edges = sum(len(_c.get('connections', {})) + len(_c.get('outgoing_connections', {})) for _c in _data.values())
            if _total_edges < 100:
                print(f"[V4] AUTO-SAVE SKIPPED: only {_total_edges} edges, disk protected", flush=True)
            else:
                with open(_path, 'w') as _f:
                    json.dump(_data, _f)
                print(f"[V4] Graph saved: {len(_v4_graph)} cubes, {_total_edges} edges", flush=True)
            print(f"[V4] Graph saved: {len(_v4_graph)} cubes", flush=True)
            
            # Decay all connections
            for _cube in _v4_graph.values():
                _cube.decay_connections()
        except Exception as _e:
            print(f"[V4] Save error: {_e}", flush=True)

# Start auto-save in background
