"""SKV v4.0 — Shared neural graph."""
import json, os, numpy as np
from app.routers.tensor_cube import TensorCube

_v4_graph = {}

def get_graph():
    global _v4_graph
    if not _v4_graph:
        _path = os.path.join(os.path.dirname(__file__), 'v4_graph.json')
        if os.path.exists(_path):
            with open(_path, 'r') as _f:
                _data = json.load(_f)
            for _cid, _cube_data in _data.items():
                _tc = TensorCube(_cid, np.array(_cube_data['vector'], dtype=np.float32))
                _tc.connections = _cube_data.get('connections', {})
                _tc.metadata = _cube_data.get('metadata', {})
                _v4_graph[_cid] = _tc
            _conns = sum(len(_c.connections) for _c in _v4_graph.values())
            print(f"[V4] Loaded from JSON: {len(_v4_graph)} cubes, {_conns} connections", flush=True)
    return _v4_graph
