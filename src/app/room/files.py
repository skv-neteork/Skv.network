"""File claims. One open claim per chain and relative path."""
import hashlib
import re

from app.room.clock import as_dt, iso, plus
from app.room.copy import CHECK_REREAD
from app.room.events import record_event
from app.room.schema import ensure

FILE_MIN = 20


class FileConflict(Exception):
    def __init__(self, owner):
        self.owner = owner or ""
        super().__init__("409 file claimed_by=%s" % self.owner)


def normalize_path(path):
    p = (path or "").replace("\\", "/").strip()
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise ValueError("relative path required")
    parts = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                raise ValueError("path escapes the work tree")
            parts.pop()
            continue
        parts.append(seg)
    if not parts:
        raise ValueError("empty path")
    return "/".join(parts)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _open(conn, chain_id, path, now=None):
    row = conn.execute(
        "SELECT id, actor_id, base_hash, lease_until, task_id FROM resource_claims WHERE chain_id=? AND path=? AND (released_at IS NULL OR released_at='')",
        (chain_id, path),
    ).fetchone()
    if not row:
        return None
    if now is not None and row[3] and row[3] < iso(as_dt(now)):
        return None
    return {"id": row[0], "actor_id": row[1], "base_hash": row[2] or "", "lease_until": row[3] or "", "task_id": row[4] or ""}


def file_claim(conn, chain_id, path, actor_id, base_hash="", task_id="", key_id="", now=None, session_id=""):
    ensure(conn)
    path = normalize_path(path)
    now_dt = as_dt(now)
    cur = _open(conn, chain_id, path, now_dt)
    if cur and cur["actor_id"] != actor_id:
        raise FileConflict(cur["actor_id"])
    lease = iso(plus(now_dt, minutes=FILE_MIN))
    if cur and cur["actor_id"] == actor_id:
        conn.execute(
            "UPDATE resource_claims SET lease_until=?, base_hash=?, task_id=? WHERE id=?",
            (lease, base_hash or cur["base_hash"], task_id or cur["task_id"], cur["id"]),
        )
        conn.commit()
        return {"path": path, "actor_id": actor_id, "base_hash": base_hash or cur["base_hash"], "lease_until": lease}
    conn.execute(
        "INSERT INTO resource_claims (chain_id, path, actor_id, task_id, base_hash, lease_until, released_at, new_hash) VALUES (?,?,?,?,?,?,NULL,'')",
        (chain_id, path, actor_id, task_id or "", base_hash or "", lease),
    )
    conn.execute(
        "INSERT INTO room_touches (chain_id, key_id, actor_id, path, task_id, at) VALUES (?,?,?,?,?,?)",
        (chain_id, key_id or "", actor_id, path, task_id or "", iso(now_dt)),
    )
    conn.commit()
    return {"path": path, "actor_id": actor_id, "base_hash": base_hash or "", "lease_until": lease}


def file_check(conn, chain_id, path, current_hash, now=None):
    ensure(conn)
    path = normalize_path(path)
    cur = _open(conn, chain_id, path, now)
    if not cur:
        return {"ok": True, "path": path, "message": ""}
    if (current_hash or "") != (cur["base_hash"] or ""):
        return {"ok": False, "path": path, "message": CHECK_REREAD, "base_hash": cur["base_hash"]}
    return {"ok": True, "path": path, "message": ""}


def file_release(conn, chain_id, path, actor_id, new_hash="", key_id="", now=None, session_id="", minus=0, plus=0, old_hash=""):
    ensure(conn)
    path = normalize_path(path)
    now_dt = as_dt(now)
    cur = _open(conn, chain_id, path, None)
    if not cur:
        raise KeyError(path)
    if cur["actor_id"] != actor_id:
        raise FileConflict(cur["actor_id"])
    conn.execute(
        "UPDATE resource_claims SET released_at=?, new_hash=? WHERE id=?",
        (iso(now_dt), new_hash or "", cur["id"]),
    )
    ev = record_event(
        conn, chain_id, key_id or "", actor_id, session_id, kind="file_change", path=path,
        old_hash=old_hash or cur["base_hash"], new_hash=new_hash or "", minus=minus, plus=plus, now=now_dt,
    )
    return {"path": path, "released": True, "event_id": ev["event_id"], "gist": ev["gist"]}
