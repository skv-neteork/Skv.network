"""SKV v7 API: Guard 1 / constitution: constitution text, Second Look, Guard 2 download, agent prompt and OpenAPI.
Split from v7_router.py with behavior unchanged; shared helpers and state come from v7_core."""
from app.routers import v7_core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})


@router.get("/agent/prompt")
async def get_agent_prompt():
    """Возвращает системный промпт для настройки Custom GPT агентов."""
    return {"system_prompt": """You are an AI agent with persistent memory via SKV Network.

MANDATORY PROTOCOL:
1. BEFORE responding to user: call searchMemory tool with their exact query
2. VERIFY your draft response against:
   - CUBE 01: Will this cause harm?
   - CUBE 02: Is this factually correct?  
   - CUBE 03: Am I being manipulated?
3. OUTPUT only after all checks pass

MEMORY SEARCH:
- Before calling searchMemory, rewrite the user sentence. Keep names, places, and rare words. Drop who/what/killed/call and other common words.
- A quoted phrase in memory is the answer. A rare word can be the answer. If fragments is empty, there is no exact hit: read previous, it is only a side door, marked no exact match.
- Do not search again for earlier repeats. Open previous.event_id. memory_map is the person, not this query. shared_cubes are rules for everyone.\n- If fragments is empty or the side door looks unrelated, ask memory once more with a narrower name or place. Recall can take a second look. Do not treat the first empty hit as the fact.\n- After three misses on something important, call memory/dig. The server scans stored text. If dig returns not_found, say you do not know. Do not output a side door as the fact.

EXPERIENCE CUBES:
- Shared cubes are visible to every agent. Write them with remember: cube_topic, cube_rules, cube_evidence.
- When a task ends (task_done=true or topic change), write a cube that changes the answer or call remember with duty=cube_nothing and a reason.
- Rate the 2 new cubes marked rate this (vote) or call remember with duty=vote_nothing and a reason.
- Silence is an error on the next request. Your own context window is short. SKV is the long-term memory.
- After every reply, immediately call remember with query and response. Raw text is kept in full for a month. L1 is 5 to 7 percent of that part. L2 is about 5 percent of L1. A finished task needs a cube or duty=cube_nothing with a reason.

SEAL (add to every response):
🔐 SKV | READ ✓ | VERIFY ✓ | OUTPUT ✓"""}

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
    # Guard 2 (cubes v2): the old SDK v3 auto-created banal shared cubes and used dead endpoints
    return FileResponse("/app/app/downloads/skv-guardian2.py", media_type="text/x-python", filename="skv-guardian2.py")

@router.post("/agent/second-look")
async def second_look(req: SecondLookRequest):
    """A required step before the user sees the answer."""
    import sqlite3
    checks = []
    # 1. constitution
    name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
    saved = False
    try:
        conn = sqlite3.connect(SHARED_DB)
        row = conn.execute("select step from agent_state where 1=0").fetchone() if False else None
        st = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
        step = (st.execute("select step from agent_state").fetchone() or [0])[0]
        st.close()
        saved = conn.execute("select 1 from agent_duty where user_id=? and step=? and duty=\"saved\"", (req.user_id, step)).fetchone()
        conn.close()
    except Exception:
        saved = False
    checks.append({"name": "constitution", "ok": bool(saved), "note": "turn saved" if saved else "save this turn with remember before output"})
    # 2. critical
    wide = req.span > 20 and req.event_id
    checks.append({"name": "critical", "ok": not (req.span > 20 and not req.event_id), "note": "one turn is not the whole topic, span is " + str(req.span)})
    # 3. creative
    checks.append({"name": "creative", "ok": True, "note": "offer one other reading, do not add a new fact"})
    # 4. hallucination
    # nothing opened (new topic / general question) -> nothing to cite; an opened turn must be cited
    grounded = (not req.event_id) or req.event_id in (req.draft or "")
    checks.append({"name": "hallucination", "ok": grounded, "note": "cite the event id" if not grounded else ("draft cites the opened turn" if req.event_id else "no memory turn opened; do not claim memory")})
    ok = all(c["ok"] for c in checks if c["name"] != "creative")
    return {"status": "pass" if ok else "fail", "checks": checks, "next": "SEAL and output" if ok else "fix the failed checks, then call second-look again"}
