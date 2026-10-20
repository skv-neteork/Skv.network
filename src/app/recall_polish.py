"""Recall polish (20.10.2026): post-processing of the agent-view /api/v7/memory pack.
Reranks (fresh decisions/L1/critical up; bulk chat import, bot drafts, code/log blobs down; dates in the
query are understood), cleans service text, dedupes, and fits the pack into ~3000 tokens.
Read-only over stored memory. Disable with memory_v2 config {"polish": false}."""
import re, json, sqlite3, datetime, os

BASE = "/data/skv/metadata_store"
TARGET_TOKENS = 3000
STOP = set("что как где когда почему зачем какой какая какие кто про это для или and the what how why when which who does about with from идея такое есть было будет хочет делают делает запланировано".split())
PLAN_WORDS = ("план", "запланир", "задач", "доск", "todo", "task", "board", "roadmap", "сделать", "дедлайн", "срок")


def _name(uid):
    return "".join(c for c in uid if c.isalnum() or c in "_-")


def _tok(s):
    from app.memory_v2 import est_tokens
    return est_tokens(s)


def query_dates(q, year=None):
    """'23.10', '20.10.2026', '2026-10-23', '23 октября' -> [date]"""
    year = year or datetime.date.today().year
    out = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", q or ""):
        out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?![\d])", q or ""):
        y = m.group(3)
        y = int(y) + (2000 if y and len(y) == 2 else 0) if y else year
        out.append((y, int(m.group(2)), int(m.group(1))))
    try:
        from app.on_this_day import dates_in
        for d in dates_in(q or "") or []:
            if isinstance(d, (tuple, list)) and len(d) == 3:
                out.append((d[0] or year, int(d[1]), int(d[2])))
    except Exception:
        pass
    res = []
    for y, mo, d in out:
        try:
            dt = datetime.date(y, mo, d)
            if dt not in res:
                res.append(dt)
        except ValueError:
            pass
    return res


def _date_forms(dt):
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    return [dt.strftime("%d.%m"), f"{dt.day}.{dt.month:02d}", dt.isoformat(), f"{dt.day} {months[dt.month-1]}"]


def terms(q):
    out = []
    for w in re.findall(r"\w[\w-]*", (q or "").lower()):
        w = w.replace("-", "")
        if len(w) < 3 or w in STOP or w.isdigit():
            continue
        st = w[:max(4, min(6, len(w) - 2))] if len(w) > 5 else w
        if st not in out:
            out.append(st)
    return out


# ---------- cleaning ----------
_THINK = re.compile(r"<thinking>.*?(</thinking>|$)", re.S | re.I)
_FENCE = re.compile(r"```.*?(```|$)", re.S)
_SERVICE = re.compile(r"^\s*(DRAFT\s*:|SECOND LOOK|Second Look\s*[:—-]|🔐|SEAL\b|#\s*SEAL|\[SKV SEAL|CORRECTED\s*:|FINAL\s*:|<\/?answer>)", re.I)


def clean(text):
    s = str(text or "")
    s = _THINK.sub(" ", s)
    s = _FENCE.sub(lambda m: " [код опущен] " if len(m.group(0)) > 160 else m.group(0), s)
    lines = []
    for ln in s.split("\n"):
        if _SERVICE.search(ln):
            continue
        t = ln.strip()
        if re.fullmatch(r"[-=*_|: ]{3,}", t):
            continue
        if t.startswith("|") and t.count("|") >= 3:   # markdown table row -> compact
            t = " · ".join(c.strip() for c in t.strip("|").split("|") if c.strip() and not re.fullmatch(r"[-: ]+", c.strip()))
            if not t:
                continue
        if re.match(r"^(Traceback|  File \"|\s*at |\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+)", ln):
            continue
        lines.append(t)
    s = " ".join(x for x in lines if x)
    s = re.sub(r"\*\*|__|#{1,6} ", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def codeish(text):
    s = str(text or "")
    if not s:
        return 0.0
    sym = sum(s.count(c) for c in "{}[]();=<>/\\_$")
    fences = s.count("```")
    logs = len(re.findall(r"(Traceback|ERROR|INFO:|DEBUG|exit_code|\bdef |\bimport |docker |\bsudo )", s))
    return min(1.0, sym / max(1, len(s)) * 6 + fences * 0.1 + logs * 0.05)


def is_service(text):
    s = str(text or "")
    return bool(re.search(r"<thinking>|\bDRAFT\s*:|Second Look|SEAL #", s))


def clip(s, chars):
    s = s or ""
    if len(s) <= chars:
        return s
    cut = s[:chars]
    p = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:p + 1] if p > chars * 0.6 else cut.rstrip()) + " …"


# ---------- scoring ----------
def _kind(eid):
    tail = eid.split("::", 1)[-1]
    if tail.startswith("grokexp_"):
        return "import"
    if tail.startswith(("critical_",)):
        return "critical"
    if tail.startswith("task_skv"):
        return "task"
    if tail.startswith(("remember_", "profile_", "grokbot_main")):
        return "note"
    if tail.startswith("chat_"):
        return "chat"
    return "other"


def _parse_ts(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts)[:19].replace("T", " "))
    except Exception:
        try:
            return datetime.datetime.fromisoformat(str(ts)[:10])
        except Exception:
            return None


META = ("skv", "скв", "/api/", "api ", "памят", "memory", "сервер", "server", "guard", "куб", "cube", "grokexp_", "агент", "agent", "бот", "endpoint", "конституц")


def meta_query(q):
    ql = (q or "").lower()
    return any(m in ql for m in META) or any(w in ql for w in PLAN_WORDS) or "дениз" in ql or "deniz" in ql or bool(query_dates(q))


def score(row, tq, dates, prior, now, mq=True):
    eid, ts, raw = row["event_id"], row.get("time_str"), row.get("raw") or ""
    low = raw.lower().replace("-", "")
    q_part = low.split("\na:", 1)[0] if low.startswith("q:") else low[:300]
    cov = sum(1 for t in tq if t in low)
    covq = sum(1 for t in tq if t in q_part)
    s = (cov / max(1, len(tq))) * 2.0 + covq * 0.4 + prior * 3.0
    if len(low) > 2500:
        s *= 0.85   # long digests match everything
    k = _kind(eid)
    s *= {"import": 0.7, "critical": 1.3, "task": 1.2, "note": 1.1, "chat": 0.8}.get(k, 1.0)
    if row.get("crit"):
        s *= 1.4
    if not mq and k != "import" and sum(1 for m in META if m in low) >= 2:
        s *= 0.45   # talk about SKV itself, for a question that is not about SKV
    if is_service(raw):
        s *= 0.55
    c = codeish(raw)
    if c > 0.35:
        s *= 1 - min(0.6, c)
    dt = _parse_ts(ts)
    if dt:
        age = max(0.0, (now - dt).total_seconds() / 86400)
        s *= 1 + 0.35 / (1 + age / 3)      # fresh decisions float up, old ones stay reachable
    if dates:
        hit = False
        for d in dates:
            if (ts or "").startswith(d.isoformat()) or any(f in raw for f in _date_forms(d)):
                hit = True
        s = s * 2.2 + 1.0 if hit else s * 0.8
    if len(clean(raw)) < 40:
        s *= 0.5
    return s


def _rows(uid, ids):
    if not ids:
        return {}
    c = sqlite3.connect(os.path.join(BASE, _name(uid) + ".db"), timeout=10)
    try:
        out = {}
        ids = list(ids)
        for i in range(0, len(ids), 300):
            ch = ids[i:i + 300]
            for eid, ts, raw, ess in c.execute(
                    "SELECT event_id, time_str, raw_dialogue, essence FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ch)), ch):
                out[eid] = {"event_id": eid, "time_str": ts, "raw": raw or ess or ""}
        try:
            gone = {r[0] for r in c.execute("SELECT event_id FROM event_forgotten")}
            out = {k: v for k, v in out.items() if k not in gone}
        except Exception:
            pass
        return out
    finally:
        c.close()


def _extra_candidates(uid, q, dates):
    ids = []
    try:
        from app import semantic as _sem
        ids += [e for e, _ in _sem.fts_ranked(uid, q, limit=40)]
    except Exception:
        pass
    c = sqlite3.connect(os.path.join(BASE, _name(uid) + ".db"), timeout=10)
    try:
        for d in dates:
            for f in _date_forms(d)[:1] + [d.isoformat()]:
                ids += [r[0] for r in c.execute(
                    "SELECT event_id FROM event_metadata WHERE (time_str LIKE ? OR raw_dialogue LIKE ?) AND event_id NOT LIKE '%::grokexp_%' ORDER BY time_str DESC LIMIT 25",
                    (f + "%", "%" + f + "%"))]
        # newest own notes that share a query term (fresh decisions)
        for t in terms(q)[:4]:
            ids += [r[0] for r in c.execute(
                "SELECT event_id FROM event_metadata WHERE event_id NOT LIKE '%::grokexp_%' AND lower(raw_dialogue) LIKE ? ORDER BY time_str DESC LIMIT 8",
                ("%" + t + "%",))]
    finally:
        c.close()
    return ids


def _crit_ids(uid):
    c = sqlite3.connect(os.path.join(BASE, _name(uid) + ".db"), timeout=10)
    try:
        s = {r[0] for r in c.execute("SELECT event_id FROM event_metadata WHERE raw_dialogue LIKE '%>>>%' OR event_id LIKE '%::critical_%' LIMIT 500")}
        try:
            s |= {r[0] for r in c.execute("SELECT event_id FROM critical_auto")}
        except Exception:
            pass
        return s
    finally:
        c.close()


def l1_summaries(uid, q, dates, k=3):
    tq = terms(q)
    c = sqlite3.connect(os.path.join(BASE, _name(uid) + ".db"), timeout=10)
    try:
        rows = c.execute("SELECT topic, summary_text, created_at FROM summary_l1 ORDER BY created_at DESC LIMIT 400").fetchall()
    finally:
        c.close()
    now = datetime.datetime.now()
    sc = []
    for topic, txt, created in rows:
        body = ((topic or "") + " " + (txt or "")).lower().replace("-", "")
        cov = sum(1 for t in tq if t in body)
        if not cov and not dates:
            continue
        s = cov / max(1, len(tq))
        if dates and any(any(f in (topic or "") + (txt or "") for f in _date_forms(d)) or str(created or "").startswith(d.isoformat()) for d in dates):
            s += 1.0
        dt = _parse_ts(created)
        if dt:
            s *= 1 + 0.5 / (1 + max(0, (now - dt).days) / 3)
        if s >= 0.5:
            sc.append((s, topic, txt, created))
    sc.sort(key=lambda x: -x[0])
    return [{"date": str(cr)[:16], "topic": t, "text": clip(clean(x), 420)} for s, t, x, cr in sc[:k]]


def calendar_items(uid, dates):
    out = []
    try:
        c = sqlite3.connect(os.path.join(BASE, _name(uid) + ".db"), timeout=10)
        for d in dates:
            for dd, title, kind in c.execute("SELECT date, title, kind FROM agent_calendar WHERE date LIKE ?", (d.isoformat() + "%",)):
                out.append({"date": dd, "title": title, "kind": kind})
        c.close()
    except Exception:
        pass
    try:
        from app import on_this_day as _otd
        for d in dates:
            for r in (_otd.collect(uid, d, 0, 10) or [])[:5]:
                out.append(r if isinstance(r, dict) else {"item": str(r)[:200]})
    except Exception:
        pass
    return out[:8]


def polish(uid, q, res, cfg=None):
    cfg = cfg or {}
    if not isinstance(res, dict) or not q or cfg.get("polish", True) is False:
        return res
    now = datetime.datetime.now()
    dates = query_dates(q, now.year)
    tq = terms(q)
    # pool with priors from the original order
    pool, prior = [], {}
    def add(eid, p):
        if eid and eid not in prior:
            pool.append(eid); prior[eid] = p
        elif eid:
            prior[eid] = max(prior[eid], p)
    for i, h in enumerate(res.get("hits") or []):
        add(h.get("event_id"), 0.6 / (1 + i * 0.3))
    for i, f in enumerate(((res.get("facts") or {}).get("items")) or []):
        add(f.get("event_id"), 0.3 / (1 + i * 0.2))
    for cl in ((res.get("lens") or {}).get("clusters") or []):
        add((cl.get("center") or {}).get("event_id"), 0.4)
    for i, e in enumerate(_extra_candidates(uid, q, dates)):
        add(e, 0.1 / (1 + i * 0.1))
    rows = _rows(uid, pool)
    mq = meta_query(q)
    crit = _crit_ids(uid)
    scored = []
    for eid in pool:
        r = rows.get(eid)
        if not r:
            continue
        r["crit"] = eid in crit
        scored.append((score(r, tq, dates, prior.get(eid, 0), now, mq), r))
    scored.sort(key=lambda x: -x[0])
    # dedupe by cleaned prefix
    seen, items = set(), []
    for sc, r in scored:
        txt = clean(r["raw"])
        sig = re.sub(r"\W+", "", txt.lower())[:120]
        if not txt or sig in seen:
            continue
        seen.add(sig)
        items.append((sc, r, txt))
    budget = int(cfg.get("polish_tokens", TARGET_TOKENS) or TARGET_TOKENS)
    hits, facts, used = [], [], 0
    if items:
        floor = max(0.15, items[0][0] * 0.2)
        items = [x for x in items if x[0] >= floor]
    for i, (sc, r, txt) in enumerate(items):
        lim = 900 if i == 0 else (450 if i < 4 else 220)
        entry = {"event_id": r["event_id"], "date": str(r.get("time_str") or "")[:16], "kind": _kind(r["event_id"]),
                 "score": round(sc, 3), "text": clip(txt, lim)}
        if r.get("crit"):
            entry["important"] = True
        cost = _tok(entry["text"]) + 25
        if used + cost > budget * 0.62:
            break
        used += cost
        (hits if i < 4 else facts).append(entry)
        if len(hits) + len(facts) >= 14:
            break
    res["hits"] = hits
    fx = res.get("facts") if isinstance(res.get("facts"), dict) else {}
    res["facts"] = {"note": "More related records, best first (dates shown; newer wins if facts conflict).", "items": facts}
    if fx.get("subqueries"):
        res["facts"]["subqueries"] = fx["subqueries"]
    # lens: keep one compact cluster around the best hit
    lens = res.get("lens") if isinstance(res.get("lens"), dict) else {}
    cls = []
    for cl in (lens.get("clusters") or [])[:1]:
        cls.append({"period": cl.get("period"), "member_ids": (cl.get("member_ids") or [])[:5],
                    "l1": clip(clean(cl.get("l1")), 300), "l2": clip(clean(cl.get("l2")), 200)})
    res["lens"] = {"mode": lens.get("mode"), "clusters": cls, "total_hits": lens.get("total_hits"),
                   "note": "Open any id with GET /api/v7/event/{id}; POST /api/v7/memory/lens with focus_event_id for neighbours."}
    sums = l1_summaries(uid, q, dates)
    if sums:
        res["summaries"] = sums
    qlow = q.lower()
    if any(w in qlow for w in PLAN_WORDS) or dates:
        try:
            from app import board as _board
            bt = _board.render(uid, 450)
            if bt:
                res["board"] = bt
        except Exception as e:
            print(f"[polish] board skipped: {e}", flush=True)
    if dates:
        cal = calendar_items(uid, dates)
        if cal:
            res["calendar"] = cal
        res["query_dates"] = [d.isoformat() for d in dates]
    if not hits:
        res["agent_hint"] = "Nothing relevant was recalled for this question. Say so honestly; do not invent."
    # global cap
    for k in ("summaries", "facts"):
        while _tok(json.dumps(res, ensure_ascii=False)) > budget * 1.15 and res.get(k):
            if k == "facts" and res["facts"]["items"]:
                res["facts"]["items"].pop()
            elif k == "summaries":
                res["summaries"].pop()
            else:
                break
    b = res.get("budget") if isinstance(res.get("budget"), dict) else {}
    b["polished"] = True
    b["total_tokens"] = _tok(json.dumps(res, ensure_ascii=False))
    res["budget"] = b
    return res
