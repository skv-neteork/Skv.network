"""SKV memory v3/v4 recall: multi-query retrieval across episodes + dated facts with resolved relative dates.

Flag: memory_config.json "recall_plus" (default true); per request recall="basic" switches it off.
- Query decomposition (server side, no LLM): the question, its content words, and name+word pairs
  (e.g. "Melanie pottery", "Melanie camping") -> one batched embedding call + bm25 per subquery, fused by RRF,
  names and rare terms boosted. Finds many separate episodes for "what/which/how many" questions.
- view["facts"]: up to recall_max_facts short dated snippets (not already in hits), oldest first,
  within the "facts" budget, so the agent can aggregate and order events in time.
- v4 (default; recall="v3" gives the previous behaviour): temporal index - absolute dates/months/years named in
  the question ("on March 16, 2022", "in October 2023", "в марте 2023") select events of that period as an extra
  ranked list and boost them; low-content turns ("Thanks!", "Glad it helped") are dropped from facts; more facts
  within the same facts budget mechanics (recall_v4_max_facts).
- Relative dates ("yesterday", "last Saturday", "two weeks ago", "next month") are resolved against the
  event date and appended as <dates: yesterday=2023-05-07>. Applied to hits and facts.
"""
import re
import sqlite3
import time
from datetime import datetime, timedelta

from app.memory_v2 import clip, config, db_path, est_tokens, norm_date, strip_critical

_NAME = re.compile(r"\b([A-Z][a-z][\w'\-]{1,})\b")
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
WD = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "eleven": 11, "twelve": 12, "couple": 2, "a couple of": 2, "few": 3, "a few": 3, "several": 3}
_NUMRX = r"(\d+|a couple of|a few|couple|few|several|an|a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
QWORDS = {"What", "Which", "When", "Where", "Who", "Whom", "Whose", "Why", "How", "Did", "Does", "Do", "Is", "Are", "Was", "Were",
          "Has", "Have", "Had", "Can", "Could", "Would", "Should", "Will", "In", "On", "At", "The", "A", "An", "If", "Based",
          "According", "Since", "After", "Before", "During", "Considering", "Given", "Apart", "Besides", "Other", "Aside"}


def enabled(req=None):
    if req is not None and (getattr(req, "recall", None) or "").lower() == "basic":
        return False
    return bool(config().get("recall_plus", True))


def version(req=None):
    r = (getattr(req, "recall", None) or "").lower() if req is not None else ""
    if r in ("v3", "plus3"):
        return 3
    if r in ("v4", "plus4"):
        return 4
    return int(config().get("recall_version", 4))


# ---------------- relative dates ----------------
def _parse_date(s):
    s = norm_date(s or "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    return d.replace(year=y, month=m % 12 + 1, day=1)


def _n(s):
    s = s.lower().strip()
    return int(s) if s.isdigit() else NUM.get(s, NUM.get(s.split()[-1], 1))


def resolve_relative(text, date_str, limit=4):
    """[(phrase, resolved)] for relative time phrases in text, resolved against the event date."""
    d = _parse_date(date_str)
    if not d or not text:
        return []
    t = text.lower()
    out, seen = [], set()

    def add(p, v):
        if p not in seen and len(out) < limit:
            seen.add(p)
            out.append((p, v))
    day = lambda x: x.strftime("%Y-%m-%d")
    for p, delta in (("the day before yesterday", -2), ("yesterday", -1), ("tonight", 0), ("this morning", 0),
                     ("today", 0), ("the day after tomorrow", 2), ("tomorrow", 1)):
        if re.search(r"\b" + p + r"\b", t):
            add(p, day(d + timedelta(days=delta)))
    for m in re.finditer(r"\b(last|this|next|past)\s+(" + "|".join(WD) + r"|weekend)\b", t):
        which, wd = m.group(1), m.group(2)
        target = 5 if wd == "weekend" else WD.index(wd)
        if which in ("last", "past"):
            back = (d.weekday() - target) % 7 or 7
            v = d - timedelta(days=back)
        elif which == "next":
            fwd = (target - d.weekday()) % 7 or 7
            v = d + timedelta(days=fwd)
        else:
            v = d + timedelta(days=(target - d.weekday()))
        add(m.group(0), day(v) + (" (weekend)" if wd == "weekend" else ""))
    for m in re.finditer(r"\b(last|this|next|past)\s+(week|month|year|summer|winter|spring|fall|autumn)\b", t):
        which, unit = m.group(1), m.group(2)
        k = -1 if which in ("last", "past") else (1 if which == "next" else 0)
        if unit == "week":
            v = d + timedelta(weeks=k)
            add(m.group(0), "week of " + day(v - timedelta(days=v.weekday())))
        elif unit == "month":
            v = _add_months(d, k)
            add(m.group(0), f"{MONTHS[v.month - 1]} {v.year}")
        elif unit == "year":
            add(m.group(0), str(d.year + k))
        else:
            add(m.group(0), f"{unit} {d.year + k if unit != 'winter' or k else d.year}")
    for m in re.finditer(r"\b" + _NUMRX + r"\s+(day|days|week|weeks|month|months|year|years)\s+(ago|before|earlier|later|from now)\b", t):
        n, unit, dirw = _n(m.group(1)), m.group(2).rstrip("s"), m.group(3)
        sign = 1 if dirw in ("later", "from now") else -1
        if unit == "day":
            v = day(d + timedelta(days=sign * n))
        elif unit == "week":
            v = "~" + day(d + timedelta(weeks=sign * n))
        elif unit == "month":
            x = _add_months(d, sign * n)
            v = f"{MONTHS[x.month - 1]} {x.year}"
        else:
            v = str(d.year + sign * n)
        add(m.group(0), v)
    for m in re.finditer(r"\bin\s+" + _NUMRX + r"\s+(days|weeks|months|years|day|week|month|year)\b", t):
        n, unit = _n(m.group(1)), m.group(2).rstrip("s")
        if unit == "day":
            v = day(d + timedelta(days=n))
        elif unit == "week":
            v = "~" + day(d + timedelta(weeks=n))
        elif unit == "month":
            x = _add_months(d, n)
            v = f"{MONTHS[x.month - 1]} {x.year}"
        else:
            v = str(d.year + n)
        add(m.group(0), v)
    return out


def annotate(text, date_str):
    r = resolve_relative(text, date_str)
    if not r:
        return text
    return text + " <dates: " + "; ".join(f"{p}={v}" for p, v in r) + ">"



# ---------------- temporal index (v4) ----------------
_MON = {m.lower(): i + 1 for i, m in enumerate(MONTHS)}
_MON.update({m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)})
_MON.update({"sept": 9})
_RU_MON = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9,
           "октябр": 10, "ноябр": 11, "декабр": 12}
_MONRX = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"
_RUMONRX = r"(январ[ьяе]|феврал[ьяе]|март[ае]?|апрел[ьяе]|ма[йяе]|июн[ьяе]|июл[ьяе]|август[ае]?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе])"


def _ru_mon(w):
    w = w.lower()
    for k in sorted(_RU_MON, key=len, reverse=True):
        if w.startswith(k):
            return _RU_MON[k]
    return None


def _month_span(y, m):
    a = datetime(y, m, 1)
    return a, _add_months(a, 1) - timedelta(seconds=1)


_RELNUM = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|couple of|few|a couple of|a few)"
_RU_NUM = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
           "девять": 9, "десять": 10, "пару": 2, "несколько": 3}


def _now(now):
    if isinstance(now, datetime):
        return now
    d = _parse_date(now) if now else None
    return d or datetime.utcnow()


def relative_periods(q, now=None):
    """Relative periods in the question ("two weeks ago", "last month", "yesterday", "на прошлой неделе"),
    resolved against now (request as_of, default server time)."""
    t = (q or "").lower()
    n = _now(now)
    out = []
    def around(days, pad):
        c = n - timedelta(days=days)
        out.append((c - timedelta(days=pad), c + timedelta(days=pad)))
    if re.search(r"\b(the day before yesterday)\b|позавчера", t):
        around(2, 1)
    elif re.search(r"\byesterday\b|\bвчера", t):
        around(1, 1)
    for m in re.finditer(r"\b" + _RELNUM + r"\s+(day|days|week|weeks|month|months|year|years)\s+ago\b", t):
        k, unit = _n(m.group(1)), m.group(2).rstrip("s")
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * k
        around(days, max(2, days // 4))
    for m in re.finditer(r"(\d+|[а-я]+)?\s*(дн[яей]|день|недел[юиь]|месяц[аев]*|год[а]?|лет)\s+назад", t):
        w = m.group(1) or "один"
        k = int(w) if w.isdigit() else _RU_NUM.get(w, 1)
        u = m.group(2)
        days = (1 if u.startswith(("дн", "ден")) else 7 if u.startswith("недел") else 30 if u.startswith("месяц") else 365) * k
        around(days, max(2, days // 4))
    if re.search(r"\b(last|past) week\b|прошл(ой|ую) неделе|прошлую неделю", t):
        s0 = n - timedelta(days=n.weekday() + 7)
        out.append((s0 - timedelta(days=1), s0 + timedelta(days=8)))
    if re.search(r"\blast month\b|прошлом месяце", t):
        a, b = _month_span(_add_months(n, -1).year, _add_months(n, -1).month)
        out.append((a, b + timedelta(days=3)))
    if re.search(r"\blast year\b|прошлом году", t):
        out.append((datetime(n.year - 1, 1, 1), datetime(n.year - 1, 12, 31, 23, 59)))
    for m in re.finditer(r"\b(last|past)\s+(" + "|".join(WD) + r")\b", t):
        back = (n.weekday() - WD.index(m.group(2))) % 7 or 7
        around(back, 1)
    return out[:3]


def query_periods(q, now=None):
    """Absolute periods named in a question -> [(start, end)]. Day -> that day..+14d (people tell about it later),
    month -> the month..+1 month, year -> the year. Empty when the question names no date."""
    t = (q or "").lower()
    out = []
    def day(y, m, d):
        try:
            a = datetime(y, m, d)
        except ValueError:
            return
        out.append((a - timedelta(days=1), a + timedelta(days=14)))
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for m in re.finditer(r"\b" + _MONRX + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t):
        day(int(m.group(3)), _MON[m.group(1)], int(m.group(2)))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONRX + r"\.?,?\s+(\d{4})\b", t):
        day(int(m.group(3)), _MON[m.group(2)], int(m.group(1)))
    for m in re.finditer(r"\b(\d{1,2})\s+" + _RUMONRX + r"\s+(\d{4})", t):
        mm = _ru_mon(m.group(2))
        if mm:
            day(int(m.group(3)), mm, int(m.group(1)))
    if not out:
        for m in re.finditer(r"\b" + _MONRX + r"\.?,?\s+(?:of\s+)?(\d{4})\b", t):
            a, b = _month_span(int(m.group(2)), _MON[m.group(1)])
            out.append((a, _add_months(a, 2)))
        for m in re.finditer(_RUMONRX + r"\s+(\d{4})", t):
            mm = _ru_mon(m.group(1))
            if mm:
                a, b = _month_span(int(m.group(2)), mm)
                out.append((a, _add_months(a, 2)))
    if not out:
        for m in re.finditer(r"\b(?:in|during|of|since|в|году|год)\s+(19\d{2}|20\d{2})\b", t):
            y = int(m.group(1))
            out.append((datetime(y, 1, 1), datetime(y, 12, 31, 23, 59)))
    if not out:
        out = relative_periods(q, now)
    return out[:3]


def _in_periods(date_str, periods):
    d = _parse_date(date_str)
    return bool(d and any(a <= d <= b for a, b in periods))


def _dated_rows(user_id, periods, limit=400):
    """[(event_id, time_str)] of events whose event date falls in one of the periods."""
    if not periods:
        return []
    conn = sqlite3.connect(f"file:{db_path(user_id)}?mode=ro", uri=True, timeout=10)
    try:
        rows = conn.execute("SELECT event_id, time_str FROM event_metadata ORDER BY rowid DESC LIMIT 20000").fetchall()
    finally:
        conn.close()
    return [(e, ts) for e, ts in rows if _in_periods(ts, periods)][:limit]


_LOW = re.compile(r"\w{3,}", re.UNICODE)


def low_content(text, names=()):
    """True for turns with almost no information ("Thanks, Mel!", "Glad it helped ya!")."""
    from app.memory_v2_lens import STOP
    nl = {n.lower() for n in names}
    body = re.sub(r"(?m)^\s*[QA]:\s*[^:\n]{1,40}:\s*", " ", text or "")
    words = [w for w in _LOW.findall(body.lower()) if w not in STOP and w not in nl]
    return len(words) < int(config().get("recall_min_content_words", 5))


# ---------------- multi-query recall ----------------
def names_in(q):
    return [n for n in dict.fromkeys(_NAME.findall(q or "")) if n not in QWORDS]


def subqueries(q, bodies, max_q=6):
    from app.memory_v2_lens import query_terms
    names = names_in(q)
    _, terms = query_terms(q, bodies)
    content = [t for t in terms if t["df"] > 0 and t["term"] not in {n.lower() for n in names}]
    content.sort(key=lambda t: -t.get("idf", 0))
    qs = [q]
    kw = " ".join(t["term"] for t in content[:6])
    if names or kw:
        qs.append(" ".join(names + [kw]).strip())
    for t in content[:4]:
        qs.append((" ".join(names[:2]) + " " + t["term"]).strip())
    return list(dict.fromkeys(s for s in qs if s))[:max_q], names, content


def candidates(user_id, q, k=30, ver=3, now=None):
    from app import semantic as sem
    from app.memory_v2_lens import _scan, _norm
    bodies = _scan(user_id)
    qs, names, content = subqueries(q, bodies)
    lists = []
    try:
        tag = sem.active_tag()
        if tag != "bge":
            vecs = sem.embed(qs, tag)
            name = sem.account_name(user_id)
            for v in vecs:
                lists.append([e for e, _ in sem.STORE.search(tag, name, v, k=k) if e.startswith(user_id + "::")])
    except Exception as e:
        print(f"[recall] vector skipped: {e}", flush=True)
    for s in qs:
        lists.append([e for e, _ in sem.fts_ranked(user_id, s, limit=k)])
    periods = query_periods(q, now) if ver >= 4 else []
    in_period = set()
    if periods:
        dated = _dated_rows(user_id, periods)
        in_period = {e for e, _ in dated}
        if in_period:
            terms = [t["norm"] for t in content] + [_norm(n) for n in names]
            bmap = {e: b for _, e, b in bodies if e in in_period}
            scored = sorted(in_period, key=lambda e: -sum(1 for w in terms if w and w in bmap.get(e, "")))
            lists.append(scored[:k])
            lists.append(scored[:k])   # double weight: the question names this period
    fused = {}
    for lst in lists:
        for rank, eid in enumerate(lst):
            fused[eid] = fused.get(eid, 0.0) + 1.0 / (60 + rank + 1)
    if in_period:
        boost = float(config().get("recall_date_boost", 1.5))
        for eid in list(fused):
            if eid in in_period:
                fused[eid] *= boost
    if names or content:
        total = max(1, len(bodies))
        nn = [_norm(n) for n in names]
        nn = [n for n in nn if sum(1 for _, _, b in bodies if n in b) / total < 0.3]   # boost only distinctive names
        rare = [t["norm"] for t in content if t.get("idf", 0) > 0.5][:6]
        body = {e: b for _, e, b in bodies if e in fused}
        for eid in list(fused):
            b = body.get(eid, "")
            if nn and any(n in b for n in nn):
                fused[eid] *= 1.25
            hit = sum(1 for r in rare if r in b)
            if hit:
                fused[eid] *= 1 + 0.2 * hit
    ranked = sorted(fused.items(), key=lambda x: -x[1])
    return [e for e, _ in ranked], qs, names, content


def _best_snippet(text, words, cap_tokens, names=()):
    text = strip_critical(text or "") or (text or "")
    if est_tokens(text) <= cap_tokens:
        return text
    parts = [p.strip() for p in _SENT.split(text) if p and p.strip()]
    if not parts:
        return clip(text, cap_tokens)
    nl = {n.lower() for n in names}
    lw = [w.lower() for w in words if w]
    def score(p):
        pl = p.lower()
        return sum((0.2 if w in nl else 1.0) for w in lw if w in pl)
    scored = sorted(range(len(parts)), key=lambda i: (-score(parts[i]), i))
    keep, used = [], 0
    for i in scored:
        tk = est_tokens(parts[i])
        if used and used + tk > cap_tokens:
            continue
        keep.append(i)
        used += tk
        if used >= cap_tokens:
            break
    return clip(" ".join(parts[i] for i in sorted(keep)), cap_tokens)


def facts(user_id, q, budget, skip_ids=(), max_facts=None, v=3, now=None):
    cfg = config()
    if v >= 4:
        max_facts = max_facts or int(cfg.get("recall_v4_max_facts", 30))
        k = int(cfg.get("recall_v4_k", 40))
    else:
        max_facts = max_facts or int(cfg.get("recall_max_facts", 20))
        k = 30
    cap = int(cfg.get("recall_snippet_tokens", 110))
    ranked, qs, names, content = candidates(user_id, q, k=k, ver=v, now=now)
    ids = [e for e in ranked if e not in set(skip_ids)][:max_facts * (3 if v >= 4 else 2)]
    if not ids:
        return None
    conn = sqlite3.connect(f"file:{db_path(user_id)}?mode=ro", uri=True, timeout=10)
    try:
        rows = {r[1]: r for r in conn.execute(
            "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ids)), ids)}
    finally:
        conn.close()
    words = names + [t["term"] for t in content]
    items, used = [], 0
    for eid in ids:
        r = rows.get(eid)
        if not r:
            continue
        date = norm_date(r[2])
        if v >= 4 and low_content(r[3], names):
            continue
        sn = annotate(_best_snippet(r[3], words, cap, names), date)
        if v >= 4:
            sn = re.sub(r"\nA:\s*$", "", sn)
        tk = est_tokens(sn) + 14
        if used + tk > budget or len(items) >= max_facts:
            break
        used += tk
        items.append({"event_id": eid, "date": date, "rowid": r[0], "text": sn})
    items.sort(key=lambda x: (x["date"], x["rowid"]))
    for it in items:
        it.pop("rowid", None)
    if v >= 4:
        return {"note": "More episodes for this question (not in hits), oldest first, so a later item is newer: "
                        "if a fact changed, the latest date wins. Aggregate across them; use the dates.",
                "subqueries": qs, "items": items}
    return {"note": "More episodes for this question (not in hits), oldest first. Aggregate across them; use the dates.",
            "subqueries": qs, "items": items}


def augment(view, user_id, q, budget, v=3, now=None):
    """Annotate hits with resolved dates and add view['facts']. Never raises."""
    t0 = time.time()
    for h in view.get("hits") or []:
        h["text"] = annotate(h.get("text", ""), h.get("date", ""))
    lens = view.get("lens") or {}
    for c in lens.get("clusters") or []:
        ce = c.get("center") or {}
        if ce.get("text"):
            ce["text"] = annotate(ce["text"], ce.get("date", ""))
    if budget and budget > 0:
        skip = [h.get("event_id") for h in view.get("hits") or []]
        f = facts(user_id, q, budget, skip_ids=skip, v=v, now=now)
        if f and f["items"]:
            view["facts"] = f
    return view
