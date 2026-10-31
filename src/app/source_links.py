"""Source links: every L1/L2 summary, critical fact and board item -> its source events (ev ids).
Ids: l1:<session_id>, l2:<block id>, crit:<key>, board:<item_id>. Table source_links in the account db.
link_all() is idempotent; called right after creation sites and before reads (backfill)."""
import json, re

def ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS source_links (obj_id TEXT PRIMARY KEY, kind TEXT, source_event_ids TEXT,
                 status TEXT, method TEXT, related_event_ids TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

def _put(c, oid, kind, ids, method, related=None, force=False):
    ids = [i for i in dict.fromkeys(ids or []) if i]
    st = "linked" if ids else "unlinked"
    old = c.execute("SELECT status, method FROM source_links WHERE obj_id=?", (oid,)).fetchone()
    if old and not force and old[1] == method and old[0] == st:
        return
    if old and old[1] == "agent" and method != "agent":
        return   # agent-given sources are never replaced by guesses
    c.execute("INSERT OR REPLACE INTO source_links (obj_id, kind, source_event_ids, status, method, related_event_ids, updated_at) VALUES (?,?,?,?,?,?,datetime('now'))",
              (oid, kind, json.dumps(ids), st, method, json.dumps(related or [])))

def _range(c, fr, to):
    if fr is None or to is None:
        return []
    return [r[0] for r in c.execute("SELECT event_id FROM event_metadata WHERE rowid BETWEEN ? AND ? ORDER BY rowid", (int(fr), int(to)))]

def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())

def _cols(c, t):
    return [r[1] for r in c.execute(f"PRAGMA table_info({t})")]

def _near_time(c, ts, n=1):
    # event closest at/after ts (board created at ts, its turn saved right before/after)
    try:
        t = (ts or "")[:16]
        r = c.execute("SELECT event_id FROM event_metadata WHERE time_str >= ? ORDER BY time_str, rowid LIMIT 1", (t,)).fetchone() \
            or c.execute("SELECT event_id FROM event_metadata WHERE time_str <= ? ORDER BY time_str DESC, rowid DESC LIMIT 1", (t,)).fetchone()
        return [r[0]] if r else []
    except Exception:
        return []

def _text_match(c, text, limit=5):
    words = [w for w in re.findall(r"[\w-]{5,}", text or "")][:4]
    out = []
    for w in words:
        for r in c.execute("SELECT event_id FROM event_metadata WHERE raw_dialogue LIKE ? ORDER BY rowid DESC LIMIT 3", ("%" + w + "%",)):
            out.append(r[0])
    return list(dict.fromkeys(out))[:limit]

_STOP = set("""about after again against being because before between could doesn every first further having other should since their there these those through under until where which while would with without into from this that what when have will your also only more most such than then them they were been does done task tasks note notes guard guards board""".split())

def _board_match(c, title, body, iid=""):
    """Board item -> events by its own words. Source = earliest event containing most title words (>=2, or the only one);
    related = a few later hits. No match -> [] (unlinked; never a time guess)."""
    words = [w for w in dict.fromkeys(re.findall(r"[\w-]{4,}", (title or "").lower())) if w not in _STOP and not w.isdigit()][:6]
    if not words:
        words = [w for w in dict.fromkeys(re.findall(r"[\w-]{5,}", (body or "").lower())) if w not in _STOP][:4]
    if iid and re.match(r"^[A-Za-z]\d{2,}$", str(iid)):
        r = c.execute("SELECT event_id FROM event_metadata WHERE raw_dialogue LIKE ? ORDER BY rowid LIMIT 1", ("%TASK " + str(iid) + " %",)).fetchone()
        if r:
            rel = [x[0] for x in c.execute("SELECT event_id FROM event_metadata WHERE raw_dialogue LIKE ? AND event_id<>? ORDER BY rowid DESC LIMIT 5", ("%" + str(iid) + "%", r[0]))]
            return [r[0]], rel
    if len(words) < 2:
        return [], []
    need = 2 if len(words) < 4 else 3
    cand = c.execute("SELECT rowid, event_id, lower(substr(raw_dialogue,1,6000)) FROM event_metadata WHERE raw_dialogue LIKE ? ORDER BY rowid",
                     ("%" + max(words, key=len) + "%",)).fetchall()
    hits = [(r[0], r[1]) for r in cand if sum(1 for w in words if w in r[2]) >= need]
    if not hits:
        return [], []
    return [hits[0][1]], [h[1] for h in hits[1:]][-5:]

def link_board_event(c, item_id, event_id):
    """Called by board add: the creation event id (agent turn) is the source."""
    ensure(c)
    if event_id:
        _put(c, "board:" + str(item_id), "board", [event_id], "created_at_event", force=True)

def link_all(c, force=False):
    ensure(c)
    if _has(c, "summary_l1"):
        cols = _cols(c, "summary_l1")
        sel = "session_id, from_rowid, to_rowid, summary_text" if "from_rowid" in cols else "session_id, NULL, NULL, summary_text"
        for sid, fr, to, txt in c.execute(f"SELECT {sel} FROM summary_l1").fetchall():
            m = re.match(r".*?_(\d+)_(\d+)$", sid or "")
            if fr is None and m:
                fr, to = m.group(1), m.group(2)
            ids = _range(c, fr, to)
            _put(c, "l1:" + str(sid), "l1", ids or _text_match(c, txt), "rowid_range" if ids else "text_match", force=force)
    if _has(c, "summary_l2_blocks"):
        for bid, fr, to, txt in c.execute("SELECT id, from_rowid, to_rowid, text FROM summary_l2_blocks").fetchall():
            ids = _range(c, fr, to)
            _put(c, "l2:" + str(bid), "l2", ids or _text_match(c, txt), "rowid_range" if ids else "text_match", force=force)
    if _has(c, "critical_auto"):
        for key, eid, val in c.execute("SELECT key, event_id, value FROM critical_auto").fetchall():
            _put(c, "crit:" + key, "critical", [eid] if eid else _text_match(c, val, 1), "event_id" if eid else "text_match", force=force)
    if _has(c, "board_items"):
        done = {r[0] for r in c.execute("SELECT obj_id FROM source_links WHERE kind='board' AND method IN ('agent','created_at_event','title_match','unlinked_checked')")}
        for iid, title, body in c.execute("SELECT item_id, title, body FROM board_items").fetchall():
            oid = "board:" + str(iid)
            if oid in done and not force:
                continue
            src, rel = _board_match(c, title, body, iid)
            _put(c, oid, "board", src, "title_match" if src else "unlinked_checked", related=rel, force=True)
    c.commit()

def resolve(c, oid):
    link_all(c)
    oid = (oid or "").strip()
    if oid.startswith("l1:llm_summary"):
        return {"error": "generic id; use a real l1:<session_id> id"}
    r = c.execute("SELECT obj_id, kind, source_event_ids, status, method, related_event_ids FROM source_links WHERE obj_id=?", (oid,)).fetchone()
    if not r:
        return {"error": "unknown id", "id": oid}
    ids, rel = json.loads(r[2] or "[]"), json.loads(r[5] or "[]")
    text = ""
    k = r[1]
    try:
        if k == "l1": text = c.execute("SELECT summary_text FROM summary_l1 WHERE session_id=?", (oid[3:],)).fetchone()[0]
        elif k == "l2": text = c.execute("SELECT text FROM summary_l2_blocks WHERE id=?", (int(oid[3:]),)).fetchone()[0]
        elif k == "critical": text = "%s: %s" % c.execute("SELECT kind, value FROM critical_auto WHERE key=?", (oid[5:],)).fetchone()
        elif k == "board": text = "%s: %s" % c.execute("SELECT title, body FROM board_items WHERE item_id=?", (oid[6:],)).fetchone()
    except Exception:
        pass
    def ev(e):
        row = c.execute("SELECT time_str, substr(raw_dialogue,1,220) FROM event_metadata WHERE event_id=?", (e,)).fetchone()
        return {"event_id": e, "date": row[0] if row else None, "text": row[1] if row else None}
    return {"id": r[0], "kind": k, "status": r[3], "method": r[4], "text": (text or "")[:800],
            "source_event_ids": ids, "n_sources": len(ids), "sources": [ev(e) for e in ids[:12]],
            "related_event_ids": rel}

def short_index(c, limit=12):
    """Compact list for step_zero / consult start: id, kind, n sources, first/last ev."""
    link_all(c)
    out = []
    for oid, k, ids, st in c.execute("SELECT obj_id, kind, source_event_ids, status FROM source_links ORDER BY kind, obj_id LIMIT ?", (limit * 4,)):
        ids = json.loads(ids or "[]")
        sh = [i.split("::")[-1] for i in ids]
        out.append({"id": oid, "status": st, "src": (sh[:1] + (["…", sh[-1]] if len(sh) > 2 else sh[1:2])) if sh else [], "n": len(sh)})
    return out[:limit * 4]
