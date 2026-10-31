"""Draft-specific Second Look: rule-based questions (no model call) that quote the draft.

Design follows Chain-of-Verification (Dhuliawala et al. 2023): open, factual verification questions
about concrete claims, answered apart from the draft, revising only what fails. Yes/no "is the draft ok?"
checklists get reaffirmed on autopilot, so every question here names the exact phrase and asks for a source
or a concrete answer. No rule fires -> no questions (silence). Reminders only; nothing is blocked.
"""
import re, sqlite3, time

MAX_Q = 4
_EV = re.compile(r"\[ev:[^\]]+\]")
_SENT = re.compile(r"(?<=[.!?…])\s+|\n+")
_PAST = re.compile(r"(?i)\b(you (said|wrote|told|asked|mentioned|decided|prefer|want|like|use)|your [a-z]+ (is|was|are)|"
                   r"last time|earlier|previously|yesterday|we (agreed|decided|discussed|did)|as before|"
                   r"ты (писал|говорил|просил|сказал|решил|хотел|предпочитаешь|любишь)|вы (писали|говорили|просили|сказали|решили)|"
                   r"раньше|ранее|вчера|в прошлый раз|прошлый раз|мы (решили|договорились|обсуждали|делали)|как и раньше|твой [а-яё]+ —)")
_DATE = re.compile(r"(?i)\b(\d{1,2}[./]\d{1,2}([./]\d{2,4})?|\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}|"
                   r"\d{1,2} (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|\d{1,2} (январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*)\b")
_NUM = re.compile(r"(?<![\w#·])(\d+[.,]?\d*\s?%|\d{3,}(?:[.,]\d+)?|\d+[.,]\d+)(?![\w])")
_FILLER = re.compile(r"(?i)^\s*(great|good|excellent|interesting) (question|point)|^\s*(let me|let's|first,|sure[,!]|of course|certainly|"
                     r"отличн|хорош|интересн|давай|сначала|конечно|понял|ок[,.!]|хорошо[,.!])")
_QWORD = re.compile(r"(?i)^\s*(what|which|who|when|where|why|how|is|are|do|does|did|can|should|сколько|что|какой|какая|какие|кто|когда|где|почему|зачем|как|можно|есть ли|ли\b)")
_STOP = set("the a an and or of to in on for is are was it this that with you your i me my не и в на с что как это по к за из у о от до ли а но же то".split())


_TOK = re.compile(r"[#\w][\w.,:/#·%+-]*")
_VER = re.compile(r"(?i)v?\d+(\.\d+){2,}[a-z0-9-]*|v\d+(\.\d+)*[a-z0-9-]*")


def _num_tokens(s):
    """Full numeric tokens worth a source: dates/times, numbers with >=3 digits, decimals, percents.
    Skipped: versions (0.1.3, v2), ids/hashes (79fb1679, t648u, ev ids), #numbers and seals."""
    s = _EV.sub(" ", re.sub(r"🔐[^\n]*", " ", s))
    for m in _TOK.finditer(s):
        t = m.group(0).rstrip(".,:;/-")
        if not re.search(r"\d", t) or t.startswith("#") or _VER.fullmatch(t):
            continue
        if re.search(r"[A-Za-zА-Яа-яЁё_]", t.rstrip("%")) or re.fullmatch(r"[0-9a-f]{6,}", t):
            continue   # mixed letters+digits = an id, hash or name, not a quantity
        if _DATE.fullmatch(t) or _NUM.fullmatch(t):
            yield t


def _words(s):
    return {w for w in re.findall(r"[a-zа-яё0-9]{3,}", (s or "").lower()) if w not in _STOP}


def _stem(w):
    return w[:5]


def _q(s, n=110):
    s = re.sub(r"\s+", " ", _EV.sub("", s)).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def questions(draft, user_message="", facts=None, tool_text=""):
    """Return up to MAX_Q {rule, quote, ask} dicts; [] when nothing fires."""
    d = re.sub(r"\n?🔐 SKV \|[^\n]*", "", draft or "").strip()
    if not d:
        return []
    facts = facts or []
    known = (user_message or "") + "\n" + (tool_text or "") + "\n" + "\n".join(str(f.get("fact", "")) for f in facts)
    sents = [s.strip() for s in _SENT.split(d) if len(s.strip()) > 3]
    out, seen = [], set()

    def add(rule, quote, ask):
        k = (rule, quote[:40])
        if k not in seen and len(out) < MAX_Q:
            seen.add(k); out.append({"rule": rule, "quote": quote, "ask": ask})

    # 1. unlinked claim about the user / the past
    for s in sents:
        if _PAST.search(s) and not _EV.search(s):
            add("unlinked_past", _q(s), 'You wrote "%s". Which [ev:id] is this from? If none, say it is unknown.' % _q(s)); break
    # 2. contradiction with a newer fact: cited ev vs a later fact on the same subject
    by_ev = {str(f.get("ev")): f for f in facts if f.get("ev")}
    for s in sents:
        for m in re.findall(r"\[ev:([^\]]+)\]", s):
            f0 = by_ev.get(m.strip())
            if not f0:
                continue
            w0 = {_stem(w) for w in _words(f0.get("fact"))}
            for f1 in facts:
                if f1 is f0 or not f1.get("time") or not f0.get("time") or str(f1["time"]) <= str(f0["time"]):
                    continue
                if len(w0 & {_stem(w) for w in _words(f1.get("fact"))}) >= 3:
                    add("newer_fact", _q(s), 'You wrote "%s" from [ev:%s] (%s). Newer [ev:%s] (%s) says "%s". What holds now?'
                        % (_q(s, 80), m, str(f0["time"])[:16], f1["ev"], str(f1["time"])[:16], _q(str(f1.get("fact")), 80)))
                    break
    # 3. number or date without a source
    for s in sents:
        if _EV.search(s):
            continue
        hit = next((tok for tok in _num_tokens(s) if tok not in known), None)
        if hit:
            add("unsourced_number", _q(s), 'You wrote "%s". Where does "%s" come from: this turn\'s tool result, a memory [ev:id], or the user? If none, drop or mark it.' % (_q(s), hit.strip())); break
    # 4. no direct answer in the first sentence
    um = (user_message or "").strip()
    if sents and (um.endswith("?") or _QWORD.search(um)) and len(um) < 400:
        first = sents[0]
        qs = {_stem(w) for w in _words(um)}
        if _FILLER.search(first) or (qs and not (qs & {_stem(w) for w in _words(first)}) and len(sents) > 2):
            add("no_direct_answer", _q(first), 'Your first sentence is "%s". What is the one-sentence answer to "%s"? Put it first.' % (_q(first, 80), _q(um, 80)))
    # 5. much longer than the question needs
    if um and len(um) < 200 and len(d) > max(900, 10 * len(um)):
        add("too_long", _q(sents[0], 60), 'The question is %d chars, the draft %d. Which parts after "%s" does the user not need for this question?' % (len(um), len(d), _q(sents[0], 60)))
    return out


# ── stats: asked / kept / changed per account ──
def _db(path):
    c = sqlite3.connect(path, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS sl_q (user TEXT PRIMARY KEY, pending INTEGER, asked INTEGER DEFAULT 0, "
              "answered INTEGER DEFAULT 0, kept INTEGER DEFAULT 0, changed INTEGER DEFAULT 0, unanswered INTEGER DEFAULT 0, t REAL)")
    return c


def parse_answer(s):
    """'kept' / 'changed: ...' ; several answers separated by '|' or ';'. Returns (kept, changed)."""
    k = c = 0
    for p in re.split(r"[|;\n]+", s or ""):
        p = p.strip().lower()
        if p.startswith(("changed", "изменил", "change")):
            c += 1
        elif p.startswith(("kept", "keep", "оставил", "ok")):
            k += 1
    return k, c


def record(path, user, asked_now, answer="", revised=False):
    """Book the answer to the previous questions, then store the new pending count. Returns stats dict."""
    try:
        c = _db(path)
        r = c.execute("SELECT pending FROM sl_q WHERE user=?", (user,)).fetchone()
        if not r:
            c.execute("INSERT INTO sl_q (user, pending, t) VALUES (?,0,?)", (user, time.time())); r = (0,)
        pend = r[0] or 0
        if pend:
            k, ch = parse_answer(answer)
            if revised and not (k or ch):
                ch = pend
            if k or ch:
                c.execute("UPDATE sl_q SET answered=answered+?, kept=kept+?, changed=changed+? WHERE user=?", (min(k + ch, pend), k, ch, user))
            else:
                c.execute("UPDATE sl_q SET unanswered=unanswered+? WHERE user=?", (pend, user))
        c.execute("UPDATE sl_q SET pending=?, asked=asked+?, t=? WHERE user=?", (asked_now, asked_now, time.time(), user))
        c.commit()
        return stats(path, user, c)
    except Exception:
        return {}


def stats(path, user, c=None):
    c = c or _db(path)
    r = c.execute("SELECT asked, answered, kept, changed, unanswered FROM sl_q WHERE user=?", (user,)).fetchone()
    if not r:
        return {}
    a, ans, k, ch, un = r
    return {"asked": a, "answered": ans, "kept": k, "changed": ch, "unanswered": un,
            "revision_rate": round(ch / (k + ch), 3) if (k + ch) else None}
