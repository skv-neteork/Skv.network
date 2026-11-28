"""T96 items 17c-17g. Pure helpers. No app import at module level.

17c skips archive search for a strict empty ack (previous answer did not ask,
under 15 minutes) and for a short directive. search_skipped says which.
A real search_as wins. A dash stays the explicit skip.
17d penalises this actor's own last 20 events in this session (score * 0.35).
An exact token in the query that is also in the fact lifts the penalty.
Other actors stay at full score. The filter is off for a compacted context,
catch-up, a new session, and a stateless client.
17e(a) builds a mini step_zero when the agent sends context_compacted, repeats
step_zero, or sends an older seal. 17e(b) is not implemented.
17f writes a typed changelog into while_away. More than 5 events collapse.
17g attaches the A/B search hint when facts are empty or weak.
Normal-path size is a token tier (base 600, strong 1200, new topic 6000).
"""
import contextvars
import hashlib
import json
import os
import re
import time
from datetime import datetime

_META = contextvars.ContextVar("skv_diet17_meta", default=None)

EMPTY_WORDS = frozenset({
    "ok", "ок", "ага", "да", "спс", "спасибо", "понял", "ясно", "принято",
})
ALWAYS_VERBS = frozenset({
    "стоп", "стой", "делай", "катим", "отмена", "жди", "проверь",
})
# Class B: at most 4 words. No archive search; return the doing row, the last
# two turns, and the git/deploy guard.
DIRECTIVES = frozenset({
    "нет", "стоп", "отмена", "откат", "подожди", "выкатывай", "пушь", "пуш", "удали",
    "продолжай", "продолжи",
    "stop", "rollback", "deploy",
})
NEW_TOPIC_PHRASES = (
    "теперь займемся",
    "другая тема",
    "переключимся",
    "now let's",
    "new topic",
)
GUARD_LINE = (
    "GIT/DEPLOY: no push, no force-push, no restart, no user-data delete. "
    "Confirm a hard-to-undo action first."
)
HINT_LINE = (
    "%s; A) memory_search(%s) now: fast, free; "
    "B) memory_recall_later(%s): deep, ~10-30 s, cheap model, result on a later turn"
)
ASK_MARKS = ("подтверди", "выкатываем", "какой вариант", "ок?", "делать?")
REASK = (
    ("я не про это", "not_this"),
    ("ты забыл", "forgot"),
    ("посмотри выше", "look_above"),
)
OWN_FRESH_N = 20
SKIP_MINUTES = 15
DUTY_QUOTA = 250
BOARD_QUOTA = 350
FACT_QUOTA = 500
DELTA_QUOTA = 400
DELTA_LONG = 1000
BASE_TOTAL = 1500
FRESH_PENALTY = 0.35
WEAK_SCORE = 0.15
TOKEN_BASE = 600
TOKEN_STRONG = 1200
TOKEN_TOPIC = 6000
STRONG_SCORE = 0.45
LEX_TOPIC = 0.12
RECALL_GAP_S = 300
# Token shares of the 600 base: 250/350/500/400 over 1500.
TOKEN_DUTY = 100
TOKEN_BOARD = 140
TOKEN_FACT = 200
TOKEN_DELTA = 160
TOKEN_DELTA_LONG = 250

_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\u200d\uFE0F"
    "]+"
)
_SEAL_N = re.compile(r"SKV \| #(\d+)")
_FILE = re.compile(r"[\w.-]+\.(?:py|md|txt|html|json|docx|sh|js|ts|yml|yaml)\b", re.I)
_TID = re.compile(r"\bT\d+\b", re.I)
_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
_CYR = re.compile(r"[а-яё]", re.I)
_EXACT = re.compile(
    r"(?:[A-Za-z]:\\[^\s]+|/[A-Za-z0-9_./-]+|\bT\d+\b|\b\d[\d.]*\b|[A-Za-z][\w./-]{2,})"
)
_STOP = frozenset({
    "this", "that", "with", "from", "have", "what", "when", "where", "which",
    "это", "этот", "эта", "как", "что", "для", "или", "the", "and", "про",
})


def set_meta(meta):
    _META.set(dict(meta or {}))


def get_meta():
    meta = _META.get()
    return meta if isinstance(meta, dict) else {}


def merge_meta(**kw):
    meta = dict(get_meta())
    meta.update(kw)
    set_meta(meta)
    return meta


def gap_hours_limit():
    raw = os.environ.get("SKV_CATCHUP_GAP_H", "3")
    try:
        n = float(raw)
    except (TypeError, ValueError):
        n = 3.0
    return n if n > 0 else 3.0


def _blen(text):
    return len(str(text or "").encode("utf-8"))


def _clip_utf8(text, n):
    raw = str(text or "").encode("utf-8")
    if len(raw) <= n:
        return str(text or "")
    return raw[: max(0, n)].decode("utf-8", "ignore")


def _words(msg):
    return [w.replace("ё", "е") for w in _WORD.findall((msg or "").lower())]


def is_emoji_only(msg):
    raw = (msg or "").strip()
    if not raw or not _EMOJI.search(raw):
        return False
    left = _EMOJI.sub("", raw)
    return not left.strip()


def is_always_meaningful(msg):
    raw = msg or ""
    if re.search(r"\d", raw):
        return True
    if _TID.search(raw) or _FILE.search(raw):
        return True
    words = _words(raw)
    if any(w in ALWAYS_VERBS for w in words):
        return True
    if "не" in words and ("надо" in words or "трогай" in words):
        return True
    return False


def is_strict_empty(msg):
    """Emoji only, or only the ack words. A verb, digit, or symbol is not empty."""
    raw = (msg or "").strip()
    if not raw or is_always_meaningful(raw):
        return False
    if is_emoji_only(raw):
        return True
    if re.search(r"[^\w\s]", raw, flags=re.U):
        return False
    words = _words(raw)
    if not words:
        return False
    return all(w in EMPTY_WORDS for w in words)


def is_directive(msg):
    """Class B: four words or fewer, and a negation or one of the action verbs."""
    raw = (msg or "").strip()
    if not raw or is_strict_empty(raw) or is_emoji_only(raw):
        return False
    words = _words(raw)
    if not words or len(words) > 4:
        return False
    if any(w in DIRECTIVES for w in words):
        return True
    if "не" in words and any(w in ("надо", "трогай", "делай") for w in words):
        return True
    return False


def has_cyrillic(text):
    return bool(_CYR.search(text or ""))


def estimate_tokens(text):
    """Cyrillic chars / 1.8 plus every other char / 4. No tokenizer."""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, default=str)
    cyr = other = 0
    for ch in text or "":
        low = ch.lower()
        if ("а" <= low <= "я") or low == "ё":
            cyr += 1
        else:
            other += 1
    return (cyr / 1.8) + (other / 4.0)


def exact_tokens(query):
    """Digits, latin tokens, paths, and T-ids. Used to lift the fresh penalty."""
    out = []
    for m in _EXACT.finditer(query or ""):
        tok = m.group(0).strip(".,:;\"'").lower()
        if tok and tok not in out:
            out.append(tok)
    return out


def _content_words(text):
    return [w for w in _words(text) if len(w) > 3 and w not in _STOP]


def search_as_text(search_as):
    """Agent gloss that is not the dash. Empty when the agent sent nothing or '-'."""
    if search_as is None:
        return ""
    if isinstance(search_as, (list, tuple)):
        parts = []
        for x in search_as:
            t = str(x).strip()
            if t and t != "-":
                parts.append(t)
        return " ".join(parts).strip()
    s = str(search_as).strip()
    if not s or s == "-":
        return ""
    return s


def is_dash(search_as):
    if search_as is None:
        return False
    if isinstance(search_as, (list, tuple)):
        vals = [str(x).strip() for x in search_as if str(x).strip()]
        return bool(vals) and all(v == "-" for v in vals)
    return str(search_as).strip() == "-"


def answer_asks(answer):
    """The previous answer ends in a question or a choice."""
    text = (answer or "").strip()
    if not text:
        return False
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or "SKV |" in s or "🔐" in s:
            continue
        lines.append(s)
    tail = " ".join(lines[-2:]) if lines else text
    end = tail.lower().replace("ё", "е")[-80:].strip()
    if end.endswith("?") or end.endswith("？"):
        return True
    if re.search(r"\[y/n\]|\(y/n\)", end):
        return True
    return any(mark in end for mark in ASK_MARKS)


def anchor_query(answer, msg, n=200):
    """Last ~200 characters of the previous answer plus the user line."""
    text = (answer or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and "SKV |" not in ln and "🔐" not in ln]
    body = " ".join(lines) if lines else text
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > n:
        body = body[-n:]
    user = re.sub(r"\s+", " ", (msg or "").strip())
    return (body + " " + user).strip()[:500]


def _shortish(msg):
    raw = (msg or "").strip()
    if len(raw) <= 40:
        return True
    return len(raw.split()) <= 6


def pick_prev_answer(answer, last_final=""):
    """The agent's previous answer for the anchor rule: a non-empty `answer` wins, else the last saved final."""
    a = str(answer or "").strip()
    return a[:4000] if a else str(last_final or "")


def apply_17c(plan, msg, search_as, prev_answer=None, minutes=None):
    """Return a plan. A filled gloss and an explicit dash are left as they are.

    Anchor replaces the query only for a short, empty, or command line that
    follows a question. A long line keeps the query the planner already chose.
    A class-B directive does not search the archive.
    """
    plan = dict(plan or {})
    plan["search_skipped"] = False
    plan["skip_reason"] = ""
    if is_dash(search_as):
        plan["search_skipped"] = True
        plan["skip_reason"] = "explicit_dash"
        return plan
    if search_as_text(search_as):
        return plan
    asks = answer_asks(prev_answer or "")
    empty = is_strict_empty(msg)
    meaningful = is_always_meaningful(msg)
    known = minutes is not None
    fresh = known and float(minutes) < SKIP_MINUTES
    if is_directive(msg):
        plan["mode"] = "directive"
        plan["query"] = ""
        plan["search_as"] = []
        plan["context"] = []
        plan["revise"] = False
        plan["duty"] = False
        plan["search_skipped"] = True
        plan["skip_reason"] = "directive"
        return plan
    if empty and not asks and fresh:
        plan["mode"] = "auto_skip"
        plan["query"] = ""
        plan["search_as"] = []
        plan["context"] = []
        plan["revise"] = False
        plan["duty"] = False
        plan["search_skipped"] = True
        plan["skip_reason"] = "empty_ack<15m"
        return plan
    if asks and (empty or meaningful or _shortish(msg)):
        plan["mode"] = "anchor"
        plan["query"] = anchor_query(prev_answer, msg)
        plan["search_as"] = []
        plan["revise"] = False
        plan["duty"] = False
        return plan
    if meaningful and plan.get("mode") in ("slice", "skip", "auto_skip", "directive"):
        plan["mode"] = "plain"
        plan["query"] = (msg or "")[:500]
        plan["revise"] = False
        plan["duty"] = False
        return plan
    if empty and known and not fresh and plan.get("mode") in ("slice", "skip", "auto_skip", "directive"):
        plan["mode"] = "plain"
        plan["query"] = (msg or "")[:500]
        plan["revise"] = False
        plan["duty"] = False
    return plan


def gap_hours(prev, now=None):
    if prev is None or prev == "":
        return None
    try:
        if isinstance(prev, (int, float)) and not isinstance(prev, bool):
            moment = time.time() if now is None else now
            if isinstance(moment, datetime):
                moment = moment.timestamp()
            return max(0.0, (float(moment) - float(prev)) / 3600.0)
        s = str(prev).replace("T", " ")[:19]
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if isinstance(now, datetime):
            cur = now.replace(tzinfo=None)
        elif isinstance(now, (int, float)) and not isinstance(now, bool):
            cur = datetime.utcfromtimestamp(now)
        else:
            cur = datetime.utcnow()
        return max(0.0, (cur - dt).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def gap_minutes(prev, now=None):
    hours = gap_hours(prev, now)
    if hours is None:
        return None
    return hours * 60.0


def _lookup_actor(conn, token_hash):
    if conn is None or not token_hash:
        return "", "", ""
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "agents" not in tabs:
            return "", "", ""
        row = conn.execute(
            "SELECT id, last_seen_at, session_id FROM agents WHERE token_hash=? ORDER BY rowid DESC LIMIT 1",
            (token_hash,),
        ).fetchone()
    except Exception:
        return "", "", ""
    if not row:
        return "", "", ""
    return row[0] or "", row[1] or "", row[2] or ""


def _session_count(conn, actor, session):
    if conn is None or not actor or not session:
        return None
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
        if "actor_agent_id" not in cols or "session_id" not in cols:
            return None
        row = conn.execute(
            "SELECT COUNT(*) FROM event_metadata WHERE actor_agent_id=? AND session_id=?",
            (actor, session),
        ).fetchone()
    except Exception:
        return None
    return int(row[0] or 0) if row else 0


def load_own_fresh(conn, actor, session, n=OWN_FRESH_N):
    """Event ids of this actor in this session, last n turns. Other actors are not included."""
    out = set()
    if conn is None or not actor or not session:
        return out
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
        if "actor_agent_id" not in cols or "session_id" not in cols or "event_id" not in cols:
            return out
        rows = conn.execute(
            "SELECT event_id FROM event_metadata WHERE session_id=? AND actor_agent_id=? "
            "ORDER BY rowid DESC LIMIT ?",
            (session, actor, int(n)),
        ).fetchall()
    except Exception:
        return out
    for row in rows:
        eid = row[0] or ""
        if not eid:
            continue
        out.add(eid)
        out.add(str(eid).split("::")[-1])
    return out


def own_fresh_ids(events, actor, session, n=OWN_FRESH_N):
    """Same rule on plain rows. events need id, actor, session, and seq."""
    if not actor or not session:
        return set()
    rows = [e for e in (events or []) if e.get("actor") == actor and e.get("session") == session]
    rows.sort(key=lambda e: e.get("seq") or 0, reverse=True)
    out = set()
    for e in rows[: int(n)]:
        eid = str(e.get("id") or "")
        if not eid:
            continue
        out.add(eid)
        out.add(eid.split("::")[-1])
    return out


def fresh_filter_enabled(context_compacted=False, catchup=False, new_session=False, stateless=False):
    if context_compacted or catchup or new_session or stateless:
        return False
    return True


def drop_own_fresh(facts, drop_ids):
    """Legacy hard drop. The live path uses penalize_own_fresh."""
    ban = {str(x) for x in (drop_ids or []) if x}
    ban |= {str(x).split("::")[-1] for x in ban}
    kept = []
    for f in facts or []:
        if not isinstance(f, dict):
            kept.append(f)
            continue
        ev = str(f.get("ev") or f.get("event_id") or "")
        if ev in ban or ev.split("::")[-1] in ban:
            continue
        kept.append(f)
    return kept


def penalize_own_fresh(facts, drop_ids, query=""):
    """score * 0.35 for this actor's fresh events. An exact token in both lifts it.

    Events that are not in drop_ids, including other actors, keep their score.
    """
    ban = {str(x) for x in (drop_ids or []) if x}
    ban |= {str(x).split("::")[-1] for x in ban}
    tokens = exact_tokens(query)
    out = []
    for f in facts or []:
        if not isinstance(f, dict):
            out.append(f)
            continue
        ev = str(f.get("ev") or f.get("event_id") or "")
        if ev not in ban and ev.split("::")[-1] not in ban:
            out.append(f)
            continue
        text = str(f.get("fact") or f.get("summary") or "").lower()
        if tokens and any(tok in text for tok in tokens):
            out.append(f)
            continue
        row = dict(f)
        try:
            row["score"] = float(row.get("score") or 0) * FRESH_PENALTY
        except (TypeError, ValueError):
            row["score"] = 0.0
        row["fresh_penalty"] = FRESH_PENALTY
        out.append(row)
    return out


def overlay(plan, msg, search_as, conn=None):
    """Apply 17c and remember 17d ids on the meta. No-op unless set_meta(on=True)."""
    meta = get_meta()
    if not meta.get("on"):
        return plan
    prev = meta.get("prev_answer") or ""
    minutes = meta.get("minutes")
    actor = meta.get("actor") or ""
    if meta.get("prev_seen_at"):
        minutes = gap_minutes(meta.get("prev_seen_at"))
    elif conn is not None and meta.get("token_hash"):
        found, seen, _sess = _lookup_actor(conn, meta.get("token_hash"))
        if found and not actor:
            actor = found
            merge_meta(actor=actor)
        if seen:
            minutes = gap_minutes(seen)
    if minutes is None and meta.get("minutes") is not None:
        minutes = meta.get("minutes")
    plan = apply_17c(plan, msg, search_as, prev, minutes)
    session = meta.get("session") or ""
    if not actor and conn is not None and meta.get("token_hash"):
        actor, _seen, _sess = _lookup_actor(conn, meta.get("token_hash"))
        if actor:
            merge_meta(actor=actor)
    count = _session_count(conn, actor, session)
    prev_session = meta.get("prev_session") or ""
    if prev_session and session and prev_session != session:
        new_session = True
    elif count is None:
        new_session = True
    else:
        new_session = count == 0
    compacted = bool(meta.get("context_compacted"))
    stateless = bool(meta.get("stateless"))
    catchup = bool(meta.get("catchup"))
    on = fresh_filter_enabled(
        context_compacted=compacted, catchup=catchup, new_session=new_session, stateless=stateless,
    )
    ids = []
    if on:
        ids = sorted(load_own_fresh(conn, actor, session))
    recent_texts = _recent_briefs(conn, actor, session) if conn is not None else []
    trig, _sim = topic_trigger(msg, search_as_text(search_as), recent_texts)
    lines = []
    if plan.get("mode") == "directive":
        lines = [h.get("summary") or "" for h in directive_hits(conn, session)]
    merge_meta(
        new_session=new_session,
        fresh_off=not on,
        own_fresh_ids=ids,
        auto_skip=plan.get("mode") == "auto_skip",
        minutes=minutes,
        search_skipped=bool(plan.get("search_skipped")),
        skip_reason=plan.get("skip_reason") or "",
        directive=plan.get("mode") == "directive",
        directive_lines=lines,
        recent_texts=recent_texts,
        topic_trigger=trig,
    )
    reset = compacted
    if conn is not None and seal_older(meta.get("last_seal"), server_seal_of(conn, actor)):
        reset = True
        print("[17f-reset] signal=old_seal", flush=True)
    if reset and conn is not None:
        plan = dict(plan)
        plan["mini_step_zero"] = load_mini_text(conn, session, actor)
    try:
        note_reask(msg)
    except Exception:
        pass
    return plan


def log_skip(reason, msg):
    clip = re.sub(r"\s+", " ", msg or "")[:40]
    print("[17c-skip] reason=%s n=%d text=%s" % (reason or "empty", len(msg or ""), clip), flush=True)


def board_hits(conn):
    """One top board row as an active-slice hit. Duties are merged later into the 500 B quota."""
    title, status, updated = _top_board(conn)
    if not title:
        return []
    text = "BOARD %s: %s" % (status or "open", title)
    return [{
        "event_id": "board:top",
        "time": updated or "",
        "score": 1.0,
        "summary": text[:180],
        "source": "active_slice",
        "active_slice": True,
    }]


def _last_turns(conn, session, n=2):
    """Short lines from the latest session rows. Bodies are clipped."""
    if conn is None:
        return []
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
    except Exception:
        return []
    if "raw_dialogue" not in cols or "event_id" not in cols:
        return []
    where = " WHERE session_id=?" if "session_id" in cols and session else ""
    args = (session, int(n)) if where else (int(n),)
    actor_sql = ", actor_agent_id" if "actor_agent_id" in cols else ""
    try:
        rows = conn.execute(
            "SELECT event_id, raw_dialogue%s FROM event_metadata%s ORDER BY rowid DESC LIMIT ?"
            % (actor_sql, where),
            args,
        ).fetchall()
    except Exception:
        return []
    out = []
    for row in rows:
        who = row[2] if actor_sql else "?"
        out.append("TURN %s: %s" % (who or "?", _brief(row[1] or "", 80)))
    return out


def directive_hits(conn, session=""):
    """Doing row, last two turns, and the git/deploy guard. No archive search."""
    hits = list(board_hits(conn))
    for i, line in enumerate(_last_turns(conn, session, 2)):
        hits.append({
            "event_id": "turn:recent:%d" % i,
            "time": "",
            "score": 1.0,
            "summary": line[:180],
            "source": "active_slice",
            "active_slice": True,
        })
    hits.append({
        "event_id": "guard:git",
        "time": "",
        "score": 1.0,
        "summary": GUARD_LINE,
        "source": "guardrail",
        "active_slice": True,
    })
    return hits


def _recent_briefs(conn, actor, session, n=5):
    if conn is None or not actor:
        return []
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
    except Exception:
        return []
    if "raw_dialogue" not in cols or "actor_agent_id" not in cols:
        return []
    where = "actor_agent_id=?"
    args = [actor]
    if "session_id" in cols and session:
        where += " AND session_id=?"
        args.append(session)
    args.append(int(n))
    try:
        rows = conn.execute(
            "SELECT raw_dialogue FROM event_metadata WHERE %s ORDER BY rowid DESC LIMIT ?" % where,
            args,
        ).fetchall()
    except Exception:
        return []
    return [_brief(r[0] or "", 160) for r in rows if r and r[0]]


def topic_trigger(msg, search_as="", recent_texts=None):
    """Explicit phrase, or low overlap with this actor's last turns. Logs a trigger."""
    blob = ((search_as or "") + " " + (msg or "")).lower().replace("ё", "е")
    for phrase in NEW_TOPIC_PHRASES:
        if phrase in blob:
            print("[17-topic] trigger=phrase", flush=True)
            return "phrase", 1.0
    q_words = _content_words(search_as or msg)
    recent = [t for t in (recent_texts or []) if t][:5]
    if len(q_words) < 3 or not recent:
        return "", 1.0
    cent = set()
    for text in recent:
        cent.update(_content_words(text))
    if not cent:
        return "", 1.0
    sim = len(set(q_words) & cent) / float(len(set(q_words)))
    if sim < LEX_TOPIC:
        print("[17-topic] trigger=lex sim=%.3f" % sim, flush=True)
        return "lex", sim
    return "", sim


def facts_are_weak(facts, floor=WEAK_SCORE):
    """Empty, or every present score is under the floor. Unscored rows are not weak.

    An active-slice row is the compact state, not a missed search.
    """
    rows = [f for f in (facts or []) if isinstance(f, dict)]
    if not rows:
        return True
    best = None
    saw = False
    for f in rows:
        if f.get("active_slice"):
            return False
        if "score" not in f or f.get("score") is None:
            continue
        try:
            score = float(f.get("score") or 0)
        except (TypeError, ValueError):
            continue
        saw = True
        if best is None or score > best:
            best = score
    if not saw:
        return False
    return best < floor


def facts_are_strong(facts, query=""):
    tokens = exact_tokens(query)
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        text = str(f.get("fact") or f.get("summary") or "")
        try:
            score = float(f.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score >= STRONG_SCORE:
            return True
        low = text.lower()
        if tokens and any(tok in low for tok in tokens):
            return True
    return False


def attach_facts_hint(resp, message="", skipped=False):
    """One English line whenever facts are empty or weak, including after a skip."""
    if not isinstance(resp, dict):
        return resp
    weak = facts_are_weak(resp.get("facts"))
    if not weak and not skipped:
        return resp
    q = re.sub(r"\s+", " ", (message or "").strip())[:120]
    shown = json.dumps(q, ensure_ascii=False)
    label = "nothing found" if skipped or not resp.get("facts") else "weak found"
    resp["facts_note"] = HINT_LINE % (label, shown, shown)
    resp["deep_search_call"] = "memory_recall_later(query=%s)" % shown
    return resp


def weak_recall_due(facts_weak, meaningful, last_job_age, searched, skipped):
    """Auto recall only when search ran, facts are weak, and the agent did not start one."""
    if skipped or searched or not facts_weak or not meaningful:
        return False
    if last_job_age is not None and float(last_job_age) < RECALL_GAP_S:
        return False
    return True


def _top_board(conn):
    if conn is None:
        return "", "", ""
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "board_items" not in tabs:
            return "", "", ""
        row = conn.execute(
            "SELECT item_id, title, status, updated_at FROM board_items "
            "WHERE coalesce(removed,0)=0 AND status IN ('doing','todo') "
            "ORDER BY CASE status WHEN 'doing' THEN 0 ELSE 1 END, updated_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return "", "", ""
    if not row:
        return "", "", ""
    return (row[1] or row[0] or ""), (row[2] or ""), (row[3] or "")


def fit_skip_facts(facts, board, duties, budget=FACT_QUOTA):
    """Top board plus duty lines, inside the facts quota."""
    lines = []
    for f in facts or []:
        if isinstance(f, dict) and (f.get("fact") or f.get("summary")):
            lines.append(str(f.get("fact") or f.get("summary")))
    if not lines and board:
        if isinstance(board, list) and board:
            b0 = board[0]
            if isinstance(b0, dict):
                lines.append("BOARD %s: %s" % (b0.get("status") or "open", b0.get("title") or b0.get("item_id") or ""))
            else:
                lines.append("BOARD: %s" % b0)
        elif isinstance(board, str):
            lines.append("BOARD: " + board)
    for d in duties or []:
        if isinstance(d, dict):
            lines.append(str(d.get("note") or d.get("id") or "")[:120])
        else:
            lines.append(str(d)[:120])
    out = []
    used = 0
    for i, line in enumerate(lines):
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        nxt = _blen(line) + (1 if out else 0)
        if out and used + nxt > budget:
            break
        if not out and _blen(line) > budget:
            line = _clip_utf8(line, budget)
            nxt = _blen(line)
        out.append({
            "ev": "board:top" if i == 0 else "duty",
            "fact": line,
            "time": "",
            "active_slice": True,
        })
        used += nxt
    return out


def _brief(raw, n=80):
    text = re.sub(r"\s+", " ", raw or "").strip()
    i = text.find(" A:")
    if i >= 0:
        text = text[i + 1:]
    return text[:n]


def load_mini_text(conn, session, actor, n=25):
    """Last session turns, the doing row, the fresh L1, and critical lines."""
    turns, board, l1, criticals = [], "", "", []
    if conn is None:
        return ""
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return ""
    if "event_metadata" in tabs:
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
        except Exception:
            cols = set()
        actor_sql = ", actor_agent_id" if "actor_agent_id" in cols else ""
        where = " WHERE session_id=?" if "session_id" in cols and session else ""
        args = (session, int(n)) if where else (int(n),)
        try:
            rows = conn.execute(
                "SELECT event_id, raw_dialogue%s FROM event_metadata%s ORDER BY rowid DESC LIMIT ?" % (actor_sql, where),
                args,
            ).fetchall()
        except Exception:
            rows = []
        for row in rows:
            eid = row[0] or ""
            raw = row[1] or ""
            who = row[2] if actor_sql else (actor or "")
            if "CRITICAL:" in raw or str(eid).split("::")[-1].startswith("critical_"):
                criticals.append(_brief(raw, 100))
            turns.append({"actor": who or "?", "ev": eid, "text": _brief(raw, 80)})
    title, status, _ts = _top_board(conn)
    if title:
        board = "%s %s" % (status or "doing", title)
    if "summary_l1" in tabs:
        try:
            row = conn.execute(
                "SELECT topic, summary_text FROM summary_l1 ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        except Exception:
            row = None
        if row:
            l1 = ((row[0] or "") + " " + (row[1] or "")).strip()
    return mini_step_zero(turns, board, l1, criticals[:3], n=n).get("text") or ""


def mini_step_zero(turns, board, l1, criticals, n=25):
    lines = []
    if board:
        lines.append("BOARD doing: " + re.sub(r"\s+", " ", board)[:120])
    for t in list(turns or [])[: int(n)]:
        who = t.get("actor") or "?"
        ev = str(t.get("ev") or "").split("::")[-1]
        text = re.sub(r"\s+", " ", t.get("text") or "")[:80]
        if ev:
            lines.append("%s: %s [ev:%s]" % (who, text, ev))
        elif text:
            lines.append("%s: %s" % (who, text))
    if l1:
        lines.append("L1: " + re.sub(r"\s+", " ", l1)[:160])
    for c in criticals or []:
        lines.append("CRITICAL: " + re.sub(r"\s+", " ", c)[:120])
    return {"text": "\n".join(lines), "n": len(lines)}


def seal_num(value):
    if value is None or value is False:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    m = _SEAL_N.search(s)
    if m:
        return int(m.group(1))
    m = re.search(r"#(\d+)", s)
    return int(m.group(1)) if m else None


def seal_older(client, server):
    a, b = seal_num(client), seal_num(server)
    if a is None or b is None:
        return False
    return a < b


def server_seal_of(conn, actor):
    if conn is None or not actor:
        return None
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
        if "actor_agent_id" not in cols or "raw_dialogue" not in cols:
            return None
        row = conn.execute(
            "SELECT raw_dialogue FROM event_metadata WHERE actor_agent_id=? ORDER BY rowid DESC LIMIT 1",
            (actor,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    nums = [int(x) for x in _SEAL_N.findall(row[0] or "")]
    return max(nums) if nums else None


def catchup_due(gap_h, client_seal, server_seal, n_new, gap_default=None):
    """Gap at or over the threshold, or an older client seal, and only when something new exists."""
    if not n_new:
        return False
    limit = gap_hours_limit() if gap_default is None else gap_default
    time_gap = gap_h is not None and gap_h >= limit
    return bool(time_gap or seal_older(client_seal, server_seal))


def _delta_seg(item):
    kind = item.get("kind") or "AGENT"
    ev = str(item.get("ev") or "").split("::")[-1]
    actor = item.get("actor") or "?"
    text = re.sub(r"\s+", " ", item.get("text") or "").strip()
    if kind == "BOARD":
        seg = "BOARD: %s" % text
        if item.get("actor"):
            seg += " (%s)" % actor
    elif kind == "CRITICAL":
        seg = "CRITICAL: %s" % text
    else:
        seg = "AGENT(%s): %s" % (actor, text)
    if ev:
        seg += " [ev:%s]" % ev
    return seg



def _delta_hours(gap_h):
    """Whole hours for the [DELTA +Nh] head. Half rounds up (8.5 -> 9), not banker's rounding."""
    x = float(gap_h or 0)
    if x < 0:
        x = 0.0
    return int(x + 0.5)


def _overflow_delta(rows, gap_h, since, budget):
    """More than 5 events: one L1 line, the board diff, new critical, and a count."""
    hours = _delta_hours(gap_h)
    head = "[DELTA +%dh]" % hours
    l1 = ""
    board = ""
    crit = ""
    for it in rows:
        kind = it.get("kind")
        if kind == "L1" and not l1:
            l1 = re.sub(r"\s+", " ", it.get("text") or "").strip()[:120]
        elif kind == "BOARD" and not board:
            board = re.sub(r"\s+", " ", it.get("text") or "").strip()[:80]
        elif kind == "CRITICAL" and not crit:
            crit = re.sub(r"\s+", " ", it.get("text") or "").strip()[:80]
    parts = [head]
    if l1:
        parts.append("L1: " + l1)
    if board:
        parts.append("BOARD: " + board)
    if crit:
        parts.append("CRITICAL: " + crit)
    day = (since or "")[:10] or "the gap"
    parts.append("+%d events, memory_search(since=%s)" % (len(rows), day))
    text = " ".join(parts)
    if _blen(text) <= budget:
        return text
    return _clip_utf8(text, budget)


def format_delta(items, gap_h, budget=None, since=""):
    """Newest first. More than 5 events collapse. A long gap may use ~1 KB."""
    rows = list(items or [])
    long = (gap_h or 0) >= 24 or len(rows) > 12
    if budget is None:
        budget = DELTA_LONG if long else DELTA_QUOTA
    if len(rows) > 5:
        return _overflow_delta(rows, gap_h, since, budget)
    hours = _delta_hours(gap_h)
    head = "[DELTA +%dh] " % hours
    parts = [_delta_seg(it) for it in rows]
    body = head + " / ".join(parts)
    if _blen(body) <= budget:
        return body
    return _overflow_delta(rows, gap_h, since, budget)


def load_delta_items(conn, actor, since_iso, limit=40):
    """Other actors, board changes, and critical rows after since_iso. Newest first."""
    items = []
    if conn is None or not since_iso:
        return items
    since = str(since_iso)[:19]
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return items
    if "room_events" in tabs:
        try:
            rows = conn.execute(
                "SELECT event_id, actor_agent_id, ev_kind, gist, created_at FROM room_events "
                "WHERE created_at > ? AND actor_agent_id IS NOT NULL AND actor_agent_id != ? "
                "ORDER BY id DESC LIMIT ?",
                (since, actor or "", int(limit)),
            ).fetchall()
        except Exception:
            rows = []
        for eid, who, kind, gist, ts in rows:
            k = "CRITICAL" if kind in ("human_directive",) else "AGENT"
            items.append({
                "kind": k, "actor": who or "", "text": (gist or kind or "turn")[:80],
                "ev": eid or "", "ts": ts or "",
            })
    if "board_history" in tabs:
        try:
            rows = conn.execute(
                "SELECT item_id, text, ts FROM board_history WHERE ts > ? ORDER BY id DESC LIMIT ?",
                (since, int(limit)),
            ).fetchall()
        except Exception:
            rows = []
        for iid, text, ts in rows:
            items.append({
                "kind": "BOARD", "actor": "",
                "text": "%s %s" % (iid, re.sub(r"\s+", " ", text or "")[:60]),
                "ev": "board:%s" % iid, "ts": ts or "",
            })
    if "board_items" in tabs and not any(i["kind"] == "BOARD" for i in items):
        try:
            rows = conn.execute(
                "SELECT item_id, title, status, updated_at FROM board_items "
                "WHERE coalesce(removed,0)=0 AND updated_at > ? ORDER BY updated_at DESC LIMIT 5",
                (since,),
            ).fetchall()
        except Exception:
            rows = []
        for iid, title, status, ts in rows:
            items.append({
                "kind": "BOARD", "actor": "",
                "text": "%s ->%s" % (title or iid, status or ""),
                "ev": "board:%s" % iid, "ts": ts or "",
            })
    if "event_metadata" in tabs:
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")}
        except Exception:
            cols = set()
        if "time_str" in cols and "raw_dialogue" in cols:
            actor_col = "actor_agent_id" in cols
            sql = "SELECT event_id, time_str, raw_dialogue"
            if actor_col:
                sql += ", actor_agent_id"
            sql += " FROM event_metadata WHERE time_str > ? ORDER BY rowid DESC LIMIT ?"
            try:
                rows = conn.execute(sql, (since, int(limit))).fetchall()
            except Exception:
                rows = []
            for row in rows:
                eid, ts, raw = row[0], row[1], row[2] or ""
                who = row[3] if actor_col and len(row) > 3 else ""
                if who and actor and who == actor:
                    continue
                if "CRITICAL:" in raw or str(eid).split("::")[-1].startswith("critical_"):
                    items.append({
                        "kind": "CRITICAL", "actor": who or "", "text": _brief(raw, 80),
                        "ev": eid or "", "ts": ts or "",
                    })
                elif who and who != actor:
                    items.append({
                        "kind": "AGENT", "actor": who, "text": _brief(raw, 80),
                        "ev": eid or "", "ts": ts or "",
                    })
    items.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    seen, out = set(), []
    for it in items:
        key = it.get("ev") or it.get("text")
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= int(limit):
            break
    return out


def catchup_text(conn, who, client_seal="", now=None):
    """Typed changelog, or '' when the gap has nothing new. Does not write."""
    if not isinstance(who, dict):
        return ""
    prev = who.get("prev_seen_at") or ""
    actor = who.get("actor_id") or ""
    gap_h = gap_hours(prev, now)
    items = load_delta_items(conn, actor, prev) if prev else []
    server = server_seal_of(conn, actor)
    if not catchup_due(gap_h, client_seal, server, len(items)):
        return ""
    long = (gap_h or 0) >= 24 or len(items) > 12
    text = format_delta(
        items, gap_h or 0, budget=DELTA_LONG if long else DELTA_QUOTA, since=str(prev or ""),
    )
    print("[17f-catchup] gap_h=%.1f n=%d bytes=%d" % (gap_h or 0, len(items), _blen(text)), flush=True)
    try:
        merge_meta(catchup=True, long_gap=long)
    except Exception:
        pass
    return text


def reask_tag(msg):
    low = (msg or "").lower().replace("ё", "е")
    for phrase, tag in REASK:
        if phrase in low:
            return tag
    return ""


def note_reask(msg, path=None):
    """Count a re-ask phrase. The log line is the tag and the counter, not the message."""
    tag = reask_tag(msg)
    if not tag:
        return 0
    path = path or os.environ.get("SKV_REASK_PATH") or "/data/skv/metadata_store/reask_count.txt"
    n = 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cur = 0
        if os.path.isfile(path):
            with open(path) as fh:
                cur = int(fh.read().strip() or "0")
        n = cur + 1
        with open(path, "w") as fh:
            fh.write(str(n))
    except Exception:
        n = 1
    print("[17-reask] tag=%s n=%d" % (tag, n), flush=True)
    return n


def _duty_join(duties):
    parts = []
    for d in duties or []:
        if isinstance(d, dict):
            parts.append(str(d.get("note") or d.get("id") or "")[:80])
        else:
            parts.append(str(d)[:80])
    return " | ".join(p for p in parts if p)


def _clip_duties(duties, budget):
    out = []
    used = 0
    for d in duties or []:
        if isinstance(d, dict):
            text = str(d.get("note") or d.get("id") or "")
        else:
            text = str(d)
        if used and used + _blen(text) + 3 > budget:
            break
        if not out and _blen(text) > budget:
            text = _clip_utf8(text, budget)
        if isinstance(d, dict):
            row = dict(d)
            if d.get("note"):
                row["note"] = text
            else:
                row["id"] = text
            out.append(row)
        else:
            out.append(text)
        used += _blen(text) + 3
    return out


def _facts_bytes(facts):
    n = 0
    first = True
    for f in facts or []:
        text = f.get("fact") if isinstance(f, dict) else f
        n += _blen(text) + (0 if first else 1)
        first = False
    return n


def _clip_facts(facts, budget):
    out = []
    used = 0
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        text = str(f.get("fact") or "")
        nxt = _blen(text) + (1 if out else 0)
        if out and used + nxt > budget:
            break
        row = dict(f)
        if not out and _blen(text) > budget:
            row["fact"] = _clip_utf8(text, budget)
            nxt = _blen(row["fact"])
        out.append(row)
        used += nxt
    return out


def _clip_board(board, budget):
    if isinstance(board, str):
        return _clip_utf8(board, budget)
    if not isinstance(board, list):
        raw = json.dumps(board, ensure_ascii=False)
        return board if _blen(raw) <= budget else _clip_utf8(raw, budget)
    out = []
    for row in board:
        trial = out + [row]
        if _blen(json.dumps(trial, ensure_ascii=False)) > budget:
            break
        out.append(row)
    if out:
        return out
    if not board or not isinstance(board[0], dict):
        return []
    row = dict(board[0])
    title = str(row.get("title") or row.get("item_id") or "")
    best = dict(row)
    best["title"] = ""
    lo, hi = 0, len(title)
    while lo <= hi:
        mid = (lo + hi) // 2
        row["title"] = title[:mid]
        if _blen(json.dumps([row], ensure_ascii=False)) <= budget:
            best = dict(row)
            lo = mid + 1
        else:
            hi = mid - 1
    packed = json.dumps([best], ensure_ascii=False)
    if _blen(packed) <= budget:
        return [best]
    return []


def section_bytes(resp):
    """Bytes of the four quota sections. Seal and next_step are outside this sum."""
    if not isinstance(resp, dict):
        return {"duties": 0, "board": 0, "facts": 0, "delta": 0, "total": 0}
    const = resp.get("constitution")
    rule = str(const.get("rule") or "") if isinstance(const, dict) else (const if isinstance(const, str) else "")
    duties = _blen(rule) + _blen(_duty_join(resp.get("duties")))
    board = _blen(json.dumps(resp.get("board"), ensure_ascii=False)) if resp.get("board") is not None else 0
    facts = _facts_bytes(resp.get("facts"))
    if resp.get("desk"):
        facts += _blen(json.dumps(resp.get("desk"), ensure_ascii=False))
    delta = _blen(resp.get("while_away") or "")
    return {"duties": duties, "board": board, "facts": facts, "delta": delta, "total": duties + board + facts + delta}


def _clip_tokens(text, cap):
    raw = str(text or "")
    if estimate_tokens(raw) <= cap + 1e-9:
        return raw
    lo, hi, best = 0, len(raw), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        piece = raw[:mid]
        if estimate_tokens(piece) <= cap + 1e-9:
            best = piece
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _phrase_topic(message):
    blob = (message or "").lower().replace("ё", "е")
    return any(phrase in blob for phrase in NEW_TOPIC_PHRASES)


def resolve_tier(resp, message="", tier=""):
    """base ~600, strong facts ~1200, new topic ~6000."""
    if tier == "new_topic" or _phrase_topic(message):
        return "new_topic", float(TOKEN_TOPIC)
    if facts_are_strong((resp or {}).get("facts"), message):
        return "strong", float(TOKEN_STRONG)
    return "base", float(TOKEN_BASE)


def section_tokens(resp):
    """Token estimate of the four quota sections. Seal and next_step stay outside."""
    if not isinstance(resp, dict):
        return {"duties": 0.0, "board": 0.0, "facts": 0.0, "delta": 0.0, "total": 0.0}
    const = resp.get("constitution")
    rule = str(const.get("rule") or "") if isinstance(const, dict) else (const if isinstance(const, str) else "")
    duties = estimate_tokens(rule) + estimate_tokens(_duty_join(resp.get("duties")))
    board = estimate_tokens(json.dumps(resp.get("board"), ensure_ascii=False)) if resp.get("board") is not None else 0.0
    facts = 0.0
    first = True
    for f in resp.get("facts") or []:
        text = f.get("fact") if isinstance(f, dict) else f
        facts += estimate_tokens(text) + (0.0 if first else 0.25)
        first = False
    if resp.get("desk"):
        facts += estimate_tokens(json.dumps(resp.get("desk"), ensure_ascii=False))
    delta = estimate_tokens(resp.get("while_away") or "")
    return {"duties": duties, "board": board, "facts": facts, "delta": delta, "total": duties + board + facts + delta}


def _clip_facts_tokens(facts, budget):
    out = []
    used = 0.0
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        text = str(f.get("fact") or "")
        sep = 0.0 if not out else 0.25
        if out and used + sep + estimate_tokens(text) > budget + 1e-9:
            break
        row = dict(f)
        if not out and estimate_tokens(text) > budget + 1e-9:
            row["fact"] = _clip_tokens(text, budget)
        out.append(row)
        used += sep + estimate_tokens(row.get("fact") or "")
    return out


def apply_quotas(resp, long_delta=False, message="", tier=""):
    """Normal-path token tiers. Unused room in one section is given to facts."""
    if not isinstance(resp, dict):
        return {}
    name, cap = resolve_tier(resp, message, tier)
    scale = cap / float(TOKEN_BASE)
    duty_cap = TOKEN_DUTY * scale
    board_cap = TOKEN_BOARD * scale
    delta_cap = (TOKEN_DELTA_LONG if long_delta else TOKEN_DELTA) * scale
    const = resp.get("constitution")
    rule = ""
    if isinstance(const, dict):
        rule = str(const.get("rule") or "")
        if estimate_tokens(rule) > duty_cap:
            const = dict(const)
            const["rule"] = _clip_tokens(rule, duty_cap)
            resp["constitution"] = const
            rule = const["rule"]
    duty_left = max(0.0, duty_cap - estimate_tokens(rule))
    joined = _duty_join(resp.get("duties"))
    if resp.get("duties") and estimate_tokens(joined) > duty_left:
        resp["duties"] = [_clip_tokens(joined, duty_left)] if duty_left > 1 else []
    if resp.get("board") is not None:
        raw = json.dumps(resp.get("board"), ensure_ascii=False)
        if estimate_tokens(raw) > board_cap and isinstance(resp.get("board"), list) and resp["board"]:
            row = dict(resp["board"][0]) if isinstance(resp["board"][0], dict) else {"title": str(resp["board"][0])}
            row["title"] = _clip_tokens(str(row.get("title") or ""), max(1.0, board_cap / 2.0))
            resp["board"] = [row]
            if estimate_tokens(json.dumps(resp["board"], ensure_ascii=False)) > board_cap:
                resp["board"] = []
    if isinstance(resp.get("while_away"), str) and estimate_tokens(resp.get("while_away")) > delta_cap:
        resp["while_away"] = _clip_tokens(resp.get("while_away"), delta_cap)
    sizes = section_tokens(resp)
    spare = (
        max(0.0, duty_cap - sizes["duties"])
        + max(0.0, board_cap - sizes["board"])
        + max(0.0, delta_cap - sizes["delta"])
    )
    fact_cap = TOKEN_FACT * scale
    desk_t = estimate_tokens(json.dumps(resp.get("desk"), ensure_ascii=False)) if resp.get("desk") else 0.0
    resp["facts"] = _clip_facts_tokens(resp.get("facts") or [], max(0.0, fact_cap + spare - desk_t))
    sizes = section_tokens(resp)
    guard = 0
    while sizes["total"] > cap + 0.05 and resp.get("facts") and guard < 8:
        resp["facts"] = resp["facts"][:-1]
        sizes = section_tokens(resp)
        guard += 1
    if sizes["total"] > cap + 0.05 and resp.get("facts"):
        resp["facts"] = _clip_facts_tokens(resp["facts"], max(0.0, cap - (sizes["total"] - sizes["facts"])))
        sizes = section_tokens(resp)
    resp["diet_tokens"] = round(sizes["total"], 2)
    resp["diet_tier"] = name
    resp["diet_bytes"] = section_bytes(resp)["total"]
    sizes = dict(sizes)
    sizes["tier"] = name
    sizes["cap"] = cap
    return sizes


def pack_ctx_flags(message, kind="", compressed=False, catchup=False):
    """Flags for turn_pack. Empty unless this turn armed the meta."""
    meta = get_meta()
    if not meta.get("on"):
        return {}
    flags = {}
    off = not fresh_filter_enabled(
        context_compacted=bool(meta.get("context_compacted") or compressed),
        catchup=bool(catchup or meta.get("catchup")),
        new_session=bool(meta.get("new_session")),
        stateless=bool(meta.get("stateless")),
    )
    if off:
        flags["fresh_off"] = True
    elif "own_fresh_ids" in meta:
        flags["own_fresh_ids"] = list(meta.get("own_fresh_ids") or [])
    if meta.get("auto_skip"):
        flags["auto_skip"] = True
    if meta.get("search_skipped"):
        flags["search_skipped"] = True
        flags["search_skip_reason"] = meta.get("skip_reason") or ""
    if meta.get("directive"):
        flags["directive"] = True
        flags["directive_lines"] = list(meta.get("directive_lines") or [])
    if meta.get("topic_trigger"):
        flags["token_tier"] = "new_topic"
    wide = False
    try:
        from app.turn_context import pack_is_wide
        wide = bool(pack_is_wide(message, kind=kind))
    except Exception:
        try:
            from turn_context import pack_is_wide
            wide = bool(pack_is_wide(message, kind=kind))
        except Exception:
            wide = False
    exempt = (
        wide or meta.get("verbose") or meta.get("stateless")
        or meta.get("context_compacted") or catchup or meta.get("catchup")
    )
    if meta.get("compact") and not exempt:
        flags["diet_quota"] = True
        flags["diet_message"] = message or ""
    if catchup and meta.get("long_gap"):
        flags["long_delta"] = True
    flags["diet_wide"] = bool(exempt)
    return flags


def token_hash(token):
    if not token:
        return ""
    return hashlib.sha256(str(token).encode()).hexdigest()
