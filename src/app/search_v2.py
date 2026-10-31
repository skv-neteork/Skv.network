"""Search v2 (2026-10-20): stopwords + light Russian/English stemming in a separate FTS5 table
(events_fts_stem, old events_fts untouched), weighted RRF (vector 1.0 / words 0.5, full word weight for
rare terms), and grouping of hits by parent L1/L2 summaries with drill-down (parent_id).
Switch: /data/skv/search_config.json {"search_v2": true}. Missing file or false = old behaviour."""
import json, os, re, sqlite3

CFG_PATH = "/data/skv/search_config.json"
DEF = {"search_v2": False, "vec_k": 50, "w_vec": 1.0, "w_words": 0.5, "w_words_rare": 1.0, "w_words_latin": 2.0,
       "rare_df": 0.02, "min_cos": 0.40, "weak_cos": 0.50, "common_df": 0.25, "fts_limit": 30}


def cfg():
    c = dict(DEF)
    try:
        with open(CFG_PATH) as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def enabled():
    return bool(cfg().get("search_v2"))


STOP = set("""и в во не что он на я с со как а то все всё она так его но да ты к у же вы за бы по только ее её мне было вот от
меня еще ещё нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом
себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда
кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее неё сейчас были куда зачем всех никогда можно
при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо
свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между это эта какие какое каким какую такое такие
такая также тоже который которые которая которое что-то как-то почему зачем сколько обсуждали обсуждаем говорили расскажи скажи
объясни помнишь знаешь давай нам наш наша наши ваш нашей был была были было вообще просто очень значит ещё ещё
the a an and or of to in on at for with is are was were be been it this that these those what which who how why when where
do does did can could would should will about from by as not no yes you we they he she i me my our your their there here""".split())
STOP_TITLE = set("делай делаем сделай давай дальше друг хорошо понял поняла поясни просто ладно смотри слушай нужно надо думаю кажется получается тоесть значит вообще сейчас потом снова опять next".split())

_TOK = re.compile(r"\w+", re.UNICODE)
_V = set("аеиоуыэюяё")
_PG = re.compile(r"((ив|ивши|ившись|ыв|ывши|ывшись)|((?<=[ая])(в|вши|вшись)))$")
_REFL = re.compile(r"(с[яь])$")
_ADJ = re.compile(r"(ее|ие|ые|ое|ими|ыми|ей|ий|ый|ой|ем|им|ым|ом|его|ого|ему|ому|их|ых|ую|юю|ая|яя|ою|ею)$")
_PART = re.compile(r"((ивш|ывш|ующ)|((?<=[ая])(ем|нн|вш|ющ|щ)))$")
_VERB = re.compile(r"((ила|ыла|ена|ейте|уйте|ите|или|ыли|ей|уй|ил|ыл|им|ым|ен|ило|ыло|ено|ят|ует|уют|ит|ыт|ены|ить|ыть|ишь|ую|ю)|((?<=[ая])(ла|на|ете|йте|ли|й|л|ем|н|ло|но|ет|ют|ны|ть|ешь|нно)))$")
_NOUN = re.compile(r"(а|ев|ов|ие|ье|е|иями|ями|ами|еи|ии|и|ией|ей|ой|ий|й|иям|ям|ием|ем|ам|ом|о|у|ах|иях|ях|ы|ь|ию|ью|ю|ия|ья|я)$")
_SUPER = re.compile(r"(ейш|ейше)$")
_DER = re.compile(r"(ост|ость)$")
_EN = re.compile(r"(ies|ing|ed|es|s)$")


def stem_ru(w):
    """Compact Snowball-style Russian stemmer (RV region; derivational step simplified)."""
    w = w.replace("ё", "е")
    i = next((k for k, ch in enumerate(w) if ch in _V), None)
    if i is None:
        return w
    pre, rv = w[:i + 1], w[i + 1:]
    m = _PG.search(rv)
    if m:
        rv = rv[:m.start()]
    else:
        rv = _REFL.sub("", rv)
        m = _ADJ.search(rv)
        if m:
            rv = rv[:m.start()]
            m2 = _PART.search(rv)
            if m2:
                rv = rv[:m2.start()]
        else:
            m = _VERB.search(rv)
            if m:
                rv = rv[:m.start()]
            else:
                rv = _NOUN.sub("", rv)
    rv = re.sub(r"и$", "", rv)
    if len(rv) > 4:
        rv = _DER.sub("", rv)
    if rv.endswith("нн"):
        rv = rv[:-1]
    else:
        rv = _SUPER.sub("", rv)
        rv = re.sub(r"ь$", "", rv)
    out = pre + rv
    return out if len(out) >= 2 else w


def stem(tok):
    t = tok.lower()
    if re.search(r"[а-яё]", t):
        return stem_ru(t)
    if "_" in t or any(ch.isdigit() for ch in t) or len(t) <= 4:
        return t
    return _EN.sub("", t) if len(t) > 5 else t


def tokens(text):
    return [t for t in _TOK.findall(text or "")]


def stem_text(text):
    return " ".join(stem(t) for t in tokens(text))


def query_terms(q):
    """[(original, stem, is_latin_term)] without stopwords/short words, unique by stem."""
    out, seen = [], set()
    for t in tokens(q):
        lo = t.lower()
        if lo in STOP or (len(lo) < 3 and not any(ch.isdigit() for ch in lo)):
            continue
        s = stem(t)
        if s in seen:
            continue
        seen.add(s)
        latin = bool(re.fullmatch(r"[A-Za-z0-9_]+", t)) and ("_" in t or t.isupper() or any(c.isdigit() for c in t) or t[:1].isupper())
        out.append((t, s, latin))
    return out


def _db(uid):
    from app.semantic import BASE_DIR, account_name
    return os.path.join(BASE_DIR, account_name(uid) + ".db")


def sync(conn):
    """Lazily add new events to events_fts_stem (rowid watermark). Old events_fts is not touched."""
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS events_fts_stem USING fts5(event_id UNINDEXED, body, tokenize=\"unicode61 tokenchars '_'\")")
    conn.execute("CREATE TABLE IF NOT EXISTS events_fts_stem_state (k TEXT PRIMARY KEY, v INTEGER)")
    row = conn.execute("SELECT v FROM events_fts_stem_state WHERE k='rowid'").fetchone()
    last = row[0] if row else 0
    rows = conn.execute("SELECT rowid, event_id, raw_dialogue FROM event_metadata WHERE rowid > ? ORDER BY rowid", (last,)).fetchall()
    rows_all, rows = rows, [r for r in rows if not (r[2] or "").startswith("[archived]")]   # archived: not indexed
    if rows:
        conn.executemany("INSERT INTO events_fts_stem(event_id, body) VALUES (?,?)",
                         [(eid, stem_text(raw)) for _, eid, raw in rows])
    if rows_all:
        conn.execute("INSERT OR REPLACE INTO events_fts_stem_state VALUES ('rowid', ?)", (rows_all[-1][0],))
        conn.commit()


def fts_ranked(uid, query, limit=30):
    """Return (ranked [(eid, score)], rare: bool). Uses informative stems only."""
    c = cfg()
    terms = query_terms(query)
    if not terms:
        return [], False
    try:
        conn = sqlite3.connect(_db(uid), timeout=10)
    except Exception:
        return [], False
    try:
        sync(conn)
        n = conn.execute("SELECT count(*) FROM events_fts_stem").fetchone()[0] or 1
        scored = []
        for t, s, latin in terms:
            df = conn.execute("SELECT count(*) FROM events_fts_stem WHERE events_fts_stem MATCH ?", ('"' + s.replace('"', '') + '"',)).fetchone()[0]
            scored.append((t, s, latin, df))
        use = [x for x in scored if x[3] > 0 and x[3] / n <= c["common_df"]]
        if not use:
            nz = [x for x in scored if x[3] > 0]
            use = sorted(nz, key=lambda x: x[3])[:1]
        if not use:
            return [], False
        rare_terms = [x for x in use if x[2] or x[3] / n <= c["rare_df"]]
        rare = 2 if any(x[2] for x in use) else (1 if (rare_terms or len(use) <= 2) else 0)
        if rare_terms:
            use = rare_terms   # rare/latin terms decide alone, common words would drown them in bm25
        expr = " OR ".join('"' + x[1].replace('"', '') + '"' for x in use[:12])
        rows = conn.execute("SELECT event_id, bm25(events_fts_stem) FROM events_fts_stem WHERE events_fts_stem MATCH ? "
                            "AND event_id IN (SELECT event_id FROM event_metadata) ORDER BY bm25(events_fts_stem) LIMIT ?",
                            (expr, limit)).fetchall()
    except Exception as e:
        print(f"[search_v2] fts failed: {e}", flush=True)
        return [], False
    finally:
        conn.close()
    out, seen = [], set()
    for eid, sc in rows:
        if eid not in seen:
            seen.add(eid)
            out.append((eid, float(-sc)))
    return out, rare


def wrrf(vec, words, w_vec, w_words, k=60):
    fused = {}
    for w, lst in ((w_vec, vec), (w_words, words)):
        for r, (eid, _s) in enumerate(lst):
            fused[eid] = fused.get(eid, 0.0) + w / (k + r + 1)
    return sorted(fused.items(), key=lambda x: -x[1])


def hybrid(uid, query, top_k=20, vec_k=None, with_cos=False):
    """Weighted RRF of vector (mml12) and stemmed keyword search. Returns [(eid, score)]."""
    from app import semantic as _sem
    c = cfg()
    sem = []
    try:
        if c.get("chunks"):
            sem, _v = chunk_events(uid, query, k=vec_k or max(c["vec_k"], top_k))
        else:
            sem, _v = _sem.semantic_events(uid, query, k=vec_k or max(c["vec_k"], top_k))
            sem = [(e, s) for e, s in sem if e.startswith(uid + "::")]
    except Exception as e:
        print(f"[search_v2] semantic skipped: {e}", flush=True)
    words, rare = fts_ranked(uid, query, limit=c["fts_limit"])
    fused = wrrf(sem, words, c["w_vec"], word_weight(c, rare))[:top_k]
    if with_cos:
        return fused, rare, (sem[0][1] if sem else 0.0), bool(words)
    return fused, rare


def word_weight(c, rare):
    return c["w_words_latin"] if rare == 2 else (c["w_words_rare"] if rare else c["w_words"])


# ---------------- grouped (L1/L2) ----------------
_DATE = re.compile(r"\b(\d{1,2}[./]\d{1,2}([./]\d{2,4})?|\d{4}-\d{2}-\d{2})\b")


def is_exact(q):
    if _DATE.search(q or ""):
        return True
    terms = query_terms(q)
    return bool(terms) and all(x[2] for x in terms)


def _snippet(raw, q, chars=220):
    from app.recall_polish import clean
    t = clean(raw or "")
    stems = {s for _, s, _ in query_terms(q)}
    pos = 0
    for m in _TOK.finditer(t):
        if stem(m.group(0)) in stems:
            pos = max(0, m.start() - 60)
            break
    s = t[pos:pos + chars].replace("\n", " ")
    return ("…" if pos else "") + s + ("…" if pos + chars < len(t) else "")


def grouped(uid, query, top_k=8, parent_id=None, hits_per_group=3):
    conn = sqlite3.connect(_db(uid), timeout=10)
    try:
        l1 = conn.execute("SELECT session_id, topic, summary_text, created_at, from_rowid, to_rowid FROM summary_l1 "
                          "WHERE from_rowid IS NOT NULL").fetchall()
        l2 = conn.execute("SELECT id, period_key, period_from, period_to, from_rowid, to_rowid, substr(text,1,300) FROM summary_l2_blocks "
                          "WHERE from_rowid IS NOT NULL").fetchall()
        v2t = {}
        if cfg().get("l1_v2"):
            try:
                v2t = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT session_id, title, summary FROM summary_l1_v2")}
            except Exception:
                v2t = {}
        rng = None
        if parent_id:
            p = [x for x in l1 if x[0] == parent_id]
            if p:
                rng = (p[0][4], p[0][5])
            else:
                p = [x for x in l2 if str(x[0]) == str(parent_id) or x[1] == parent_id]
                if p:
                    rng = (p[0][4], p[0][5])
            if not rng:
                return {"mode": "grouped", "groups": [], "results": [], "note": "parent_id not found"}
        if rng:   # drill-down: filter both branches to the parent's range BEFORE fusion
            from app import semantic as _sem
            c = cfg()
            inr = {e for (e,) in conn.execute("SELECT event_id FROM event_metadata WHERE rowid BETWEEN ? AND ?", rng)}
            sem = _range_vectors(uid, query, inr)
            words, rare = fts_ranked(uid, query, limit=5000)
            words = [(e, x) for e, x in words if e in inr]
            hits = wrrf(sem, words, c["w_vec"], word_weight(c, rare))[:100]
        else:
            hits, rare, top_cos, has_words = hybrid(uid, query, top_k=60, with_cos=True)
        ids = [e for e, _ in hits]
        meta = {}
        for i in range(0, len(ids), 400):
            ch = ids[i:i + 400]
            for rid, eid, ts, raw, kind, src in conn.execute(
                    "SELECT rowid, event_id, time_str, raw_dialogue, kind, source FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ch)), ch):
                meta[eid] = (rid, ts, raw, kind, src)
        # archive steps 1+2: archived raw text -> real snippet; old date or nothing found -> keyword search in event_archive
        from app import archive_recall as _ar
        for e, v in list(meta.items()):
            if _ar.is_marker(v[2]):
                t = _ar.full_text(conn, e)
                if t:
                    meta[e] = (v[0], v[1], t, v[3], v[4])
    finally:
        conn.close()
    if rng:
        hits = [(e, s) for e, s in hits if e in meta and rng[0] <= meta[e][0] <= rng[1]]
        return {"mode": "drilldown", "parent_id": parent_id, "groups": [],
                "results": [{"event_id": e, "score": round(s, 5), "source": "personal", "summary": _snippet(meta[e][2], query),
                             "metadata": {"time_str": meta[e][1]}} for e, s in hits[:top_k]]}
    _out = _grouped_rest(uid, query, top_k, hits, meta, l1, l2, v2t, top_cos, hits_per_group)
    from app import archive_recall as _ar
    arch = _ar.search(uid, query, limit=5) if (not _out.get("results") or _ar.is_old(query) or missing_terms(uid, query)) else []
    if arch:
        seen = {r.get("event_id") for r in _out.get("results") or []}
        add = [{"event_id": a["event_id"], "score": a["score"], "source": "archive", "archived": True, "summary": a["snippet"],
                "metadata": {"time_str": a["time_str"]}} for a in arch if a["event_id"] not in seen]
        if add:
            _out["results"] = [x for x in add if x["score"] >= 0.99] + (_out.get("results") or []) + [x for x in add if x["score"] < 0.99]
            _out["archive"] = add
            _out["archive_note"] = "raw text older than 90 days, found by keywords in the archive (no vectors); open with GET /event/{id}"
    return _out


def _grouped_rest(uid, query, top_k, hits, meta, l1, l2, v2t, top_cos, hits_per_group):
    miss = missing_terms(uid, query)
    if top_cos < cfg()["min_cos"] or (top_cos < cfg()["weak_cos"] and miss):
        return {"mode": "grouped", "groups": [], "results": [], "no_confident_match": True,
                "explanation": "Точных совпадений нет. Слабые похожие записи не показаны, чтобы не путать.",
                "note": f"best similarity {top_cos:.2f}; words never seen in memory: {', '.join(miss) or '-'}",
                "deep_search": {"available": True,
                                "how": "Ask the user first. Then POST /api/v7/memory/recall_later {user_id, query}: a delayed "
                                       "cheap agent (5-30 lens steps) writes a report with sources. Poll GET /api/v7/memory/recall_later/{job_id}; also arrives later in /memory as 'remembered'."}}
    try:
        from app import semantic as _sem
        _ord, sup = _sem.supersede(uid, [e for e, _ in hits])
    except Exception:
        sup = {}
    crit = _crit(uid)
    if is_exact(query):
        return {"mode": "exact", "groups": [], "results": [
            {"event_id": e, "score": round(s, 5), "source": "personal", "summary": _snippet(meta[e][2], query),
             "metadata": {"time_str": meta[e][1]}} for e, s in hits[:top_k] if e in meta]}
    groups = {}
    for e, s in hits:
        if e not in meta:
            continue
        rid = meta[e][0]
        cover = [x for x in l1 if x[4] <= rid <= x[5]]
        par = min(cover, key=lambda x: x[5] - x[4]) if cover else None
        key = par[0] if par else "_none"
        if par and par[0] in v2t:
            par = (par[0], par[1], v2t[par[0]][0] + " — " + v2t[par[0]][1], par[3], par[4], par[5])
        g = groups.setdefault(key, {"parent_id": key if par else None, "level": "L1" if par else None,
                                    "title": ((par[1] or "") + ": " + (par[2] or "").strip().split("\n")[0][:160]) if par else "(без выжимки)",
                                    "summary": (par[2] or "")[:400] if par else "", "date": par[3] if par else None,
                                    "hits": 0, "score": 0.0, "best": []})
        if par:
            l2c = [x for x in l2 if x[4] <= rid <= x[5]]
            if l2c and "l2" not in g:
                b = min(l2c, key=lambda x: x[5] - x[4])
                g["l2"] = {"id": b[0], "period": f"{b[2]} — {b[3]}", "text": (b[6] or "")[:200]}
        g["hits"] += 1
        g["score"] += s
        if len(g["best"]) < hits_per_group:
            g["best"].append(_tags({"event_id": e, "time_str": meta[e][1], "snippet": _snippet(meta[e][2], query)}, meta[e], sup, crit))
    out = sorted(groups.values(), key=lambda g: -g["score"])[:top_k]
    for g in out:
        g["score"] = round(g["score"], 5)
    flat = [{"event_id": b["event_id"], "score": g["score"], "source": "personal", "summary": b["snippet"],
             "metadata": {"time_str": b["time_str"], "parent_id": g["parent_id"]}} for g in out for b in g["best"][:1]]
    return {"mode": "grouped", "groups": out, "results": flat,
            "hint": "pick a group and call again with parent_id to search inside it"}


def _range_vectors(uid, query, ids):
    """Exact cosine over the parent's events only (HNSW cannot return k close to index size)."""
    import numpy as np
    from app import semantic as _sem
    tag = _sem.active_tag()
    with _sem.STORE.lock:
        e = _sem.STORE._load(tag, _sem.account_name(uid))
        if not e:
            return []
        lab = [(eid, e["pos"][eid]) for eid in ids if eid in e["pos"]]
        if not lab:
            return []
        vecs = np.asarray(e["index"].get_items([l for _, l in lab]), dtype=np.float32)
    q = _sem.embed([query], tag)[0]
    vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
    sims = vecs @ q
    order = np.argsort(-sims)[:200]
    return [(lab[i][0], float(sims[i])) for i in order]


_DEC = re.compile(r"^\s*Q:\s*(Решение|Итог|Critical|TASK|Решили|Вывод|L1 и critical)|\b(critical|decision)\b", re.I)


def _tags(d, m, sup, crit=()):
    """date/source/kind label; 'superseded_by' marks an older record with a newer one on the same subject (output only)."""
    kind, src, raw = (m[3] or ""), (m[4] or ""), (m[2] or "")[:300]
    d["source"] = src or None
    d["kind"] = kind or None
    if d["event_id"] in crit:
        d["label"] = "critical"
    elif kind.lower() in ("decision", "task"):
        d["label"] = "decision"
    else:
        d["label"] = "decision?" if _DEC.search(raw) else "discussion"
    if d["event_id"] in sup:
        d["superseded_by"] = sup[d["event_id"]]
    return d


def missing_terms(uid, query):
    """Informative query words that occur nowhere in the user's memory."""
    try:
        conn = sqlite3.connect(_db(uid), timeout=10)
        try:
            return [t for t, st, _l in query_terms(query) if not conn.execute(
                "SELECT 1 FROM events_fts_stem WHERE events_fts_stem MATCH ? LIMIT 1", ('"' + st.replace('"', '') + '"',)).fetchone()]
        finally:
            conn.close()
    except Exception:
        return []


# ---------------- v3 (2026-10-20 13:20): chunk index, L1 v2 titles, critical labels ----------------
CHUNK, OVERLAP = 800, 150


def _chunks(text):
    t = text or ""
    if len(t) <= CHUNK:
        return [t]
    out, i = [], 0
    while i < len(t):
        out.append(t[i:i + CHUNK])
        if i + CHUNK >= len(t):
            break
        i += CHUNK - OVERLAP
    return out[:40]


def _chunk_name(uid):
    from app.semantic import account_name
    return account_name(uid) + "__chunks"


def build_chunks(uid, since_rowid=0, threads=2, batch=64, conn=None):
    """Per-chunk vectors in a NEW index <account>__chunks (old index untouched). One entry per chunk -> no dupes."""
    from app import semantic as _sem
    own = conn is None
    conn = conn or sqlite3.connect(_db(uid), timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS events_fts_stem_state (k TEXT PRIMARY KEY, v INTEGER)")
    rows = conn.execute("SELECT rowid, event_id, raw_dialogue FROM event_metadata WHERE rowid > ? ORDER BY rowid", (since_rowid,)).fetchall()
    tag, name = _sem.active_tag(), _chunk_name(uid)
    ids, texts = [], []
    for _r, eid, raw in rows:
        if (raw or "").startswith("[archived]"):
            continue   # archived: no chunk vectors
        for k, ch in enumerate(_chunks(raw)):
            ids.append(f"{eid}#{k}")
            texts.append(ch)
    for i in range(0, len(ids), batch):
        vecs = _sem.embed(texts[i:i + batch], tag, threads=threads)
        _sem.STORE.add(tag, name, ids[i:i + batch], vecs, save=False)
    if ids:
        _sem.STORE.save(tag, name)
    if rows:
        conn.execute("INSERT OR REPLACE INTO events_fts_stem_state VALUES ('chunk_rowid', ?)", (rows[-1][0],))
        conn.commit()
    if own:
        conn.close()
    return len(rows), len(ids)


def chunk_events(uid, query, k=50):
    """Vector search over chunks; record score = best chunk. Returns ([(eid, cos)], qvec)."""
    from app import semantic as _sem
    try:
        conn = sqlite3.connect(_db(uid), timeout=10)
        st = conn.execute("SELECT v FROM events_fts_stem_state WHERE k='chunk_rowid'").fetchone()
        mx = conn.execute("SELECT max(rowid) FROM event_metadata").fetchone()[0] or 0
        if st and mx > st[0] and mx - st[0] <= 50:   # fresh records: embed on the fly (few)
            build_chunks(uid, st[0], conn=conn)
        conn.close()
    except Exception as e:
        print(f"[search_v2] chunk sync skipped: {e}", flush=True)
    tag = _sem.active_tag()
    vec = _sem.embed([query], tag)[0]
    hits = _sem.STORE.search(tag, _chunk_name(uid), vec, k=min(400, k * 8))
    best = {}
    for cid, s in hits:
        eid = cid.rsplit("#", 1)[0]
        if eid.startswith(uid + "::") and s > best.get(eid, -1):
            best[eid] = s
    return sorted(best.items(), key=lambda x: -x[1])[:k], vec


def build_l1_v2(uid):
    """Extractive titles for L1 rows: top distinctive words + first real user questions from the records
    themselves. NEW table summary_l1_v2; summary_l1 and raw records are not modified."""
    import math, collections
    conn = sqlite3.connect(_db(uid), timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS summary_l1_v2 (session_id TEXT PRIMARY KEY, title TEXT, summary TEXT, built_at TEXT)")
    n = conn.execute("SELECT count(*) FROM event_metadata").fetchone()[0] or 1
    df = collections.Counter()
    docs = {}
    for rid, raw in conn.execute("SELECT rowid, raw_dialogue FROM event_metadata"):
        q = (raw or "").split("\nA:")[0]
        st = {stem(t) for t in tokens(q) if t.lower() not in STOP and t.lower() not in STOP_TITLE and len(t) > 3}
        docs[rid] = (q, st)
        df.update(st)
    made = 0
    for sid, a, b in conn.execute("SELECT session_id, from_rowid, to_rowid FROM summary_l1 WHERE from_rowid IS NOT NULL").fetchall():
        tf, qs, orig = collections.Counter(), [], {}
        for rid in range(a, b + 1):
            if rid not in docs:
                continue
            q, st = docs[rid]
            tf.update(st)
            for t in tokens(q):
                orig.setdefault(stem(t), t.lower())
            qq = re.sub(r"\s+", " ", q.replace("Q:", "")).strip()
            if len(qq) >= 25 and not qq.startswith(("[", "{", "#", "`", "=")):
                qs.append(qq[:140])
        if not tf:
            continue
        top = sorted(tf, key=lambda s: -(tf[s] * math.log(n / (1 + df[s]))))[:5]
        title = ", ".join(orig.get(s, s) for s in top)
        summary = " | ".join(qs[:4])
        conn.execute("INSERT OR REPLACE INTO summary_l1_v2 VALUES (?,?,?,datetime('now'))", (sid, title, summary))
        made += 1
    conn.commit()
    conn.close()
    return made


def _crit(uid):
    try:
        from app.recall_polish import _crit_ids
        return set(_crit_ids(uid) or [])
    except Exception:
        return set()
