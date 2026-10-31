"""REST equivalent of the MCP tool turn (same logic): agent self-check context + [ev:] id check + save + server seal.
Used by Guard 1 (REST/starter prompt chats) and Guard 2. POST /api/v7/agent/turn (Bearer) or GET /api/v7/agent/turn?k=."""
import re, json, time, hmac, hashlib, sqlite3, os
import httpx

BASE = "http://127.0.0.1:8000/api/v7"
SITE = "http://127.0.0.1:8000"
DB = "/data/skv/metadata_store/rest_turn.db"
SEAL_LOG = "/data/skv/skv_seals.log"
SEAL_CODE_FMT = "🔐 SKV | #{n:03d}·{c} | [READ ✓] [VERIFY ✓] [CORRECT ✓] [OUTPUT ✓]"
SEAL_FMT = "🔐 SKV | #{n:03d} | [READ ✓] [VERIFY ✓] [CORRECT ✓] [OUTPUT ✓]"
_LOW = {"yes", "y", "ok", "okay", "continue", "go", "go on", "next", "no", "thanks", "thank you", "да", "ок", "го",
        "продолжай", "дальше", "нет", "спасибо", "работай", "давай", "ага"}


def _seal_key() -> bytes:
    for p in ("/data/skv/.seal_key",):
        try:
            return open(p, "rb").read()
        except Exception:
            pass
    raise RuntimeError("seal key missing")


def seal_code(user: str, n: int, text: str) -> str:
    return hmac.new(_seal_key(), ("%s|%d|%s" % (user, n, hashlib.sha256((text or "").encode()).hexdigest())).encode(), "sha256").hexdigest()[:4]


def _db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("create table if not exists st(user text primary key, last_user text, saved_t real, eid text, seal int, final text, verdict text)")
    return c


def _req(key, method, path, body=None, params=None, base=BASE):
    with httpx.Client(timeout=90.0) as c:
        r = c.request(method, base + path, headers={"Authorization": "Bearer " + key, "User-Agent": "skv-rest-turn"}, json=body, params=params)
        try:
            d = r.json()
        except Exception:
            d = {"raw": r.text[:2000]}
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "error": d}
        return d


def _sid(e):
    return (e or "").split("::")[-1]


def _is_low(m):
    return re.sub(r"[^\w ]", "", (m or "").strip().lower()) in _LOW


def _words(s, n):
    w = str(s or "").split()
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


def _hits(key, q):
    d = _req(key, "POST", "/search", {"query_text": q, "top_k": 20})
    allr = (d or {}).get("results") or [] if isinstance(d, dict) else []
    top = max([float(r.get("score") or 0) for r in allr] or [0])
    out, seen = [], set()
    for r in allr:
        s = r.get("summary") or ""
        if (top and float(r.get("score") or 0) < 0.45 * top) or r.get("superseded_by") or r.get("superseded") or "[lightweight]" in s[:40]:
            continue
        k = re.sub(r"\s+", " ", re.sub(r"🔐[^\n]*", "", s))[:200]
        if k in seen:
            continue
        seen.add(k)
        out.append({"event_id": r.get("event_id"), "time": r.get("time"), "score": float(r.get("score") or 0), "summary": s})
        if len(out) >= 5:
            break
    return out


SEAL_CTR_DB = "/data/skv/metadata_store/seal_counter.db"
def _next_seal(key, user, same=False):
    """Monotonic per-account seal number: max(stored counter, bootstrap) (+1 unless retry of same turn); reserved atomically."""
    c = sqlite3.connect(SEAL_CTR_DB, timeout=15, isolation_level=None)
    try:
        c.execute("create table if not exists ctr(user text primary key, n integer)")
        c.execute("begin immediate")
        row = c.execute("select n from ctr where user=?", (user,)).fetchone()
        stored = row[0] if row else 0
        try: boot = _last_seal(key)
        except Exception: boot = 0
        n = max(stored, boot) + (0 if (same and stored) else 1)
        c.execute("insert or replace into ctr values(?,?)", (user, n)); c.execute("commit")
        return n
    finally:
        c.close()


def _last_seal(key):
    d = _req(key, "POST", "/session/bootstrap", {"recent_messages": []})
    raw = ((d or {}).get("continuity") or {}).get("raw") or "" if isinstance(d, dict) else ""
    ss = [int(x) for x in re.findall(r"SKV \| #(\d+)", raw)]
    return max(ss) if ss else 0



# ─── compact mode helpers (opt-in turn(compact=true)) ───
_PLACEHOLDER_ID = re.compile(r"^(<[^>]*>|id|ids|event_id|\.{2,}|…|x+|n+|_+|\*+)$", re.I)
def _real_cites(text):
    """[ev:...] citations minus doc placeholders like [ev:id], [ev:ID], [ev:<id>], [ev:...]."""
    text = re.sub(r"```.*?(```|$)", " ", text or "", flags=re.S)   # fenced code blocks: examples, not citations
    text = re.sub(r"`[^`\n]*`", " ", text)                          # inline code spans: examples, not citations
    return [c for c in dict.fromkeys(re.findall(r"\[ev:([^\]\s]+)\]", text)) if not _PLACEHOLDER_ID.match(c.strip())]
def _compact_facts(hits, own, rel=0.7, n=3, chars=200):
    top = max([float(h.get("score") or 0) for h in hits] or [0])
    out = []
    for h in hits:
        if _sid(h.get("event_id")) == own: continue
        if top and h.get("score") is not None and float(h.get("score") or 0) < rel * top: continue
        s = re.sub(r"\s+", " ", str(h.get("summary") or "")).strip()
        out.append({"ev": _sid(h.get("event_id")), "fact": (s[:chars].rstrip() + " [cut]" if len(s) > chars else s) + " [ev:%s]" % _sid(h.get("event_id"))})
        if len(out) >= n: break
    return out
def _compact_gate(user, session, cubes, checklist, db):
    """Return cubes/checklist only when their hash changed since this session's last turn; else versions only."""
    import sqlite3 as _sq, hashlib as _hl, json as _js
    cv = _hl.sha1(_js.dumps(cubes, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
    kv = _hl.sha1(_js.dumps(checklist, ensure_ascii=False).encode()).hexdigest()[:8]
    c = _sq.connect(db, timeout=10)
    c.execute("create table if not exists cst(user text, session text, cubes_h text, check_h text, t real, primary key(user, session))")
    row = c.execute("select cubes_h, check_h from cst where user=? and session=?", (user, session)).fetchone() or (None, None)
    c.close()
    out = {"cubes_version": cv, "checklist_version": kv}
    if row[0] != cv: out["cubes"] = cubes
    else: out["cubes_unchanged"] = True
    if row[1] != kv: out["self_check"] = checklist
    else: out["self_check_unchanged"] = True
    def commit():
        c2 = _sq.connect(db, timeout=10)
        c2.execute("create table if not exists cst(user text, session text, cubes_h text, check_h text, t real, primary key(user, session))")
        import time as _t
        c2.execute("insert or replace into cst values(?,?,?,?,?)", (user, session, cv, kv, _t.time())); c2.commit(); c2.close()
    return out, commit

COMPACT_DB = "/data/skv/metadata_store/compact_state_rest.db"


def _board_rel(user, msg, answer=""):
    """Direct call (same process, no HTTP self-call): up to 3 relevant open board tasks + close hint."""
    try:
        from app import board as _b
        d = _b.relevant(user, (msg or "")[:1500], (answer or "")[:3000], 3)
        return {k: v for k, v in (("board", d.get("board")), ("board_hint", d.get("board_hint"))) if v}
    except Exception as e:
        print(f"[rest_turn] board skipped: {e}", flush=True)
        return {}


def _prof_rel(user, msg, answer, session_id, compact):
    """Relevant profile rows + duties (in-process; empty when the layer is off). Never fails the turn."""
    try:
        from app import profile as _prof
        return _prof.relevant(user, (msg or "")[:2000], (answer or "")[:4000], session_id or "rest", bool(compact)) or {}
    except Exception:
        return {}


def turn(key, user_message, draft="", query="", session_id="rest", duty="", duty_reason="", task_done=False, critical="", l1_summary="", l2_summary="", source_event_ids=None, sensitive=None, compact=False, answer="", draft_summary="", profile=None, profile_review=None, source="", second_look=""):
    if answer and not draft:
        draft = answer
    if not key:
        return {"ok": False, "status": 401, "error": "API key required (Authorization: Bearer sk_... or ?k=sk_...)"}
    st = _req(key, "GET", "/constitution/status")
    if isinstance(st, dict) and st.get("status") == 401:
        return {"ok": False, "status": 401, "error": "invalid API key"}
    user = (st.get("installed_by") if isinstance(st, dict) else "") or hashlib.sha256(key.encode()).hexdigest()[:16]
    c = _db()
    row = c.execute("select last_user, saved_t, eid, seal, final, verdict from st where user=?", (user,)).fetchone() or (None, 0, "", None, "", "")
    last_user, saved_t, last_eid, last_seal, last_final, last_verdict = row
    now = time.time()
    from app.secret_scrub import scrub as _scrub
    _um_h = "h:" + hashlib.sha256((user_message or "").encode()).hexdigest()  # state keeps a hash, never the raw text
    same = bool(last_user in (_um_h, user_message) and now - (saved_t or 0) < 900 and last_eid)
    q = _scrub((query or user_message or "")[:500], sensitive)
    hits = [] if (_is_low(user_message) and not query) else _hits(key, q)
    own = _sid(last_eid) if same else ""
    facts = [{"ev": _sid(h["event_id"]), "time": h.get("time"), "fact": _words(h["summary"], 60)} for h in hits if _sid(h["event_id"]) != own]
    cubes = []
    try:
        if not _is_low(user_message):
            cd = _req(key, "GET", "/api/cubes/search", params={"query": q[:200]}, base=SITE)
            for x in ((cd or {}).get("results") or [])[:3] if isinstance(cd, dict) else []:
                if isinstance(x, dict) and (x.get("cube_id") or x.get("id")):
                    cubes.append({"cube_id": x.get("cube_id") or x.get("id"), "essence": _words(x.get("essence") or x.get("title") or "", 25)})
    except Exception:
        cubes = []
    checklist = ["Facts missing or the user asks to recall: dig deeper (POST /api/v7/memory with lines=all, GET /api/v7/event/{id}, POST /api/v7/memory/dig) before saying you do not remember.",
                 "Every fact about the user or the past in the draft rests on an [ev:id] from facts, or is said to be unknown.",
                 "Newest fact wins; superseded entries are history.",
                 "No fact outside the user message, this turn's results, memory [ev:] or general knowledge."]
    if cubes:
        checklist.insert(4, "The answer follows the relevant cubes (%s) or says why not; then vote or duty=vote_nothing." % ", ".join(x["cube_id"] for x in cubes))
    cg = None
    if compact:
        facts = _compact_facts(hits, own)
        cg, cg_commit = _compact_gate(user, session_id or "rest", cubes, checklist, COMPACT_DB)
    if not draft and compact:
        c.close(); cg_commit()
        return {"mode": "context", "compact": True, "facts": facts, **cg, **_board_rel(user, user_message), **_prof_rel(user, user_message, "", session_id, True), "next": "self-check, then turn with answer=<final> and compact=true"}
    if not draft:
        c.close()
        return {"mode": "context", "facts": facts, "cubes": cubes, "self_check": checklist, **_board_rel(user, user_message), **_prof_rel(user, user_message, "", session_id, False),
                "next": "write the draft, run the self_check, then call turn again with user_message and draft; the seal comes only from that call"}
    drawn = [m.group(0) for m in re.finditer(r"🔐?\s*SKV\s*\|\s*#[^\n]*", draft)]
    clean = re.sub(r"\n?🔐?\s*SKV\s*\|\s*#[^\n]*", "", draft).rstrip()
    cited = _real_cites(clean + "\n" + (draft_summary or ""))
    known = {_sid(h["event_id"]) for h in hits}
    invalid = []
    for x in cited:
        sx = _sid(x)
        if sx in known:
            continue
        if "::" in x and not x.startswith(user + "::"):
            invalid.append(x); continue
        ev = _req(key, "GET", "/event/" + user + "::" + sx, params={"lines": "all"})
        if isinstance(ev, dict) and ev.get("ok") is not False and not ev.get("error"):
            known.add(sx)
        else:
            invalid.append(x)
    ext_src = str(source or "").startswith(("guard2_ext", "ext", "hook"))
    unverified = list(invalid) if (invalid and ext_src) else []   # ext/hook: save anyway, flag [VERIFY ?]; MCP/REST agents stay strict
    if invalid and not ext_src:
        c.close()
        return {"verdict": "revise", "saved": False, "seal": None, "invalid_ids": invalid,
                "fixes": ["[ev:%s] does not exist in your memory: remove it, cite a real id from facts, or say the fact is unknown" % x for x in invalid],
                "facts": facts, "next": "nothing saved: fix the draft, call turn again with the same user_message"}
    pc = {}
    if True:   # profile check (always: also yields the [PROFILE ✗] seal mark) BEFORE the seal is reserved: a rejection burns no seal
        from app import profile as _prof
        pc = _prof.precheck(user, profile, profile_review, bool(l2_summary))
        if pc.get("errors"):
            c.close()
            return {"verdict": "revise", "saved": False, "seal": None, "profile_errors": pc["errors"],
                    "next": "nothing saved, no seal used: fix profile / profile_review and call turn again with the same user_message"}
    seal_n = last_seal if (same and last_verdict == "pass" and last_seal) else _next_seal(key, user, same)
    seal = SEAL_CODE_FMT.format(n=seal_n, c=seal_code(user, seal_n, clean)).replace("[VERIFY ✓]", "[VERIFY ?]" if unverified else "[VERIFY ✓]") + ((" " + pc["seal_mark"]) if pc.get("seal_mark") else "")
    final = clean + "\n" + seal
    if same and last_final == final:
        saved = {"event_id": last_eid, "note": "identical turn already saved: not saved again"}
    else:
        body = {"query": user_message, "response": final, "duty": duty, "duty_reason": duty_reason, "task_done": bool(task_done),
                "critical": critical, "pin": bool(critical), "session_id": session_id or "rest", "self_check": True,
                "l1_summary": l1_summary or "", "l2_map": l2_summary or "", "source_event_ids": [_sid(x) for x in (source_event_ids or []) if x], "sensitive": [x for x in (sensitive or []) if x],
                "profile": profile or None, "profile_review": profile_review or None}
        if _is_low(user_message) and len(final) < 400 and not (critical or duty or l1_summary or l2_summary or sensitive):
            body["topic"] = "lightweight"; body["query"] = "[lightweight] " + user_message
        if same:
            body["query"] = "[revision of ev:%s] " % _sid(last_eid) + body["query"]; body["supersedes"] = last_eid
        saved = _req(key, "POST", "/remember", body)
    ok = isinstance(saved, dict) and saved.get("ok") is not False and saved.get("status") != "revise"
    eid = (saved.get("event_id") or ((saved.get("saved") or [""])[0]) or "") if isinstance(saved, dict) else ""
    if ok:
        c.execute("insert or replace into st values(?,?,?,?,?,?,?)", (user, _um_h, now, eid, seal_n, final, "pass"))
        c.commit()
        try:
            with open(SEAL_LOG, "a") as fh:
                fh.write(json.dumps({"t": int(now), "user": user, "seal": seal_n, "code": seal.split("·")[1][:4], "event_id": eid, "via": "rest"}) + "\n")
        except Exception:
            pass
        try:
            _req(key, "POST", "/agent/second-look", {"draft": final, "event_id": "", "span": 0, "searched": True, "hit_ids": []})
        except Exception:
            pass
    c.close()
    _slq, _sls = [], {}
    if ok:
        try:
            from app import second_look_q as _SLQ
            _slq = _SLQ.questions(clean, user_message, facts)
            _sls = _SLQ.record(COMPACT_DB, user, len(_slq), second_look, revised=bool(same))
        except Exception:
            _slq = []
    _slh = {"second_look_questions": [q["ask"] for q in _slq], "second_look_answer_with": "next turn: second_look=\"kept|changed: <what>\""} if _slq else {}
    # Extension/web clients (source=guard2_ext:*) cannot write L1/L2: don't hand them summary duties;
    # the server-side LLM fallback (memory_v2_llm) summarises those turns instead.
    ext = str(source or "").startswith(("guard2_ext", "ext", "hook"))
    if ext and isinstance(saved, dict) and saved.get("summary_due"):
        saved = dict(saved); saved.pop("summary_due", None)
    duties = [saved.get(k) for k in ("summary_due", "cube_duty", "duties", "duty_errors", "reminders") if isinstance(saved, dict) and saved.get(k)]
    if isinstance(saved, dict) and saved.get("cube_harvest"):
        duties.insert(0, saved["cube_harvest"])
    prof = {k: saved[k] for k in ("profile_applied", "profile_version", "profile_warnings", "profile_errors", "profile_mark", "profile_fallback_started", "profile_duties")
            if isinstance(saved, dict) and saved.get(k)}
    prof.update({k: v for k, v in _prof_rel(user, user_message, clean, session_id, compact).items() if k not in prof})
    if compact:
        if ok: cg_commit()
        r = {**_slh, **({"unknown_ids": unverified, "verify": "unknown ev ids in reply (not in memory); saved with [VERIFY ?]"} if unverified else {}), "verdict": "pass" if ok else "revise", "saved": ok, "compact": True, "event_id": eid or None, "seal": seal if ok else None,
             "cited_ok": cited, "facts": facts, **(cg if ok else {"cubes": cubes, "self_check": checklist}), "duties": [str(d)[:300] for d in duties]}
        if isinstance(saved, dict) and saved.get("summary_due"): r["summary_due"] = saved.get("summary_due")
        if ext: r["summary_mode"] = "server"
        if drawn: r["seal_warning"] = "self-written seal in your answer ignored; only this seal field is valid"
        if not ok: r["error"] = saved
        r.update(_board_rel(user, user_message, clean)); r.update(prof)
        return r
    return {**_slh, **({"unknown_ids": unverified, "verify": "unknown ev ids in reply (not in memory); saved with [VERIFY ?]"} if unverified else {}), "verdict": "pass" if ok else "revise", "saved": ok, "event_id": eid or None, "seal": seal if ok else None,
            "cited_ok": cited, "facts": facts, "cubes": cubes, "self_check": checklist, "duties": [str(d)[:300] for d in duties], **_board_rel(user, user_message, clean), **prof,
            "seal_warning": ("your draft contained a seal you wrote yourself (%s); only the server seal from this field is valid. A seal without a turn call is a violation." % drawn[0][:60]) if drawn else None,
            "summary_due": saved.get("summary_due") if isinstance(saved, dict) else None, "saved_parts": saved.get("saved") if isinstance(saved, dict) else None,
            "error": None if ok else saved, **({"second_look_stats": _sls} if _slq and _sls else {})}


def seal_next(key, same=False):
    if not key:
        return {"ok": False, "status": 401, "error": "API key required"}
    st = _req(key, "GET", "/constitution/status")
    if isinstance(st, dict) and st.get("status") == 401:
        return {"ok": False, "status": 401, "error": "invalid API key"}
    user = (st.get("installed_by") if isinstance(st, dict) else "") or hashlib.sha256(key.encode()).hexdigest()[:16]
    return {"ok": True, "n": _next_seal(key, user, bool(same))}
