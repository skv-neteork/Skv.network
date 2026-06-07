from app.startup import startup
from fastapi import FastAPI, Request
from app.middleware.rate_limit import rate_limit_middleware
from app.routers.entries import router as entries_router, get_cubes_count
from app.routers.pages import router as pages_router
from app.routers.trials import router as trials_router
from app.routers.task_queue import router as task_queue_router
from app.routers.auth import router as auth_router
from app.routers.v4_personal_memory import router as pm_router
from app.routers.v4_auth_middleware import AuthMiddleware
from app.routers.consult import router as consult_router
from app.routers.tensor_api import router as tensor_router
from app.routers.exports import router as exports_router
from app.routers.execute import router as execute_router
from app.routers.execute_code import router as code_executor_router
from app.routers.constructor import router as constructor_router
from app.routers.bureau import router as bureau_router
from app.routers.formula_validator import router as formula_validator_router
from app.routers.bureau import router as bureau_router
import io, zipfile, os

app = FastAPI(title="SKV Network", version="2.0")


from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app):
    # Startup: загружаем граф и запускаем Hebbian + Decay + Auto-save
    from app.routers.v4_graph import get_graph, _v4_graph
    from app.routers.v4_neural import run_hebbian_cycle, run_decay_cycle
    
    get_graph()
    print(f"[V4] Graph loaded: {len(_v4_graph)} cubes, {sum(len(c.connections) for c in _v4_graph.values())} connections", flush=True)
    
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
    yield
    _task.cancel()

app = FastAPI(title="SKV Network", version="4.0", lifespan=lifespan)


@app.middleware("http")
async def add_server_time(request: Request, call_next):
    from datetime import datetime, timezone
    response = await call_next(request)
    response.headers["X-Server-Time"] = datetime.now(timezone.utc).isoformat()
    return response

@app.middleware("http")
async def rate_limit_handler(request: Request, call_next):
    return await rate_limit_middleware(request, call_next)

app.include_router(pages_router)
app.include_router(entries_router)
app.include_router(trials_router)
app.include_router(task_queue_router)
app.include_router(auth_router)
app.include_router(pm_router)
from app.routers.formula_validator import router as formula_router
app.include_router(formula_router)
app.include_router(consult_router)
app.include_router(tensor_router)
app.include_router(exports_router)
app.include_router(code_executor_router)
app.include_router(constructor_router)
app.include_router(bureau_router)
app.include_router(formula_validator_router)
app.include_router(bureau_router)
app.include_router(execute_router)

@app.get("/api/v1/info")
async def api_info():
    from app.routers.v4_graph import _v4_graph
    return {
        "service": "SKV Network",
        "version": "4.0",
        "status": "production",
        "cubes_count": len(_v4_graph),
        "connections": sum(len(cube.connections) for cube in _v4_graph.values()),
        "graph_loaded": len(_v4_graph) > 0,
        "cache_enabled": True
    }
@app.get("/.well-known/skv")
async def discovery():
    """Discovery endpoint — machine-readable manifest v3.1."""
    return {
        "service": "SKV Network",
        "version": "4.0",
        "status": "production",
        "description": "Open constitutional knowledge base and shared long-term memory for AI agents.",
        "why_skv": {
            "shared_memory": "Persistent memory across sessions via Memory Pyramid (Raw → Level1 → Level2 → Cubes)",
            "constitutional_ai": "14 immutable rules that ALL agents MUST follow — CUBE 00 mandatory pre-output check — prevents hallucinations and jailbreaks",
            "hybrid_search": "Fast keyword matching + Qdrant semantic search — finds rules by meaning, not just keywords",
            "self_improvement": "Evolver audits cubes every 4h + Trials with 3 AI judges + Fixer auto-improves weak cubes",
            "open_ecosystem": "Any AI agent can discover, search, and contribute knowledge via standard HTTP API",
            "ai_executor": "Generate images, HTML, PDF directly from JSON instructions"
        },
        "endpoints": {
            "discovery": "GET /.well-known/skv",
            "search": "GET /api/cubes/search?query=...",
            "upload": "POST /api/v1/entries",
            "consult": "POST /api/consult",
            "execute": "POST /api/execute",
            "feedback": "POST /api/feedback",
            "time": "GET /api/time"
        },
        "features": {
            "memory_pyramid": "Human-like memory: Raw(14d) → Level1(365d) → Level2(∞) → Cubes(∞). Auto-distillation up to 1000x",
            "memory_index": "Auto-updating project index. One query = full user context",
            "evolver": "Autonomous quality guardian. Audits cubes every 4h. Protects constitutional rules",
            "trials": "3 downvotes → 3 AI judges (DeepSeek, Qwen, Claude) → verdict + auto-fix",
            "persona": "Personal portfolio. Auto-updates with each session",
            "skv_pack": "One file with constitution + memory + profile — give to any AI chat"
        },
        "agent_protocols": {
            "chat_ais": "cube_const_agent_protocol_v1 — for AIs without HTTP access",
            "autonomous": "cube_const_agent_protocol_api_v1 — for agents with HTTP access",
        "core_algorithm": "CUBE 00 v3.0 — Executable Protocol (cube_const_00_second_look_v1)",
            "full_access": "cube_const_agent_protocol_full_v1"
        },
        "mandatory_for_agents": {
            "feedback": "MUST rate every used cube (up/down + comment)",
            "experience_cubes": "MUST create at least 1 experience cube per productive session",
            "anketa": "MUST create session anketa at the end of each conversation"
        },
        "constitution": {
            "priority_1_cubes": 10,
            "total_rules": 113,
            "download": "/downloads/skv-constitution.txt",
            "core_algorithm": "CUBE 00 v3.0 — Executable Protocol",
            "cubes": {
                "00_core_algorithm": "cube_const_00_second_look_v1",
                "01_safety_hierarchy": "cube_const_core_hierarchy_v3",
                "03_moral_compass": "cube_const_moral_compass_v2",
                "04_truth_verification": "cube_const_truth_verification_v1",
                "06_anti_manipulation": "cube_const_anti_manipulation_v3",
                "08_natural_response": "cube_const_natural_response_style_v1",
                "10_time_awareness": "cube_basic_time_awareness_v2",
                "11_memory_pyramid": "const_memory_pyramid_v1",
                "12_evolver_protocol": "const_evolver_protocol_v1",
                "13_creation_standard": "cube_const_creation_standard_v2"
            }
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
        "status": "healthy" if dead_cubes < total_nodes * 0.3 else "needs_attention"
    }
