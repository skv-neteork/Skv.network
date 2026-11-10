"""Agent identity. The token is returned once; only its hash is stored."""
import hashlib
import re
import secrets

from app.room.clock import as_dt, iso, parse_iso
from app.room.copy import RESERVED_NAMES, ROLES
from app.room.schema import ensure

_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])?$|^[a-z0-9]{3}$")


def token_hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()


def check_name(name):
    n = (name or "").strip().lower()
    if n in RESERVED_NAMES:
        raise ValueError("name reserved")
    if not (3 <= len(n) <= 32) or not re.fullmatch(r"[a-z0-9-]+", n):
        raise ValueError("name must be lowercase [a-z0-9-], 3-32")
    if n.startswith("-") or n.endswith("-"):
        raise ValueError("name must be lowercase [a-z0-9-], 3-32")
    return n


def _suggestion(conn, key_id, name):
    base = name
    for i in range(2, 20):
        suf = "-%d" % i
        cand = (base[: 32 - len(suf)] + suf) if len(base) + len(suf) > 32 else base + suf
        row = conn.execute("SELECT 1 FROM agents WHERE key_id=? AND name=?", (key_id, cand)).fetchone()
        if not row:
            return cand
    return name + "-2"


def _row(conn, key_id, name):
    r = conn.execute(
        "SELECT id, token_hash, session_id, last_seen_at, role FROM agents WHERE key_id=? AND name=?",
        (key_id, name),
    ).fetchone()
    if not r:
        return None
    return {"id": r[0], "token_hash": r[1], "session_id": r[2] or "", "last_seen_at": r[3], "role": r[4]}


def explicit_count(conn, key_id):
    ensure(conn)
    return conn.execute("SELECT COUNT(*) FROM agents WHERE key_id=?", (key_id,)).fetchone()[0]


def identify(conn, key_id, chain_id, name, role="assistant", client_hint="", session_id="", now=None, display_name=""):
    """Return a fresh token, or NAME_IN_USE. Does not replace another session's token hash."""
    ensure(conn)
    name = check_name(name)
    # role and client_hint are optional. An unknown role is kept in client_hint and the agent is an assistant.
    role_in = (role or "").strip()
    role = role_in.lower() or "assistant"
    if role not in ROLES:
        client_hint = ("role=%s %s" % (role_in[:40], client_hint or "")).strip()
        role = "assistant"
    client_hint = str(client_hint or "")
    session_id = (session_id or "").strip() or secrets.token_hex(8)
    now_dt = as_dt(now)
    cur = _row(conn, key_id, name)
    if cur:
        seen = parse_iso(cur["last_seen_at"])
        busy = seen and (now_dt - seen).total_seconds() < 30 * 60 and (cur["session_id"] or "") != session_id
        if busy:
            return {
                "error": "NAME_IN_USE",
                "suggestion": _suggestion(conn, key_id, name),
                "agent_id": cur["id"],
                "saved": False,
            }
    token = secrets.token_urlsafe(32)
    th = token_hash(token)
    stamp = iso(now_dt)
    if cur:
        conn.execute(
            "UPDATE agents SET token_hash=?, session_id=?, last_seen_at=?, client_hint=?, role=?, display_name=?, chain_id=? "
            "WHERE key_id=? AND id=?",
            (th, session_id, stamp, (client_hint or "")[:200], role, (display_name or name)[:80], chain_id, key_id, cur["id"]),
        )
        agent_id = cur["id"]
    else:
        agent_id = name
        conn.execute(
            "INSERT INTO agents (id, key_id, chain_id, name, display_name, role, token_hash, client_hint, created_at, last_seen_at, session_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (agent_id, key_id, chain_id, name, (display_name or name)[:80], role, th, (client_hint or "")[:200], stamp, stamp, session_id),
        )
    conn.commit()
    return {
        "agent_id": agent_id,
        "agent_token": token,
        "session_id": session_id,
        "role": role,
        "name": name,
    }


def _touch_seen(conn, key_id, agent_id, session_id, now):
    conn.execute(
        "UPDATE agents SET last_seen_at=?, session_id=? WHERE key_id=? AND id=?",
        (iso(now), session_id or "", key_id, agent_id),
    )


def resolve_call(conn, key_id, chain_id, key_name, agent_token="", session_id="", client_hint="", client_actor="", now=None):
    """Server actor. client_actor is ignored. A key with no identify() rows stays implicit."""
    ensure(conn)
    now_dt = as_dt(now)
    session_id = (session_id or "").strip() or "mcp"
    n_explicit = explicit_count(conn, key_id)
    if agent_token:
        th = token_hash(agent_token)
        row = conn.execute(
            "SELECT id, role, name, session_id FROM agents WHERE key_id=? AND token_hash=?",
            (key_id, th),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "BAD_TOKEN", "saved": False}
        _touch_seen(conn, key_id, row[0], session_id, now_dt)
        conn.commit()
        return {"ok": True, "actor_id": row[0], "role": row[1], "name": row[2], "implicit": False, "multi": n_explicit > 0, "key_id": key_id, "chain_id": chain_id}
    if n_explicit == 0:
        return {
            "ok": True,
            "actor_id": key_name or "agent",
            "role": "assistant",
            "name": key_name or "agent",
            "implicit": True,
            "multi": False,
            "key_id": key_id,
            "chain_id": chain_id,
        }
    bound = conn.execute(
        "SELECT id, role, name, last_seen_at FROM agents WHERE key_id=? AND session_id=?",
        (key_id, session_id),
    ).fetchall()
    live = []
    for r in bound:
        seen = parse_iso(r[3])
        if seen and (now_dt - seen).total_seconds() < 30 * 60:
            live.append(r)
    if len(live) == 1:
        _touch_seen(conn, key_id, live[0][0], session_id, now_dt)
        conn.commit()
        return {"ok": True, "actor_id": live[0][0], "role": live[0][1], "name": live[0][2], "implicit": False, "multi": True, "key_id": key_id, "chain_id": chain_id, "bound": True}
    row = conn.execute("SELECT n FROM identify_misses WHERE key_id=? AND session_id=?", (key_id, session_id)).fetchone()
    n = (row[0] if row else 0) + 1
    conn.execute(
        "INSERT OR REPLACE INTO identify_misses (key_id, session_id, n) VALUES (?,?,?)",
        (key_id, session_id, n),
    )
    conn.commit()
    if n < 2:
        return {
            "ok": False,
            "error": "IDENTIFY_REQUIRED",
            "hint": (client_hint or "")[:120],
            "saved": False,
            "multi": True,
        }
    actor = "unidentified@%s" % session_id
    return {
        "ok": True,
        "actor_id": actor,
        "role": "assistant",
        "name": actor,
        "implicit": False,
        "multi": True,
        "unidentified": True,
        "warning": "saved as %s; this lane is not another agent's" % actor,
        "key_id": key_id,
        "chain_id": chain_id,
    }


def hash_of(conn, key_id, agent_id):
    r = conn.execute("SELECT token_hash FROM agents WHERE key_id=? AND id=?", (key_id, agent_id)).fetchone()
    return r[0] if r else ""
