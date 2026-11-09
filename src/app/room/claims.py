"""Task claims. Enforcement runs only when the caller passes an actor."""
from app.room.clock import as_dt, iso, plus
from app.room.events import record_event
from app.room.schema import ensure

TASK_MIN = 30
FILE_MIN = 20


class ClaimConflict(Exception):
    def __init__(self, owner, rev=None):
        self.owner = owner or ""
        self.rev = rev
        super().__init__("409 claimed_by=%s" % self.owner)


def _get(conn, item_id):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(board_items)")}
    if "item_id" not in cols and "claimed_by" not in cols:
        ensure(conn)
    row = conn.execute(
        "SELECT item_id, status, claimed_by, lease_until, rev, created_by, removed FROM board_items WHERE item_id=?",
        (item_id,),
    ).fetchone()
    if not row or row[6]:
        return None
    return {"item_id": row[0], "status": row[1] or "", "claimed_by": row[2] or "", "lease_until": row[3] or "",
            "rev": int(row[4] or 0), "created_by": row[5] or ""}


def _lease_alive(row, now):
    if not row or not row["claimed_by"] or not row["lease_until"]:
        return False
    return row["lease_until"] >= iso(as_dt(now))


def add_task(conn, item_id, title="", created_by="", status="todo", now=None):
    ensure(conn)
    conn.execute(
        """INSERT OR IGNORE INTO board_items
           (item_id, kind, title, body, status, updated_at, removed, created_by, claimed_by, lease_until, rev, created_at)
           VALUES (?,?,?,?,?,?,0,?,?,?,0,?)""",
        (item_id, "task", title or item_id, "", status, iso(as_dt(now)), created_by or "", "", "", iso(as_dt(now))),
    )
    conn.commit()
    return _get(conn, item_id)


def claim_task(conn, item_id, actor_id, expected_rev=None, chain_id="", key_id="", now=None, session_id=""):
    ensure(conn)
    row = _get(conn, item_id)
    if not row:
        raise KeyError(item_id)
    now_dt = as_dt(now)
    if expected_rev is not None and int(expected_rev) != row["rev"]:
        raise ClaimConflict(row["claimed_by"], row["rev"])
    if row["claimed_by"] and row["claimed_by"] != actor_id and _lease_alive(row, now_dt):
        raise ClaimConflict(row["claimed_by"], row["rev"])
    lease = iso(plus(now_dt, minutes=TASK_MIN))
    rev = row["rev"] + 1
    conn.execute(
        "UPDATE board_items SET claimed_by=?, lease_until=?, rev=?, created_by=coalesce(NULLIF(created_by,''), ?), updated_at=? WHERE item_id=?",
        (actor_id, lease, rev, actor_id, iso(now_dt), item_id),
    )
    ev = record_event(conn, chain_id or "", key_id or "", actor_id, session_id, kind="claim", text=item_id,
                      task_id=item_id, now=now_dt)
    return {"item_id": item_id, "claimed_by": actor_id, "rev": rev, "lease_until": lease, "event_id": ev["event_id"]}


def release_task(conn, item_id, actor_id, now=None):
    ensure(conn)
    row = _get(conn, item_id)
    if not row:
        raise KeyError(item_id)
    if row["claimed_by"] and row["claimed_by"] != actor_id:
        raise ClaimConflict(row["claimed_by"], row["rev"])
    now_s = iso(as_dt(now))
    conn.execute(
        "UPDATE board_items SET claimed_by='', lease_until='', rev=?, status=CASE WHEN status='doing' THEN 'todo' ELSE status END, updated_at=? WHERE item_id=?",
        (row["rev"] + 1, now_s, item_id),
    )
    conn.commit()
    return {"item_id": item_id, "released": True}


def assert_doing(conn, item_id, actor_id, now=None):
    """doing requires a live claim by this actor. No actor → caller skips this."""
    if not actor_id:
        return
    row = _get(conn, item_id)
    if not row:
        raise KeyError(item_id)
    if row["claimed_by"] != actor_id or not _lease_alive(row, now):
        raise ValueError("doing requires a claim")


def assert_done(conn, item_id, actor_id, author_kind="agent", now=None):
    if not actor_id or author_kind == "human":
        return
    row = _get(conn, item_id)
    if not row:
        raise KeyError(item_id)
    if row["claimed_by"] != actor_id or not _lease_alive(row, now):
        raise ValueError("done only by the claim owner or a human")


def expire_tasks(conn, chain_id="", key_id="", now=None):
    """Expired lease → task back to todo, plus a handoff notice from room-lease."""
    ensure(conn)
    now_dt = as_dt(now)
    now_s = iso(now_dt)
    rows = conn.execute(
        "SELECT item_id, claimed_by, status, lease_until FROM board_items WHERE removed=0 AND coalesce(claimed_by,'')!='' AND coalesce(lease_until,'')!='' AND lease_until<?",
        (now_s,),
    ).fetchall()
    notices = []
    for item_id, owner, status, _lease in rows:
        conn.execute(
            "UPDATE board_items SET claimed_by='', lease_until='', status=?, updated_at=? WHERE item_id=?",
            ("todo" if status in ("doing", "todo", "") else status, now_s, item_id),
        )
        ev = record_event(
            conn, chain_id or "", key_id or "", "room-lease", "", kind="handoff",
            text="LEASE_EXPIRED task#%s back to todo" % item_id, task_id=item_id,
            target_actor=owner, now=now_dt,
        )
        notices.append(ev["event_id"])
    conn.commit()
    return notices


def renew_leases(conn, actor_id, chain_id="", now=None):
    """Extend only this actor's open leases: tasks 30 min, files 20 min."""
    if not actor_id:
        return {"tasks": 0, "files": 0}
    ensure(conn)
    now_dt = as_dt(now)
    t_lease = iso(plus(now_dt, minutes=TASK_MIN))
    f_lease = iso(plus(now_dt, minutes=FILE_MIN))
    cur = conn.execute(
        "UPDATE board_items SET lease_until=? WHERE removed=0 AND claimed_by=? AND coalesce(lease_until,'')!=''",
        (t_lease, actor_id),
    )
    tasks = cur.rowcount if cur.rowcount is not None else 0
    cur = conn.execute(
        "UPDATE resource_claims SET lease_until=? WHERE actor_id=? AND (released_at IS NULL OR released_at='')",
        (f_lease, actor_id),
    )
    files = cur.rowcount if cur.rowcount is not None else 0
    conn.commit()
    return {"tasks": tasks, "files": files}
