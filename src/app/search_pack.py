"""B10 mini-lens pack: one search core for memory_search, turn facts, and /memory follow-up.

Pipeline: retrieve wide (vector ~80, FTS ~80, name-exact ~40) -> wrrf -> top 50 -> top 20
-> diversity (max 2 per episode, max 3 per day unless the query is date-specific) -> top N.
Each hit: centre verbatim (cap ~400 tokens) + neighbours +-1 (widen to +-2 when short)
+ covering L1 + L2 + ev ids + absolute date + match_reason.
Budget default 3000 tokens; N = floor(budget/600) clamped 3..10.
Never silent-cut: truncated flag + hint to memory_search(focus_event_id=...).
"""
import json, os, re, sqlite3, time
from datetime import datetime, timedelta

from app.memory_v2 import config as _mcfg, db_path, est_tokens, clip as _clip
from app import search_line as _ln

CAP_CENTRE = 400
TOK_PER_HIT = 600
BUDGET_DEFAULT = 3000
BUDGET_CAP = 12000


def budget_of(n=None, cfg=None):
    cfg = cfg or _mcfg()
    b = int((cfg.get("budgets") or {}).get("search_pack", BUDGET_DEFAULT) or BUDGET_DEFAULT)
    cap = int((cfg.get("caps") or {}).get("search_pack", BUDGET_CAP) or BUDGET_CAP)
    if n is not None:
        try:
            b = int(n)
        except Exception:
            pass
    return max(600, min(cap, b))


def n_hits(budget):
    return max(3, min(10, int(budget) // TOK_PER_HIT))


def follow_next(query, hits, offset=0, total=None, reliable=True, focus_event_id=""):
    """Ready-to-call next step. Follow-ups stay on memory_search; recall_later only if that fails."""
    q = json.dumps(query or "", ensure_ascii=False)
    if not hits:
        return "nothing found: memory_recall_later(query=%s)" % q
    pick = 0
    for i, h in enumerate(hits):
        if h.get("truncated") or ((h.get("centre") or {}).get("truncated")):
            pick = i
            break
    ev = (hits[pick].get("ev") or _ev(hits[pick].get("event_id")))
    num = int(offset or 0) + pick + 1
    parts = ["more around #%d: memory_search(focus_event_id=%s)" % (num, ev)]
    if query and total is not None and int(offset or 0) + len(hits) < int(total):
        parts.append("more results: memory_search(query=%s, offset=%d)" % (q, int(offset or 0) + len(hits)))
    if not reliable:
        parts.append("nothing found: memory_recall_later(query=%s)" % q)
    return "; ".join(parts)


# ---------- relative dates (basic) ----------
_HARD = (
    (re.compile(r"\b(yesterday|вчера)\b", re.I), "yesterday", 1, 1),
    (re.compile(r"\b(today|сегодня)\b", re.I), "today", 0, 0),
    (re.compile(r"\b(last\s+week|прошл(?:ой|ую|ая)\s+недел\w*)\b", re.I), "last_week", 7, 1),
    (re.compile(r"\b(this\s+week|на\s+этой\s+недел\w*)\b", re.I), "this_week", 6, 0),
)
_SOFT = re.compile(r"\b(recently|lately|недавно|в\s+последнее\s+время)\b", re.I)
_YMD = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _now(now=None):
    if isinstance(now, datetime):
        return now
    if now:
        for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(now)[:19], f)
            except Exception:
                pass
    return datetime.utcnow()


def resolve_time(query, now=None, since=None, until=None):
    """Explicit dates / yesterday / last week = hard filter. 'recently' = soft boost only."""
    q = query or ""
    now = _now(now)
    hard, phrase, since_s, until_s = False, None, since, until
    m = _YMD.search(q)
    if m:
        hard, phrase = True, m.group(1)
        since_s = since_s or (m.group(1) + " 00:00")
        until_s = until_s or (m.group(1) + " 23:59")
    else:
        for rx, name, back, until_back in _HARD:
            if rx.search(q):
                hard, phrase = True, name
                a = (now - timedelta(days=back)).strftime("%Y-%m-%d") + " 00:00"
                b = (now - timedelta(days=until_back)).strftime("%Y-%m-%d") + " 23:59"
                since_s, until_s = since_s or a, until_s or b
                break
    soft = bool(_SOFT.search(q)) and not hard
    if soft:
        phrase = "recently"
    return {"since": since_s, "until": until_s, "hard": hard, "soft": soft, "phrase": phrase,
            "now": now.strftime("%Y-%m-%d %H:%M:%S")}


def date_specific(query, window=None):
    w = window or resolve_time(query)
    return bool(w.get("hard") or _YMD.search(query or ""))


# ---------- retrieve ----------
def name_exact(uid, query, limit=40):
    from app import search_v2 as _v2
    names = _v2.anchors(query)
    if not names:
        return []
    try:
        conn = sqlite3.connect(_v2._db(uid), timeout=10)
    except Exception:
        return []
    try:
        _v2.sync(conn)
        clause = _ln.attach_vis(conn)
        seen, out = set(), []
        for n in names[:6]:
            st = _v2.stem(n)
            rows = conn.execute(
                "SELECT event_id, bm25(events_fts_stem) FROM events_fts_stem WHERE events_fts_stem MATCH ? "
                "AND event_id IN (SELECT event_id FROM event_metadata) %s "
                "ORDER BY bm25(events_fts_stem) LIMIT ?" % clause,
                ('"' + st.replace('"', "") + '"', limit)).fetchall()
            for eid, sc in rows:
                if eid not in seen:
                    seen.add(eid)
                    out.append((eid, float(-sc)))
                if len(out) >= limit:
                    return out
    except Exception as e:
        print("[search_pack] name_exact skipped: %s" % type(e).__name__, flush=True)
        return []
    finally:
        conn.close()
    return out[:limit]


def retrieve_wide(uid, query, top_k=50, since=None, until=None, exclude_imports=False, source=None):
    """Line-scoped wide retrieve. Returns the usual text_search dicts, extra keys allowed."""
    from app import q2s as _q2s
    k = max(50, int(top_k or 50))
    out = _q2s.text_core(uid, query, k, since, until, exclude_imports, source)
    have = {o.get("event_id") for o in out}
    extra = []
    try:
        extra = name_exact(uid, query, 40)
    except Exception as e:
        print("[search_pack] name branch skipped: %s" % type(e).__name__, flush=True)
    if extra:
        from app.search_text import _out as _fmt
        add = _fmt(uid, extra)
        out = out + [x for x in add if x.get("event_id") not in have]
    out = [o for o in out if _ln.visible(o.get("event_id"))]
    return out[:k]


def _rowid_map(uid, eids):
    if not eids:
        return {}
    conn = sqlite3.connect(f"file:{db_path(uid)}?mode=ro", uri=True, timeout=10)
    try:
        out = {}
        for i in range(0, len(eids), 400):
            ch = [e for e in eids[i:i + 400] if e]
            if not ch:
                continue
            for rid, eid, ts, raw in conn.execute(
                    "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE event_id IN (%s)"
                    % ",".join("?" * len(ch)), ch):
                out[eid] = {"rowid": rid, "time": ts, "raw": raw or ""}
    finally:
        conn.close()
    return out


def diversify(hits, query, window=None, gap=3):
    """Max 2 per episode (rowid gap), max 3 per calendar day unless the query is date-specific."""
    spec = date_specific(query, window)
    uid = ""
    if hits and "::" in str(hits[0].get("event_id") or ""):
        uid = hits[0]["event_id"].split("::", 1)[0]
    meta = _rowid_map(uid, [h.get("event_id") for h in hits]) if uid else {}
    per_ep, per_day, accepted, out = {}, {}, [], []
    for h in hits:
        eid = h.get("event_id")
        m = meta.get(eid) or {}
        rid = m.get("rowid") or 0
        day = str(m.get("time") or (h.get("metadata") or {}).get("time_str") or "")[:10]
        ep = rid
        for ar, ae in accepted:
            if abs(rid - ar) <= gap:
                ep = ae
                break
        if per_ep.get(ep, 0) >= 2:
            continue
        if (not spec) and day and per_day.get(day, 0) >= 3:
            continue
        per_ep[ep] = per_ep.get(ep, 0) + 1
        if day:
            per_day[day] = per_day.get(day, 0) + 1
        accepted.append((rid, ep))
        h = dict(h)
        h["_rowid"] = rid
        h["_day"] = day
        out.append(h)
        if len(out) >= 20:
            break
    return out


def _cover(conn, rowid):
    l1 = l2 = ""
    l1_id = l2_id = None
    try:
        r = conn.execute(
            "SELECT session_id, topic, summary_text FROM summary_l1 "
            "WHERE from_rowid <= ? AND to_rowid >= ? ORDER BY (to_rowid - from_rowid) ASC LIMIT 1",
            (rowid, rowid)).fetchone()
        if r:
            l1_id, l1 = r[0], ("%s: %s" % (r[1] or "", r[2] or "")).strip(": ")
    except Exception:
        pass
    try:
        r = conn.execute(
            "SELECT id, text FROM summary_l2_blocks WHERE from_rowid <= ? AND to_rowid >= ? "
            "AND source != 'legacy_summary_l2' ORDER BY (source='agent') DESC, (to_rowid - from_rowid) ASC LIMIT 1",
            (rowid, rowid)).fetchone()
        if r:
            l2_id, l2 = r[0], r[1] or ""
    except Exception:
        pass
    return l1, l2, l1_id, l2_id


def _neigh(conn, rowid, n):
    if n <= 0:
        return [], []
    b = conn.execute(
        "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid < ? ORDER BY rowid DESC LIMIT ?",
        (rowid, n)).fetchall() if rowid else []
    a = conn.execute(
        "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid > ? ORDER BY rowid ASC LIMIT ?",
        (rowid, n)).fetchall() if rowid else []
    return list(reversed(b)), a


def _ev(eid):
    return (eid or "").split("::")[-1]


def _part(eid, ts, raw, cap):
    t = raw or ""
    tok = est_tokens(t)
    cut = tok > cap
    if cut:
        t = _clip(t, cap)
    return {"ev": _ev(eid), "event_id": eid, "date": str(ts or "")[:16], "text": t,
            "truncated": cut, "tokens": min(tok, cap)}


def package(uid, hits, query, budget=None, window=None):
    budget = budget_of(budget)
    n = n_hits(budget)
    used, items, truncated = 0, [], False
    hint = "memory_search(focus_event_id=<ev>) for a wider episode; memory_recall_later for a deep search"
    if not hits:
        nxt = follow_next(query, [], 0, 0, True, "")
        return {"hits": [], "n": 0, "budget_tokens": budget, "window": window,
                "truncated": False, "hint": hint, "next": nxt}
    conn = sqlite3.connect(f"file:{db_path(uid)}?mode=ro", uri=True, timeout=10)
    try:
        for h in hits[:n]:
            eid = h.get("event_id")
            row = conn.execute(
                "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE event_id=?",
                (eid,)).fetchone()
            if not row:
                # keep the summary-only hit
                summ = h.get("summary") or ""
                item = {"ev": _ev(eid), "event_id": eid, "date": (h.get("metadata") or {}).get("time_str"),
                        "score": h.get("score"), "centre": {"text": summ, "truncated": False},
                        "neighbours": [], "l1": "", "l2": "", "match_reason": h.get("source") or "search",
                        "truncated": False}
                items.append(item)
                used += est_tokens(summ) + 40
                continue
            rid, _, ts, raw = row
            try:
                from app import archive_recall as _ar
                if _ar.is_marker(raw):
                    t = _ar.full_text(conn, eid)
                    if t:
                        raw = t
            except Exception:
                pass
            centre = _part(eid, ts, raw, CAP_CENTRE)
            left = budget - used - 80
            rad = 1
            nb_tok = 0
            before, after = _neigh(conn, rid, 1)
            for _rid, _e, _t, _raw in before + after:
                nb_tok += min(est_tokens(_raw or ""), 180)
            if rad == 1 and nb_tok < 120 and left > 400:
                b2, a2 = _neigh(conn, rid, 2)
                before, after = b2, a2
                rad = 2
            neigh = [_part(e, t, r, 180) for _, e, t, r in before + after]
            l1, l2, l1_id, l2_id = _cover(conn, rid)
            l1s, l2s = _clip(l1, 120) if l1 else "", _clip(l2, 60) if l2 else ""
            reason = h.get("source") or "hybrid"
            if h.get("score") is not None:
                reason = "%s score=%.4f" % (reason, float(h["score"]))
            item = {"ev": _ev(eid), "event_id": eid, "date": str(ts or "")[:16], "score": h.get("score"),
                    "centre": centre, "neighbours": neigh, "neighbour_radius": rad,
                    "l1": l1s, "l2": l2s, "l1_id": ("l1:%s" % l1_id) if l1_id else None,
                    "l2_id": ("l2:%s" % l2_id) if l2_id else None,
                    "match_reason": reason,
                    "truncated": bool(centre.get("truncated") or any(x.get("truncated") for x in neigh))}
            cost = centre.get("tokens", 0) + sum(x.get("tokens", 0) for x in neigh) + est_tokens(l1s) + est_tokens(l2s) + 50
            if items and used + cost > budget:
                truncated = True
                break
            used += cost
            items.append(item)
            if len(items) >= n:
                if len(hits) > n:
                    truncated = True
                break
    finally:
        conn.close()
    if truncated:
        hint = "truncated:true — open one hit with memory_search(focus_event_id=<ev>); deeper: memory_recall_later"
    return {"hits": items, "n": len(items), "budget_tokens": budget, "tokens_used": used,
            "window": window, "truncated": truncated, "hint": hint}


def expand(uid, focus_event_id, radius=4, budget=None):
    """Wider episode around one event (old memory_lens / memory_event)."""
    budget = budget_of(budget)
    eid = focus_event_id if "::" in (focus_event_id or "") else "%s::%s" % (uid, focus_event_id)
    conn = sqlite3.connect(f"file:{db_path(uid)}?mode=ro", uri=True, timeout=10)
    try:
        row = conn.execute(
            "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE event_id=? OR event_id LIKE ?",
            (eid, "%::" + (focus_event_id or "").split("::")[-1])).fetchone()
        if not row:
            nxt = "nothing found: memory_recall_later(query=%s)" % json.dumps(focus_event_id or "", ensure_ascii=False)
            return {"hits": [], "n": 0, "focus_event_id": focus_event_id, "truncated": False,
                    "hint": "unknown event_id", "next": nxt}
        rid, eid, ts, raw = row
        archived = False
        try:
            from app import archive_recall as _ar
            if _ar.is_marker(raw):
                t = _ar.full_text(conn, eid)
                if t:
                    raw, archived = t, True
        except Exception:
            pass
        rad = max(1, min(int(radius or 4), 8))
        before, after = _neigh(conn, rid, rad)
        centre = _part(eid, ts, raw, 800)
        neigh = [_part(e, t, r, 300) for _, e, t, r in before + after]
        l1, l2, l1_id, l2_id = _cover(conn, rid)
        item = {"ev": _ev(eid), "event_id": eid, "date": str(ts or "")[:16], "score": None,
                "centre": centre, "neighbours": neigh, "neighbour_radius": rad,
                "l1": _clip(l1, 200) if l1 else "", "l2": _clip(l2, 120) if l2 else "",
                "l1_id": ("l1:%s" % l1_id) if l1_id else None,
                "l2_id": ("l2:%s" % l2_id) if l2_id else None,
                "match_reason": "focus", "truncated": bool(centre.get("truncated")),
                "archived": archived}
    finally:
        conn.close()
    nxt = follow_next("", [item], 0, 1, True, eid)
    return {"hits": [item], "n": 1, "focus_event_id": eid, "budget_tokens": budget,
            "truncated": item["truncated"], "archived": archived,
            "hint": "memory_search(query, since, until) for a time window; memory_recall_later for a deep search",
            "next": nxt}


def search(uid, query="", top_k=None, since=None, until=None, exclude_imports=False, source=None,
           focus_event_id="", budget=None, now=None, radius=4, offset=0):
    """One call = one answer package. Used by memory_search, turn facts, /memory follow-up."""
    offset = max(0, int(offset or 0))
    if focus_event_id:
        return expand(uid, focus_event_id, radius=radius, budget=budget)
    window = resolve_time(query, now=now, since=since, until=until)
    use_since = window["since"] if window["hard"] else since
    use_until = window["until"] if window["hard"] else until
    b = budget_of(budget)
    n = n_hits(b) if top_k is None else max(1, min(10, int(top_k)))
    wide = retrieve_wide(uid, query, top_k=50, since=use_since, until=use_until,
                         exclude_imports=exclude_imports, source=source)
    if window.get("soft"):
        # recency boost only: keep order mostly, but pull last 14 days slightly up
        def _age(h):
            ts = str((h.get("metadata") or {}).get("time_str") or "")
            return ts
        wide = sorted(wide, key=lambda h: (_age(h) < (window["now"][:10]), -float(h.get("score") or 0)))
    gap = int(_mcfg().get("lens_gap", 3) or 3)
    div = diversify(wide, query, window, gap=gap)
    sliced = div[offset:offset + n]
    pack = package(uid, sliced, query, budget=b, window=window)
    pack["window"] = window
    pack["retrieved"] = len(wide)
    pack["offset"] = offset
    pack["total"] = len(div)
    for i, h in enumerate(pack.get("hits") or []):
        h["rank"] = offset + i + 1
    pack["next"] = follow_next(query, pack.get("hits") or [], offset, len(div), True, "")
    return pack
