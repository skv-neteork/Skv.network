"""Memory lines (2026-10-24): each agent key (sk_, its chain_id) = its own memory line.
Default reads (/memory, /memory/start, /memory/dig, /session/bootstrap) show only the caller key's line.
Explicit cross-line search: body/query field lines="all" (MCP: memory_consult(lines="all")).
Events saved before lines existed (untagged) belong to the account's "main" line.
Storage stays one DB per account; lines are tagged in shared_master.event_lines and filtered on output.
Known limit: L1/L2 summaries built across lines are not split."""
import json, re, sqlite3
MASTER = "/data/skv/metadata_store/shared_master.db"
STORE = "/data/skv/metadata_store/"
READ_PATHS = {"/api/v7/memory", "/api/v7/memory/start", "/api/v7/memory/dig", "/api/v7/session/bootstrap", "/api/v7/search", "/api/v7/memory/lens", "/api/v7/memory/recall_later"}
READ_PREFIXES = ("/api/v7/memory/recall_later/", "/api/v7/event/")

def is_read(path):
    return path in READ_PATHS or path.startswith(READ_PREFIXES)
WRITE_PATHS = {"/api/v7/remember"}


def _m():
    c = sqlite3.connect(MASTER, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS event_lines (event_id TEXT PRIMARY KEY, user_id TEXT, chain_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_event_lines_user ON event_lines(user_id)")
    return c


def key_info(token):
    if not token:
        return None
    from app import api_keys as _ak
    info = _ak.chain_for_token(token)
    if not info or not info[1] or info[3] != "agent":
        return None  # session/internal keys see everything
    c = _m()
    try:
        row = c.execute("SELECT chain_id FROM user_api_keys WHERE user_id=? AND kind='agent' AND name='main' AND is_active=1 LIMIT 1", (info[0],)).fetchone()
    finally:
        c.close()
    return {"user_id": info[0], "chain_id": info[1], "main_chain": row[0] if row else None}


def tag(user_id, chain_id, event_ids):
    c = _m()
    try:
        for e in event_ids:
            if isinstance(e, str) and "::" in e:
                c.execute("INSERT OR IGNORE INTO event_lines(event_id,user_id,chain_id) VALUES (?,?,?)", (e, user_id, chain_id))
        c.commit()
    finally:
        c.close()


def foreign(ki):
    """Return (foreign_event_ids, foreign_snippets) for the caller's line."""
    uid, me = ki["user_id"], ki["chain_id"]
    is_main = (me == ki["main_chain"])
    c = _m()
    try:
        tagged = dict(c.execute("SELECT event_id, chain_id FROM event_lines WHERE user_id=?", (uid,)).fetchall())
    finally:
        c.close()
    db = STORE + re.sub(r"[^a-z0-9_]", "", uid.lower()) + ".db"
    ids, snips = set(), []
    own_tok, for_tok = set(), set()
    TOK = re.compile(r"\b[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+\b")
    try:
        u = sqlite3.connect("file:" + db + "?mode=ro", uri=True, timeout=5)
        rows = u.execute("SELECT event_id, raw_dialogue FROM event_metadata").fetchall()
        crit = u.execute("SELECT event_id, value FROM critical_auto").fetchall() if u.execute("SELECT 1 FROM sqlite_master WHERE name='critical_auto'").fetchone() else []
        u.close()
    except Exception:
        rows, crit = [], []
    for eid, raw in rows:
        ch = tagged.get(eid)
        mine = (ch == me) if ch is not None else is_main
        toks = {t for t in TOK.findall(raw or "") if len(t) >= 6 and re.search(r"[A-Za-z]", t) and re.search(r"\d", t)}
        (own_tok if mine else for_tok).update(toks)
        if not mine:
            ids.add(eid)
            s = (raw or "").strip().splitlines()[0][:60] if raw else ""
            if len(s) >= 12:
                snips.append(s)
    for eid, val in crit:
        if eid in ids and val and len(str(val)) >= 3:
            snips.append(str(val)) if len(str(val)) >= 6 else None
    snips.extend(sorted(for_tok - own_tok))  # distinctive codes (e.g. ABC-DEF-42) only seen in other lines
    return ids, snips


def _bad(o, ids, snips):
    if isinstance(o, dict):
        e = o.get("event_id")
        if isinstance(e, str) and e in ids:
            return True
        mem = o.get("member_ids")
        if isinstance(mem, list) and mem and all(m in ids for m in mem):
            return True
        return False
    if isinstance(o, str):
        return any(s in o for s in snips)
    return False


def scrub(o, ids, snips):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if isinstance(v, str) and k not in ("text", "context") and "\n" in v:
                out[k] = scrub_text(v, snips)
            else:
                out[k] = scrub(v, ids, snips)
        if isinstance(out.get("member_ids"), list):
            out["member_ids"] = [m for m in out["member_ids"] if m not in ids]
        return out
    if isinstance(o, list):
        return [scrub(x, ids, snips) for x in o if not _bad(x, ids, snips)]
    return o


def scrub_text(t, snips):
    if not snips:
        return t
    lines = t.split("\n"); out = []; skip = False
    for ln in lines:
        if any(s in ln for s in snips):
            skip = True; continue
        if skip and ln.startswith("A:"):
            continue
        skip = False; out.append(ln)
    return "\n".join(out)


def wants_all(query_params, body_bytes):
    v = (query_params.get("lines") or query_params.get("scope") or "").lower()
    if v == "all":
        return True
    try:
        b = json.loads(body_bytes or b"{}")
        return str(b.get("lines") or b.get("scope") or "").lower() == "all"
    except Exception:
        return False


# ---------- line-scoped DB view (2026-10-24b) ----------
# During a default (own-line) read, read-only connections to the account DB get TEMP VIEWs that shadow
# event_metadata / critical_auto / summary_l1 / summary_l1_v2 / summary_l2_blocks / summary_l2, so every layer
# (raw, L1, L2, critical, search) is built only from the caller line. Summary visibility:
#   explicit tag in summary_lines -> that line only; else rowid range must contain only the caller line's events;
#   legacy rows without a range -> main line only. lines=all -> no shadow (merged view).
import contextvars, os
LINE_CTX = contextvars.ContextVar("skv_line_ctx", default=None)
_orig_connect = getattr(sqlite3, "_skv_orig_connect", None) or sqlite3.connect
sqlite3._skv_orig_connect = _orig_connect


def _mm():
    c = _orig_connect(MASTER, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS event_lines (event_id TEXT PRIMARY KEY, user_id TEXT, chain_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS summary_lines (user_id TEXT, tbl TEXT, skey TEXT, chain_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, tbl, skey))")
    return c


def db_file(uid):
    return os.path.realpath(STORE + re.sub(r"[^a-z0-9_]", "", uid.lower()) + ".db")


def line_map(uid):
    c = _mm()
    try:
        return dict(c.execute("SELECT event_id, chain_id FROM event_lines WHERE user_id=?", (uid,)).fetchall())
    finally:
        c.close()


def make_ctx(ki):
    uid, me = ki["user_id"], ki["chain_id"]
    is_main = (me == ki["main_chain"])
    c = _mm()
    try:
        tags = c.execute("SELECT event_id, chain_id FROM event_lines WHERE user_id=?", (uid,)).fetchall()
        stags = c.execute("SELECT tbl, skey, chain_id FROM summary_lines WHERE user_id=?", (uid,)).fetchall()
    finally:
        c.close()
    if is_main:
        ids = [e for e, ch in tags if ch != me]
        if not ids and all(ch == me for _, _, ch in stags):
            return None
        mode = "deny"
    else:
        ids = [e for e, ch in tags if ch == me]
        mode = "allow"
    return {"db": db_file(uid), "is_main": is_main, "mode": mode, "ids": ids,
            "stags": [(t, k, 1 if ch == me else 0) for t, k, ch in stags]}


def tag_summaries(uid, chain_id, since_utc):
    """After /remember: agent-written L1/L2 rows from this request belong to the writer's line."""
    try:
        u = _orig_connect("file:" + db_file(uid) + "?mode=ro", uri=True, timeout=5)
        l1 = l2 = []
        try:
            l1 = [r[0] for r in u.execute("SELECT session_id FROM summary_l1 WHERE created_at >= ? AND session_id NOT LIKE 'llm_l1_%'", (since_utc,)).fetchall()]
        except Exception:
            pass
        try:
            l2 = [f"{r[0]}:{r[1]}" for r in u.execute("SELECT source, period_key FROM summary_l2_blocks WHERE created_at >= ? AND source='agent'", (since_utc,)).fetchall()]
        except Exception:
            pass
        u.close()
        c = _mm()
        try:
            c.executemany("INSERT OR REPLACE INTO summary_lines(user_id,tbl,skey,chain_id) VALUES (?,?,?,?)",
                          [(uid, "l1", k, chain_id) for k in l1 if k] + [(uid, "l2", k, chain_id) for k in l2])
            c.commit()
        finally:
            c.close()
    except Exception as e:
        print(f"[lines] tag_summaries error: {e}", flush=True)


def _range_ok(fr, to, tbl, key):
    tagged = f"EXISTS (SELECT 1 FROM temp._ln_stag g WHERE g.tbl='{tbl}' AND g.skey={key})"
    mine = f"EXISTS (SELECT 1 FROM temp._ln_stag g WHERE g.tbl='{tbl}' AND g.skey={key} AND g.mine=1)"
    lo = f"COALESCE({fr},{to})"
    rng = (f"({to} IS NOT NULL AND EXISTS (SELECT 1 FROM temp._ln_vis v WHERE v.r BETWEEN {lo} AND {to}) "
           f"AND NOT EXISTS (SELECT 1 FROM main.event_metadata e WHERE e.rowid BETWEEN {lo} AND {to} "
           f"AND e.rowid NOT IN (SELECT r FROM temp._ln_vis)))")
    return f"(CASE WHEN {tagged} THEN {mine} ELSE ({rng} OR ({to} IS NULL AND _ln_main())) END)"


def _shadow(conn, ctx):
    have = {r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
    if "event_metadata" not in have:
        return
    conn.create_function("_ln_main", 0, lambda: 1 if ctx["is_main"] else 0, deterministic=True)
    conn.execute("CREATE TEMP TABLE _ln_ids(id TEXT PRIMARY KEY)")
    conn.executemany("INSERT OR IGNORE INTO temp._ln_ids VALUES (?)", [(i,) for i in ctx["ids"]])
    conn.execute("CREATE TEMP TABLE _ln_stag(tbl TEXT, skey TEXT, mine INTEGER)")
    conn.executemany("INSERT INTO temp._ln_stag VALUES (?,?,?)", ctx["stags"])
    conn.execute("CREATE TEMP TABLE _ln_vis(r INTEGER PRIMARY KEY, eid TEXT)")
    neg = "NOT" if ctx["mode"] == "deny" else ""
    conn.execute(f"INSERT INTO temp._ln_vis SELECT rowid, event_id FROM main.event_metadata WHERE event_id {neg} IN (SELECT id FROM temp._ln_ids)")
    conn.execute("CREATE INDEX temp._ln_vis_e ON _ln_vis(eid)")
    conn.execute("CREATE TEMP VIEW event_metadata AS SELECT rowid AS rowid, * FROM main.event_metadata WHERE rowid IN (SELECT r FROM temp._ln_vis)")
    if "critical_auto" in have:
        conn.execute("CREATE TEMP VIEW critical_auto AS SELECT rowid AS rowid, * FROM main.critical_auto c "
                     "WHERE c.event_id IN (SELECT eid FROM temp._ln_vis) OR (c.event_id IS NULL AND _ln_main())")
    if "summary_l1" in have:
        _c1 = {r[1] for r in conn.execute("PRAGMA main.table_info(summary_l1)")}
        if {"from_rowid", "to_rowid"} <= _c1:
            conn.execute("CREATE TEMP VIEW summary_l1 AS SELECT rowid AS rowid, * FROM main.summary_l1 s WHERE "
                         + _range_ok("s.from_rowid", "s.to_rowid", "l1", "s.session_id"))
        else:   # base schema of a fresh account (range columns not migrated yet): main line only
            conn.execute("CREATE TEMP VIEW summary_l1 AS SELECT rowid AS rowid, * FROM main.summary_l1 WHERE _ln_main()")
    if "summary_l1_v2" in have:
        conn.execute("CREATE TEMP VIEW summary_l1_v2 AS SELECT rowid AS rowid, * FROM main.summary_l1_v2 WHERE session_id IN (SELECT session_id FROM temp.summary_l1)")
    if "summary_l2_blocks" in have:
        conn.execute("CREATE TEMP VIEW summary_l2_blocks AS SELECT * FROM main.summary_l2_blocks b WHERE "
                     + _range_ok("b.from_rowid", "b.to_rowid", "l2", "(b.source || ':' || b.period_key)"))
    if "summary_l2" in have:
        conn.execute("CREATE TEMP VIEW summary_l2 AS SELECT rowid AS rowid, * FROM main.summary_l2 WHERE _ln_main()")


def _connect(database, *a, **k):
    conn = _orig_connect(database, *a, **k)
    ctx = LINE_CTX.get()
    if ctx is not None:
        try:
            p = str(database)
            ro = "mode=ro" in p
            if p.startswith("file:"):
                p = p[5:].split("?", 1)[0]
            if os.path.realpath(p) == ctx["db"]:
                if ro:
                    _shadow(conn, ctx)
                else:
                    ctx.setdefault("rw_hits", 0)
                    ctx["rw_hits"] += 1
        except Exception as e:
            print(f"[lines] shadow error: {e}", flush=True)
    return conn


sqlite3.connect = _connect


def label_all(ki, d):
    """lines=all: tag each hit that carries an event_id with its source line (chain_id) + own/other."""
    uid, me, main = ki["user_id"], ki["chain_id"], ki["main_chain"]
    c = _m()
    try:
        tagged = dict(c.execute("SELECT event_id, chain_id FROM event_lines WHERE user_id=?", (uid,)).fetchall())
    finally:
        c.close()
    def walk(x):
        if isinstance(x, dict):
            eid = x.get("event_id") or (x.get("id") if isinstance(x.get("id"), str) and "::" in x.get("id") else None)
            if isinstance(eid, str) and "::" in eid:
                ch = tagged.get(eid, main)
                x["source_line"] = {"chain_id": ch, "own": ch == me}
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(d)
    return d
