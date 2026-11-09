"""Live glue: resolve the caller, stamp the event, move the cursor only after JSON is built.

A key that has never called identify stays on the old path: no IDENTIFY_REQUIRED.
Tokens are never written into the result.
"""
import json
import sqlite3

from app.room.claims import expire_tasks, renew_leases
from app.room.digest import build_while_away, commit_cursor
from app.room.events import record_event
from app.room.identity import explicit_count
from app.room.identity import identify as identify_agent
from app.room.identity import resolve_call
from app.room.schema import ensure
from app.room.step_zero import step_zero_package

# MCP gate refuses the first call without a token (IDENTIFY_REQUIRED, nothing written).
# REST keeps the save and only adds this hint.
REST_IDENTIFY_HINT = (
    "На этом ключе уже есть агенты. Вызови identify(name) и передавай agent_token. Этот ход сохранён."
)
REST_BAD_TOKEN_HINT = "agent_token не подошёл. Вызови identify ещё раз. Этот ход сохранён."


def lookup_key(token):
    if not token:
        return None
    from app.api_keys import MASTER_DB, ensure_schema, hash_key
    conn = sqlite3.connect(MASTER_DB, timeout=5)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT rowid, user_id, chain_id, name, kind FROM user_api_keys "
            "WHERE api_key IN (?, ?) AND is_active=1 LIMIT 1",
            (token, hash_key(token)),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "key_id": "k%d" % row[0],
        "user_id": row[1],
        "chain_id": row[2] or "",
        "key_name": row[3] or "agent",
        "kind": row[4] or "",
    }


def open_account(info):
    from app import shelves
    conn = shelves.connect(info["user_id"])
    ensure(conn)
    return conn


def gate(info, conn, agent_token="", session_id="", client_hint=""):
    """None when the call may proceed. A dict when the caller must identify. Nothing is written on that path."""
    who = resolve_call(
        conn, info["key_id"], info["chain_id"], info["key_name"],
        agent_token=agent_token or "", session_id=session_id or "mcp", client_hint=client_hint or "",
    )
    if who.get("error") == "IDENTIFY_REQUIRED":
        return {"error": "IDENTIFY_REQUIRED", "hint": who.get("hint") or "", "saved": False,
                "next": "call identify(name), then pass agent_token on every call"}
    return who


def _annotate_facts(conn, chain_id, actor_id, facts, digest_ids):
    if not isinstance(facts, list):
        return
    found = {}
    try:
        rows = conn.execute("SELECT event_id, actor_agent_id FROM room_events WHERE chain_id=?", (chain_id,)).fetchall()
        found = {r[0]: r[1] for r in rows}
    except Exception:
        return
    kept = []
    for fact in facts:
        if not isinstance(fact, dict):
            kept.append(fact)
            continue
        ev = str(fact.get("ev") or "")
        if ev in digest_ids:
            continue
        owner = found.get(ev)
        fact = dict(fact)
        fact["actor"] = owner
        fact["is_self"] = bool(owner) and owner == actor_id
        kept.append(fact)
    facts[:] = kept


def _safe(obj):
    raw = json.dumps(obj, ensure_ascii=False, default=str)
    return json.loads(raw)


def finish_turn(conn, info, who, result, kind="", context_state="normal"):
    """Attach the digest when this key has explicit agents. Commit the cursor only after serialization."""
    if not isinstance(result, dict) or not isinstance(who, dict) or not who.get("ok"):
        return result
    if who.get("implicit"):
        return result
    if result.get("saved") is False or result.get("error") == "IDENTIFY_REQUIRED":
        return result
    try:
        expire_tasks(conn, info.get("chain_id") or "", info.get("key_id") or "")
        renew_leases(conn, who["actor_id"], info.get("chain_id") or "")
        if result.get("saved") or result.get("event_id"):
            record_event(
                conn, info.get("chain_id") or "", info.get("key_id") or "", who["actor_id"],
                result.get("session_id") or "mcp", kind=kind or "turn",
                text=(result.get("event_id") or "")[:80], event_id=result.get("event_id") or None,
                author_kind="human" if who.get("role") == "human" else "agent",
            )
        away = build_while_away(conn, who["actor_id"], info.get("key_id") or "", info.get("chain_id") or "", who.get("role") or "assistant")
        result = dict(result)
        result["actor"] = who["actor_id"]
        result["while_away"] = away.get("text")
        _annotate_facts(conn, info.get("chain_id") or "", who["actor_id"], result.get("facts"), set(away.get("event_ids") or []))
        if who.get("warning"):
            result["room_warning"] = who["warning"]
        if context_state == "lost":
            pack = step_zero_package(
                conn, who["actor_id"], info.get("key_id") or "", info.get("chain_id") or "",
                who.get("role") or "assistant", result.get("session_id") or "mcp", context_state="lost",
            )
            if pack.get("text"):
                result["room_step_zero"] = pack["text"]
        blob = json.dumps(result, ensure_ascii=False, default=str)
        if away.get("text"):
            commit_cursor(conn, who["actor_id"], info.get("chain_id") or "", away.get("proposed_upto"))
        json.loads(blob)
        return result
    except Exception as exc:
        print("[room] turn decorate skipped: %s" % type(exc).__name__, flush=True)
        return result


def do_identify(info, conn, name, role="", client_hint="", session_id=""):
    out = identify_agent(
        conn, info["key_id"], info["chain_id"], name,
        role=role or "assistant", client_hint=client_hint or "", session_id=session_id or "",
    )
    if out.get("error"):
        return out
    pack = step_zero_package(
        conn, out["agent_id"], info["key_id"], info["chain_id"], out.get("role") or "assistant",
        out.get("session_id") or "", display_name=out.get("name") or "",
    )
    if pack.get("while_away"):
        commit_cursor(conn, out["agent_id"], info["chain_id"], pack.get("proposed_upto"))
    # The token is returned once, here, and is not copied into the pack text.
    return {
        "agent_id": out["agent_id"],
        "agent_token": out["agent_token"],
        "session_id": out["session_id"],
        "step_zero": bool(pack.get("step_zero")),
        "handoff_digest": pack.get("while_away"),
        "room_text": pack.get("text") or "",
    }


def explicit_count_ro(user_id, key_id):
    """Read-only. Does not create the account database or the room tables."""
    import os
    import sqlite3 as _sq
    try:
        from app import shelves
        path = os.path.join(shelves.BASE_DIR, shelves._name(user_id) + ".db")
    except Exception:
        return 0
    if not path or not os.path.isfile(path):
        return 0
    conn = _sq.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agents'").fetchone():
            return 0
        return conn.execute("SELECT COUNT(*) FROM agents WHERE key_id=?", (key_id,)).fetchone()[0]
    except _sq.Error:
        return 0
    finally:
        conn.close()


def _hinted(result, hint):
    out = dict(result)
    out["identify_hint"] = hint
    if out.get("error") == "IDENTIFY_REQUIRED":
        out.pop("error", None)
    return out


def rest_attach(info, conn, result, agent_token="", session_id="rest", kind="turn", context_state="normal"):
    """Stamp a REST turn and attach while_away.

    A missing token never refuses the save. MCP still returns IDENTIFY_REQUIRED
    and writes nothing on the first miss; this path only adds identify_hint.
    """
    if not isinstance(result, dict) or not isinstance(info, dict):
        return result
    if result.get("mode") in ("context", "recap"):
        return result
    if result.get("saved") is False and not result.get("event_id"):
        return result
    if "not saved again" in str(result.get("note") or ""):
        if not agent_token and explicit_count(conn, info.get("key_id") or "") > 0:
            return _hinted(result, REST_IDENTIFY_HINT)
        return result
    if not agent_token:
        if explicit_count(conn, info.get("key_id") or "") == 0:
            return result
        return _hinted(result, REST_IDENTIFY_HINT)
    who = gate(info, conn, agent_token, session_id or "rest")
    if not isinstance(who, dict) or not who.get("ok"):
        hint = REST_IDENTIFY_HINT if (who or {}).get("error") == "IDENTIFY_REQUIRED" else REST_BAD_TOKEN_HINT
        return _hinted(result, hint)
    return finish_turn(conn, info, who, result, kind=kind or "turn", context_state=context_state or "normal")


def rest_step_zero(info, conn, agent_token="", session_id="rest", force=False, context_state="normal"):
    """Room block for REST step_zero: what the other agents on this line did."""
    if not agent_token:
        if explicit_count(conn, info.get("key_id") or "") == 0:
            return {"ok": True, "step_zero": False, "text": "", "while_away": None}
        return {"ok": True, "step_zero": False, "text": "", "while_away": None, "identify_hint": REST_IDENTIFY_HINT}
    who = gate(info, conn, agent_token, session_id or "rest")
    if not isinstance(who, dict) or not who.get("ok"):
        hint = REST_IDENTIFY_HINT if (who or {}).get("error") == "IDENTIFY_REQUIRED" else REST_BAD_TOKEN_HINT
        return {"ok": True, "step_zero": False, "text": "", "while_away": None, "identify_hint": hint}
    pack = step_zero_package(
        conn, who["actor_id"], info.get("key_id") or "", info.get("chain_id") or "",
        who.get("role") or "assistant", session_id or "rest", context_state or "normal", bool(force),
        display_name=who.get("name") or "",
    )
    if pack.get("while_away"):
        commit_cursor(conn, who["actor_id"], info.get("chain_id") or "", pack.get("proposed_upto"))
    return {
        "ok": True,
        "step_zero": bool(pack.get("step_zero")),
        "kind": pack.get("kind"),
        "text": pack.get("text") or "",
        "while_away": pack.get("while_away"),
        "others_block": pack.get("others_block") or "",
    }
