"""Q2S (2026-11-02): search a QUESTION the way its answer was written.

Vector search of "What do Melanie's kids like?" misses "They were stoked for the dinosaur exhibit" (rank 43-157);
the statement form finds it. Bench /data/skv/q2s (eval5.json; hit@5 raw -> Q2S):
  - questions: raw hybrid + rule forms (undo EN do-support/inversion, wh-strip RU/DE/ES/FR), RRF sum:
    LoCoMo EN 65% -> 67%, MRR 0.45 -> 0.51; and every question uses hybrid instead of the
    name_and_meaning route (that route: 42% hit@5 on the same 144 questions);
  - agent-supplied search_as (forms by the calling model): hybrid(raw)x0.3 + max over forms:
    cross-lingual RU/DE/ES 19% -> 26%, Deniz RU/EN MRR 0.54 -> 0.60-0.65, LoCoMo EN 65% -> 58-61% (small loss);
  - server cheap-LLM rewrite: no gain -> off (q2s_llm).

Switch: /data/skv/search_config.json "q2s": true|false (read on every call, no restart);
env SKV_Q2S=0 forces off. Off -> search_text._text_search_core exactly as before.
Rollback: /root/skv-core/rollback_q2s.sh
Q2S-PRON sub-flag "q2s_pron" (app/q2s_pron.py): names -> exact entity set, question -> short pronoun event forms
searched by vector inside it; an event that >=2 forms agree on (top-5 in each) is lifted to rank 4
(never above the top 3 of this RRF). Off -> exactly the Q2S above.
Rollback: rollback_q2s.sh pron-off (instant) | rollback_q2s.sh pron (remove hook + module)
"""
import os, re, json, time, contextvars, hashlib, sqlite3

SEARCH_AS = contextvars.ContextVar("q2s_search_as", default=None)
CFG = "/data/skv/search_config.json"
DEF = {"q2s": False, "q2s_rules": True, "q2s_llm": False, "q2s_model": "google/gemini-2.5-flash-lite", "q2s_timeout_s": 1.5,
       "q2s_w_raw": 1.0, "q2s_w_raw_agent": 0.3, "q2s_w_rules": 1.0, "q2s_w_agent": 1.0, "q2s_w_llm": 0.8, "q2s_fuse_agent": "max", "q2s_fuse_rules": "sum",
       "q2s_pron": False}
CACHE = "/data/skv/metadata_store/q2s_cache.db"
_cfg_cache = {"m": None, "v": dict(DEF)}
STATS = {"agent": 0, "rules": 0, "llm": 0, "skip": 0, "err": 0}


def cfg():
    try:
        m = os.path.getmtime(CFG)
        if m != _cfg_cache["m"]:
            v = dict(DEF); v.update(json.load(open(CFG)))
            _cfg_cache.update(m=m, v=v)
    except Exception:
        pass
    return _cfg_cache["v"]


def enabled():
    if (os.environ.get("SKV_Q2S") or "").strip().lower() in ("0", "off", "false", "no"):
        return False
    return bool(cfg().get("q2s"))


def sanitize(search_as, query=""):
    """Agent forms: list or 'a | b' / newline string -> max 3 clean statements <= 160 chars."""
    if not search_as:
        return []
    if isinstance(search_as, str):
        s = search_as.strip()
        if s.startswith("["):
            try:
                search_as = json.loads(s)
            except Exception:
                search_as = [s]
        else:
            search_as = re.split(r"\s*(?:\n|\|)\s*", s)
    out, seen = [], {(query or "").strip().lower()}
    for f in search_as if isinstance(search_as, (list, tuple)) else []:
        f = re.sub(r"[`*_#>\[\]{}]", " ", str(f or ""))
        f = re.sub(r"\s+", " ", f).strip(" -\"'")[:160]
        if len(f) >= 3 and f.lower() not in seen:
            seen.add(f.lower()); out.append(f)
        if len(out) >= 3:
            break
    return out


# ---------------- rules (no LLM) ----------------
import re
_WH = r"(what|when|where|who|whom|whose|which|why|how|what kind of|what type of|what types of|how many|how much|how long|how often)"
_AUX = r"(did|do|does|is|are|was|were|has|have|had|can|could|will|would|should)"
_EN_Q = re.compile(r"^\s*" + _WH + r"((?:\s+\w+){0,3}?)\s+" + _AUX + r"\s+(.+?)\s*\??\s*$", re.I)
_EN_Q2 = re.compile(r"^\s*" + _AUX + r"\s+(.+?)\s*\??\s*$", re.I)
_WH_ANY = re.compile(r"^\s*(what|when|where|who|which|why|how)\b\s*", re.I)
_RU_WH = re.compile(r"\b(что|чего|чем|когда|где|куда|откуда|кто|кого|кому|как|почему|зачем|сколько|какой|какая|какое|какие|каким|какую|какого|ли|же)\b", re.I)
_DE_WH = re.compile(r"^\s*(was|wann|wo|woher|wohin|wer|wen|wem|wie|warum|welche[rsnm]?|wieviel)\b\s*", re.I)
_ES_WH = re.compile(r"^\s*[¿¡]?\s*(qué|que|cuándo|cuando|dónde|donde|quién|quien|cómo|como|por qué|cuál|cual|cuánto|cuántos|cuántas)\b\s*", re.I)
_FR_WH = re.compile(r"^\s*(qu'est-ce que|que|quand|où|qui|comment|pourquoi|quel|quelle|quels|quelles|combien)\b\s*", re.I)
_NAME = re.compile(r"\b([A-ZА-ЯЁ][\w'’-]+)")
_SKIPCAP = set("what when where who which why how did do does is are was were i the a an что когда где кто как почему сколько какой какая какие was wann wo wer wie warum qué cuándo dónde".split())

def _names(q):
    out = []
    for m in _NAME.finditer(q):
        w = m.group(1)
        if w.lower().strip("'’s") in _SKIPCAP or m.start() == 0 and w.lower() in _SKIPCAP:
            continue
        if m.start() == 0 or q[:m.start()].strip() in ("¿",):
            continue
        out.append(w)
    return out

def _first_person(s, names):
    for n in names:
        base = re.sub(r"['’]s$", "", n)
        s = re.sub(r"\b" + re.escape(base) + r"['’]s\b", "my", s)
        s = re.sub(r"\b" + re.escape(base) + r"\b", "I", s, count=1)
    s = re.sub(r"\bher\b|\bhis\b|\btheir\b", "my", s)
    return re.sub(r"\s+", " ", s).strip()

def is_question(q):
    q = (q or "").strip()
    return q.endswith("?") or bool(_EN_Q.match(q) or _WH_ANY.match(q) or _RU_WH.search(q[:25]) or _DE_WH.match(q) or _ES_WH.match(q))

def forms(q):
    q = (q or "").strip()
    out = []
    names = _names(q)
    m = _EN_Q.match(q)
    if m:
        rest = m.group(4)
        head = [w for w in (m.group(2) or "").split() if w.lower() not in ("of", "kind", "type", "types", "sort")]
        if head:
            rest = rest + " " + " ".join(head)
        out.append(rest)
        subj = rest.split()[0] if rest.split() else ""
        if subj[:1].isupper() and not subj.isupper():
            out.append(_first_person(rest, [subj]))
    else:
        m2 = _EN_Q2.match(q)
        s = None
        if m2 and re.match(r"^[A-Za-z]", q):
            s = m2.group(2)
        elif _WH_ANY.match(q):
            s = _WH_ANY.sub("", q).rstrip("? ")
        elif re.search(r"[а-яё]", q, re.I):
            s = re.sub(r"\s+", " ", _RU_WH.sub(" ", q)).strip(" ?")
        elif _DE_WH.match(q):
            s = _DE_WH.sub("", q).rstrip("? ")
        elif _ES_WH.match(q):
            s = _ES_WH.sub("", q).strip("¿? ")
        elif _FR_WH.match(q):
            s = _FR_WH.sub("", q).rstrip("? ")
        if s:
            out.append(s)
            subj = s.split()[0] if s.split() else ""
            if re.match(r"^[A-Za-z]", s) and subj[:1].isupper() and not subj.isupper() and subj.lower() not in ("the", "i"):
                out.append(_first_person(s, [subj]))
    seen, res = set(), []
    for f in out:
        f = f.strip()
        if f and f.lower() != q.lower() and f.lower() not in seen:
            seen.add(f.lower()); res.append(f)
    return res[:3]


# ---------------- optional server cheap-LLM (off by default: no gain on the eval) ----------------
_LLM_SYS = ("You rewrite a memory-search question into short declarative search texts. Goal: retrieval, not answering.\n"
            "Rules:\n- Do NOT answer. Never invent the missing fact. No placeholders like [date].\n"
            "- Statement form, not a question: undo question word order and do-support.\n"
            "- Keep names and specific words exactly.\n"
            "- Give 3 items, each under 12 words: third person; first person as said in chat; a paraphrase with synonyms.\n"
            "- Language: the question language, plus one English item if the question is not English.\n"
            "Output only a JSON array of strings.")


def _cache():
    c = sqlite3.connect(CACHE, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS q2s_cache (h TEXT PRIMARY KEY, forms TEXT, t REAL)")
    return c


def llm_forms(query):
    v = cfg()
    h = hashlib.sha256(("v1|%s|%s" % (v["q2s_model"], re.sub(r"\s+", " ", query.strip().lower()))).encode()).hexdigest()[:24]
    try:
        c = _cache()
        row = c.execute("SELECT forms FROM q2s_cache WHERE h=?", (h,)).fetchone()
        c.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    try:
        from app import consult_pool as _P
        from app.security import polza_post
        body = {"model": v["q2s_model"], "max_tokens": 200,
                "messages": [{"role": "system", "content": _LLM_SYS}, {"role": "user", "content": query[:300]}]}
        r = _P._post(polza_post, body, float(v["q2s_timeout_s"]))
        txt = r.json()["choices"][0]["message"].get("content") or ""
        m = re.search(r"\[.*\]", txt, re.S)
        arr = sanitize(json.loads(m.group(0)) if m else [], query)
        c = _cache(); c.execute("INSERT OR REPLACE INTO q2s_cache VALUES (?,?,?)", (h, json.dumps(arr, ensure_ascii=False), time.time())); c.commit(); c.close()
        return arr
    except Exception as e:
        print("[q2s] llm skipped: %s" % type(e).__name__, flush=True)
        return []


# ---------------- search ----------------
def _fuse(lists, top_k, k=60, mode="sum"):
    """Weighted RRF. lists = [(weight, [(eid, score)], family)]; mode "max" = max over the forms of one family, then sum."""
    fam = {}
    for w, lst, f in lists:
        d = fam.setdefault(f if mode == "max" else id(lst), {})
        for r, (e, _s) in enumerate(lst):
            v = w / (k + r + 1)
            d[e] = max(d.get(e, 0.0), v) if mode == "max" else d.get(e, 0.0) + v
    sc = {}
    for d in fam.values():
        for e, v in d.items():
            sc[e] = sc.get(e, 0.0) + v
    return sorted(sc.items(), key=lambda x: -x[1])[:top_k]


def plan(query, search_as=None):
    """-> (kind, forms) ; kind in agent|rules|llm|None (None = use the normal path)."""
    v = cfg()
    agent = sanitize(search_as, query)
    if agent:
        return "agent", agent
    if not is_question(query):
        return None, []
    fs = forms(query) if v.get("q2s_rules", True) else []
    if v.get("q2s_llm"):
        lf = llm_forms(query)
        if lf:
            return "llm", fs + lf
    return "rules", fs   # a question with no rule forms still gets raw hybrid (not the name_and_meaning route)


def search(uid, query, top_k=20, search_as=None):
    """Fused [(event_id, score)] or None when Q2S does not apply."""
    from app import search_v2 as _v2
    v = cfg()
    kind, fs = plan(query, search_as)
    if not kind:
        STATS["skip"] += 1
        return None
    pool = max(60, top_k)
    raw, _ = _v2.hybrid(uid, query, top_k=pool)
    w_raw = v["q2s_w_raw_agent"] if kind == "agent" else v["q2s_w_raw"]
    w_f = {"agent": v["q2s_w_agent"], "rules": v["q2s_w_rules"], "llm": v["q2s_w_llm"]}[kind]
    lists = [(w_raw, raw, "raw")]
    for f in fs:
        try:
            lists.append((w_f, _v2.hybrid(uid, f, top_k=pool)[0], kind))
        except Exception as e:
            print("[q2s] form skipped: %s" % type(e).__name__, flush=True)
    STATS[kind] += 1
    mode = v.get("q2s_fuse_agent", "max") if kind == "agent" else v.get("q2s_fuse_rules", "sum")
    if v.get("q2s_pron") and is_question(query):   # 2026-11-02 Q2S-PRON: names exact + short pronoun form by meaning inside them
        try:
            from app import q2s_pron as _pr
            res = _fuse(lists, top_k, mode=mode)
            return _pr.insert(res, _pr.lists(uid, query, v), v)[:top_k]
        except Exception as e:
            print("[q2s] pron skipped: %s" % type(e).__name__, flush=True)
    return _fuse(lists, top_k, mode=mode)


def text_core(uid, query, top_k=20, since=None, until=None, exclude_imports=False, source=None):
    """search_text.text_search entry: Q2S when on and applicable, else the unchanged _text_search_core."""
    from app import search_text as _st, search_v2 as _v2
    if enabled() and _v2.enabled() and not (since or until or exclude_imports or (source and source.lower() != "events")):
        try:
            fused = search(uid, query, top_k, SEARCH_AS.get())
            if fused:
                out = _st._arch(uid, query, _st._out(uid, fused))
                if out:
                    return out
        except Exception as e:
            STATS["err"] += 1
            print("[q2s] fallback to normal search: %s" % type(e).__name__, flush=True)
    return _st._text_search_core(uid, query, top_k, since, until, exclude_imports, source)
