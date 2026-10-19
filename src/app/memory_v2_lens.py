"""SKV memory v2, step C: lens = targeted search in distant memory, grouped into episodes.

Corpus: all events (not only grokexp_*). Terms: EN/RU stop words removed, ranked by rarity (idf).
Candidates: semantic+bm25 RRF list + bm25 on rare terms + exact substring hits (double weight).
Grouping: events close in time (rowid gap <= lens_gap) form one episode (cluster).
Output: cluster 1 in full (center + raw neighbours before/after + covering L1/L2 + critical),
clusters 2..N briefly (center preview + period + expand handle), total_hits, more_cursor.
focus_event_id: expand one episode around that event without a new search.
"""
import json
import math
import re
import sqlite3

from app.memory_v2 import clip, config, db_path, est_tokens, mask_text, norm_date, strip_critical

STOP_EN = set("""a an the and or but if then else of to in on at by for with about from into onto over under after before
what which who whom whose when where why how did do does doing done we you i me my mine our ours your yours they them their
he him his she her it its is are was were be been being am have has had having this that these those there here can could
would should will shall may might must not no yes all any some more most other such only own same so than too very just also
let lets please tell show find give get got say said remember recall decide decided decision last time thing things something
anything everything again still now then today yesterday tomorrow ok okay hi hello hey thanks thank like want need know think
one two first second new old way much many each every both either neither via per vs etc""".split())
STOP_RU = set("""и в во не что он на я с со как а то все всё она так его но да ты к у же вы за бы по только ее её мне было вот от
меня еще ещё нет о об из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там
потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет
ж тогда кто этот того потому этого какой какая какие совсем ним здесь этом один почти мой тем чтобы нее неё сейчас были куда
зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них много разве три эту
моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между это помнишь расскажи
напомни скажи давай мы наш наша наши ваш ваша про насчет насчёт решили решение говорили обсуждали было""".split())
STOP = STOP_EN | STOP_RU
_TOK = re.compile(r"\w[\w\-]*", re.UNICODE)

_scan_cache = {}


def _norm(s):
    return (s or "").lower().replace("-", "").replace(" ", "").replace("ё", "е")


def _scan(user_id):
    """[(rowid, event_id, norm_body)] for all events, cached until the table changes."""
    path = db_path(user_id)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        sig = conn.execute("SELECT COUNT(*), MAX(rowid) FROM event_metadata").fetchone()
        hit = _scan_cache.get(path)
        if hit and hit[0] == sig:
            return hit[1]
        rows = [(r, e, _norm(t)) for r, e, t in conn.execute("SELECT rowid, event_id, raw_dialogue FROM event_metadata")]
    finally:
        conn.close()
    if len(_scan_cache) > 40:
        _scan_cache.pop(next(iter(_scan_cache)))
    _scan_cache[path] = (sig, rows)
    return rows


def query_terms(q, bodies):
    seen, terms = set(), []
    for t in _TOK.findall((q or "").lower()):
        plain = t.replace("-", "").replace("ё", "е")
        if len(plain) < 3 or plain in STOP or t in STOP or plain.isdigit() and len(plain) < 4:
            continue
        if plain in seen:
            continue
        seen.add(plain)
        terms.append({"term": t, "norm": plain})
    n = max(1, len(bodies))
    for t in terms:
        t["df"] = sum(1 for _, _, b in bodies if t["norm"] in b)
        t["idf"] = round(math.log((n + 1) / (t["df"] + 1)), 3)
    useful = [t for t in terms if t["df"] > 0]
    rare = [t for t in useful if t["df"] / n <= 0.3] or useful
    rare.sort(key=lambda t: -t["idf"])
    return rare[:4], terms


def _rrf(*lists, k=60):
    fused = {}
    for lst in lists:
        for rank, eid in enumerate(lst):
            fused[eid] = fused.get(eid, 0.0) + 1.0 / (k + rank + 1)
    return fused


def _semantic_list(user_id, q):
    try:
        from app import semantic as sem
        if sem.active_tag() == "bge":
            return []
        hn, _ = sem.semantic_events(user_id, q, k=30)
        hn = [e for e, _ in hn if e.startswith(f"{user_id}::")]
        ft = [e for e, _ in sem.fts_ranked(user_id, q, limit=30)]
        fused = _rrf(hn, ft)
        return [e for e, _ in sorted(fused.items(), key=lambda x: -x[1])]
    except Exception as e:
        print(f"[lens] semantic skipped: {e}", flush=True)
        return []


def _ctx_rows(conn, rowid, before, after):
    b = conn.execute("SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid < ? ORDER BY rowid DESC LIMIT ?", (rowid, before)).fetchall() if before else []
    a = conn.execute("SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid > ? ORDER BY rowid ASC LIMIT ?", (rowid, after)).fetchall() if after else []
    return list(reversed(b)), a


def _cover_l1(conn, rowid):
    try:
        r = conn.execute("SELECT topic, summary_text FROM summary_l1 WHERE from_rowid <= ? AND to_rowid >= ? ORDER BY (to_rowid - from_rowid) ASC LIMIT 1", (rowid, rowid)).fetchone()
        return (f"{r[0]}: {r[1]}" if r else "")
    except sqlite3.OperationalError:
        return ""


def _cover_l2(conn, rowid):
    try:
        r = conn.execute("SELECT text FROM summary_l2_blocks WHERE from_rowid <= ? AND to_rowid >= ? AND source != 'legacy_summary_l2' ORDER BY (source='agent') DESC, (to_rowid - from_rowid) ASC LIMIT 1", (rowid, rowid)).fetchone()
        return r[0] if r else ""
    except sqlite3.OperationalError:
        return ""


def _crit_for(conn, norms, limit=2):
    if not norms:
        return []
    out = []
    for (raw,) in conn.execute("SELECT raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE '%>>>%' ORDER BY rowid DESC LIMIT 200"):
        for ln in (raw or "").split("\n"):
            if ">>>" in ln and any(n in _norm(ln) for n in norms):
                s = re.sub(r"(>>>\s*)+", ">>> ", ln.strip())
                if s not in out:
                    out.append(s)
                if len(out) >= limit:
                    return out
    return out


def _entry(r, cap):
    return {"event_id": r[1], "date": norm_date(r[2]), "text": clip(strip_critical(r[3]) or (r[3] or ""), cap, headtail=True)}


def _full_cluster(conn, center_row, members, norms, budget, radius=2, match_type="lens", score=None):
    used = 0
    c_cap = min(500, max(120, int(budget * 0.4)))
    center = _entry(center_row, c_cap)
    center["match_type"] = match_type
    if score is not None:
        center["score"] = round(score, 4)
    used += est_tokens(center["text"]) + 20
    nb_cap = max(40, min(110, int((budget - used) * 0.12)))
    before, after = _ctx_rows(conn, center_row[0], radius, radius)
    bef = [_entry(r, nb_cap) for r in before]
    aft = [_entry(r, nb_cap) for r in after]
    used += sum(est_tokens(x["text"]) + 12 for x in bef + aft)
    l1 = clip(_cover_l1(conn, center_row[0]), 120)
    l2 = clip(_cover_l2(conn, center_row[0]), 90)
    crit = [mask_text(clip(c, 60)) for c in _crit_for(conn, norms)]
    used += est_tokens(l1) + est_tokens(l2) + sum(est_tokens(c) for c in crit) + 20
    dates = [norm_date(m[2]) for m in members if m[2]]
    out = {"center": center, "before": bef, "after": aft, "members": len(members),
           "member_ids": [m[1] for m in members[:3]], "period": f"{min(dates) if dates else ''}..{max(dates) if dates else ''}"}
    if l1:
        out["l1"] = l1
    if l2:
        out["l2"] = l2
    if crit:
        out["critical"] = crit
    return out, used


def _brief_cluster(center_row, members, cap=70, match_type="lens", score=None):
    dates = [norm_date(m[2]) for m in members if m[2]]
    c = _entry(center_row, cap)
    c["match_type"] = match_type
    if score is not None:
        c["score"] = round(score, 4)
    return {"center": c, "members": len(members),
            "period": f"{min(dates) if dates else ''}..{max(dates) if dates else ''}",
            "expand": {"focus_event_id": center_row[1]}}, est_tokens(c["text"]) + 30


def lens(user_id, query, raw_results=None, budget=1500, focus_event_id=None, radius=2, offset=0,
         kind=None, source=None, project=None):
    cfg = config()
    gap = int(cfg.get("lens_gap", 3))
    max_clusters = int(cfg.get("lens_clusters_max", 5))
    conn = sqlite3.connect(f"file:{db_path(user_id)}?mode=ro", uri=True, timeout=10)
    try:
        if focus_event_id:
            if not focus_event_id.startswith(f"{user_id}::"):
                return {"mode": "focus", "clusters": [], "error": "event not found"}
            row = conn.execute("SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE event_id=?", (focus_event_id,)).fetchone()
            if not row:
                return {"mode": "focus", "clusters": [], "error": "event not found"}
            bodies = _scan(user_id)
            rare, _ = query_terms(query, bodies) if query else ([], [])
            full, used = _full_cluster(conn, row, [row], [t["norm"] for t in rare], budget, radius=max(1, radius), match_type="focus")
            while (full["before"] or full["after"]) and est_tokens(json.dumps(full, ensure_ascii=False)) > budget:
                (full["before"] if len(full["before"]) >= len(full["after"]) else full["after"]).pop(0 if len(full["before"]) >= len(full["after"]) else -1)
            used = est_tokens(json.dumps(full, ensure_ascii=False))
            return {"mode": "focus", "terms": [t["term"] for t in rare], "clusters": [full], "clusters_total": 1,
                    "total_hits": 1, "more_cursor": None, "tokens": used}
        bodies = _scan(user_id)
        rare, all_terms = query_terms(query, bodies)
        norms = [t["norm"] for t in rare]
        # exact substring hits (all), ranked by number of rare terms then recency
        phrase = _norm(re.sub(r"[^\w\s\-]", "", query or ""))
        idf = {t["norm"]: t["idf"] for t in rare}
        sub_hits = []
        for rid, eid, b in bodies:
            k = sum(idf[n] * math.log1p(min(b.count(n), 20)) for n in norms if n in b)
            ph = 1 if (len(phrase) > 5 and len(norms) > 1 and phrase in b) else 0
            if k or ph:
                sub_hits.append((k + 5 * ph, rid, eid, ph))
        sub_hits.sort(key=lambda x: (-x[0], -x[1]))
        phrase_ids = {e for _, _, e, ph in sub_hits if ph}
        sub_ids = [e for _, _, e, _ in sub_hits]
        bm = []
        if norms:
            try:
                from app import semantic as sem
                bm = [e for e, _ in sem.fts_ranked(user_id, " ".join(t["term"] for t in rare), limit=60)]
            except Exception:
                bm = []
        if raw_results:
            sem_list = [r["event_id"] for r in raw_results if str(r.get("event_id", "")).startswith(f"{user_id}::")]
        else:
            sem_list = _semantic_list(user_id, query)
        fused = _rrf(sem_list, bm, sub_ids[:200], sub_ids[:200])
        if kind or source or project:
            try:
                from app import shelves as sh
                ok = sh.allowed(user_id, list(fused.keys()), kind, source, project)
                fused = {e: s for e, s in fused.items() if e in ok}
                sub_ids = [e for e in sub_ids if e in ok]
            except Exception as e:
                print(f"[lens] shelf filter skipped: {e}", flush=True)
        total_hits = len(set(sub_ids) | set(bm)) or len(fused)
        if sub_ids or bm:
            keep = set(sub_ids[:200]) | set(bm) | set(sem_list[:10])
            fused = {e: v for e, v in fused.items() if e in keep}
        top = sorted(fused.items(), key=lambda x: -x[1])[:80]
        if not top:
            return {"mode": "search", "terms": [t["term"] for t in rare], "clusters": [], "clusters_total": 0, "total_hits": 0, "more_cursor": None, "tokens": 0}
        ids = [e for e, _ in top]
        q = "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ids))
        rows = {r[1]: r for r in conn.execute(q, ids)}
        score = dict(top)
        ordered = sorted([rows[e] for e in ids if e in rows], key=lambda r: r[0])
        clusters, cur = [], []
        for r in ordered:
            if cur and r[0] - cur[-1][0] > gap:
                clusters.append(cur)
                cur = []
            cur.append(r)
        if cur:
            clusters.append(cur)
        ranked = []
        for c in clusters:
            best = max(c, key=lambda r: score.get(r[1], 0))
            cs = max(score.get(r[1], 0) for r in c) + 0.002 * math.log1p(len(c))
            ranked.append((cs, best, c))
        ranked.sort(key=lambda x: -x[0])
        sub_set = set(sub_ids)
        bm_set = set(bm)

        def mt(eid):
            return "phrase" if eid in phrase_ids else ("keyword" if eid in sub_set or eid in bm_set else "vector")

        out, used = [], 0
        page = ranked[offset:]
        for i, (cs, best, members) in enumerate(page):
            if len(out) >= max_clusters:
                break
            if i == 0:
                full, u = _full_cluster(conn, best, members, norms, int(budget * 0.6), radius=min(radius, 2), match_type=mt(best[1]), score=score.get(best[1]))
                out.append(full)
                used += u
            else:
                br, u = _brief_cluster(best, members, match_type=mt(best[1]), score=score.get(best[1]))
                if used + u > budget:
                    break
                out.append(br)
                used += u
        while len(out) > 1 and est_tokens(json.dumps(out, ensure_ascii=False)) + 60 > budget:
            out.pop()
        used = est_tokens(json.dumps(out, ensure_ascii=False))
        nxt = offset + len(out)
        return mask_obj_safe({"mode": "search", "terms": [t["term"] for t in rare], "dropped_terms": [t["term"] for t in all_terms if t not in rare],
                              "clusters": out, "clusters_total": len(ranked), "total_hits": total_hits,
                              "more_cursor": nxt if nxt < len(ranked) else None, "tokens": used})
    finally:
        conn.close()


def mask_obj_safe(o):
    from app.memory_v2 import mask_obj
    return mask_obj(o)
