"""Line filter inside candidate retrieval (B10).

HNSW and events_fts_stem are per-account and not line-shadowed. Filtering after top-k
lets other lines crowd out the caller's hits. Apply the line scope while retrieving:
vector over-fetch + keep until enough visible; FTS with a temp-table condition.
lines=all -> LINE_CTX is None -> no filter.
"""
from app.search_text import _line_ctx, _visible


def ctx():
    return _line_ctx()


def visible(eid):
    return _visible(ctx(), eid)


def take(pairs, k=None):
    """[(eid, score), ...] -> only visible, optionally cut to k."""
    c = ctx()
    if not c:
        return list(pairs[:k] if k is not None else pairs)
    out = [(e, s) for e, s in pairs if _visible(c, e)]
    return out[:k] if k is not None else out


def attach_vis(conn):
    """Temp table of the caller's visible event ids on this connection. Returns SQL AND-clause or ''."""
    c = ctx()
    if not c:
        return ""
    ids = list(c.get("ids") or [])
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _skv_line(id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _skv_line")
    if ids:
        conn.executemany("INSERT OR IGNORE INTO _skv_line VALUES (?)", [(i,) for i in ids])
    if c.get("mode") == "deny":
        if not ids:
            return ""
        return "AND event_id NOT IN (SELECT id FROM _skv_line)"
    # allow: only the tagged own-line ids (untagged belong to main, so a non-main line sees tagged-own only)
    if not ids:
        return "AND 0"
    return "AND event_id IN (SELECT id FROM _skv_line)"


def semantic_visible(uid, query, k=80, cap=4000):
    """Vector hits with line filter applied before the cut. Over-fetches until k visible or the index is exhausted."""
    from app import semantic as _sem
    c = ctx()
    fetch = k if not c else min(cap, max(int(k) * 8, 200))
    last = -1
    vec = None
    while True:
        hits, vec = _sem.semantic_events(uid, query, k=fetch)
        vis = take([(e, s) for e, s in hits if str(e).startswith(str(uid) + "::")], k)
        got = len(hits)
        if len(vis) >= k or not c or got <= last or got < fetch:
            return vis, vec
        last = got
        nxt = min(cap, fetch * 2)
        if nxt <= fetch:
            return vis, vec
        fetch = nxt
