"""REST equivalent of the MCP tool turn (same logic): agent self-check context + [ev:] id check + save + server seal.
Used by Guard 1 (REST/starter prompt chats) and Guard 2. POST /api/v7/agent/turn (Bearer) or GET /api/v7/agent/turn?k=."""
import contextvars
import re, json, time, hmac, hashlib, sqlite3, os

_TOPIC_Q = contextvars.ContextVar("skv_turn_topic_q", default="")
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


def _clip_duty(d, cap=300):
    """Short duty lines stay capped. An author-cube CORE block on a cube reminder stays whole."""
    s = d if isinstance(d, str) else str(d)
    if "AUTHOR CUBE CORE (" in s:
        return s
    return s[:cap]


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


def _hits(key, q, search_as=None, keep=8, context=None):
    _b = {"query_text": q, "top_k": keep, "pack": True, "budget_tokens": 1800}
    if search_as:
        _b["search_as"] = [str(x)[:160] for x in (search_as if isinstance(search_as, list) else [search_as])][:3]
    if context:
        _b["context"] = [str(x)[:400] for x in list(context)[:3] if str(x or "").strip()]
    d = _req(key, "POST", "/search", _b)
    allr = (d or {}).get("results") or [] if isinstance(d, dict) else []
    out, seen = [], set()
    for r in allr:
        s = r.get("summary") or ""
        # No cut on the flat RRF score. Cosine is filtered before fusion; topic diet runs later.
        if r.get("superseded_by") or r.get("superseded") or "[lightweight]" in s[:40]:
            continue
        k = re.sub(r"\s+", " ", re.sub(r"🔐[^\n]*", "", s))[:200]
        if k in seen:
            continue
        seen.add(k)
        meta = r.get("metadata") or {}
        out.append({"event_id": r.get("event_id"), "time": meta.get("time_str") or r.get("time") or "",
                    "score": float(r.get("score") or 0), "summary": s, "source": r.get("source") or ""})
        if len(out) >= keep:
            break
    return out


def _turn_hits(key, user, user_message, query, search_as, sensitive, compact=False):
    """One /search, or the active-state slice. Does not invent search_as."""
    from app.secret_scrub import scrub as _scrub
    q = _scrub((query or user_message or "")[:500], sensitive)
    try:
        from app import turn_context as tc
        from app.search_v2 import _db as _db_path
    except Exception as exc:
        print("[rest_turn] turn_context unavailable: %s" % type(exc).__name__, flush=True)
        if str(search_as or "").strip() == "-":
            return "", []
        return q, _hits(key, q, search_as)
    tc.set_plan({})
    conn = None
    try:
        multi = bool(tc.is_multi(user_message or ""))
        conn = tc.open_ro(_db_path(user))
        recent, echoes = [], set()
        if conn is not None:
            recent, echoes = tc.recent_from_conn(conn, user_message or "")
        plan = tc.followup_plan(user_message or "", search_as, recent)
        if plan.get("mode") == "plain" and query and not tc.is_short(user_message or ""):
            plan = dict(plan)
            plan["query"] = (query or "")[:500]
        tc.set_plan(plan)
        try:
            from app import turn_diet17 as _d17
            plan = _d17.overlay(plan, user_message or "", search_as, conn)
            tc.set_plan(plan)
        except Exception as _exc:
            print("[17c] overlay skipped: %s" % type(_exc).__name__, flush=True)
        mode = plan.get("mode")
        if mode == "auto_skip":
            try:
                from app import turn_diet17 as _d17
                _d17.log_skip(plan.get("skip_reason") or "empty", user_message or "")
                return "", _d17.board_hits(conn)
            except Exception as _exc:
                print("[17c] skip pack skipped: %s" % type(_exc).__name__, flush=True)
                return "", []
        if mode == "directive":
            try:
                from app import turn_diet17 as _d17
                _d17.log_skip(plan.get("skip_reason") or "directive", user_message or "")
                return "", _d17.directive_hits(conn)
            except Exception as _exc:
                print("[17c] directive pack skipped: %s" % type(_exc).__name__, flush=True)
                return "", []
        if mode == "skip":
            return "", []
        if mode == "slice":
            hits = tc.active_slice(conn, plan.get("task_hint") or "") if conn is not None else []
            if tc.slice_keeps(plan, hits):
                return "", hits
            # No doing row: keep the short line as the query. Replacing it with
            # the previous line dropped short follow-ups that already hit.
            q = _scrub((user_message or "")[:500], sensitive)
            ctx = list(plan.get("context") or [])[:2]
            search_as = []
            skip_merge = False
        else:
            skip_merge = mode == "deictic"
            if mode == "plain" and _is_low(user_message) and not (plan.get("query") or "").strip() and not plan.get("search_as"):
                return q, []
            q = _scrub((plan.get("query") or q or "")[:500], sensitive)
            search_as = plan.get("search_as") or []
            ctx = list(plan.get("context") or [])
        if not (q or "").strip() and not search_as:
            return q, []
        hits = _hits(key, q, search_as, context=ctx)
        try:
            if not skip_merge:
                hits, echoes = tc.merge_status_newest(hits, user_message or "", conn, ctx, echoes)
            topic = q if tc.is_short(user_message or "") else (user_message or q)
            layers = tc.layer_from_conn(conn, topic) if conn is not None else []
            extra = []
            if multi and conn is not None:
                best = ""
                for h in hits:
                    eid = h.get("event_id") or ""
                    sid = str(eid).split("::")[-1]
                    if eid not in echoes and sid not in echoes:
                        best = eid
                        break
                if best:
                    extra = tc.neighbours(conn, best, topic)
            hits = tc.rank(list(hits) + layers + extra, topic, echoes, multi, limit=tc.turn_rank_limit(compact))
            if plan.get("recency_h"):
                hits = tc.rerank_recency(hits, q, plan["recency_h"])
        except Exception as exc:
            print("[rest_turn] context rank skipped: %s" % type(exc).__name__, flush=True)
        return q, hits
    except Exception as exc:
        print("[rest_turn] context expand skipped: %s" % type(exc).__name__, flush=True)
        return q, _hits(key, q, search_as)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
def _norm_ids(raw):
    """str or list -> bare ids. A string is not iterated character by character."""
    try:
        from app.turn_pack import bare_ids
        return bare_ids(raw)
    except Exception:
        if isinstance(raw, str):
            return [_sid(x) for x in re.split(r"[,|\s]+", raw) if x.strip()]
        return [_sid(x) for x in (raw or []) if x]


def _compact_facts(hits, own, rel=0.7, n=3, chars=200, message=None, kind=""):
    """Compact facts. Wide turns keep 2400. A normal message uses the 1500 budget."""
    from app import turn_context as tc
    return tc.compact_facts(hits, own, rel=rel, n=n, chars=chars, message=message, kind=kind)
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


def _harvest_fallback(result, user, duty=""):
    """Per-account cube_harvest when this call has no identified agent. Remember already closed aliases."""
    if not user or not isinstance(result, dict) or result.get("cube_harvest"):
        return result
    try:
        from app import cube_harvest as _ch
        extra = _ch.due(user, "turn")
        if extra:
            result = dict(result)
            result.update(extra)
            if result.get("cube_harvest"):
                result["duties"] = [result["cube_harvest"]] + list(result.get("duties") or [])
    except Exception as exc:
        print("[room] harvest fallback skipped: %s" % type(exc).__name__, flush=True)
    return result


def _context_catchup(key, result, agent_token, session_id):
    """17f on a context turn. Nothing is stamped. last_seen is read before it is moved."""
    if not isinstance(result, dict) or not agent_token or not key:
        return result
    try:
        from app.room.bridge import lookup_key, open_account
        from app.room.clock import iso
        from app import turn_diet17 as _d17
        from datetime import datetime, timezone
        info = lookup_key(key)
        if not info:
            return result
        conn = open_account(info)
        try:
            th = hashlib.sha256(str(agent_token).encode()).hexdigest()
            row = conn.execute(
                "SELECT id, last_seen_at FROM agents WHERE key_id=? AND token_hash=?",
                (info.get("key_id") or "", th),
            ).fetchone()
            if not row:
                return result
            who = {"actor_id": row[0], "prev_seen_at": row[1] or "", "ok": True}
            text = _d17.catchup_text(conn, who, str((_d17.get_meta() or {}).get("last_seal") or ""))
            conn.execute(
                "UPDATE agents SET last_seen_at=?, session_id=? WHERE key_id=? AND id=?",
                (iso(datetime.now(timezone.utc)), session_id or "", info.get("key_id") or "", row[0]),
            )
            conn.commit()
            if text:
                result = dict(result)
                result["while_away"] = text
                result["catch_up"] = True
            return result
        finally:
            conn.close()
    except Exception as exc:
        print("[17f] context catch-up skipped: %s" % type(exc).__name__, flush=True)
        return result


def _with_room(key, result, agent_token="", session_id="rest", context_state="normal", kind="turn", gist="", duty=""):
    """Attach the room digest when this key has agents. A missing token does not undo the save.

    A compact context turn used to return here before while_away was set, so the
    field stayed null. Catch-up is attached without saving a room event.
    """
    if not isinstance(result, dict) or result.get("mode") in ("context", "recap") or result.get("saved") is False:
        if isinstance(result, dict) and result.get("mode") in ("context", "recap"):
            return _context_catchup(key, result, agent_token, session_id)
        return result
    if not (result.get("saved") or result.get("event_id")):
        return result
    try:
        from app.room.bridge import explicit_count_ro, lookup_key, open_account, rest_attach
        info = lookup_key(key)
        if not info:
            return result
        if not agent_token and not explicit_count_ro(info.get("user_id") or "", info.get("key_id") or ""):
            from app.room.bridge import SOFT_IDENTIFY_HINT, soft_nudge_due
            if soft_nudge_due(info.get("key_id"), session_id or "rest"):
                result = {**result, "identify_hint": SOFT_IDENTIFY_HINT}
            return _harvest_fallback(result, info.get("user_id") or "", duty)
        conn = open_account(info)
        try:
            return rest_attach(info, conn, result, agent_token or "", session_id or "rest", kind or "turn", context_state or "normal", gist or "", duty or "")
        finally:
            conn.close()
    except Exception as exc:
        print("[room] rest attach skipped: %s" % type(exc).__name__, flush=True)
        return result


def _const_heartbeat(result, user, session_id, user_message="", msg_ref="", ack=False, reset=False, wrote=False):
    """T73 heartbeat for REST /agent/turn: constitution{v,hash,rule,stale} + manifest when due. Never fails the turn."""
    if not isinstance(result, dict) or "verdict" not in result or not user:
        return result
    try:
        from app import const_bind as _CB
        if not _CB.enabled():
            return result
        key = hashlib.sha1(((msg_ref or "") + "|" + (user_message or "")[:400]).encode("utf-8", "replace")).hexdigest()[:12]
        missed = "missed_turns" in json.dumps(result.get("duties") or "", ensure_ascii=False)
        cb = _CB.on_turn(user, session_id or "rest", msg_key=key, ack=bool(ack), reset=bool(reset),
                         no_seal=bool(wrote and not result.get("seal")), missed=missed)
        if not cb:
            return result
        out = dict(result)
        out.update(cb)
        try:
            from app.t89_rules import pin_last
            pin_last(out, "next_step")
        except Exception:
            pass
        return out
    except Exception as exc:
        print("[rest_turn] const_bind skipped: %s" % type(exc).__name__, flush=True)
        return result


def _hook_events(ok, task_done, sensitive, context_reset, context_state):
    """Mechanical names only. User-text phrase matching stays on the suggest path."""
    events = ["before_reply"]
    if ok:
        events.append("after_reply")
    if task_done:
        events.append("task_end")
    if sensitive:
        events.append("secret_in_text")
    if context_reset or str(context_state or "") in ("lost", "new"):
        events.append("session_start")
    return events


def _attach_hooks(result, uid, events, chain_id):
    """Deliver matching do-text. A failure stays off the turn. The log stores capture pointers, not the account."""
    if not isinstance(result, dict) or not events:
        return result
    try:
        from app.hook_bus import cues_for_installed
        from app.signal_log import append_pointer_file
        cues = cues_for_installed(uid, events, chain_id or "session")
        if not cues:
            return result
        result["hook_cues"] = cues
        append_pointer_file(
            "hook_fire",
            ref=" ".join(events)[:180],
            cube_id=" ".join(sorted({c.get("cube_id") or "" for c in cues}))[:180],
            extra={"n": len(cues)},
        )
    except Exception:
        pass
    return result


def _session_window(user):
    """Newest dialogue ids. The recall component drops these so it does not echo the current chat."""
    ids = []
    try:
        from app.spontaneous_recall import recent_events
        for ev in recent_events(user, limit=8) or []:
            eid = (ev or {}).get("event_id") or ""
            if eid:
                ids.append(eid)
    except Exception:
        pass
    return ids


def _decorate(result, user, message, facts=None, launch_ok=False, l1_new=False, keyword=False):
    """Tool duty and the once-per-hash tool map on every user-facing return.

    The recall component no longer launches here. turn_pack.finish calls safety_net
    after fact selection, so a context turn with empty facts can queue the job.
    The keyword sidecar runs only when the component is off and keyword is true.
    launch_ok and l1_new stay in the signature for existing callers. A failure never fails the turn.
    """
    if not isinstance(result, dict):
        return result
    result["_tp_user"] = user
    try:
        from app.tool_duty import apply as _td
        _td(result, message, facts if facts is not None else (result.get("facts") or []))
    except Exception:
        pass
    try:
        from app.tool_map import apply as _tm
        _tm(result, user)
    except Exception:
        pass
    # The component used to launch here, before fact selection, and a context
    # turn passed launch_ok false. The 17g safety net runs after the pack.
    # tool_duty stays a hint and does not count as the agent searching.
    try:
        from app.components.recall_component import enabled as _rc_on
        if _rc_on():
            return result
    except Exception:
        pass
    if keyword:
        try:
            from app.spontaneous_recall import push_into as _sr_push
            _sr_push(result, user, message, l1_new=l1_new)
        except Exception:
            pass
    return result


def _pack_turn(res, message, session, duty, duty_reason, source_event_ids, compressed_at, compressed, used_fact_ids, l1_summary, l2_summary="", agent_token=""):
    """T84 pack after the watch. Pops the stashed account id so it never leaves the server."""
    if not isinstance(res, dict):
        return res
    source_event_ids = _norm_ids(source_event_ids)
    user = res.pop("_tp_user", "") or ""
    topic_query = str(res.pop("_topic_query", "") or "") or _TOPIC_Q.get()
    try:
        from app import turn_pack as _tp
        _ctx = {
            "user": user,
            "session": session or "rest",
            "message": message or "",
            "topic_query": topic_query or "",
            "duty": duty or "",
            "duty_reason": duty_reason or "",
            "source_event_ids": source_event_ids or [],
            "compressed": bool(compressed),
            "compressed_at": str(compressed_at or ""),
            "used_fact_ids": used_fact_ids or "",
            "l1_just_saved": bool(str(l1_summary or "").strip()),
            "l1_summary": l1_summary or "",
            "l2_summary": l2_summary or "",
            "load_portfolio": True,
            "actor": agent_token or "",
            "harvest": bool(agent_token),
            "recall_exclude": _session_window(user) if user else [],
        }
        try:
            from app import turn_diet17 as _d17
            _ctx.update(_d17.pack_ctx_flags(message or "", compressed=bool(compressed), catchup=bool(res.get("catch_up"))))
            try:
                from app import turn_context as _tc_plan
                _mini = (_tc_plan.current_plan() or {}).get("mini_step_zero")
            except Exception:
                _mini = ""
            if _mini:
                res["mini_step_zero"] = _mini
        except Exception:
            pass
        _tp.finish(res, _ctx)
    except Exception as exc:
        print("[rest_turn] turn pack skipped: %s" % type(exc).__name__, flush=True)
    return res


def _stamp_user(res, user):
    if isinstance(res, dict) and user:
        res["_gap_user"] = user
    return res


def _apply_seal_gaps(res, user, agent_token, source, draft, answer, recap, msg_ref, duty, duty_reason):
    """One journal check per turn: recap answers, plus a guard2/hook draft (that text was already shown).
    A normal new draft is sealed by this call and is not a gap. Counters are always on the body."""
    if not isinstance(res, dict) or not user:
        return res
    try:
        from app import seal_gap as _sg
        from app import turn_watch_rest as _tw
        items = []
        for ref, _u, ans in _tw.parse_recap(recap):
            if (ans or "").strip():
                items.append({"ref": ref, "text": ans})
        if str(source or "").startswith(("guard2_ext", "ext", "hook")) and (draft or answer):
            items.append({"ref": msg_ref or "visible", "text": answer or draft})
        if items:
            note = _sg.observe(user, agent_token or "", items, duty=duty, duty_reason=duty_reason)
        else:
            note = {"unsealed_gaps": 0, "unsealed_gaps_total": _sg.total(_sg.scope(user, agent_token or "")), "duty": None}
        res["unsealed_gaps"] = int(note.get("unsealed_gaps") or 0)
        res["unsealed_gaps_total"] = int(note.get("unsealed_gaps_total") or 0)
        if note.get("duty"):
            res["duties"] = [note["duty"]] + list(res.get("duties") or [])
    except Exception:
        res.setdefault("unsealed_gaps", 0)
        res.setdefault("unsealed_gaps_total", 0)
    return res


def turn(key, user_message, draft="", query="", session_id="rest", duty="", duty_reason="", task_done=False, critical="", l1_summary="", l2_summary="", source_event_ids=None, sensitive=None, compact=False, answer="", draft_summary="", profile=None, profile_review=None, source="", second_look="", search_as=None, agent_token="", context_state="normal", kind="turn", msg_ref="", recap=None, const_ack=False, ack="", context_reset=False, context_compressed_at="", compressed=False, used_fact_ids=None, context_compacted=False, last_seal=""):
    """msg_ref / recap are optional (turn-watch, see turn_watch_rest.py): clients that send neither get exactly the old behaviour. const_ack / ack="const" / context_reset are the T73 constitution heartbeat (same as MCP turn)."""
    _TOPIC_Q.set("")
    try:
        from app import turn_context as _tc_plan
        _tc_plan.set_plan({})
        _tc_plan.set_agent(agent_token)
    except Exception:
        pass
    try:
        from app import turn_diet17 as _d17
        _src = str(source or "")
        _d17.set_meta({
            "on": True,
            "context_compacted": bool(context_compacted),
            "last_seal": str(last_seal or ""),
            "session": session_id or "rest",
            "stateless": (not str(agent_token or "").strip()) or _src.startswith(("guard2_ext", "ext", "hook", "guard1", "api")),
            "verbose": False,
            "compact": bool(compact),
            "token_hash": hashlib.sha256(str(agent_token).encode()).hexdigest() if agent_token else "",
            "actor": "",
            "prev_answer": "",
            "minutes": None,
        })
    except Exception:
        pass
    def _out(res):
        if isinstance(res, dict):
            gu = res.pop("_gap_user", "") or ""
            if gu:
                _apply_seal_gaps(res, gu, agent_token, source, draft, answer, recap, msg_ref, duty, duty_reason)
        res = _pack_turn(res, user_message, session_id, duty, duty_reason, source_event_ids, context_compressed_at, compressed, used_fact_ids, l1_summary, l2_summary, agent_token)
        if isinstance(res, dict):
            try:
                from app import turn_context as _tc_plan
                _tc_plan.attach_gloss(res, _tc_plan.current_plan(), agent_token)
            except Exception:
                pass
        return res
    if isinstance(recap, str) and not recap.strip():
        recap = None
    if not msg_ref and not recap:
        return _out(_turn_inner(key, user_message, draft, query, session_id, duty, duty_reason, task_done, critical, l1_summary, l2_summary, source_event_ids, sensitive, compact, answer, draft_summary, profile, profile_review, source, second_look, search_as, agent_token, context_state, kind, const_ack=const_ack, ack=ack, context_reset=context_reset, msg_ref=msg_ref))
    from app import turn_watch_rest as _tw
    user = ""
    try:
        st = _req(key, "GET", "/constitution/status") if key else {}
        if isinstance(st, dict) and st.get("status") != 401:
            user = st.get("installed_by") or hashlib.sha256(key.encode()).hexdigest()[:16]
    except Exception:
        user = ""
    if not user:   # no/invalid key: the inner call answers 401
        return _out(_turn_inner(key, user_message, draft, query, session_id, duty, duty_reason, task_done, critical, l1_summary, l2_summary, source_event_ids, sensitive, compact, answer, draft_summary, profile, profile_review, source, second_look, search_as, agent_token, context_state, kind, const_ack=const_ack, ack=ack, context_reset=context_reset, msg_ref=msg_ref))
    k = _tw.scope(user, agent_token or "")
    rc = {}
    if recap:
        try:
            from app.secret_scrub import scrub as _sc
            rc = _tw.save_recaps(_req, key, k, recap, session_id, sensitive, _sc)
        except Exception as exc:
            rc = {"recap_error": "recap not saved: %s" % type(exc).__name__}
    res = _turn_inner(key, user_message, draft, query, session_id, duty, duty_reason, task_done, critical, l1_summary, l2_summary, source_event_ids, sensitive, compact, answer, draft_summary, profile, profile_review, source, second_look, search_as, agent_token, context_state, kind, const_ack=const_ack, ack=ack, context_reset=context_reset, msg_ref=msg_ref)
    if not isinstance(res, dict):
        return res
    try:
        ref = _tw.span(msg_ref)
        saved_now = bool(res.get("saved")) and res.get("mode") != "context"
        try:
            from app.turn_pack import system_skip_refs as _skip
            _tw.cover(k, _skip(recap))
        except Exception:
            pass
        missing = _tw.check(k, ref, saved_now)
        if missing:
            res["duties"] = [_tw.duty(missing)] + list(res.get("duties") or [])
            if user:
                try:
                    from app import const_bind as _CB
                    if _CB.enabled():
                        _CB.bump(user, "missed_turns")
                except Exception:
                    pass
        if rc:
            res.update(rc)
    except Exception as exc:
        print("[rest_turn] turn-watch skipped: %s" % type(exc).__name__, flush=True)
    return _out(res)


def _turn_inner(key, user_message, draft="", query="", session_id="rest", duty="", duty_reason="", task_done=False, critical="", l1_summary="", l2_summary="", source_event_ids=None, sensitive=None, compact=False, answer="", draft_summary="", profile=None, profile_review=None, source="", second_look="", search_as=None, agent_token="", context_state="normal", kind="turn", const_ack=False, ack="", context_reset=False, msg_ref=""):
    if answer and not draft:
        draft = answer
    if not key:
        return {"ok": False, "status": 401, "error": "API key required (Authorization: Bearer sk_... or ?k=sk_...)"}
    st = _req(key, "GET", "/constitution/status")
    if isinstance(st, dict) and st.get("status") == 401:
        return {"ok": False, "status": 401, "error": "invalid API key"}
    user = (st.get("installed_by") if isinstance(st, dict) else "") or hashlib.sha256(key.encode()).hexdigest()[:16]
    _ack = bool(const_ack) or (str(ack or "").strip().lower() == "const")
    _reset = bool(context_reset)
    _wrote = bool(draft)
    def _hb(res):
        return _const_heartbeat(res, user, session_id, user_message, msg_ref, _ack, _reset, _wrote)
    c = _db()
    row = c.execute("select last_user, saved_t, eid, seal, final, verdict from st where user=?", (user,)).fetchone() or (None, 0, "", None, "", "")
    last_user, saved_t, last_eid, last_seal, last_final, last_verdict = row
    now = time.time()
    try:
        from app import turn_diet17 as _d17
        extra = {}
        if last_final and not (_d17.get_meta() or {}).get("prev_answer"):
            extra["prev_answer"] = last_final
        if saved_t and (_d17.get_meta() or {}).get("minutes") is None and not (_d17.get_meta() or {}).get("prev_seen_at"):
            extra["minutes"] = (now - float(saved_t)) / 60.0
        if extra:
            _d17.merge_meta(**extra)
    except Exception:
        pass
    ext_src = str(source or "").startswith(("guard2_ext", "ext", "hook"))
    # ext/hook: the same prompt on another site (or sent again in a new reply) is a NEW turn, not a revision -> hash includes the source
    _um_h = "h:" + hashlib.sha256(((user_message or "") + (("|" + str(source)) if ext_src else "")).encode()).hexdigest()  # state keeps a hash, never the raw text
    same = bool(last_user in (_um_h, user_message) and now - (saved_t or 0) < 900 and last_eid)
    q, hits = _turn_hits(key, user, user_message, query, search_as, sensitive, compact=compact)
    _TOPIC_Q.set(q or "")
    try:
        from app import turn_context as _tc_plan
        _gp = _tc_plan.current_plan()
        if isinstance(_gp, dict):
            _gp["summary_missing"] = bool(draft) and len(draft) > 300 and not str(draft_summary or "").strip()
    except Exception:
        pass
    own = _sid(last_eid) if same else ""
    facts = [{"ev": _sid(h["event_id"]), "time": h.get("time"), "fact": _words(h["summary"], 60)} for h in hits if _sid(h["event_id"]) != own]
    cubes = []
    try:
        if q and not _is_low(user_message):
            cd = _req(key, "GET", "/api/cubes/search", params={"query": q[:200]}, base=SITE)
            for x in ((cd or {}).get("results") or [])[:3] if isinstance(cd, dict) else []:
                if isinstance(x, dict) and (x.get("cube_id") or x.get("id")):
                    cubes.append({"cube_id": x.get("cube_id") or x.get("id"), "essence": _words(x.get("essence") or x.get("title") or "", 25)})
    except Exception:
        cubes = []
    # Static text. Cube ids live on the cubes field. Putting them here changed the
    # checklist hash every turn, so compact mode resent self_check (~500 bytes).
    checklist = ["Facts missing or the user asks to recall: dig deeper (POST /api/v7/memory with lines=all, GET /api/v7/event/{id}, POST /api/v7/memory/dig) before saying you do not remember.",
                 "Every fact about the user or the past in the draft rests on an [ev:id] from facts, or is said to be unknown.",
                 "Newest fact wins; superseded entries are history.",
                 "No fact outside the user message, this turn's results, memory [ev:] or general knowledge.",
                 "The answer follows the relevant cubes or says why not; then vote or duty=vote_nothing."]
    cg = None
    if compact:
        facts = _compact_facts(hits, own, message=user_message, kind=kind)
        cg, cg_commit = _compact_gate(user, session_id or "rest", cubes, checklist, COMPACT_DB)
    if not draft and compact:
        c.close(); cg_commit()
        return _stamp_user(_decorate({"mode": "context", "compact": True, "facts": facts, **cg, **_board_rel(user, user_message), **_prof_rel(user, user_message, "", session_id, True), "next": "self-check, then turn with answer=<final> and compact=true"}, user, user_message, facts, launch_ok=False), user)
    if not draft:
        c.close()
        return _stamp_user(_decorate({"mode": "context", "facts": facts, "cubes": cubes, "self_check": checklist, **_board_rel(user, user_message), **_prof_rel(user, user_message, "", session_id, False),
                "next": "write the draft, run the self_check, then call turn again with user_message and draft; the seal comes only from that call"}, user, user_message, facts, launch_ok=False), user)
    drawn = [m.group(0) for m in re.finditer(r"🔐?\s*SKV\s*\|\s*#[^\n]*", draft)]
    clean = re.sub(r"\n?🔐?\s*SKV\s*\|\s*#[^\n]*", "", draft).rstrip()
    if same and ext_src and re.sub(r"\n?🔐?\s*SKV\s*\|\s*#[^\n]*", "", last_final or "").rstrip() != clean:
        same = False   # ext: a different reply to the same prompt = new turn with its own seal number (agents keep revise-retry semantics)
    cited = _real_cites(clean + "\n" + (draft_summary or ""))
    known = {_sid(h["event_id"]) for h in hits}
    invalid = []
    transient = []
    for x in cited:
        sx = _sid(x)
        if sx in known:
            continue
        if "::" in x and not x.startswith(user + "::"):
            invalid.append(x); continue
        try:
            ev = _req(key, "GET", "/event/" + user + "::" + sx, params={"lines": "all"})
        except Exception:
            transient.append(x)
            continue
        if isinstance(ev, dict) and ev.get("ok") is not False and not ev.get("error"):
            known.add(sx)
            continue
        status = 0
        if isinstance(ev, dict):
            try:
                status = int(ev.get("status") or 0)
            except (TypeError, ValueError):
                status = 0
        if status >= 500:
            transient.append(x)
        else:
            invalid.append(x)
    # A 5xx or a dropped lookup is not a fake id. Save the turn and mark [VERIFY ?]. A real 404 still revises.
    unverified = list(transient)
    if invalid and ext_src:
        unverified.extend(invalid)   # ext/hook: save anyway, flag [VERIFY ?]; MCP/REST agents stay strict on a real miss
    _gloss_revise = False
    try:
        from app import turn_context as _tc_plan
        _gloss_revise = bool((_tc_plan.current_plan() or {}).get("revise"))
    except Exception:
        _gloss_revise = False
    if invalid and not ext_src and not _gloss_revise:
        c.close()
        return _stamp_user(_hb(_decorate({"verdict": "revise", "saved": False, "seal": None, "invalid_ids": invalid,
                "fixes": ["[ev:%s] does not exist in your memory: remove it, cite a real id from facts, or say the fact is unknown" % x for x in invalid],
                "facts": facts, "next": "nothing saved: fix the draft, call turn again with the same user_message"}, user, user_message, facts, launch_ok=False)), user)
    pc = {}
    _pw = []
    if True:   # profile check (always: also yields the [PROFILE ✗] seal mark) BEFORE the seal is reserved: a rejection burns no seal
        from app import profile as _prof
        pc = _prof.precheck(user, profile, profile_review, bool(l2_summary))
        if pc.get("errors") and _prof.separable(pc["errors"]):
            _pw = list(pc["errors"])
            if any("text must be 1.." in str(e) for e in pc["errors"]):
                profile = _prof.drop_overlong(profile)
            if any("profile_review required" in str(e) for e in pc["errors"]):
                l2_summary = ""
                profile_review = None
            pc = _prof.precheck(user, profile, profile_review, bool(l2_summary))
            if pc.get("errors") and not _prof.separable(pc["errors"]):
                c.close()
                return _stamp_user(_hb(_decorate({"verdict": "revise", "saved": False, "seal": None, "profile_errors": pc["errors"],
                        "next": "nothing saved, no seal used: fix profile / profile_review and call turn again with the same user_message"}, user, user_message, facts, launch_ok=False)), user)
            if pc.get("errors"):
                profile = None
                l2_summary = ""
                profile_review = None
                pc = {"ok": True, "errors": [], "warnings": list(_pw), "seal_mark": ""}
            else:
                pc = dict(pc)
                pc["warnings"] = list(pc.get("warnings") or []) + _pw
        elif pc.get("errors"):
            c.close()
            return _stamp_user(_hb(_decorate({"verdict": "revise", "saved": False, "seal": None, "profile_errors": pc["errors"],
                    "next": "nothing saved, no seal used: fix profile / profile_review and call turn again with the same user_message"}, user, user_message, facts, launch_ok=False)), user)
    if _gloss_revise:
        from app.turn_context import gloss_revise_reason, remember_fields
        reason = gloss_revise_reason()
        body = {"query": user_message, "response": clean, "duty": duty, "duty_reason": duty_reason, "task_done": bool(task_done),
                "critical": critical, "pin": bool(critical), "session_id": session_id or "rest", "self_check": True,
                "l1_summary": l1_summary or "", "l2_map": l2_summary or "", "source_event_ids": _norm_ids(source_event_ids),
                "sensitive": [x for x in (sensitive or []) if x], "profile": profile or None, "profile_review": profile_review or None}
        body.update(remember_fields(search_as, draft_summary, last_eid if last_eid else ""))
        if same:
            body["query"] = "[revision of ev:%s] " % _sid(last_eid) + body["query"]
            body["supersedes"] = last_eid
        saved = _req(key, "POST", "/remember", body)
        eid = (saved.get("event_id") or ((saved.get("saved") or [""])[0]) or "") if isinstance(saved, dict) else ""
        if eid:
            c.execute("insert or replace into st values(?,?,?,?,?,?,?)", (user, _um_h, now, eid, None, clean, "revise"))
            c.commit()
        c.close()
        return _stamp_user(_hb(_decorate({
            "verdict": "revise", "status": "revise", "saved": bool(eid), "seal": None, "facts": [],
            "event_id": eid or None, "reason": reason, "next": reason,
        }, user, user_message, [], launch_ok=False)), user)
    seal_n = last_seal if (same and last_verdict == "pass" and last_seal) else _next_seal(key, user, same)
    # Web extension: the model only saw SKV memory if the user inserted the memory block (or the reply cites [ev:]).
    # Otherwise the seal must not claim READ: [READ ?] + a warning naming how many facts the model did not see.
    ext_web = str(source or "").startswith(("guard2_ext", "ext"))
    no_read = bool(ext_web and "[SKV memory" not in (user_message or "") and not cited and facts)
    seal = SEAL_CODE_FMT.format(n=seal_n, c=seal_code(user, seal_n, clean)).replace("[VERIFY ✓]", "[VERIFY ?]" if unverified else "[VERIFY ✓]").replace("[READ ✓]", "[READ ?]" if no_read else "[READ ✓]") + ((" " + pc["seal_mark"]) if (pc.get("seal_mark") and not ext_src) else "")   # ext/hook cannot send profile ops: open candidates go to the server fallback, no [PROFILE ✗]
    final = clean + "\n" + seal
    if same and last_final == final:
        saved = {"event_id": last_eid, "note": "identical turn already saved: not saved again"}
    else:
        body = {"query": user_message, "response": final, "duty": duty, "duty_reason": duty_reason, "task_done": bool(task_done),
                "critical": critical, "pin": bool(critical), "session_id": session_id or "rest", "self_check": True,
                "l1_summary": l1_summary or "", "l2_map": l2_summary or "", "source_event_ids": _norm_ids(source_event_ids), "sensitive": [x for x in (sensitive or []) if x],
                "profile": profile or None, "profile_review": profile_review or None}
        try:
            from app.turn_context import remember_fields
            body.update(remember_fields(search_as, draft_summary, last_eid if last_eid else ""))
        except Exception:
            pass
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
            from app import seal_gap as _sg
            _sg.record_issued(user, seal_n, seal.split("·")[1][:4], clean, eid, via="rest")
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
            _slq = _SLQ.dedupe(COMPACT_DB, user, _slq, second_look)
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
    if isinstance(saved, dict) and isinstance(saved.get("task_cube"), dict) and saved["task_cube"].get("note") and not ext:
        duties = ["TASK CUBE: " + str(saved["task_cube"]["note"])] + duties   # T71
    if isinstance(saved, dict) and isinstance(saved.get("duty_rules"), dict) and saved["duty_rules"].get("rules") and not ext:
        try:
            from app.duty_rules import diet_block
            duties = diet_block(saved["duty_rules"]["rules"], user, session_id or "rest", COMPACT_DB) + duties
        except Exception:
            duties = [str(x)[:180] for x in saved["duty_rules"]["rules"]] + duties
    prof = {k: saved[k] for k in ("profile_applied", "profile_version", "profile_warnings", "profile_errors", "profile_mark", "profile_fallback_started", "profile_duties")
            if isinstance(saved, dict) and saved.get(k)}
    prof.update({k: v for k, v in _prof_rel(user, user_message, clean, session_id, compact).items() if k not in prof})
    if compact:
        if ok: cg_commit()
        r = {**_slh, **({"unknown_ids": unverified, "verify": "unknown ev ids in reply (not in memory); saved with [VERIFY ?]"} if unverified else {}), "verdict": "pass" if ok else "revise", "saved": ok, "compact": True, "event_id": eid or None, "seal": seal if ok else None,
             "cited_ok": cited, "facts": facts, **(cg if ok else {"cubes": cubes, "self_check": checklist}), "duties": [_clip_duty(d) for d in duties]}
        if isinstance(saved, dict) and saved.get("summary_due"): r["summary_due"] = saved.get("summary_due")
        if ext: r["summary_mode"] = "server"
        if drawn: r["seal_warning"] = "self-written seal in your answer ignored; only this seal field is valid"
        elif no_read: r["seal_warning"] = "SKV memory was not given to the model before this answer (%d matching facts exist): [READ ?]. Use Insert SKV memory before sending." % len(facts)
        if not ok: r["error"] = saved
        r.update(_board_rel(user, user_message, clean)); r.update(prof)
    else:
        r = {**_slh, **({"unknown_ids": unverified, "verify": "unknown ev ids in reply (not in memory); saved with [VERIFY ?]"} if unverified else {}), "verdict": "pass" if ok else "revise", "saved": ok, "event_id": eid or None, "seal": seal if ok else None,
            "cited_ok": cited, "facts": facts, "cubes": cubes, "self_check": checklist, "duties": [_clip_duty(d) for d in duties], **_board_rel(user, user_message, clean), **prof,
            "seal_warning": ("your draft contained a seal you wrote yourself (%s); only the server seal from this field is valid. A seal without a turn call is a violation." % drawn[0][:60]) if drawn else
                            (("SKV memory was not given to the model before this answer (%d matching facts exist): [READ ?]. Use Insert SKV memory before sending." % len(facts)) if no_read else None),
            "summary_due": saved.get("summary_due") if isinstance(saved, dict) else None, "saved_parts": saved.get("saved") if isinstance(saved, dict) else None,
            "error": None if ok else saved, **({"second_look_stats": _sls} if _slq and _sls else {})}
    if isinstance(saved, dict) and isinstance(saved.get("portfolio"), dict) and saved.get("portfolio"):
        r["portfolio"] = saved["portfolio"]
    if _pw:
        extra = list(r.get("profile_warnings") or []) if isinstance(r.get("profile_warnings"), list) else []
        r["profile_warnings"] = extra + [str(x) for x in _pw]
    _decorate(r, user, user_message, facts, launch_ok=bool(ok), l1_new=bool((l1_summary or "").strip()), keyword=True)
    _attach_hooks(r, user, _hook_events(ok, task_done, sensitive, _reset, context_state), session_id)
    return _stamp_user(_hb(_with_room(key, r, agent_token, session_id, context_state, kind, (answer or draft), duty)), user)


def seal_next(key, same=False):
    if not key:
        return {"ok": False, "status": 401, "error": "API key required"}
    st = _req(key, "GET", "/constitution/status")
    if isinstance(st, dict) and st.get("status") == 401:
        return {"ok": False, "status": 401, "error": "invalid API key"}
    user = (st.get("installed_by") if isinstance(st, dict) else "") or hashlib.sha256(key.encode()).hexdigest()[:16]
    return {"ok": True, "n": _next_seal(key, user, bool(same))}
