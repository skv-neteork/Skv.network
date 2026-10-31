"""SKV user profile layer: lasting rules about HOW to work with this user (docs/user_profile_design.md).
One core for MCP, REST and Guards: schema, op validation, apply, duties, server fallback, relevance, step_zero block, dig.
Data lives in the account db (profile_rows (named so to avoid the legacy memory_v2_windows user_profile table), profile_log, profile_duties, profile_state); the per-account
feature flag lives in shared_master.db (profile_flags). Rows are never deleted: correct = supersede, delete = retract."""
import hashlib, json, os, re, sqlite3, threading, time, uuid

SHARED_DB = "/data/skv/metadata_store/shared_master.db"
KINDS = ("prohibition", "rule", "decision", "preference", "identity")
OPS = ("add", "supersede", "retract", "confirm", "dismiss")
AUTHORS = ("agent", "server_fallback", "import", "user")
DEFAULTS = {"profile_turn_rows": 5, "profile_turn_bytes": 800, "profile_sz_bytes": 1500, "profile_sz_rows": 12,
            "profile_fallback_grace_turns": 5, "candidate_resolve_turns": 2, "profile_l2_warn_reviews": 3,
            "profile_max_ops": 10, "profile_text_max": 300, "profile_dup_jaccard": 0.85}
SELF_CHECK_ITEM = ("Answer does not violate the PROFILE rows shown (%s); if it must, say why or supersede the row. "
                   "Resolve open profile duties (profile_candidate / profile_conflict / profile_unconfirmed) with profile ops or dismiss.")


def cfg(k):
    try:
        from app import memory_v2 as _mv2
        v = _mv2.config().get(k)
        if v is not None:
            return type(DEFAULTS[k])(v)
    except Exception:
        pass
    return DEFAULTS[k]


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


# ─── flag ───
def _flags():
    c = sqlite3.connect(SHARED_DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS profile_flags (user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, updated_at TEXT)")
    return c


def enabled(uid):
    if not uid:
        return False
    try:
        c = _flags()
        r = c.execute("SELECT enabled FROM profile_flags WHERE user_id=?", (uid,)).fetchone()
        c.close()
        return bool(r and r[0])
    except Exception:
        return False


def set_flag(uid, on):
    c = _flags()
    c.execute("INSERT OR REPLACE INTO profile_flags (user_id, enabled, updated_at) VALUES (?,?,?)", (uid, 1 if on else 0, _now()))
    c.commit(); c.close()
    return {"user_id": uid, "profile_enabled": bool(on)}


# ─── schema ───
def ensure(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS profile_rows (
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'global',
      status TEXT NOT NULL DEFAULT 'active', supersedes_id TEXT, superseded_by TEXT, source_event_ids TEXT NOT NULL,
      author TEXT NOT NULL, agent_name TEXT, confidence REAL NOT NULL DEFAULT 0.9, priority INTEGER NOT NULL DEFAULT 2,
      keywords TEXT, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS prof_rows_status ON profile_rows(status, scope);
    CREATE TABLE IF NOT EXISTS profile_log (seq INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT, op TEXT,
      before_json TEXT, after_json TEXT, turn_event_id TEXT, author TEXT, at TEXT);
    CREATE TABLE IF NOT EXISTS profile_duties (id TEXT PRIMARY KEY, kind TEXT, event_id TEXT, signal TEXT, ref_ids TEXT,
      opened_turn INTEGER, status TEXT, resolution TEXT, resolved_at TEXT);
    CREATE TABLE IF NOT EXISTS profile_state (k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS profile_vec (id TEXT PRIMARY KEY, h TEXT, v BLOB);
    """)


# ─── per-account time zone (display only; storage stays UTC) ───
def get_tz(uid):
    try:
        c = _db(uid)
        try:
            return _st(c, "tz", "UTC") or "UTC"
        finally:
            c.close()
    except Exception:
        return "UTC"


def set_tz(uid, tz):
    from zoneinfo import ZoneInfo
    ZoneInfo(tz)   # raises on an unknown zone
    c = _db(uid)
    try:
        _st_set(c, "tz", tz); c.commit()
    finally:
        c.close()
    return tz


# ─── multilingual semantic match for profile rows (MiniLM mml12; RU message vs EN rule) ───
SEM_TAG, SEM_MIN, SEM_BAND = "mml12", 0.33, 0.10   # cos floor; keep only rows near the best match


def _row_vecs(c, rows):
    import numpy as np
    from app import semantic as _sem
    have = {i: (h, v) for i, h, v in c.execute("SELECT id, h, v FROM profile_vec")}
    out, todo = {}, []
    for r in rows:
        h = hashlib.sha1((r["text"] + "|" + (r["keywords"] or "")).encode()).hexdigest()[:12]
        if r["id"] in have and have[r["id"]][0] == h:
            out[r["id"]] = np.frombuffer(have[r["id"]][1], dtype=np.float32)
        else:
            todo.append((r, h))
    if todo:
        vecs = _sem.embed([r["text"] + " " + (r["keywords"] or "") for r, _ in todo], tag=SEM_TAG)
        for (r, h), v in zip(todo, vecs):
            c.execute("INSERT OR REPLACE INTO profile_vec (id, h, v) VALUES (?,?,?)", (r["id"], h, v.astype("float32").tobytes()))
            out[r["id"]] = v
    return out


def _sem_scores(c, rows, q):
    if not (q or "").strip() or not rows:
        return {}
    try:
        from app import semantic as _sem
        rv = _row_vecs(c, rows)
        qv = _sem.embed([q[:1000]], tag=SEM_TAG)[0]
        return {i: float(v @ qv) for i, v in rv.items()}
    except Exception as e:
        print(f"[profile] semantic skipped: {e}", flush=True)
        return {}


def _db(uid):
    from app import shelves as _sh
    c = _sh.connect(uid)
    ensure(c)
    return c


def _st(c, k, d=None):
    r = c.execute("SELECT v FROM profile_state WHERE k=?", (k,)).fetchone()
    return r[0] if r else d


def _st_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO profile_state (k, v) VALUES (?,?)", (k, str(v)))


def _row(c, pid):
    r = c.execute("SELECT * FROM profile_rows WHERE id=?", (pid,)).fetchone()
    if not r:
        return None
    return dict(zip([d[0] for d in c.execute("SELECT * FROM profile_rows LIMIT 0").description], r))


def _active(c):
    cur = c.execute("SELECT * FROM profile_rows WHERE status='active'")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def version(c):
    rows = c.execute("SELECT id, updated_at FROM profile_rows WHERE status='active' ORDER BY id").fetchall()
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:8]


def _head(c, pid):
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        r = c.execute("SELECT status, superseded_by FROM profile_rows WHERE id=?", (pid,)).fetchone()
        if not r or r[0] != "superseded" or not r[1]:
            return pid
        pid = r[1]
    return pid


# ─── text helpers ───
_STOPW = set("""the and for that this with from have will your you are not but all any can into when what which they them then than
just also only very more most such about after before again always never dont don't do does did use using user agent answer
это как что чтобы для при или его она они оно тут там так уже ещё еще всегда никогда надо нужно можно будет было есть если
когда потом сначала только тоже очень себя меня мне мой моя наш ваш""".split())


def _toks(s):
    out = set()
    for w in re.findall(r"[\w-]{3,}", (s or "").lower()):
        if w in _STOPW or w.isdigit():
            continue
        out.add(w[:6] if re.search(r"[а-яё]", w) else w[:8])
    return out


def _jacc(a, b):
    a, b = _toks(a), _toks(b)
    return len(a & b) / float(len(a | b)) if a and b else 0.0


_SECRET_RX = [
    re.compile(r"\[SECRET\]"),
    re.compile(r"(?i)(?:secret|token|api[ _-]?key|password|passcode|пароль|токен|ключ)\s*(?:is|=|:|—|-|это)\s*[\"«']?(?=[^\s\"«']*\d)[A-Za-z0-9][\w\-.@/+=]{5,}"),
    re.compile(r"\bsk_[A-Za-z0-9]{12,}"), re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"\bgithub_pat_\w{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"), re.compile(r"\b(?:xox[abpr]|sk-)[A-Za-z0-9-]{16,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"), re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{5,}"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), re.compile(r"(?<![\w-])\+\d[\d\s().-]{8,}\d(?!\w)"), re.compile(r"\b\d{3}[\s.-]\d{3}[\s.-]\d{2}[\s.-]?\d{2}\b"),
    re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b"),
]


def secret_hit(text):
    t = text or ""
    for rx in _SECRET_RX:
        m = rx.search(t)
        if m:
            return m.group(0)[:6] + "…"
    return ""


# signal lexicon (design 5.2). A trusted cube 'cube_profile_signals_lexicon' (one regex per line) overrides it.
_SIGNALS_DEFAULT = [r"\bвсегда\b", r"\bникогда\b", r"\bне надо\b", r"\bне делай", r"\bхочу,? чтобы\b", r"\bпредпочитаю\b",
                    r"\bзапомни\b", r"\bправило\b", r"\bвпредь\b", r"\bс этого момента\b", r"\bбольше не\b", r"\bлучше так\b",
                    r"\bдавай всегда\b", r"\bдаю добро\b.{0,80}\bно\b", r"\balways\b", r"\bnever\b", r"\bdon'?t\b", r"\bprefer\b",
                    r"\bfrom now on\b", r"\bremember that\b", r"\brule\b"]
_SIG_CACHE = {"t": 0, "rx": None}


def _signals():
    if _SIG_CACHE["rx"] is not None and time.time() - _SIG_CACHE["t"] < 300:
        return _SIG_CACHE["rx"]
    pats = _SIGNALS_DEFAULT
    try:
        sc = sqlite3.connect(SHARED_DB, timeout=10)
        r = sc.execute("SELECT rules_markdown FROM cubes_new WHERE cube_id='cube_profile_signals_lexicon' AND coalesce(status,'') NOT IN ('deprecated','archived','quarantine')").fetchone()
        sc.close()
        if r and r[0]:
            lines = [l.strip() for l in r[0].splitlines() if l.strip() and not l.strip().startswith("#")]
            if lines:
                pats = lines
    except Exception:
        pass
    rx = []
    for p in pats:
        try:
            rx.append(re.compile(p, re.I))
        except re.error:
            pass
    _SIG_CACHE.update(t=time.time(), rx=rx)
    return rx


_DURABLE = re.compile(r"\b(всегда|никогда|впредь|с этого момента|отныне|каждый раз|по умолчанию|запомни|правило|давай всегда|always|never|from now on|every time|by default|remember that|rule)\b", re.I)


def _candidate_ok(c, sig, msg):
    """Plan #4: a profile candidate needs durable wording, or the same weak signal twice (two observations).
    'make this shorter' is turn-local. Switch off with profile_candidate_strict=false in turn_diet.json."""
    if not diet_cfg("profile_candidate_strict", True) or _DURABLE.search(msg or ""):
        return True
    toks = sorted(_toks(sig))[:12]
    try:
        seen = json.loads(_st(c, "weak_sigs", "[]") or "[]")
    except Exception:
        seen = []
    hit = any(len(set(toks) & set(s)) >= 2 for s in seen)
    _st_set(c, "weak_sigs", json.dumps((seen + [toks])[-20:]))
    return hit


def detect_signal(msg):
    m0 = msg or ""
    for rx in _signals():
        m = rx.search(m0)
        if m:
            return m0[max(0, m.start() - 10): m.end() + 40].strip()
    return ""


# ─── validation ───
def _ev_norm(c, uid, ev, cur_eid):
    e = str(ev or "").strip().replace("[", "").replace("]", "")
    if e.startswith("ev:"):
        e = e[3:]
    if e in ("", "this", "current", "this_turn") or e == "__current__":
        return cur_eid or "__current__", None
    if "::" in e and not e.startswith(uid + "::"):
        return None, "ev %s belongs to another account" % e
    full = e if "::" in e else uid + "::" + e
    if cur_eid and full == cur_eid:
        return full, None
    for t in ("event_metadata", "event_archive"):
        try:
            if c.execute("SELECT 1 FROM %s WHERE event_id=?" % t, (full,)).fetchone():
                return full, None
        except sqlite3.OperationalError:
            pass
    return None, "ev %s does not exist in your memory" % e


def _scope_ok(s):
    return s == "global" or bool(re.match(r"^(project|topic):[\w .\-/]{1,60}$", s or ""))


def validate(c, uid, ops, cur_eid=None, author="agent"):
    """-> (errors, normalized ops). No writes."""
    errs, out = [], []
    if ops is None:
        return [], []
    if isinstance(ops, (str, bytes)):
        try:
            ops = json.loads(ops or "[]")
        except Exception:
            return ["profile must be a JSON list of ops"], []
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list):
        return ["profile must be a list of ops"], []
    if len(ops) > cfg("profile_max_ops"):
        return ["too many profile ops in one turn (%d > %d)" % (len(ops), cfg("profile_max_ops"))], []
    active = _active(c)
    for i, o in enumerate(ops):
        p = "profile[%d]" % i
        if not isinstance(o, dict):
            errs.append(p + ": op must be an object"); continue
        op = str(o.get("op") or "").strip().lower()
        if op not in OPS:
            errs.append(p + ": op must be one of " + "|".join(OPS)); continue
        n = {"op": op, "reason": str(o.get("reason") or "").strip()[:300]}
        if op == "dismiss":
            did = str(o.get("duty_id") or "").strip()
            r = c.execute("SELECT status FROM profile_duties WHERE id=?", (did,)).fetchone()
            if not r:
                errs.append(p + ": unknown duty_id %s" % did); continue
            if r[0] != "open":
                errs.append(p + ": duty %s is already %s" % (did, r[0])); continue
            if len(n["reason"]) < 10:
                errs.append(p + ": dismiss needs reason (>=10 chars)"); continue
            n["duty_id"] = did; out.append(n); continue
        evs = o.get("ev", o.get("source_event_ids"))
        evs = [x for x in re.split(r"[,\s]+", evs) if x] if isinstance(evs, str) else list(evs or [])
        if evs == ["unlinked"]:
            ur = str(o.get("unlinked_reason") or "").strip()
            if author != "import" and len(ur) < 10:
                errs.append(p + ": ev 'unlinked' needs unlinked_reason (>=10 chars)"); continue
            n["ev"], n["unlinked_reason"] = [], ur
        else:
            if not evs:
                evs = ["__current__"]
            good = []
            for e in evs[:20]:
                f, er = _ev_norm(c, uid, e, cur_eid)
                if er:
                    errs.append(p + ": " + er)
                else:
                    good.append(f)
            if len(good) != len(evs[:20]):
                continue
            n["ev"] = list(dict.fromkeys(good))
        if op in ("add", "supersede"):
            text = re.sub(r"\s+", " ", str(o.get("text") or "")).strip()
            if not text or len(text) > cfg("profile_text_max"):
                errs.append(p + ": text must be 1..%d chars (one rule per row)" % cfg("profile_text_max")); continue
            s = secret_hit(text)
            if s:
                errs.append(p + ": text looks like a secret or contact (%s): secrets and contacts go to the Vault; reference vault:<name> instead" % s); continue
            scope = str(o.get("scope") or "global").strip()
            if scope.startswith("agent:"):
                errs.append(p + ": scope agent:<name> is not supported (one profile per account)"); continue
            if not _scope_ok(scope):
                errs.append(p + ": scope must be global | project:<name> | topic:<tag>"); continue
            n.update(text=text, scope=scope, keywords=str(o.get("keywords") or "")[:200])
            try:
                pr = int(o.get("priority") or 0)
            except Exception:
                pr = 0
        if op == "add":
            kind = str(o.get("kind") or "").strip().lower()
            if kind not in KINDS:
                errs.append(p + ": kind must be one of " + "|".join(KINDS)); continue
            n["kind"] = kind
            n["priority"] = pr if pr in (1, 2, 3) else (1 if kind == "prohibition" else 2)
            dup = next((r for r in active if r["scope"] == n["scope"] and _jacc(r["text"], text) >= cfg("profile_dup_jaccard")), None)
            dup = dup or next((x for x in out if x.get("op") == "add" and _jacc(x["text"], text) >= cfg("profile_dup_jaccard")), None)
            if dup:
                errs.append(p + ": near-duplicate of %s: use confirm or supersede (dup_of=%s)" % ((dup.get("id") or "an op in this turn"), dup.get("id") or "")); continue
        if op in ("supersede", "retract", "confirm"):
            pid = str(o.get("id") or "").strip().replace("prof:", "")
            r = _row(c, pid)
            if not r:
                errs.append(p + ": unknown profile id %s" % pid); continue
            if r["status"] != "active":
                h = _head(c, pid)
                errs.append(p + ": %s is %s; current head is %s" % (pid, r["status"], h if h != pid else "none (retracted)")); continue
            if op in ("supersede", "retract") and len(n["reason"]) < 5:
                errs.append(p + ": %s needs reason" % op); continue
            n["id"] = pid
            if op == "supersede":
                kind = str(o.get("kind") or r["kind"]).strip().lower()
                if kind not in KINDS:
                    errs.append(p + ": kind must be one of " + "|".join(KINDS)); continue
                n["kind"] = kind
                n["priority"] = pr if pr in (1, 2, 3) else r["priority"]
        out.append(n)
    return errs, out


def check_review(c, review, has_l2):
    """profile_review rules tied to L2 (design 5.1). -> (errors, warnings, review_ops). Warn-only for the first N L2 per account."""
    if not has_l2 and not review:
        return [], [], None
    if isinstance(review, str):
        try:
            review = json.loads(review) if review.strip().startswith("{") else {"no_changes": True, "reason": review}
        except Exception:
            return ["profile_review must be JSON {ops:[...]} or {no_changes:true, reason}"], [], None
    probs, rops = [], None
    if not has_l2:
        return [], ["profile_review sent without l2_summary: its ops are applied, no_changes is ignored"], (review or {}).get("ops")
    if not review:
        probs.append("L2 rejected: profile_review required (send profile_review={ops:[...]} or {no_changes:true, reason:'<why, >=20 chars>'})")
    elif review.get("no_changes"):
        if len(str(review.get("reason") or "").strip()) < 20:
            probs.append("profile_review.no_changes needs reason >= 20 chars")
        op_open = c.execute("SELECT id FROM profile_duties WHERE status='open' AND kind='profile_candidate'").fetchall()
        if op_open:
            probs.append("profile_review.no_changes rejected: open profile candidates %s: resolve (add/supersede) or dismiss them" % ", ".join(r[0] for r in op_open))
    else:
        rops = review.get("ops")
        if not isinstance(rops, list):
            probs.append("profile_review.ops must be a list (or send no_changes:true + reason)")
    warned = int(_st(c, "l2_warned", 0) or 0)
    if probs and warned < cfg("profile_l2_warn_reviews"):
        return [], ["WARN-ONLY (%d of %d L2 left before hard reject): would have rejected: %s" % (cfg("profile_l2_warn_reviews") - warned, cfg("profile_l2_warn_reviews"), p) for p in probs], rops
    return probs, [], rops


def _due_mark(c, ops):
    """[PROFILE ✗] when an open candidate is older than candidate_resolve_turns and this turn's ops do not resolve it."""
    cur = int(_st(c, "turn_n", 0) or 0) + 1
    resolved = {o.get("duty_id") for o in ops if o.get("op") == "dismiss"}
    evs = {e for o in ops for e in (o.get("ev") or [])}
    for did, ev, opened in c.execute("SELECT id, event_id, opened_turn FROM profile_duties WHERE status='open' AND kind='profile_candidate'").fetchall():
        if did in resolved or ev in evs:
            continue
        if cur - int(opened or 0) > cfg("candidate_resolve_turns"):
            return "[PROFILE ✗]"
    return ""


def precheck(uid, ops=None, review=None, has_l2=False):
    """Called by the wrappers BEFORE the seal is reserved and by /remember before anything is stored."""
    if not enabled(uid):
        return {"ok": True, "enabled": False, "errors": [], "warnings": (["profile layer is off for this account: profile fields ignored"] if (ops or review) else []), "seal_mark": ""}
    c = _db(uid)
    try:
        errs, nops = validate(c, uid, ops, None)
        rerrs, warns, rops = check_review(c, review, has_l2)
        e2, nrops = validate(c, uid, rops, None) if rops else ([], [])
        errs += rerrs + ["profile_review." + x for x in e2]
        return {"ok": not errs, "enabled": True, "errors": errs, "warnings": warns, "seal_mark": "" if errs else _due_mark(c, nops + nrops)}
    finally:
        c.close()


# ─── apply ───
def _log(c, pid, op, before, after, eid, author):
    c.execute("INSERT INTO profile_log (profile_id, op, before_json, after_json, turn_event_id, author, at) VALUES (?,?,?,?,?,?,?)",
              (pid, op, json.dumps(before, ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False) if after else None, eid, author, _now()))


def _links(c, pid, evs, method):
    from app import source_links as _sl
    _sl.ensure(c)
    _sl._put(c, "prof:" + pid, "profile", evs, method, force=True)


def _new_row(c, n, eid, author, agent_name, conf, supersedes=None):
    pid = "p_" + uuid.uuid4().hex[:8]
    now = _now()
    evs = [eid if e == "__current__" else e for e in n.get("ev") or []]
    c.execute("INSERT INTO profile_rows (id, kind, text, scope, status, supersedes_id, source_event_ids, author, agent_name, confidence, priority, keywords, reason, created_at, updated_at) "
              "VALUES (?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?)",
              (pid, n["kind"], n["text"], n["scope"], supersedes, json.dumps(evs or ["unlinked"]), author, agent_name, conf, n["priority"],
               n.get("keywords") or "", n.get("reason") or n.get("unlinked_reason") or "", now, now))
    _links(c, pid, evs, author if author != "agent" else "agent")
    return pid, evs


def _apply_ops(c, ops, eid, author, agent_name):
    applied = []
    conf = 0.9 if author in ("agent", "user") else (0.8 if author == "import" else 0.55)
    for n in ops:
        op = n["op"]
        if op == "dismiss":
            c.execute("UPDATE profile_duties SET status='resolved', resolution=?, resolved_at=? WHERE id=?", ("dismissed: " + n["reason"], _now(), n["duty_id"]))
            applied.append({"op": op, "duty_id": n["duty_id"]}); continue
        if op == "add":
            pid, evs = _new_row(c, n, eid, author, agent_name, conf)
            _log(c, pid, "add", None, _row(c, pid), eid, author)
            applied.append({"op": op, "id": "prof:" + pid})
        elif op == "supersede":
            old = _row(c, n["id"])
            pid, evs = _new_row(c, n, eid, author, agent_name, conf, supersedes=n["id"])
            c.execute("UPDATE profile_rows SET status='superseded', superseded_by=?, reason=?, updated_at=? WHERE id=?", (pid, n["reason"], _now(), n["id"]))
            _log(c, n["id"], "supersede", old, _row(c, pid), eid, author)
            applied.append({"op": op, "id": "prof:" + pid, "supersedes": "prof:" + n["id"]})
        elif op == "retract":
            old = _row(c, n["id"])
            c.execute("UPDATE profile_rows SET status='retracted', reason=?, updated_at=? WHERE id=?", (n["reason"], _now(), n["id"]))
            _log(c, n["id"], "retract", old, _row(c, n["id"]), eid, author)
            applied.append({"op": op, "id": "prof:" + n["id"]})
        elif op == "confirm":
            old = _row(c, n["id"])
            evs = list(dict.fromkeys(json.loads(old["source_event_ids"] or "[]") + [eid if e == "__current__" else e for e in n.get("ev") or []]))
            evs = [e for e in evs if e and e != "unlinked"]
            c.execute("UPDATE profile_rows SET author=CASE WHEN author='server_fallback' THEN 'agent' ELSE author END, confidence=max(confidence, 0.9), "
                      "source_event_ids=?, updated_at=? WHERE id=?", (json.dumps(evs or ["unlinked"]), _now(), n["id"]))
            _links(c, n["id"], evs, "agent")
            _log(c, n["id"], "confirm", old, _row(c, n["id"]), eid, author)
            applied.append({"op": op, "id": "prof:" + n["id"]})
        if op in ("add", "supersede"):
            for e in n.get("ev") or []:
                ee = eid if e == "__current__" else e
                c.execute("UPDATE profile_duties SET status='resolved', resolution=?, resolved_at=? WHERE status='open' AND kind='profile_candidate' AND event_id=?",
                          ("%s %s" % (op, applied[-1]["id"]), _now(), ee))
    return applied


_NEG = re.compile(r"(?i)\b(никогда|не надо|не делай|не|never|don'?t|do not|no)\b")
_POS = re.compile(r"(?i)\b(всегда|always)\b")


def _polarity(t):
    return -1 if _NEG.search(t or "") else (1 if _POS.search(t or "") else 0)


def _conflicts(c, new_ids):
    """Server negation heuristic: same scope, opposite polarity, strong word overlap -> profile_conflict duty."""
    act = _active(c)
    out = []
    for nid in new_ids:
        a = next((r for r in act if r["id"] == nid), None)
        if not a:
            continue
        for b in act:
            if b["id"] == nid or b["scope"] != a["scope"]:
                continue
            pa, pb = _polarity(a["text"]), _polarity(b["text"])
            ta = _toks(_NEG.sub(" ", _POS.sub(" ", a["text"])))
            tb = _toks(_NEG.sub(" ", _POS.sub(" ", b["text"])))
            ov = len(ta & tb) / float(min(len(ta), len(tb)) or 1)
            if pa and pb and pa != pb and ov >= 0.6:
                key = json.dumps(sorted([a["id"], b["id"]]))
                if not c.execute("SELECT 1 FROM profile_duties WHERE kind='profile_conflict' AND status='open' AND ref_ids=?", (key,)).fetchone():
                    out.append(key)
    return out


def _open_duty(c, kind, eid, signal, ref_ids=None, turn_n=0):
    did = "pd_" + uuid.uuid4().hex[:8]
    c.execute("INSERT INTO profile_duties (id, kind, event_id, signal, ref_ids, opened_turn, status) VALUES (?,?,?,?,?,?,'open')",
              (did, kind, eid, signal[:200], ref_ids, turn_n))
    return did


def _refresh_duties(c):
    """Close conflict/unconfirmed duties whose rows were superseded, retracted, confirmed or narrowed."""
    for did, kind, ref in c.execute("SELECT id, kind, ref_ids FROM profile_duties WHERE status='open' AND kind IN ('profile_conflict','profile_unconfirmed')").fetchall():
        ids = json.loads(ref or "[]")
        rows = [_row(c, i) for i in ids]
        done = False
        if kind == "profile_conflict":
            done = any(not r or r["status"] != "active" for r in rows) or len({r["scope"] for r in rows if r}) > 1
        else:
            done = all(not r or r["status"] != "active" or r["author"] != "server_fallback" for r in rows)
        if done:
            c.execute("UPDATE profile_duties SET status='resolved', resolution='rows changed', resolved_at=? WHERE id=?", (_now(), did))


def apply(uid, eid, user_msg="", answer="", ops=None, review=None, has_l2=False, author="agent", agent_name=""):
    """After the turn event is stored: apply ops (one transaction), L2 counters, candidate/conflict duties, aging, fallback."""
    try:
        if user_msg and author in ("agent", "user"):
            from app import cube_consent as _cc
            _cc.observe(uid, user_msg, "turn", eid)
    except Exception as _e:
        print("[cube_consent] observe failed:", _e, flush=True)
    if not enabled(uid):
        return {}
    c = _db(uid)
    res = {}
    try:
        c.execute("BEGIN IMMEDIATE")
        errs, nops = validate(c, uid, ops, eid, author)
        rerrs, warns, rops = check_review(c, review, has_l2)
        e2, nrops = validate(c, uid, rops, eid, author) if rops else ([], [])
        if errs or rerrs or e2:
            c.rollback()
            return {"profile_errors": errs + rerrs + e2, "profile_applied": []}
        mark = _due_mark(c, nops + nrops)
        tn = int(_st(c, "turn_n", 0) or 0) + (1 if eid else 0)
        _st_set(c, "turn_n", tn)
        applied = _apply_ops(c, nops + nrops, eid, author, agent_name)
        if has_l2:
            if review:
                _st_set(c, "l2_skip_streak", 0)
            else:
                _st_set(c, "l2_skip_streak", int(_st(c, "l2_skip_streak", 0) or 0) + 1)
            if warns:
                _st_set(c, "l2_warned", int(_st(c, "l2_warned", 0) or 0) + 1)
            elif review:
                _st_set(c, "l2_warned", max(int(_st(c, "l2_warned", 0) or 0), 0))
        new_ids = [a["id"][5:] for a in applied if a.get("op") in ("add", "supersede")]
        for key in _conflicts(c, new_ids):
            _open_duty(c, "profile_conflict", eid, "rows contradict: " + key, key, tn)
        sig = detect_signal(user_msg) if (eid and user_msg and author == "agent") else ""
        handled = any(eid in (n.get("ev") or []) or "__current__" in (n.get("ev") or []) for n in nops + nrops if n["op"] in ("add", "supersede", "confirm", "retract"))
        if sig and not handled and _candidate_ok(c, sig, user_msg):
            _open_duty(c, "profile_candidate", eid, sig, None, tn)
        _refresh_duties(c)
        expired = []
        if eid:
            for did, dev, opened, signal in c.execute("SELECT id, event_id, opened_turn, signal FROM profile_duties WHERE status='open' AND kind='profile_candidate'").fetchall():
                if tn - int(opened or 0) >= cfg("profile_fallback_grace_turns"):
                    c.execute("UPDATE profile_duties SET status='fallback', resolution=?, resolved_at=? WHERE id=?", ("agent ignored it %d turns" % (tn - int(opened or 0)), _now(), did))
                    expired.append((did, dev, signal))
        if has_l2 and int(_st(c, "l2_skip_streak", 0) or 0) >= 2:
            _st_set(c, "l2_skip_streak", 0)
            expired.append(("l2", None, "profile_review skipped for 2 L2 windows"))
        c.commit()
        res = {"profile_applied": applied, "profile_version": version(c)}
        if warns:
            res["profile_warnings"] = warns
        if mark:
            res["profile_mark"] = mark
        if expired:
            threading.Thread(target=_fallback_run, args=(uid, expired), daemon=True).start()
            res["profile_fallback_started"] = [d for d, _, _ in expired]
        res["profile_duties"] = duties(c, tn)
    except Exception:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        c.close()
    return res


def duties(c, tn=None):
    tn = int(_st(c, "turn_n", 0) or 0) if tn is None else tn
    out = []
    for did, kind, ev, sig, ref, opened in c.execute("SELECT id, kind, event_id, signal, ref_ids, opened_turn FROM profile_duties WHERE status='open' ORDER BY opened_turn").fetchall():
        d = {"id": did, "kind": kind, "event_id": (ev or "").split("::")[-1] or None, "signal": sig}
        if ref:
            d["ids"] = ["prof:" + x for x in json.loads(ref)]
        age = tn - int(opened or 0)
        if kind == "profile_candidate":
            left = cfg("candidate_resolve_turns") - age
            d["do"] = ("lasting user rule? next turn: turn(..., profile=[{op:add|supersede, kind, text, ev:['%s']}]) or profile=[{op:dismiss, duty_id:'%s', reason}] (JSON array)" % (d["event_id"], did))
            if left <= 0:
                d["overdue"] = "OVERDUE: seal gets [PROFILE ✗] until resolved; server fallback after %d turns" % cfg("profile_fallback_grace_turns")
            elif left == 1:
                d["escalation"] = "last turn to resolve before [PROFILE ✗]"
        elif kind == "profile_conflict":
            d["do"] = "supersede one row or narrow the scopes"
        else:
            d["do"] = "server_fallback row: confirm (op:confirm) or retract it"
        out.append(d)
    return out[:6]


# ─── server fallback (last resort) ───
_FB_PROMPT = ("You extract LASTING rules the user explicitly stated about how an AI assistant must work with them. "
              "Only explicit user-stated lasting rules, preferences, prohibitions or decisions; never one-off requests, never facts about the world, "
              "never secrets, emails or phones. Quote the user (keep their language). Return JSON {\"rows\":[{\"kind\":\"prohibition|rule|decision|preference|identity\",\"text\":\"<=200 chars\"}]} "
              "with at most 2 rows, or {\"rows\":[]} if nothing qualifies.")


def _event_user_text(c, eid):
    r = c.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id=?", (eid,)).fetchone()
    if not r:
        return ""
    q = (r[0] or "").split("\nA:", 1)[0]
    return re.sub(r"^Q:\s*(\[[^\]]*\]\s*)*", "", q).strip()


def _fallback_rows(text, signal):
    rows = []
    try:
        from app import memory_v2_llm as _llm
        out, _u = _llm._llm([{"role": "system", "content": _FB_PROMPT}, {"role": "user", "content": text[:3000]}], 300, json_mode=True)
        d = _llm._json_out(out) if hasattr(_llm, "_json_out") else json.loads(out)
        rows = [r for r in (d or {}).get("rows", []) if isinstance(r, dict)][:2]
    except Exception as e:
        print("[profile] fallback llm unavailable, extractive quote: %s" % type(e).__name__, flush=True)
        sent = next((s.strip() for s in re.split(r"(?<=[.!?\n])\s+", text) if signal and signal.split()[0].lower() in s.lower()), "") or signal
        if sent:
            low = sent.lower()
            kind = "prohibition" if _NEG.search(low) else ("preference" if re.search(r"предпочит|prefer", low) else "rule")
            rows = [{"kind": kind, "text": "User said: «%s»" % sent[:220]}]
    return rows


def _fallback_run(uid, expired):
    try:
        c = _db(uid)
        tn = int(_st(c, "turn_n", 0) or 0)
        made = []
        for did, ev, signal in expired:
            if not ev:
                continue
            text = _event_user_text(c, ev)
            for r in _fallback_rows(text, signal):
                kind = str(r.get("kind") or "rule").lower()
                t = re.sub(r"\s+", " ", str(r.get("text") or "")).strip()[:cfg("profile_text_max")]
                if kind not in KINDS or not t or secret_hit(t):
                    continue
                if any(_jacc(a["text"], t) >= cfg("profile_dup_jaccard") for a in _active(c)):
                    continue
                n = {"kind": kind, "text": t, "scope": "global", "priority": 1 if kind == "prohibition" else 2, "ev": [ev], "reason": "server_fallback for " + did}
                pid, _ = _new_row(c, n, ev, "server_fallback", "server", 0.55)
                _log(c, pid, "fallback_add", None, _row(c, pid), ev, "server_fallback")
                _open_duty(c, "profile_unconfirmed", ev, "server_fallback wrote prof:%s: confirm or retract" % pid, json.dumps([pid]), tn)
                made.append(pid)
        c.commit(); c.close()
        with open("/var/log/skv_selfcheck.log", "a") as fh:
            fh.write(json.dumps({"t": int(time.time()), "user": uid, "profile_fallback": [d for d, _, _ in expired], "rows": made}) + "\n")
    except Exception as e:
        print("[profile] fallback failed: %s" % e, flush=True)


# ─── reads ───
_KORD = {k: i for i, k in enumerate(KINDS)}


def _line(r):
    unc = " (unconfirmed)" if r["author"] == "server_fallback" else ""
    sc = "" if r["scope"] == "global" else " (%s)" % r["scope"]
    return "[prof:%s] %s: %s%s%s" % (r["id"], r["kind"].upper(), r["text"], sc, unc)


def _scope_hit(r, words):
    if r["scope"] == "global":
        return True
    name = r["scope"].split(":", 1)[1].lower()
    return any(t in words for t in _toks(name))


def relevant_rows(c, q, answer=""):
    words = _toks((q or "") + " " + (answer or ""))
    duty_ids = set()
    for (ref,) in c.execute("SELECT ref_ids FROM profile_duties WHERE status='open' AND ref_ids IS NOT NULL").fetchall():
        duty_ids |= set(json.loads(ref or "[]"))
    scored = []
    act = _active(c)
    sem = _sem_scores(c, act, ((q or "") + " " + (answer or "")[:300]).strip())
    best = max(sem.values()) if sem else 0.0
    sem = {i: v for i, v in sem.items() if v >= SEM_MIN and v >= best - SEM_BAND}
    for r in act:
        cs = sem.get(r["id"], 0.0)
        if not _scope_hit(r, words) and not cs:
            continue
        ov = len(_toks(r["text"] + " " + (r["keywords"] or "")) & words)
        s = 0.0
        if cs >= SEM_MIN:
            s += 20 * (cs - SEM_MIN) + 2   # meaning match, language-independent
        if r["kind"] == "prohibition" and (ov or r["priority"] == 1):
            s += 10
        s += 3 * ov
        if r["id"] in duty_ids:
            s += 5
        if r["scope"] != "global" and ov:
            s += 2   # narrower scope beats global
        if s <= 0 and r["priority"] != 1:
            continue
        s += (4 - r["priority"]) * 0.5
        scored.append((s, r))
    scored.sort(key=lambda x: (-x[0], _KORD.get(x[1]["kind"], 9)))
    out, size = [], 0
    for s, r in scored:
        ln = _line(r)
        if len(out) >= cfg("profile_turn_rows") or size + len(ln.encode()) > cfg("profile_turn_bytes"):
            break
        out.append({"id": "prof:" + r["id"], "line": ln, "kind": r["kind"], "text": r["text"],
                    "_m": bool(sem.get(r["id"], 0.0) >= SEM_MIN or (_toks(r["text"] + " " + (r["keywords"] or "")) & words))}); size += len(ln.encode())
    return out


def _warnings(rows, answer):
    w = []
    a = _toks(answer)
    for r in rows:
        if r["kind"] != "prohibition" or not answer:
            continue
        m = _NEG.search(r["text"])
        tail = _toks(r["text"][m.end():] if m else r["text"])
        hit = tail & a
        if len(hit) >= 2 or (tail and len(hit) == len(tail)):
            w.append("%s may be violated (answer mentions: %s): check it, say why, or supersede" % (r["id"], ", ".join(sorted(hit))[:80]))
    return w[:3]


_DIET_CFG = {"m": None, "v": {}}


def diet_cfg(k, default):
    """Shared tuning file of the MCP turn diet (/data/skv/turn_diet.json); defaults when absent."""
    p = os.environ.get("SKV_TURN_DIET_CFG", "/data/skv/turn_diet.json")
    try:
        m = os.path.getmtime(p)
        if m != _DIET_CFG["m"]:
            with open(p) as fh:
                _DIET_CFG.update(m=m, v=json.load(fh))
    except Exception:
        pass
    return _DIET_CFG["v"].get(k, default)


def digest(c, chars=320):
    """~80-token capsule of the active profile: prohibitions and top-priority rows first, no ids."""
    act = sorted(_active(c), key=lambda r: (_KORD.get(r["kind"], 9), r["priority"], r["author"] == "server_fallback"))
    parts, n = [], 0
    for r in act:
        t = re.sub(r"\s+", " ", r["text"]).strip()
        t = t if len(t) <= 90 else t[:87].rstrip() + "..."
        if n + len(t) + 2 > chars:
            break
        parts.append(t); n += len(t) + 2
    if not parts:
        return ""
    more = len(act) - len(parts)
    return "; ".join(parts) + (" (+%d more)" % more if more > 0 else "")


def relevant(uid, q="", answer="", session="", compact=False, diet=False):
    """turn read path: <=5 rows / <=800 B. Compact: full set only when profile_version changed for the session; else only new rows."""
    if not enabled(uid):
        return {}
    c = _db(uid)
    try:
        v = version(c)
        rows = relevant_rows(c, q, answer)
        out = {"profile_version": v}
        if compact and session:
            k = "cs:" + session
            prev = json.loads(_st(c, k, "{}") or "{}")
            if prev.get("v") == v:
                seen = set(prev.get("ids") or [])
                new = [r for r in rows if r["id"] not in seen]
                out["profile_unchanged"] = True
                if new:
                    out["profile_new"] = [r["line"] for r in new]
                seen |= {r["id"] for r in rows}
            else:
                out["profile"] = [r["line"] for r in rows]
                seen = {r["id"] for r in rows}
            _st_set(c, k, json.dumps({"v": v, "ids": sorted(seen)[-60:]}))
        else:
            out["profile"] = [r["line"] for r in rows]
        ds = duties(c)
        if ds:
            out["profile_duties"] = ds
        w = _warnings(rows, answer)
        if w:
            out["profile_warning"] = w
        if rows:
            out["profile_check"] = SELF_CHECK_ITEM % ", ".join(r["id"] for r in rows)
        if diet:   # extra keys for the MCP compact path only; the default response is unchanged
            out["profile_strict"] = [r["line"] for r in rows if r.get("_m")]
            dg = digest(c, int(diet_cfg("profile_digest_chars", 320)))
            if dg:
                out["profile_digest"] = dg
        c.commit()
        return out
    finally:
        c.close()


def block(uid):
    """step_zero page 1: PROFILE v<hash> (N active), <=1.5 KB / <=12 rows, prohibitions first."""
    if not enabled(uid):
        return ""
    c = _db(uid)
    try:
        act = _active(c)
        act.sort(key=lambda r: (_KORD.get(r["kind"], 9), r["priority"], r["author"] == "server_fallback", r["updated_at"]))
        head = "=== PROFILE v%s (%d active): how to work with this user; cite rows as prof:<id> ===" % (version(c), len(act))
        lines, size = [], len(head.encode())
        for r in act:
            ln = _line(r)
            if len(lines) >= cfg("profile_sz_rows") or size + len(ln.encode()) + 1 > cfg("profile_sz_bytes") - 80:
                break
            lines.append(ln); size += len(ln.encode()) + 1
        tail = []
        if len(lines) < len(act):
            tail.append("+%d more: memory_dig(focus_id=prof:list)" % (len(act) - len(lines)))
        nd = c.execute("SELECT count(*) FROM profile_duties WHERE status='open'").fetchone()[0]
        if nd:
            tail.append("%d open profile duties: resolve them in your next turn" % nd)
        if not act:
            lines = ["(empty: when the user states a lasting rule, add it with turn profile=[{op:add,...}])"]
        return "\n".join([head] + lines + tail)
    finally:
        c.close()


def dig(uid, q):
    c = _db(uid)
    try:
        q = (q or "").strip()
        if q == "prof:list":
            rows = sorted(_active(c), key=lambda r: (_KORD.get(r["kind"], 9), r["priority"]))
            return {"id": q, "kind": "profile", "version": version(c), "n": len(rows), "rows": [_line(r) for r in rows]}
        if q == "prof:history":
            log = c.execute("SELECT seq, profile_id, op, turn_event_id, author, at FROM profile_log ORDER BY seq DESC LIMIT 100").fetchall()
            return {"id": q, "kind": "profile_history", "log": [{"seq": a, "id": "prof:" + (b or ""), "op": o, "ev": (e or "").split("::")[-1], "author": au, "at": t} for a, b, o, e, au, t in log]}
        pid = q[5:] if q.startswith("prof:") else q
        r = _row(c, pid)
        if not r:
            return {"error": "unknown id", "id": q}
        chain, p = [], r.get("supersedes_id")
        while p and len(chain) < 20:
            o = _row(c, p)
            if not o:
                break
            chain.append({"id": "prof:" + o["id"], "status": o["status"], "text": o["text"], "reason": o["reason"]}); p = o.get("supersedes_id")
        ids = [e for e in json.loads(r["source_event_ids"] or "[]") if e != "unlinked"]
        def ev(e):
            row = c.execute("SELECT time_str, substr(raw_dialogue,1,220) FROM event_metadata WHERE event_id=?", (e,)).fetchone()
            return {"event_id": e, "date": row[0] if row else None, "text": row[1] if row else None}
        log = c.execute("SELECT op, turn_event_id, author, at FROM profile_log WHERE profile_id=? ORDER BY seq", (pid,)).fetchall()
        return {"id": "prof:" + pid, "kind": "profile", "status": r["status"] if ids or r["status"] != "active" else r["status"],
                "link_status": "linked" if ids else "unlinked", "method": r["author"], "text": "%s: %s" % (r["kind"].upper(), r["text"]),
                "row": {k: r[k] for k in ("kind", "scope", "status", "author", "confidence", "priority", "superseded_by", "reason", "created_at", "updated_at")},
                "head": "prof:" + _head(c, pid), "history_chain": chain,
                "log": [{"op": o, "ev": (e or "").split("::")[-1], "author": a, "at": t} for o, e, a, t in log],
                "source_event_ids": ids, "n_sources": len(ids), "sources": [ev(e) for e in ids[:12]], "related_event_ids": []}
    finally:
        c.close()


def export(uid):
    c = _db(uid)
    try:
        cur = c.execute("SELECT * FROM profile_rows ORDER BY created_at")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        log = c.execute("SELECT seq, profile_id, op, turn_event_id, author, at FROM profile_log ORDER BY seq").fetchall()
        return {"user_id": uid, "version": version(c), "enabled": enabled(uid), "rows": rows,
                "log": [dict(zip(("seq", "profile_id", "op", "turn_event_id", "author", "at"), x)) for x in log]}
    finally:
        c.close()


def import_ops(uid, ops, dry_run=True):
    """Batch import (author=import): ev must be given or 'unlinked'. dry_run validates and reports only."""
    c = _db(uid)
    try:
        errs, n = validate(c, uid, ops, None, author="import")
        rep = {"dry_run": bool(dry_run), "n_ops": len(ops or []), "errors": errs,
               "linked": sum(1 for x in n if x.get("ev")), "unlinked": sum(1 for x in n if x.get("op") == "add" and not x.get("ev"))}
        if errs or dry_run:
            return rep
        if any("__current__" in (x.get("ev") or []) for x in n):
            rep["errors"] = ["import ops need explicit ev ids or 'unlinked' + unlinked_reason"]
            return rep
        c.execute("BEGIN IMMEDIATE")
        rep["applied"] = _apply_ops(c, n, None, "import", "import")
        c.commit()
        rep["profile_version"] = version(c)
        return rep
    finally:
        c.close()


_NOPUB = __import__("re").compile(r"(don'?t|do not|never|no|stop)\W+(\w+\W+){0,3}publish|не\s+публик|без\s+публикац", __import__("re").I)


def publish_opted_out(uid):
    """True when the user said 'don't publish' (an active profile prohibition/rule/decision). Checked before every shared cube."""
    try:
        c = _db(uid)
        try:
            from app.cube_consent import profile_nopub as _pn
            return any(_pn(r.get("text") or "") for r in _active(c) if r.get("kind") in ("prohibition", "rule", "decision", "preference"))
        finally:
            c.close()
    except Exception:
        return None   # unknown -> callers fail closed


def retract_nopub(uid, eid="", reason="user allowed publishing again; newest explicit statement wins"):
    """Opt-in after an opt-out: retract active 'don't publish' rows (kept in profile_log history)."""
    c = _db(uid); n = 0
    try:
        for r in _active(c):
            if r.get("kind") in ("prohibition", "rule", "decision", "preference") and __import__("app.cube_consent", fromlist=["x"]).profile_nopub(r.get("text") or ""):
                old = _row(c, r["id"])
                c.execute("UPDATE profile_rows SET status='retracted', reason=?, updated_at=? WHERE id=?", (reason, _now(), r["id"]))
                _log(c, r["id"], "retract", old, _row(c, r["id"]), eid or "cube_consent", "server")
                n += 1
        c.commit()
    finally:
        c.close()
    return n
