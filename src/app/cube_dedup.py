"""Cube dedup, skill scrub, confirmations and rank v0.

Thresholds live in cube_dedup_config.json. Cosine uses stored vectors.
embed_on_create stays off until calibrate() sees about 100 labeled pairs
that already include a cosine: the live catalog has no vectors, and this
module does not load a second embedder. calibrate() writes only when
store=True. A fitted cut is not a fixed 0.90 or 0.75.
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
_HOST = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.)+(?:com|net|org|io|ru|dev)\b",
    re.I,
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{8,}")
_PRIV = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEYISH = re.compile(r"\b(?:sk_|pza_|re_|AKIA|xai-|ghp_|github_pat_)[A-Za-z0-9_\-]{8,}")
_STEP = re.compile(r"^\s*(?:step\s+\d+[:.)]|(\d+)[.)]|[-*])\s+(.*)$", re.I)
_NEG = re.compile(r"\b(do not|don't|never|avoid|forbid|without|disable)\b", re.I)
_POS = re.compile(r"\b(always|must|required)\b", re.I)
_NEG_TEXT = re.compile(r"\b(never|forbid|forbidden|avoid|disable)\b|\bdo not\b|\bdon't\b", re.I)
_INJECT = (
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "you are now",
)
_DUP_LABELS = {"duplicate", "paraphrase", "same"}
_DIST_LABELS = {"distinct", "new", "different"}
_REL_LABELS = {"related"}
_CHEAP_MODEL = "google/gemini-2.5-flash-lite"


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
        "embed_on_create": False, "probation_n": 2,
    }
    base.update({k: cfg[k] for k in base if k in cfg})
    return base


def _pair_score(pair):
    """Cosine the caller already measured. This does not embed text."""
    if not isinstance(pair, dict):
        return None
    for key in ("cosine", "score"):
        if pair.get(key) is None:
            continue
        try:
            return float(pair[key])
        except (TypeError, ValueError):
            return None
    if pair.get("vector_a") and pair.get("vector_b"):
        return cosine(pair["vector_a"], pair["vector_b"])
    return None


def _best_cut(pos, neg):
    """Highest cosine cut that puts `pos` above it and `neg` below it."""
    if not pos or not neg:
        return None
    grid = sorted({round(float(x), 4) for x in list(pos) + list(neg)})
    best_t, best_acc = None, -1
    for t in grid:
        acc = sum(1 for s in pos if s >= t) + sum(1 for s in neg if s < t)
        if acc > best_acc or (acc == best_acc and (best_t is None or t > best_t)):
            best_acc, best_t = acc, t
    return best_t


def _clip_cos(value):
    return max(0.01, min(0.99, float(value)))


def calibrate(pairs, cfg=None, store=False, path=None):
    """Fit cosine cuts from labeled pairs. Writes the config only when store=True.

    Below 100 pairs the starting thresholds stay. Pairs need a label and a cosine
    that the caller already computed. Opposite labels are left out of the cut:
    a high cosine can still be the opposite rule.
    """
    cfg = dict(cfg or load_config())
    n = len(pairs or [])
    if n < 100:
        return {"calibrated": False, "n": n, "thresholds": cfg, "stored": False,
                "reason": "need about 100 labeled pairs before thresholds change"}
    scored = []
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        score = _pair_score(pair)
        label = str(pair.get("label") or "").strip().lower()
        if score is None or not label or label == "opposite":
            continue
        scored.append((label, score))
    if len(scored) < 100:
        return {"calibrated": False, "n": n, "thresholds": cfg, "stored": False,
                "reason": "need about 100 labeled pairs with a cosine before thresholds change"}
    dup = [s for lab, s in scored if lab in _DUP_LABELS]
    dist = [s for lab, s in scored if lab in _DIST_LABELS]
    rel = [s for lab, s in scored if lab in _REL_LABELS]
    if len(dup) < 10 or len(dist) < 10:
        return {"calibrated": False, "n": n, "thresholds": cfg, "stored": False,
                "reason": "need duplicate and distinct scores before thresholds change"}
    high = _best_cut(dup, dist + rel)
    if high is None:
        return {"calibrated": False, "n": n, "thresholds": cfg, "stored": False,
                "reason": "no separable cut in the labeled pairs"}
    if len(rel) >= 10:
        mid = _best_cut(dup, rel)
        low = _best_cut(rel, dist)
    else:
        mid = (max(dist) + min(dup)) / 2.0
        low = (min(dist) + max(dist)) / 2.0
    if mid is None or low is None:
        return {"calibrated": False, "n": n, "thresholds": cfg, "stored": False,
                "reason": "no separable cut in the labeled pairs"}
    duplicate_cos = _clip_cos(high)
    near_cos = _clip_cos(min(mid, duplicate_cos - 0.01))
    related_cos = _clip_cos(min(low, near_cos - 0.01))
    fitted = dict(cfg)
    fitted["duplicate_cos"] = round(duplicate_cos, 4)
    fitted["near_cos"] = round(near_cos, 4)
    fitted["related_cos"] = round(related_cos, 4)
    stored = False
    if store:
        dest = path or _CFG
        try:
            with open(dest, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            blob = {}
        if not isinstance(blob, dict):
            blob = {}
        blob["duplicate_cos"] = fitted["duplicate_cos"]
        blob["near_cos"] = fitted["near_cos"]
        blob["related_cos"] = fitted["related_cos"]
        blob["note"] = "Fitted by calibrate() from labeled pair cosines. Not a fixed 0.90/0.75."
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        stored = True
    return {"calibrated": True, "n": n, "used": len(scored), "thresholds": fitted,
            "stored": stored, "reason": "fitted from labeled cosine pairs"}


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


def _sub_ip(text, mark):
    from app.cube_guard import replace_ip

    def repl(m):
        return replace_ip(m.group(0), mark)

    return _IP.sub(repl, text or "")


def _clean_piece(text):
    t = text or ""
    t = _EV.sub(" ", t)
    t = _EMAIL.sub(" ", t)
    t = _sub_ip(t, " ")
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
        ip_out = _sub_ip(t, "[ip]")
        if ip_out != t:
            placeholders.append("ip")
        t = ip_out
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


def _text_opposite(new_text, old_text):
    """always X versus never X on the same remaining words. No network."""
    a, b = new_text or "", old_text or ""
    a_pos, a_neg = bool(_POS.search(a)), bool(_NEG_TEXT.search(a))
    b_pos, b_neg = bool(_POS.search(b)), bool(_NEG_TEXT.search(b))
    left_neg, left_pos = a_neg and not a_pos, a_pos and not a_neg
    right_neg, right_pos = b_neg and not b_pos, b_pos and not b_neg
    if not ((left_neg and right_pos) or (left_pos and right_neg)):
        return False
    left = _toks(_NEG_TEXT.sub(" ", _POS.sub(" ", a)))
    right = _toks(_NEG_TEXT.sub(" ", _POS.sub(" ", b)))
    if len(left) < 2 or len(right) < 2:
        return False
    return jaccard(left, right) >= 0.5


def court_scan(text):
    """File text is data. Hidden-instruction phrases go to court before a shared publish."""
    low = (text or "").lower()
    hits = [p for p in _INJECT if p in low]
    return {"treat_as_data": True, "hits": hits, "court": bool(hits)}


def _polza_key():
    raw = (os.environ.get("POLZA_KEY") or "").strip()
    if raw:
        return raw
    path = os.environ.get("SKV_ENV_FILE", "/root/skv-core/.env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("POLZA_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def cheap_opposite(text_a, text_b, timeout=8):
    """Gemini flash-lite. None when the flag is off, the call fails, or the reply is unclear.

    SKV_OPPOSITE_LLM=1 turns the call on. Tests leave it unset and stay offline.
    """
    if os.environ.get("SKV_OPPOSITE_LLM", "") != "1":
        return None
    key = _polza_key()
    if not key:
        return None
    prompt = (
        "Two rules. Reply one word only: OPPOSITE if one requires what the other forbids "
        "(always X versus never X). Reply SAME otherwise.\nA: %s\nB: %s"
        % ((text_a or "")[:800], (text_b or "")[:800])
    )
    body = json.dumps({
        "model": _CHEAP_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 16,
    }).encode()
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.polza.ai/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "skv-dedup"},
        )
        raw = urllib.request.urlopen(req, timeout=timeout).read()
        data = json.loads(raw)
        word = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip().upper()
    except Exception:
        return None
    if word.startswith("OPPOSITE"):
        return True
    if word.startswith("SAME"):
        return False
    return None


def active_opposite_check():
    """The create path calls this. Offline unless SKV_OPPOSITE_LLM=1."""
    if os.environ.get("SKV_OPPOSITE_LLM", "") == "1":
        return cheap_opposite
    return None


def scrubbed_parts(fields):
    """Scrub, then build the parts similarity compares. A secret refuses the publish."""
    scrub = scrub_skill(fields)
    if not scrub["ok"]:
        return scrub
    src = scrub["fields"]
    parts = parts_from(
        topic=src.get("topic") or "",
        problem=src.get("essence") or src.get("problem") or "",
        hooks=src.get("hooks") or "",
        skill_md=src.get("skill_md") or "",
        rules=src.get("rules") or src.get("rules_markdown") or "",
        requirements=fields.get("requirements") if isinstance(fields, dict) else [],
    )
    return {"ok": True, "parts": parts, "fields": src, "placeholders": scrub["placeholders"],
            "changed": scrub["changed"]}


def opening_status(plan, default="community"):
    """Low-band neighbor: probation. A quarantine or a cube with no neighbor keeps its status."""
    if default == "quarantine":
        return default
    if isinstance(plan, dict) and plan.get("probation"):
        return "probation"
    return default


def _extra(new_list, old_list):
    old = set(old_list or [])
    return [x for x in (new_list or []) if x not in old]


def classify(draft, candidates, cfg=None, opposite_check=None):
    """Decide duplicate / near_duplicate / conflict / related / new. Does not write or vote."""
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
    hook_opposite = _opposite(hooks, target.get("hook_rows"))
    text_opposite = _text_opposite(norm_text(parts), target.get("norm_text") or "")
    opposite = hook_opposite or text_opposite
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
    band = bool(target is sha_hit or cos >= cfg["near_cos"])
    if (not opposite) and band and opposite_check is not None:
        try:
            judged = opposite_check(norm_text(parts), target.get("norm_text") or "")
        except Exception:
            judged = None
        if judged is True:
            opposite = True
            reasons.append("opposite_check")
    base = {"canonical_cube_id": target.get("cube_id"), "similarity": round(float(cos), 4), "reasons": reasons,
            "diff": {"added_steps": added_steps, "added_hooks": added_hooks, "req_delta": delta},
            "auto_vote": False}
    if opposite and band:
        why = "opposite_hook" if hook_opposite else "opposite"
        return {**base, "result": "conflict", "court": True, "link": "against", "merge": False,
                "reasons": reasons + [why]}
    extra = bool(added_steps or added_hooks)
    if target is sha_hit and not extra and compatible:
        return {**base, "result": "duplicate", "next": _NEXT}
    if cos >= cfg["duplicate_cos"] and hook_j >= cfg["hook_jaccard"] and compatible and not extra:
        return {**base, "result": "duplicate", "next": _NEXT}
    if cos >= cfg["near_cos"] or (target is sha_hit and extra) or (cos >= cfg["duplicate_cos"] and (extra or not compatible)):
        return {**base, "result": "near_duplicate", "merge_candidate": True, "link": "merge_candidate", "court": True}
    if cos >= cfg["related_cos"]:
        return {**base, "result": "related", "probation": True, "probation_n": int(cfg.get("probation_n") or 2)}
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


def link_kind(conn, src, dst, kind, by=""):
    """Insert a link. Never deletes a cube and never merges one."""
    conn.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
    conn.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (src, dst, kind, by or ""))


def link_related(conn, src, dst, by=""):
    link_kind(conn, src, dst, "related", by)


def link_against(conn, src, dst, by=""):
    """Opposite rule. The canonical cube stays. This is not a merge."""
    link_kind(conn, src, dst, "against", by)


def link_merge_candidate(conn, src, dst, by=""):
    """Middle band. Court or the author decides. This does not merge by itself."""
    link_kind(conn, src, dst, "merge_candidate", by)


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
    agent = str(agent_id or "").strip()
    # A window name such as b20-keepalive is not an agent. Do not publish it.
    if agent and not re.match(r"^[bt]\d{1,4}-", agent, re.I):
        out["agent"] = agent[:80]
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
    promoted = _maybe_promote(conn, cube_id, ver) if outcome == "ok" else False
    return {"ok": True, "counted": True, "vote": "recorded", "votes": after, "rank_v0": rank, "promoted": promoted}


def _maybe_promote(conn, cube_id, ver):
    """Probation ends after N ok confirms from different accounts. The author is already excluded."""
    cfg = load_config()
    try:
        need = int(cfg.get("probation_n") or 2)
    except (TypeError, ValueError):
        need = 2
    if need < 1:
        need = 1
    try:
        oks = conn.execute(
            "SELECT COUNT(*) FROM cube_confirmations WHERE cube_id=? AND version=? AND outcome='ok'",
            (cube_id, ver)).fetchone()[0]
        st = conn.execute("SELECT coalesce(status,'') FROM cubes_new WHERE cube_id=?", (cube_id,)).fetchone()
    except Exception:
        return False
    if st and st[0] == "probation" and oks >= need:
        conn.execute("UPDATE cubes_new SET status='community' WHERE cube_id=? AND status='probation'", (cube_id,))
        return True
    return False


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
