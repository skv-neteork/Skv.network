"""Turn-only memory context.

The search query is the clean user message. A short or incomplete message also
passes the last one or two user replies as a separate list (see context_queries);
they are not glued into the query. Ranks decisions / critical marks / L1 / L2
above recent self Q/A, and returns several dated facts for a multi-event question.
No embeddings and no change to /search ranking.
"""
import contextvars
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone

_STOP = set("""
a an the of to for from in on at by with as is are was were be been being
do did does done this that these those it its and or but if then than so
not no nor yes you your we our they them their my me i he she his her
what when where which who whom whose why how about into over just very
really please now can could would should will shall must need want like
have has had some such only also there here tell say said says make made
everything something anything nothing
это эта эти этот того этом эту что как для или если когда где кто чем
чтобы надо нужно можно будет было были есть ещё еще уже только тоже очень
просто сейчас теперь пожалуйста сделай сделать делай давай всё все этот
тебя тебе меня мне нас нам него неё она они его еще
""".split())

_SHORT = {"do everything", "сделай всё", "сделай все", "делай", "делай все", "делай всё"}
_ORDER = ("decision", "critical", "l1", "l2", "event", "echo")
_DURABLE = {"decision", "critical", "l1", "l2"}
_SECRET_KIND = {"password", "secret", "token", "credential", "api_key", "apikey", "private_key"}
_PROBE = re.compile(r"^\s*(\[(latency[ _-]?test|report|test|probe|ping|service)[^\]]*\]|zz)", re.I)
_REMEMBER = re.compile(r"(?:[\w.+-]+::)?remember_\d+")
_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


def _tokens(text):
    return _WORD.findall((text or "").lower())


def content_words(text):
    return [w for w in _tokens(text) if len(w) >= 4 and w not in _STOP]


def _same_word(a, b):
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5]:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return False


def _overlap_count(topic_words, text):
    dw = content_words(text)
    n = 0
    for w in topic_words:
        if any(_same_word(w, d) for d in dw):
            n += 1
    return n


def _topic_match(topic, text):
    tw = content_words(topic)
    if not tw:
        return False
    n = _overlap_count(tw, text or "")
    if len(tw) <= 3:
        return n >= 1
    return n >= 2 or (n / len(tw)) >= 0.20


def on_topic(topic, text, extra=""):
    """True if text overlaps topic, or the optional search_as extra source."""
    if _topic_match(topic, text):
        return True
    return bool(extra) and _topic_match(extra, text)


def is_short(msg):
    raw = " ".join(re.sub(r"[^\w\s]", " ", (msg or "").lower(), flags=re.U).split())
    if not raw:
        return False
    if raw in _SHORT or raw.startswith("do everything") or raw.startswith("сделай всё") or raw.startswith("сделай все"):
        return True
    return len(raw.split()) <= 3


def is_multi(msg):
    """True only for the original user message, never the expanded query."""
    low = (msg or "").strip().lower()
    if not low:
        return False
    if low.count("?") >= 2:
        return True
    if len(set(re.findall(r"\b20\d{2}\b", low))) >= 2:
        return True
    if re.search(r"\b(both|each|several|how many|which days)\b", low):
        return True
    if re.search(r"\b(and when|and where|and what)\b", low):
        return True
    if "сколько раз" in low or "и когда" in low or re.search(r"когда\b.+\bи\b", low):
        return True
    if re.search(r"\b(when|where|what|who|which|how)\b", low) and re.search(r"\b(and|и)\b", low):
        parts = re.split(r"\b(?:and|и)\b", low)
        if sum(1 for p in parts if content_words(p)) >= 2:
            return True
    return False


def forms(search_as):
    """Keep the agent's statement forms. Never invent any. Max 3 x 160."""
    if not search_as:
        return []
    if isinstance(search_as, str):
        s = search_as.strip()
        if not s:
            return []
        try:
            search_as = json.loads(s) if s.startswith("[") else re.split(r"\s*(?:\n|\|)\s*", s)
        except Exception:
            search_as = [s]
    if not isinstance(search_as, list):
        search_as = [str(search_as)]
    out = []
    for x in search_as:
        t = str(x).strip()[:160]
        if t:
            out.append(t)
        if len(out) >= 3:
            break
    return out


def _clip(text, n):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


# A file, a path, or an id the follow-up itself does not repeat. Bare numbers are not enough.
_SPECIFIC = re.compile(
    r"(?:remember_\d+|profile_[0-9a-f]{6,}|prof:[0-9a-z0-9]{6,}|\bT\d{2,3}\b|"
    r"[\w.-]+\.(?:py|md|txt|html|json|docx|sh)|/[\w./-]{3,})",
    re.I,
)


def _word_list(msg):
    raw = " ".join(re.sub(r"[^\w\s]", " ", (msg or "").lower(), flags=re.U).split())
    return raw.split() if raw else []


def incomplete(msg):
    """Short, or at most six words that do not already name a file or an id.

    A longer line stands alone. A short line that already names its own file or id
    stands alone too: the previous reply must not compete with that name.
    """
    msg = (msg or "").strip()
    if not msg or _SPECIFIC.search(msg):
        return False
    if is_short(msg):
        return True
    return len(_word_list(msg)) <= 6


def status_recency(msg, context_lines=None):
    """A short status question that names nothing, after the previous line also names nothing.

    The follow-up path stays in charge when the previous line names a file or an id.
    A command with no question mark stays on that path too.
    """
    if not incomplete(msg):
        return False
    if "?" not in (msg or "") and "？" not in (msg or ""):
        return False
    if len(content_words(msg)) > 1:
        return False
    for line in context_lines or []:
        if _SPECIFIC.search(line or ""):
            return False
    return True


def _context_line(text, n=400):
    """One previous reply. A file or id past the head is kept inside the clip."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= n:
        return t
    marks = list(_SPECIFIC.finditer(t))
    if not marks or marks[0].end() <= n:
        return t[:n]
    m = marks[0]
    head = t[:60].rstrip()
    window = t[max(0, m.start() - 40): m.end() + 80]
    return (head + " " + window).strip()[:n]


def context_queries(user_message, recent_user_messages, limit=2):
    """Last 1-2 user replies when the message is short or incomplete.

    Empty for a long self-contained message. This list is a separate search
    signal. It is not concatenated onto the query.
    """
    if not incomplete(user_message):
        return []
    msg = (user_message or "").strip()
    out = []
    for line in recent_user_messages or []:
        t = (line or "").strip()
        if not t or t == msg or t in out:
            continue
        out.append(_context_line(t))
        if len(out) >= max(1, int(limit or 2)):
            break
    return out


def search_as_skip(search_as):
    """True when every agent form is the dash that means do not recall."""
    kept = forms(search_as)
    return bool(kept) and all(x.strip() == "-" for x in kept)


# Status phrases and deictic markers. A command in _SHORT is not one of these.
_STATUS = (
    "как идет", "как идёт", "как дела", "ну как", "как успехи", "какой статус",
    "как там", "готово", "статус", "what is the status", "how's it going",
    "how is it going", "status",
)
_DEICTIC = re.compile(
    r"\b(там|это|этот|эта|этого|этом|он|она|они|него|неё|нее|дальше|this|that|there)\b",
    re.I,
)
_JUNK = set("""
делай делаем сделай давай дальше хорошо понял поняла ладно next ok okay yes no
thanks thank спасибо да ок
""".split())
_PLAN = contextvars.ContextVar("skv_followup_plan", default=None)
_AGENT = contextvars.ContextVar("skv_gloss_agent", default="")
_DUTY = (
    "search_as_missing: send search_as=<what the user means, 3-8 words> or exactly -. "
    "Turns hanging: %d."
)
_SUMMARY_DUTY = (
    "draft_summary_missing: 5-8 words of what you checked, changed or decided, and the result."
)
_REVISE_REASON = (
    "search_as required: send search_as=<what the user means, 3-8 words> or exactly -. "
    "The event is saved. Resend only search_as."
)


def _bare(msg):
    raw = (msg or "").lower().replace("ё", "е").replace("'", "").replace("\u2019", "").replace("`", "")
    return " ".join(re.sub(r"[^\w\s]", " ", raw, flags=re.U).split())


def _is_command(msg):
    raw = " ".join(re.sub(r"[^\w\s]", " ", (msg or "").lower(), flags=re.U).split())
    if not raw:
        return False
    return raw in _SHORT or raw.startswith("do everything") or raw.startswith("сделай всё") or raw.startswith("сделай все")


def is_status(msg):
    """A bare status question. 'как идет сборка' has two content words and is not one."""
    if _SPECIFIC.search(msg or ""):
        return False
    bare = _bare(msg)
    if not bare:
        return False
    words = bare.split()
    shortish = is_short(msg) or (incomplete(msg) and len(words) <= 5)
    if not shortish or len(content_words(msg)) > 1:
        return False
    for phrase in _STATUS:
        p = _bare(phrase)
        if bare == p or bare.startswith(p + " "):
            return True
    return False


def is_deictic(msg):
    """'а он сделал?' points at the current task. A status line and a command do not."""
    if is_status(msg) or _is_command(msg) or _SPECIFIC.search(msg or ""):
        return False
    if not (is_short(msg) or incomplete(msg)):
        return False
    return bool(_DEICTIC.search(_bare(msg)))


def is_empty_followup(msg):
    """Ack or filler. A question and a deictic line are not acks."""
    if _is_command(msg) or _SPECIFIC.search(msg or "") or is_status(msg):
        return False
    if not (msg or "").strip() or not (is_short(msg) or incomplete(msg)):
        return False
    words = [w.replace("ё", "е") for w in _word_list(msg)]
    if not words:
        return False
    if len(words) == 1 and words[0] in _JUNK:
        return True
    if "?" in (msg or "") or "？" in (msg or "") or is_deictic(msg):
        return False
    return all(w in _JUNK or w in _STOP or len(w) < 4 for w in words)


def gloss_good(search_as):
    """Two content words that are not a single filler. A dash is not a gloss."""
    kept = forms(search_as)
    if not kept or all(x.strip() == "-" for x in kept):
        return False
    text = " ".join(kept)
    words = [w.replace("ё", "е") for w in _word_list(text)]
    if len(words) == 1 and words[0] in _JUNK:
        return False
    return len(content_words(text)) >= 2


def _needs_gloss(msg):
    """Short or reference line that should carry the agent's interpretation."""
    if is_status(msg) or _is_command(msg) or _SPECIFIC.search(msg or "") or is_empty_followup(msg):
        return False
    if is_deictic(msg):
        return True
    text = " ".join((msg or "").split())
    if not text:
        return False
    if is_short(msg) or (incomplete(msg) and len(text) < 40):
        return len(content_words(msg)) >= 1
    return False


def _bad_dash(msg):
    """Dash where the line still needs a gloss. Status, fillers, and long lines are allowed."""
    if is_status(msg) or _SPECIFIC.search(msg or "") or is_empty_followup(msg) or _is_command(msg):
        return False
    if not (is_short(msg) or incomplete(msg)):
        return False
    return len(content_words(msg)) >= 2 or "?" in (msg or "") or "？" in (msg or "")


def gloss_kind(msg, search_as):
    kept = forms(search_as)
    if kept and all(x.strip() == "-" for x in kept):
        return "dash_rejected" if _bad_dash(msg) else "dash_ok"
    if gloss_good(search_as):
        return "filled"
    if kept:
        return "junk"
    if _needs_gloss(msg) or is_deictic(msg):
        return "missed"
    return "open"


def followup_plan(user_message, search_as, recent_user_messages=None):
    """How this turn is searched. The raw line is never concatenated onto search_as.

    mode skip: no memory facts. slice: the active board and the latest answers.
    deictic: search_as alone, recency half-life 36h. gloss: search_as is the query
    and the last series lines stay a separate context list. series: a short line
    that already names its topic stays the query; a vaguer one uses the previous line.
    """
    msg = (user_message or "").strip()
    kept = forms(search_as)
    kind = gloss_kind(msg, search_as)
    good = kind == "filled"
    ctx3 = context_queries(msg, recent_user_messages, limit=3)
    plan = {
        "mode": "plain",
        "query": msg[:500],
        "search_as": [],
        "context": ctx3[:2],
        "user_weight": 1.0,
        "recency_h": None,
        "task_hint": "",
        "gloss": kind,
        "stat": "",
        "revise": False,
        "duty": False,
    }
    if is_status(msg):
        plan.update(mode="slice", query="", context=[], user_weight=0.0,
                    task_hint=(kept[0] if good else ""))
        if kind == "dash_ok":
            plan["stat"] = "dash_ok"
        elif good:
            plan["stat"] = "filled"
        return plan
    if kind == "dash_rejected":
        plan.update(mode="skip", query="", context=[], revise=True, duty=True, stat="dash_rejected")
        return plan
    if kind == "dash_ok":
        plan.update(mode="skip", query="", context=[], stat="dash_ok")
        return plan
    if is_empty_followup(msg) and not good:
        plan.update(mode="slice", query="", context=ctx3, user_weight=0.0)
        return plan
    if is_deictic(msg) and good:
        plan.update(mode="deictic", query=kept[0][:500], search_as=[], context=[],
                    user_weight=0.0, recency_h=36.0, stat="filled")
        return plan
    if is_deictic(msg) and kind in ("missed", "junk"):
        plan.update(mode="slice", query="", context=ctx3, user_weight=0.0,
                    revise=True, duty=True, stat="missed")
        return plan
    if good and is_short(msg):
        plan.update(mode="gloss", query=kept[0][:500], search_as=kept[1:], context=ctx3, stat="filled")
        return plan
    if good:
        plan.update(mode="plain", query=msg[:500], search_as=kept, context=ctx3[:2], stat="filled")
        return plan
    if _needs_gloss(msg) and kind in ("missed", "junk"):
        vague = len(content_words(msg)) < 2
        if vague and ctx3:
            query, rest = ctx3[0], ctx3[1:]
        else:
            query, rest = msg[:500], ctx3
        plan.update(mode="series", query=query, search_as=[], context=rest,
                    revise=True, duty=True, stat="missed")
        return plan
    if not (is_short(msg) or incomplete(msg)):
        plan["context"] = []
    return plan


def build_search(user_message, search_as, recent_user_messages):
    """Return (query, search_as). Skip and slice search nothing here.

    The query is never a glued previous line. A real gloss on a non-status
    short line is the query. A long line stays the query.
    """
    plan = followup_plan(user_message, search_as, recent_user_messages)
    if plan["mode"] in ("skip", "slice"):
        return "", []
    return (plan.get("query") or "")[:500], list(plan.get("search_as") or [])


def set_plan(plan):
    _PLAN.set(plan if isinstance(plan, dict) else {})


def current_plan():
    plan = _PLAN.get()
    return plan if isinstance(plan, dict) else {}


def agent_key(token):
    """Stable counter key. The raw token is not stored."""
    raw = (token or "").strip()
    if not raw:
        return "anon"
    if len(raw) == 17 and raw.startswith("a") and all(c in "0123456789abcdef" for c in raw[1:]):
        return raw
    return "a" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def set_agent(token):
    _AGENT.set(agent_key(token))


def gloss_revise_reason():
    return _REVISE_REASON


def remember_fields(search_as, draft_summary, note_event_id):
    """Fields /remember stores on the event. Empty values are left out."""
    out = {}
    if isinstance(search_as, list):
        text = " | ".join(str(x).strip() for x in search_as if str(x).strip())
    else:
        text = str(search_as or "").strip()
    if text:
        out["search_as"] = text[:500]
    if str(draft_summary or "").strip():
        out["draft_summary"] = str(draft_summary).strip()[:200]
    if str(note_event_id or "").strip():
        out["note_event_id"] = str(note_event_id).strip()
    return out


def _age_hours(time_s, now):
    s = str(time_s or "")
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", s)
    if not m:
        return 1e6
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                      int(m.group(4) or 0), int(m.group(5) or 0), tzinfo=timezone.utc)
    except ValueError:
        return 1e6
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def rerank_recency(hits, query, half_life=36.0, now=None):
    """Same shape as blend_score. half_life 36 is this path only; the global one stays 168."""
    try:
        life = float(half_life)
    except (TypeError, ValueError):
        life = 36.0
    if life <= 0:
        life = 36.0
    moment = now or datetime.now(timezone.utc)
    qwords = content_words(query)
    ranked = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        try:
            rel = float(h.get("score") or 0)
        except (TypeError, ValueError):
            rel = 0.0
        if qwords:
            cov = _overlap_count(qwords, h.get("summary") or "") / float(len(qwords))
        else:
            cov = 1.0
        if cov < 0.0:
            cov = 0.0
        if cov > 1.0:
            cov = 1.0
        age = _age_hours(h.get("time"), moment)
        score = rel * (0.15 + 0.85 * cov) * (0.45 + 0.55 * math.exp(-age / life))
        row = dict(h)
        row["score"] = score
        ranked.append(row)
    ranked.sort(key=lambda x: -float(x.get("score") or 0))
    return ranked


def _slice_hit(eid, ts, text, score):
    return {
        "event_id": eid,
        "time": ts or "",
        "score": score,
        "summary": text,
        "source": "active_slice",
        "active_slice": True,
    }


def _pick_doing(rows, hint):
    if not rows:
        return None
    words = content_words(hint or "")
    best, best_n = None, 0
    if words:
        for row in rows:
            n = _overlap_count(words, "%s %s" % (row[1] or "", row[2] or ""))
            if n > best_n:
                best, best_n = row, n
        if best is not None and best_n:
            return best
    return rows[0]


def _agent_clip(raw, n=500):
    raw = re.sub(r"\s+", " ", raw or "").strip()
    i = raw.find(" A:")
    if i < 0:
        i = raw.find("A:")
    if i >= 0:
        return _clip((raw[:min(i, 80)] + " " + raw[i:]).strip(), n)
    return _clip(raw, n)


def active_slice(conn, hint=""):
    """Doing item, its latest change, the last answers, and the last L1. Read only."""
    if conn is None:
        return []
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return []
    board_hit = hist_hit = src_hit = None
    if "board_items" in tabs:
        try:
            rows = conn.execute(
                "SELECT item_id, title, body, status, updated_at FROM board_items "
                "WHERE coalesce(removed,0)=0 AND status='doing' ORDER BY updated_at DESC"
            ).fetchall()
        except sqlite3.Error:
            rows = []
        item = _pick_doing(rows, hint)
        if item:
            iid, title, body, _status, updated = item
            board_hit = _slice_hit("board:" + str(iid), updated, "doing: %s. %s" % (title or iid, _clip(body or "", 400)), 1.0)
            if "board_history" in tabs:
                try:
                    hist = conn.execute(
                        "SELECT text, ts FROM board_history WHERE item_id=? ORDER BY id DESC LIMIT 1",
                        (iid,),
                    ).fetchone()
                except sqlite3.Error:
                    hist = None
                if hist and (hist[0] or "").strip():
                    hist_hit = _slice_hit("board:%s:hist" % iid, hist[1], "change: " + _clip(hist[0], 300), 0.85)
            if "source_links" in tabs:
                try:
                    link = conn.execute(
                        "SELECT source_event_ids, status FROM source_links WHERE obj_id=?",
                        ("board:" + str(iid),),
                    ).fetchone()
                except sqlite3.Error:
                    link = None
                if link and ((link[0] or "").strip() or (link[1] or "").strip()):
                    src_hit = _slice_hit(
                        "board:%s:src" % iid, "",
                        "source: %s %s" % (link[1] or "", _clip(link[0] or "", 180)),
                        0.8,
                    )
    l1_hits = []
    if "summary_l1" in tabs:
        try:
            l1_rows = conn.execute(
                "SELECT rowid, topic, summary_text, created_at FROM summary_l1 ORDER BY rowid DESC LIMIT 2"
            ).fetchall()
        except sqlite3.Error:
            l1_rows = []
        for row in l1_rows:
            text = _clip(((row[1] or "") + " " + (row[2] or "")).strip(), 400)
            if text:
                l1_hits.append(_slice_hit("l1:%s" % row[0], row[3], text, 0.75))
    events = []
    if "event_metadata" in tabs:
        try:
            ev_rows = conn.execute(
                "SELECT event_id, time_str, raw_dialogue FROM event_metadata ORDER BY rowid DESC LIMIT 12"
            ).fetchall()
        except sqlite3.Error:
            ev_rows = []
        for eid, ts, raw in ev_rows:
            if not eid or (raw or "").startswith("[archived]") or "A:" not in (raw or ""):
                continue
            events.append(_slice_hit(eid, ts, _agent_clip(raw, 500), 0.7))
            if len(events) >= 3:
                break
    out = []
    if board_hit:
        out.append(board_hit)
    if events:
        out.append(events[0])
    if l1_hits:
        out.append(l1_hits[0])
    for extra in (hist_hit, src_hit):
        if extra:
            out.append(extra)
    out.extend(events[1:])
    out.extend(l1_hits[1:])
    return out


def slice_keeps(plan, hits):
    """The slice is the whole answer, except a gloss miss with no doing row.

    Status and an empty ack stay on the slice. A deictic miss with no doing
    item searches the short line itself. The previous lines stay context.
    """
    plan = plan if isinstance(plan, dict) else {}
    has_board = any(str(h.get("event_id") or "").startswith("board:") for h in (hits or []) if isinstance(h, dict))
    if has_board or not plan.get("context") or not plan.get("revise"):
        return True
    return False


def _append_line(result, key, line):
    cur = result.get(key) or ""
    if not isinstance(cur, str):
        return
    if line not in cur:
        result[key] = (cur + " " + line).strip() if cur else line


def attach_gloss(result, plan, agent="", path=None):
    """Count the gloss once and, when it was required, say so on next."""
    if not isinstance(result, dict):
        return result
    plan = plan if isinstance(plan, dict) else {}
    stat = plan.get("stat") or ""
    key = agent_key(agent) if agent else (_AGENT.get() or "anon")
    if stat in ("filled", "dash_ok", "dash_rejected", "missed") and not plan.get("_bumped"):
        try:
            try:
                from gloss_note import bump, count_of
            except ImportError:
                from app.gloss_note import bump, count_of
            bump(key, stat, path=path)
            plan["_bumped"] = True
            result["search_as_stat"] = stat
        except Exception:
            result["search_as_stat"] = stat
    if plan.get("duty"):
        try:
            try:
                from gloss_note import count_of
            except ImportError:
                from app.gloss_note import count_of
            hanging = count_of(key, "missed", path=path)
        except Exception:
            hanging = 0
        line = _DUTY % hanging
        _append_line(result, "next", line)
        _append_line(result, "next_step", line)
        duties = list(result.get("duties") or [])
        if line not in duties:
            duties.append(line)
            result["duties"] = duties
    if plan.get("summary_missing"):
        _append_line(result, "next", _SUMMARY_DUTY)
        _append_line(result, "next_step", _SUMMARY_DUTY)
        duties = list(result.get("duties") or [])
        if _SUMMARY_DUTY not in duties:
            duties.append(_SUMMARY_DUTY)
            result["duties"] = duties
    return result


def user_q(raw):
    q = (raw or "").partition("\nA:")[0]
    q = re.sub(r"^\s*(\[revision of ev:[^\]]*\]\s*)+", "", q)
    q = re.sub(r"^Q:\s*", "", q).strip()
    return q


def _day(time_s):
    s = str(time_s or "")
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{2})\.(\d{2})\.(20\d{2})", s)
    if m:
        return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
    return ""


def _stale(time_s, days=2):
    day = _day(time_s)
    if not day:
        return False
    try:
        dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days > days
    except Exception:
        return False


def _tables(conn):
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return set()


def recent_from_conn(conn, current=""):
    """Newest user lines (up to 4) and the event ids of the newest 3 raw turns (the echoes)."""
    if conn is None:
        return [], set()
    try:
        rows = conn.execute(
            "SELECT event_id, raw_dialogue, time_str FROM event_metadata "
            "WHERE coalesce(raw_dialogue,'') NOT LIKE '%[lightweight]%' "
            "ORDER BY rowid DESC LIMIT 12"
        ).fetchall()
    except Exception:
        return [], set()
    fresh = [r for r in rows if not _stale(r[2])]
    topic_rows = fresh if fresh else rows
    echoes = set()
    for eid, _raw, _ts in rows[:3]:
        if eid:
            echoes.add(eid)
            echoes.add(str(eid).split("::")[-1])
    cur = (current or "").strip()
    texts = []
    for eid, raw, _ts in topic_rows:
        if "[lightweight]" in (raw or "")[:80]:
            continue
        q = user_q(raw)
        if not q or _PROBE.match(q):
            continue
        if cur and q.strip() == cur:
            continue
        if q not in texts:
            texts.append(q)
        if len(texts) >= 4:
            break
    return texts, echoes


def newest_status_hits(conn, msg="", limit=5):
    """Newest saved lines, newest first. Used when a status question has no named referent.

    Scores sit above a weak search (about 0.03) and under a real durable layer.
    The question itself, if it was already saved, is not one of these lines.
    """
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT event_id, raw_dialogue, time_str FROM event_metadata "
            "WHERE coalesce(raw_dialogue,'') NOT LIKE '%[lightweight]%' "
            "ORDER BY rowid DESC LIMIT 12"
        ).fetchall()
    except Exception:
        return []
    cur = (msg or "").strip()
    out = []
    for eid, raw, ts in rows:
        if not eid:
            continue
        if "[lightweight]" in (raw or "")[:80]:
            continue
        q = user_q(raw)
        if not q or _PROBE.match(q):
            continue
        if cur and q.strip() == cur:
            continue
        score = 0.20 - 0.01 * len(out)
        out.append(_hit(eid, score, "event", "event", _clip(q, 240), ts or ""))
        if len(out) >= max(1, int(limit or 4)):
            break
    return out


def merge_status_newest(hits, msg, conn, context_lines, echoes):
    """Prepend this account's newest events and keep them out of the one-echo slot.

    No change when the question names its own topic or the previous line names a file.
    """
    echoes = set(echoes or [])
    if not status_recency(msg, context_lines):
        return list(hits or []), echoes
    extra = newest_status_hits(conn, msg=msg, limit=5)
    if not extra:
        return list(hits or []), echoes
    for h in extra:
        eid = str(h.get("event_id") or "")
        echoes.discard(eid)
        echoes.discard(eid.split("::")[-1])
    seen, merged = set(), []
    for h in extra + list(hits or []):
        eid = str(h.get("event_id") or "")
        sid = eid.split("::")[-1]
        key = sid or eid
        if key in seen:
            continue
        seen.add(key)
        merged.append(h)
    return merged, echoes


def _eid_at(conn, rowid):
    if not rowid:
        return ""
    try:
        r = conn.execute("SELECT event_id FROM event_metadata WHERE rowid=?", (int(rowid),)).fetchone()
        return (r[0] or "") if r else ""
    except Exception:
        return ""


def _remember(blob):
    m = _REMEMBER.search(blob or "")
    return m.group(0) if m else ""


def _hit(event_id, score, source, layer, summary, time_s):
    return {
        "event_id": event_id or ("%s:row" % layer),
        "score": float(score or 0),
        "source": source,
        "layer": layer,
        "summary": summary,
        "time": time_s or "",
    }


def _take(rows, topic, limit, build):
    out = []
    for row in rows:
        try:
            item = build(row)
        except Exception:
            item = None
        if item:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _decisions(conn, topic, limit):
    try:
        rows = conn.execute(
            "SELECT id, text, source_event_ids, updated_at FROM profile_rows "
            "WHERE kind='decision' AND status='active' ORDER BY updated_at DESC LIMIT 40"
        ).fetchall()
    except Exception:
        return []

    def build(row):
        pid, text, src, updated = row
        if not on_topic(topic, text or ""):
            return None
        eid = _remember(src) or ("prof:%s" % pid)
        return _hit(eid, 0.9 + 0.01 * _overlap_count(content_words(topic), text or ""), "decision", "decision",
                    "[decision] " + _clip(text, 240), updated or "")

    return _take(rows, topic, limit, build)


def _critical(conn, topic, limit):
    try:
        try:
            rows = conn.execute(
                "SELECT kind, value, context, event_id, time_str FROM critical_auto "
                "WHERE coalesce(demoted,0)=0 ORDER BY time_str DESC LIMIT 80"
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT kind, value, context, event_id, time_str FROM critical_auto ORDER BY time_str DESC LIMIT 80"
            ).fetchall()
    except Exception:
        return []

    def build(row):
        kind, value, ctx, eid, ts = row
        if (kind or "").strip().lower() in _SECRET_KIND:
            return None
        try:
            from app.critical_auto import is_junk
            if is_junk(kind, value, ctx):
                return None
        except Exception:
            pass
        blob = "%s %s %s" % (kind or "", value or "", ctx or "")
        if not on_topic(topic, blob):
            return None
        return _hit(eid or ("critical:%s" % _clip(value, 24)), 0.85, "critical", "critical",
                    "[critical] " + _clip(blob, 240), ts or "")

    return _take(rows, topic, limit, build)


def _l1(conn, topic, limit):
    try:
        rows = conn.execute(
            "SELECT session_id, topic, summary_text, created_at, to_rowid FROM summary_l1 ORDER BY rowid DESC LIMIT 30"
        ).fetchall()
    except Exception:
        return []

    def build(row):
        sid, title, text, created, to_row = row
        blob = "%s %s" % (title or "", text or "")
        if not on_topic(topic, blob):
            return None
        eid = _eid_at(conn, to_row) or ("l1:%s" % (sid or "row"))
        return _hit(eid, 0.8, "l1", "l1", "[l1] " + _clip(blob, 240), created or "")

    return _take(rows, topic, limit, build)


def _l2(conn, topic, limit):
    hits = []
    try:
        rows = conn.execute(
            "SELECT id, text, period_from, created_at, to_rowid FROM summary_l2_blocks ORDER BY id DESC LIMIT 20"
        ).fetchall()
    except Exception:
        rows = []

    def build(row):
        bid, text, period, created, to_row = row
        if not on_topic(topic, text or ""):
            return None
        eid = _eid_at(conn, to_row) or ("l2:%s" % bid)
        return _hit(eid, 0.75, "l2", "l2", "[l2] " + _clip(text, 240), period or created or "")

    hits.extend(_take(rows, topic, limit, build))
    if hits or limit <= 0:
        return hits[:limit]
    try:
        row = conn.execute("SELECT map_json, last_updated FROM summary_l2 ORDER BY last_updated DESC LIMIT 1").fetchone()
    except Exception:
        row = None
    if row and on_topic(topic, (row[0] or "")[:4000]):
        hits.append(_hit("l2:map", 0.7, "l2", "l2", "[l2] " + _clip(row[0], 240), row[1] or ""))
    return hits[:limit]


def layer_from_conn(conn, topic, limit_each=3):
    if conn is None or not (topic or "").strip():
        return []
    tabs = _tables(conn)
    out = []
    if "profile_rows" in tabs:
        out.extend(_decisions(conn, topic, limit_each))
    if "critical_auto" in tabs:
        out.extend(_critical(conn, topic, limit_each))
    if "summary_l1" in tabs:
        out.extend(_l1(conn, topic, limit_each))
    if "summary_l2_blocks" in tabs or "summary_l2" in tabs:
        out.extend(_l2(conn, topic, limit_each))
    return out


def neighbours(conn, event_id, topic, radius=2):
    """rowid ± radius around one event. Each neighbour must share a topic word."""
    if conn is None or not event_id:
        return []
    sid = str(event_id).split("::")[-1]
    try:
        row = conn.execute("SELECT rowid FROM event_metadata WHERE event_id=? ORDER BY rowid DESC LIMIT 1", (event_id,)).fetchone()
        if not row and sid and sid != event_id:
            row = conn.execute(
                "SELECT rowid FROM event_metadata WHERE event_id=? OR event_id LIKE ? ORDER BY rowid DESC LIMIT 1",
                (sid, "%::" + sid),
            ).fetchone()
    except Exception:
        return []
    if not row:
        return []
    rid = int(row[0])
    try:
        rows = conn.execute(
            "SELECT event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid BETWEEN ? AND ? AND rowid != ?",
            (rid - int(radius), rid + int(radius), rid),
        ).fetchall()
    except Exception:
        return []
    out = []
    for eid, ts, raw in rows:
        if not eid or "[lightweight]" in (raw or "")[:40]:
            continue
        text = user_q(raw) or _clip(raw, 200)
        if not on_topic(topic, text + " " + (raw or "")[:500]):
            continue
        out.append(_hit(eid, 0.55, "event", "event", _clip(text, 240), ts or ""))
    return out


def _layer_of(h, echo_ids):
    layer = (h.get("layer") or "").lower()
    if layer in _ORDER:
        return layer
    src = (h.get("source") or "").lower()
    if src in _DURABLE:
        return src
    summ = (h.get("summary") or "").lstrip().lower()
    if summ.startswith("[decision]"):
        return "decision"
    if summ.startswith("[critical"):
        return "critical"
    if summ.startswith("[l1]"):
        return "l1"
    if summ.startswith("[l2]"):
        return "l2"
    eid = str(h.get("event_id") or "")
    sid = eid.split("::")[-1]
    if eid in echo_ids or sid in echo_ids:
        return "echo"
    return "event"


def _copy_time(h):
    h = dict(h)
    if not h.get("time"):
        meta = h.get("metadata") or {}
        h["time"] = meta.get("time_str") or meta.get("time") or ""
    return h


def _prefix_date(summary, time_s):
    day = _day(time_s)
    if not day:
        return summary
    hm = ""
    m = re.search(r"\b(\d{2}:\d{2})\b", str(time_s or ""))
    if m:
        hm = " " + m.group(1)
    prefix = day + hm
    text = summary or ""
    if text.startswith(day):
        return text
    return prefix + " — " + text


def _diversify(hits, limit):
    picked, seen, later = [], set(), []
    for h in hits:
        day = _day(h.get("time"))
        if day and day in seen:
            later.append(h)
            continue
        if day:
            seen.add(day)
        picked.append(h)
        if len(picked) >= limit:
            return picked
    for h in later:
        picked.append(h)
        if len(picked) >= limit:
            break
    return picked


def _yyyymmdd(time_s):
    day = _day(time_s)
    if not day:
        return 0
    try:
        return int(day.replace("-", ""))
    except ValueError:
        return 0


def rank(hits, topic, echo_ids, multi, limit=5):
    """Layer order, then score, then newer day. At most one recent echo, kept as an ordinary event.

    An off-topic critical or decision mark is an ordinary event. It does not take the durable boost.
    An empty topic does not demote, because on_topic is false for every row in that case.
    """
    echo_ids = set(echo_ids or [])
    prepared = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        item = _copy_time(h)
        item["layer"] = _layer_of(item, echo_ids)
        prepared.append(item)
    if content_words(topic):
        for item in prepared:
            if item["layer"] in ("critical", "decision") and not on_topic(topic, item.get("summary") or ""):
                item["layer"] = "event"
                item["score"] = float(item.get("score") or 0) * 0.2
    echoes = [h for h in prepared if h["layer"] == "echo"]
    rest = [h for h in prepared if h["layer"] != "echo"]
    if echoes:
        # Demote the newest self-echo, do not drop it. A short follow-up's file
        # often lives in that line. One echo stays, as an ordinary event, so it
        # can still fit in the pack. The rest of the tail stays out.
        echoes.sort(key=lambda h: -float(h.get("score") or 0))
        kept = echoes[0]
        kept["layer"] = "event"
        rest.append(kept)
    order = {name: i for i, name in enumerate(_ORDER)}
    rest.sort(key=lambda h: (order.get(h["layer"], 9), -float(h.get("score") or 0), -_yyyymmdd(h.get("time"))))
    if multi:
        rest = _diversify(rest, limit)
        for h in rest:
            h["summary"] = _prefix_date(h.get("summary") or "", h.get("time") or "")
    else:
        rest = rest[:limit]
    seen, out = set(), []
    for h in rest:
        key = (str(h.get("event_id") or ""), (h.get("summary") or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= limit:
            break
    mx = max([float(h.get("score") or 0) for h in out] or [0]) or 1.0
    has_durable = any(h["layer"] in _DURABLE for h in out)
    for h in out:
        if h["layer"] in _DURABLE:
            h["score"] = mx
        elif h["layer"] == "echo" and has_durable:
            h["score"] = mx * 0.5
    return out


# Compact turn pack. search_config.json key turn_pack_2400, default on when the key is absent.
# Wide turns keep 2400. A normal turn uses the smaller budget.
_SEARCH_CFG = "/data/skv/search_config.json"
PACK_BUDGET = 2400
PACK_NORMAL = 1500
PACK_NORMAL_N = 3
PACK_NORMAL_CLIP = 160
PACK_RAW_SLOTS = 2
PACK_CLIP = 400
PACK_RANK = 12
_LEGACY_RANK = 5


def pack_2400_enabled(cfg=None):
    """True unless the config explicitly sets turn_pack_2400 to false. Missing file or key stays on."""
    if cfg is None:
        cfg = _search_cfg()
    if not isinstance(cfg, dict) or "turn_pack_2400" not in cfg:
        return True
    return bool(cfg.get("turn_pack_2400"))


def _search_cfg():
    try:
        with open(_SEARCH_CFG, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def turn_rank_limit(compact=False, cfg=None):
    """Compact turns read 12 ranked hits so the 2400 pack can fill. Otherwise the old limit of 5."""
    if compact and pack_2400_enabled(cfg):
        return PACK_RANK
    return _LEGACY_RANK


def _event_sid(event_id):
    return str(event_id or "").split("::")[-1]


def _message_window(message):
    if not (message or "").strip():
        return None
    try:
        from app.turn_pack import date_window
    except Exception:
        try:
            import turn_pack as _tp
            date_window = _tp.date_window
        except Exception:
            return None
    try:
        return date_window(message)
    except Exception:
        return None


def pack_is_wide(message=None, kind="", expand=False):
    """None message keeps the 2400 pack the bench calls without a turn message.

    A real message is normal unless it is multi-part, a date window, a doc, or expand.
    """
    if expand or str(kind or "").strip().lower() in ("doc", "expand"):
        return True
    if message is None:
        return True
    if is_multi(message):
        return True
    return bool(_message_window(message))


def _is_summary_hit(h):
    layer = str((h or {}).get("layer") or "").lower()
    if layer in ("l1", "l2"):
        return True
    text = str((h or {}).get("summary") or "").lstrip()
    return text.startswith("[l1]") or text.startswith("[l2]")


def _order_for_pack(hits, limit_n, reserve_raw):
    """Of a base of limit_n facts, keep 1-2 slots for raw events."""
    rows = [h for h in (hits or []) if isinstance(h, dict)]
    if not limit_n:
        return rows
    raw, summ = [], []
    for h in rows:
        (summ if _is_summary_hit(h) else raw).append(h)
    if not reserve_raw or not raw:
        return (raw + summ)[:limit_n]
    slots = min(int(reserve_raw), len(raw), int(limit_n))
    chosen = list(raw[:slots])
    for h in list(raw[slots:]) + summ:
        if len(chosen) >= limit_n:
            break
        chosen.append(h)
    return chosen


def compact_facts(hits, own="", cfg=None, rel=0.7, n=3, chars=200, message=None, kind="", expand=False):
    """Facts for turn(compact=true).

    Flag on and wide (or no message): clip 400, stop at 2400, no relative score cut.
    Flag on and a normal message: 1500 characters, at most 3 facts, 160 characters each, raw slots kept.
    Flag off: relative 0.7, three facts, chars each. own is this turn's event and is skipped.
    pack2400 marks a packed row so the later topic diet does not throw it away.
    The summary field is not copied: fact already carries the text.
    """
    own_sid = _event_sid(own)
    if not pack_2400_enabled(cfg):
        return _legacy_facts(hits, own_sid, rel, n, chars)
    if pack_is_wide(message, kind=kind, expand=expand):
        return _pack_budget(hits, own_sid, PACK_BUDGET, PACK_CLIP, mark=True)
    return _pack_budget(
        hits, own_sid, PACK_NORMAL, PACK_NORMAL_CLIP,
        mark=True, limit_n=PACK_NORMAL_N, reserve_raw=PACK_RAW_SLOTS,
    )


def _pack_budget(hits, own_sid, budget, clip, mark=True, limit_n=0, reserve_raw=0):
    parts = []
    chosen = []
    used = 0
    ordered = _order_for_pack(hits, limit_n, reserve_raw)
    for h in ordered:
        if not isinstance(h, dict):
            continue
        ev = _event_sid(h.get("event_id"))
        if own_sid and ev == own_sid:
            continue
        text = re.sub(r"\s+", " ", str(h.get("summary") or "")).strip()
        if not text:
            continue
        row_clip = 400 if h.get("active_slice") else clip
        piece = text[:row_clip]
        extra = len(piece) + (1 if parts else 0)
        if parts and used + extra > budget:
            break
        if not parts and len(piece) > budget:
            piece = piece[:budget]
        shown = piece.rstrip() + " [cut]" if len(text) > len(piece) else piece
        fact = shown + (" [ev:%s]" % ev if ev else "")
        parts.append(piece)
        row = {
            "ev": ev,
            "time": h.get("time") or "",
            "fact": fact,
            "event_id": h.get("event_id"),
            "score": h.get("score"),
        }
        if h.get("active_slice"):
            row["active_slice"] = True
        elif mark:
            row["pack2400"] = True
        chosen.append(row)
        used += len(piece) + (1 if len(parts) > 1 else 0)
        if used >= budget:
            break
    return chosen


def _legacy_facts(hits, own_sid, rel, n, chars):
    top = max([float(h.get("score") or 0) for h in (hits or []) if isinstance(h, dict)] or [0])
    out = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        ev = _event_sid(h.get("event_id"))
        if own_sid and ev == own_sid:
            continue
        if top and h.get("score") is not None and float(h.get("score") or 0) < rel * top:
            continue
        text = re.sub(r"\s+", " ", str(h.get("summary") or "")).strip()
        if not text:
            continue
        body = text[:chars].rstrip() + " [cut]" if len(text) > chars else text
        out.append({
            "ev": ev,
            "time": h.get("time") or "",
            "fact": body + (" [ev:%s]" % ev if ev else ""),
            "event_id": h.get("event_id"),
            "score": h.get("score"),
            "summary": h.get("summary") or "",
        })
        if len(out) >= n:
            break
    return out


def open_ro(path):
    if not path:
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    except Exception:
        return None
