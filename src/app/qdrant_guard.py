"""Qdrant is optional and NOT part of the v7 stack (vectors live in SQLite; no skv_qdrant container or
data exists since the v7 migration). Set SKV_QDRANT_HOST to point legacy v4 code at a real Qdrant.
Qdrant is optional (legacy cube fallback). If host skv_qdrant does not resolve, replace QdrantClient
with a quiet stub: searches return empty, writes raise QdrantUnavailable. Checked once per process (re-checked every 10 min)."""
import os, socket, time
HOST = os.getenv("SKV_QDRANT_HOST", "skv_qdrant")
_state = {"ok": None, "t": 0.0}
class QdrantUnavailable(RuntimeError): pass
def available(host=None):
    host = host or HOST
    if _state["ok"] is None or time.time() - _state["t"] > 600:
        try: socket.getaddrinfo(host, 6333); _state["ok"] = True
        except OSError: _state["ok"] = False
        _state["t"] = time.time()
    return _state["ok"]
class _Empty:
    points = []
class _Stub:
    def __init__(self, *a, **k): pass
    def query_points(self, *a, **k): return _Empty()
    def search(self, *a, **k): return []
    def scroll(self, *a, **k): return ([], None)
    def __getattr__(self, name):
        def _f(*a, **k): raise QdrantUnavailable("qdrant disabled (skv_qdrant not resolvable)")
        return _f
def install():
    try:
        import qdrant_client
    except Exception:
        return False
    if available(): return True
    real = qdrant_client.QdrantClient
    class Guarded:
        def __new__(cls, *a, **k):
            if available():
                if k.get("host") == "skv_qdrant": k["host"] = HOST
                return real(*a, **k)
            return _Stub()
    qdrant_client.QdrantClient = Guarded
    print(f"[qdrant_guard] legacy Qdrant not deployed ({HOST}): v4 Qdrant paths return empty; v7 search uses SQLite vectors", flush=True)
    return False
