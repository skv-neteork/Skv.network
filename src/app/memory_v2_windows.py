"""SKV memory v2, step B: first-request pack = memory map + three non-overlapping windows.

raw (newest turns, verbatim) -> L1 (summaries strictly older than raw) -> L2 (blocks strictly older than L1).
Also: schema migration (additive), L1 ranges, L2 block series, user profile, maintenance thread.
Nothing here deletes user data. The legacy summary_l2 row is kept and copied into summary_l2_blocks.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time

from app.memory_v2 import (BASE_DIR, account_name, clip, config, db_path, est_tokens, mask_text, norm_date,
                           strip_critical)

DEFAULT_EXCLUDE_TOPICS = ["skv_eval"]
DEFAULT_EXCLUDE_KINDS = ["doc", "docs", "document", "code", "log", "file"]
L2_BLOCK_L1 = 12          # max L1 summaries per L2 block
L2_BLOCK_TOKENS = 220


def _cfg(key, default):
    return config().get(key, default)


# ---------------- schema / migration ----------------
def ensure_schema(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(summary_l1)")}
    if not cols:
        conn.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(summary_l1)")}
    for col, ddl in (("from_rowid", "INTEGER"), ("to_rowid", "INTEGER"), ("lang", "TEXT")):
        if col not in cols:
            conn.execute(f"ALTER TABLE summary_l1 ADD COLUMN {col} {ddl}")
    conn.execute("""CREATE TABLE IF NOT EXISTS summary_l2_blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, source TEXT, period_key TEXT,
        period_from TEXT, period_to TEXT, from_rowid INTEGER, to_rowid INTEGER,
        topics_json TEXT, text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, period_key))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS user_profile (
        user_id TEXT PRIMARY KEY, who TEXT, projects_json TEXT, topics_json TEXT, prefs_json TEXT, updated_at TEXT)""")


def _has_events(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_metadata'").fetchone())


def snapshot_legacy_l2(conn, user_id=""):
    """Copy every distinct summary_l2 content into summary_l2_blocks (source legacy_summary_l2). Idempotent."""
    try:
        rows = conn.execute("SELECT user_id, map_json, last_updated FROM summary_l2").fetchall()
    except sqlite3.OperationalError:
        return 0
    n = 0
    for uid, mj, upd in rows:
        if not mj:
            continue
        key = hashlib.sha1(mj.encode("utf-8", "replace")).hexdigest()[:16]
        cur = conn.execute("INSERT OR IGNORE INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, text, topics_json) VALUES (?,?,?,?,?,?,?)",
                           (uid or user_id, "legacy_summary_l2", key, upd, upd, mj, "[]"))
        n += cur.rowcount
    return n


def _event_index(conn):
    rows = conn.execute("SELECT rowid, event_id, time_str FROM event_metadata ORDER BY rowid").fetchall()
    return rows


def backfill_l1_ranges(conn):
    """Give L1 rows without a range a from/to rowid. grokexp L1 via l1_span; others by creation time."""
    todo = conn.execute("SELECT rowid, session_id, created_at FROM summary_l1 WHERE to_rowid IS NULL").fetchall()
    if not todo:
        return 0
    events = _event_index(conn)
    grok = {}
    for rid, eid, _ in events:
        m = re.search(r"::grokexp_(\d+)$", eid or "")
        if m:
            grok[int(m.group(1))] = rid
    spans = {}
    try:
        for sid, a, b in conn.execute("SELECT session_id, start_n, end_n FROM l1_span"):
            spans[sid] = (a, b)
    except sqlite3.OperationalError:
        pass
    dated = [(rid, norm_date(ts)) for rid, _, ts in events]
    n = 0
    for l1rid, sid, created in todo:
        fr = to = None
        if sid in spans:
            a, b = spans[sid]
            ra = [grok[i] for i in range(a, b + 1) if i in grok]
            if ra:
                fr, to = min(ra), max(ra)
        if to is None and created:
            c16 = str(created)[:16]
            same = [rid for rid, d in dated if d == c16]
            older = [rid for rid, d in dated if d and d <= c16]
            pick = max(same) if same else (max(older) if older else None)
            if pick:
                fr = to = pick
        if to is not None:
            conn.execute("UPDATE summary_l1 SET from_rowid=?, to_rowid=? WHERE rowid=?", (fr, to, l1rid))
            n += 1
    return n


def _excluded_topic(topic):
    t = (topic or "").lower()
    return any(t.startswith(p.lower()) for p in _cfg("window_exclude_topic_prefixes", DEFAULT_EXCLUDE_TOPICS))


def _l1_rows(conn):
    return conn.execute("SELECT rowid, topic, summary_text, from_rowid, to_rowid, created_at FROM summary_l1 WHERE to_rowid IS NOT NULL ORDER BY to_rowid").fetchall()


def _dates_for(conn, rowids):
    rowids = [r for r in set(rowids) if r]
    if not rowids:
        return {}
    q = "SELECT rowid, time_str FROM event_metadata WHERE rowid IN (%s)" % ",".join("?" * len(rowids))
    return {r: norm_date(t) for r, t in conn.execute(q, rowids)}


_JUNK = re.compile(r"(?i)(json|слишком длинн|too long|ответы на вопросы|вопрос \d|^\W*\d+\.\s*$)")


def _first_sentence(s, n=160):
    s = re.sub(r"[*#`]+", "", re.sub(r"\s+", " ", (s or ""))).strip()
    for part in re.split(r"(?<=[.!?])\s+", s):
        part = part.strip()
        if len(part) >= 40 and not _JUNK.search(part):
            return part[:n]
    return "" if _JUNK.search(s[:n]) else s[:n]


def _make_block(l1s, dates):
    topics = {}
    for _, t, _, _, _, _ in l1s:
        topics[t or "?"] = topics.get(t or "?", 0) + 1
    fr = min(r[3] or r[4] for r in l1s)
    to = max(r[4] for r in l1s)
    d0, d1 = dates.get(fr, ""), dates.get(to, "")
    top = sorted(topics.items(), key=lambda x: -x[1])[:5]
    hl = []
    for r in sorted(l1s, key=lambda r: -len(r[2] or "")):
        fs = _first_sentence(r[2])
        if fs and fs not in hl:
            hl.append(fs)
        if len(hl) >= 5:
            break
    text = f"{len(l1s)} summaries, rowid {fr}-{to}. Topics: " + ", ".join(f"{t} x{c}" for t, c in top) + ". " + " | ".join(hl)
    return {"from_rowid": fr, "to_rowid": to, "period_from": d0, "period_to": d1, "topics": [t for t, _ in top],
            "text": clip(text, L2_BLOCK_TOKENS)}


def _group_blocks(l1s, dates):
    """Split L1 rows (sorted by to_rowid) into blocks: new block on week change or every L2_BLOCK_L1 rows."""
    groups, cur, wk = [], [], None
    for r in l1s:
        d = dates.get(r[4], "")
        w = d[:10]
        try:
            w = time.strftime("%G-W%V", time.strptime(d[:10], "%Y-%m-%d"))
        except Exception:
            pass
        if cur and (w != wk or len(cur) >= L2_BLOCK_L1):
            groups.append(cur)
            cur = []
        cur.append(r)
        wk = w
    if cur:
        groups.append(cur)
    return groups


def rebuild_auto_blocks(conn, user_id=""):
    l1s = [r for r in _l1_rows(conn) if not _excluded_topic(r[1])]
    if not l1s:
        return 0
    dates = _dates_for(conn, [r[3] for r in l1s] + [r[4] for r in l1s])
    n = 0
    for g in _group_blocks(l1s, dates):
        b = _make_block(g, dates)
        key = f"auto:{min(r[3] or r[4] for r in g)}"
        conn.execute("""INSERT INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text)
                        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source, period_key) DO UPDATE SET
                        period_from=excluded.period_from, period_to=excluded.period_to, from_rowid=excluded.from_rowid,
                        to_rowid=excluded.to_rowid, topics_json=excluded.topics_json, text=excluded.text""",
                     (user_id, "auto", key, b["period_from"], b["period_to"], b["from_rowid"], b["to_rowid"], json.dumps(b["topics"], ensure_ascii=False), b["text"]))
        n += 1
    return n


def seed_profile(conn, user_id):
    if conn.execute("SELECT 1 FROM user_profile WHERE user_id=?", (user_id,)).fetchone():
        return False
    who, projects = "", []
    try:
        row = conn.execute("SELECT map_json FROM summary_l2 ORDER BY last_updated DESC LIMIT 1").fetchone()
        j = json.loads(row[0]) if row and row[0] else {}
        if isinstance(j, dict):
            who = str(j.get("who") or j.get("user_profile") or j.get("profile") or "")[:600]
            projects = [{"name": str(p)} for p in (j.get("projects") or [])][:20]
    except Exception:
        pass
    conn.execute("INSERT INTO user_profile (user_id, who, projects_json, topics_json, prefs_json, updated_at) VALUES (?,?,?,?,?,datetime('now'))",
                 (user_id, who, json.dumps(projects, ensure_ascii=False), "[]", "{}"))
    return True


def migrate_db(path, user_id=None):
    conn = sqlite3.connect(path, timeout=30)
    try:
        if not _has_events(conn):
            return {"skipped": "no event_metadata"}
        user_id = user_id or os.path.basename(path)[:-3]
        ensure_schema(conn)
        res = {"legacy_l2_snapshots": snapshot_legacy_l2(conn, user_id), "l1_ranges": backfill_l1_ranges(conn),
               "auto_blocks": rebuild_auto_blocks(conn, user_id), "profile_seeded": seed_profile(conn, user_id)}
        conn.commit()
        return res
    finally:
        conn.close()


def migrate_user(user_id):
    return migrate_db(db_path(user_id), user_id)


def migrate_all():
    out = {}
    for f in sorted(os.listdir(BASE_DIR)):
        if not f.endswith(".db") or f in ("shared_master.db",):
            continue
        try:
            out[f] = migrate_db(os.path.join(BASE_DIR, f))
        except Exception as e:
            out[f] = {"error": str(e)}
    return out


_ready = set()


def ready(user_id):
    p = db_path(user_id)
    if p not in _ready:
        migrate_db(p, user_id)
        _ready.add(p)


# ---------------- writes from remember ----------------
def on_remember(user_id, event_id, l1_saved_session=None, l2_map=None):
    """Called after /remember: give the new L1 a range, append agent L2 block (legacy row stays as before)."""
    ready(user_id)
    conn = sqlite3.connect(db_path(user_id), timeout=30)
    try:
        ensure_schema(conn)
        row = conn.execute("SELECT rowid FROM event_metadata WHERE event_id=?", (event_id,)).fetchone() if event_id else None
        to = row[0] if row else (conn.execute("SELECT MAX(rowid) FROM event_metadata").fetchone()[0] or 0)
        if l1_saved_session:
            last = conn.execute("SELECT MAX(to_rowid) FROM summary_l1 WHERE to_rowid < ?", (to,)).fetchone()[0]
            fr = max((last or 0) + 1, to - 15, 1)
            fr = min(fr, to)
            conn.execute("UPDATE summary_l1 SET from_rowid=?, to_rowid=? WHERE session_id=?", (fr, to, l1_saved_session))
        if l2_map:
            key = hashlib.sha1(l2_map.encode("utf-8", "replace")).hexdigest()[:16]
            last = conn.execute("SELECT MAX(to_rowid) FROM summary_l2_blocks WHERE source='agent'").fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO summary_l2_blocks (user_id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text) VALUES (?,?,?,datetime('now'),datetime('now'),?,?,?,?)",
                         (user_id, "agent", key, (last or 0) + 1, to, "[]", l2_map))
            try:
                j = json.loads(l2_map)
                if isinstance(j, dict) and (j.get("who") or j.get("user_profile") or j.get("projects")):
                    merge_profile(user_id, who=j.get("who") or j.get("user_profile"), projects=j.get("projects"), conn=conn)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


def before_legacy_l2_overwrite(user_id):
    """Snapshot the current summary_l2 row before remember overwrites it."""
    ready(user_id)
    conn = sqlite3.connect(db_path(user_id), timeout=30)
    try:
        ensure_schema(conn)
        snapshot_legacy_l2(conn, user_id)
        conn.commit()
    finally:
        conn.close()


# ---------------- profile ----------------
def get_profile(user_id, conn=None):
    own = conn is None
    if own:
        ready(user_id)
        conn = sqlite3.connect(db_path(user_id), timeout=30)
    try:
        row = conn.execute("SELECT who, projects_json, prefs_json, updated_at FROM user_profile WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"who": "", "projects": [], "prefs": {}, "updated_at": None}
        return {"who": row[0] or "", "projects": json.loads(row[1] or "[]"), "prefs": json.loads(row[2] or "{}"), "updated_at": row[3]}
    finally:
        if own:
            conn.close()


def merge_profile(user_id, who=None, projects=None, prefs=None, conn=None):
    own = conn is None
    if own:
        ready(user_id)
        conn = sqlite3.connect(db_path(user_id), timeout=30)
    try:
        ensure_schema(conn)
        cur = get_profile(user_id, conn)
        if who:
            cur["who"] = str(who)[:1200]
        if projects:
            names = {p["name"].lower(): p for p in cur["projects"] if isinstance(p, dict) and p.get("name")}
            for p in projects:
                p = {"name": p} if isinstance(p, str) else dict(p)
                if p.get("name"):
                    names[p["name"].lower()] = {**names.get(p["name"].lower(), {}), **{k: str(v)[:200] for k, v in p.items()}}
            cur["projects"] = list(names.values())[:30]
        if prefs and isinstance(prefs, dict):
            cur["prefs"].update({k: str(v)[:300] for k, v in prefs.items()})
        conn.execute("INSERT OR REPLACE INTO user_profile (user_id, who, projects_json, topics_json, prefs_json, updated_at) VALUES (?,?,?,?,?,datetime('now'))",
                     (user_id, cur["who"], json.dumps(cur["projects"], ensure_ascii=False), "[]", json.dumps(cur["prefs"], ensure_ascii=False)))
        if own:
            conn.commit()
        return get_profile(user_id, conn)
    finally:
        if own:
            conn.close()


def list_l2_blocks(user_id, limit=50):
    ready(user_id)
    conn = sqlite3.connect(db_path(user_id), timeout=30)
    try:
        rows = conn.execute("SELECT id, source, period_key, period_from, period_to, from_rowid, to_rowid, topics_json, text, created_at FROM summary_l2_blocks ORDER BY COALESCE(to_rowid, 0) DESC, id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "source": r[1], "period_key": r[2], "period_from": r[3], "period_to": r[4], "from_rowid": r[5], "to_rowid": r[6],
             "topics": json.loads(r[7] or "[]"), "text": mask_text(r[8] or ""), "created_at": r[9]} for r in rows]


# ---------------- map ----------------
def build_map(conn, user_id, budget):
    prof = get_profile(user_id, conn)
    projects = []
    for p in prof["projects"]:
        if isinstance(p, dict) and p.get("name"):
            projects.append({"name": p["name"], "note": p.get("note", "")})
    try:
        for name, cnt in conn.execute("SELECT project, COUNT(*) FROM event_metadata WHERE project IS NOT NULL AND project != '' GROUP BY project ORDER BY 2 DESC LIMIT 10"):
            if not any(x["name"].lower() == name.lower() for x in projects):
                projects.append({"name": name, "note": f"{cnt} records"})
    except sqlite3.OperationalError:
        pass
    topics = []
    for t, cnt, last in conn.execute("SELECT topic, COUNT(*), MAX(created_at) FROM summary_l1 WHERE topic IS NOT NULL GROUP BY topic ORDER BY MAX(created_at) DESC"):
        if _excluded_topic(t) or not t:
            continue
        topics.append({"topic": t, "count": cnt, "last": str(last)[:10]})
    m = {"who": prof["who"] or "(no profile yet: set it with POST /api/v7/memory/profile)", "projects": projects, "topics": topics[:12]}
    while est_tokens(json.dumps(m, ensure_ascii=False)) > budget and (m["topics"] or m["projects"]):
        if len(m["topics"]) > 3:
            m["topics"].pop()
        elif len(m["projects"]) > 3:
            m["projects"].pop()
        elif m["topics"]:
            m["topics"].pop()
        else:
            m["projects"].pop()
    if est_tokens(json.dumps(m, ensure_ascii=False)) > budget:
        m["who"] = clip(m["who"], max(20, budget // 2))
    return m


# ---------------- windows ----------------
def _window_kind_ok(kind):
    return (kind or "dialogue") not in _cfg("window_exclude_kinds", DEFAULT_EXCLUDE_KINDS)


def raw_window(conn, budget, min_msgs=10, max_msgs=30, msg_cap=600):
    rows = conn.execute("SELECT rowid, event_id, time_str, raw_dialogue, kind, essence FROM event_metadata WHERE raw_dialogue IS NOT NULL AND raw_dialogue != '' ORDER BY rowid DESC LIMIT ?", (max_msgs * 6,)).fetchall()
    cands = []
    for rid, eid, ts, raw, kind, ess in rows:
        if not _window_kind_ok(kind) or raw.startswith("[archived]") or _excluded_topic(ess):
            continue
        text = strip_critical(raw)
        if not text:
            continue
        cands.append({"rowid": rid, "event_id": eid, "date": norm_date(ts), "text": text})
        if len(cands) >= max_msgs:
            break
    costs = [min(est_tokens(c["text"]), msg_cap) for c in cands]
    n, tot = 0, 0
    while n < len(cands) and tot + costs[n] + 28 <= budget:
        tot += costs[n] + 28
        n += 1
    k = min(min_msgs, len(cands))
    if n < k:
        lo, hi = 20, msg_cap
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if sum(min(costs[i], mid) + 28 for i in range(k)) <= budget:
                lo = mid
            else:
                hi = mid - 1
        caps = [min(costs[i], lo) for i in range(k)]
    else:
        caps = costs[:n]
    out, used = [], 0
    for c, cap in zip(cands, caps):
        c["text"] = clip(c["text"], cap, headtail=True)
        used += est_tokens(c["text"]) + 28
        out.append(c)
    return out, used


def l1_window(conn, b1, budget, entry_cap=150):
    rows = [r for r in conn.execute("SELECT rowid, topic, summary_text, from_rowid, to_rowid FROM summary_l1 WHERE to_rowid IS NOT NULL AND to_rowid < ? ORDER BY to_rowid DESC, rowid DESC", (b1,))]
    out, used, cursor = [], 0, b1
    gaps = 0
    for rid, topic, text, fr, to in rows:
        fr = fr or to
        if to >= cursor or _excluded_topic(topic):
            continue
        if to < cursor - 1:
            g = _gap_entry(conn, to + 1, cursor - 1)
            if g:
                if used + g["_cost"] > budget:
                    break
                used += g.pop("_cost")
                out.append(g)
                gaps += 1
        t = clip(text or "", entry_cap)
        cost = est_tokens(t) + est_tokens(topic or "") + 40
        if used + cost > budget:
            break
        out.append({"kind": "l1", "topic": topic, "text": t, "from_rowid": fr, "to_rowid": to})
        used += cost
        cursor = fr
    dates = _dates_for(conn, [e["from_rowid"] for e in out] + [e["to_rowid"] for e in out])
    for e in out:
        e["date_from"], e["date_to"] = dates.get(e["from_rowid"], ""), dates.get(e["to_rowid"], "")
    return out, used, cursor


def _gap_entry(conn, fr, to):
    rows = conn.execute("SELECT rowid, essence, kind FROM event_metadata WHERE rowid BETWEEN ? AND ? ORDER BY rowid DESC", (fr, to)).fetchall()
    rows = [r for r in rows if _window_kind_ok(r[2]) and not _excluded_topic(r[1])]
    if not rows:
        return None
    heads = []
    for _, ess, _ in rows[:3]:
        e = re.sub(r"\s+", " ", strip_critical(ess or ""))[:70]
        if e and e not in heads:
            heads.append(e)
    text = "; ".join(heads)
    return {"kind": "gap", "count": len(rows), "text": text, "from_rowid": fr, "to_rowid": to, "_cost": est_tokens(text) + 45}


def l2_window(conn, user_id, b2, budget):
    out, used, cursor = [], 0, b2
    stored = conn.execute("SELECT source, period_from, period_to, from_rowid, to_rowid, text FROM summary_l2_blocks WHERE to_rowid IS NOT NULL AND to_rowid < ? AND source != 'legacy_summary_l2' ORDER BY to_rowid DESC, CASE source WHEN 'agent' THEN 0 WHEN 'llm' THEN 1 ELSE 2 END", (b2,)).fetchall()
    for src, pf, pt, fr, to, text in stored:
        fr = fr or to
        if to >= cursor:
            continue
        t = clip(text or "", L2_BLOCK_TOKENS)
        cost = est_tokens(t) + 32
        if used + cost > budget:
            break
        out.append({"source": src, "period": f"{(pf or '')[:10]}..{(pt or '')[:10]}", "from_rowid": fr, "to_rowid": to, "text": t})
        used += cost
        cursor = fr
    return out, used, cursor


def critical_lines(conn, budget):
    rows = conn.execute("SELECT time_str, raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE '%>>>%' ORDER BY rowid DESC LIMIT 60").fetchall()
    out, seen, used = [], set(), 0
    for ts, raw in rows:
        for ln in (raw or "").split("\n"):
            if ">>>" not in ln:
                continue
            s = re.sub(r"(>>>\s*)+", ">>> ", ln.strip())
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            line = f"[{norm_date(ts)}] {mask_text(clip(s, 80))}"
            cost = est_tokens(line) + 4
            if used + cost > budget:
                return out, used
            out.append(line)
            used += cost
    return out, used


def first_pack(user_id, budgets):
    ready(user_id)
    cfg = config()
    conn = sqlite3.connect(f"file:{db_path(user_id)}?mode=ro", uri=True, timeout=10)
    try:
        mm = build_map(conn, user_id, budgets["map"]) if budgets["map"] > 0 else None
        raw, raw_used = raw_window(conn, budgets["raw"], int(cfg.get("raw_min_msgs", 10)), int(cfg.get("raw_max_msgs", 30)), int(cfg.get("raw_msg_cap", 600))) if budgets["raw"] > 0 else ([], 0)
        b1 = min([r["rowid"] for r in raw] or [(conn.execute("SELECT MAX(rowid) FROM event_metadata").fetchone()[0] or 0) + 1])
        l1, l1_used, b2 = l1_window(conn, b1, budgets["l1"]) if budgets["l1"] > 0 else ([], 0, b1)
        l2, l2_used, b3 = l2_window(conn, user_id, b2, budgets["l2"]) if budgets["l2"] > 0 else ([], 0, b2)
        crit, crit_used = critical_lines(conn, budgets["critical"]) if budgets["critical"] > 0 else ([], 0)
    finally:
        conn.close()
    pack = {"windows": {"raw": raw, "l1": l1, "l2": l2,
                        "bounds": {"raw_from_rowid": b1, "l1_from_rowid": b2, "l2_from_rowid": b3},
                        "tokens": {"raw": raw_used, "l1": l1_used, "l2": l2_used}},
            "critical": crit, "_window_ids": [r["event_id"] for r in raw]}
    if mm is not None:
        pack["memory_map"] = mm
    return pack


# ---------------- maintenance ----------------
def purge_expired_vault_reveals():
    try:
        from app import vault
        n = vault.purge_expired_reveals()
        if n:
            print(f"[memory_v2] wiped {n} expired/opened transient reveal payload(s)", flush=True)
        return n
    except Exception as e:
        print(f"[memory_v2] reveal purge error: {e}", flush=True)
        return 0


def revoke_expired_keys():
    """Grace-period keys: user_api_keys.expires_at passed -> is_active=0 (kept for audit)."""
    try:
        c = sqlite3.connect(os.path.join(BASE_DIR, "shared_master.db"), timeout=30)
        try:
            if "expires_at" not in {r[1] for r in c.execute("PRAGMA table_info(user_api_keys)")}:
                return 0
            n = c.execute("UPDATE user_api_keys SET is_active=0 WHERE is_active=1 AND expires_at IS NOT NULL AND expires_at <= datetime('now')").rowcount
            c.commit()
            if n:
                print(f"[memory_v2] revoked {n} expired api key(s)", flush=True)
            return n
        finally:
            c.close()
    except Exception as e:
        print(f"[memory_v2] key revoke error: {e}", flush=True)
        return 0


def _maintain_loop():
    revoke_expired_keys()
    purge_expired_vault_reveals()
    time.sleep(60)
    while True:
        revoke_expired_keys()
        purge_expired_vault_reveals()
        try:
            if config().get("enabled", True) and config().get("maintenance", True):
                res = migrate_all()
                n = sum(1 for v in res.values() if "error" not in v and "skipped" not in v)
                print(f"[memory_v2] maintenance ok: {n} accounts", flush=True)
        except Exception as e:
            print(f"[memory_v2] maintenance error: {e}", flush=True)
        time.sleep(int(config().get("maintenance_interval_s", 900)))


def start_maintenance():
    if os.environ.get("SKV_MEMV2_MAINT", "1") == "0":
        return
    threading.Thread(target=_maintain_loop, name="skv-memv2-maint", daemon=True).start()
