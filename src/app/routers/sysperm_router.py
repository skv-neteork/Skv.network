"""System-file permission (owner decision 2026-10-19).
An agent touches system files only under an explicit, time-limited owner grant; without one it must refuse.
Every check and every action is written to an audit log.
  POST /api/v7/sysperm/grant   {scope, ttl_minutes, actions, agent, note}   owner only -> grant_id
  POST /api/v7/sysperm/check   {path, action, agent}                        -> allowed + grant_id (refusals are logged too)
  POST /api/v7/sysperm/log     {grant_id, path, action, result, detail}     agent reports what it did
  POST /api/v7/sysperm/revoke  {grant_id}                                   owner only
  GET  /api/v7/sysperm/grants  /  GET /api/v7/sysperm/audit                 owner only
The user comes from the API key (V7AuthMiddleware puts it into ?user_id)."""
import os, json, secrets, sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v7/sysperm")
DB = os.environ.get("SKV_SYSPERM_DB", "/data/skv/metadata_store/shared_master.db")
MAX_TTL_MIN = 240
ACTIONS = {"read", "write", "exec", "delete"}


def _owners():
    return {u.strip().lower() for u in os.environ.get("SKV_SHELL_OWNERS", "denizchavdarov@gmail.com").split(",") if u.strip()}


def _now():
    return datetime.now(timezone.utc)


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS sys_grants (grant_id TEXT PRIMARY KEY, owner TEXT, scope TEXT, actions TEXT, agent TEXT, note TEXT, created_at TEXT, expires_at TEXT, revoked_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS sys_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user_id TEXT, agent TEXT, grant_id TEXT, event TEXT, action TEXT, path TEXT, result TEXT, detail TEXT)")
    return c


def _uid(request):
    uid = (request.query_params.get("user_id") or "").strip()
    if not uid:
        raise HTTPException(401, "API key required")
    return uid


def _owner(request):
    uid = _uid(request)
    if uid.lower() not in _owners():
        raise HTTPException(403, "owner only")
    return uid


def _norm(p):
    p = (p or "").strip()
    if not p.startswith("/") or "\x00" in p:
        raise HTTPException(422, "absolute path required")
    return os.path.normpath(p)


def _covers(scope, path):
    scope = _norm(scope)
    return path == scope or path.startswith(scope.rstrip("/") + "/")


def _audit(c, uid, agent, gid, event, action="", path="", result="", detail=""):
    c.execute("INSERT INTO sys_audit (ts,user_id,agent,grant_id,event,action,path,result,detail) VALUES (?,?,?,?,?,?,?,?,?)",
              (_now().isoformat(timespec="seconds"), uid, agent or "", gid or "", event, action, path, result, (detail or "")[:500]))


class GrantReq(BaseModel):
    scope: str
    ttl_minutes: int = 30
    actions: list = ["read"]
    agent: str = ""
    note: str = ""


class CheckReq(BaseModel):
    path: str
    action: str = "read"
    agent: str = ""


class LogReq(BaseModel):
    grant_id: str
    path: str
    action: str
    result: str = "ok"
    detail: str = ""
    agent: str = ""


class RevokeReq(BaseModel):
    grant_id: str


@router.post("/grant", status_code=201)
async def grant(req: GrantReq, request: Request):
    uid = _owner(request)
    scope = _norm(req.scope)
    if scope == "/":
        raise HTTPException(422, "scope '/' is too wide; name a directory or file")
    acts = sorted({str(a).lower() for a in (req.actions or ["read"])})
    if not acts or not set(acts) <= ACTIONS:
        raise HTTPException(422, "actions: read|write|exec|delete")
    if not (1 <= req.ttl_minutes <= MAX_TTL_MIN):
        raise HTTPException(422, f"ttl_minutes 1..{MAX_TTL_MIN}")
    gid = "sg_" + secrets.token_hex(6)
    exp = (_now() + timedelta(minutes=req.ttl_minutes)).isoformat(timespec="seconds")
    c = _conn()
    try:
        c.execute("INSERT INTO sys_grants VALUES (?,?,?,?,?,?,?,?,NULL)", (gid, uid, scope, json.dumps(acts), req.agent.strip(), req.note[:300], _now().isoformat(timespec="seconds"), exp))
        _audit(c, uid, req.agent, gid, "grant", ",".join(acts), scope, "ok", req.note)
        c.commit()
    finally:
        c.close()
    return {"status": "ok", "grant_id": gid, "scope": scope, "actions": acts, "expires_at": exp, "agent": req.agent.strip() or "any of your agents"}


@router.post("/check")
async def check(req: CheckReq, request: Request):
    uid = _uid(request)
    path = _norm(req.path)
    action = (req.action or "read").lower()
    now = _now().isoformat(timespec="seconds")
    c = _conn()
    try:
        hit = None
        if uid.lower() in _owners():  # grants belong to the owner; only the owner's agents (owner key) can use them
            for gid, scope, acts, agent, exp in c.execute("SELECT grant_id, scope, actions, agent, expires_at FROM sys_grants WHERE revoked_at IS NULL AND expires_at > ? ORDER BY expires_at DESC", (now,)):
                if action in json.loads(acts) and _covers(scope, path) and (not agent or agent == (req.agent or "").strip()):
                    hit = (gid, exp)
                    break
        _audit(c, uid, req.agent, hit[0] if hit else "", "check", action, path, "allowed" if hit else "refused")
        c.commit()
    finally:
        c.close()
    if hit:
        return {"allowed": True, "grant_id": hit[0], "expires_at": hit[1], "then": "Do only this action, then POST /api/v7/sysperm/log with the result."}
    return {"allowed": False, "then": "Refuse. Tell the person you need an explicit, time-limited owner grant for this system path (POST /api/v7/sysperm/grant)."}


@router.post("/log", status_code=201)
async def log(req: LogReq, request: Request):
    uid = _uid(request)
    path = _norm(req.path)
    c = _conn()
    try:
        g = c.execute("SELECT scope, actions, expires_at, revoked_at FROM sys_grants WHERE grant_id=?", (req.grant_id,)).fetchone()
        valid = bool(g) and uid.lower() in _owners() and not g[3] and g[2] > _now().isoformat(timespec="seconds") and _covers(g[0], path) and req.action.lower() in json.loads(g[1])
        _audit(c, uid, req.agent, req.grant_id, "action" if valid else "action_without_grant", req.action.lower(), path, req.result[:40], req.detail)
        c.commit()
    finally:
        c.close()
    return {"status": "logged", "within_grant": valid}


@router.post("/revoke")
async def revoke(req: RevokeReq, request: Request):
    uid = _owner(request)
    c = _conn()
    try:
        n = c.execute("UPDATE sys_grants SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL", (_now().isoformat(timespec="seconds"), req.grant_id)).rowcount
        _audit(c, uid, "", req.grant_id, "revoke", "", "", "ok" if n else "not_found")
        c.commit()
    finally:
        c.close()
    if not n:
        raise HTTPException(404, "no active grant with this id")
    return {"status": "revoked", "grant_id": req.grant_id}


@router.get("/grants")
async def grants(request: Request, active: bool = True):
    _owner(request)
    now = _now().isoformat(timespec="seconds")
    c = _conn()
    try:
        q = "SELECT grant_id, scope, actions, agent, note, created_at, expires_at, revoked_at FROM sys_grants"
        rows = c.execute(q + (" WHERE revoked_at IS NULL AND expires_at > ?" if active else "") + " ORDER BY created_at DESC LIMIT 100", ((now,) if active else ())).fetchall()
    finally:
        c.close()
    return {"items": [dict(zip(("grant_id", "scope", "actions", "agent", "note", "created_at", "expires_at", "revoked_at"), r)) for r in rows]}


@router.get("/audit")
async def audit(request: Request, limit: int = 100, grant_id: str = ""):
    _owner(request)
    c = _conn()
    try:
        q = "SELECT ts, user_id, agent, grant_id, event, action, path, result, detail FROM sys_audit"
        args = []
        if grant_id:
            q += " WHERE grant_id=?"; args.append(grant_id)
        rows = c.execute(q + " ORDER BY id DESC LIMIT ?", args + [max(1, min(limit, 500))]).fetchall()
    finally:
        c.close()
    return {"items": [dict(zip(("ts", "user_id", "agent", "grant_id", "event", "action", "path", "result", "detail"), r)) for r in rows]}
