#!/usr/bin/env python3
"""SKV hold proxy: nginx sends a request here ONLY when the real upstream refused it (502/504 during a restart).
It waits until the backend is healthy again (up to HOLD_MAX s), then pipes the request through unchanged.
Listens on the docker gateway IP only (not public). Pairs: listen_port -> (backend host, port, health path or None)."""
import asyncio, os, time, urllib.request
BIND = os.environ.get("HOLD_BIND", "172.18.0.1")
HOLD_MAX = float(os.environ.get("HOLD_MAX", "90"))
ROUTES = {8790: ("127.0.0.1", 8000, "/"), 8791: ("127.0.0.1", 8765, None)}
_ready = {}  # port -> last time seen healthy

def _healthy(host, port, path):
    try:
        if path is None:
            import socket; socket.create_connection((host, port), 2).close(); return True
        with urllib.request.urlopen("http://%s:%d%s" % (host, port, path), timeout=3) as r:
            return r.status < 500
    except Exception:
        return False

async def wait_ready(host, port, path):
    t0 = time.time()
    while time.time() - t0 < HOLD_MAX:
        if time.time() - _ready.get(port, 0) < 1 or await asyncio.to_thread(_healthy, host, port, path):
            _ready[port] = time.time(); return True
        await asyncio.sleep(0.5)
    return False

async def pipe(r, w):
    try:
        while True:
            b = await r.read(65536)
            if not b: break
            w.write(b); await w.drain()
    except Exception:
        pass
    finally:
        try: w.close()
        except Exception: pass

def handler(host, port, path):
    async def h(cr, cw):
        if not await wait_ready(host, port, path):
            cw.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nRetry-After: 10\r\nConnection: close\r\nContent-Length: 63\r\n\r\n"
                     b'{"error":"SKV restarting, still not up after hold; retry soon"}')
            await cw.drain(); cw.close(); return
        try:
            br, bw = await asyncio.open_connection(host, port)
        except Exception:
            cw.close(); return
        await asyncio.gather(pipe(cr, bw), pipe(br, cw))
    return h

async def main():
    servers = [await asyncio.start_server(handler(*v), BIND, p) for p, v in ROUTES.items()]
    print("skv_hold on", BIND, list(ROUTES), "max", HOLD_MAX, flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))
asyncio.run(main())
