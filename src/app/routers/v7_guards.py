from typing import List, Optional, Any
"""SKV v7 API: Guard 1 / constitution: constitution text, Second Look, Guard 2 download, agent prompt and OpenAPI.
Split from v7_router.py with behavior unchanged; shared helpers and state come from v7_core."""
from app.routers import v7_core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})


@router.get("/agent/prompt")
async def get_agent_prompt():
    """System prompt for Custom GPT / non-MCP agents. Same PROTOCOL step names as MCP."""
    from app.skv_protocol import AGENT_PROMPT, ROLE_LINE
    return {"system_prompt": AGENT_PROMPT, "role": ROLE_LINE, "protocol": "bootstrap→consult→draft→second_look→remember→cube/vote"}

@router.get("/agent/openapi.json")
async def get_agent_tools():
    """OpenAPI схема для Function Calling агентов (GPT, Claude, DeepSeek)"""
    import json, os
    schema_path = os.path.join(os.path.dirname(__file__), 'openapi_schema.json')
    with open(schema_path, 'r') as f:
        return json.load(f)

@router.get("/constitution")
async def get_constitution_v8():
    """Возвращает кубы конституции CUBE 00-05"""
    import sqlite3
    conn = sqlite3.connect(SHARED_DB)
    cur = conn.cursor()
    _flt, _args = _const_trusted_sql()
    cur.execute("SELECT cube_id, essence, rules_markdown FROM cubes_new WHERE cube_id LIKE 'cube_const_%' AND "
                + _flt + " ORDER BY cube_id", _args)
    cubes = []
    import re as _re
    latest = {}   # one cube per number: only the newest version (e.g. 05_v9 supersedes 05_v8) is served
    for eid, essence, raw in cur.fetchall():
        cube_num = eid.replace('cube_const_', '').split('_')[0]
        m = _re.search(r"_v(\d+)$", eid)
        ver = int(m.group(1)) if m else -1
        if cube_num not in latest or ver > latest[cube_num][0]:
            latest[cube_num] = (ver, eid, essence, raw)
    for cube_num in sorted(latest):
        _, eid, essence, raw = latest[cube_num]
        cubes.append({
            "id": eid,
            "cube": "CUBE " + cube_num.zfill(2),
            "essence": essence or "",
            "content": raw or "",
            "length": len(raw or "")
        })
    conn.close()
    return {
        "version": "v8.0 PRO",
        "cubes_count": len(cubes),
        "cubes": cubes,
        "total_chars": sum(c["length"] for c in cubes)
    }


@router.get("/agent/guardian.py")
async def download_guardian():
    from fastapi.responses import FileResponse
    # Guard 2: local MCP emulator + draft insurance (PROTOCOL-aligned; see app.skv_protocol)
    return FileResponse("/app/app/downloads/skv-guardian2.py", media_type="text/x-python", filename="skv-guardian2.py")

@router.post("/agent/second-look")
async def second_look(req: SecondLookRequest):
    """PROTOCOL step: second_look. PASS needs: (1) this turn saved via /remember first; (2) if the draft states a memory fact, it cites an event id (opened or from this turn's search hits)."""
    import sqlite3
    checks = []
    saved = False
    try:
        step = _duty_step(req.user_id)
        conn = sqlite3.connect(SHARED_DB)
        saved = bool(conn.execute("select 1 from agent_duty where user_id=? and step=? and duty='saved'", (req.user_id, step)).fetchone())
        conn.close()
    except Exception:
        saved = False
    checks.append({"name": "constitution", "ok": saved, "note": "turn saved" if saved else "FAIL: this turn is not saved yet. Call memory_remember(text=user message, response=draft) FIRST, then second_look again (or use the one-call tool turn)."})
    checks.append({"name": "critical", "ok": not (req.span > 20 and not req.event_id), "note": "span " + str(req.span) + ": one turn is not the whole topic" + ("" if not (req.span > 20 and not req.event_id) else "; FAIL: wide search (span>20) needs event_id of the turn you rely on")})
    checks.append({"name": "creative", "ok": True, "note": "offer one other reading, do not add a new fact"})
    draft = req.draft or ""
    ids = [i for i in ([req.event_id] if req.event_id else []) + list(req.hit_ids or []) if i]
    _short = lambda i: str(i).split("::")[-1].replace("ev:", "")
    cited = [i for i in ids if i in draft or _short(i) in draft]
    if req.event_id:
        ok = req.event_id in draft or _short(req.event_id) in draft or bool(cited)
        note = "draft cites " + ", ".join(cited) if ok else "FAIL: you opened event " + req.event_id + "; cite its id in the draft (e.g. [ev:" + req.event_id + "]) or drop the memory claim"
    elif req.searched:
        ok = True
        note = ("memory searched this turn; draft cites " + ", ".join(cited)) if cited else "memory searched this turn (%d hits); if you state a fact from memory, cite its event id" % len(req.hit_ids or [])
    else:
        ok = True
        note = "no memory search or opened turn this call; do not claim memory facts"
    checks.append({"name": "hallucination", "ok": ok, "note": note})
    ok = all(c["ok"] for c in checks if c["name"] != "creative")
    return {"status": "pass" if ok else "fail", "checks": checks,
            "pass_requires": "1) turn saved via memory_remember before this call; 2) cite event id for any memory fact",
            "next": "SEAL and output" if ok else "fix the failed checks (see FAIL notes), then call second-look again"}


class TurnRequest(BaseModel):
    user_message: str
    draft: str = ""
    query: str = ""
    session_id: str = "rest"
    duty: str = ""
    duty_reason: str = ""
    task_done: bool = False
    sensitive: List[str] = []
    critical: str = ""
    l1_summary: str = ""
    l2_summary: str = ""
    source_event_ids: List[str] = []
    user_id: str = ""
    compact: bool = False
    answer: str = ""
    draft_summary: str = ""
    profile: Optional[Any] = None          # profile ops (list or JSON string)
    profile_review: Optional[Any] = None   # with l2_summary: {"ops":[...]} or {"no_changes":true,"reason":...}
    source: str = ""                       # e.g. guard2_ext:chatgpt -> no L1/L2 duties, server summarises
    second_look: str = ""                  # answers to last turn's second_look_questions: "kept|changed: <what>"


def _turn_key(request, k=""):
    a = request.headers.get("authorization") or ""
    if a.lower().startswith("bearer "):
        return a[7:].strip()
    return (k or request.query_params.get("key") or request.headers.get("x-api-key") or "").strip()


@router.post("/agent/turn")
def agent_turn_post(req: TurnRequest, request: Request):
    """REST twin of the MCP tool turn: self-check context, [ev:] id check, save, server seal #NNN·code."""
    from app.rest_turn import turn as _t
    return _t(_turn_key(request), req.user_message, req.draft, req.query, req.session_id, req.duty, req.duty_reason, req.task_done, req.critical, req.l1_summary, req.l2_summary, req.source_event_ids, req.sensitive, req.compact, req.answer, req.draft_summary, req.profile, req.profile_review, source=req.source, second_look=req.second_look)


@router.get("/agent/turn")
def agent_turn_get(request: Request, q: str = "", draft: str = "", k: str = "", duty: str = "", duty_reason: str = "", task_done: bool = False, critical: str = "", l1_summary: str = "", l2_summary: str = "", source_event_ids: str = "", sensitive: str = "", compact: bool = False, answer: str = "", draft_summary: str = "", profile: str = "", profile_review: str = "", second_look: str = ""):
    """Same as POST /agent/turn for chats that can only open URLs: ?k=KEY&q=USER_MESSAGE&draft=DRAFT."""
    from app.rest_turn import turn as _t
    return _t(_turn_key(request, k), q, draft, "", "rest-get", duty, duty_reason, task_done, critical, l1_summary, l2_summary, [x.strip() for x in source_event_ids.split(",") if x.strip()], [x.strip() for x in sensitive.split("|") if x.strip()], compact, answer, draft_summary, profile or None, profile_review or None, second_look=second_look)


from pydantic import BaseModel as _BM
class SealNextReq(_BM):
    same: bool = False

@router.post("/agent/seal_next")
def agent_seal_next(request: Request, req: SealNextReq = None):
    """Reserve the next per-account seal number (shared counter for MCP + REST turn). Sync def: runs in threadpool (it calls this API)."""
    from app.rest_turn import seal_next as _sn
    return _sn(_turn_key(request), bool(req.same) if req else False)

_FB_HITS = {}
@router.get("/agent/feedback")
async def agent_feedback_get(k: str = "", key: str = "", text: str = "", kind: str = "bug", title: str = ""):
    """GET-only feedback door for agents without POST (ChatGPT web tool). Rate-limited, secrets masked."""
    import re as _re, sqlite3 as _sq, uuid as _uu, time as _t
    from fastapi.responses import JSONResponse
    tok = (k or key or "").strip()
    uid = None
    try:
        from app import api_keys as _akm
        uid = _akm.user_for(tok) if tok else None
    except Exception:
        uid = None
    if not uid:
        return JSONResponse({"status": "error", "error": "valid k=sk_ key required"}, status_code=401)
    text = (text or "").strip()
    if len(text) < 3:
        return JSONResponse({"status": "error", "error": "text required"}, status_code=400)
    now = _t.time()
    hits = [x for x in _FB_HITS.get(uid, []) if now - x < 3600]
    if len(hits) >= 10:
        return JSONResponse({"status": "error", "error": "rate limit: 10 per hour"}, status_code=429)
    hits.append(now); _FB_HITS[uid] = hits
    def _mask(s):
        s = _re.sub(r"sk_[A-Za-z0-9_\-]{8,}", "[SECRET]", s or "")
        s = _re.sub(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|пароль)(\s*[:=]\s*)\S+", r"\1\2[SECRET]", s)
        s = _re.sub(r"\b(?:\d[ -]?){13,19}\b", "[SECRET]", s)
        try:
            from app import memory_v2 as _mv
            s = _mv.mask_text(s)
        except Exception:
            pass
        return s
    body = _mask(text)[:4000]
    kind = kind if kind in ("bug", "idea", "praise", "other") else "bug"
    ttl = _mask(title or body[:80])[:120]
    fid = f"fb_{_uu.uuid4().hex[:12]}"
    conn = _sq.connect(SHARED_DB)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS feedback_reports
            (id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, type TEXT, title TEXT,
             description TEXT, event_id TEXT, cube_id TEXT, query_text TEXT,
             severity INTEGER, status TEXT DEFAULT 'new', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("INSERT INTO feedback_reports (id,user_id,agent_id,type,title,description,severity) VALUES (?,?,?,?,?,?,?)",
                     (fid, uid, "get_door", kind, ttl, body, 1))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "feedback_id": fid, "kind": kind, "saved_text": body[:300]}
