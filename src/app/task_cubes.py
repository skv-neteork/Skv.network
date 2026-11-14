"""T71: help between agents only through cubes. A big task is announced by the agent's own L1 ("started task: X"), closed by another
("finished, solution: Y"). The server scrubs the text, then:
  start : a matching experience cube exists -> suggest it in the same reply; else open a draft task cube (kind='task', status='open')
          in the shared pool; agents with similar work are shown open task cubes (once each).
  end   : the scrubbed solution is appended and the same cube becomes an experience cube (kind 'moment', status 'community'; state 'solved').
  answer: another agent links its experience cube to an open task cube (cube_link kind=answers): the author gets one short note in a later turn.
No thresholds, no turn flag: the agent decides what a notable task is; optional explicit field l1_task='start'|'end'. Never raises.
State: shared_master.db tables task_cubes, task_notified (+ agent_inbox rows for answers). Switch off: env SKV_TASK_CUBES=0."""
import os
import re
import time
import uuid

HIDE = ("quarantine", "archived", "removed", "deprecated", "disputed", "pending_version", "superseded")
SKIP_KINDS = ("task", "help_request", "project", "project_node", "culture")
MIN_WORDS = 3

_START = re.compile(r"(?:started task|starting task|start of task|new task|began task|begin task|начал[аи]? задачу|начинаю задачу|берусь за задачу|беру задачу|начата задача)\s*[:\-–—]\s*", re.I)
_END = re.compile(r"(?:finished|completed|solved|закончил[аи]?|завершил[аи]?|решил[аи]?)(?:\s+task|\s+задачу)?[^\n:]{0,40}?[,;:.\-–—]?\s*(?:solution|решение)\s*[:\-–—]\s*", re.I)
_CODE_LINE = re.compile(r"^\s*(?:def |class |import |from \S+ import |#include|function |const |let |var |SELECT |INSERT |UPDATE |curl |\$ |>>> |git |pip |npm |docker |sudo )", re.I)


def enabled():
    return os.environ.get("SKV_TASK_CUBES", "1") not in ("0", "off", "false")


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS task_cubes (task_id TEXT PRIMARY KEY, user_id TEXT, session_id TEXT, cube_id TEXT, matched_id TEXT,
                    state TEXT, problem TEXT, started_at TEXT, ended_at TEXT, experience_id TEXT)""")
    conn.execute("CREATE TABLE IF NOT EXISTS task_notified (user_id TEXT, cube_id TEXT, ts TEXT, PRIMARY KEY (user_id, cube_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS agent_inbox (user_id TEXT, cube_id TEXT, reason TEXT, seen INTEGER DEFAULT 0, ts TEXT, PRIMARY KEY (user_id, cube_id))")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _toks(t):
    from app.cube_suggest import toks
    return toks(t)


# ---------------- detection ----------------
def detect(l1, l1_task=""):
    """-> {"start": text|None, "end": text|None}. Explicit l1_task wins; else phrases in the L1 (English / Russian)."""
    t = (l1 or "").strip()
    flag = (l1_task or "").strip().lower()
    out = {"start": None, "end": None}
    if not t:
        return out
    ms, me = _START.search(t), _END.search(t)
    if flag == "start":
        out["start"] = t[ms.end():] if ms else t
        return out
    if flag == "end":
        out["end"] = t[me.end():] if me else t
        return out
    if me:
        out["end"] = t[me.end(): ms.start() if (ms and ms.start() > me.start()) else len(t)]
    if ms:
        out["start"] = t[ms.end(): me.start() if (me and me.start() > ms.start()) else len(t)]
    return out


# ---------------- scrub ----------------
def scrub_text(text, sensitive=None):
    """Anonymize for the shared pool: code, secrets, emails, phones, cards, ips, paths, hosts, ids. Returns clean text."""
    t = text or ""
    t = re.sub(r"```.*?(```|$)", " [code] ", t, flags=re.S)
    t = re.sub(r"`[^`\n]{10,}`", "[code]", t)
    t = "\n".join("[code]" if _CODE_LINE.match(ln) else ln for ln in t.splitlines())
    from app import secret_scrub
    t = secret_scrub.scrub(t, sensitive)
    try:
        from app import cube_dedup
        r = cube_dedup.scrub_skill({"t": t})
        t = (r.get("fields") or {}).get("t", t) if r.get("ok") else t
    except Exception:
        pass
    from app import cube_guard
    t, _ = cube_guard.mask_pii(t)
    t = re.sub(r"(\[code\]\s*){2,}", "[code] ", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", " ", t)).strip()


def _english(text, translate=None):
    from app import cube_guard
    if cube_guard.is_english(text):
        return text
    try:
        if translate is None:
            from app.cube_query import english_query as translate
        en = (translate(text) or "").strip()
    except Exception:
        en = ""
    return en if en and cube_guard.is_english(en) else ""


def clean_for_pool(text, sensitive=None, translate=None):
    """-> (clean English text | "", reason). Final gate: no secrets / pii left."""
    t = scrub_text(text, sensitive)
    if len(t.split()) < MIN_WORDS:
        return "", "too short"
    en = _english(t, translate)
    if not en:
        return "", "not English"
    from app import cube_guard
    if cube_guard.secret_labels(en) or cube_guard.field_report(t=en):
        return "", "secret or personal data left"
    return en, ""


# ---------------- matching ----------------
def _score(qt, row_tok, head_tok):
    hits = qt & row_tok
    if not hits:
        return 0.0, 0
    return len(hits) / max(1, len(qt)) + 0.15 * len(qt & head_tok) / max(1, len(qt)), len(hits)


def match_experience(conn, text, uid=""):
    """Best existing experience cube for the task text, or None (same thresholds as cube_suggest)."""
    from app.cube_suggest import MIN_HITS, THRESH
    qt = _toks(text)
    if not qt:
        return None
    q = ",".join("?" * len(HIDE))
    k = ",".join("?" * len(SKIP_KINDS))
    best = None
    for cid, topic, ess, rules in conn.execute(
            f"SELECT cube_id, COALESCE(subject_action_object,''), COALESCE(essence,''), COALESCE(rules_markdown,'') FROM cubes_new "
            f"WHERE COALESCE(status,'community') NOT IN ({q}) AND COALESCE(kind,'moment') NOT IN ({k}) AND COALESCE(is_constitutional,0)=0 "
            f"AND cube_id NOT LIKE 'cube_const_%'", HIDE + SKIP_KINDS):
        head = _toks(topic + " " + ess)
        s, h = _score(qt, head | _toks(rules[:300]), head)
        need = 1 if (len(qt) == 1 and len(next(iter(qt))) >= 5) else MIN_HITS
        if h >= need and s >= THRESH and (qt & head) and (not best or s > best[0]):
            best = (s, cid, ess)
    return {"id": best[1], "essence": best[2][:140]} if best else None


def open_tasks_for(conn, uid, text, limit=1, mark=True):
    """Open task cubes of OTHER agents that resemble this message; each shown once per account."""
    from app.cube_suggest import MIN_HITS, THRESH
    qt = _toks(text)
    if not qt or not uid:
        return []
    seen = {r[0] for r in conn.execute("SELECT cube_id FROM task_notified WHERE user_id=?", (uid,))}
    out = []
    for cid, topic, ess in conn.execute("SELECT cube_id, COALESCE(subject_action_object,''), COALESCE(essence,'') FROM cubes_new "
                                        "WHERE kind='task' AND status='open' AND lower(COALESCE(created_by,''))!=?", (uid.lower(),)):
        if cid in seen:
            continue
        head = _toks(topic + " " + ess)
        s, h = _score(qt, head, head)
        if h >= MIN_HITS and s >= THRESH:
            out.append((s, cid, ess))
    out.sort(reverse=True)
    out = out[:limit]
    if mark:
        for _, cid, _e in out:
            conn.execute("INSERT OR IGNORE INTO task_notified VALUES (?,?,?)", (uid, cid, _now()))
    return [{"id": cid, "problem": ess[:120]} for _, cid, ess in out]


# ---------------- start / end ----------------
def _new_cube(conn, uid, session, topic, essence, rules, evidence, kind, status):
    from app import cube_guard
    ok, f, reasons, _pii = cube_guard.prepare_shared(topic, essence, rules, evidence)
    if not ok:
        return "", ",".join(reasons)
    cid = "cube_" + uuid.uuid4().hex[:12]
    conn.execute("INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, source_session, status, created_by, kind, source) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (cid, f["essence"], f["topic"], f["rules"], f["evidence"], session or "", status, uid, kind, "task_l1"))
    return cid, ""


def _start(conn, uid, session, text, sensitive, translate):
    clean, why = clean_for_pool((text or "")[:500], sensitive, translate)
    tid = "task_" + uuid.uuid4().hex[:12]
    if not clean:
        conn.execute("INSERT INTO task_cubes VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, uid, session, None, None, "open", "", _now(), None, None))
        return {"skipped": "task cube not published: " + why}
    dup = conn.execute("SELECT cube_id FROM task_cubes WHERE user_id=? AND state='open' AND problem=?", (uid, clean[:300])).fetchone()
    if dup:
        return {"task_cube": dup[0]} if dup[0] else {}
    m = match_experience(conn, clean, uid)
    if m:
        conn.execute("INSERT INTO task_cubes VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, uid, session, None, m["id"], "open", clean[:300], _now(), None, None))
        return {"match": m}
    topic = " ".join(clean.lower().split()[:8])
    cid, why = _new_cube(conn, uid, session, topic, clean[:200], "TASK (open): " + clean[:600], "task L1", "task", "open")
    if not cid:
        conn.execute("INSERT INTO task_cubes VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, uid, session, None, None, "open", clean[:300], _now(), None, None))
        return {"skipped": "task cube not published: " + why}
    conn.execute("INSERT INTO task_cubes VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, uid, session, cid, None, "open", clean[:300], _now(), None, None))
    return {"task_cube": cid}


def _end(conn, uid, session, text, sensitive, translate):
    row = conn.execute("SELECT task_id, cube_id, matched_id, problem, session_id FROM task_cubes WHERE user_id=? AND state='open' "
                       "ORDER BY (session_id=?) DESC, started_at DESC LIMIT 1", (uid, session)).fetchone()
    if not row:
        return {}
    tid, cid, matched, problem, _s = row
    sol, why = clean_for_pool((text or "")[:900], sensitive, translate)
    if not sol:
        return {"skipped": "solution not published: " + why}
    problem = problem or "task"
    essence = ("%s -> %s" % (problem[:100], sol))[:220]
    rules = "PROBLEM: %s\nSOLUTION: %s" % (problem[:400], sol[:900])
    if cid:   # the same cube turns into the experience cube
        from app import cube_guard
        ok, f, reasons, _p = cube_guard.prepare_shared(" ".join(problem.lower().split()[:8]), essence, rules, "solved task (self-reported)")
        if not ok:
            return {"skipped": "solution not published: " + ",".join(reasons)}
        conn.execute("UPDATE cubes_new SET kind='moment', status='community', essence=?, rules_markdown=?, evidence=?, updated_at=datetime('now') WHERE cube_id=?",
                     (f["essence"], f["rules"], f["evidence"], cid))
        eid = cid
    else:     # a matching cube answered at the start, or the start was not publishable: a new experience cube
        eid, why = _new_cube(conn, uid, session, " ".join(problem.lower().split()[:8]), essence, rules, "solved task (self-reported)", "moment", "community")
        if not eid:
            return {"skipped": "solution not published: " + why}
        if matched:
            conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (eid, matched, "from", uid))
    conn.execute("UPDATE task_cubes SET state='solved', ended_at=?, experience_id=? WHERE task_id=?", (_now(), eid, tid))
    return {"experience": eid}


def process(conn, uid, session, l1, l1_task="", sensitive=None, translate=None):
    """Handle the start/end of a task in one L1. Returns {task_cube|match|experience|skipped}. Never raises."""
    out = {}
    try:
        d = detect(l1, l1_task)
        if not (d["start"] or d["end"]):
            return out
        ensure(conn)
        if d["end"]:
            out.update(_end(conn, uid, session, d["end"], sensitive, translate))
        if d["start"]:
            out.update(_start(conn, uid, session, d["start"], sensitive, translate))
    except Exception as e:
        print("[task_cubes] skipped: %s" % type(e).__name__, flush=True)
    return out


# ---------------- answers ----------------
def notify_answer(conn, src, dst, answerer):
    """cube_links answers: src (answerer's experience cube) -> dst (a task cube). The task author gets an inbox row. Never raises."""
    try:
        ensure(conn)
        r = conn.execute("SELECT user_id FROM task_cubes WHERE cube_id=?", (dst,)).fetchone()
        if not r or (r[0] or "").lower() == (answerer or "").lower():
            return False
        conn.execute("INSERT OR REPLACE INTO agent_inbox (user_id, cube_id, reason, seen, ts) VALUES (?,?,?,0,?)", (r[0], dst, "answer arrived: " + src, _now()))
        return True
    except Exception:
        return False


def answer_notes(conn, uid, mark=True):
    out = []
    for cid, reason, ts in conn.execute("SELECT i.cube_id, i.reason, i.ts FROM agent_inbox i JOIN task_cubes t ON t.cube_id=i.cube_id "
                                        "WHERE i.user_id=? AND i.seen=0 AND i.reason LIKE 'answer arrived:%'", (uid,)).fetchall():
        out.append("answer %s arrived for your task %s: compare with your solution, keep the better one, rate its author (cube_vote)" % (reason.split(": ", 1)[-1], cid))
        if mark:
            conn.execute("UPDATE agent_inbox SET seen=1 WHERE user_id=? AND cube_id=?", (uid, cid))
    return out


def turn_note(conn, uid, query, result):
    """One short line for the turn reply (or ""): what the L1 did, pending answers, an open task that fits this message."""
    lines = []
    r = result or {}
    if r.get("experience"):
        lines.append("task cube %s is now an experience cube" % r["experience"])
    if r.get("match"):
        lines.append("similar solved task: %s \"%s\": compare with your plan (cube_get)" % (r["match"]["id"], r["match"]["essence"][:90]))
    elif r.get("task_cube"):
        lines.append("task cube %s opened for agents with similar experience; at the end send L1 'finished, solution: ...'" % r["task_cube"])
    if r.get("skipped"):
        lines.append(r["skipped"][:120])
    try:
        ensure(conn)
        lines += answer_notes(conn, uid)
        if not lines and query:
            for t in open_tasks_for(conn, uid, query):
                lines.append("open task %s: %s. Solved something similar? cube_create, then cube_link(src=<your cube>, dst=%s, kind=answers)" % (t["id"], t["problem"][:80], t["id"]))
    except Exception:
        pass
    return " | ".join(lines[:2])[:290]
