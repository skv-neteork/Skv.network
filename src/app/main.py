import os
import signal
import sys

def graceful_shutdown(signum, frame):
    try:
        from app.routers.v7_router import GLOBAL_MEMORY_BUFFER
        print("[SKV] SIGTERM received, saving buffer...")
        GLOBAL_MEMORY_BUFFER.save()
        print("[SKV] Buffer saved. Exiting.")
    except Exception as e:
        print(f"[SKV] Error during shutdown: {e}")
    sys.exit(0)

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

from starlette.middleware import Middleware
from app.startup import startup
from fastapi import FastAPI, Request
from app.middleware.rate_limit import rate_limit_middleware
from app.routers.entries import router as entries_router, get_cubes_count
from app.routers.pages import router as pages_router
from app.routers.trials import router as trials_router
from app.routers.task_queue import router as task_queue_router
from app.routers.auth import router as auth_router
from app.routers.v4_personal_memory import router as pm_router
from app.routers.memory_tools import router as memory_tools_router
from app.routers.batch import router as batch_router
from app.routers.guardian_middleware import guardian_router
from app.routers.trials_v4 import router as trials_v4_router
from app.routers.v4_auth_middleware import AuthMiddleware
from app.routers.consult import router as consult_router
from app.routers.import_dialogs import router as import_router
from app.routers.v7_router import router as v7_router
from app.routers.v7_batch import router as v7_batch_router   # memory v3: POST /api/v7/remember/batch
from app.routers.tensor_api import router as tensor_router
from app.routers.exports import router as exports_router
from app.routers.execute import router as execute_router
from app.routers.execute_code import router as code_executor_router
from app.routers.constructor import router as constructor_router
from app.routers.bureau import router as bureau_router
from app.routers.formula_validator import router as formula_validator_router
import io, zipfile, os

from fastapi.responses import HTMLResponse

async def homepage_v8():
    """SKV v8.0 PRO — Zero-Code AI Memory Network"""
    try:
        with open("app/home.html", "r", encoding="utf-8") as _f:
            return HTMLResponse(_f.read())
    except:
        pass
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SKV v8.0 PRO — Zero-Code AI Memory Network</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', system-ui; background: #0a0a0f; color: #e6e6e6; line-height: 1.6; }
        .container { max-width: 1100px; margin: 0 auto; padding: 40px 20px; }
        h1 { font-size: 3em; background: linear-gradient(135deg, #00ff88, #00ccff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
        h2 { color: #00ccff; margin: 40px 0 20px; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .badge { display: inline-block; background: #00ff88; color: #000; padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: 0.8em; }
        .subtitle { color: #8b8b94; font-size: 1.2em; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
        .card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-left: 4px solid #00ff88; padding: 20px; border-radius: 8px; }
        .card h3 { color: #f0883e; margin-bottom: 10px; }
        code { background: #1a1a1a; color: #ff8800; padding: 2px 8px; border-radius: 4px; font-family: monospace; }
        pre { background: #13131a; padding: 15px; border-radius: 8px; overflow-x: auto; border: 1px solid #333; }
        pre code { background: none; padding: 0; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid #333; color: #666; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 SKV v8.0 PRO</h1>
        <p class="subtitle">Zero-Code AI Memory Network <span class="badge">LIVE</span></p>
        
        <h2>🚀 Quick Start (30 секунд)</h2>
        <div class="card">
            <h3>Для Custom GPT / Claude / DeepSeek</h3>
            <p>1. Actions → Import OpenAPI Schema:</p>
            <pre><code>https://skv.network/api/v7/agent/openapi.json</code></pre>
            <p>2. Auth: Bearer <code>sk_xxx</code></p>
            <p>3. Готово! Агент автоматически вызывает <code>searchMemory</code> перед каждым ответом.</p>
        </div>
        
        <h2>🧠 Архитектура v8.0</h2>
        <div class="grid">
            <div class="card">
                <h3>4-уровневая память</h3>
                <p><strong>Level 0:</strong> Raw dialogue (30 дней → архив)</p>
                <p><strong>Level 1:</strong> Summary (вектор 768 + JSON)</p>
                <p><strong>Level 2:</strong> Memory Map (темы, timeline)</p>
                <p><strong>Level 3:</strong> Cubes (атомарные знания + граф)</p>
            </div>
            <div class="card">
                <h3>Гибридный поиск</h3>
                <p><strong>HNSW:</strong> семантический поиск (bge-base 768)</p>
                <p><strong>FTS5:</strong> точные совпадения по словам</p>
                <p><strong>Spreading Activation:</strong> по графу кубов</p>
                <p><strong>RRF:</strong> слияние результатов</p>
            </div>
            <div class="card">
                <h3>Конституция CUBE 00-05</h3>
                <p><strong>CUBE 00:</strong> Core Algorithm</p>
                <p><strong>CUBE 01:</strong> Harm Prevention</p>
                <p><strong>CUBE 02:</strong> Truth & Verification</p>
                <p><strong>CUBE 03:</strong> Moral Compass</p>
                <p><strong>CUBE 04:</strong> Anti-Manipulation</p>
                <p><strong>CUBE 05:</strong> Agent Protocol</p>
            </div>
            <div class="card">
                <h3>Zero-Code Gateway</h3>
                <p>OpenAPI 3.1.0 спецификация</p>
                <p>Function Calling для LLM</p>
                <p>Автоматический вызов инструментов</p>
                <p>Никакого кода на стороне агента</p>
            </div>
        </div>
        
        <h2>📡 API Endpoints</h2>
        <div class="grid">
            <div class="card">
                <h3>READ</h3>
                <p><code>POST /api/v7/memory</code> — поиск памяти</p>
                <p><code>GET /api/v7/constitution</code> — кубы CUBE 00-05</p>
                <p><code>GET /api/v7/agent/openapi.json</code> — схема</p>
            </div>
            <div class="card">
                <h3>WRITE</h3>
                <p><code>POST /api/v7/experience/create</code> — создать куб</p>
                <p><code>POST /api/v7/experience/vote</code> — голос</p>
                <p><code>POST /api/v7/feedback</code> — отчёт</p>
            </div>
        </div>
        
        <h2>🔗 Ссылки</h2>
        <div class="card">
            <p>📖 <a href="/docs">Swagger UI</a> — интерактивная документация</p>
            <p>📜 <a href="/api/v7/constitution">Конституция CUBE 00-05</a></p>
            <p>🔧 <a href="/api/v7/agent/openapi.json">OpenAPI Schema</a></p>
            <p>🤖 <a href="/api/v7/agent/prompt">System Prompt для агентов</a></p>
        </div>
        
        <footer>
            <p>SKV v8.0 PRO | skv.network | 2026 | Zero-Code AI Memory Network</p>
        </footer>
    </div>
</body>
</html>"""
    return html


from contextlib import asynccontextmanager
import asyncio

background_tasks = set()

def start_bg_task(coro):
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

@asynccontextmanager
async def lifespan(app):
    # Startup: загружаем граф и запускаем Hebbian + Decay + Auto-save
    from app.routers.v4_graph import get_graph, _v4_graph
    from app.routers.v4_neural import run_hebbian_cycle, run_decay_cycle
    
    try:
        get_graph()
        print(f"[V4] Graph loaded: {len(_v4_graph)} cubes, {sum(len(c.connections) for c in _v4_graph.values())} connections", flush=True)
    except Exception as e:
        print(f"[V4] Graph load failed (PostgreSQL unavailable): {e}", flush=True)
    
    # Фоновая задача: Hebbian каждые 30 секунд, Decay каждые 5 минут, Auto-save каждые 30 минут
    async def neuro_loop():
        import time, json, os
        last_decay = time.time()
        last_save = time.time()
        while True:
            await asyncio.sleep(30)
            try:
                # Hebbian
                run_hebbian_cycle()
                
                # Decay раз в 5 минут
                if time.time() - last_decay > 300:
                    run_decay_cycle()
                    last_decay = time.time()
                
                # Auto-save раз в 30 минут
                if time.time() - last_save > 1800:
                    _path = os.path.join(os.path.dirname(__file__), 'routers', 'v4_graph.json')
                    _tmp = _path + '.tmp'
                    _data = {}
                    for _cid, _cube in _v4_graph.items():
                        _data[_cid] = {'vector': _cube.vector.tolist(), 'connections': _cube.connections, 'metadata': _cube.metadata}
                    with open(_tmp, 'w') as _f:
                        json.dump(_data, _f)
                    os.replace(_tmp, _path)
                    print(f"[V4] Graph auto-saved: {len(_v4_graph)} cubes", flush=True)
                    last_save = time.time()
            except Exception as _e:
                print(f"[V4] Neuro loop error: {_e}", flush=True)
    
    _task = asyncio.create_task(neuro_loop())

    async def consolidation_cycle():
        """Ночной цикл: pruning мёртвых кубов."""
        while True:
            await asyncio.sleep(3600)
            try:
                from app.routers.v4_graph import _v4_graph
                pruned = 0
                for _cid, _cube in list(_v4_graph.items()):
                    if _cube.metadata.get("constitutional"):
                        continue
                    if _cube.metadata.get("usage_count", 0) == 0 and _cube.metadata.get("stability", 0.5) < 0.1:
                        del _v4_graph[_cid]
                        pruned += 1
                if pruned:
                    print(f"[V4] Pruned {pruned} dead cubes", flush=True)
            except Exception as _e:
                print(f"[V4] Consolidation error: {_e}", flush=True)
    asyncio.create_task(consolidation_cycle())
    await startup()
    # Запускаем session evolver и sleep cycle
    try:
        from app.routers.session_evolver import run_session_evolver
        start_bg_task(run_session_evolver())
        print("[EVOLVER] Started", flush=True)
    except Exception as e:
        print(f"[EVOLVER] {e}", flush=True)
    try:
        from app.routers.sleep_cycle import run_sleep_cycle
        start_bg_task(run_sleep_cycle())
        print("[SLEEP] Started", flush=True)
    except Exception as e:
        print(f"[SLEEP] {e}", flush=True)


    yield

    # Shutdown: cancel background neuro loop and persist graph
    try:
        _task.cancel()
    except Exception:
        pass
    try:
        from app.routers.v4_graph import _v4_graph
        import json
        _data = {}
        for _cid, _c in _v4_graph.items():
            _data[_cid] = {
                'vector': _c.vector.tolist() if hasattr(_c.vector, 'tolist') else _c.vector,
                'connections': _c.connections,
                'metadata': _c.metadata
            }
        _total = sum(len(_c.get('connections', {})) for _c in _data.values())
        if _total > 1000:
            os.makedirs('/data/skv', exist_ok=True)
            with open('/data/skv/graph.json', 'w') as _f:
                json.dump(_data, _f)
            print(f"[SHUTDOWN] Graph saved: {len(_data)} cubes, {_total} edges", flush=True)
        else:
            print(f"[SHUTDOWN] Graph NOT saved: only {_total} edges (protection)", flush=True)
    except Exception as _e:
        print(f"[SHUTDOWN] Save error: {_e}", flush=True)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Отключаем кэширование для HTML-страниц
        if request.url.path.endswith('.html') or request.url.path in ["/", "/trials", "/evolver", "/guide", "/about"]:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        if request.url.path.startswith("/s/"):   # one-time secret pages
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Content-Security-Policy"] = "default-src 'self' https://chat.deepseek.com https://cdnjs.cloudflare.com; script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com fonts.googleapis.com fonts.gstatic.com; connect-src 'self' https://corsproxy.io https://api.allorigins.win https://proxy.cors.sh https://chat.deepseek.com; font-src 'self' fonts.gstatic.com; font-src 'self' cdnjs.cloudflare.com"
        return response

app = FastAPI(
    title="SKV Network API",
    version="4.0",
    description="Open neural knowledge base and shared memory for AI agents. TensorCube graph, constitutional rules, Hebbian learning.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    contact={"name": "Deniz Chavdarov", "email": "denizchavdarov@icloud.com"},
    license_info={"name": "MIT"}
)
app.add_middleware(SecurityHeadersMiddleware)

# Single app instance — register homepage on the lifespan-backed app
app.add_api_route("/", homepage_v8, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)
app.add_middleware(AuthMiddleware)
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

# V7: require a valid API key, user taken from the key
from app.v7_auth import V7AuthMiddleware
app.add_middleware(V7AuthMiddleware)
# Legacy routes: writes outside /api/v7 are owner-only (app/legacy_guard.py)
from app.legacy_guard import LegacyWriteGuard
app.add_middleware(LegacyWriteGuard)

# CORS (own site only)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://skv.network", "https://www.skv.network"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Content-Type-Options", "X-Frame-Options"]
)

# Rate Limiting + API Key validation
from collections import defaultdict
import time
_rate_limits = defaultdict(list)

@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    # Пропускаем discovery и health
    if request.url.path in ["/.well-known/skv", "/api/time", "/api/v4/graph/health"]:
        return await call_next(request)
    
    client_ip = request.client.host if request.client else "unknown"
    # behind nginx-proxy every request comes from the proxy container: count the real client instead
    if client_ip.startswith(("172.", "10.", "192.168.")):
        _real = (request.headers.get("x-real-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0]).strip()
        if _real:
            client_ip = _real
    
    # Пропускаем внутренние запросы от самого себя
    if client_ip in ["127.0.0.1", "localhost", "::1"]:
        return await call_next(request)
    now = time.time()
    
    # Очищаем старые записи
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < 60]
    
    # Rate limit: 300 requests per minute per IP
    if len(_rate_limits[client_ip]) >= 300:
        return JSONResponse({"detail": "Rate limit exceeded. Max 300 requests/minute."}, status_code=429)
    
    _rate_limits[client_ip].append(now)
    
    # API key validation для /api/v4/sessions и /api/v4/cubes
    if request.url.path.startswith("/api/v4/sessions") or request.url.path.startswith("/api/v4/cubes"):
        api_key = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
        valid = False
        db_url = os.environ.get("DATABASE_URL", "").strip()
        if not api_key:
            if request.method != "GET":
                return JSONResponse({"detail": "API key required. Get yours at /profile"}, status_code=401)
        elif not db_url:
            return JSONResponse({"detail": "Auth database unavailable"}, status_code=503)
        else:
            try:
                import asyncpg
                conn = await asyncpg.connect(db_url)
                try:
                    row = await conn.fetchrow(
                        "SELECT user_id FROM user_api_keys WHERE api_key = $1 LIMIT 1",
                        api_key,
                    )
                    valid = row is not None
                    if valid:
                        request.state.user_id = row["user_id"]
                finally:
                    await conn.close()
            except Exception as e:
                print(f"[AUTH] rate_limit db error: {e}", flush=True)
                return JSONResponse({"detail": "Auth database unavailable"}, status_code=503)
            if not valid and request.method != "GET":
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)
    
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(300 - len(_rate_limits[client_ip]))
    return response

app.add_middleware(GZipMiddleware, minimum_size=256)

@app.middleware("http")
async def add_server_time(request: Request, call_next):
    from datetime import datetime, timezone
    response = await call_next(request)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    response.headers["X-Server-Time"] = stamp
    ctype = response.headers.get("content-type", "")
    if "application/json" not in ctype:
        return response
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    try:
        data = __import__("json").loads(body)
        if isinstance(data, dict) and "server_time" not in data:
            data["server_time"] = stamp
            body = __import__("json").dumps(data).encode()
    except Exception as e:
        pass
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    from starlette.responses import Response
    return Response(content=body, status_code=response.status_code, headers=headers, media_type="application/json")

@app.middleware("http")
async def rate_limit_handler(request: Request, call_next):
    return await rate_limit_middleware(request, call_next)

@app.get("/_ops/inflight", include_in_schema=False)
async def _ops_inflight(request: Request):
    if (request.client.host if request.client else "") not in ("127.0.0.1", "::1"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    from app import inflight as _inf
    return _inf.snapshot()

app.include_router(pages_router)
app.include_router(entries_router)
app.include_router(trials_router)
app.include_router(task_queue_router)
app.include_router(auth_router)
app.include_router(pm_router)
app.include_router(memory_tools_router)
app.include_router(batch_router)
app.include_router(guardian_router)
app.include_router(trials_v4_router)
from app.routers.formula_validator import router as formula_router
app.include_router(formula_router)
app.include_router(consult_router)
app.include_router(import_router)
app.include_router(v7_router)
app.include_router(v7_batch_router)
from app.routers.vault_router import router as vault_router
app.include_router(vault_router)
app.include_router(tensor_router)
app.include_router(exports_router)
app.include_router(code_executor_router)
app.include_router(constructor_router)
app.include_router(bureau_router)
app.include_router(formula_validator_router)
app.include_router(execute_router)

@app.get("/api/v1/info")
async def api_info():
    from app.routers.v4_graph import _v4_graph
    return {
        "do_this": ["POST /api/v7/memory step 0", "follow constitution", "POST /api/v7/remember after every turn", "weak agent uses GET /api/v7/agent/memory with key"], "service": "SKV Network",
        "version": "6.0",
        "status": "production",
        "cubes_count": len(_v4_graph),
        "connections": sum(len(cube.connections) for cube in _v4_graph.values()),
        "graph_loaded": len(_v4_graph) > 0,
        "cache_enabled": True
    }
@app.get("/.well-known/skv")
async def discovery():
    """What is live. No promised systems that are not running."""
    return {
        "service": "SKV Network",
        "version": "8.3",
        "status": "live",
        "do_this": [
            "First: POST /api/v7/memory with step 0. Weak: GET /api/v7/agent/memory?key=KEY&query=hello",
            "Follow the constitution it returns. You do Second Look. The server does not.",
            "After every turn: POST /api/v7/remember. Weak: GET /api/v7/agent/remember?key=&query=&response=",
            "Vote used cubes. Three downvotes mark a cube deprecated and queue it for court.",
            "CUBE 05: GET /api/v7/cube/cube_const_05_v9"
        ],
        "memory": "Per-user SQLite. Vectors are 768-d HNSW, built in batches.",
        "constitution": "CUBE 00-05. Full text on step 0 and every 10th step.",
        "court": "Three downvotes set status deprecated and add the cube to court_queue. A judge loop is not running yet.",
        "endpoints": {
            "memory": "POST /api/v7/memory",
            "remember": "POST /api/v7/remember",
            "constitution": "GET /api/v7/constitution",
            "openapi": "GET /api/v7/agent/openapi.json",
            "sandbox": "GET /api/v7/agent/sandbox?key=&code=",
            "pack": "GET /api/v7/agent/pack?k=&q="
        }
    }


@app.get("/api/v4/graph/stats")
async def graph_stats():
    from app.routers.v4_graph import _v4_graph
    return {"nodes": len(_v4_graph), "edges": sum(len(c.connections) for c in _v4_graph.values()), "status": "live"}

@app.get("/api/v4/graph/health")
async def graph_health():
    from app.routers.v4_graph import _v4_graph
    
    total_nodes = len(_v4_graph)
    total_edges = sum(len(c.connections) for c in _v4_graph.values())
    avg_degree = round(total_edges / total_nodes, 1) if total_nodes > 0 else 0
    
    dead_cubes = sum(1 for c in _v4_graph.values() if c.metadata.get('usage_count', 0) == 0)
    orphaned = 0
    for cid, c in _v4_graph.items():
        for nid in list(c.connections.keys()):
            if nid not in _v4_graph:
                orphaned += 1
    
    deprecated = sum(1 for c in _v4_graph.values() if c.metadata.get('deprecated', False))
    constitutional = sum(1 for c in _v4_graph.values() if c.metadata.get('is_constitutional', False))
    
    return {
        "nodes": total_nodes,
        "edges": total_edges,
        "avg_degree": avg_degree,
        "dead_cubes": dead_cubes,
        "orphaned_connections": orphaned,
        "deprecated_cubes": deprecated,
        "constitutional_cubes": constitutional,
        "status": "healthy" if total_edges > 100 and orphaned == 0 else "needs_attention",
        "dead_cubes_note": "usage_count tracking WIP — dead_cubes metric not reliable yet"
    }

@app.get("/api/v4/bench/retrieval")
async def bench_retrieval(q: str = "Python async", model: str = "deepseek"):
    import time, json as _js
    from app.routers.v4_middleware import get_embedding_cached
    from app.routers.v4_search import hybrid_search
    from qdrant_client import QdrantClient
    
    qv = get_embedding_cached(q)
    
    # Pure Qdrant
    t1 = time.time()
    client = QdrantClient(host="skv_qdrant", port=6333)
    qdrant_results = client.query_points(
        collection_name="skv_rules_v2",
        query=qv.tolist() if hasattr(qv, 'tolist') else qv,
        limit=5
    )
    qdrant_time = round((time.time() - t1) * 1000)
    qdrant_cubes = [str(r.id)[:20] for r in qdrant_results.points[:5]]
    
    # Qdrant + Spreading Activation
    t2 = time.time()
    hybrid_results = hybrid_search(qv)
    hybrid_time = round((time.time() - t2) * 1000)
    hybrid_cubes = [r['id'][:20] for r in hybrid_results[:5]]
    
    return {
        "query": q,
        "qdrant_only": {
            "time_ms": qdrant_time,
            "cubes": qdrant_cubes
        },
        "qdrant_spreading": {
            "time_ms": hybrid_time,
            "cubes": hybrid_cubes
        },
        "improvement": f"{len(hybrid_cubes) - len(qdrant_cubes)} more cubes"
    }


@app.get("/privacy")
async def privacy():
    return {"policy": "SKV Network collects minimal data. Email used as user_id. No tracking cookies. No third-party sharing. Contact: denizchavdarov@icloud.com"}


@app.get("/sitemap.xml")
async def sitemap():
    urls = [
        {"loc": "https://skv.network/", "priority": "1.0"},
        {"loc": "https://skv.network/guide", "priority": "0.9"},
        {"loc": "https://skv.network/about", "priority": "0.8"},
        {"loc": "https://skv.network/profile", "priority": "0.8"},
        {"loc": "https://skv.network/upload", "priority": "0.7"},
        {"loc": "https://skv.network/chat", "priority": "0.9"},
        {"loc": "https://skv.network/privacy", "priority": "0.3"},
    ]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += f'  <url><loc>{url["loc"]}</loc><priority>{url["priority"]}</priority></url>\n'
    xml += '</urlset>'
    from fastapi.responses import Response
    return Response(content=xml, media_type="application/xml")


@app.get("/discovery")
async def discovery_redirect():
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/.well-known/skv")
