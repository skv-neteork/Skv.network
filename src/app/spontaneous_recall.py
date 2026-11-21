"""Spontaneous recall (T73): a high-relevance decision on the next turn.

The requesting turn never waits on a model. Jobs live in a sibling table,
not recall_later, so remembered / for_recall stay unchanged. Ranking is
local token overlap plus a decision bonus. A cheap model is available only
when SKV_SPONTANEOUS_MODEL is set, and on_turn does not call it.
"""
import hashlib
import json
import os
import re
import sqlite3
import time

SIDECAR = os.environ.get("SKV_SPONTANEOUS_DB", "/data/skv/metadata_store/spontaneous_recall.db")
THRESHOLD = 0.72
MAX_HITS = 3
FACT_CHARS = 160
EVERY = 10

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "you", "your", "our", "not", "but", "has", "have", "had", "its", "into",
    "about", "after", "before", "when", "what", "who", "how", "why", "can",
    "will", "just", "than", "then", "them", "they", "his", "her", "she", "him",
}
_WORD = re.compile(r"[0-9A-Za-z\u0400-\u04FF]{3,}")
_DECISION = re.compile(
    r"\b(decided|decision|agreed|agreement|standing[\s-]+rule)\b|решил|договорил",
    re.I,
)
# "password is <token>" does not match the colon form in mask_text. Drop the token anyway.
_LEAK = re.compile(
    r"(?i)\b(?:passwords?|passwds?|secrets?|tokens?|api[\s_-]*keys?)\b\s*(?:is|was|are|=|:)?\s*\S+"
)


def scrub(text):
    """Secrets never land in the sidecar. Failures return an empty string."""
    if not text:
        return ""
    try:
        from app.memory_v2 import mask_text
        text = mask_text(text) or ""
    except Exception:
        text = text or ""
    return _LEAK.sub("[secret]", text)


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS spontaneous_job (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        topic TEXT,
        status TEXT,
        created_at REAL,
        ready_json TEXT,
        delivered_at REAL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS spontaneous_state (
        user TEXT PRIMARY KEY,
        turns INTEGER,
        last_topic TEXT,
        last_sched_turn INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS spontaneous_seen (
        user TEXT,
        ev TEXT,
        delivered_at REAL,
        PRIMARY KEY (user, ev)
    )""")


def user_key(uid):
    return hashlib.sha256((uid or "").encode()).hexdigest()[:16]


def tokens(text):
    """Content words in first-seen order. Stopwords drop. Order is kept."""
    out, seen = [], set()
    for w in _WORD.findall((text or "").lower()):
        if w in _STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def topic_of(text):
    return " ".join(tokens(text)[:8])


def _covers(tok, body):
    for b in body:
        if tok == b:
            return True
        if len(tok) >= 5 and len(b) >= 5 and (b.startswith(tok) or tok.startswith(b)):
            return True
    return False


def is_decision(text):
    return _DECISION.search(text or "") is not None


def score_text(topic, text, decision=None):
    tw = tokens(topic)
    if not tw:
        return 0.0
    bw = tokens(text)
    overlap = sum(1 for t in tw if _covers(t, bw)) / len(tw)
    decided = is_decision(text) if decision is None else bool(decision)
    # Only a decision clears the delivery threshold. A plain echo of the
    # current message stays below it, so the sidecar does not store the turn.
    if decided and overlap >= 0.34:
        return min(1.0, 0.55 + overlap)
    if decided and overlap == 0:
        return 0.0
    if decided:
        return overlap
    return min(overlap, 0.5)


def _sid(event_id):
    eid = event_id or ""
    return eid.split("::")[-1] if eid else ""


def _fact(text):
    fact = re.sub(r"\s+", " ", text or "").strip()
    if len(fact) > FACT_CHARS:
        fact = fact[:FACT_CHARS].rstrip() + " [cut]"
    return fact


def pick(topic, events, seen):
    ranked = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        sid = _sid(ev.get("event_id") or ev.get("ev") or "")
        if not sid or sid in seen:
            continue
        text = ev.get("text")
        if text is None:
            text = ((ev.get("essence") or "") + "\n" + (ev.get("raw_dialogue") or "")).strip()
        sc = score_text(topic, text, ev.get("decision") if "decision" in ev else None)
        if sc >= THRESHOLD:
            ranked.append((sc, sid, text))
    ranked.sort(key=lambda row: -row[0])
    out = []
    for sc, sid, text in ranked[:MAX_HITS]:
        fact = _fact(text)
        out.append({
            "ev": sid,
            "score": round(sc, 3),
            "fact": fact,
            "line": "recalled: %s [ev:%s]" % (fact, sid),
        })
    return out


def _state(conn, user):
    row = conn.execute(
        "SELECT turns, last_topic, last_sched_turn FROM spontaneous_state WHERE user=?",
        (user,),
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO spontaneous_state (user, turns, last_topic, last_sched_turn) VALUES (?,?,?,?)",
            (user, 0, "", 0),
        )
        return 0, "", 0
    return int(row[0] or 0), row[1] or "", int(row[2] or 0)


def deliver(conn, user):
    """Hand out jobs that were ready before this turn. Marks each ev seen."""
    seen = {r[0] for r in conn.execute("SELECT ev FROM spontaneous_seen WHERE user=?", (user,))}
    rows = conn.execute(
        "SELECT id, ready_json FROM spontaneous_job WHERE user=? AND status='ready' AND delivered_at IS NULL ORDER BY id",
        (user,),
    ).fetchall()
    lines = []
    now = time.time()
    for jid, raw in rows:
        try:
            payload = json.loads(raw or "[]")
        except Exception:
            payload = []
        if not isinstance(payload, list):
            payload = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            ev = item.get("ev") or ""
            line = item.get("line") or ""
            if not ev or ev in seen or not line:
                continue
            seen.add(ev)
            conn.execute(
                "INSERT OR REPLACE INTO spontaneous_seen (user, ev, delivered_at) VALUES (?,?,?)",
                (user, ev, now),
            )
            lines.append(line)
        conn.execute(
            "UPDATE spontaneous_job SET status='delivered', delivered_at=? WHERE id=?",
            (now, jid),
        )
    return lines


def on_turn(conn, topic="", events=None, l1_new=False, user="", messages=None):
    """Deliver ready hits, then maybe store a job for the following turn.

    The job created here is not delivered until the next on_turn. model_called
    is always false: this function does not open a model HTTP client.
    """
    ensure(conn)
    if events is None:
        events = messages or []
    clean_events = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        item = dict(ev)
        if item.get("text") is not None:
            item["text"] = scrub(item.get("text"))
        else:
            item["essence"] = scrub(item.get("essence") or "")
            item["raw_dialogue"] = scrub(item.get("raw_dialogue") or "")
        clean_events.append(item)
    events = clean_events
    user = user or ""
    lines = deliver(conn, user)
    turns, last_topic, last_sched = _state(conn, user)
    turns += 1
    topic_s = scrub(topic or "").strip()
    changed = bool(last_topic) and bool(topic_s) and topic_s != last_topic
    due = (turns - int(last_sched or 0)) >= EVERY or bool(l1_new) or changed
    scheduled = False
    if due and (topic_s or l1_new):
        seen = {r[0] for r in conn.execute("SELECT ev FROM spontaneous_seen WHERE user=?", (user,))}
        picked = pick(topic_s, events, seen)
        conn.execute(
            "INSERT INTO spontaneous_job (user, topic, status, created_at, ready_json, delivered_at) VALUES (?,?,?,?,?,NULL)",
            (user, topic_s, "ready", time.time(), json.dumps(picked, ensure_ascii=False)),
        )
        last_sched = turns
        scheduled = True
    conn.execute(
        "UPDATE spontaneous_state SET turns=?, last_topic=?, last_sched_turn=? WHERE user=?",
        (turns, topic_s or last_topic, last_sched, user),
    )
    conn.commit()
    return {
        "recalled": lines,
        "scheduled": scheduled,
        "turns": turns,
        "model_called": False,
    }


def maybe_rank_model(topic, events):
    """Optional cheap model. Not used by on_turn. Off unless the env flag is set."""
    flag = os.environ.get("SKV_SPONTANEOUS_MODEL", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return None
    try:
        from app.recall_later import _llm
        from app.memory_v2 import config
        cfg = config()
        cap = float(cfg.get("recall_later_max_cost_rub") or 3.0)
        blob = topic_of(topic)[:200]
        content, cost, _model = _llm(
            [{"role": "user", "content": "rank only, no new facts: " + blob}],
            60,
        )
        if cost and float(cost) > cap:
            return None
        return content
    except Exception:
        return None


def recent_events(uid, limit=8):
    """Last few dialogue rows from the account shelf. Failures return []."""
    if not uid:
        return []
    try:
        from app.memory_v2 import db_path
    except Exception:
        return []
    path = db_path(uid)
    if not path or not os.path.isfile(path):
        return []
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    except Exception:
        return []
    try:
        try:
            rows = conn.execute(
                "SELECT event_id, essence, raw_dialogue FROM event_metadata ORDER BY rowid DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        except Exception:
            return []
    finally:
        conn.close()
    out = []
    for eid, ess, raw in rows:
        text = scrub(((ess or "") + "\n" + (raw or "")).strip())
        out.append({"event_id": eid or "", "text": text, "decision": is_decision(text)})
    return out


def open_db():
    os.makedirs(os.path.dirname(SIDECAR), exist_ok=True)
    conn = sqlite3.connect(SIDECAR, timeout=10)
    ensure(conn)
    return conn


def push_into(result, uid, user_message="", l1_new=False):
    """Attach recalled lines when any are ready. Empty stays off the payload."""
    if not isinstance(result, dict) or not uid:
        return result
    try:
        events = recent_events(uid)
        conn = open_db()
        try:
            out = on_turn(
                conn,
                topic=topic_of(scrub(user_message)),
                events=events,
                l1_new=bool(l1_new),
                user=user_key(uid),
            )
        finally:
            conn.close()
        lines = [ln for ln in (out.get("recalled") or []) if ln][:MAX_HITS]
        if lines:
            result["recalled"] = lines
    except Exception:
        pass
    return result
