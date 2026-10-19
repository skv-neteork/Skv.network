"""In-process background job counter (for safe restarts). GET /_ops/inflight from localhost only."""
import threading, time
_lock = threading.Lock()
_jobs = {}   # name -> count


class track:
    def __init__(self, name):
        self.name = name
    def __enter__(self):
        with _lock:
            _jobs[self.name] = _jobs.get(self.name, 0) + 1
        return self
    def __exit__(self, *a):
        with _lock:
            _jobs[self.name] = max(0, _jobs.get(self.name, 0) - 1)
        return False


def snapshot():
    with _lock:
        jobs = {k: v for k, v in _jobs.items() if v}
    try:
        from app.routers import import_dialogs as _imp
        with _imp._cycle_lock:
            if _imp._cycle_state:
                jobs["import_cycle"] = len(_imp._cycle_state)
    except Exception:
        pass
    return {"busy": bool(jobs), "jobs": jobs, "ts": time.time()}
