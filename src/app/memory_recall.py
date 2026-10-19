"""SKV memory v3 recall: multi-query retrieval across episodes + dated facts with resolved relative dates.

Flag: memory_config.json "recall_plus" (default true); per request recall="basic" switches it off.
- Query decomposition (server side, no LLM): the question, its content words, and name+word pairs
  (e.g. "Melanie pottery", "Melanie camping") -> one batched embedding call + bm25 per subquery, fused by RRF,
  names and rare terms boosted. Finds many separate episodes for "what/which/how many" questions.
- view["facts"]: up to recall_max_facts short dated snippets (not already in hits), oldest first,
  within the "facts" budget, so the agent can aggregate and order events in time.
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


def candidates(user_id, q, k=30):
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
    fused = {}
    for lst in lists:
        for rank, eid in enumerate(lst):
            fused[eid] = fused.get(eid, 0.0) + 1.0 / (60 + rank + 1)
    if names or content:
        nn = [_norm(n) for n in names]
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


def _best_snippet(text, words, cap_tokens):
    text = strip_critical(text or "") or (text or "")
    parts = [p.strip() for p in _SENT.split(text) if p and p.strip()]
    if not parts:
        return clip(text, cap_tokens)
    lw = [w.lower() for w in words if w]
    scored = sorted(range(len(parts)), key=lambda i: -sum(1 for w in lw if w in parts[i].lower()))
    keep, used = [], 0
    for i in scored:
        tk = est_tokens(parts[i])
        if used and used + tk > cap_tokens:
            continue
        keep.append(i)
        used += tk
        if used >= cap_tokens:
            break
    out = " … ".join(parts[i] for i in sorted(keep))
    return clip(out, cap_tokens)


def facts(user_id, q, budget, skip_ids=(), max_facts=None):
    cfg = config()
    max_facts = max_facts or int(cfg.get("recall_max_facts", 24))
    cap = int(cfg.get("recall_snippet_tokens", 70))
    ranked, qs, names, content = candidates(user_id, q)
    ids = [e for e in ranked if e not in set(skip_ids)][:max_facts * 2]
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
        sn = annotate(_best_snippet(r[3], words, cap), date)
        tk = est_tokens(sn) + 14
        if used + tk > budget or len(items) >= max_facts:
            break
        used += tk
        items.append({"event_id": eid, "date": date, "rowid": r[0], "text": sn})
    items.sort(key=lambda x: (x["date"], x["rowid"]))
    for it in items:
        it.pop("rowid", None)
    return {"note": "More episodes for this question (not in hits), oldest first. Aggregate across them; use the dates.",
            "subqueries": qs, "items": items}


def augment(view, user_id, q, budget):
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
        f = facts(user_id, q, budget, skip_ids=skip)
        if f and f["items"]:
            view["facts"] = f
    return view
