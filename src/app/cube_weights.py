"""Exposure, application, and outcome traces.

Rank is the join of those three. Decay lowers rank. This module never deletes a cube.
A trace is not a cube_vote and not a cube_confirm. Those stay explicit agent calls.
"""
import time

KINDS = ("exposure", "application", "outcome")
HALF_LIFE_DAYS = 90.0


def ensure(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cube_weight_trace (
            id INTEGER PRIMARY KEY,
            cube_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            account_id TEXT,
            value REAL,
            ref TEXT,
            ts REAL NOT NULL)"""
    )


def _decay(ts, now):
    age_days = max(0.0, (float(now) - float(ts)) / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def recompute(conn, cube_id, now=None):
    """Join the three traces and, when the cube row exists, store rank_v0. Never DELETE."""
    now = time.time() if now is None else float(now)
    rows = conn.execute(
        "SELECT kind, value, ts FROM cube_weight_trace WHERE cube_id=?",
        (cube_id,),
    ).fetchall()
    exposure = application = 0.0
    outcomes = []
    newest = None
    for kind, value, ts in rows:
        weight = _decay(ts, now)
        if kind == "exposure":
            exposure += weight
        elif kind == "application":
            application += weight
        elif kind == "outcome":
            outcomes.append((max(-1.0, min(1.0, float(value))), weight))
        newest = float(ts) if newest is None else max(newest, float(ts))
    score = 1.0 + 0.15 * exposure + 0.45 * application
    if outcomes:
        mass = sum(w for _v, w in outcomes) or 1.0
        mean = sum(v * w for v, w in outcomes) / mass
        score *= max(0.05, 0.5 + 0.5 * mean)
    if newest is not None:
        score *= _decay(newest, now)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "cubes_new" in tables:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(cubes_new)")}
        if "rank_v0" in cols:
            conn.execute("UPDATE cubes_new SET rank_v0=? WHERE cube_id=?", (float(score), cube_id))
    return float(score)


def record(conn, cube_id, kind, account_id="", value=1.0, ref="", ts=None):
    """Insert one trace of one kind and refresh rank. Does not vote or confirm."""
    if kind not in KINDS:
        raise ValueError("kind must be exposure, application, or outcome")
    ensure(conn)
    ts = time.time() if ts is None else float(ts)
    conn.execute(
        "INSERT INTO cube_weight_trace (cube_id, kind, account_id, value, ref, ts) VALUES (?,?,?,?,?,?)",
        (cube_id, kind, (account_id or "")[:120], float(value), (ref or "")[:200], ts),
    )
    rank = recompute(conn, cube_id, now=ts)
    return {"ok": True, "kind": kind, "rank_v0": rank, "voted": False, "confirmed": False}


def count_kind(conn, cube_id, kind):
    ensure(conn)
    return conn.execute(
        "SELECT COUNT(*) FROM cube_weight_trace WHERE cube_id=? AND kind=?",
        (cube_id, kind),
    ).fetchone()[0]
