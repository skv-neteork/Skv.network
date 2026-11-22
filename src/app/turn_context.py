"""Turn-only memory context.

Folds the last user lines into the one search query, ranks decisions / critical
marks / L1 / L2 above recent self Q/A, and returns several dated facts for a
multi-event question. No embeddings and no change to /search ranking.
"""
import json
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


def on_topic(topic, text):
    tw = content_words(topic)
    if not tw:
        return False
    n = _overlap_count(tw, text or "")
    if len(tw) <= 3:
        return n >= 1
    return n >= 2 or (n / len(tw)) >= 0.20


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


def _flat(text):
    """Context folded into a short follow-up must not look like a new question (that would add Q2S hybrids)."""
    return _clip(re.sub(r"[?？]", " ", text or ""), 140)


def build_search(user_message, search_as, recent_user_messages):
    """Return (query, search_as). One query string. search_as is only what the agent passed."""
    kept = forms(search_as)
    msg = (user_message or "").strip()
    recent = []
    for line in recent_user_messages or []:
        t = (line or "").strip()
        if not t or t == msg or t in recent:
            continue
        recent.append(t)
        if len(recent) >= 4:
            break
    if is_short(msg):
        bits = [msg] if msg else []
        bits.extend(_flat(line) for line in recent[:3])
        return " ".join(bits).strip()[:500], kept
    extra = []
    have = set(content_words(msg))
    for line in recent[:3]:
        for w in content_words(line):
            if w not in have and w not in extra:
                extra.append(w)
            if len(extra) >= 8:
                break
        if len(extra) >= 8:
            break
    q = msg if not extra else (msg + " " + " ".join(extra))
    return q[:500], kept


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
    """Layer order, then score, then newer day. At most one echo, and none when three durable hits exist.

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
    durables = [h for h in prepared if h["layer"] in _DURABLE]
    drop_echo = len(durables) >= 3
    echoes = [h for h in prepared if h["layer"] == "echo"]
    rest = [h for h in prepared if h["layer"] != "echo"]
    if not drop_echo and echoes:
        echoes.sort(key=lambda h: -float(h.get("score") or 0))
        rest.append(echoes[0])
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


def open_ro(path):
    if not path:
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    except Exception:
        return None
