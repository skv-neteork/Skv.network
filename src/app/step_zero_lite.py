"""Step-zero memory for MCP clients (port of mcp_skv._sz_memory). Small response: avoids >16KB stalls."""

import re, os, sqlite3, time as _time

SEAL_FMT = "🔐 SKV | #{n:03d} | [READ ✓] [VERIFY ✓] [CORRECT ✓] [OUTPUT ✓]"

_SEAL_RE = re.compile(r"🔐\s*SKV\s*\|\s*#(\d+)[^\n]*?OUTPUT\s*✓\]?")

def _cut_at(text: str, size: int) -> int:
    """Best cut position <= size on a cube/paragraph/sentence/word boundary (never mid-word)."""
    if len(text) <= size:
        return len(text)
    win = text[:size]
    for sep in ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
        k = win.rfind(sep)
        if k >= size * 0.5:
            return k + len(sep)
    k = win.rfind(" ")
    return k + 1 if k > 0 else size

def _trim_words(text: str, n: int) -> str:
    """Shorten at a sentence/word boundary; marks the cut explicitly (no silent mid-word cut)."""
    text = text or ""
    if len(text) <= n:
        return text
    return text[:_cut_at(text, n)].rstrip() + " [cut]"

def _ev_time(eid: str) -> str:
    m = re.search(r"_(1[6-9]\d{8})\d*$", eid or "")
    return _time.strftime("%Y-%m-%d %H:%M UTC", _time.gmtime(int(m.group(1)))) if m else ""

def _norm_seal(text: str) -> str:
    """Old seal spellings in stored memory -> canonical server format."""
    return _SEAL_RE.sub(lambda m: SEAL_FMT.format(n=int(m.group(1))), text or "")

def _seals_in(text: str) -> list:
    return [int(x) for x in re.findall(r"SKV \| #(\d+)", text or "")]

def _sid(eid: str) -> str:
    return (eid or "").split("::")[-1]

def _sz_memory(n_tail: int = 4, an: int = 700) -> tuple:
    """Memory part of step_zero; every item carries [ev:id]. Returns (text, items) for turn's citation check."""
    c = _udb()
    if c is None:
        return "=== MEMORY ===\n(no saved memory yet)", []
    items, parts = [], []
    def qa(raw, qn, an):
        raw = _norm_seal(re.sub(r"\n?🔐 SKV \|[^\n]*", "", raw or ""))
        q, _, a = raw.partition("\nA:")
        q = re.sub(r"^Q:\s*", "", q).strip()
        return "Q: " + _trim_words(q, qn) + " A: " + _trim_words(a.strip(), an)
    rows0 = c.execute("SELECT rowid, event_id, raw_dialogue FROM event_metadata WHERE raw_dialogue NOT LIKE '%[lightweight]%' ORDER BY rowid DESC LIMIT 40").fetchall()
    rows, qseen = [], set()
    for r in rows0:
        q = re.sub(r"^Q:\s*", "", (r[2] or "").partition("\nA:")[0]).strip()
        qn = re.sub(r"\([^)]*\)|\W+", " ", q.lower()).strip()
        if re.match(r"\s*(\[(latency[ _-]?test|report|test|probe|ping|service)[^\]]*\]|zz)", q, re.I):
            continue
        if len(qn) < 12 or re.fullmatch(r"(да|нет|ок|ok|yes|no|go|продолжай|продолжи|дальше|continue|next|давай|согласен|понял)( \w+){0,2}", qn):
            continue
        k = " ".join(qn.split()[:12])
        if k in qseen:
            continue
        qseen.add(k); rows.append(r)
        if len(rows) > n_tail:
            break
    ids = {r[0]: r[1] for r in c.execute("SELECT rowid, event_id FROM event_metadata").fetchall()}
    if rows:
        r = rows[0]; txt = qa(r[2], 600, 1500)
        parts.append("=== HOW THE LAST SESSION ENDED ===\n[ev:%s] %s %s" % (_sid(r[1]), _ev_time(r[1]), txt)); items.append((r[1], txt))
        parts.append("=== AGENT NOTE (first reply only) ===\nTell the user in one line: memory line loaded, the last thing you remember, ready to continue. Do not repeat this every turn.")
        tl = []
        for r in rows[1:]:
            txt = qa(r[2], 260, an); tl.append("[ev:%s] %s %s" % (_sid(r[1]), _ev_time(r[1]), txt)); items.append((r[1], txt))
        parts.append("=== MEMORY TAIL (newest first) ===\n" + "\n".join(tl))
    lay = []
    try:
        _tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    except Exception:
        _tabs = set()
    try:
        for t, frm, to in ([] if "summary_l2_blocks" not in _tabs else c.execute("SELECT text, from_rowid, to_rowid FROM summary_l2_blocks ORDER BY id DESC LIMIT 1").fetchall()):
            e = ids.get(int(to or 0)) or ids.get(max([k for k in ids if k <= int(to or 0)] or [0]), "")
            if e:
                txt = _trim_words(t or "", 700); lay.append("L2 [ev:%s] (covers events %s-%s) %s" % (_sid(e), frm, to, txt)); items.append((e, txt))
        for t, frm, to in ([] if "summary_l1" not in _tabs else c.execute("SELECT summary_text, from_rowid, to_rowid FROM summary_l1 ORDER BY to_rowid DESC LIMIT 1").fetchall()):
            e = ids.get(int(to or 0)) or ids.get(max([k for k in ids if k <= int(to or 0)] or [0]), "")
            if e:
                t = re.sub(r"(?s)^.*?\"summary\":\s*", "", t or ""); txt = _trim_words(re.sub(r"\s+", " ", t), 900)
                lay.append("L1 [ev:%s] (covers events %s-%s) %s" % (_sid(e), frm, to, txt)); items.append((e, txt))
    except Exception as ex:
        print("[step_zero] layers skipped: %s" % ex, flush=True)
    if lay:
        parts.append("=== MEMORY LAYERS (L2 map, L1 stages; id = last event of the range) ===\n" + "\n".join(lay))
    cr, seen = [], set()
    for e, raw in c.execute("SELECT event_id, raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE '%>>>%' ORDER BY rowid DESC LIMIT 6").fetchall():
        for ln in re.findall(r">>> ([^\n]+)", raw or ""):
            if ln not in seen:
                seen.add(ln); cr.append("[ev:%s] %s %s" % (_sid(e), _ev_time(e), _trim_words(ln, 200))); items.append((e, ln))
    try:
        for v, ctx, e in c.execute("SELECT value, context, event_id FROM critical_auto ORDER BY time_str DESC LIMIT 6").fetchall():
            if e and v not in seen:
                seen.add(v); txt = "%s: %s" % (v, _sentence_ctx(c, e, v, ctx)); cr.append("[ev:%s] (auto) %s" % (_sid(e), txt)); items.append((e, txt))
    except Exception:
        pass
    parts.append("=== CRITICAL FACTS ===\n" + ("\n".join(cr) or "(none)"))
    c.close()
    return "\n\n".join(parts), items

def _sentence_ctx(c, e, v, ctx) -> str:
    """Whole sentence(s) around value v from the event's raw dialogue; never starts mid-word."""
    raw = ""
    try:
        row = c.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id=?", (e,)).fetchone(); raw = (row or [""])[0] or ""
    except Exception:
        pass
    src = raw if v and v in raw else (ctx or "")
    i = src.find(v) if v else -1
    if i < 0:
        i = 0
    bs = [m.end() for m in re.finditer(r"[.!?](?=\s)|\n", src[:i])]; a = bs[-1] if bs else 0
    if i - a > 160:
        sp = src.find(" ", i - 120); a = sp + 1 if 0 <= sp < i else i
    mb = re.compile(r"[.!?](?=\s|$)|\n").search(src, i + len(v or "")); b = mb.start() if mb else len(src)
    out = src[a:b + 1].strip()
    if a > 0 and not re.match(r"[A-ZА-ЯЁ0-9\"«(>]", out):
        out = re.sub(r"^\S*\s+", "", out)
    return _trim_words(out, 240)


def _udb_for(uid):
    base = (uid or "").replace("@", "").replace(".", "")
    for n in (base, base.replace("+", "")):
        p = "/data/skv/metadata_store/%s.db" % n
        if n and os.path.exists(p):
            try:
                c = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=5)
                c.execute("SELECT 1 FROM event_metadata LIMIT 1")
                return c
            except Exception:
                continue
    return None

_UID = {"u": ""}
def _udb():
    return _udb_for(_UID["u"])

def last_seal(uid):
    c = _udb_for(uid)
    if c is None:
        return 0
    try:
        for (raw,) in c.execute("SELECT raw_dialogue FROM event_metadata ORDER BY rowid DESC LIMIT 60"):
            ss = _seals_in(_norm_seal(raw or ""))
            if ss:
                return max(ss)
    finally:
        c.close()
    return 0

def build(uid, n_tail=4, an=700, budget=7300):
    _UID["u"] = uid
    for nt, a in ((n_tail, an), (4, 500), (3, 450), (2, 400), (1, 300)):
        mem, items = _sz_memory(nt, a)
        if len(mem) <= budget:
            break
    try:
        from app import profile as _prof
        pb = _prof.block(uid)
    except Exception:
        pb = ""
    try:
        tz = _prof.get_tz(uid)
    except Exception:
        tz = "UTC"
    return {"seal": last_seal(uid), "memory": mem, "profile": pb, "tz": tz,
            "items": [[e, (x or "")[:300]] for e, x in items]}

