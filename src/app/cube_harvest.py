"""Per-account cube-harvest fallback (25.10), used only when the caller has no identified agent.

Identified agents use the per-agent reminder in app.room.skills_harvest (same duty name: cube_harvest,
~SKV_SKILLS_HARVEST_HOURS / 72h). This module stays for implicit sessions and for GET /cube_harvest/due.
Closing aliases (cube_harvest, skills_harvest, skills_none, skills_skip) reset this timer via done().
The reminder points at the live author cube (CUBE_ID followed through superseded_by)."""
import os, sqlite3, time
DB = "/data/skv/metadata_store/cube_harvest.db"
CUBE_ID = "cube_688c0ebbb3be"
BASE = "/data/skv/metadata_store"
MIN_TURNS = 10          # fewer new turns than this: nothing worth harvesting, stay quiet
TURN_COOLDOWN_S = 6 * 3600   # in turn() show it at most every 6 h; step_zero always shows it while due


def latest_cube_id(cid=None):
    """CUBE_ID may be superseded by newer versions (cube_688c0ebbb3be -> ... ): follow links_json.superseded_by so the
    reminder points at the live harvest/author cube. Falls back to CUBE_ID. (2026-11-02)"""
    import json
    cid = cid or CUBE_ID
    try:
        c = sqlite3.connect("file:/data/skv/metadata_store/shared_master.db?mode=ro", uri=True, timeout=5)
        try:
            for _ in range(20):
                r = c.execute("select coalesce(status,''), links_json from cubes_new where cube_id=?", (cid,)).fetchone()
                if not r or r[0] != "superseded":
                    break
                nxt = (json.loads(r[1] or "{}") or {}).get("superseded_by") if (r[1] or "").startswith("{") else None
                if not nxt:
                    break
                cid = nxt
        finally:
            c.close()
    except Exception:
        return CUBE_ID
    return cid


def _days():
    """Interval in days. SKV_SKILLS_HARVEST_HOURS wins when set; else SKV_CUBE_HARVEST_DAYS; else 3."""
    try:
        if os.environ.get("SKV_SKILLS_HARVEST_HOURS"):
            from app.room.skills_harvest import interval_hours
            return max(0.01, float(interval_hours()) / 24.0)
        return max(0.01, float(os.environ.get("SKV_CUBE_HARVEST_DAYS", "3")))
    except Exception:
        return 3.0


def _db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("create table if not exists h(user text primary key, last_t real, last_rowid int, shown_t real, n_done int default 0)")
    return c


def _udb(user):
    from app.account_memory import account_db_name
    cands = [os.path.join(BASE, account_db_name(user) + ".db"), os.path.join(BASE, account_db_name(user).replace("+", "") + ".db")]
    best, mx = None, -1
    for p in dict.fromkeys(cands):
        if not os.path.exists(p):
            continue
        try:
            u = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=5)
            r = u.execute("select max(rowid) from event_metadata").fetchone()[0] or 0
            u.close()
            if r > mx:
                best, mx = p, r
        except Exception:
            pass
    return best, max(mx, 0)


def _range(path, after):
    u = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    try:
        rows = u.execute("select rowid, event_id, time_str from event_metadata where rowid>? order by rowid", (after,)).fetchall()
    finally:
        u.close()
    sid = lambda e: (e or "").split("::")[-1]
    if not rows:
        return 0, None, None, None
    return len(rows), sid(rows[0][1]), sid(rows[-1][1]), rows[0][2]


def due(user, where="turn"):
    """{'cube_harvest': {...}} when a harvest is due, else {}. Never raises."""
    if not user:
        return {}
    try:
        now = time.time(); c = _db()
        row = c.execute("select last_t, last_rowid, shown_t from h where user=?", (user,)).fetchone()
        path, mx = _udb(user)
        if not row:   # first sight: start the clock, no reminder on day one
            c.execute("insert into h(user,last_t,last_rowid,shown_t) values(?,?,?,0)", (user, now, mx)); c.commit(); c.close()
            return {}
        last_t, last_rowid, shown_t = row
        if now - (last_t or 0) < _days() * 86400 or not path:
            c.close(); return {}
        if where == "turn" and now - (shown_t or 0) < TURN_COOLDOWN_S:
            c.close(); return {}
        n, a, b, since = _range(path, last_rowid or 0)
        if n < MIN_TURNS:
            c.close(); return {}
        if where == "turn":   # step_zero shows it without starting the turn cooldown
            c.execute("update h set shown_t=? where user=?", (now, user)); c.commit()
        c.close()
        _cid = latest_cube_id()
        return {"cube_harvest": {
            "due": True, "kind": "reminder", "cube_id": _cid, "turns": n, "from_ev": a, "to_ev": b, "since": since,
            "do": "Harvest experience from these turns: cube_get(cube_id=\"%s\") and follow its cube_harvest-duty path "
                  "(repeated mistakes, fixes that worked, user corrections, new craft facts; search before writing; 0-2 strong cubes is normal)." % _cid,
            "close": "turn(..., duty=\"cube_harvest\", duty_reason=\"created: <ids> | fixed: <ids> | nothing: <why>\") resets the timer",
            "note": "reminder only, nothing is blocked"}}
    except Exception as e:
        print(f"[cube_harvest] due skipped: {type(e).__name__}: {e}", flush=True)
        return {}


def done(user, reason=""):
    try:
        _, mx = _udb(user); c = _db(); now = time.time()
        c.execute("insert into h(user,last_t,last_rowid,shown_t,n_done) values(?,?,?,0,1) on conflict(user) do update set last_t=?, last_rowid=?, shown_t=0, n_done=coalesce(n_done,0)+1",
                  (user, now, mx, now, mx))
        c.commit(); c.close()
        return {"cube_harvest_done": True, "next_in_days": _days()}
    except Exception as e:
        print(f"[cube_harvest] done skipped: {e}", flush=True)
        return {}
