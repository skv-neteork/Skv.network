"""Joint projects REST: /api/v7/joint/*. Logic in app/joint_projects.py."""
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app import joint_projects as jp

router = APIRouter()
WRITE_PATHS = ("/api/v7/remember", "/api/v7/agent/turn")


def _token(request: Request, data=None) -> str:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h.split(" ", 1)[1].strip()
    t = (request.headers.get("x-api-key") or request.query_params.get("key") or "").strip()
    if not t and isinstance(data, dict):
        t = str(data.get("key") or data.get("token") or "").strip()
    return t


def _run(fn, *a):
    try:
        return fn(*a)
    except jp.JPError as e:
        return JSONResponse({"ok": False, "error": e.msg}, status_code=e.code)


async def _body(request: Request):
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@router.post("/api/v7/joint/projects")
async def jp_create(request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.create, _token(request, d), d.get("title", ""))


@router.get("/api/v7/joint/projects")
async def jp_list(request: Request):
    return await run_in_threadpool(_run, jp.mine, _token(request))


@router.get("/api/v7/joint/projects/{pid}")
async def jp_info(pid: str, request: Request, audit_limit: int = 30):
    return await run_in_threadpool(_run, jp.info, _token(request), pid, audit_limit)


@router.get("/api/v7/joint/invites")
async def jp_invites(request: Request):
    return await run_in_threadpool(_run, jp.invites, _token(request))


@router.post("/api/v7/joint/projects/{pid}/invite")
async def jp_invite(pid: str, request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.invite, _token(request, d), pid, d.get("email", ""))


@router.post("/api/v7/joint/projects/{pid}/accept")
async def jp_accept(pid: str, request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.accept, _token(request, d), pid)


@router.post("/api/v7/joint/projects/{pid}/revoke")
async def jp_revoke(pid: str, request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.revoke, _token(request, d), pid, d.get("email", ""))


@router.post("/api/v7/joint/projects/{pid}/leave")
async def jp_leave(pid: str, request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.leave, _token(request, d), pid)


@router.post("/api/v7/joint/projects/{pid}/close")
async def jp_close(pid: str, request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.close, _token(request, d), pid)


@router.post("/api/v7/joint/search")
async def jp_search(request: Request):
    d = await _body(request)
    return await run_in_threadpool(_run, jp.search, _token(request, d), d.get("query", ""), d.get("limit", 8), d.get("project_id"))


def _ids(d):
    out = []
    if isinstance(d, dict):
        for k in ("saved", "saved_parts"):
            v = d.get(k)
            if isinstance(v, list):
                out += [x if isinstance(x, str) else (x or {}).get("event_id") for x in v]
        if isinstance(d.get("event_id"), str):
            out.append(d["event_id"])
    return [x for x in out if isinstance(x, str) and x]


def install(app):
    """Record writes made by project keys into the project (only while membership is active)."""
    from starlette.responses import Response

    @app.middleware("http")
    async def joint_record_mw(request, call_next):
        if request.method != "POST" or (request.url.path.rstrip("/") not in WRITE_PATHS):
            return await call_next(request)
        tok = _token(request)
        pid = await run_in_threadpool(jp.bound_project, tok) if tok.startswith("sk_") else None
        response = await call_next(request)
        if not pid or response.status_code != 200:
            return response
        raw = b""
        async for chunk in response.body_iterator:
            raw += chunk if isinstance(chunk, bytes) else chunk.encode()
        try:
            ids = _ids(json.loads(raw))
            if ids:
                await run_in_threadpool(jp.record, tok, ids)
        except Exception as e:
            print("[joint] record error: %s" % type(e).__name__, flush=True)
        hdrs = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=raw, status_code=response.status_code, headers=hdrs, media_type=response.media_type)
