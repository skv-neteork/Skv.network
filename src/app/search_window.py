"""B11 date window. The agent picks the dates. This module does not parse phrases.

Filter the window first (active memory line, calendar date of time_str as written),
then either return every event in order or rank the whole window.
Score = 0.85 * cosine(L2-normalised vectors) + 0.15 * exact token overlap.
No stemming, no BM25, no RRF, no server-side widening.

WINDOW_CAP is the measured perf limit (2026-11-14, benchlme3, mml12):
3988 events took 0.14 s to read vectors and 0.37 s to overlap; ~20k events
is about 2.5 s. Above that the call is 422 window_too_large. Nothing below
the cap is dropped before ranking.
"""
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta

from app.memory_v2 import clip as _clip, db_path, est_tokens
from app import search_line as _ln

WINDOW_CAP = 20000
LIMIT_DEFAULT = 20
LIMIT_MAX = 100
BUDGET_FLOOR = 200
HIT_CAP = 250          # display tokens per ranked hit, so the top 10 fit in the default 3000
SCORE_COS = 0.85
SCORE_OV = 0.15
_YMD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DUR = re.compile(r"^(\d+)([dhw])$", re.I)
_TOK = re.compile(r"\w+", re.UNICODE)
# Hint only. These phrases are not turned into a filter.
_REL = re.compile(
    r"\b(yesterday|today|tomorrow|ago|recently|last\s+week|last\s+month|"
    r"вчера|сегодня|завтра|позавчера|назад|недел\w*|"
    r"gestern|vorgestern|heute|morgen|"
    r"ayer|hoy|mañana|manana|"
    r"hier|aujourd'hui|demain)\b",
    re.I)
EXAMPLE = 'memory_search(query="received a gift", date="2023-03-04")'
WIDEN_EXAMPLE = 'memory_search(query="received a gift", since="2023-03-01", until="2023-03-08")'


class WindowError(Exception):
    def __init__(self, status, code, detail, example=None):
        self.status = int(status)
        self.code = code
        self.detail = detail
        self.example = example or EXAMPLE
        super().__init__(detail)

    def body(self):
        return {"ok": False, "error": self.code, "detail": self.detail,
                "hint": self.detail, "example": self.example}


def relative_phrase(query):
    return bool(_REL.search(query or ""))


def tokens(text):
    t = unicodedata.normalize("NFKC", text or "").lower()
    return set(_TOK.findall(t))


def overlap(query, text):
    q = tokens(query)
    if not q:
        return 0.0
    return len(q & tokens(text)) / float(len(q))


def _ymd(s):
    m = _YMD.match(s or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def _blank(v):
    s = ("" if v is None else str(v)).strip()
    return "" if s.lower() in ("unknown", "?") else s


def _now(now):
    if isinstance(now, datetime):
        return now
    if now:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(now)[:19], fmt)
            except ValueError:
                pass
    return datetime.utcnow()


def _bound_one(raw, now, side):
    """Return (kind, value). kind is date (calendar) or stamp (compared to time_str as written)."""
    m = _DUR.match(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        sec = n * {"h": 3600, "d": 86400, "w": 604800}[unit]
        stamp = (_now(now) - timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M")
        return "stamp", stamp
    day = _ymd(raw[:10])
    if day and raw == day.strftime("%Y-%m-%d"):
        return "date", day.strftime("%Y-%m-%d")
    if day and re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", raw):
        return "stamp", raw[:16].replace("T", " ")
    raise WindowError(400, "bad_date",
                      "%s must be YYYY-MM-DD or a duration like 3d/12h/2w (got %r)" % (side, raw[:40]))


def parse(date=None, since=None, until=None, time=None, now=None):
    """Explicit params only. Returns a bounds dict. Raises WindowError (400)."""
    time_s = ("" if time is None else str(time)).strip().lower()
    if time_s not in ("", "unknown", "?"):
        raise WindowError(400, "bad_time",
                          "time must be omitted or 'unknown'. Convert the date yourself and pass date or since/until.",
                          EXAMPLE)
    date_s = ("" if date is None else str(date)).strip()
    since_raw = ("" if since is None else str(since)).strip()
    until_raw = ("" if until is None else str(until)).strip()
    date_set = bool(date_s) and date_s.lower() not in ("unknown", "?")
    since_set = bool(since_raw) and since_raw.lower() not in ("unknown", "?")
    until_set = bool(until_raw) and until_raw.lower() not in ("unknown", "?")
    explicit_unknown = time_s in ("unknown", "?")
    if explicit_unknown and (date_set or since_set or until_set):
        raise WindowError(400, "conflict",
                          "time=unknown cannot be combined with date or since/until. Drop one of them.")
    if date_s.lower() in ("unknown", "?"):
        date_set = False
    if date_set and (since_set or until_set):
        raise WindowError(400, "conflict",
                          "Pass date or since/until, not both. date=D is the window [D-1, D+1]. Exact day is since=until=D.")
    if date_set:
        day = _ymd(date_s)
        if not day or date_s != day.strftime("%Y-%m-%d"):
            raise WindowError(400, "bad_date", "date must be YYYY-MM-DD (got %r)" % date_s[:40])
        lo = (day - timedelta(days=1)).strftime("%Y-%m-%d")
        hi = (day + timedelta(days=1)).strftime("%Y-%m-%d")
        return {"window_set": True, "since": lo, "until": hi, "since_kind": "date", "until_kind": "date",
                "note": None}
    lo = hi = None
    lo_kind = hi_kind = None
    if since_set:
        lo_kind, lo = _bound_one(since_raw, now, "since")
    if until_set:
        hi_kind, hi = _bound_one(until_raw, now, "until")
    if lo and hi:
        lo_key = lo if lo_kind == "stamp" else lo + " 00:00"
        hi_key = hi if hi_kind == "stamp" else hi + " 23:59"
        if lo_key > hi_key:
            raise WindowError(400, "since_after_until",
                              "since is after until. The server does not swap them.")
    if lo or hi:
        return {"window_set": True, "since": lo, "until": hi, "since_kind": lo_kind, "until_kind": hi_kind,
                "note": None}
    covered = "all time (window unknown)"
    return {"window_set": False, "since": None, "until": None, "since_kind": None, "until_kind": None,
            "note": "no window set", "covered_window": covered}


def paging(limit, offset):
    if limit is None or (isinstance(limit, str) and str(limit).strip() == ""):
        limit = LIMIT_DEFAULT
    if offset is None or (isinstance(offset, str) and str(offset).strip() == ""):
        offset = 0
    try:
        limit_i = int(limit)
        offset_i = int(offset)
    except (TypeError, ValueError):
        raise WindowError(400, "bad_paging", "limit and offset must be integers. limit default 20, max 100.")
    if limit_i < 1 or limit_i > LIMIT_MAX or offset_i < 0:
        raise WindowError(400, "bad_paging",
                          "limit must be 1..%d (default %d) and offset must be >= 0." % (LIMIT_MAX, LIMIT_DEFAULT))
    return limit_i, offset_i


def _in_window(ts, bounds):
    ts = ts or ""
    if not ts:
        return False
    day = ts[:10]
    lo, hi = bounds.get("since"), bounds.get("until")
    if lo:
        if bounds.get("since_kind") == "date":
            if day < lo:
                return False
        elif ts < lo:
            return False
    if hi:
        if bounds.get("until_kind") == "date":
            if day > hi:
                return False
        elif ts > hi:
            return False
    return True


def _skip_import(kind, head, eid, exclude_imports):
    if not exclude_imports:
        return False
    if (kind or "") == "import":
        return True
    if (head or "").startswith("[archived]"):
        return True
    if re.search(r"(chat_grok_test|sandbox_event|smoke|probe_)", eid or "", re.I):
        return True
    return False


def collect(uid, bounds, exclude_imports=False, db=None):
    """Events inside the window on the active line. Reads time_str first, bodies after the cap check."""
    path = db or db_path(uid)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        where = ["coalesce(time_str,'') != ''"]
        args = []
        lo, hi = bounds.get("since"), bounds.get("until")
        if lo and bounds.get("since_kind") == "date":
            where.append("substr(time_str,1,10) >= ?")
            args.append(lo)
        elif lo:
            where.append("time_str >= ?")
            args.append(lo)
        if hi and bounds.get("until_kind") == "date":
            where.append("substr(time_str,1,10) <= ?")
            args.append(hi)
        elif hi:
            where.append("time_str <= ?")
            args.append(hi)
        sql = ("SELECT event_id, time_str, kind, substr(coalesce(raw_dialogue,''),1,12) "
               "FROM event_metadata WHERE " + " AND ".join(where))
        meta = []
        for eid, ts, kind, head in conn.execute(sql, args):
            if not _ln.visible(eid):
                continue
            if _skip_import(kind, head, eid, exclude_imports):
                continue
            if not _in_window(ts, bounds):
                continue
            meta.append((eid, ts or ""))
        if len(meta) > WINDOW_CAP:
            raise WindowError(
                422, "window_too_large",
                "This window has %d events. The cap is %d (measured: ~2.5 s to rank 20000). Narrow since/until."
                % (len(meta), WINDOW_CAP),
                WIDEN_EXAMPLE)
        bodies = {}
        ids = [e for e, _ in meta]
        for i in range(0, len(ids), 400):
            ch = ids[i:i + 400]
            q = "SELECT event_id, raw_dialogue FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ch))
            for eid, raw in conn.execute(q, ch):
                bodies[eid] = raw or ""
    finally:
        conn.close()
    rows = []
    for eid, ts in meta:
        rows.append({"id": eid, "date": ts, "content": bodies.get(eid, "")})
    rows.sort(key=lambda r: (r["date"], r["id"]))
    return rows


def cosines(uid, eids, query):
    """Cosine of L2-normalised vectors, as stored. Missing vector -> 0. Not rescaled to 0..1."""
    if not eids or not (query or "").strip():
        return {e: 0.0 for e in eids}
    from app import semantic as sem
    tag = sem.active_tag()
    name = sem.account_name(uid)
    try:
        import numpy as np
        entry = sem.STORE._load(tag, name)
        qv = sem.embed([query], tag)[0]
    except Exception as exc:
        print("[search_window] vectors skipped: %s" % type(exc).__name__, flush=True)
        return {e: 0.0 for e in eids}
    if not entry or not entry.get("ids"):
        return {e: 0.0 for e in eids}
    pos = entry["pos"]
    labels, wanted = [], []
    for eid in eids:
        i = pos.get(eid)
        if i is not None:
            labels.append(i)
            wanted.append(eid)
    out = {e: 0.0 for e in eids}
    if not labels:
        return out
    vecs = np.asarray(entry["index"].get_items(labels), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1)
    norms[norms == 0] = 1.0
    q = np.asarray(qv, dtype="float32")
    qn = float(np.linalg.norm(q)) or 1.0
    dots = (vecs / norms[:, None]) @ (q / qn)
    for eid, s in zip(wanted, dots.tolist()):
        out[eid] = float(s)
    return out


def _show(text, cap):
    full = text or ""
    if est_tokens(full) <= cap:
        return full, False
    return _clip(full, cap), True


def _pack_page(ordered, budget, limit, offset, scored):
    budget = max(BUDGET_FLOOR, int(budget or 3000))
    page = []
    used = 0
    idx = offset
    # Ranked (and over-budget chrono) pages clip so the top of the order is visible.
    per = HIT_CAP if scored else 10 ** 6
    while idx < len(ordered) and len(page) < limit:
        row = ordered[idx]
        text, cut = _show(row["content"], per)
        cost = est_tokens(text) + 24
        if page and used + cost > budget:
            break
        if not page and cost > budget:
            text, cut = _show(row["content"], max(40, budget - 24))
            cost = est_tokens(text) + 24
        hit = {"id": row["id"], "date": row["date"], "content": text,
               "score": row.get("score"), "truncated": cut}
        page.append(hit)
        used += cost
        idx += 1
    has_more = idx < len(ordered)
    return page, used, (idx if has_more else None), has_more


def order_rows(rows, query, budget, limit, offset, cosine_fn=None, uid="", always_rank=False):
    """Chronological when there is no query or the full texts fit. Else score every row."""
    budget = max(BUDGET_FLOOR, int(budget or 3000))
    full_cost = sum(est_tokens(r["content"]) + 24 for r in rows)
    has_query = bool((query or "").strip())
    scored = has_query and len(rows) > 0 and (always_rank or full_cost > budget)
    ordered = list(rows)
    if scored:
        fn = cosine_fn or (lambda u, ids, q: cosines(u, ids, q))
        cos = fn(uid, [r["id"] for r in ordered], query)
        for r in ordered:
            ov = overlap(query, r["content"])
            r["score"] = round(SCORE_COS * float(cos.get(r["id"], 0.0)) + SCORE_OV * ov, 5)
        ordered.sort(key=lambda r: (-float(r["score"]), r["date"], r["id"]))
    else:
        for r in ordered:
            r["score"] = None
        ordered.sort(key=lambda r: (r["date"], r["id"]))
    page, used, nxt, more = _pack_page(ordered, budget, limit, offset, scored=scored or full_cost > budget)
    return {"ordered_n": len(ordered), "hits": page, "tokens_used": used,
            "next_offset": nxt, "has_more": more, "scored": scored, "full_cost": full_cost}


def widen_hint(bounds, query):
    """Ready call the agent can make. The server does not run it."""
    lo, hi = bounds.get("since"), bounds.get("until")
    q = (query or "").replace('"', "")
    parts = []
    if lo and bounds.get("since_kind") == "date":
        lo_d = (_ymd(lo) - timedelta(days=3)).strftime("%Y-%m-%d")
    else:
        lo_d = lo
    if hi and bounds.get("until_kind") == "date":
        hi_d = (_ymd(hi) + timedelta(days=3)).strftime("%Y-%m-%d")
    else:
        hi_d = hi
    call = "memory_search("
    bits = []
    if q:
        bits.append('query="%s"' % q[:180])
    if lo_d:
        bits.append('since="%s"' % lo_d)
    if hi_d:
        bits.append('until="%s"' % hi_d)
    call += ", ".join(bits) + ")"
    return "widen ±3 days: " + call


def _budget(budget):
    if budget is None or budget == "":
        from app.memory_v2 import config as cfg
        c = cfg()
        b = int((c.get("budgets") or {}).get("search_pack", 3000) or 3000)
        cap = int((c.get("caps") or {}).get("search_pack", 12000) or 12000)
        return max(600, min(cap, b))
    return max(BUDGET_FLOOR, int(budget))


def run(uid, query="", date=None, since=None, until=None, time=None, budget=None, limit=None,
        offset=0, exclude_imports=False, now=None, db=None, cosine_fn=None, always_rank=False):
    bounds = parse(date, since, until, time, now=now)
    if not bounds["window_set"]:
        raise WindowError(400, "no_window", "run() is the window path. Omit dates for a normal search.")
    limit_i, offset_i = paging(limit, offset)
    b = _budget(budget)
    rows = collect(uid, bounds, exclude_imports=exclude_imports, db=db)
    page = order_rows(rows, query, b, limit_i, offset_i, cosine_fn=cosine_fn, uid=uid,
                      always_rank=always_rank)
    covered = {"since": bounds["since"], "until": bounds["until"]}
    hint = widen_hint(bounds, query)
    nxt = hint
    if page["has_more"]:
        bits = []
        if (query or "").strip():
            bits.append('query="%s"' % (query or "").replace('"', "")[:180])
        if bounds["since"]:
            bits.append('since="%s"' % bounds["since"])
        if bounds["until"]:
            bits.append('until="%s"' % bounds["until"])
        bits.append("offset=%d" % page["next_offset"])
        nxt = "memory_search(" + ", ".join(bits) + "); " + hint
    return {
        "hits": page["hits"],
        "n": len(page["hits"]),
        "total_in_window": len(rows),
        "covered_window": covered,
        "window_set": True,
        "window": {"since": bounds["since"], "until": bounds["until"], "hard": True,
                   "soft": False, "phrase": None, "window_set": True},
        "offset": offset_i,
        "next_offset": page["next_offset"],
        "has_more": page["has_more"],
        "limit": limit_i,
        "budget_tokens": b,
        "tokens_used": page["tokens_used"],
        "scored": page["scored"],
        "note": None,
        "truncated": bool(page["has_more"]),
        "hint": hint,
        "next": nxt,
    }
