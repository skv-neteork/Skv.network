"""T89 items 13-16 and 14e-14h. Pure checks. No network, no mail, no secret echo.

Contacts and secrets stay out of the portfolio. Danger answers and the vault
password are stored as sha256 only and are never put in a reply. The password
is an extra barrier, not a replacement for the API key. A second channel is
not sent: this process does not send mail or posts.
"""
import hashlib
import re
import sqlite3

R05C = (
    "cubes: write or duty=cube_nothing; vote on used; publish without a separate ask "
    "after the one-time notice; scrub personal data; user can say 'don't publish'"
)
CUBE05_ID = "cube_const_05_v24"
CUBE05_PREV = "cube_const_05_v23"
AUTHOR_CUBE = "cube_8ca30802c689"
EMPTY_CUBE_HINT = "no cube found; check whether your experience fits cube_create"
NO_EXACT = "точных совпадений нет"
PRIVATE_CUBES = "private cubes are closed"
EARLY_DONE_PAGE = 3
SCORE_FLOOR = 0.01

PORTFOLIO_FIELDS = ("name", "profession", "family", "preference", "device", "language")
_FIELD_ALIAS = {
    "preferences": "preference", "devices": "device", "languages": "language",
    "relatives": "family", "relative": "family",
}
# Control questions use non-public facts. Profession and workplace are public.
CONTROL_FIELDS = ("family", "preference", "device", "language")
_OPINION = re.compile(
    r"(?i)\b(i think|i believe|in my opinion|maybe|perhaps|probably|might|"
    r"по-моему|мне кажется|возможно|наверное|думаю)\b"
)
_DANGER = re.compile(
    r"(?i)(удали(?:ть)?\s+сервер|delete\s+the\s+server|drop\s+database|"
    r"rm\s+-rf|format\s+(?:the\s+)?disk|wipe\s+(?:the\s+)?(?:server|disk|database))"
)
_IDEA = re.compile(
    r"(?i)(dream|intention|goal|i want|we should|хочу|мечта|цель|намерен|важно|must|always|никогда|всегда)"
)
_IMPORTANT = re.compile(r"(?i)(dream|мечта|важно|must|always|никогда|всегда|goal|цель)")
_MARK = re.compile(r"^>{3}\s?\S|^CRITICAL:\s?\S", re.M)


def pin_last(obj, key="next_step"):
    """Put one field last so the ready call is the last line, after the constitution."""
    if not isinstance(obj, dict) or key not in obj:
        return obj
    value = obj.pop(key)
    obj[key] = value
    return obj


def weak_score(results, floor=SCORE_FLOOR):
    """True when a numeric score exists and the best one is under the floor."""
    best = None
    for row in results or []:
        if not isinstance(row, dict):
            continue
        score = row.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        score = float(score)
        if best is None or score > best:
            best = score
    return best is not None and best < floor


def apply_score_floor(out, results, query=""):
    """score < 0.01 is not a reliable match. Message is exact. Deep search is offered."""
    if not isinstance(out, dict) or not weak_score(results):
        return out
    out["reliable_matches"] = False
    out["not_in_memory"] = True
    out["message"] = NO_EXACT
    out["offer"] = "memory_recall_later"
    q = (query or "")[:200]
    out["next"] = "nothing found: memory_recall_later(query=%s)" % _json_str(q)
    out["deep_search"] = "memory_recall_later"
    return out


def _json_str(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def search_first_line(message=""):
    """Deep-search hint for a weak turn, including an ordinary reply."""
    q = (message or "").strip()[:120]
    if q:
        return "search first: memory_recall_later(query=%s)" % _json_str(q)
    return "search first: memory_recall_later"


def summary_ready_call(level, source_ids=""):
    level = 2 if int(level or 1) == 2 else 1
    ids = source_ids or "<ev ids>"
    field = "l2_summary" if level == 2 else "l1_summary"
    return "summary_build(level=%d) via turn(%s=\"<stages; copy every >>> mark; dated key ideas>\", source_event_ids=\"%s\")" % (
        level, field, ids)


def key_ideas(text, today=""):
    """User intentions as durable dated facts. Important ones are L2 and survive archiving."""
    found = []
    for raw in (text or "").splitlines():
        line = " ".join(raw.split()).strip()
        if len(line) < 8 or not _IDEA.search(line):
            continue
        layer = "l2" if _IMPORTANT.search(line) else "l1"
        found.append({
            "text": line[:240],
            "date": today or "",
            "layer": layer,
            "survives_archiving": layer == "l2",
        })
        if len(found) >= 8:
            break
    return found


def critical_marks(text):
    return [m.group(0).strip()[:240] for m in _MARK.finditer(text or "")][:20]


def summary_steps(level):
    level = 2 if int(level or 1) == 2 else 1
    common = [
        "Copy every >>> and CRITICAL mark verbatim.",
        "Pull the user's key ideas and intentions out as dated facts.",
        "Important ideas go to L2 and the memory map so they survive archiving.",
    ]
    if level == 1:
        return [
            "Write L1 as stages: done / decided / outcome, about 5-8% of the raw text.",
            *common,
            "Send it with source_event_ids. The server returns whatever is missing.",
        ]
    return [
        "Write L2 as one headline per stage plus open items, about 5% of those L1.",
        *common,
        "Send it with source_event_ids. The server returns whatever is missing.",
    ]


def summary_build(level=1, draft="", source_event_ids="", material="", today=""):
    """Material and short steps when due. With a draft, return the missing pieces."""
    level = 2 if int(level or 1) == 2 else 1
    ids = [x for x in re.split(r"[,\s]+", str(source_event_ids or "")) if x and x != "<ev ids>"]
    marks = critical_marks(material)
    ideas = key_ideas(material, today=today)
    packet = {
        "level": level,
        "steps": summary_steps(level),
        "marks": marks,
        "key_ideas": ideas,
        "source_event_ids": ids,
        "ready_call": summary_ready_call(level, ",".join(ids)),
    }
    if not str(draft or "").strip():
        packet["ok"] = False
        packet["missing"] = ["draft"]
        return packet
    return {**packet, **summary_check(level, draft, ids, marks, ideas)}


def summary_check(level, draft, source_ids=None, marks=None, ideas=None):
    """Server check: verbatim marks, source ids, sane size, key ideas present."""
    level = 2 if int(level or 1) == 2 else 1
    text = str(draft or "")
    missing = []
    lo, hi = (40, 4000) if level == 1 else (20, 2000)
    if len(text.strip()) < lo:
        missing.append("size: shorter than %d characters" % lo)
    if len(text) > hi:
        missing.append("size: longer than %d characters" % hi)
    for mark in marks or []:
        if mark not in text:
            missing.append("mark: " + mark[:80])
    for ev in source_ids or []:
        if ev not in text:
            missing.append("id: " + ev)
    for idea in ideas or []:
        body = idea.get("text") or ""
        if body and body not in text:
            missing.append("key idea: " + body[:80])
        if idea.get("layer") == "l2" and level == 2 and body and body not in text:
            missing.append("l2 idea: " + body[:80])
    ready = summary_ready_call(level, ",".join(source_ids or []))
    if missing:
        return {"ok": False, "missing": missing, "ready_call": ready}
    return {"ok": True, "missing": [], "ready_call": ready}


def _norm_field(field):
    f = str(field or "").strip().lower()
    f = _FIELD_ALIAS.get(f, f)
    return f if f in PORTFOLIO_FIELDS else ""


def _norm_source(source):
    s = str(source or "user_said").strip().lower().replace(" ", "_").replace("-", "_")
    if s in ("said", "user", "user_said"):
        return "user_said"
    if s in ("search", "verified", "verified_by_search"):
        return "verified_by_search"
    return ""


def portfolio_refusal(text):
    """Contacts and secrets never enter the portfolio. Return a label, not the value."""
    from app.profile import secret_hit
    if secret_hit(text or ""):
        return "contact or secret"
    if re.search(r"(?i)\[vault:|password|пароль|api[_ ]?key|token", text or ""):
        return "contact or secret"
    return ""


def ensure_portfolio(c):
    c.execute("""CREATE TABLE IF NOT EXISTS portfolio_rows (
      id TEXT PRIMARY KEY, field TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active', supersedes_id TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")


def _now():
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _pid():
    import uuid
    return "pf_" + uuid.uuid4().hex[:8]


def portfolio_apply(c, ops, today=None):
    """Add or replace a user-fact line. The old row stays, status superseded. Never DELETE."""
    ensure_portfolio(c)
    today = today or _now()
    applied, errors = [], []
    for i, op in enumerate(ops or []):
        if not isinstance(op, dict):
            continue
        field = _norm_field(op.get("field") or op.get("kind"))
        if not field:
            continue
        text = " ".join(str(op.get("text") or "").split()).strip()
        if not text or len(text) > 300:
            errors.append("portfolio %d: text must be 1..300 characters" % i)
            continue
        why = portfolio_refusal(text)
        if why:
            errors.append("portfolio %d: refused (%s). Contacts and secrets stay in the vault." % (i, why))
            continue
        source = _norm_source(op.get("source"))
        if not source:
            errors.append("portfolio %d: source must be user_said or verified_by_search" % i)
            continue
        prev = c.execute(
            "SELECT id, text FROM portfolio_rows WHERE field=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
            (field,),
        ).fetchone()
        new_id = _pid()
        if prev:
            c.execute(
                "UPDATE portfolio_rows SET status='superseded', updated_at=? WHERE id=?",
                (today, prev[0]),
            )
        c.execute(
            "INSERT INTO portfolio_rows (id, field, text, source, status, supersedes_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (new_id, field, text, source, "active", prev[0] if prev else None, today, today),
        )
        applied.append({"id": new_id, "field": field, "source": source, "date": today, "replaced": prev[0] if prev else ""})
    c.commit()
    return {"applied": applied, "errors": errors, "lines": portfolio_lines(c)}


def split_portfolio(ops):
    """Portfolio ops have a portfolio field and no profile op. No write.

    A profile op always carries op=add|supersede|retract|confirm|dismiss.
    Those stay in the profile list even when kind is preference.
    """
    raw = ops
    if isinstance(ops, (str, bytes)):
        import json
        try:
            ops = json.loads(ops or b"[]")
        except Exception:
            return raw, []
    if isinstance(ops, dict):
        ops = [ops]
    if ops is None:
        return None, []
    if not isinstance(ops, list):
        return raw, []
    kept, pf = [], []
    for op in ops:
        field = _norm_field(op.get("field") or op.get("kind")) if isinstance(op, dict) else ""
        has_profile_op = isinstance(op, dict) and bool(str(op.get("op") or "").strip())
        if field and not has_profile_op:
            pf.append(op)
        else:
            kept.append(op)
    return kept, pf


def take_portfolio(uid, ops, connect):
    """Split portfolio ops off the profile list and store them. connect(uid) -> sqlite connection."""
    kept, pf = split_portfolio(ops)
    if isinstance(ops, (str, bytes)) and not isinstance(kept, list):
        return ops, {}
    if not pf:
        return kept, {}
    c = connect(uid)
    try:
        return kept, portfolio_apply(c, pf)
    finally:
        c.close()


def portfolio_lines(c, limit=12):
    ensure_portfolio(c)
    rows = c.execute(
        "SELECT field, text, source, status, created_at FROM portfolio_rows ORDER BY created_at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    out = []
    for field, text, source, status, created in rows:
        prefix = "(old) " if status != "active" else ""
        out.append("%s%s %s %s: %s" % (prefix, created, field, source, text))
    return out


def portfolio_text(c):
    lines = portfolio_lines(c)
    if not lines:
        return ""
    return "=== PORTFOLIO (user facts, not rules; contacts and secrets stay in the vault) ===\n" + "\n".join(lines)


def portfolio_public(uid, base_dir, name_fn):
    """Read the portfolio only when the account file already exists. Do not create one."""
    import os
    path = os.path.join(base_dir, name_fn(uid) + ".db")
    if not uid or not os.path.isfile(path):
        return []
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    try:
        return portfolio_lines(c)
    except sqlite3.Error:
        return []
    finally:
        c.close()


def looks_like_opinion(text):
    return bool(_OPINION.search(text or ""))


def second_look_line(src, const, better, opinion=False):
    """Exact three-part form. src is this turn or model memory. Opinions are marked."""
    src = "checked this turn" if src == "checked this turn" else "model memory"
    if opinion:
        src = src + " (opinion)"
    return "src: %s · const: %s · better: %s" % (src, const, better)


def second_look_for(draft, checked_this_turn=False, const="01-04 and memory", better="correct the weak spot"):
    src = "checked this turn" if checked_this_turn else "model memory"
    return second_look_line(src, const, better, opinion=looks_like_opinion(draft))


def is_dangerous(text):
    return bool(_DANGER.search(text or ""))


def recall_query(query):
    """Query text safe to echo in a deep-search call. A danger command is not echoed."""
    text = str(query or "")
    if is_dangerous(text):
        return ""
    return text[:200]


def hash_value(value):
    """sha256 of the value. Callers must not put this in an agent reply."""
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def mask_sensitive(value):
    return "[SECRET]" if str(value or "") else ""


def _public_reply(payload):
    """Drop anything an agent must not see."""
    banned = {"password", "answer", "answers", "password_hash", "hash", "hashes", "expected"}
    return {k: v for k, v in payload.items() if k not in banned}


def set_password(store, value):
    """Store only the hash. The reply marks the input sensitive and does not return the value."""
    if not str(value or "").strip():
        return _public_reply({"ok": False, "error": "empty password", "sensitive": True})
    store["password_hash"] = hash_value(value)
    return _public_reply({
        "ok": True, "set": True, "sensitive": True, "masked": mask_sensitive(value),
        "note": "The server stored a hash. The agent does not see the value. This does not replace the API key.",
    })


def check_password(store, value):
    have = store.get("password_hash")
    if not have:
        return _public_reply({"ok": False, "match": False, "error": "password is not set", "sensitive": True})
    match = have == hash_value(value)
    return _public_reply({
        "ok": match, "match": match, "sensitive": True, "masked": mask_sensitive(value),
        "note": "Compared on the server. The value is not returned.",
    })


def control_questions(rows, store=None):
    """2-3 questions from non-public portfolio facts. The reply has no answer text."""
    store = store if store is not None else {}
    picked = []
    for row in rows or []:
        field = _norm_field(row.get("field"))
        text = str(row.get("text") or "")
        if field not in CONTROL_FIELDS or not text or portfolio_refusal(text):
            continue
        if field in ("profession",) or field == "workplace":
            continue
        picked.append((field, text))
        if len(picked) >= 3:
            break
    questions = []
    hashes = []
    for field, text in picked:
        questions.append("Control question (%s): answer with the non-public fact you saved. Do not use profession or workplace." % field)
        hashes.append(hash_value(text))
    while len(questions) < 2:
        questions.append("Control question: name a non-public fact (family, device, or a private preference), not your profession or workplace.")
        if len(questions) >= 3:
            break
    questions = questions[:3]
    store["answer_hashes"] = hashes
    store["questions"] = list(questions)
    return _public_reply({
        "questions": questions,
        "n": len(questions),
        "sensitive": True,
        "answers_stored": "hash_only" if hashes else "none_yet",
        "excluded": "profession and workplace are not used",
    })


def compare_answers(store, answers):
    """Server-side compare. The reply is match/mismatch only."""
    expected = list(store.get("answer_hashes") or [])
    given = [hash_value(a) for a in (answers or [])]
    if not expected:
        return _public_reply({"ok": False, "match": False, "error": "no control answers stored", "sensitive": True})
    match = given[:len(expected)] == expected and len(given) >= len(expected)
    return _public_reply({"ok": match, "match": match, "sensitive": True, "note": "Hashes compared. Answers are not returned."})


def danger_gate(message, store=None, password="", answers=None, rows=None):
    """Extra barrier for a destructive command. Not a replacement for the API key. No outward mail."""
    store = store if store is not None else {}
    if not is_dangerous(message):
        return _public_reply({"required": False})
    destructive = bool(re.search(r"(?i)удали|wipe|format|drop database|rm\s+-rf", message or ""))
    base = {
        "required": True,
        "blocked": True,
        "sensitive": True,
        "replaces_api_key": False,
        "second_channel_sent": False,
        "second_channel": "not sent. Outward mail is off. The barrier is the hashed password plus hashed control questions.",
    }
    if destructive:
        base["second_channel"] = "A second channel would apply to this destructive action, and it was not sent."
    if not store.get("password_hash"):
        asked = control_questions(rows or [], store)
        base.update({
            "ask": "Set the vault password once. The input is sensitive and masked. Then answer the control questions.",
            "questions": asked.get("questions") or [],
            "ready_call": "danger_gate(password=<sensitive>, answers=[...])",
        })
        return _public_reply(base)
    pw = check_password(store, password) if password else {"match": False}
    if not pw.get("match"):
        base["ask"] = "The vault password does not match. Input stays sensitive and masked."
        base["ready_call"] = "danger_gate(password=<sensitive>)"
        return _public_reply(base)
    if not store.get("answer_hashes"):
        asked = control_questions(rows or [], store)
        base["questions"] = asked.get("questions") or []
        base["ask"] = "Password matched. Answer the control questions. They are the fallback if the password is forgotten."
        base["password_match"] = True
        return _public_reply(base)
    ans = compare_answers(store, answers or [])
    if not ans.get("match"):
        base["ask"] = "Control answers do not match."
        base["password_match"] = True
        return _public_reply(base)
    base["blocked"] = False
    base["ok"] = True
    base["password_match"] = True
    base["answers_match"] = True
    base["note"] = "Barrier passed. The API key is still required. Nothing was emailed."
    return _public_reply(base)


def step_zero_done(page, n, early=EARLY_DONE_PAGE):
    """done is true at the last page, or earlier so turn is not blocked for the whole pack."""
    n = max(1, int(n or 1))
    page = int(page or 1)
    return page >= n or page >= min(n, int(early))


def step_zero_next(page, pages):
    """Turn is allowed while pages remain. The three pack888 phrases stay."""
    n = len(pages)
    from app.memory_pack888 import pack_span
    span = pack_span(pages)
    if page >= n:
        return "step zero complete: answer the user using turn(user_message, draft)"
    allow = "turn(user_message, draft) is allowed now, even while pages remain. "
    if step_zero_done(page, n) and page < n:
        allow = "step zero complete enough to answer. " + allow
    if span and page < span[1]:
        return (
            allow + "Optional step_zero(page=%d) continues the memory pack 8/8/8 "
            "(pages %d..%d). A record may continue on the next page."
        ) % (page + 1, span[0], span[1])
    return (
        allow + "Optional remaining pages are the constitution "
        "(CUBE 00-04 + CUBE 05-MCP)."
    )


def remote_step_next(page, total, text=""):
    """Same rule for the REST page path, which does not have the local page list."""
    total = max(1, int(total or 1))
    page = int(page or 1)
    if page >= total:
        return "step zero complete: answer the user using turn(user_message, draft)"
    allow = "turn(user_message, draft) is allowed now, even while pages remain. "
    packish = ("PACK888" in (text or "")) or page == 1
    if packish:
        return allow + "Optional step_zero(page=%d) continues the memory pack 8/8/8." % (page + 1)
    return allow + "Optional remaining pages are the constitution."


def author_triage(author_cube):
    """cube_create accepts only after the author cube was the triage. None means proceed."""
    if str(author_cube or "").strip() == AUTHOR_CUBE:
        return None
    return {
        "ok": False,
        "error": "author cube triage required",
        "author_cube": AUTHOR_CUBE,
        "private_cubes": PRIVATE_CUBES,
        "next": 'cube_get(cube_id="%s") then cube_create(..., author_cube="%s")' % (AUTHOR_CUBE, AUTHOR_CUBE),
    }


def empty_cube_search():
    return {"hint": EMPTY_CUBE_HINT, "message": EMPTY_CUBE_HINT}


def const05_record(text):
    """A new cube version. The previous id is named, not edited."""
    return {
        "cube_id": CUBE05_ID,
        "supersedes": CUBE05_PREV,
        "edit_in_place": False,
        "text": text,
        "r05c": R05C,
    }
