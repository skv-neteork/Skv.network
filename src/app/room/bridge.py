"""Live glue: resolve the caller, stamp the event, move the cursor only after JSON is built.

A key that has never called identify stays on the old path: no IDENTIFY_REQUIRED.
Tokens are never written into the result.
"""
import json
import re
import sqlite3
import time

from app.room.claims import expire_tasks, renew_leases
from app.room.digest import build_while_away, commit_cursor, short_id
from app.room.events import _SECRET, record_event
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
# Any agent, even the only one on a key, introduces itself: the memory then shows which agent led which part.
SOFT_IDENTIFY_HINT = (
    "Представься: identify(name) и передавай agent_token в каждом вызове — тогда в памяти видно, какой агент "
    "(Claude, Grok и т.д.) вёл эту часть диалога. Этот ход сохранён."
)
STEP_ZERO_NEXT = (
    "теперь вызови step_zero(agent_token) и прочитай все страницы page=1..N до done=true "
    "(now call step_zero(agent_token) and read all pages until done=true)"
)
STEP_ZERO_REMINDER = (
    "ты ещё не вызывал step_zero(agent_token): вызови его и прочитай все страницы page=1..N до done=true, "
    "потом продолжай с turn (step_zero not called yet for this agent)"
)
_NUDGE = {}


def soft_nudge_due(scope, session_id="", every=20):
    """In-memory counter: remind an unidentified caller on its first turn of the session and then every Nth."""
    k = "%s|%s" % (scope or "", session_id or "")
    if len(_NUDGE) > 5000:
        _NUDGE.clear()
    n = _NUDGE.get(k, 0)
    _NUDGE[k] = n + 1
    return n % max(1, int(every)) == 0


_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-]{24,}")


def turn_gist(text, limit=80):
    """One short phrase about a turn for the other agents. Secret-looking text yields an empty gist."""
    s = re.sub(r"\n?🔐 SKV \|[^\n]*", "", text or "")
    s = re.sub(r"\[ev:[^\]]*\]", "", s)
    s = re.sub(r"[`*#>|]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s or _SECRET.search(s):
        return ""
    s = _LONG_TOKEN.sub("…", s)
    first = re.split(r"(?<=[.!?…])\s", s, maxsplit=1)[0].strip()
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first


def mark_pack_seen(conn, key_id, actor_id, session_id="", now=None):
    """The agent called the real step_zero (page 1) with its token."""
    ensure(conn)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now if now is not None else time.time()))
    conn.execute(
        "INSERT INTO agent_pack_seen (key_id, actor_id, session_id, seen_at) VALUES (?,?,?,?) "
        "ON CONFLICT(key_id, actor_id) DO UPDATE SET session_id=excluded.session_id, seen_at=excluded.seen_at",
        (key_id or "", actor_id or "", session_id or "", stamp),
    )
    conn.commit()


def pack_seen(conn, key_id, actor_id):
    ensure(conn)
    return bool(conn.execute(
        "SELECT 1 FROM agent_pack_seen WHERE key_id=? AND actor_id=?", (key_id or "", actor_id or "")
    ).fetchone())


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


def gate(info, conn, agent_token="", session_id="", client_hint="", soft=False):
    """None when the call may proceed. A dict when the caller must identify. Nothing is written on that path.

    soft=True (the turn tool): a missing token never blocks. The turn is saved without an actor and the
    reply carries a reminder to identify.
    """
    who = resolve_call(
        conn, info["key_id"], info["chain_id"], info["key_name"],
        agent_token=agent_token or "", session_id=session_id or "mcp", client_hint=client_hint or "",
    )
    if who.get("error") == "IDENTIFY_REQUIRED":
        if soft:
            return {"ok": True, "implicit": True, "soft_identify": True, "actor_id": info.get("key_name") or "agent",
                    "role": "assistant", "name": info.get("key_name") or "agent", "multi": True,
                    "key_id": info["key_id"], "chain_id": info["chain_id"]}
        return {"error": "IDENTIFY_REQUIRED", "hint": who.get("hint") or "", "saved": False,
                "next": "call identify(name), then pass agent_token on every call"}
    return who


def _annotate_facts(conn, chain_id, actor_id, facts, digest_ids):
    if not isinstance(facts, list):
        return
    found = {}
    try:
        rows = conn.execute("SELECT event_id, actor_agent_id FROM room_events WHERE chain_id=?", (chain_id,)).fetchall()
        # room events keep <account>::<id>; facts show the short id
        found = {short_id(r[0]): r[1] for r in rows}
    except Exception:
        return
    digest_short = {short_id(x) for x in (digest_ids or ())}
    kept = []
    for fact in facts:
        if not isinstance(fact, dict):
            kept.append(fact)
            continue
        ev = short_id(fact.get("ev"))
        if ev in digest_short:
            continue
        owner = found.get(ev)
        fact = dict(fact)
        fact["actor"] = owner
        fact["is_self"] = bool(owner) and owner == actor_id
        if owner and owner != actor_id:
            # another agent's record: [ev:id] becomes [ev:id@agent]
            tag = "[ev:%s]" % ev
            for key in ("fact", "text"):
                if isinstance(fact.get(key), str) and tag in fact[key]:
                    fact[key] = fact[key].replace(tag, "[ev:%s@%s]" % (ev, owner))
        kept.append(fact)
    facts[:] = kept


def _safe(obj):
    raw = json.dumps(obj, ensure_ascii=False, default=str)
    return json.loads(raw)


def _full_event_id(info, event_id):
    eid = str(event_id or "").strip()
    if eid and "::" not in eid and info.get("user_id"):
        return "%s::%s" % (info["user_id"], eid)
    return eid


def _saved_events(info, result, gist="", gists=None):
    """(event id, gist) of every event this reply saved: the turn itself and each recap-sealed turn."""
    gists = gists or {}
    out, seen = [], set()

    def add(eid, g):
        full = _full_event_id(info, eid)
        if full and full not in seen:
            seen.add(full)
            out.append((full, g or ""))

    if result.get("event_id") and result.get("saved") is not False:
        add(result.get("event_id"), gists.get(short_id(result.get("event_id"))) or gist)
    for rid in result.get("recap_event_ids") or []:
        add(rid, gists.get(short_id(rid)) or "")
    for item in result.get("recap_seals") or []:
        if isinstance(item, dict) and item.get("event_id"):
            add(item["event_id"], gists.get(short_id(item["event_id"])) or "")
    return out


def finish_turn(conn, info, who, result, kind="", context_state="normal", gist="", gists=None, agent_token_given=True, duty=""):
    """Attach the digest when this key has explicit agents. Commit the cursor only after serialization.

    gist is a short phrase about this turn (the agent's answer); gists maps a recap event id to its phrase.
    """
    if not isinstance(result, dict) or not isinstance(who, dict) or not who.get("ok"):
        return result
    if who.get("implicit"):
        if not isinstance(result, dict) or result.get("saved") is False:
            return result
        hint = None
        if who.get("soft_identify") or not agent_token_given:
            if who.get("soft_identify") or soft_nudge_due(info.get("key_id") or info.get("user_id"), result.get("session_id") or "mcp"):
                hint = SOFT_IDENTIFY_HINT
        if hint:
            result = dict(result)
            result["identify_hint"] = hint
        return result
    if result.get("saved") is False or result.get("error") == "IDENTIFY_REQUIRED":
        return result
    try:
        expire_tasks(conn, info.get("chain_id") or "", info.get("key_id") or "")
        renew_leases(conn, who["actor_id"], info.get("chain_id") or "")
        events = _saved_events(info, result, gist, gists)
        if events:
            have = {r[0] for r in conn.execute(
                "SELECT event_id FROM room_events WHERE chain_id=?", (info.get("chain_id") or "",)
            ).fetchall()}
            for full, g in events:
                if full in have:
                    continue   # a replaced draft keeps its first stamp
                record_event(
                    conn, info.get("chain_id") or "", info.get("key_id") or "", who["actor_id"],
                    result.get("session_id") or "mcp", kind=kind or "turn",
                    text=full[:80], event_id=full, gist=g if (kind or "turn") == "turn" else "",
                    essence=g if (kind or "turn") == "turn" else "",
                    author_kind="human" if who.get("role") == "human" else "agent",
                )
        elif result.get("saved"):
            record_event(
                conn, info.get("chain_id") or "", info.get("key_id") or "", who["actor_id"],
                result.get("session_id") or "mcp", kind=kind or "turn",
                text="", event_id=None, gist=gist if (kind or "turn") == "turn" else "",
                author_kind="human" if who.get("role") == "human" else "agent",
            )
        away = build_while_away(conn, who["actor_id"], info.get("key_id") or "", info.get("chain_id") or "", who.get("role") or "assistant")
        result = dict(result)
        result["actor"] = who["actor_id"]
        result["while_away"] = away.get("text")
        _annotate_facts(conn, info.get("chain_id") or "", who["actor_id"], result.get("facts"), set(away.get("event_ids") or []))
        if who.get("warning"):
            result["room_warning"] = who["warning"]
            if who.get("unidentified"):
                result["identify_hint"] = SOFT_IDENTIFY_HINT
        if not pack_seen(conn, info.get("key_id") or "", who["actor_id"]):
            result["step_zero_reminder"] = STEP_ZERO_REMINDER
        try:
            from app.room.skills_harvest import turn_note
            note = turn_note(conn, info.get("key_id") or "", who["actor_id"], user_id=info.get("user_id") or "", duty=duty)
            if note:
                result["skills_harvest"] = note
                result["duties"] = list(result.get("duties") or []) + [note]
        except Exception as exc:
            print("[room] skills harvest skipped: %s" % type(exc).__name__, flush=True)
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
    first = bool(pack.get("step_zero"))
    if first:
        # a fresh session: the real step_zero is due again, so turn keeps reminding until it is called
        conn.execute("DELETE FROM agent_pack_seen WHERE key_id=? AND actor_id=?", (info["key_id"], out["agent_id"]))
        conn.commit()
    nxt = STEP_ZERO_NEXT if first else "продолжай с turn(agent_token) на каждое сообщение пользователя"
    room_text = pack.get("text") or ""
    if first:
        room_text = (nxt + "\n" + room_text).strip()
    skills_step = ""
    try:
        from app.room.skills_harvest import identify_step
        skills_step = identify_step(conn, info["key_id"], out["agent_id"])
    except Exception as exc:
        print("[room] skills step skipped: %s" % type(exc).__name__, flush=True)
    if skills_step:
        room_text = (room_text + "\n" + skills_step).strip()
    res = {
        "agent_id": out["agent_id"],
        "agent_token": out["agent_token"],
        "session_id": out["session_id"],
        "step_zero": bool(pack.get("step_zero")),
        "next": nxt,
        "handoff_digest": pack.get("while_away"),
        "room_text": room_text,
    }
    if skills_step:
        res["skills_step"] = skills_step
    return res


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


def rest_attach(info, conn, result, agent_token="", session_id="rest", kind="turn", context_state="normal", gist="", duty=""):
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
            if soft_nudge_due(info.get("key_id"), session_id or "rest"):
                return _hinted(result, SOFT_IDENTIFY_HINT)
            return result
        return _hinted(result, REST_IDENTIFY_HINT)
    who = gate(info, conn, agent_token, session_id or "rest")
    if not isinstance(who, dict) or not who.get("ok"):
        hint = REST_IDENTIFY_HINT if (who or {}).get("error") == "IDENTIFY_REQUIRED" else REST_BAD_TOKEN_HINT
        return _hinted(result, hint)
    return finish_turn(conn, info, who, result, kind=kind or "turn", context_state=context_state or "normal",
                       gist=turn_gist(gist or ""), duty=duty or "")


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
    mark_pack_seen(conn, info.get("key_id") or "", who["actor_id"], session_id or "rest")
    return {
        "ok": True,
        "step_zero": bool(pack.get("step_zero")),
        "kind": pack.get("kind"),
        "text": pack.get("text") or "",
        "while_away": pack.get("while_away"),
        "others_block": pack.get("others_block") or "",
    }
