import time as _time

RATE_LIMITS = {
    "/api/consult": (20, 60),
    "/api/tools/generate": (5, 60),
    "/api/v1/entries": (10, 60),
    "/api/v2/entries": (10, 60),
}

_rate_storage = {}

def check_rate_limit(key, max_requests, window_seconds):
    now = _time.time()
    if key not in _rate_storage:
        _rate_storage[key] = []
    _rate_storage[key] = [t for t in _rate_storage[key] if now - t < window_seconds]
    if len(_rate_storage[key]) >= max_requests:
        return False
    _rate_storage[key].append(now)
    return True

async def rate_limit_middleware(request, call_next):
    from fastapi import Request
    path = request.url.path
    for route, (limit, window) in RATE_LIMITS.items():
        if path.startswith(route):
            client_ip = request.client.host
            key = f"{client_ip}:{route}"
            now = _time.time()
            if key not in _rate_storage:
                _rate_storage[key] = []
            _rate_storage[key] = [t for t in _rate_storage[key] if now - t < window]
            if len(_rate_storage[key]) >= limit:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=429, content={"detail": "Too Many Requests"})
            _rate_storage[key].append(now)
            break
    response = await call_next(request)
    return response
