"""T72: duty RULES in the turn reply (not commands). The agent decides from its chat history; the server only keeps the rules in context.

Each rule says what the agent does, in which circumstances and how the result looks. Per turn the server shows 1-2 short rules:
a relevant one when an event matches (summary_due -> L1, task_done -> cube, a RATE hint -> vote ...), otherwise the next one in a
round-robin per (account, session). Escalation: per duty the server counts shown-but-not-done. While the agent is compliant the text is soft; after
N ignored (default 4) the header becomes "MANDATORY: <duty> reminded <k> times without action, do it now" and the rule is pinned
every turn until the agent does the duty, or dismisses it with turn(duty="rule_<duty>", duty_reason="<why>"), then it is soft again.
Only occasions that really applied count as ignored (L1 only while turns are uncovered, cube only after a task close, ...).

Config (re-read on mtime): /data/skv/duty_rules.json {"enabled","escalate_after","per_turn","snooze_turns","max_pinned"}; env SKV_DUTY_RULES=0 switches it off.
State: /data/skv/metadata_store/duty_rules.db (tables dr_scope, dr_duty). Never raises: on any error the turn is unchanged."""
import json
import os
import re
import sqlite3
import time

DB = "/data/skv/metadata_store/duty_rules.db"
CFG_PATH = "/data/skv/duty_rules.json"
SHARED_DB = "/data/skv/metadata_store/shared_master.db"
DEFAULTS = {"enabled": True, "escalate_after": 4, "per_turn": 1, "snooze_turns": 30, "max_pinned": 2}
_C = {"m": None, "v": dict(DEFAULTS)}

DUTIES = ("l1", "critical", "l2", "cube", "sensitive", "vote", "profile")
AUTHOR_CUBE = "cube_3de96286fc73"
DONE_ALIASES = {"cube": ("cube_nothing", "cube_harvest", "skills_harvest", "skills_none", "skills_skip"), "vote": ("vote_nothing",)}
_REMEMBER = re.compile(r"\b(remember|keep in mind|don'?t forget|codename|from now on|always|never)\b|запомни|не забудь|учти|кодов\w+ слов|с этого момента|всегда|никогда", re.I)


def _cube_id():
    try:
        from app.room.skills_harvest import meta_cube_id
        return meta_cube_id() or AUTHOR_CUBE
    except Exception:
        return AUTHOR_CUBE


def rule_text(duty):
    """Soft rule: what / when / how it looks. Short, English."""
    return {
        "l1": "RULE L1: at the start or end of a big task, or when a topic closes, send l1_summary = stages done / decided / outcome (~5-8% of the raw text) "
              "+ source_event_ids it covers. You judge from the chat; skip routine chatter.",
        "critical": "RULE critical: when the user states a lasting fact (name, codename, standing rule, decision), send critical=\"<one fact>\" in that turn "
                    "(several: separate with ' | '). Not for passing details.",
        "l2": "RULE L2: after ~10 L1 send l2_summary = topic map (one headline per stage + open items, ~5% of those L1) with source_event_ids and profile_review.",
        "cube": "RULE experience cube: when a task closes, publish a cube: problem / steps / result, English, no personal data, code or secrets. "
                "Open the author cube first: cube_get(cube_id=\"%s\"). Nothing worth sharing: duty=cube_nothing + reason." % _cube_id(),
        "sensitive": "RULE sensitive: when a message or your answer holds a password, key, token or card, pass sensitive=\"<exact string>|...\"; the server masks it as [SECRET]. "
                     "Never repeat it in critical, summaries or cubes.",
        "vote": "RULE vote: after you apply a cube, rate it: cube_vote +1 / -1 (or duty=vote_nothing + reason).",
        "profile": "RULE profile: when the user states or changes a lasting rule about how to work with them, write it in the same turn: "
                   "profile=[{op:add,kind,text,scope,ev:[\"this\"]}].",
    }.get(duty, "")


SHORT = {
    "l1": "send l1_summary (stages done / decided / outcome, ~5-8% of raw text) + source_event_ids.",
    "critical": "send critical=\"<lasting fact>\" for each lasting fact the user stated (several: ' | ').",
    "l2": "send l2_summary (topic map: one headline per stage + open items) + source_event_ids + profile_review.",
    "cube": "publish the experience cube (problem / steps / result, scrubbed; cube_get the author cube first) or duty=cube_nothing + reason.",
    "sensitive": "pass sensitive=\"<exact secret string>|...\" for every secret in this exchange.",
    "vote": "rate the cube you applied: cube_vote +1 / -1, or duty=vote_nothing + reason.",
    "profile": "write the user's lasting rule: profile=[{op:add,kind,text,scope,ev:[\"this\"]}].",
}


def mandatory_text(duty, k):
    return ("MANDATORY: %s reminded %d times without action, do it now: %s Does not apply? duty=rule_%s + duty_reason=\"<why>\"."
            % (duty, k, SHORT.get(duty, ""), duty))


def cfg(k):
    try:
        m = os.path.getmtime(CFG_PATH)
        if m != _C["m"]:
            with open(CFG_PATH) as fh:
                d = json.load(fh)
            v = dict(DEFAULTS)
            v.update({a: b for a, b in d.items() if a in DEFAULTS})
            _C.update(m=m, v=v)
    except FileNotFoundError:
        _C.update(m=None, v=dict(DEFAULTS))
    except Exception:
        pass
    return _C["v"].get(k, DEFAULTS.get(k))


def enabled():
    return os.environ.get("SKV_DUTY_RULES", "1") not in ("0", "off", "false") and bool(cfg("enabled"))


def _db(path=None):
    c = sqlite3.connect(path or DB, timeout=10, isolation_level=None)
    c.execute("create table if not exists dr_scope(user text, scope text, turn_n int default 0, rr int default 0, primary key(user, scope))")
    c.execute("create table if not exists dr_duty(user text, scope text, duty text, shown int default 0, ignored int default 0, done_n int default 0, "
              "pending int default 0, pinned int default 0, last_shown_turn int default -1000000, last_shown_t real default 0, snooze_until int default 0, "
              "primary key(user, scope, duty))")
    return c


def _fmt(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))


def external_done(user, duty, since_t, shared_db=None):
    """Evidence outside /remember fields: a cube the account created, or a cube vote, since the rule was last shown."""
    if not user or not since_t or duty not in ("cube", "vote"):
        return False
    p = shared_db or SHARED_DB
    if not os.path.isfile(p):
        return False
    try:
        c = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=5)
        try:
            if duty == "cube":
                return c.execute("select 1 from cubes_new where lower(created_by)=? and created_at>=? limit 1", (user.strip().lower(), _fmt(since_t))).fetchone() is not None
            return c.execute("select 1 from cube_outcomes where lower(user_id)=? and ts>=? limit 1", (user.strip().lower(), _fmt(since_t))).fetchone() is not None
        finally:
            c.close()
    except sqlite3.Error:
        return False


def signals(req_fields, ctx):
    """-> (done:set, dismissed:dict, events:set, applicable:dict) from one /remember call.
    req_fields: l1_summary, l2_map, critical, sensitive, profile, profile_review, duty, duty_reason, task_done, query.
    ctx: l1_pending (uncovered turns), nl1 (L1 since the last L2), summary_due (dict|None), cube_hint (bool), rate_hint (bool),
         vaulted (bool: the save path found a secret), profile_open (bool)."""
    f = req_fields
    d = (f.get("duty") or "").strip().lower()
    done, dismissed, events = set(), {}, set()
    if f.get("l1_summary"): done.add("l1")
    if f.get("l2_map"): done.add("l2")
    if (f.get("critical") or "").strip(): done.add("critical")
    if [x for x in (f.get("sensitive") or []) if x]: done.add("sensitive")
    if f.get("profile") or f.get("profile_review"): done.add("profile")
    for duty, names in DONE_ALIASES.items():
        if d in names: done.add(duty)
    if f.get("cube_created"): done.add("cube")
    if d.startswith("rule_") and d[5:] in DUTIES and len((f.get("duty_reason") or "").strip()) >= 3:
        dismissed[d[5:]] = f.get("duty_reason").strip()[:120]
    sd = ctx.get("summary_due") or {}
    if isinstance(sd, dict):
        if sd.get("l1"): events.add("l1")
        if sd.get("l2"): events.add("l2")
    if f.get("task_done") or ctx.get("cube_hint"): events.add("cube")
    if ctx.get("rate_hint"): events.add("vote")
    if ctx.get("profile_open"): events.add("profile")
    app = {
        "l1": int(ctx.get("l1_pending") or 0) >= 8,
        "l2": int(ctx.get("nl1") or 0) >= 10,
        "cube": bool(f.get("task_done") or ctx.get("cube_hint")),
        "vote": bool(ctx.get("rate_hint")),
        "sensitive": bool(ctx.get("vaulted")),
        "profile": bool(ctx.get("profile_open")),
        "critical": bool(_REMEMBER.search(f.get("query") or "")),
    }
    return done, dismissed, events, app


def on_turn(user, scope, done=(), dismissed=None, events=(), applicable=None, now=None, db=None, shared_db=None, rules=None):
    """Update compliance state, choose the rule(s) for this reply. Returns {"id":"duty_rules","severity":"critical","rules":[...]} or {}."""
    if not user or not enabled():
        return {}
    now = time.time() if now is None else now
    done, dismissed, events, applicable = set(done), dict(dismissed or {}), set(events), dict(applicable or {})
    n_esc, per_turn, snooze, max_pin = int(cfg("escalate_after")), int(cfg("per_turn")), int(cfg("snooze_turns")), int(cfg("max_pinned"))
    scope = (scope or "")[:40]
    c = None
    try:
        c = _db(db)
        c.execute("begin immediate")
        r = c.execute("select turn_n, rr from dr_scope where user=? and scope=?", (user, scope)).fetchone() or (0, 0)
        turn_n, rr = r[0] + 1, r[1]
        rows = {}
        for d in DUTIES:
            x = c.execute("select shown, ignored, done_n, pending, pinned, last_shown_turn, last_shown_t, snooze_until from dr_duty where user=? and scope=? and duty=?", (user, scope, d)).fetchone()
            rows[d] = dict(zip(("shown", "ignored", "done_n", "pending", "pinned", "last_shown_turn", "last_shown_t", "snooze_until"), x)) if x else \
                {"shown": 0, "ignored": 0, "done_n": 0, "pending": 0, "pinned": 0, "last_shown_turn": -10 ** 6, "last_shown_t": 0.0, "snooze_until": 0}
        for d in DUTIES:
            s = rows[d]
            if d not in done and d in ("cube", "vote") and s["pending"] and external_done(user, d, s["last_shown_t"], shared_db):
                done.add(d)
            if d in done:
                s.update(ignored=0, pinned=0, pending=0, done_n=s["done_n"] + 1)
            elif d in dismissed:
                s.update(ignored=0, pinned=0, pending=0, snooze_until=turn_n + snooze)
            else:
                if s["pending"]:
                    if s["pending"] == 2 or applicable.get(d):
                        s["ignored"] += 1
                    s["pending"] = 0
                if s["pinned"] and d in ("l1", "l2") and not applicable.get(d) and d not in events:
                    s.update(ignored=0, pinned=0)       # covered another way (e.g. server fallback): back to soft
                if s["ignored"] >= n_esc:
                    s["pinned"] = 1
        shown = []
        for d in DUTIES:   # pinned first (MANDATORY), at most max_pinned
            if rows[d]["pinned"] and d not in done and d not in dismissed and len(shown) < max_pin:
                shown.append(d)
        npin = len(shown)
        extra = 2 if npin == 0 else 1   # with pinned MANDATORY rules: at most one more
        for d in DUTIES:   # event matched (at most 2 non-pinned rules per reply)
            if d in events and d not in shown and d not in done and d not in dismissed and rows[d]["snooze_until"] <= turn_n and len(shown) < npin + extra:
                shown.append(d)
        if per_turn > 0 and npin == 0 and len(shown) < 2:   # round-robin filler: next rule in the cycle
            for i in range(len(DUTIES)):
                d = DUTIES[(rr + i) % len(DUTIES)]
                if d in shown or d in done or d in dismissed or rows[d]["snooze_until"] > turn_n:
                    continue
                shown.append(d); rr = (rr + i + 1) % len(DUTIES)
                break
        out = []
        for d in shown:
            s = rows[d]
            s.update(shown=s["shown"] + 1, pending=2 if (applicable.get(d) or d in events) else 1, last_shown_turn=turn_n, last_shown_t=now)
            out.append(mandatory_text(d, s["ignored"]) if s["pinned"] else rule_text(d))
        for d in DUTIES:
            s = rows[d]
            c.execute("insert or replace into dr_duty values(?,?,?,?,?,?,?,?,?,?,?)",
                      (user, scope, d, s["shown"], s["ignored"], s["done_n"], s["pending"], s["pinned"], s["last_shown_turn"], s["last_shown_t"], s["snooze_until"]))
        c.execute("insert or replace into dr_scope values(?,?,?,?)", (user, scope, turn_n, rr))
        c.execute("commit")
        return {"id": "duty_rules", "severity": "critical", "rules": out} if out else {}
    except Exception as e:
        try:
            c.execute("rollback")
        except Exception:
            pass
        print("[duty_rules] skipped: %s" % type(e).__name__, flush=True)
        return {}
    finally:
        if c is not None:
            c.close()


def stats(user, scope=None, db=None):
    """Debug/ops: per duty counters for an account (no secrets)."""
    c = _db(db)
    try:
        q = "select scope, duty, shown, ignored, done_n, pinned from dr_duty where user=?" + (" and scope=?" if scope else "")
        return [dict(zip(("scope", "duty", "shown", "ignored", "done", "pinned"), r)) for r in c.execute(q, (user, scope) if scope else (user,))]
    finally:
        c.close()
