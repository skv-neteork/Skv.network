"""Server-stamped room events. A client-supplied actor is ignored."""
import re

from app.room.clock import as_dt, iso
from app.room.schema import ensure

_SECRET = re.compile(r"(sk_|pza_|re_[A-Za-z0-9]{10,}|agent_token|BEGIN PRIVATE)", re.I)


def make_gist(kind, text="", path="", task_id="", old_hash="", new_hash="", minus=0, plus=0):
    kind = kind or "turn"
    if kind == "file_change":
        g = "FILE_CHANGE %s %s→%s (−%s/+%s)" % (path or "?", (old_hash or "")[:7], (new_hash or "")[:7], int(minus or 0), int(plus or 0))
    elif kind == "claim":
        g = "CLAIM task#%s" % (task_id or "?")
    elif kind == "turn":
        g = ""
    else:
        label = {
            "handoff": "HANDOFF",
            "result": "RESULT",
            "blocked": "BLOCKED",
            "decision": "DECISION",
            "brief": "BRIEF",
            "human_directive": "HUMAN",
        }.get(kind, kind.upper())
        g = (label + " " + (text or "")).strip()
    g = re.sub(r"\s+", " ", g).strip()
    return g[:100]


def safe_essence(text):
    s = re.sub(r"\s+", " ", (text or "")).strip()
    if not s or len(s) > 80 or _SECRET.search(s):
        return ""
    return s


def record_event(conn, chain_id, key_id, actor_id, session_id="", kind="turn", author_kind="agent",
                 text="", essence="", path="", task_id="", target_actor="", event_id=None, now=None,
                 client_actor=None, old_hash="", new_hash="", minus=0, plus=0):
    """Stamp actor_id from the server. client_actor is discarded and never stored."""
    ensure(conn)
    del client_actor
    kind = (kind or "turn").strip()
    author_kind = author_kind if author_kind in ("agent", "human") else "agent"
    gist = make_gist(kind, text=text, path=path, task_id=task_id, old_hash=old_hash, new_hash=new_hash, minus=minus, plus=plus)
    ess = safe_essence(essence or (text if kind == "turn" else ""))
    stamp = iso(as_dt(now))
    actor = actor_id if actor_id else None
    cur = conn.execute(
        """INSERT INTO room_events
           (event_id, chain_id, key_id, actor_agent_id, session_id, ev_kind, author_kind, gist, essence, body, path, task_id, target_actor, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id or ("tmp-%s" % secrets_hex()), chain_id, key_id, actor, session_id or "", kind, author_kind,
         gist, ess, (text or "")[:2000], path or "", task_id or "", target_actor or "", stamp),
    )
    rid = cur.lastrowid
    if not event_id:
        event_id = "r%d" % rid
        conn.execute("UPDATE room_events SET event_id=? WHERE id=?", (event_id, rid))
    if path and actor:
        conn.execute(
            "INSERT INTO room_touches (chain_id, key_id, actor_id, path, task_id, at) VALUES (?,?,?,?,?,?)",
            (chain_id, key_id, actor, path, task_id or "", stamp),
        )
    if task_id and actor and kind == "claim":
        conn.execute(
            "INSERT INTO room_touches (chain_id, key_id, actor_id, path, task_id, at) VALUES (?,?,?,?,?,?)",
            (chain_id, key_id, actor, "", task_id, stamp),
        )
    _stamp_metadata(conn, event_id, actor, session_id, kind, author_kind, gist)
    conn.commit()
    return _one(conn, rid)


def secrets_hex():
    import secrets
    return secrets.token_hex(8)


def _stamp_metadata(conn, event_id, actor, session_id, kind, author_kind, gist):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
    if "actor_agent_id" not in cols or not event_id:
        return
    conn.execute(
        "UPDATE event_metadata SET actor_agent_id=?, session_id=?, ev_kind=?, author_kind=?, gist=? WHERE event_id=?",
        (actor, session_id or "", kind, author_kind, gist, event_id),
    )


def _one(conn, rid):
    row = conn.execute(
        "SELECT id, event_id, chain_id, key_id, actor_agent_id, session_id, ev_kind, author_kind, gist, essence, body, path, task_id, target_actor, created_at FROM room_events WHERE id=?",
        (rid,),
    ).fetchone()
    keys = ("id", "event_id", "chain_id", "key_id", "actor_agent_id", "session_id", "ev_kind", "author_kind", "gist", "essence", "body", "path", "task_id", "target_actor", "created_at")
    return dict(zip(keys, row))


def list_events(conn, chain_id):
    ensure(conn)
    rows = conn.execute(
        "SELECT id, event_id, chain_id, key_id, actor_agent_id, session_id, ev_kind, author_kind, gist, essence, body, path, task_id, target_actor, created_at "
        "FROM room_events WHERE chain_id=? ORDER BY id",
        (chain_id,),
    ).fetchall()
    keys = ("id", "event_id", "chain_id", "key_id", "actor_agent_id", "session_id", "ev_kind", "author_kind", "gist", "essence", "body", "path", "task_id", "target_actor", "created_at")
    return [dict(zip(keys, r)) for r in rows]


def legacy_rows(conn, limit=5):
    """event_metadata rows with a NULL actor, if that table exists. Never treated as own."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
    if not cols:
        return []
    if "actor_agent_id" in cols:
        q = "SELECT event_id, coalesce(gist, essence, '') FROM event_metadata WHERE actor_agent_id IS NULL ORDER BY rowid DESC LIMIT ?"
    else:
        q = "SELECT event_id, coalesce(essence, '') FROM event_metadata ORDER BY rowid DESC LIMIT ?"
    try:
        return [{"event_id": r[0], "gist": (r[1] or "")[:140]} for r in conn.execute(q, (limit,)).fetchall()]
    except Exception:
        return []
