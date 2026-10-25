"""/api/v7/search without a valid 768-d query_vector used to crash the worker (malloc in HNSW -> 502).
Text queries now go through the same semantic + keyword (RRF) path as /memory."""
def text_search(uid, query, top_k=20, since=None, until=None, exclude_imports=False, source=None):
    if since or until or exclude_imports or (source and source.lower() != "events"):
        return filtered_search(uid, query, top_k, since, until, exclude_imports, source)
    from app import semantic as _sem
    from app import search_v2 as _v2
    if _v2.enabled():
        fused, _rare = _v2.hybrid(uid, query, top_k=top_k)
        out = _arch(uid, query, _out(uid, fused))
        if len(out) < 3 and len(_v2.query_terms(query)) > 1:   # any-term + morphology fallback for multi-word queries
            have = {o["event_id"] for o in out}
            out += [o for o in filtered_search(uid, query, top_k) if o["event_id"] not in have][:top_k - len(out)]
        return out
    sem = []
    try:
        sem, _v = _sem.semantic_events(uid, query, k=max(top_k, 20))
        sem = [(e, s) for e, s in sem if e.startswith(uid + "::")]
    except Exception as e:
        print(f"[search_text] semantic skipped: {e}", flush=True)
    fts = _sem.fts_ranked(uid, query, limit=30)
    fused = _sem.rrf(sem, fts)[:top_k]
    return _arch(uid, query, _out(uid, fused))


def _arch(uid, query, out):
    """Archive steps 1+2: real text for archived hits; old date / nothing found / unseen words -> event_archive keywords."""
    try:
        from app import archive_recall as _ar, search_v2 as _v2
        from app.memory_v2 import db_path
        import sqlite3
        c = sqlite3.connect(db_path(uid), timeout=10)
        try:
            for o in out:
                if _ar.is_marker(o.get("summary")):
                    t = _ar.full_text(c, o["event_id"])
                    if t:
                        o["summary"], o["source"] = "[archived] " + t[:290], "archive"
        finally:
            c.close()
        if not out or _ar.is_old(query) or _v2.missing_terms(uid, query):
            seen = {o["event_id"] for o in out}
            add = [{"event_id": a["event_id"], "score": a["score"], "source": "archive",
                          "summary": "[archived] " + a["snippet"], "metadata": {"time_str": a["time_str"], "archived": True}}
                         for a in _ar.search(uid, query, limit=5) if a["event_id"] not in seen]
            # every query word matched in the archive beats weak live hits; partial matches go last
            out = [x for x in add if x["score"] >= 0.99] + out + [x for x in add if x["score"] < 0.99]
    except Exception as e:
        print(f"[search_text] archive skipped: {e}", flush=True)
    return out


def _out(uid, fused):
    from app.recall_polish import _rows, clean, clip
    rows = _rows(uid, [e for e, _ in fused])
    out = []
    for e, sc in fused:
        r = rows.get(e)
        if not r:
            continue
        out.append({"event_id": e, "score": float(round(sc, 5)), "source": "personal",
                    "summary": clip(clean(r["raw"]), 300), "metadata": {"time_str": r.get("time_str")}})
    return out


# ---- filtered search (2026-10-25): date window, imports/tests excluded, any-term + prefix morphology, relevance x recency, board notes ----
import re as _re, math as _math, time as _time, sqlite3 as _sq3
_TESTID = _re.compile(r"(chat_grok_test|sandbox_event|smoke|probe_)", _re.I)
_REL = _re.compile(r"^\s*(\d+)\s*([dhw])\s*$", _re.I)
TZ_H = 3   # account local (MSK) -> UTC for time_str


def _bound(v):
    """'3d' / '12h' / '2w' relative, or 'YYYY-MM-DD[ HH:MM]' local -> UTC 'YYYY-MM-DD HH:MM'."""
    if not v:
        return None
    v = str(v).strip()
    m = _REL.match(v)
    if m:
        sec = int(m.group(1)) * {"h": 3600, "d": 86400, "w": 604800}[m.group(2).lower()]
        return _time.strftime("%Y-%m-%d %H:%M", _time.gmtime(_time.time() - sec))
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            t = _time.mktime(_time.strptime(v[:16] if "%H" in f else v[:10], f)) - _time.timezone   # parse as UTC epoch
            return _time.strftime("%Y-%m-%d %H:%M", _time.gmtime(t - TZ_H * 3600))
        except Exception:
            continue
    return None


def _age_h(ts):
    try:
        return max(0.0, (_time.time() - (_time.mktime(_time.strptime(ts[:16], "%Y-%m-%d %H:%M")) - _time.timezone)) / 3600)
    except Exception:
        return 1e6


def _expr(terms):
    parts = []
    for _t, s, _l in terms[:12]:
        s = s.replace('"', '')
        if not s:
            continue
        parts.append('"%s"' % s)
        if len(s) >= 5 and not _re.fullmatch(r"[A-Za-z0-9_]+", s):
            parts.append('"%s"*' % s[:max(4, len(s) - 2)])   # morphology fallback (ошибк* -> ошибка/ошибки/ошибкой)
    return " OR ".join(parts)


def _board(uid, query, top_k):
    from app import search_v2 as _v2
    stems = [s for _, s, _ in _v2.query_terms(query)]
    c = _sq3.connect(_v2._db(uid), timeout=10)
    try:
        rows = c.execute("SELECT item_id, kind, title, body, status, updated_at FROM board_items WHERE COALESCE(removed,0)=0").fetchall()
    except Exception:
        rows = []
    finally:
        c.close()
    out = []
    for iid, kind, title, body, st, up in rows:
        txt = "%s %s" % (title or "", body or "")
        low = txt.lower()
        st_txt = set(_v2.stem_text(txt).split())
        hit = sum(1 for s in stems if s in st_txt or (len(s) >= 5 and any(w.startswith(s[:max(4, len(s) - 2)]) for w in st_txt)))
        if query.strip().lower() in low:
            hit += len(stems) + 1
        if hit:
            sc = hit / max(1, len(stems)) * (1 + 0.6 * _math.exp(-_age_h(up or "") / 72))
            out.append({"event_id": "board:%s" % iid, "score": round(sc, 5), "source": "board",
                        "summary": ("[board %s/%s] " % (kind, st) + txt.strip())[:300], "metadata": {"time_str": up}})
    out.sort(key=lambda x: -x["score"])
    return out[:top_k]


def filtered_search(uid, query, top_k=20, since=None, until=None, exclude_imports=False, source=None):
    from app import search_v2 as _v2, semantic as _sem
    src = (source or "events").lower()
    if src in ("board", "notes", "board_notes"):
        return _board(uid, query, top_k)
    lo, hi = _bound(since), _bound(until)
    c = _sq3.connect(_v2._db(uid), timeout=10)
    try:
        _v2.sync(c)
        meta = {}
        for eid, ts, kind, head in c.execute("SELECT event_id, time_str, kind, substr(raw_dialogue,1,12) FROM event_metadata"):
            if lo and (ts or "") < lo:
                continue
            if hi and (ts or "") > hi:
                continue
            if exclude_imports and ((kind or "") == "import" or (head or "").startswith("[archived]") or _TESTID.search(eid or "")):
                continue
            meta[eid] = ts or ""
        terms = _v2.query_terms(query)
        fts, fseen = [], set()
        ex = _expr(terms)
        if ex and meta:
            for eid, sc in c.execute("SELECT event_id, bm25(events_fts_stem) FROM events_fts_stem WHERE events_fts_stem MATCH ? "
                                     "ORDER BY bm25(events_fts_stem) LIMIT 3000", (ex,)):
                if eid in meta and eid not in fseen:
                    fseen.add(eid); fts.append((eid, -sc))
                    if len(fts) >= 80:
                        break
    finally:
        c.close()
    sem = []
    try:
        s0, _v = _sem.semantic_events(uid, query, k=600)
        sem = [(e, s) for e, s in s0 if e in meta][:80]
    except Exception as e:
        print(f"[search_text] filtered semantic skipped: {e}", flush=True)
    fused = dict(_v2.wrrf(sem, fts, 1.0, 1.2))
    for eid in list(fused):
        fused[eid] *= 1 + 0.6 * _math.exp(-_age_h(meta.get(eid, "")) / 72)   # relevance x recency (3-day half scale)
    ranked = sorted(fused.items(), key=lambda x: -x[1])[:top_k]
    out = _out(uid, ranked)
    if src == "all":
        out = sorted(out + _board(uid, query, max(3, top_k // 3)), key=lambda x: -x["score"])[:top_k]
    return out
