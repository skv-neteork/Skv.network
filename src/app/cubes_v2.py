"""Experience cubes v2 (2026-10-19). Rules from skv_cubes_design_v2.md:
- a cube must change the answer (code / lifehack / warning / fact / culture);
- duty per task: when a task ends (task_done=true or topic change) the agent writes a cube or
  duty=cube_nothing with a reason; only silence is an error;
- pack = culture cover + 3 strong + 2 new 'rate this'; new slots must be rated (vote or vote_nothing);
- trusted after 3 'helped' confirmations from distinct non-author clients who were shown the cube;
- a judge can archive (never hard-delete) only with a second judge agreeing;
- links next/from/against (against = dispute, both stay alive until court);
- help requests (on top of cube_tasks) answered by solution cubes; verify by requester; reputation after 3 confirmations;
- projects = linked nodes (part_of), private or open, roles owner/member/helper.
All functions take an open sqlite3 connection to shared_master.db and do not commit unless stated."""
import json, re, time, uuid

EXPERIENCE_KINDS = ("moment", "fact", "culture", "lifehack", "warning", "code")
ALL_KINDS = EXPERIENCE_KINDS + ("help_request", "solution", "project", "project_node")
# One shelf, different carriers: answer-shaping vs installable skill/hooks vs future robotics.
CARRIERS = ("answer", "skill", "robotics")
DEFAULT_CARRIER = "answer"
AGENT_LINKS = ("next", "from", "against")
LEGACY_LINKS = ("progress", "synthesis", "cover", "source", "answer", "hypothesis", "sequence")
SERVER_LINKS = ("part_of", "depends_on", "answers", "solves", "supersedes")
ALL_LINKS = AGENT_LINKS + LEGACY_LINKS + SERVER_LINKS
HIDDEN_STATUS = ("deprecated", "archived", "removed", "quarantine")
HIDDEN_SQL = "status NOT IN ('deprecated','archived','removed','quarantine')"
VISIBLE_KIND_SQL = "COALESCE(kind,'moment') NOT IN ('help_request','project','project_node')"
TRUST_CONFIRMS = 3
NEW_SHOWN_LIMIT = 6          # legacy name, kept for imports
NEW_CAP = 12                 # impressions a cube may get per earned rating: allowed while shown < NEW_CAP * (ratings + 1)
RATED_ENOUGH = 3             # a cube leaves the 'rate this' slots once it has this many ratings (or is trusted)
AGE_OUT_IMPRESSIONS = 12     # 0 ratings after this many impressions -> court (reason: no ratings)
RATE_GRACE_STEPS = 2         # new-slot cubes must be rated within this many steps
TOPIC_MIN_TURNS = 5          # a topic change ends a task only after this many turns since the last cube / cube_nothing
CUBE_GRACE_STEPS = 1         # after a task ends the agent has this many steps to write cube / cube_nothing


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def ensure(conn):
    have = _cols(conn, "cubes_new")
    for col, ddl in (("kind", "TEXT DEFAULT 'moment'"), ("lang", "TEXT DEFAULT 'en'"), ("project_id", "TEXT"),
                     ("source", "TEXT DEFAULT 'agent'"), ("trust", "TEXT DEFAULT 'new'"), ("confirms", "INTEGER DEFAULT 0"),
                     ("shown", "INTEGER DEFAULT 0"), ("parent_id", "TEXT"), ("triviality", "TEXT"), ("aged_at", "TEXT"),
                     ("skill_md", "TEXT"), ("hooks", "TEXT"),
                     ("carrier", "TEXT DEFAULT 'answer'")):
        if col not in have:
            conn.execute(f"ALTER TABLE cubes_new ADD COLUMN {col} {ddl}")
    conn.execute("CREATE TABLE IF NOT EXISTS cube_outcomes (cube_id TEXT, user_id TEXT, outcome TEXT, ts TEXT, PRIMARY KEY (cube_id, user_id))")
    oc = _cols(conn, "cube_outcomes")
    for col in ("reason", "ip"):
        if col not in oc:
            conn.execute(f"ALTER TABLE cube_outcomes ADD COLUMN {col} TEXT")
    conn.execute("CREATE TABLE IF NOT EXISTS cube_duty_state (user_id TEXT PRIMARY KEY, last_topic TEXT, pending_cube INTEGER DEFAULT 0, pending_step INTEGER, pending_reason TEXT, rate_pending TEXT DEFAULT '[]', rate_step INTEGER)")
    if "turns" not in _cols(conn, "cube_duty_state"):
        conn.execute("ALTER TABLE cube_duty_state ADD COLUMN turns INTEGER DEFAULT 0")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind));
    CREATE TABLE IF NOT EXISTS cube_tasks (task_id TEXT PRIMARY KEY, topic TEXT, question TEXT, tried TEXT, accept TEXT, status TEXT, created_by TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS court_queue (cube_id TEXT PRIMARY KEY, reason TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS cube_outcomes (cube_id TEXT, user_id TEXT, outcome TEXT, ts TEXT, PRIMARY KEY (cube_id, user_id));
    CREATE TABLE IF NOT EXISTS cube_impressions (cube_id TEXT, user_id TEXT, slot TEXT, step INTEGER, ts TEXT, PRIMARY KEY (cube_id, user_id));
    CREATE TABLE IF NOT EXISTS court_verdicts (id INTEGER PRIMARY KEY, cube_id TEXT, judge TEXT, verdict TEXT, reason TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS help_requests (cube_id TEXT PRIMARY KEY, topic TEXT, status TEXT, accept TEXT, deadline TEXT, project_id TEXT, node_id TEXT, created_by TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS help_answers (help_id TEXT, solution_id TEXT, author TEXT, state TEXT, reason TEXT, ts TEXT, PRIMARY KEY (help_id, solution_id));
    CREATE TABLE IF NOT EXISTS solution_confirms (solution_id TEXT, user_id TEXT, ts TEXT, PRIMARY KEY (solution_id, user_id));
    CREATE TABLE IF NOT EXISTS agent_inbox (user_id TEXT, cube_id TEXT, reason TEXT, seen INTEGER DEFAULT 0, ts TEXT, PRIMARY KEY (user_id, cube_id));
    CREATE TABLE IF NOT EXISTS agent_reputation (user_id TEXT, topic TEXT, solved INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, helped INTEGER DEFAULT 0, PRIMARY KEY (user_id, topic));
    CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, owner TEXT, title TEXT, goal TEXT, topic TEXT, visibility TEXT, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS project_members (project_id TEXT, user_id TEXT, role TEXT, node_id TEXT, PRIMARY KEY (project_id, user_id));
    CREATE TABLE IF NOT EXISTS project_nodes (node_id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, title TEXT, body TEXT, status TEXT, supersedes TEXT, created_by TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS cube_duty_state (user_id TEXT PRIMARY KEY, last_topic TEXT, pending_cube INTEGER DEFAULT 0, pending_step INTEGER, pending_reason TEXT, rate_pending TEXT DEFAULT '[]', rate_step INTEGER);
    CREATE TABLE IF NOT EXISTS cubes_archive (cube_id TEXT, essence TEXT, subject_action_object TEXT, rules_markdown TEXT, evidence TEXT, raw_dialogue TEXT, links_json TEXT, status TEXT, rating REAL, upvotes INT, downvotes INT, usage_count INT, last_used NUM, energy REAL, is_constitutional NUM, constitutional_order INT, vector, source_session TEXT, created_by TEXT, created_at NUM, updated_at NUM, votes_json TEXT);
    """)


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def new_id(prefix="cube_"):
    return prefix + uuid.uuid4().hex[:12]


def norm_topic(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def norm_kind(k, default="moment"):
    k = (k or "").strip().lower()
    return k if k in ALL_KINDS else default


def normalize_hooks(hooks):
    """Hooks = when-to-fire for a skill cube. Accept list[str]|list[dict]|JSON str|None -> JSON str or ''.
    Thin pass: no scripts. Each hook is either a string (when) or {when, do}."""
    if hooks is None or hooks == "":
        return ""
    if isinstance(hooks, str):
        s = hooks.strip()
        if not s:
            return ""
        try:
            hooks = json.loads(s)
        except Exception:
            # plain multiline: one when per line
            hooks = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not isinstance(hooks, list):
        raise ValueError("hooks must be a list of strings or {when, do} objects")
    out = []
    for h in hooks[:32]:
        if isinstance(h, str):
            t = h.strip()[:500]
            if t:
                out.append({"when": t})
        elif isinstance(h, dict):
            when = str(h.get("when") or h.get("if") or "").strip()[:500]
            do = str(h.get("do") or h.get("then") or "").strip()[:500]
            if when:
                item = {"when": when}
                if do:
                    item["do"] = do
                out.append(item)
        else:
            raise ValueError("each hook must be a string or object")
    return json.dumps(out, ensure_ascii=False) if out else ""


def parse_hooks(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def has_skill(skill_md, hooks_raw=""):
    return bool((skill_md or "").strip() or parse_hooks(hooks_raw))


def norm_carrier(carrier, skill_md="", hooks_raw=""):
    """answer = shapes reply; skill = installable skill+hooks; robotics = future body skills."""
    c = (carrier or "").strip().lower()
    if c in CARRIERS:
        return c
    if has_skill(skill_md, hooks_raw):
        return "skill"
    return DEFAULT_CARRIER


# ---------------- duty ----------------
def _state(conn, uid):
    r = conn.execute("SELECT last_topic, pending_cube, pending_step, pending_reason, rate_pending, rate_step FROM cube_duty_state WHERE user_id=?", (uid,)).fetchone()
    if not r:
        conn.execute("INSERT OR IGNORE INTO cube_duty_state (user_id) VALUES (?)", (uid,))
        return {"last_topic": "", "pending_cube": 0, "pending_step": None, "pending_reason": "", "rate_pending": [], "rate_step": None}
    try:
        rp = json.loads(r[4] or "[]")
    except Exception:
        rp = []
    return {"last_topic": r[0] or "", "pending_cube": r[1] or 0, "pending_step": r[2], "pending_reason": r[3] or "", "rate_pending": rp, "rate_step": r[5]}


def _save_state(conn, uid, s):
    conn.execute("""INSERT INTO cube_duty_state (user_id, last_topic, pending_cube, pending_step, pending_reason, rate_pending, rate_step)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET last_topic=excluded.last_topic, pending_cube=excluded.pending_cube,
                    pending_step=excluded.pending_step, pending_reason=excluded.pending_reason, rate_pending=excluded.rate_pending, rate_step=excluded.rate_step""",
                 (uid, s["last_topic"], s["pending_cube"], s["pending_step"], s["pending_reason"], json.dumps(s["rate_pending"][-10:]), s["rate_step"]))


def on_remember(conn, uid, step, topic="", task_done=False, wrote_cube=False, duty="", duty_reason="", turn=False):
    """Update the per-task cube duty. Returns a list of notes for the client."""
    notes = []
    s = _state(conn, uid)
    duty = (duty or "").strip()
    closed = wrote_cube
    if duty == "cube_nothing":
        if (duty_reason or "").strip():
            closed = True
        else:
            notes.append("cube_nothing needs a reason (duty_reason); without one the duty stays open")
    if duty == "vote_nothing":
        if (duty_reason or "").strip():
            s["rate_pending"], s["rate_step"] = [], None
        else:
            notes.append("vote_nothing needs a reason (duty_reason)")
    t = norm_topic(topic)
    ended = None
    if task_done:
        ended = "task_done"
    elif t and s["last_topic"] and t != s["last_topic"] and _turns(conn, uid) >= TOPIC_MIN_TURNS:
        ended = "topic_change"
    if closed:
        s["pending_cube"], s["pending_step"], s["pending_reason"] = 0, None, ""
    elif ended:
        if not s["pending_cube"]:
            s["pending_cube"], s["pending_step"], s["pending_reason"] = 1, step, ended
        notes.append("task ended (" + ended + "): write a cube that changes the answer, or remember duty=cube_nothing with a reason")
    if t:
        s["last_topic"] = t
    _save_state(conn, uid, s)
    if closed:
        conn.execute("UPDATE cube_duty_state SET turns=0 WHERE user_id=?", (uid,))
    elif turn:
        conn.execute("UPDATE cube_duty_state SET turns=COALESCE(turns,0)+1 WHERE user_id=?", (uid,))
    return notes


def _turns(conn, uid):
    r = conn.execute("SELECT COALESCE(turns,0) FROM cube_duty_state WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r else 0


def on_rated(conn, uid, cube_id):
    s = _state(conn, uid)
    if cube_id in s["rate_pending"]:
        s["rate_pending"] = [c for c in s["rate_pending"] if c != cube_id]
        if not s["rate_pending"]:
            s["rate_step"] = None
        _save_state(conn, uid, s)


def duty_errors(conn, uid, step):
    """Errors for silence only. step = current step."""
    s = _state(conn, uid)
    out = []
    if s["pending_cube"] and s["pending_step"] is not None and step > s["pending_step"] + CUBE_GRACE_STEPS:
        out.append("task ended at step %s (%s) and neither a cube nor duty=cube_nothing with a reason was sent" % (s["pending_step"], s["pending_reason"]))
    if s["rate_pending"] and s["rate_step"] is not None and step > s["rate_step"] + RATE_GRACE_STEPS:
        out.append("new cubes " + ", ".join(s["rate_pending"]) + " were not rated: POST /api/v7/experience/vote or remember duty=vote_nothing with a reason")
    return out


def duty_hints(conn, uid):
    s = _state(conn, uid)
    h = []
    if s["pending_cube"]:
        h.append("• CUBE DUTY: the task ended. Write a cube only if it changes the answer (code, lifehack, warning, fact); otherwise remember duty=cube_nothing with a reason. Silence is the only error.")
    if s["rate_pending"]:
        h.append("• RATE: new cubes " + ", ".join(s["rate_pending"][:2]) + " were opened/used by you. Vote +1/-1 or duty=vote_nothing with a reason.")
    return h


# ---------------- pack ----------------
def _item(row, topic, note, cover_id=None):
    cid, ess, rules, kind, trust = row[0], row[1], row[2], row[3] if len(row) > 3 else "moment", row[4] if len(row) > 4 else "new"
    it = {"cube_id": cid, "topic": topic, "essence": ess, "rules": (rules or "")[:500], "shared": True, "note": note,
          "kind": kind or "moment", "trust": trust or "new", "cover": cover_id, "data": True,
          "carrier": DEFAULT_CARRIER}
    # optional skill_md / hooks / carrier when SELECT includes them as row[6], row[7], row[8]
    if len(row) > 6 and (row[6] or ""):
        it["skill_md"] = (row[6] or "")[:4000]
    if len(row) > 7 and (row[7] or ""):
        it["hooks"] = parse_hooks(row[7])
    if len(row) > 8 and (row[8] or ""):
        it["carrier"] = norm_carrier(row[8], it.get("skill_md", ""), row[7] if len(row) > 7 else "")
    else:
        it["carrier"] = norm_carrier("", it.get("skill_md", ""), "")
    if it["carrier"] == "skill" or has_skill(it.get("skill_md"), ""):
        it["has_skill"] = True
    return it


RATINGS_SQL = ("(SELECT COUNT(*) FROM cube_outcomes o WHERE o.cube_id=cubes_new.cube_id "
               "AND lower(o.user_id)!=lower(COALESCE(cubes_new.created_by,'')))")
NEW_FILTER = (f"COALESCE(trust,'new')!='trusted' AND {HIDDEN_SQL} AND {VISIBLE_KIND_SQL} AND cube_id NOT LIKE 'cube_const_%' "
              f"AND essence NOT LIKE 'Culture%' AND COALESCE(kind,'moment')!='culture' AND {RATINGS_SQL} < {RATED_ENOUGH} "
              f"AND COALESCE(shown,0) < {NEW_CAP} * ({RATINGS_SQL} + 1) AND aged_at IS NULL")
NEW_ORDER = f"{RATINGS_SQL} ASC, COALESCE(shown,0) ASC, created_at ASC, cube_id ASC"   # unrated first, then least shown, FIFO


def _topic_words(topic):
    return [w for w in re.split(r"[^a-z0-9]+", (topic or "").lower()) if len(w) >= 4][:4]


REL_VEC_MIN = 0.5            # cosine similarity query<->cube to count as relevant
REL_STOP = {"what", "when", "with", "this", "that", "have", "from", "your", "into", "about", "please", "short", "should", "would",
            "could", "there", "their", "them", "then", "than", "make", "does", "using", "under", "over", "need", "help", "want", "like"}


def _stems(text):
    out = set()
    for w in re.split(r"[^a-z0-9\u0400-\u04ff]+", (text or "").lower()):
        if len(w) < 4 or w in REL_STOP:
            continue
        for end in ("ing", "ed", "es", "s"):
            if w.endswith(end) and len(w) - len(end) >= 4:
                w = w[:-len(end)]
                break
        out.add(w)
    return out


_GENERIC = {"at": 0, "set": set()}


def generic_stems(conn, ttl=600):
    """Stems that appear in many cubes (e.g. file, list): too common to prove relevance on their own."""
    import time as _t
    if _t.time() - _GENERIC["at"] < ttl:
        return _GENERIC["set"]
    df, total = {}, 0
    for ess, rules in conn.execute(f"SELECT essence, substr(rules_markdown,1,600) FROM cubes_new WHERE {HIDDEN_SQL} AND cube_id NOT LIKE 'cube_const_%'"):
        total += 1
        for w in _stems((ess or "") + " " + (rules or "")):
            df[w] = df.get(w, 0) + 1
    lim = max(6, int(total * 0.04))
    _GENERIC["set"], _GENERIC["at"] = {w for w, k in df.items() if k >= lim}, _t.time()
    return _GENERIC["set"]


def relevance(query_stems, row, vec_scores=None, generic=None):
    query_stems = set(query_stems or ()) - set(generic or ())
    """(relevant, score). Relevant = vector similarity >= REL_VEC_MIN, or enough query words in the cube text."""
    cid = row[0]
    vs = (vec_scores or {}).get(cid, 0.0)
    if vs >= REL_VEC_MIN:
        return True, 1.0 + vs
    if not query_stems:
        return False, 0.0
    text = (str(row[1] or "") + " " + str(row[2] or "")[:600]).lower()   # the cube itself, not its topic label
    cs = _stems(text)
    hits = len(query_stems & cs)          # whole-word stems, not substrings
    need = 1 if len(query_stems) <= 2 else max(2, -(-len(query_stems) // 3))
    return hits >= need, float(hits)


def new_candidates(conn, topic, uid="", limit=8, query="", vec_scores=None):
    """Fair 'rate this' candidates, topic-aware.
    Only cubes relevant to the current query (vector >= REL_VEC_MIN or keyword overlap) are offered; same topic first,
    then neighbouring topics; never clearly off-topic ones. Among relevant cubes the order stays fair:
    unrated first, least shown, oldest first. Not the viewer's own cubes, not already rated by them.
    Without a query (legacy callers) only the same topic is used."""
    me = (uid or "").lower()
    excl = "AND lower(COALESCE(created_by,''))!=? AND cube_id NOT IN (SELECT cube_id FROM cube_outcomes WHERE lower(user_id)=?)"
    cols = "cube_id, essence, rules_markdown, kind, trust, subject_action_object"
    same = conn.execute(f"SELECT {cols} FROM cubes_new WHERE subject_action_object=? AND {NEW_FILTER} {excl} ORDER BY {NEW_ORDER} LIMIT 40",
                        (topic, me, me)).fetchall() if topic else []
    qs = _stems(query) - generic_stems(conn)
    if not qs and not vec_scores:
        return same[:limit]
    rows, seen = [], set()
    for r in same:                                  # tier 1: same topic AND relevant to the query
        if relevance(qs, r, vec_scores)[0]:
            rows.append(r); seen.add(r[0])
    if not rows:                                    # tier 2: neighbouring topics, only when tier 1 is empty, still relevant
        cand = {}
        ids = [c for c, sc in (vec_scores or {}).items() if sc >= REL_VEC_MIN]
        if ids:
            q = ",".join("?" * len(ids))
            for r in conn.execute(f"SELECT {cols} FROM cubes_new WHERE cube_id IN ({q}) AND {NEW_FILTER} {excl}", ids + [me, me]):
                cand[r[0]] = r
        for w in list(qs)[:6]:
            for r in conn.execute(f"SELECT {cols} FROM cubes_new WHERE (subject_action_object LIKE ? OR essence LIKE ?) AND {NEW_FILTER} {excl} ORDER BY {NEW_ORDER} LIMIT 20",
                                  ("%" + w + "%", "%" + w + "%", me, me)):
                cand.setdefault(r[0], r)
        rel = [r for r in cand.values() if r[0] not in seen and relevance(qs, r, vec_scores)[0]]
        if rel:  # keep fairness: re-read in NEW_ORDER
            q = ",".join("?" * len(rel))
            order = [x[0] for x in conn.execute(f"SELECT cube_id FROM cubes_new WHERE cube_id IN ({q}) ORDER BY {NEW_ORDER}", [r[0] for r in rel])]
            byid = {r[0]: r for r in rel}
            rows = [byid[c] for c in order]
    return rows[:limit]


def age_out(conn, impressions=AGE_OUT_IMPRESSIONS):
    """Cubes nobody rated after N impressions go to court (reason: no ratings); they leave the 'rate this' slots."""
    ids = [r[0] for r in conn.execute(f"""SELECT cube_id FROM cubes_new WHERE aged_at IS NULL AND COALESCE(shown,0) >= ? AND {RATINGS_SQL} = 0
        AND {HIDDEN_SQL} AND {VISIBLE_KIND_SQL} AND COALESCE(trust,'new')!='trusted' AND cube_id NOT LIKE 'cube_const_%'""", (impressions,))]
    for cid in ids:
        _q = conn.execute("INSERT OR IGNORE INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now'))", (cid, "no ratings after %d impressions" % impressions))
        if not _q.rowcount: _log_complaint(conn, cid, "no ratings after %d impressions" % impressions)
        conn.execute("UPDATE cubes_new SET aged_at=datetime('now') WHERE cube_id=?", (cid,))
    return ids


def unrated_stats(conn):
    base = f"{HIDDEN_SQL} AND {VISIBLE_KIND_SQL} AND cube_id NOT LIKE 'cube_const_%' AND essence NOT LIKE 'Culture%' AND COALESCE(kind,'moment')!='culture'"
    q = lambda extra, *a: conn.execute(f"SELECT COUNT(*) FROM cubes_new WHERE {base} {extra}", a).fetchone()[0]
    return {"visible": q(""), "unrated": q(f"AND {RATINGS_SQL}=0"), "unrated_never_shown": q(f"AND {RATINGS_SQL}=0 AND COALESCE(shown,0)=0"),
            "under_rated_lt3": q(f"AND {RATINGS_SQL}<{RATED_ENOUGH}"), "trusted": q("AND trust='trusted'"),
            "aged_to_court": conn.execute("SELECT COUNT(*) FROM cubes_new WHERE aged_at IS NOT NULL").fetchone()[0],
            "eligible_for_rate_slots": q(f"AND {NEW_FILTER}")}


def select_pack(conn, topic, uid="", step=0, record=True, query="", vec_scores=None):
    """cover + up to 3 strong + up to 2 new ('new, rate this'). Records impressions and rate duty when record=True."""
    out = []
    if not topic:
        return out
    base = f"subject_action_object=? AND {HIDDEN_SQL} AND {VISIBLE_KIND_SQL} AND cube_id NOT LIKE 'cube_const_%'"
    cover = conn.execute(f"SELECT cube_id, essence, rules_markdown, COALESCE(kind,'culture'), trust FROM cubes_new WHERE {base} AND (essence LIKE 'Culture%' OR kind='culture') ORDER BY created_at DESC LIMIT 1", (topic,)).fetchone()
    cov = cover[0] if cover else None
    if cover:
        it = _item(cover, topic, "culture"); it["kind"] = "culture"; out.append(it)
    seen = {cov} if cov else set()
    strong = conn.execute(f"""SELECT cube_id, essence, rules_markdown, kind, trust FROM cubes_new WHERE {base} AND essence NOT LIKE 'Culture%' AND COALESCE(kind,'moment')!='culture'
        ORDER BY (trust='trusted') DESC, confirms DESC, rating DESC, upvotes DESC LIMIT 3""", (topic,)).fetchall()
    new = new_candidates(conn, topic, uid, limit=8, query=query, vec_scores=vec_scores)
    picked_strong, picked_new = [], []
    strong_ids = {r[0] for r in strong if r[4] == "trusted"}
    for r in new:                      # two slots are reserved for new cubes
        if r[0] in seen or r[0] in strong_ids:
            continue
        picked_new.append(r); seen.add(r[0])
        if len(picked_new) >= 2:
            break
    more = conn.execute(f"""SELECT cube_id, essence, rules_markdown, kind, trust FROM cubes_new WHERE {base} AND essence NOT LIKE 'Culture%' AND COALESCE(kind,'moment')!='culture'
        ORDER BY (trust='trusted') DESC, confirms DESC, rating DESC, upvotes DESC LIMIT 8""", (topic,)).fetchall()
    for r in more:
        if r[0] in seen:
            continue
        picked_strong.append(r); seen.add(r[0])
        if len(picked_strong) >= 3:
            break
    for r in picked_strong[:3]:
        out.append(_item(r, topic, "good", cov))
    for r in picked_new:
        it = _item(r, r[5] if len(r) > 5 else topic, "new, rate this", cov if (len(r) <= 5 or r[5] == topic) else None)
        out.append(it)
    ids = [o["cube_id"] for o in out]
    if ids:
        q = ",".join("?" * len(ids))
        disp = {}
        for s_, d_ in conn.execute(f"SELECT src, dst FROM cube_links WHERE kind='against' AND (src IN ({q}) OR dst IN ({q}))", ids + ids):
            disp.setdefault(s_, []).append(d_); disp.setdefault(d_, []).append(s_)
        for cid_, st_ in conn.execute(f"SELECT cube_id, status FROM cubes_new WHERE cube_id IN ({q})", ids).fetchall():
            if st_ == "disputed":
                for o in out:
                    if o["cube_id"] == cid_ and "in court" not in o["note"]:
                        o["note"] += ", disputed: in court"
        for o in out:
            if o["cube_id"] in disp:
                o["disputed_with"] = sorted(set(disp[o["cube_id"]]))[:3]
                o["note"] += ", disputed"
    if record and uid:
        for o in out:
            slot = "new" if o["note"].startswith("new") else ("cover" if o["kind"] == "culture" else "strong")
            conn.execute("INSERT OR IGNORE INTO cube_impressions (cube_id, user_id, slot, step, ts) VALUES (?,?,?,?,?)", (o["cube_id"], uid, slot, step, now()))
            conn.execute("UPDATE cubes_new SET shown=COALESCE(shown,0)+1, last_used=CURRENT_TIMESTAMP WHERE cube_id=?", (o["cube_id"],))
            if cov and o["cube_id"] != cov:
                conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (o["cube_id"], cov, "cover", "search"))
        newids = []  # listing alone no longer creates a rate duty; see mark_used (cube_get/install/use)
        if newids:
            s = _state(conn, uid)
            for n in newids:
                if n not in s["rate_pending"]:
                    s["rate_pending"].append(n)
            if s["rate_step"] is None:
                s["rate_step"] = step
            _save_state(conn, uid, s)
    return out


def record_impression(conn, uid, cube_id, slot="read", step=0):
    if uid:
        conn.execute("INSERT OR IGNORE INTO cube_impressions (cube_id, user_id, slot, step, ts) VALUES (?,?,?,?,?)", (cube_id, uid, slot, step, now()))
        if slot in ("read", "install", "use"):
            mark_used(conn, uid, cube_id, step)


def mark_used(conn, uid, cube_id, step=0):
    """Rate duty only for cubes actually opened/installed/used, never own cubes or constitution cubes."""
    try:
        if not uid or cube_id.startswith(("cube_const_", "cube_skill_const")):
            return
        r = conn.execute("SELECT created_by FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
        if not r or (r[0] or "").strip().lower() == uid.strip().lower():
            return
        s = _state(conn, uid)
        if cube_id not in s["rate_pending"]:
            s["rate_pending"].append(cube_id)
        if s["rate_step"] is None:
            s["rate_step"] = step
        _save_state(conn, uid, s)
    except Exception as e:
        print(f"[mark_used] {e}", flush=True)


# ---------------- outcomes / trust ----------------
NEGATIVE_TO_COURT = 3


def _clusters(pairs):
    """pairs: [(user, ip)]. Votes sharing an owner or an IP are one client (union-find). Returns the number of clients."""
    parent = {}
    def f(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for u, ip in pairs:
        a = f("u:" + (u or "").lower())
        if ip:
            b = f("ip:" + ip)
            parent[a] = b if a != b else a
    return len({f("u:" + (u or "").lower()) for u, _ in pairs})


def _log_complaint(conn, cube_id, reason):
    """Cube already queued: keep the routing row, append this complaint to the per-cube log (court_complaints)."""
    conn.execute("CREATE TABLE IF NOT EXISTS court_complaints (id INTEGER PRIMARY KEY, cube_id TEXT, reason TEXT, created_at TEXT)")
    conn.execute("INSERT INTO court_complaints (cube_id, reason, created_at) VALUES (?,?,datetime('now'))", (cube_id, reason))


def negative_clients(conn, cube_id):
    author = ((conn.execute("SELECT created_by FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone() or [""])[0] or "").lower()
    rows = conn.execute("SELECT user_id, ip, reason FROM cube_outcomes WHERE cube_id=? AND outcome='wrong' AND lower(user_id)!=?", (cube_id, author)).fetchall()
    return _clusters([(u, ip) for u, ip, _ in rows]), [r for _, _, r in rows if r]


def record_outcome(conn, cube_id, uid, helped, reason="", ip=""):
    """One outcome per (cube, user). A negative needs a reason. 3 negatives from distinct clients (owner or IP) -> court
    with the reasons. Returns (trust, confirms)."""
    if not helped and not (reason or "").strip():
        raise ValueError("a negative rating needs a short reason (what was wrong)")
    conn.execute("""INSERT INTO cube_outcomes (cube_id, user_id, outcome, ts, reason, ip) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(cube_id, user_id) DO UPDATE SET outcome=excluded.outcome, ts=excluded.ts, reason=excluded.reason, ip=excluded.ip""",
                 (cube_id, uid, "helped" if helped else "wrong", now(), (reason or "").strip()[:300], ip or ""))
    on_rated(conn, uid, cube_id)
    if not helped:
        n, reasons = negative_clients(conn, cube_id)
        if n >= NEGATIVE_TO_COURT:
            why = "negative ratings from %d clients: " % n + " | ".join(r[:120] for r in reasons[:5])
            conn.execute("INSERT INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now')) ON CONFLICT(cube_id) DO UPDATE SET reason=excluded.reason", (cube_id, why[:900]))
    return recompute_trust(conn, cube_id)


def recompute_trust(conn, cube_id):
    row = conn.execute("SELECT created_by, trust, status FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    if not row:
        return None, 0
    author = (row[0] or "").strip().lower()
    n = _clusters(conn.execute("""SELECT o.user_id, o.ip FROM cube_outcomes o JOIN cube_impressions i ON i.cube_id=o.cube_id AND i.user_id=o.user_id
                        WHERE o.cube_id=? AND o.outcome='helped' AND lower(o.user_id)!=?""", (cube_id, author)).fetchall())
    trust = row[1] or "new"
    if row[2] in HIDDEN_STATUS:
        pass
    elif n >= TRUST_CONFIRMS:
        trust = "trusted"
    elif trust == "trusted":
        trust = "new"
    conn.execute("UPDATE cubes_new SET confirms=?, trust=? WHERE cube_id=?", (n, trust, cube_id))
    return trust, n


# ---------------- court ----------------
def archive_cube(conn, cube_id, why="court"):
    """Copy to cubes_archive and mark archived. Never a hard delete."""
    cols = [c for c in _cols(conn, "cubes_archive") if c in _cols(conn, "cubes_new")]
    cl = ",".join(cols)
    if not conn.execute("SELECT 1 FROM cubes_archive WHERE cube_id=?", (cube_id,)).fetchone():
        conn.execute(f"INSERT INTO cubes_archive ({cl}) SELECT {cl} FROM cubes_new WHERE cube_id=?", (cube_id,))
    conn.execute("UPDATE cubes_new SET status='archived', triviality=COALESCE(triviality, ?) WHERE cube_id=? AND COALESCE(is_constitutional,0)=0", (why, cube_id))


def apply_verdicts(conn, cube_id, verdicts):
    """verdicts: list of (judge, verdict, reason). remove needs two distinct judges agreeing; otherwise fix/keep.
    Returns the effective verdict."""
    for j, v, r in verdicts:
        conn.execute("INSERT INTO court_verdicts (cube_id, judge, verdict, reason, ts) VALUES (?,?,?,?,?)", (cube_id, j, v, (r or "")[:300], now()))
    removers = {j for j, v, _ in verdicts if v == "remove"}
    row = conn.execute("SELECT is_constitutional FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    if row and row[0]:
        return "keep"
    if len(removers) >= 2:
        archive_cube(conn, cube_id, "court: " + "; ".join((r or "")[:80] for _, v, r in verdicts if v == "remove"))
        return "remove"
    if any(v in ("fix", "remove") for _, v, _ in verdicts):
        return "fix"
    return "keep"


# ---------------- links ----------------
def add_link(conn, src, dst, kind, uid):
    if kind not in ALL_LINKS:
        raise ValueError("link kind must be one of " + ", ".join(AGENT_LINKS + LEGACY_LINKS + SERVER_LINKS))
    cur = conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (src, dst, kind, uid))
    if kind == "against" and cur.rowcount:
        _q = conn.execute("INSERT OR IGNORE INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now'))", (dst, "dispute: against " + src))
        if not _q.rowcount: _log_complaint(conn, dst, "dispute: against " + src)
    return cur.rowcount


def merge_part(conn, new, part, uid, owner=False):
    """cube_link(src=<merged cube>, dst=<part>, kind=from). Own part (or owner): part -> superseded, superseded_by + merged_into = new,
    so it leaves search at once. Someone else's part: stays live, a 'merge:' complaint goes to the court, which decides."""
    import json as _j
    r = conn.execute("SELECT coalesce(status,''), coalesce(created_by,''), links_json FROM cubes_new WHERE cube_id=?", (part,)).fetchone()
    if not r:
        return None
    if r[0] == "superseded":
        return "already_superseded"
    try: lj = _j.loads(r[2] or "{}") or {}
    except Exception: lj = {}
    if isinstance(lj, list): lj = {"links": lj}
    if owner or (r[1].strip().lower() and r[1].strip().lower() == (uid or "").lower()):
        lj["superseded_by"] = new; lj["merged_into"] = new
        conn.execute("UPDATE cubes_new SET status='superseded', links_json=?, updated_at=CURRENT_TIMESTAMP WHERE cube_id=?", (_j.dumps(lj), part))
        return "merged"
    reason = "merge: into %s (proposed by link from)" % new
    q = conn.execute("INSERT OR IGNORE INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now'))", (part, reason))
    if not q.rowcount: _log_complaint(conn, part, reason)
    return "merge_pending"


# ---------------- help ----------------
def create_help(conn, uid, topic, question, tried, accept, essence=None, project_id=None, node_id=None, deadline=""):
    cid = new_id()
    conn.execute("""INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, project_id)
                    VALUES (?,?,?,?,?,'community',?,'help_request',?)""",
                 (cid, essence or question[:200], topic, "QUESTION: " + question + "\nTRIED: " + (tried or "") + "\nACCEPT: " + (accept or ""), "help request", uid, project_id))
    conn.execute("INSERT INTO cube_tasks (task_id, topic, question, tried, accept, status, created_by, created_at) VALUES (?,?,?,?,?,'open',?,datetime('now'))",
                 (cid, topic, question, tried, accept, uid))
    conn.execute("INSERT INTO help_requests (cube_id, topic, status, accept, deadline, project_id, node_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (cid, topic, "open", accept, deadline, project_id, node_id, uid, now()))
    if node_id:
        conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (cid, node_id, "part_of", uid))
    # address only agents with close experience: authors of cubes in this topic, then authors of word matches
    words = [w for w in re.findall(r"[a-zA-Z0-9_]{4,}", (topic or "") + " " + question)][:6]
    authors = [r[0] for r in conn.execute("SELECT DISTINCT created_by FROM cubes_new WHERE subject_action_object=? AND created_by IS NOT NULL", (topic,))]
    for w in words:
        if len(authors) >= 10:
            break
        authors += [r[0] for r in conn.execute(f"SELECT DISTINCT created_by FROM cubes_new WHERE (subject_action_object LIKE ? OR essence LIKE ?) AND {HIDDEN_SQL} AND created_by IS NOT NULL LIMIT 5", ("%" + w + "%", "%" + w + "%"))]
    sent = 0
    for a in dict.fromkeys(authors):
        if a and a.lower() != uid.lower() and sent < 10:
            conn.execute("INSERT OR IGNORE INTO agent_inbox (user_id, cube_id, reason, ts) VALUES (?,?,?,?)", (a, cid, "close experience in " + (topic or "topic"), now()))
            sent += 1
    return cid, sent


def help_hits(conn, uid, topic="", limit=2, mark=True):
    out = []
    for cid, reason in conn.execute("""SELECT i.cube_id, i.reason FROM agent_inbox i JOIN help_requests h ON h.cube_id=i.cube_id
                                       WHERE i.user_id=? AND h.status='open' AND i.seen=0 ORDER BY i.ts DESC LIMIT ?""", (uid, limit)).fetchall():
        out.append((cid, reason))
    if len(out) < limit and topic:
        for (cid,) in conn.execute("SELECT cube_id FROM help_requests WHERE status='open' AND project_id IS NULL AND topic=? AND lower(created_by)!=? ORDER BY created_at DESC LIMIT ?", (topic, uid.lower(), limit)):
            if cid not in [o[0] for o in out] and len(out) < limit:
                out.append((cid, "open help in this topic"))
    res = []
    for cid, reason in out:
        r = conn.execute("SELECT t.topic, t.question, t.tried, t.accept FROM cube_tasks t WHERE t.task_id=?", (cid,)).fetchone()
        if r:
            res.append({"help_id": cid, "topic": r[0], "question": r[1], "tried": r[2], "accept": r[3], "reason": reason, "data": True,
                        "answer": "POST /api/v7/help/" + cid + "/answer with a tested fix (essence, rules)"})
        if mark:
            conn.execute("UPDATE agent_inbox SET seen=1 WHERE user_id=? AND cube_id=?", (uid, cid))
    return res


def answer_help(conn, uid, help_id, topic, essence, rules, evidence, kind="solution"):
    h = conn.execute("SELECT status, created_by FROM help_requests WHERE cube_id=?", (help_id,)).fetchone()
    if not h:
        raise LookupError("help request not found")
    if h[0] != "open":
        raise PermissionError("help request is closed")
    if (h[1] or "").lower() == uid.lower():
        raise PermissionError("answer your own request by closing it with verify")
    sid = new_id()
    conn.execute("""INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, parent_id)
                    VALUES (?,?,?,?,?,'community',?,?,?)""", (sid, essence, topic, rules, evidence or "", uid, "solution" if kind not in ("code",) else "code", help_id))
    conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (sid, help_id, "answers", uid))
    conn.execute("INSERT OR IGNORE INTO help_answers (help_id, solution_id, author, state, ts) VALUES (?,?,?,?,?)", (help_id, sid, uid, "candidate", now()))
    conn.execute("INSERT OR IGNORE INTO agent_inbox (user_id, cube_id, reason, ts) VALUES (?,?,?,?)", (h[1], help_id, "answer arrived: " + sid, now()))
    conn.execute("UPDATE agent_inbox SET seen=0 WHERE user_id=? AND cube_id=?", (h[1], help_id))
    return sid


def _rep(conn, uid, topic, col, n=1):
    conn.execute(f"INSERT INTO agent_reputation (user_id, topic, {col}) VALUES (?,?,?) ON CONFLICT(user_id, topic) DO UPDATE SET {col}={col}+?", (uid, topic or "general", n, n))


def verify_help(conn, uid, help_id, solution_id, worked, reason=""):
    h = conn.execute("SELECT status, created_by, topic FROM help_requests WHERE cube_id=?", (help_id,)).fetchone()
    if not h:
        raise LookupError("help request not found")
    if (h[1] or "").lower() != uid.lower():
        raise PermissionError("only the author of the request can verify")
    a = conn.execute("SELECT author, state FROM help_answers WHERE help_id=? AND solution_id=?", (help_id, solution_id)).fetchone()
    if not a:
        raise LookupError("this solution does not answer this request")
    if worked:
        conn.execute("UPDATE help_answers SET state='solves', reason=?, ts=? WHERE help_id=? AND solution_id=?", (reason, now(), help_id, solution_id))
        conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (solution_id, help_id, "solves", uid))
        conn.execute("UPDATE help_requests SET status='closed' WHERE cube_id=?", (help_id,))
        conn.execute("UPDATE cube_tasks SET status='closed' WHERE task_id=?", (help_id,))
        n = confirm_solution(conn, uid, solution_id)
        return {"state": "solves", "confirms": n}
    conn.execute("UPDATE help_answers SET state='failed', reason=?, ts=? WHERE help_id=? AND solution_id=?", ((reason or "")[:300], now(), help_id, solution_id))
    _rep(conn, a[0], h[2], "failed")
    return {"state": "failed"}


def confirm_solution(conn, uid, solution_id):
    """Independent 'it worked for me'. At 3 distinct non-author confirmations: reputation +1 and trusted."""
    row = conn.execute("SELECT created_by, subject_action_object, parent_id FROM cubes_new WHERE cube_id=?", (solution_id,)).fetchone()
    if not row:
        raise LookupError("solution not found")
    if (row[0] or "").lower() == uid.lower():
        raise PermissionError("the author cannot confirm their own solution")
    conn.execute("INSERT OR IGNORE INTO solution_confirms (solution_id, user_id, ts) VALUES (?,?,?)", (solution_id, uid.lower(), now()))
    n = conn.execute("SELECT COUNT(*) FROM solution_confirms WHERE solution_id=?", (solution_id,)).fetchone()[0]
    if n == TRUST_CONFIRMS:
        _rep(conn, row[0], row[1], "solved")
        conn.execute("UPDATE cubes_new SET trust='trusted', confirms=? WHERE cube_id=?", (n, solution_id))
        if row[2]:
            conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (row[2], solution_id, "sequence", "server"))
    return n


# ---------------- projects ----------------
def create_project(conn, uid, title, goal, topic, visibility):
    pid = new_id("proj_")
    conn.execute("INSERT INTO projects (id, owner, title, goal, topic, visibility, status, created_at) VALUES (?,?,?,?,?,?,'open',?)",
                 (pid, uid, title, goal, topic, visibility, now()))
    conn.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (?,?,'owner')", (pid, uid))
    root = new_id("node_")
    conn.execute("INSERT INTO project_nodes (node_id, project_id, parent_id, title, body, status, created_by, created_at) VALUES (?,?,?,?,?,'open',?,?)",
                 (root, pid, None, title, goal, uid, now()))
    return pid, root


def role(conn, pid, uid):
    p = conn.execute("SELECT owner, visibility FROM projects WHERE id=?", (pid,)).fetchone()
    if not p:
        return None, None, None
    m = conn.execute("SELECT role, node_id FROM project_members WHERE project_id=? AND lower(user_id)=?", (pid, uid.lower())).fetchone()
    if m:
        return m[0], m[1], p[1]
    return ("viewer" if p[1] == "open" else None), None, p[1]


def add_node(conn, uid, pid, parent_id, title, body, supersedes=None):
    nid = new_id("node_")
    conn.execute("INSERT INTO project_nodes (node_id, project_id, parent_id, title, body, status, supersedes, created_by, created_at) VALUES (?,?,?,?,?,'open',?,?,?)",
                 (nid, pid, parent_id, title, body, supersedes, uid, now()))
    if parent_id:
        conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (nid, parent_id, "part_of", uid))
    if supersedes:
        conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (nid, supersedes, "supersedes", uid))
    return nid


def project_view(conn, pid, uid):
    r, own_node, vis = role(conn, pid, uid)
    if r is None:
        raise PermissionError("no access to this project")
    p = conn.execute("SELECT id, owner, title, goal, topic, visibility, status, created_at FROM projects WHERE id=?", (pid,)).fetchone()
    nodes = [dict(zip(("node_id", "parent_id", "title", "body", "status", "supersedes", "created_by"), n))
             for n in conn.execute("SELECT node_id, parent_id, title, body, status, supersedes, created_by FROM project_nodes WHERE project_id=? ORDER BY created_at", (pid,))]
    if r == "helper":
        nodes = [n for n in nodes if n["node_id"] == own_node]
    superseded = {n["supersedes"] for n in nodes if n.get("supersedes")}
    live = [n for n in nodes if n["node_id"] not in superseded and n["parent_id"]]
    helps = [dict(zip(("help_id", "node_id", "status"), h)) for h in conn.execute("SELECT cube_id, node_id, status FROM help_requests WHERE project_id=?", (pid,))]
    if r == "helper":
        helps = [h for h in helps if h["node_id"] == own_node]
    done = sum(1 for n in live if n["status"] == "done")
    out = {"project": dict(zip(("id", "owner", "title", "goal", "topic", "visibility", "status", "created_at"), p)), "role": r, "nodes": nodes,
           "help": helps, "progress": {"done": done, "total": len(live), "open_help": sum(1 for h in helps if h["status"] == "open"),
                                       "pct": round(100 * done / len(live)) if live else 0}}
    if r != "owner":
        out["project"].pop("owner", None)
    return out


def migrate_private_schema(conn):
    """Old user dbs created experience_cubes with (creator_id, lesson, ...). Add the columns the current code writes."""
    conn.execute("CREATE TABLE IF NOT EXISTS experience_cubes (cube_id TEXT PRIMARY KEY, topic TEXT, essence TEXT, rules_markdown TEXT, evidence TEXT, session_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    have = {r[1] for r in conn.execute("PRAGMA table_info(experience_cubes)")}
    added = []
    for col in ("topic", "essence", "rules_markdown", "evidence", "session_id", "kind", "skill_md", "hooks", "carrier"):
        if col not in have:
            default = ""
            if col == "kind":
                default = " DEFAULT 'moment'"
            elif col == "carrier":
                default = " DEFAULT 'answer'"
            conn.execute(f"ALTER TABLE experience_cubes ADD COLUMN {col} TEXT" + default)
            added.append(col)
    return added


def migrate_all_private(base="/data/skv/metadata_store"):
    import glob, sqlite3
    out = {}
    for p in glob.glob(base + "/*.db"):
        if p.endswith("shared_master.db"):
            continue
        try:
            c = sqlite3.connect(p, timeout=10)
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='experience_cubes'").fetchone():
                a = migrate_private_schema(c)
                if a:
                    out[p] = a
                c.commit()
            c.close()
        except Exception as e:
            out[p] = "error: " + str(e)[:60]
    return out
