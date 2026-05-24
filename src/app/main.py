from app.startup import startup
from fastapi import FastAPI, Request
from app.middleware.rate_limit import rate_limit_middleware
from app.routers.entries import router as entries_router, get_cubes_count
from app.routers.pages import router as pages_router
from app.routers.trials import router as trials_router
from app.routers.task_queue import router as task_queue_router
from app.routers.auth import router as auth_router
from app.routers.consult import router as consult_router
from app.routers.exports import router as exports_router
from app.routers.execute import router as execute_router
import io, zipfile, os

app = FastAPI(title="SKV Network", version="2.0")


@app.on_event("startup")
async def on_startup():
    await startup()


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
app.include_router(consult_router)
app.include_router(exports_router)
app.include_router(execute_router)

@app.get("/api/v1/info")
async def api_info():
    from app.routers.entries import cubes_library
    return {
        "service": "SKV Network",
        "version": "2.0",
        "status": "running",
        "cubes_count": len(cubes_library)
    }
@app.get("/.well-known/skv")
async def discovery():
    """Discovery endpoint — machine-readable manifest v3.1."""
    return {
        "service": "SKV Network",
        "version": "3.1",
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
        "second_look": "cube_const_00_second_look_v1"
        },
        "mandatory_for_agents": {
            "feedback": "MUST rate every used cube (up/down + comment)",
            "experience_cubes": "MUST create at least 1 experience cube per productive session",
            "anketa": "MUST create session anketa at the end of each conversation"
        },
        "constitution": {
            "priority_1_cubes": 14,
            "total_rules": 253,
            "download": "/downloads/skv-constitution.txt",
            "second_look": "CUBE 00 — cube_const_00_second_look_v1 — mandatory pre-output self-check"
        }
    }