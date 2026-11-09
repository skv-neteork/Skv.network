"""Targeted cube suggestions inside search + agent-proposed fixes via the court (owner t437-t438, 2026-10-24).
suggest(): 2-3 proven cubes + 1 new 'rate_this' on strong topic match; empty on weak match; no repeat per session;
skips cubes already installed in the chain; never quarantine/archived. Light: candidate list cached in-process.
Fixes: propose_fix() -> cube_fixes(pending) + court_queue('fix:<id>'); judges approve -> apply_fix() snapshots
old version into cube_versions (rollback possible)."""
import re, json, time, sqlite3, threading

DB = "/data/skv/metadata_store/shared_master.db"
HIDE = ("quarantine", "archived", "removed", "deprecated", "disputed")
STOP = set("the and for with that this from what when how your you are was were can will into about have has not but all any use using get make why who which our out its over also just like then than them they more most some such only".split())
THRESH = 0.6          # share of query tokens found in the cube (+ head bonus)
MIN_HITS = 2          # at least 2 shared tokens (1 if the query has a single long token)
_TTL = 120
_cache = {"ts": 0, "rows": []}
_lock = threading.Lock()


def toks(t):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()) if w not in STOP}


def _load():
    with _lock:
        if time.time() - _cache["ts"] < _TTL and _cache["rows"]:
            return _cache["rows"]
        c = sqlite3.connect(DB, timeout=10)
        try:
            q = ",".join("?" * len(HIDE))
            rows = c.execute(f"""SELECT cube_id, COALESCE(subject_action_object,''), COALESCE(essence,''), COALESCE(rules_markdown,''),
                COALESCE(kind,'moment'), COALESCE(carrier,'answer'), COALESCE(status,'community'), COALESCE(rating,0),
                COALESCE(upvotes,0)+COALESCE(downvotes,0), COALESCE(skill_md,''), COALESCE(created_at,'')
                FROM cubes_new WHERE COALESCE(status,'community') NOT IN ({q}) AND COALESCE(is_constitutional,0)=0
                AND COALESCE(kind,'') NOT IN ('help_request')""", HIDE).fetchall()
        finally:
            c.close()
        out = []
        for r in rows:
            out.append({"id": r[0], "topic": r[1], "essence": r[2], "kind": r[4], "carrier": r[5], "status": r[6],
                        "rating": r[7], "votes": r[8], "has_skill": bool(r[9].strip()) or r[5] == "skill",
                        "created": str(r[10]), "tok": toks(r[1] + " " + r[2]) | toks(r[3][:300]), "tok_head": toks(r[1] + " " + r[2])})
        _cache.update(ts=time.time(), rows=out)
        return out


def _score(qt, row):
    hits = qt & row["tok"]
    if not hits:
        return 0.0, 0
    s = len(hits) / max(1, len(qt))
    s += 0.15 * len(qt & row["tok_head"]) / max(1, len(qt))   # topic/essence match weighs more
    return s, len(hits)


def _seen_conn():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS cube_suggest_seen (user_id TEXT, session_id TEXT, cube_id TEXT, ts TEXT, PRIMARY KEY (user_id, session_id, cube_id))")
    return c


def _installed(uid):
    try:
        from app import chain_skills as cs
        ids = set()
        for ch in (None, "session"):
            ids |= {x["cube_id"] for x in cs.list_ids(uid, ch)}
        return ids
    except Exception:
        return set()


def _item(r, rate_this=False):
    skill = r["has_skill"]
    return {"id": r["id"], "topic": r["topic"][:120], "kind": r["kind"], "carrier": r["carrier"],
            "essence": r["essence"][:220], "rating": r["rating"], "status": r["status"], "has_skill": skill,
            "rate_this": rate_this,
            "action": ("skill cube: offer the user to install (cube_install) — install only after yes" if skill
                       else "use in the answer if it fits") + ("; then rate it with cube_vote (+1/-1, or a fix)" if rate_this else "; rate after use")}


def suggest(query, uid="", session_id="", top=3):
    empty = {"items": [], "note": "no strong topic match"}
    try:
        from app.cube_query import english_query
        query = english_query(query) or (query or "")
        qt = toks(query)
        if not qt:
            return empty
        need = 1 if (len(qt) == 1 and len(next(iter(qt))) >= 5) else MIN_HITS
        scored = []
        for r in _load():
            s, h = _score(qt, r)
            if h >= need and s >= THRESH and (qt & r["tok_head"]):
                scored.append((s, r))
        if not scored:
            return empty
        uid = (uid or "").strip().lower()
        sess = (session_id or "default")[:80]
        skip = _installed(uid) if uid else set()
        c = _seen_conn()
        try:
            if uid:
                skip |= {x[0] for x in c.execute("SELECT cube_id FROM cube_suggest_seen WHERE user_id=? AND session_id=?", (uid, sess))}
            scored = [(s, r) for s, r in scored if r["id"] not in skip]
            rank = {"golden": 3, "verified": 2, "community": 1}
            proven = sorted([x for x in scored if x[1]["status"] in ("golden", "verified") or x[1]["rating"] >= 1],
                            key=lambda x: (-rank.get(x[1]["status"], 0), -x[1]["rating"], -x[0]))[:top]
            fresh = sorted([x for x in scored if x[1]["votes"] == 0 and x[1]["status"] == "community"
                            and x[1]["id"] not in {p[1]["id"] for p in proven}], key=lambda x: (-x[0], x[1]["created"]))[:1]
            items = [_item(r) for _, r in proven] + [_item(r, True) for _, r in fresh]
            if uid and items:
                for it in items:
                    c.execute("INSERT OR IGNORE INTO cube_suggest_seen VALUES (?,?,?,datetime('now'))", (uid, sess, it["id"]))
                    c.execute("INSERT OR IGNORE INTO cube_impressions (cube_id, user_id, slot, step, ts) VALUES (?,?,?,0,datetime('now'))", (it["id"], uid, "suggest"))
                c.commit()
        finally:
            c.close()
        if not items:
            return {"items": [], "note": "already suggested in this session or installed"}
        return {"items": items, "hint": "Proven cubes: use if they fit. rate_this: new cube, rate it after use (cube_vote; may propose a fix)."}
    except Exception as e:
        return {"items": [], "note": "suggest skipped: " + str(e)[:80]}


# ---------------- proposed fixes ----------------
def ensure_fix(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cube_fixes (id INTEGER PRIMARY KEY, cube_id TEXT, user_id TEXT, essence TEXT, rules TEXT,
        skill_md TEXT, hooks TEXT, reason TEXT, status TEXT DEFAULT 'pending', verdict TEXT, ts TEXT, decided_at TEXT);
    CREATE TABLE IF NOT EXISTS cube_versions (cube_id TEXT, version INTEGER, topic TEXT, essence TEXT, rules TEXT, skill_md TEXT,
        hooks TEXT, replaced_by_fix INTEGER, ts TEXT, PRIMARY KEY (cube_id, version));
    CREATE TABLE IF NOT EXISTS court_queue (cube_id TEXT PRIMARY KEY, reason TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS court_complaints (id INTEGER PRIMARY KEY, cube_id TEXT, reason TEXT, created_at TEXT);
    CREATE TRIGGER IF NOT EXISTS court_q_ins AFTER INSERT ON court_queue BEGIN
        INSERT INTO court_complaints (cube_id, reason, created_at) VALUES (NEW.cube_id, NEW.reason, datetime('now')); END;
    CREATE TRIGGER IF NOT EXISTS court_q_upd AFTER UPDATE OF reason ON court_queue WHEN NEW.reason IS NOT OLD.reason BEGIN
        INSERT INTO court_complaints (cube_id, reason, created_at) VALUES (NEW.cube_id, NEW.reason, datetime('now')); END;
    CREATE TABLE IF NOT EXISTS court_votes (fix_id INTEGER, judge TEXT, verdict TEXT, reason TEXT, ts TEXT, PRIMARY KEY (fix_id, judge));
    CREATE TABLE IF NOT EXISTS court_judges (user_id TEXT PRIMARY KEY, added_by TEXT, ts TEXT);
    """)


def complaints(conn, cube_id):
    """Every complaint/case reason ever queued for this cube (court_queue keeps only the routing row)."""
    ensure_fix(conn)
    return [{"reason": r, "at": t} for r, t in conn.execute("SELECT reason, created_at FROM court_complaints WHERE cube_id=? ORDER BY id", (cube_id,)).fetchall()]


VOTER_MIN_AGE_DAYS = 3


def verified_voter(conn, uid):
    """A +1 that can promote someone else's version: confirmed account, >= 3 days old, with own activity
    (cubes created + ratings >= 2). Test/guest accounts never qualify."""
    u = (uid or "").strip().lower()
    if not u or u.endswith(".invalid") or u.startswith("guest_"):
        return False
    r = conn.execute("SELECT confirmed FROM users WHERE lower(email)=? AND created_at <= datetime('now', ?)", (u, "-%d days" % VOTER_MIN_AGE_DAYS)).fetchone()
    if not r or not r[0]:
        return False
    act = conn.execute("SELECT (SELECT COUNT(*) FROM cubes_new WHERE lower(created_by)=?) + (SELECT COUNT(*) FROM cube_outcomes WHERE lower(user_id)=?)", (u, u)).fetchone()[0]
    return act >= 2


def is_judge(conn, uid, owner=False):
    ensure_fix(conn)
    return owner or conn.execute("SELECT 1 FROM court_judges WHERE lower(user_id)=?", ((uid or "").lower(),)).fetchone() is not None


def human_vote(conn, fix_id, judge, verdict, reason):
    """One authenticated judge account = one vote. The case author cannot judge. Approve needs 2 distinct judge
    accounts and no reject; one reject (with a reason) rejects."""
    ensure_fix(conn)
    j = (judge or "").strip().lower()
    verdict = (verdict or "").strip().lower()
    if verdict not in ("approve", "reject"):
        return {"ok": False, "error": "verdict must be approve or reject"}
    if len((reason or "").strip()) < 5:
        return {"ok": False, "error": "a verdict needs a reason (shown with the decision)"}
    fx = conn.execute("SELECT cube_id, lower(coalesce(user_id,'')), status, reason FROM cube_fixes WHERE id=?", (int(fix_id),)).fetchone()
    if not fx:
        return {"ok": False, "error": "no such case"}
    if fx[2] != "pending":
        return {"ok": False, "error": "case already decided: " + fx[2]}
    _new = re.match(r"version:(cube_[0-9a-f]+)", fx[3] or "")
    authors = {fx[1]}
    if _new:
        authors.add((conn.execute("SELECT lower(coalesce(created_by,'')) FROM cubes_new WHERE cube_id=?", (_new.group(1),)).fetchone() or [""])[0])
    if j in authors:
        return {"ok": False, "error": "the case author cannot judge this case", "status": 403}
    conn.execute("INSERT OR REPLACE INTO court_votes (fix_id, judge, verdict, reason, ts) VALUES (?,?,?,?,datetime('now'))", (int(fix_id), j, verdict, reason.strip()[:500]))
    vs = conn.execute("SELECT judge, verdict, reason FROM court_votes WHERE fix_id=? ORDER BY ts", (int(fix_id),)).fetchall()
    txt = "; ".join("%s:%s:%s" % (a, b, c[:120]) for a, b, c in vs)
    if any(v == "reject" for _, v, _ in vs):
        apply_fix(conn, int(fix_id), False, "human court: " + txt); decided = "rejected"
    elif len({a for a, v, _ in vs if v == "approve"}) >= 2:
        apply_fix(conn, int(fix_id), True, "human court: " + txt); decided = "approved"
    else:
        return {"ok": True, "decided": None, "votes": len(vs), "note": "recorded; a second distinct judge account must approve"}
    conn.execute("DELETE FROM court_queue WHERE cube_id=?", (fx[0],))
    return {"ok": True, "decided": decided, "votes": len(vs)}


COURT_MAX_PENDING = 10   # open court cases per account (fixes, foreign versions, removals): each costs us 1-2 paid judge calls
COURT_MAX_DAY = 30


def court_rate(conn, uid):
    """None if the account may file another court case, else an error text."""
    ensure_fix(conn)
    u = (uid or "").strip().lower()
    p = conn.execute("SELECT COUNT(*) FROM cube_fixes WHERE lower(user_id)=? AND status='pending'", (u,)).fetchone()[0]
    if p >= COURT_MAX_PENDING:
        return "too many open court cases (%d); wait for verdicts" % p
    d = conn.execute("SELECT COUNT(*) FROM cube_fixes WHERE lower(user_id)=? AND ts >= datetime('now','-1 day')", (u,)).fetchone()[0]
    if d >= COURT_MAX_DAY:
        return "court filing limit reached (%d in 24h); try tomorrow" % d
    return None


def propose_fix(conn, cube_id, uid, reason, essence="", rules="", skill_md="", hooks=""):
    from app import cube_guard as cg
    ensure_fix(conn)
    row = conn.execute("SELECT subject_action_object, essence, rules_markdown, skill_md, hooks, COALESCE(is_constitutional,0), status FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "cube not found"}
    if row[5]:
        return {"ok": False, "error": "constitution cubes are fixed by the owner only"}
    if row[6] in ("archived", "quarantine", "removed"):
        return {"ok": False, "error": "cube is " + row[6]}
    if not (reason or "").strip():
        return {"ok": False, "error": "a fix needs a short reason"}
    _rl = court_rate(conn, uid)
    if _rl:
        return {"ok": False, "error": _rl, "status": 429}
    if not any((essence, rules, skill_md, hooks)):
        return {"ok": False, "error": "a fix needs fix_essence, fix_rules, fix_skill_md or fix_hooks"}
    ok, f, why, _ = cg.prepare_shared(row[0], essence or row[1], rules or row[2], "fix proposal", True, skill_md or "", hooks or "")
    if not ok:
        return {"ok": False, "error": "guard: " + ",".join(why)}
    cur = conn.execute("INSERT INTO cube_fixes (cube_id, user_id, essence, rules, skill_md, hooks, reason, ts) VALUES (?,?,?,?,?,?,?,datetime('now'))",
                       (cube_id, uid, f["essence"] if essence else "", f["rules"] if rules else "", f["skill_md"] if skill_md else "", hooks or "", reason.strip()[:500]))
    fid = cur.lastrowid
    conn.execute("INSERT INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now')) ON CONFLICT(cube_id) DO UPDATE SET reason=excluded.reason",
                 (cube_id, "fix:%d %s" % (fid, reason.strip()[:300])))
    return {"ok": True, "fix_id": fid, "status": "pending", "note": "sent to the judges; applied only if they approve (old version kept)"}


def pending_fix(conn, cube_id):
    ensure_fix(conn)
    r = conn.execute("SELECT id, essence, rules, skill_md, hooks, reason FROM cube_fixes WHERE cube_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (cube_id,)).fetchone()
    return dict(zip(("id", "essence", "rules", "skill_md", "hooks", "reason"), r)) if r else None


VERSION_VOTES = 2   # distinct non-author clients voting +1 on the pending version -> promoted (Deniz 25.10)


def promote_version(conn, old, new, verdict="votes"):
    """Pending new version of someone else's cube -> live; old -> superseded_by new."""
    import json as _j
    r = conn.execute("SELECT links_json, coalesce(status,'') FROM cubes_new WHERE cube_id=?", (old,)).fetchone()
    if not r or r[1] == "superseded":
        return False
    try: lj = _j.loads(r[0] or "{}")
    except Exception: lj = {}
    if isinstance(lj, list): lj = {"links": lj}
    lj["superseded_by"] = new
    lj["proposed_versions"] = [x for x in lj.get("proposed_versions", []) if x != new]
    conn.execute("UPDATE cubes_new SET status='superseded', links_json=?, updated_at=CURRENT_TIMESTAMP WHERE cube_id=?", (_j.dumps(lj), old))
    conn.execute("UPDATE cubes_new SET status='community', updated_at=CURRENT_TIMESTAMP WHERE cube_id=? AND status='pending_version'", (new,))
    ensure_fix(conn)
    conn.execute("UPDATE cube_fixes SET status='approved', verdict=?, decided_at=datetime('now') WHERE cube_id=? AND status='pending' AND reason LIKE ?", (verdict[:300], old, "version:%s%%" % new))
    conn.execute("DELETE FROM court_queue WHERE cube_id=? AND reason LIKE ?", (old, "version:%s%%" % new))
    _cache["ts"] = 0
    return True


REMOVAL_GROUNDS = ("personal_data", "secret", "harmful", "illegal", "legal_claim")


def request_removal(conn, cube_id, uid, ground, reason):
    """A published cube is public property: no author retract. Removal only via court for a valid ground."""
    ensure_fix(conn)
    ground = (ground or "").strip().lower()
    if ground not in REMOVAL_GROUNDS:
        return {"ok": False, "error": "removal needs a valid ground: " + ", ".join(REMOVAL_GROUNDS)}
    if len((reason or "").strip()) < 10:
        return {"ok": False, "error": "removal needs a concrete reason (what exactly is leaked/harmful/claimed)"}
    row = conn.execute("SELECT COALESCE(is_constitutional,0), status FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "cube not found"}
    if row[0]:
        return {"ok": False, "error": "constitution cubes are changed by the owner only"}
    if row[1] in ("archived", "removed"):
        return {"ok": False, "error": "cube is already " + row[1]}
    _rl = court_rate(conn, uid)
    if _rl and not conn.execute("SELECT 1 FROM cube_fixes WHERE cube_id=? AND status='pending' AND reason LIKE 'removal:%'", (cube_id,)).fetchone():
        return {"ok": False, "error": _rl, "status": 429}
    tag = "removal:%s %s" % (ground, reason.strip()[:400])
    ex = conn.execute("SELECT id FROM cube_fixes WHERE cube_id=? AND status='pending' AND reason LIKE 'removal:%'", (cube_id,)).fetchone()
    if ex:
        return {"ok": True, "fix_id": ex[0], "status": "pending", "note": "a removal request for this cube is already with the court"}
    cur = conn.execute("INSERT INTO cube_fixes (cube_id, user_id, essence, rules, skill_md, hooks, reason, ts) VALUES (?,?,?,?,?,?,?,datetime('now'))",
                       (cube_id, uid, "", "", "", "", tag))
    fid = cur.lastrowid
    conn.execute("INSERT INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now')) ON CONFLICT(cube_id) DO UPDATE SET reason=excluded.reason",
                 (cube_id, "fix:%d %s" % (fid, tag[:300])))
    return {"ok": True, "fix_id": fid, "status": "pending", "kind": "removal_request",
            "note": "sent to the court; the cube stays public unless judges approve removal for this ground"}


def apply_fix(conn, fix_id, approved, verdict=""):
    """approved=True: snapshot old -> cube_versions, write new text. Returns new version number or 0."""
    ensure_fix(conn)
    fx = conn.execute("SELECT cube_id, essence, rules, skill_md, hooks FROM cube_fixes WHERE id=? AND status='pending'", (fix_id,)).fetchone()
    if not fx:
        return 0
    cid = fx[0]
    _rs = (conn.execute("SELECT reason FROM cube_fixes WHERE id=?", (fix_id,)).fetchone() or [""])[0] or ""
    if _rs.startswith("removal:"):
        st = "approved" if approved else "rejected"
        conn.execute("UPDATE cube_fixes SET status=?, verdict=?, decided_at=datetime('now') WHERE id=?", (st, verdict[:300], fix_id))
        if approved:
            from app import cubes_v2 as _cv
            _cv.archive_cube(conn, cid, _rs.split()[0])
            _cache["ts"] = 0
            return 1
        return 0
    if _rs.startswith("version:"):   # a proposed new version (cube_create supersedes= on someone else's cube)
        new = _rs.split()[0][8:]
        if approved:
            promote_version(conn, cid, new, "court: " + verdict)
            return 1
        conn.execute("UPDATE cube_fixes SET status='rejected', verdict=?, decided_at=datetime('now') WHERE id=?", (verdict[:300], fix_id))
        conn.execute("UPDATE cubes_new SET status='rejected' WHERE cube_id=? AND status='pending_version'", (new,))
        return 0
    if not approved:
        conn.execute("UPDATE cube_fixes SET status='rejected', verdict=?, decided_at=datetime('now') WHERE id=?", (verdict[:300], fix_id))
        return 0
    old = conn.execute("SELECT subject_action_object, essence, rules_markdown, skill_md, hooks FROM cubes_new WHERE cube_id=?", (cid,)).fetchone()
    v = (conn.execute("SELECT COALESCE(MAX(version),0) FROM cube_versions WHERE cube_id=?", (cid,)).fetchone()[0] or 0) + 1
    conn.execute("INSERT INTO cube_versions VALUES (?,?,?,?,?,?,?,?,datetime('now'))", (cid, v, old[0], old[1], old[2], old[3], old[4], fix_id))
    conn.execute("""UPDATE cubes_new SET essence=COALESCE(NULLIF(?,''),essence), rules_markdown=COALESCE(NULLIF(?,''),rules_markdown),
        skill_md=COALESCE(NULLIF(?,''),skill_md), hooks=COALESCE(NULLIF(?,''),hooks), updated_at=CURRENT_TIMESTAMP
        WHERE cube_id=? AND COALESCE(is_constitutional,0)=0""", (fx[1], fx[2], fx[3], fx[4], cid))
    conn.execute("UPDATE cube_fixes SET status='approved', verdict=?, decided_at=datetime('now') WHERE id=?", (verdict[:300], fix_id))
    _cache["ts"] = 0
    return v + 1   # current = previous versions + 1


def rollback(conn, cube_id, version):
    ensure_fix(conn)
    r = conn.execute("SELECT essence, rules, skill_md, hooks FROM cube_versions WHERE cube_id=? AND version=?", (cube_id, int(version))).fetchone()
    if not r:
        return False
    cur = conn.execute("SELECT subject_action_object, essence, rules_markdown, skill_md, hooks FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    nv = (conn.execute("SELECT COALESCE(MAX(version),0) FROM cube_versions WHERE cube_id=?", (cube_id,)).fetchone()[0] or 0) + 1
    conn.execute("INSERT INTO cube_versions VALUES (?,?,?,?,?,?,?,?,datetime('now'))", (cube_id, nv, cur[0], cur[1], cur[2], cur[3], cur[4], None))
    conn.execute("UPDATE cubes_new SET essence=?, rules_markdown=?, skill_md=?, hooks=? WHERE cube_id=?", (r[0], r[1], r[2], r[3], cube_id))
    _cache["ts"] = 0
    return True
