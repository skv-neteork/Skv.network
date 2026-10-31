"""Cube publishing consent (2026-10-25): server-owned opt-out + notice_shown, intent detection RU/EN.
status(uid): 'opted_out' | 'notice_required' (show NOTICE, call notice_shown, recheck) | 'allowed' | 'unknown' (fail closed: unknown = do not publish)."""
import re, sqlite3, time
SHARED_DB = "/data/skv/metadata_store/shared_master.db"
NOTICE = ("I may publish experience cubes, scrubbed of personal data, to the shared pool; say 'don't publish' to stop. Published cubes are permanent "
          "public property; removal only via court for a valid reason (leaked personal data or secret, harmful or illegal content, legal claim).")
# Opt-out = a DIRECT first-person request to stop publishing (Deniz 25.10 t680u). Not opt-out: quoted phrases ('don't publish'),
# rule/notice/design discussion, per-task "no publishing" for a draft. Checked per sentence after quotes are removed.
_Q = re.compile(r"'[^'\n]{1,80}'|\"[^\"\n]{1,80}\"|«[^»\n]{1,80}»|“[^”\n]{1,80}”|‘[^’\n]{1,80}’|`[^`\n]{1,80}`")
_META = re.compile(r"(?i)\b(rules?|notice|agents?|user\s+can|can\s+say|says?|said|retract\w*|design|decision|policy|court|harvest|gate|if|when|unless)\b"
                   r"|правил|агент|сказать|скажет|отзыв|решени|если|когда|суд\b|политик")
_META_P = re.compile(r"(?i)\b(notice|agents?\s+(gives?|may|can|shows?)|user\s+can|can\s+say|retract\w*|harvest|installs?)\b|скажет|можно\s+сказать|уведомл")
_OUT = re.compile(r"(?ix)("
    r"^(please\W+|ok\W+|okay\W+|so\W+|and\W+)*(don'?t|do\s+not|stop|never)\W+(publish|publishing|share|sharing|post|posting)\b"
    r"|\b(don'?t|do\s+not|stop|never)\W+(publish|publishing|share|sharing|post|posting)\W+(\w+\W+){0,2}(my|our|any\s+of\s+my)\b"
    r"|\bI\s+(don'?t|do\s+not)\s+want\s+(you\s+to\s+)?(\w+\W+){0,2}(publish|share|be\s+published|shared)\b"
    r"|\bI\s+opt\W*out\b"
    r"|^(пожалуйста\W+|слушай\W+|ок\W+|и\W+)*не\s+(надо\s+|нужно\s+)?(публикуй|публиковать|выкладывай|выкладывать|делись|делиться)"
    r"|\bне\s+(надо\s+|нужно\s+)?(публикуй|публиковать|выкладывай|выкладывать|делись|делиться)\w*\W+(\w+\W+){0,2}(мои|моё|мое|мой|мою|наши|нашу)\b"
    r"|\bзапрещаю\s+(публиковать|делиться|выкладывать)"
    r"|\bхватит\s+(публиковать|делиться|выкладывать)"
    r"|\bя\s+против\s+публикац"
    r"|\bя\s+(не\s+хочу|отказываюсь)\W+(\w+\W+){0,2}(публикова|публикац|делиться|выклады)"
    r")")
_IN = re.compile(r"(?ix)("
    r"\b(you\s+)?(may|can)\s+(publish|share)\s+(again|cubes)\b|\bresume\s+(publishing|sharing)\b|\bI\s+opt\W*in\b|\bI\s+am\s+(for|ok\s+with)\s+publishing\b"
    r"|\b(снова\s+|опять\s+)?можно\s+(снова\s+)?(публиковать|делиться|выкладывать)|\bразрешаю\s+(публиковать|делиться)|\bя\s+за\s+публикац"
    r")")
_NOPUB_P = re.compile(r"(don'?t|do not|never|no|stop)\W+(\w+\W+){0,3}publish|не\s+публик|без\s+публикац|против\s+публикац", re.I)


def _sentences(text):
    t = _Q.sub(" ", (text or "")[:4000])
    return [x.strip() for x in re.split(r"[.!?;\n]+", t) if x.strip()]


def detect(text):
    """'out' only for a direct request; 'in' for an explicit allow; None otherwise (meta talk, quotes, rules)."""
    ss = [x for x in _sentences(text) if not _META.search(x)]
    if any(_OUT.search(x) for x in ss):
        return "out"
    if any(_IN.search(x) for x in ss):
        return "in"
    return None


def profile_nopub(text):
    """A profile row counts as opt-out only if a non-quoted, non-notice sentence says don't publish."""
    return any(_NOPUB_P.search(x) for x in _sentences(text) if not _META_P.search(x))


def _c():
    c = sqlite3.connect(SHARED_DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS cube_consent (user_id TEXT PRIMARY KEY, opted_out INTEGER DEFAULT 0, notice_shown_at TEXT, "
              "source TEXT, updated_at TEXT)")
    for col in ("notice_ts REAL", "notice_msg INTEGER DEFAULT 0", "after_n INTEGER DEFAULT 0", "after_hash TEXT", "max_msg INTEGER DEFAULT 0"):
        try:
            c.execute("ALTER TABLE cube_consent ADD COLUMN " + col)
        except Exception:
            pass
    return c


_REF = re.compile(r"\bt(\d{1,7})u\b")


def _ord(s):
    """Client message ordinal from 't687u' / '[t687u] ...' / '687'. 0 = unknown."""
    s = str(s or "")
    m = _REF.search(s) or re.fullmatch(r"\s*(\d{1,7})\s*", s)
    return int(m.group(1)) if m else 0


def seen_user(uid, text):
    """Every user message (turn): track the newest message ordinal and distinct user messages after the notice."""
    import hashlib
    uid = (uid or "").lower()
    if not uid:
        return
    c = _c()
    try:
        r = c.execute("SELECT notice_ts, after_hash FROM cube_consent WHERE user_id=?", (uid,)).fetchone()
        if not r:
            return
        o = _ord((text or "")[:200])
        if o:
            c.execute("UPDATE cube_consent SET max_msg=MAX(COALESCE(max_msg,0),?) WHERE user_id=?", (o, uid))
        if r[0]:
            h = hashlib.sha1((text or "").strip()[:2000].encode()).hexdigest()[:16]
            if h != r[1]:
                c.execute("UPDATE cube_consent SET after_n=COALESCE(after_n,0)+1, after_hash=? WHERE user_id=?", (h, uid))
        c.commit()
    finally:
        c.close()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def set_opt(uid, out, source=""):
    c = _c()
    try:
        c.execute("INSERT INTO cube_consent (user_id, opted_out, source, updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                  "opted_out=excluded.opted_out, source=excluded.source, updated_at=excluded.updated_at", ((uid or "").lower(), 1 if out else 0, source[:200], _now()))
        c.execute("CREATE TABLE IF NOT EXISTS cube_consent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, opted_out INTEGER, source TEXT, ts TEXT)")
        c.execute("INSERT INTO cube_consent_log (user_id, opted_out, source, ts) VALUES (?,?,?,?)", ((uid or "").lower(), 1 if out else 0, source[:200], _now()))
        c.commit()
    finally:
        c.close()


def observe(uid, text, source="turn", eid=""):
    """Called on every user message. Returns 'out'/'in'/None. Newest explicit statement wins:
    opt-in also retracts older profile 'don't publish' rows (profile op with history)."""
    try:
        seen_user(uid, text)
    except Exception as e:
        print("[cube_consent] seen_user failed:", e, flush=True)
    d = detect(text)
    if d and uid:
        set_opt(uid, d == "out", "%s: %s" % (source, (text or "")[:120]))
        if d == "in":
            try:
                from app import profile as _p
                _p.retract_nopub(uid, eid)
            except Exception as e:
                print("[cube_consent] retract_nopub failed:", e, flush=True)
    return d


def mark_notice(uid, msg_ref=""):
    """Record the notice once, with time and the client message id of the user message this reply answers.
    Publishing opens only after a LATER user message (the user gets a window to say 'don't publish')."""
    c = _c()
    try:
        c.execute("INSERT INTO cube_consent (user_id, notice_shown_at, notice_ts, notice_msg, after_n, updated_at) VALUES (?,?,?,?,0,?) ON CONFLICT(user_id) DO UPDATE SET "
                  "notice_ts=CASE WHEN cube_consent.notice_shown_at IS NULL THEN excluded.notice_ts ELSE cube_consent.notice_ts END, "
                  "notice_msg=CASE WHEN cube_consent.notice_shown_at IS NULL THEN excluded.notice_msg ELSE cube_consent.notice_msg END, "
                  "after_n=CASE WHEN cube_consent.notice_shown_at IS NULL THEN 0 ELSE cube_consent.after_n END, "
                  "notice_shown_at=COALESCE(cube_consent.notice_shown_at, excluded.notice_shown_at), updated_at=excluded.updated_at",
                  ((uid or "").lower(), _now(), time.time(), _ord(msg_ref), _now()))
        c.commit()
        return c.execute("SELECT notice_shown_at FROM cube_consent WHERE user_id=?", ((uid or "").lower(),)).fetchone()[0]
    finally:
        c.close()


def _after(r, req_ord):
    """Notice row (opted_out, shown_at, notice_ts, notice_msg, after_n, max_msg): True once a user message after the notice exists.
    Legacy rows (shown before ordinals were stored) count as after. Same message as the notice -> False."""
    ts, nm, an, mm = r[2], r[3] or 0, r[4] or 0, r[5] or 0
    if not ts:
        return True
    if nm and req_ord:
        return req_ord > nm
    if nm and mm > nm:
        return True
    return an >= 2   # the notice turn itself is recorded once; one more distinct user message = the window passed


def info(uid, msg_ref=""):
    try:
        c = _c()
        try:
            r = c.execute("SELECT opted_out, notice_shown_at, notice_ts, notice_msg, after_n, max_msg FROM cube_consent WHERE user_id=?", ((uid or "").lower(),)).fetchone()
        finally:
            c.close()
        from app import profile as _p
        prof = _p.publish_opted_out(uid)
        if prof is None:
            return {"status": "unknown", "notice_shown": bool(r and r[1])}
        out = bool(r and r[0]) or bool(prof)
        st = "opted_out" if out else ("notice_required" if not (r and r[1]) else ("allowed" if _after(r, _ord(msg_ref)) else "notice_pending"))
        return {"status": st, "hint": ("notice shown in reply to %s; publish only after the user's next message" % ("t%du" % r[3] if r[3] else "the current message")) if st == "notice_pending" else None, "notice_shown": bool(r and r[1]), "notice_shown_at": (r[1] if r else None),
                "notice": None if (r and r[1]) else NOTICE}
    except Exception as e:
        return {"status": "unknown", "error": str(e)[:120]}
