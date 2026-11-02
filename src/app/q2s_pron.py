"""Q2S-PRON (2026-11-02): a question -> proper names (exact) + a SHORT pronoun event form (vector), searched
by meaning INSIDE the events that contain the names, fused with the live Q2S result by RRF.

Why: "What do Melanie's kids like?" vs the stored turn "They were stoked for the dinosaur exhibit":
raw question = rank 31 (16 within Melanie turns); "they liked it" / "им понравилось" = rank 4 (1 within Melanie turns).
Names do the filtering, the pronoun form carries the event shape; common nouns of the subject ("kids") are dropped
because they pull every other turn about kids.

Purely rule-based, no LLM, multilingual (EN do-support/inversion, RU, DE, ES, FR basic).
Switch: /data/skv/search_config.json "q2s_pron": true|false (needs "q2s": true). Off -> Q2S exactly as before.
Rollback: /root/skv-core/rollback_q2s.sh pron-off  (instant)  |  rollback_q2s.sh pron  (remove the hook)
"""
import os, re, sqlite3, time, unicodedata
import numpy as np

DEF = {"q2s_pron": False, "q2s_pron_min_set": 3, "q2s_pron_max_frac": 0.6,
       "q2s_pron_k": 30, "q2s_pron_forms": 4,
       "q2s_pron_top": 5, "q2s_pron_agree": 3, "q2s_pron_agree_min": 2, "q2s_pron_pos": 3, "q2s_pron_n": 1}
STATS = {"lifted": 0, "used": 0, "filtered": 0, "global": 0, "noforms": 0, "err": 0, "ms": 0.0}

# ---------------------------------------------------------------- names
_WORDS_NOT_NAMES = set("""what when where who whom whose which why how did do does is are was were has have had can could will would should
the a an i in on at of to for and or but if my your his her their our its this that these those lgbtq
что когда где куда откуда кто кого кому как почему зачем сколько какой какая какое какие каким какую какого ли же я мы ты вы он она они
was wann wo woher wohin wer wen wem wie warum welche welcher welches welchen wieviel hat haben ist sind ich
qué que cuándo cuando dónde donde quién quien cómo como por cuál cual cuánto cuántos cuántas el la los las les
qu quand où qui comment pourquoi quel quelle quels quelles combien est-ce le""".split())

_TOK = re.compile(r"[\wÀ-ÿА-Яа-яЁё'’-]+", re.U)


def names(q):
    """Capitalised words that are not question/function words: Melanie's -> Melanie, Melanies -> Melanies (DE handled at match)."""
    out = []
    for m in _TOK.finditer(q or ""):
        w = m.group(0).strip("'’-")
        if not w[:1].isupper() or len(w) < 2:
            continue
        base = re.sub(r"['’]s$", "", w)
        if base.lower() in _WORDS_NOT_NAMES or re.match(r"(?i)^(qu|d|l)['’]", w):
            continue
        if base.isupper() and len(base) <= 5 and m.start() == 0:
            continue
        if base not in out:
            out.append(base)
    return out


def persons(nm):
    """Names that can be a grammatical subject (not acronyms like LGBTQ / ЛГБТК-группу / RAM)."""
    return [n for n in nm if not (len(n) > 1 and n[:2].isupper())]


_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))


def _skel(w):
    """Rough phonetic skeleton so Кэролайн ~ Caroline, Мелани ~ Melanie, Selectel ~ Селектел."""
    w = w.lower()
    w = "".join(_TR.get(ch, ch) for ch in w)
    w = unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode()
    w = re.sub(r"[^a-z]", "", w)
    for a, b in (("ph", "f"), ("ck", "k"), ("c", "k"), ("q", "k"), ("x", "ks"), ("w", "v"), ("y", "i"), ("j", "i"), ("h", "")):
        w = w.replace(a, b)
    w = re.sub(r"[aeiou]+", "a", w)
    return re.sub(r"(.)\1+", r"\1", w)


_VOCAB = {}   # uid -> (n_events, {skeleton: set(surface words)})


def _vocab(uid, conn):
    n = conn.execute("SELECT max(rowid) FROM event_metadata").fetchone()[0] or 0
    v = _VOCAB.get(uid)
    if v and v[0] == n:
        return v[1]
    sk = {}
    for (raw,) in conn.execute("SELECT raw_dialogue FROM event_metadata WHERE raw_dialogue NOT LIKE '[archived]%'"):
        for w in re.findall(r"\b[A-ZА-ЯЁ][a-zа-яё]{2,}", raw or ""):
            s = _skel(w)
            if len(s) >= 3:
                sk.setdefault(s, set()).add(w)
    _VOCAB[uid] = (n, sk)
    if len(_VOCAB) > 20:
        _VOCAB.pop(next(iter(_VOCAB)))
    return sk


def entity_events(uid, nm, conn):
    """Events containing any of the names (stemmed FTS), with cross-script / declension fallback via the account's
    own capitalised-word vocabulary (Кэролайн -> Caroline, Melanies -> Melanie, Мелании -> Мелани)."""
    from app import search_v2 as V
    V.sync(conn)
    hits, used = set(), []
    for n in nm:
        cands = [n]
        rows = []
        for c in cands:
            rows = conn.execute("SELECT event_id FROM events_fts_stem WHERE events_fts_stem MATCH ?", ('"' + V.stem(c.lower()).replace('"', '') + '"',)).fetchall()
            if rows:
                break
        if not rows:
            sk = _skel(n)
            voc = _vocab(uid, conn)
            alt = set(voc.get(sk, ()))
            if not alt:   # declension / genitive -s: drop the last 1-2 letters of the skeleton
                for cut in (1, 2):
                    if len(sk) - cut >= 4:
                        alt |= {w for s, ws in voc.items() if s == sk[:-cut] for w in ws}
                        if alt:
                            break
            for a in sorted(alt)[:3]:
                rows += conn.execute("SELECT event_id FROM events_fts_stem WHERE events_fts_stem MATCH ?", ('"' + V.stem(a.lower()).replace('"', '') + '"',)).fetchall()
        if rows:
            used.append(n)
            hits.update(r[0] for r in rows)
    return hits, used


# ---------------------------------------------------------------- pronoun event forms
_EN_IRR = {"go": "went", "do": "did", "have": "had", "make": "made", "see": "saw", "get": "got", "take": "took", "buy": "bought", "find": "found",
           "give": "gave", "come": "came", "think": "thought", "tell": "told", "say": "said", "feel": "felt", "become": "became", "begin": "began",
           "bring": "brought", "build": "built", "choose": "chose", "draw": "drew", "drink": "drank", "drive": "drove", "eat": "ate", "fall": "fell",
           "fly": "flew", "forget": "forgot", "grow": "grew", "hear": "heard", "keep": "kept", "know": "knew", "learn": "learned", "leave": "left",
           "lose": "lost", "meet": "met", "pay": "paid", "put": "put", "read": "read", "ride": "rode", "run": "ran", "sell": "sold", "send": "sent",
           "sing": "sang", "sit": "sat", "sleep": "slept", "speak": "spoke", "spend": "spent", "swim": "swam", "teach": "taught", "throw": "threw",
           "understand": "understood", "wear": "wore", "win": "won", "write": "wrote", "paint": "painted", "be": "was", "hold": "held", "lead": "led",
           "set": "set", "stand": "stood", "break": "broke", "catch": "caught", "fight": "fought", "hang": "hung", "lend": "lent", "shoot": "shot"}


def _past(v):
    v = v.lower()
    if v in _EN_IRR:
        return _EN_IRR[v]
    if v.endswith("e"):
        return v + "d"
    if re.search(r"[^aeiou]y$", v):
        return v[:-1] + "ied"
    if re.search(r"[^aeiou][aeiou][bdgmnpt]$", v) and len(v) <= 4:
        return v + v[-1] + "ed"
    return v + "ed"


_EN_WH = r"(?:what|when|where|who|whom|whose|which|why|how)(?:\s+(?:kind|kinds|type|types|sort)\s+of)?(?:\s+(?:long|many|much|often|old|far|soon))?"
_EN_AUX = r"(did|do|does|is|are|was|were|has|have|had|can|could|will|would|might|may|should)"
_EN_Q = re.compile(r"^\s*(" + _EN_WH + r")((?:\s+[a-z]+){0,2}?)\s+" + _EN_AUX + r"\s+(.+?)\s*\??\s*$", re.I)
_EN_YN = re.compile(r"^\s*" + _EN_AUX + r"\s+(.+?)\s*\??\s*$", re.I)
_EN_WHSUBJ = re.compile(r"^\s*(who|what)\s+((?:[a-z]+ed|[a-z]+s|went|made|gave|got|said|told|took|wrote|bought)\b.*?)\s*\??\s*$", re.I)
_PLURAL_N = set("kids children family parents friends sons daughters siblings brothers sisters grandparents pets dogs cats team colleagues coworkers students".split())
_EN_GROUP = re.compile(r"^((?:[A-Z][\w-]*['’]s\s+)?(?:\w+\s+){0,2}?)([a-z]+)\b")
_STOP_OBJ = set("a an the some any".split())


def _en_split_subject(rest, nm):
    """rest = '<subject> <verb phrase>'. Subject: 'X', "X's kids", 'X and Y', 'X and her kids', 'her kids'.
    -> (pronoun_subj, pronoun_obj, plural, verb_phrase)"""
    toks = rest.split()
    i, plural, first_is_name = 0, False, False
    if not toks:
        return None
    t0 = re.sub(r"['’]s$", "", toks[0])
    poss = toks[0] != t0 or toks[0].lower() in ("her", "his", "their", "my", "our", "your")
    if t0 in nm or toks[0].lower() in ("her", "his", "their", "my", "our", "your", "she", "he", "they", "i", "we", "you"):
        i = 1
        first_is_name = not poss
        if poss:   # X's [adj] noun
            j = i
            while j < len(toks) and j < i + 3 and not re.match(r"^(\w+ed|\w+ing)$", toks[j]) and toks[j].lower() not in ("and",):
                if toks[j].lower() in _PLURAL_N or (toks[j].endswith("s") and not toks[j].endswith("ss") and len(toks[j]) > 3):
                    plural = True; j += 1; break
                j += 1
                if j - i >= 1 and toks[j - 1][:1].islower():
                    break
            i = j
        if i < len(toks) and toks[i].lower() == "and":
            plural = True
            i += 1
            while i < len(toks) and (re.sub(r"['’]s$", "", toks[i]) in nm or toks[i].lower() in ("her", "his", "their", "kids", "children", "family", "husband", "wife", "partner", "friends")):
                i += 1
    else:
        return None
    vp = " ".join(toks[i:])
    if plural:
        return "they", "them", True, vp
    return "I", "me", False, vp


def _forms_en(q, nm):
    m = _EN_Q.match(q)
    wh, aux, rest = None, None, None
    if m:
        wh, aux, rest = m.group(1).lower(), m.group(3).lower(), m.group(4)
        if m.group(2).strip():   # 'what books did X read' -> object noun goes after the verb
            rest = rest + " " + m.group(2).strip()
    else:
        m = _EN_YN.match(q)
        if m and q[:1].isupper():
            aux, rest = m.group(1).lower(), m.group(2)
    if not rest:
        m = _EN_WHSUBJ.match(q)
        return [m.group(2)] if m else []
    sp = _en_split_subject(rest, nm)
    if not sp:
        return []
    subj, obj, plural, vp = sp
    toks = vp.split()
    out = []
    if aux in ("did", "do", "does"):
        if not toks:
            return []
        verb, tail = toks[0], [t for t in toks[1:] if t.lower() not in _STOP_OBJ]
        past, pres = _past(verb), verb if (plural or subj == "I") else (verb + "s")
        tail_s = " ".join(tail)
        if aux == "did":
            out += [f"{subj} {past} it" if not tail else f"{subj} {past}", f"{subj} {past} {tail_s}".strip()]
        else:
            out += [f"{subj} {pres} it" if not tail else f"{subj} {pres}", f"{subj} {past} it" if not tail else f"{subj} {past}",
                    f"{subj} {pres} {tail_s}".strip()]
    elif aux in ("is", "are", "was", "were"):
        be = {"I": "am", "they": "are"}.get(subj, "is") if aux in ("is", "are") else ("were" if plural else "was")
        if toks and re.match(r"^\w+ing$", toks[0]):
            out += [f"{subj} {be} {vp}", f"{subj} {be} {toks[0]}"]
        elif rest.split()[0].endswith(("'s", "’s")) and not vp:   # what is X's identity -> my identity is
            noun = " ".join(rest.split()[1:])
            out += [f"{'my' if subj == 'I' else 'their'} {noun}", f"{subj} {be}"]
        else:
            out += [f"{subj} {be} {vp}".strip()]
    elif aux in ("has", "have", "had"):
        hv = "have" if subj in ("I", "they") else "has"
        out += [f"{subj} {hv} {vp}".strip()]
        if toks and toks[0] == "been" and len(toks) > 1:
            out.append(f"{subj} {hv} been {toks[1]}")
    else:
        out += [f"{subj} {aux} {vp}".strip()]
    return out


_RU_WH = re.compile(r"\b(что|чего|чем|чему|когда|где|куда|откуда|кто|кого|кому|как|почему|зачем|сколько|какой|какая|какое|какие|каким|какую|какого|какой-то|ли|же|разве|именно)\b", re.I)
_RU_DAT = re.compile(r"\b(нрав\w*|понрав\w*|понравил\w*)\b", re.I)
_RU_VERB = re.compile(r"\w+(л|ла|ло|ли|лся|лась|лось|лись|ет|ют|ит|ят|ть|ться|ется|ются)$", re.I)


def _forms_ru(q, nm):
    s = q.strip().rstrip("?!. ")
    toks = s.split()
    low = [t.lower() for t in toks]
    nmset = {n.lower() for n in nm}
    plural = False
    keep = []
    for i, t in enumerate(toks):
        w = t.lower().strip(",.")
        if _RU_WH.fullmatch(w):
            continue
        if re.sub(r"['’]s$", "", t) in nm or w in nmset:
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if nxt and (re.sub(r"['’]s$", "", nxt) in nm) and not _RU_VERB.fullmatch(w) and w not in ("у", "с", "к", "о", "от", "для", "и", "в", "на"):
            plural = plural or w.endswith(("ям", "ей", "и", "ы", "ам", "ов"))   # детям/детей/дети/друзьям -> they
            continue   # "детям Мелани": the possessed noun is the subject -> pronoun
        if w == "у" and nxt and re.sub(r"['’]s$", "", nxt) in nm:
            keep.append("у меня")
            continue
        prev = [x.lower() for x in toks[max(0, i - 2):i]]
        if (w == "и" and i > 0 and toks[i - 1] in nm) or (w in ("её", "ее", "его", "их", "мои", "свои") and "и" in prev):
            plural = True
            continue
        if plural and i > 0 and toks[i - 1].lower() in ("её", "ее", "его", "их", "свои") and not _RU_VERB.fullmatch(w):
            continue   # "Мелани и её дети": дети -> они
        keep.append(t)
    body = " ".join(k for k in keep if k)
    body = re.sub(r"\s+", " ", body).strip(" ,")
    if not body:
        return []
    out = []
    if _RU_DAT.search(body):
        p = "им" if plural else "мне"
        v = _RU_DAT.search(body).group(0)
        out += [f"{p} понравилось", f"{p} {body}"]
        if not v.lower().startswith("понрав"):
            out.append(f"{p} нравится")
    else:
        verbs = [t for t in body.split() if _RU_VERB.fullmatch(t.lower())]
        past = any(re.search(r"(л|ла|ло|ли|лся|лась|лось|лись)$", v.lower()) for v in verbs)
        p = "они" if plural else ("я" if past else "")
        out += [f"{p} {body}".strip()]
        if verbs and len(body.split()) >= 2:
            out.append(f"{p} {verbs[0]}".strip())
    if "у меня" in body:
        out = [body] + [o for o in out if o != body]
    return out


_DE = re.compile(r"^\s*(was|wann|wo|woher|wohin|wer|wen|wem|wie|warum|welche[rsnm]?|wieviel|wie\s+lange|wie\s+viele?)\s+(\w+)\s+(.+?)\s*\?*\s*$", re.I)
_ES_WH = re.compile(r"^\s*[¿¡]?\s*(qué|que|cuándo|cuando|dónde|donde|adónde|quién|quien|cómo|como|por qué|cuál|cual|cuánto|cuántos|cuántas|de dónde)\b\s*", re.I)
_FR_WH = re.compile(r"^\s*(qu['’]est-ce\s+qu['’]?e?|que|qu['’]|quand|où|d['’]où|qui|comment|pourquoi|quel|quelle|quels|quelles|combien)\s*", re.I)


def _forms_de(q, nm):
    m = _DE.match(q)
    if not m:
        return []
    verb, rest = m.group(2), m.group(3)
    toks = [t for t in rest.split() if re.sub(r"s$", "", t) not in nm and t not in nm]
    plural = any(t in nm or re.sub(r"s$", "", t) in nm for t in rest.split()) and any(t.lower() in ("kinder", "eltern", "freunde", "familie") for t in toks) \
        or " und " in rest
    toks = [t for t in toks if t.lower() not in ("kinder", "eltern", "freunde", "familie", "und", "ihre", "seine")]
    aux = verb.lower() in ("hat", "haben", "ist", "sind", "war", "waren", "hatte", "hatten")
    p = "sie" if plural else "ich"
    vv = verb.lower()
    if not plural:
        vv = {"hat": "habe", "ist": "bin", "war": "war", "hatte": "hatte", "mag": "mag", "mögen": "mag"}.get(vv, vv)
    body = " ".join(toks)
    out = [f"{p} {vv} {body}".strip()]
    if not aux and verb.lower().startswith(("mög", "mag", "lieb", "gefäll", "gefall")):
        out.append(f"{p} {'mochten' if plural else 'mochte'} es")
    return out


def _forms_es(q, nm):
    if not _ES_WH.match(q):
        return []
    s = _ES_WH.sub("", q).strip("¿? ")
    s = re.sub(r"\b(a\s+)?(los|las|el|la)\s+(hijos|hijas|niños|amigos|padres|familia)\s+de\s+\w+", " ", s, flags=re.I)
    plural = bool(re.search(r"\b(les|hijos|niños|amigos|padres|y sus)\b", q, re.I))
    s = " ".join(t for t in s.split() if t not in nm and re.sub(r"['’]s$", "", t) not in nm and t.lower() not in ("de", "y", "sus", "su"))
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return []
    out = [s]
    if re.search(r"\bgust", s):
        out.append(("les" if plural else "me") + " gustó")
    return out


def _forms_fr(q, nm):
    if not _FR_WH.match(q):
        return []
    s = _FR_WH.sub("", q).strip("? ")
    s = re.sub(r"\b(les|des)\s+(enfants|amis|parents)\s+d[e']\s*\w+", " ils ", s, flags=re.I)
    s = " ".join(t for t in s.split() if t not in nm and t.lower() not in ("est-ce", "que", "qu'"))
    return [re.sub(r"\s+", " ", s).strip()] if s.strip() else []


def forms(q, nm=None, maxn=4):
    q = (q or "").strip()
    nm = names(q) if nm is None else nm
    nm = persons(nm)
    if not nm:
        return []   # no person -> no pronoun subject; the live Q2S rule forms already cover it
    if re.search(r"[а-яё]", q, re.I):
        out = _forms_ru(q, nm)
    elif re.match(r"^\s*[¿¡]", q) or _ES_WH.match(q) and re.search(r"[áéíóúñ¿]", q):
        out = _forms_es(q, nm)
    elif _DE.match(q) and not _EN_Q.match(q):
        out = _forms_de(q, nm)
    elif _FR_WH.match(q) and re.search(r"[àâçéèêëîïôûù]|est-ce", q, re.I):
        out = _forms_fr(q, nm)
    else:
        out = _forms_en(q, nm)
    res, seen = [], {q.lower()}
    for f in out:
        f = re.sub(r"\s+", " ", f).strip(" ,?")
        if len(f) >= 3 and f.lower() not in seen:
            seen.add(f.lower()); res.append(f)
    return res[:maxn]


# ---------------------------------------------------------------- search
def _vectors(uid, ids):
    from app import semantic as S
    e = S.STORE._load(S.active_tag(), S.account_name(uid))
    if not e:
        return [], None
    have = [i for i in ids if i in e["pos"]]
    if not have:
        return [], None
    with S.STORE.lock:
        try:
            M = np.asarray(e["index"].get_items([e["pos"][i] for i in have]), dtype=np.float32)
        except RuntimeError:            # some labels were removed from the index: fetch one by one
            ok, rows = [], []
            for i in have:
                try:
                    rows.append(e["index"].get_items([e["pos"][i]])[0]); ok.append(i)
                except RuntimeError:
                    pass
            if not ok:
                return [], None
            have, M = ok, np.asarray(rows, dtype=np.float32)
    M /= np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-9)
    return have, M


def lists(uid, query, cfgv=None, k=None):
    """-> [(eid, cos)] per form, or [] when nothing applies. Never raises."""
    t = time.time()
    try:
        from app import semantic as S, search_v2 as V
        c = dict(DEF); c.update(cfgv or {})
        k = k or int(c["q2s_pron_k"])
        nm = names(query)
        if not persons(nm):
            STATS["noforms"] += 1
            return []
        conn = sqlite3.connect(V._db(uid), timeout=10)
        try:
            ent, used = entity_events(uid, nm, conn)
            n_all = conn.execute("SELECT count(*) FROM event_metadata").fetchone()[0] or 1
        finally:
            conn.close()
        de = bool(_DE.match(query) and not _EN_Q.match(query))   # German capitalises every noun: only names found in memory are names
        fs = forms(query, used if de else nm, int(c["q2s_pron_forms"]))
        if not fs:
            STATS["noforms"] += 1
            return []
        Q = S.embed(fs)
        out = []
        if ent and len(ent) >= int(c["q2s_pron_min_set"]) and len(ent) / n_all <= float(c["q2s_pron_max_frac"]):
            ids, M = _vectors(uid, [e for e in ent if e.startswith(uid + "::")])
            if ids:
                STATS["filtered"] += 1
                sims = Q @ M.T
                for row in sims:
                    o = np.argsort(-row)[:k]
                    out.append([(ids[j], float(row[j])) for j in o])
        if not out:
            STATS["global"] += 1
            name = S.account_name(uid)
            for v in Q:
                hits = S.STORE.search(S.active_tag(), name, v, k=k)
                out.append([(e, s) for e, s in hits if e.startswith(uid + "::")])
        STATS["used"] += 1
        return out
    except Exception as e:
        STATS["err"] += 1
        print("[q2s_pron] skipped: %s" % type(e).__name__, flush=True)
        return []
    finally:
        STATS["ms"] += (time.time() - t) * 1000


def insert(res, pl, cfgv=None):
    """Consensus lift (2026-11-02, chosen on the eval: additive RRF of the forms regressed LoCoMo).
    res: fused [(eid, score)] of live Q2S. An event that is in the top-`top` of >= max(agree_min, min(agree, #forms))
    pronoun-form lists is moved to position `pos` (0-based) unless it is already above it. Never touches the top `pos`."""
    c = dict(DEF); c.update(cfgv or {})
    if not pl or len(pl) < int(c["q2s_pron_agree_min"]):
        return res
    t, pos = int(c["q2s_pron_top"]), int(c["q2s_pron_pos"])
    need = max(int(c["q2s_pron_agree_min"]), min(int(c["q2s_pron_agree"]), len(pl)))
    cnt, best = {}, {}
    for lst in pl:
        for r, (e, _s) in enumerate(lst[:t]):
            cnt[e] = cnt.get(e, 0) + 1
            best[e] = min(best.get(e, 99), r)
    cand = [e for e in sorted(cnt, key=lambda e: (-cnt[e], best[e])) if cnt[e] >= need][:int(c["q2s_pron_n"])]
    out = list(res)
    for j, e in enumerate(cand):
        ids = [x for x, _ in out]
        p = pos + j
        if e in ids and ids.index(e) <= p:
            continue
        if e in ids:
            out.pop(ids.index(e))
        sc = out[p - 1][1] if 0 < p <= len(out) else (out[0][1] if out else 1.0)
        out.insert(min(p, len(out)), (e, sc))
        STATS["lifted"] += 1
    return out
