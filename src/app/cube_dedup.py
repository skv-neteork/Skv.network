"""Cube dedup, skill scrub, confirmations and rank v0.

Thresholds live in cube_dedup_config.json. Cosine uses stored vectors.
embed_on_create stays off until calibrate() sees about 100 labeled pairs:
the live catalog has no vectors, and an uncalibrated model would file
ordinary creates as court cases.
"""
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_CFG = os.path.join(_HERE, "cube_dedup_config.json")
_HIDDEN = ("superseded", "rejected", "archived", "removed", "quarantine", "pending_version", "deprecated", "disputed")
_NEXT = "cube_confirm(...) | cube_propose_version(...)"
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CHAIN = re.compile(r"\bch_[0-9a-fA-F]{8,}\b")
_EV = re.compile(r"\[ev:[^\]]+\]")
_REPO = re.compile(r"\bgithub\.com/[\w.-]+/[\w.-]+\b", re.I)
_PATH = re.compile(r"(?:(?:/|\b)(?:root|home|Users|opt|var|data|tmp|workspace)/[^\s\"'`<>]+)|(?:[A-Za-z]:\\[^\s\"'`<>]+)")
_HOST = re.compile(r"\b[a-z0-9][a-z0-9-]{0,62}\.(?:com|net|org|io|ru|dev)\b", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{8,}")
_PRIV = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEYISH = re.compile(r"\b(?:sk_|pza_|re_|AKIA|xai-|ghp_|github_pat_)[A-Za-z0-9_\-]{8,}")
_STEP = re.compile(r"^\s*(?:step\s+\d+[:.)]|(\d+)[.)]|[-*])\s+(.*)$", re.I)
_NEG = re.compile(r"\b(do not|don't|never|avoid|forbid|without|disable)\b", re.I)


def load_config():
    try:
        with open(_CFG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        cfg = {}
    base = {
        "candidate_cos": 0.78, "duplicate_cos": 0.93, "hook_jaccard": 0.6,
        "near_cos": 0.84, "related_cos": 0.75, "norm_jaccard_exact": 0.85,
        "young_account_days": 7, "young_weight": 0.5, "half_life_days": 90,
        "embed_on_create": False,
    }
    base.update({k: cfg[k] for k in base if k in cfg})
    return base


def calibrate(pairs, cfg=None):
    """Suggest thresholds from labeled pairs. Does not write the config below 100 pairs."""
    cfg = dict(cfg or load_config())
    n = len(pairs or [])
    if n < 100:
        return {"calibrated": False, "n": n, "thresholds": cfg,
                "reason": "need about 100 labeled pairs before thresholds change"}
    return {"calibrated": False, "n": n, "thresholds": cfg,
            "reason": "pair set is large enough to review; thresholds stay at the starting values until a person accepts a fit"}


def _toks(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower())}


def jaccard(a, b):
    aa, bb = set(a or []), set(b or [])
    if not aa and not bb:
        return 1.0
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def parse_hooks(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:
            data = [ln.strip() for ln in str(raw).splitlines() if ln.strip()]
    out = []
    for h in data[:32]:
        if isinstance(h, str) and h.strip():
            out.append({"when": h.strip()[:500], "do": ""})
        elif isinstance(h, dict):
            when = str(h.get("when") or h.get("if") or "").strip()[:500]
            do = str(h.get("do") or h.get("then") or "").strip()[:500]
            if when:
                out.append({"when": when, "do": do})
    return out


def _steps_from(skill_md, rules):
    lines = []
    for src in (skill_md or "", rules or ""):
        for ln in src.splitlines():
            m = _STEP.match(ln)
            if m:
                lines.append(re.sub(r"\s+", " ", (m.group(2) or m.group(0)).strip().lower()))
        if lines:
            break
    if not lines:
        lines = [re.sub(r"\s+", " ", ln.strip().lower()) for ln in (skill_md or rules or "").splitlines() if ln.strip()][:32]
    return lines


def _clean_piece(text):
    t = text or ""
    t = _EV.sub(" ", t)
    t = _EMAIL.sub(" ", t)
    t = _IP.sub(" ", t)
    t = _CHAIN.sub(" ", t)
    t = _REPO.sub(" ", t)
    t = _PATH.sub(" ", t)
    t = _HOST.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def parts_from(topic="", problem="", hooks=None, steps=None, result="", requirements=None, skill_md="", rules=""):
    hs = parse_hooks(hooks)
    step_list = list(steps or []) or _steps_from(skill_md, rules)
    reqs = list(requirements or [])
    return {
        "topic": _clean_piece(topic),
        "problem": _clean_piece(problem),
        "hooks": [_clean_piece(h["when"]) for h in hs if h.get("when")],
        "hook_rows": hs,
        "steps": [_clean_piece(s) for s in step_list if _clean_piece(s)],
        "result": _clean_piece(result),
        "requirements": reqs,
    }


def norm_text(parts):
    req_bits = []
    for r in parts.get("requirements") or []:
        if isinstance(r, dict):
            req_bits.append(" ".join([str(r.get("kind") or ""), str(r.get("name") or ""), str(r.get("constraint_text") or "")]))
        else:
            req_bits.append(str(r))
    chunks = [parts.get("topic") or "", parts.get("problem") or ""]
    chunks += parts.get("hooks") or []
    chunks += parts.get("steps") or []
    chunks += [parts.get("result") or ""]
    chunks += [_clean_piece(x) for x in req_bits]
    return "\n".join(x for x in chunks if x)


def steps_sha(parts):
    return _sha("\n".join(parts.get("steps") or []))


def _entropy(token):
    if not token:
        return 0.0
    from collections import Counter
    n = len(token)
    return -sum((c / n) * math.log2(c / n) for c in Counter(token).values())


def _secret_reasons(text):
    reasons = []
    if _PRIV.search(text or ""):
        reasons.append("private_key")
    if _JWT.search(text or ""):
        reasons.append("jwt")
    if _KEYISH.search(text or ""):
        reasons.append("key_pattern")
    for tok in re.findall(r"[A-Za-z0-9+/_=.-]{24,}", text or ""):
        if _entropy(tok) >= 3.6 and re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok):
            reasons.append("high_entropy")
            break
    return reasons


def scrub_skill(fields):
    """Skill import scrub. Secrets refuse the publish. Paths, hosts, ids become placeholders."""
    src = {k: (v if isinstance(v, str) else ("" if v is None else json.dumps(v, ensure_ascii=False))) for k, v in (fields or {}).items()}
    blob = "\n".join(src.values())
    secrets = _secret_reasons(blob)
    if secrets:
        return {"ok": False, "reasons": ["secret:" + ",".join(sorted(set(secrets)))], "fields": src, "changed": False, "placeholders": [], "doubtful": False}
    placeholders = []

    def repl(name, rx, mark, text):
        new, n = rx.subn(mark, text)
        if n:
            placeholders.append(name)
        return new

    out = {}
    for k, v in src.items():
        t = v
        t = repl("event", _EV, "[event]", t)
        t = repl("email", _EMAIL, "[email]", t)
        t = repl("ip", _IP, "[ip]", t)
        t = repl("chain", _CHAIN, "[chain]", t)
        t = repl("repo", _REPO, "[repo]", t)
        t = repl("path", _PATH, "[path]", t)
        t = repl("host", _HOST, "[host]", t)
        out[k] = t
    doubtful = len(set(placeholders)) >= 4
    return {"ok": True, "reasons": [], "fields": out, "changed": out != src, "placeholders": sorted(set(placeholders)), "doubtful": doubtful}


def _req_map(reqs):
    out = {}
    for r in reqs or []:
        if not isinstance(r, dict):
            continue
        key = (str(r.get("kind") or ""), str(r.get("name") or ""))
        out[key] = (str(r.get("constraint_text") or ""), bool(r.get("optional")))
    return out


def req_delta(new_reqs, old_reqs):
    a, b = _req_map(new_reqs), _req_map(old_reqs)
    added = [k for k in a if k not in b]
    removed = [k for k in b if k not in a]
    changed = [k for k in a if k in b and a[k][0] != b[k][0]]
    return {"added": added, "removed": removed, "changed": changed}


def reqs_compatible(new_reqs, old_reqs):
    d = req_delta(new_reqs, old_reqs)
    return not d["changed"]


def _opposite(new_hooks, old_hooks):
    old = {(h["when"] or "").strip().lower(): (h.get("do") or "") for h in (old_hooks or [])}
    for h in new_hooks or []:
        when = (h.get("when") or "").strip().lower()
        if when not in old:
            continue
        a, b = h.get("do") or "", old[when]
        if bool(_NEG.search(a)) != bool(_NEG.search(b)) and jaccard(_toks(a), _toks(b)) >= 0.3:
            return True
    return False


def _extra(new_list, old_list):
    old = set(old_list or [])
    return [x for x in (new_list or []) if x not in old]


def classify(draft, candidates, cfg=None):
    """Decide duplicate / near_duplicate / conflict / related / new. Does not write."""
    cfg = cfg or load_config()
    kind = (draft.get("kind") or "moment").strip().lower()
    parts = draft.get("parts") or {}
    sha = draft.get("steps_sha") or steps_sha(parts)
    hooks = parts.get("hook_rows") or []
    whens = parts.get("hooks") or []
    best = None
    best_cos = -1.0
    sha_hit = None
    for c in candidates or []:
        if (c.get("kind") or "moment").strip().lower() != kind:
            continue
        if (c.get("status") or "") in _HIDDEN:
            continue
        if c.get("cube_id") and c.get("cube_id") == draft.get("cube_id"):
            continue
        if sha and c.get("steps_sha") == sha:
            # Same checklist on a different subject is a different cube.
            # Cosine is off until vectors exist, so the subject has to match.
            same_hooks = jaccard(whens, c.get("hooks") or []) >= cfg["hook_jaccard"] or not (whens or c.get("hooks"))
            same_subject = bool(parts.get("topic")) and parts.get("topic") == (c.get("topic") or "")
            if same_hooks and same_subject and sha_hit is None:
                sha_hit = c
        cos = cosine(draft.get("vector"), c.get("vector"))
        if cos is None or cos < cfg["related_cos"]:
            continue
        if cos > best_cos:
            best, best_cos = c, cos
    target = sha_hit or best
    if target is None:
        return {"result": "new", "reasons": []}
    measured = cosine(draft.get("vector"), target.get("vector"))
    if measured is None:
        cos = 1.0 if target is sha_hit else 0.0
    else:
        cos = measured
    added_steps = _extra(parts.get("steps"), target.get("steps")) if len(parts.get("steps") or []) > len(target.get("steps") or []) else []
    added_hooks = _extra(whens, target.get("hooks"))
    delta = req_delta(parts.get("requirements"), target.get("requirements"))
    opposite = _opposite(hooks, target.get("hook_rows"))
    hook_j = jaccard(whens, target.get("hooks") or [])
    compatible = reqs_compatible(parts.get("requirements"), target.get("requirements"))
    reasons = []
    if target is sha_hit:
        reasons.append("steps_sha")
    if cos >= cfg["duplicate_cos"]:
        reasons.append("cosine")
    if hook_j >= cfg["hook_jaccard"]:
        reasons.append("hooks")
    if compatible:
        reasons.append("requirements")
    base = {"canonical_cube_id": target.get("cube_id"), "similarity": round(float(cos), 4), "reasons": reasons,
            "diff": {"added_steps": added_steps, "added_hooks": added_hooks, "req_delta": delta}}
    if opposite and (target is sha_hit or cos >= cfg["near_cos"]):
        return {**base, "result": "conflict", "court": True, "reasons": reasons + ["opposite_hook"]}
    extra = bool(added_steps or added_hooks)
    if target is sha_hit and not extra and compatible:
        return {**base, "result": "duplicate", "next": _NEXT}
    if cos >= cfg["duplicate_cos"] and hook_j >= cfg["hook_jaccard"] and compatible and not extra:
        return {**base, "result": "duplicate", "next": _NEXT}
    if cos >= cfg["near_cos"] or (target is sha_hit and extra) or (cos >= cfg["duplicate_cos"] and (extra or not compatible)):
        return {**base, "result": "near_duplicate"}
    if cos >= cfg["related_cos"]:
        return {**base, "result": "related"}
    return {"result": "new", "reasons": []}


def _vec(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if isinstance(raw, list) and raw and isinstance(raw[0], (int, float)):
        return [float(x) for x in raw]
    return None


def ensure(conn):
    have = {r[1] for r in conn.execute("PRAGMA table_info(cubes_new)")}
    for col, ddl in (("norm_text", "TEXT"), ("steps_sha", "TEXT"), ("requirements_json", "TEXT"),
                     ("applied_json", "TEXT"), ("rank_v0", "REAL"), ("cube_version", "TEXT DEFAULT '1'")):
        if col not in have:
            conn.execute("ALTER TABLE cubes_new ADD COLUMN %s %s" % (col, ddl))
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cube_confirmations (
        cube_id TEXT, version TEXT, account_id TEXT, agent_id TEXT,
        outcome TEXT, evidence TEXT, env_json TEXT, created_at TEXT,
        UNIQUE(cube_id, version, account_id));
    CREATE TABLE IF NOT EXISTS cube_contributions (
        id INTEGER PRIMARY KEY, cube_id TEXT, version TEXT, account_id TEXT, agent_id TEXT,
        type TEXT, source_hash TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS cube_requirements (
        id INTEGER PRIMARY KEY, cube_id TEXT, version TEXT, kind TEXT, name TEXT,
        constraint_text TEXT, optional INTEGER);
    CREATE INDEX IF NOT EXISTS ix_cubes_steps_sha ON cubes_new(steps_sha);
    """)


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except Exception:
        return default


def load_candidates(conn, kind):
    ensure(conn)
    q = ",".join("?" * len(_HIDDEN))
    rows = conn.execute(
        """SELECT cube_id, coalesce(kind,'moment'), coalesce(steps_sha,''), coalesce(norm_text,''),
                  coalesce(hooks,''), coalesce(skill_md,''), coalesce(rules_markdown,''),
                  coalesce(requirements_json,''), vector, coalesce(status,'community'),
                  coalesce(subject_action_object,''), coalesce(essence,'')
           FROM cubes_new WHERE coalesce(kind,'moment')=? AND coalesce(status,'community') NOT IN (%s)""" % q,
        (kind,) + _HIDDEN).fetchall()
    out = []
    for r in rows:
        parts = parts_from(topic=r[10], problem=r[11], hooks=r[4], skill_md=r[5], rules=r[6], requirements=_loads(r[7], []))
        out.append({
            "cube_id": r[0], "kind": r[1], "steps_sha": r[2] or steps_sha(parts), "norm_text": r[3] or norm_text(parts),
            "topic": parts["topic"],
            "hooks": parts["hooks"], "hook_rows": parts["hook_rows"], "steps": parts["steps"],
            "requirements": parts["requirements"], "vector": _vec(r[8]), "status": r[9],
        })
    return out


def stamp(conn, cube_id, parts, vector=None, requirements=None, applied=None, version="1"):
    ensure(conn)
    conn.execute(
        """UPDATE cubes_new SET norm_text=?, steps_sha=?, requirements_json=?, applied_json=?, cube_version=?
           WHERE cube_id=?""",
        (norm_text(parts), steps_sha(parts), json.dumps(requirements or parts.get("requirements") or [], ensure_ascii=False),
         json.dumps(applied or {}, ensure_ascii=False), version or "1", cube_id))
    if vector:
        conn.execute("UPDATE cubes_new SET vector=? WHERE cube_id=?", (json.dumps(vector), cube_id))
    conn.execute("DELETE FROM cube_requirements WHERE cube_id=? AND version=?", (cube_id, version or "1"))
    for req in requirements or parts.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        conn.execute(
            "INSERT INTO cube_requirements (cube_id, version, kind, name, constraint_text, optional) VALUES (?,?,?,?,?,?)",
            (cube_id, version or "1", req.get("kind") or "", req.get("name") or "", req.get("constraint_text") or "", 1 if req.get("optional") else 0))


def link_related(conn, src, dst, by=""):
    conn.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
    conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (src, dst, "related", by or ""))


def link_pending(conn, canonical, new_id, diff, reason):
    conn.execute("CREATE TABLE IF NOT EXISTS court_queue (cube_id TEXT PRIMARY KEY, reason TEXT, created_at TEXT)")
    row = conn.execute("SELECT links_json FROM cubes_new WHERE cube_id=?", (canonical,)).fetchone()
    try:
        lj = json.loads((row[0] if row else "") or "{}")
    except Exception:
        lj = {}
    if isinstance(lj, list):
        lj = {"links": lj}
    lj["proposed_versions"] = list(dict.fromkeys((lj.get("proposed_versions") or []) + [new_id]))
    conn.execute("UPDATE cubes_new SET links_json=? WHERE cube_id=?", (json.dumps(lj), canonical))
    conn.execute("UPDATE cubes_new SET parent_id=?, status='pending_version', links_json=? WHERE cube_id=?",
                 (canonical, json.dumps({"supersedes": canonical, "diff": diff, "court": True}), new_id))
    conn.execute("INSERT INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now')) ON CONFLICT(cube_id) DO UPDATE SET reason=excluded.reason",
                 (canonical, (reason or "pending version")[:900]))


def public_author(created_by, agent_id=""):
    email = (created_by or "").strip().lower()
    if not email:
        return None
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:10]
    out = {"account": "acct_" + digest}
    if agent_id:
        out["agent"] = str(agent_id)[:80]
    return out


def confirm(conn, cube_id, account_id, outcome, evidence, agent_id="", env=None, version=""):
    ensure(conn)
    account = (account_id or "").strip().lower()
    outcome = (outcome or "").strip().lower()
    evidence = (evidence or "").strip()
    if outcome not in ("ok", "partial", "fail"):
        return {"ok": False, "error": "outcome must be ok, partial or fail"}
    if not evidence or len(evidence) > 500:
        return {"ok": False, "error": "evidence is required and at most 500 characters"}
    row = conn.execute("SELECT coalesce(created_by,''), coalesce(cube_version,'1') FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "cube not found"}
    if account and account == (row[0] or "").strip().lower():
        return {"ok": True, "counted": False, "reason": "author", "votes": _vote_count(conn, cube_id, version or row[1] or "1")}
    ver = (version or row[1] or "1").strip() or "1"
    before = _vote_count(conn, cube_id, ver)
    conn.execute(
        """INSERT OR IGNORE INTO cube_confirmations (cube_id, version, account_id, agent_id, outcome, evidence, env_json, created_at)
           VALUES (?,?,?,?,?,?,?,datetime('now'))""",
        (cube_id, ver, account, (agent_id or "")[:80], outcome, evidence[:500], json.dumps(env or {}, ensure_ascii=False)))
    after = _vote_count(conn, cube_id, ver)
    if after == before:
        return {"ok": True, "counted": True, "vote": "one", "votes": after, "note": "this account already confirmed this version"}
    conn.execute(
        "INSERT INTO cube_contributions (cube_id, version, account_id, agent_id, type, source_hash, created_at) VALUES (?,?,?,?,?,?,datetime('now'))",
        (cube_id, ver, account, (agent_id or "")[:80], "case", _sha(evidence), ))
    rank = recompute_rank(conn, cube_id, ver)
    return {"ok": True, "counted": True, "vote": "recorded", "votes": after, "rank_v0": rank}


def _vote_count(conn, cube_id, version):
    return conn.execute("SELECT COUNT(*) FROM cube_confirmations WHERE cube_id=? AND version=?", (cube_id, version)).fetchone()[0]


def _young(conn, account_id, cfg, now=None):
    try:
        row = conn.execute("SELECT created_at FROM users WHERE lower(email)=?", ((account_id or "").lower(),)).fetchone()
    except Exception:
        return False
    if not row or not row[0]:
        return False
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    raw = str(row[0])[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            created = datetime.strptime(raw, fmt)
            break
        except Exception:
            created = None
    if created is None:
        return False
    return (now - created).days < int(cfg["young_account_days"])


def confirmation_rows(conn, cube_id, version, author=""):
    ensure(conn)
    author = (author or "").strip().lower()
    rows = conn.execute(
        "SELECT account_id, outcome, created_at FROM cube_confirmations WHERE cube_id=? AND version=?",
        (cube_id, version)).fetchall()
    return [r for r in rows if (r[0] or "").strip().lower() != author]


def q_of(rows, weight_of):
    ok = partial = fail = 0.0
    for account, outcome, _ts in rows:
        w = float(weight_of(account))
        if outcome == "ok":
            ok += w
        elif outcome == "partial":
            partial += w
        elif outcome == "fail":
            fail += w
    return (ok + 0.5 * partial + 1.0) / (ok + partial + 1.5 * fail + 2.0)


def rank_score(relevance, q, a_ok, last_ok, now=None, half_life_days=90):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if last_ok is None:
        decay = 1.0
    else:
        if isinstance(last_ok, str):
            last_ok = datetime.strptime(str(last_ok)[:19], "%Y-%m-%d %H:%M:%S")
        age = max(0.0, (now - last_ok).total_seconds() / 86400.0)
        decay = 0.5 ** (age / float(half_life_days))
    return float(relevance) * (0.5 + 0.5 * q) * (1.0 + 0.3 * math.log(1.0 + a_ok)) * decay


def recompute_rank(conn, cube_id, version="1", relevance=1.0, now=None):
    cfg = load_config()
    author = ((conn.execute("SELECT coalesce(created_by,'') FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone() or [""])[0])
    rows = confirmation_rows(conn, cube_id, version, author)
    weight = lambda account: cfg["young_weight"] if _young(conn, account, cfg, now) else 1.0
    q = q_of(rows, weight)
    oks = [(a, ts) for a, outcome, ts in rows if outcome == "ok"]
    a_ok = sum(weight(a) for a, _ts in oks)
    last = max((ts for _a, ts in oks), default=None)
    score = rank_score(relevance, q, a_ok, last, now, cfg["half_life_days"])
    conn.execute("UPDATE cubes_new SET rank_v0=? WHERE cube_id=?", (score, cube_id))
    return score


def propose_version(conn, canonical_id, fields, reason, created_by=""):
    """Court only. The canonical cube stays as it is. No auto-merge."""
    ensure(conn)
    parent = conn.execute(
        "SELECT subject_action_object, essence, rules_markdown, skill_md, hooks, kind, carrier, created_by FROM cubes_new WHERE cube_id=?",
        (canonical_id,)).fetchone()
    if not parent:
        return {"ok": False, "error": "cube not found"}
    import uuid
    new_id = "cube_" + uuid.uuid4().hex[:12]
    topic = fields.get("topic") or parent[0]
    essence = fields.get("essence") or parent[1]
    rules = fields.get("rules") or parent[2]
    skill = fields.get("skill_md") if "skill_md" in fields else (parent[3] or "")
    hooks = fields.get("hooks") if "hooks" in fields else (parent[4] or "")
    if not isinstance(hooks, str):
        hooks = json.dumps(hooks, ensure_ascii=False)
    kind = fields.get("kind") or parent[5] or "moment"
    carrier = fields.get("carrier") or parent[6] or "answer"
    author = created_by or parent[7] or ""
    conn.execute(
        """INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, skill_md, hooks, carrier, parent_id)
           VALUES (?,?,?,?,?,'pending_version',?,?,?,?,?,?)""",
        (new_id, essence, topic, rules, "court version", author, kind, skill, hooks, carrier, canonical_id))
    parts = parts_from(topic=topic, problem=essence, hooks=hooks, skill_md=skill, rules=rules, requirements=fields.get("requirements") or [])
    stamp(conn, new_id, parts, requirements=fields.get("requirements") or [], version="2")
    diff = fields.get("diff") or {"added_steps": [], "added_hooks": [], "req_delta": {}}
    link_pending(conn, canonical_id, new_id, diff, reason)
    conn.execute(
        "INSERT INTO cube_contributions (cube_id, version, account_id, agent_id, type, source_hash, created_at) VALUES (?,?,?,?,?,?,datetime('now'))",
        (new_id, "2", (author or "").lower(), "", "origin", _sha(norm_text(parts))))
    return {"ok": True, "result": "pending_version", "cube_id": new_id, "canonical_cube_id": canonical_id, "court": True}


def fill_missing_steps(conn, limit=400):
    ensure(conn)
    rows = conn.execute(
        """SELECT cube_id, coalesce(subject_action_object,''), coalesce(essence,''), coalesce(rules_markdown,''),
                  coalesce(skill_md,''), coalesce(hooks,''), coalesce(requirements_json,'')
           FROM cubes_new WHERE coalesce(steps_sha,'')='' LIMIT ?""", (int(limit),)).fetchall()
    n = 0
    for r in rows:
        parts = parts_from(topic=r[1], problem=r[2], hooks=r[5], skill_md=r[4], rules=r[3], requirements=_loads(r[6], []))
        if not parts["steps"] and not parts["topic"]:
            continue
        stamp(conn, r[0], parts, requirements=parts["requirements"])
        n += 1
    return n
