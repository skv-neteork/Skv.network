"""Passage lexical rerank of the top of a text search result (consult idea; ablation 2026-11-02).

Long dialogue events often hold the answer in one short span; whole-event BM25/vector scores dilute it.
For each of the top N results, find the best ~60-token window and the share of query content stems in it,
then rescore: 1/(rank+5) + lam * share. Only when the query is in the memory's base language
(cross-language queries have no lexical overlap; the agent is told to query in the base language).
Config (q2s.json): passage_rr (1), passage_rr_lam (0.2), passage_rr_n (20). Env SKV_PASSAGE_RR=0 turns it off.
"""
import os, re, time, sqlite3

_SW = {"en": set("the and is are was were you that this with have for not what when where who how which did does do".split()),
       "de": set("der die das und ist nicht ich ein eine mit auch wie wann wo wer was welche hat".split()),
       "es": set("el la los las que es una por para con como pero cuando donde quien cual qué cuándo dónde quién cómo".split()),
       "fr": set("le la les et est une des que pour avec pas dans quand où qui quel quelle comment".split())}
_STOP = set("что как какой какая какие каким какую когда где кто почему зачем сколько это для при над под или чем его она они был была было".split()) | _SW["en"]
_mem = {}


def lang(t):
    t = t or ""
    cyr = len(re.findall(r"[А-Яа-яЁёІіЇїЄє]", t)); lat = len(re.findall(r"[A-Za-z]", t))
    if cyr + lat == 0:
        return None
    if cyr >= 0.5 * lat:
        return "uk" if len(re.findall(r"[ІіЇїЄє]", t)) > 0.01 * cyr else "ru"
    w = re.findall(r"[a-zäöüßñéèàçáíóú]+", t.lower())
    sc = {k: sum(1 for x in w if x in v) for k, v in _SW.items()}
    if re.search(r"[äöüß]", t.lower()): sc["de"] += 2
    if re.search(r"[ñ¿¡]", t.lower()): sc["es"] += 2
    return max(sc, key=sc.get) if max(sc.values()) else "en"


def _db(uid):
    from app import semantic as S
    return sqlite3.connect("/data/skv/metadata_store/%s.db" % S.account_name(uid))


def base_lang(uid, ttl=86400):
    h = _mem.get(uid)
    if h and time.time() - h[1] < ttl:
        return h[0]
    c = _db(uid)
    try:
        rows = c.execute("SELECT raw_dialogue FROM event_metadata WHERE raw_dialogue IS NOT NULL ORDER BY rowid DESC LIMIT 400").fetchall()
    finally:
        c.close()
    votes = {}
    for (t,) in rows:
        t = (t or "")[:3000]
        if len(re.findall(r"[A-Za-zА-Яа-яЁё]", t)) < 20:
            continue
        lg = lang(t); votes[lg] = votes.get(lg, 0) + 1
    lg = max(votes, key=votes.get) if votes else None
    _mem[uid] = (lg, time.time())
    return lg


def toks(s):
    return [t[:5] if len(t) > 5 else t for t in re.findall(r"[\w/.:-]+", (s or "").lower()) if len(t) > 2 and t not in _STOP]


def _texts(uid, ids):
    c = _db(uid)
    try:
        q = "SELECT event_id, raw_dialogue FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ids))
        return {e: t or "" for e, t in c.execute(q, ids)}
    finally:
        c.close()


def rerank(uid, query, out, cfg):
    """out: list of dicts with event_id (search_text output). Returns a reordered list (same items)."""
    if (os.environ.get("SKV_PASSAGE_RR") or "").strip().lower() in ("0", "off", "false", "no"):
        return out
    if not cfg.get("passage_rr", 1) or not out or len(out) < 2:
        return out
    ql = lang(query)
    if not ql or ql != base_lang(uid):
        return out
    qt = set(toks(query))
    if not qt:
        return out
    lam = float(cfg.get("passage_rr_lam", 0.2)); n = int(cfg.get("passage_rr_n", 20))
    head = out[:n]
    tx = _texts(uid, [o.get("event_id") for o in head if o.get("event_id")])
    sc = []
    for r, o in enumerate(head):
        w = toks(tx.get(o.get("event_id"), "")); best = 0.0
        for i in range(0, max(1, len(w) - 40 + 1), 20):
            best = max(best, len(qt & set(w[i:i + 60])) / len(qt))
        sc.append((1.0 / (r + 5) + lam * best, -r, o))
    return [o for _s, _r, o in sorted(sc, key=lambda x: (-x[0], -x[1]))] + list(out[n:])
