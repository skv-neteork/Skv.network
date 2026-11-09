"""/api/v7/search without a valid 768-d query_vector used to crash the worker (malloc in HNSW -> 502).
Text queries now go through the same semantic + keyword (RRF) path as /memory."""
def _text_search_core(uid, query, top_k=20, since=None, until=None, exclude_imports=False, source=None):
    if since or until or exclude_imports or (source and source.lower() != "events"):
        return filtered_search(uid, query, top_k, since, until, exclude_imports, source)
    from app import semantic as _sem
    from app import search_v2 as _v2
    if _v2.enabled():
        # question -> reformulate: name exact, narrative vector
        if any(query.lower().startswith(w) for w in ("when ","what ","where ","who ","how ")):
            fused, _rare = _v2.name_and_meaning(uid, query, top_k=top_k)
        else:
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


# ---- 2026-11-01: line-aware over-fetch + critical / vault metadata in search ----
# 1) memory lines: semantic/FTS indexes are not line-shadowed, the middleware drops foreign hits AFTER top_k was cut,
#    so a key on a non-main line got 0-1 of top_k hits. Over-fetch and drop foreign ids before cutting.
# 2) critical facts (critical_auto) and the vault are separate stores: search now also matches their NON-SECRET
#    metadata (kind / value of a critical fact; vault name, kind, note, domains, and the scrubbed context around the
#    [vault:name] reference). A vault value is never read here (no decrypt; vault.listing() has no value column).
def _line_ctx():
    try:
        from app import memory_lines as _ml
        return _ml.LINE_CTX.get()
    except Exception:
        return None


def _visible(ctx, eid):
    if not ctx or not isinstance(eid, str) or "::" not in eid:
        return True
    ids = ctx.get("_idset")
    if ids is None:
        ids = ctx["_idset"] = set(ctx.get("ids") or [])
    return (eid not in ids) if ctx.get("mode") == "deny" else (eid in ids)


def _stems(query):
    from app import search_v2 as _v2
    return [st for _, st, _ in _v2.query_terms(query)]


def _need(stems):
    """2 terms -> both; 3+ -> 2/3; metadata rows are short, one generic word ("account") is not a match."""
    return 1.0 if len(stems) <= 2 else 0.6


def _match(stems, query, text):
    from app import search_v2 as _v2
    if not stems or not text:
        return 0.0
    st_txt = set(_v2.stem_text(text).split())
    hit = sum(1 for s in stems if s in st_txt or (len(s) >= 5 and any(w.startswith(s[:max(4, len(s) - 2)]) for w in st_txt)))
    if query.strip().lower() in text.lower():
        hit = len(stems)
    return hit / len(stems)


def _critical_hits(uid, query, stems, ctx, limit=3):
    from app import search_v2 as _v2
    out = []
    try:
        c = _sq3.connect("file:" + _v2._db(uid) + "?mode=ro", uri=True, timeout=10)   # ro -> line-shadowed view
    except Exception:
        return out
    try:
        rows = c.execute("SELECT kind, value, context, event_id, time_str FROM critical_auto").fetchall()
    except Exception:
        rows = []
    finally:
        c.close()
    for kind, value, cx, eid, ts in rows:
        if not _visible(ctx, eid):
            continue
        f = _match(stems, query, "%s %s %s" % (kind or "", value or "", cx or ""))
        if f >= _need(stems):
            out.append(((f, ts or ""), {"event_id": eid or "critical:%s" % (value or "")[:40], "score": f, "source": "critical",
                            "summary": ("[critical %s] %s — %s" % (kind, value, cx or ""))[:300], "metadata": {"time_str": ts}}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [o for _, o in out[:limit]]


def _vault_hits(uid, query, stems, limit=3):
    out = []
    try:
        from app import vault as _vault
        items = _vault.listing(uid)
    except Exception:
        return out
    ctxs = {}
    eids = [i.get("from_event") for i in items if i.get("from_event")]
    if eids:
        try:
            from app.recall_polish import _rows
            rows = _rows(uid, eids)
            for i in items:
                raw = (rows.get(i.get("from_event")) or {}).get("raw") or ""
                ref = "[vault:%s]" % i["name"]
                k = raw.find(ref)
                if k >= 0:   # memory text is already scrubbed: only the reference sits there, never the value
                    ctxs[i["name"]] = _re.sub(r"\s+", " ", raw[max(0, k - 90):k + len(ref) + 60]).strip()
        except Exception as e:
            print(f"[search_text] vault ctx skipped: {e}", flush=True)
    for i in items:
        cx = ctxs.get(i["name"], "")
        doms = ",".join(i.get("allowed_domains") or [])
        f = _match(stems, query, "vault secret %s %s %s %s %s" % (i["name"].replace("_", " "), i.get("kind") or "", i.get("note") or "", doms, cx))
        if f >= _need(stems):
            s = "[vault] %s stored as [vault:%s]%s%s — value hidden; use it via vault inject/reveal, never paste it" % (
                i.get("kind") or "secret", i["name"], (" (domains: %s)" % doms) if doms else "", (" — context: " + cx) if cx else "")
            out.append(((f, 1 if cx else 0, i.get("updated_at") or ""), {"event_id": i.get("from_event") or "vault:%s" % i["name"], "score": f, "source": "vault",
                            "summary": s[:300], "metadata": {"time_str": i.get("updated_at")}}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [o for _, o in out[:limit]]


def text_search(uid, query, top_k=20, since=None, until=None, exclude_imports=False, source=None):
    ctx = _line_ctx()
    k = min(120, max(top_k * 4, 40)) if ctx else top_k
    from app import q2s as _q2s   # 2026-11-02 Q2S: question -> statement forms (flag search_config q2s; off = _text_search_core)
    out = _q2s.text_core(uid, query, k, since, until, exclude_imports, source)
    if ctx:
        out = [o for o in out if _visible(ctx, o.get("event_id"))]
    out = out[:top_k]
    src = (source or "events").lower()
    if src in ("events", "all") and not (since or until):
        try:
            stems = _stems(query)
            have = {o.get("event_id") for o in out}
            top = max([float(o.get("score") or 0) for o in out] or [1.0]) or 1.0
            extra = [x for x in _critical_hits(uid, query, stems, ctx) + _vault_hits(uid, query, stems) if x["event_id"] not in have or x["source"] == "vault"]
            for x in extra:
                x["score"] = round(top * (0.6 + 0.35 * x["score"]), 5)   # full match ranks near the best event hit
            if extra:
                keep = max(0, top_k - len(extra)) if len(out) >= top_k else len(out)
                out = sorted(out[:keep] + extra, key=lambda x: -float(x.get("score") or 0))
        except Exception as e:
            print(f"[search_text] critical/vault skipped: {e}", flush=True)
    return out
