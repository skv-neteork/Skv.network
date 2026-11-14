"""Adaptive turn-response diet (SKV MCP).

FULL mode (unchanged schema) for: verbose=true, the first turn of a session, and every non-MCP client
(REST / Guard / extension never pass through here). COMPACT mode for MCP agents with the constitution
installed after their first turn: empty fields, static boilerplate and repeated items are dropped; seal,
verdict, saved, event_id, relevant facts/cubes, real duties and targeted second_look always stay.
All cuts are switchable in CFG_PATH (JSON, re-read on mtime change). Never raises: on any error the
response is returned untouched (= full mode)."""
import hashlib
import json
import os
import re
import sqlite3
import time

CFG_PATH = os.environ.get("SKV_TURN_DIET_CFG", "/data/skv/turn_diet.json")
DEFAULTS = {
    "enabled": True,                 # master switch for compact mode (off = full mode everywhere)
    "session_idle_min": 60,          # a new session starts after this idle gap (or step_zero page 1)
    "omit_empty": ["facts", "cubes", "duties", "cited_ok", "supersedes", "seal_warning", "board"],
    "drop_static_self_check": True,  # self_check only when the draft triggers one
    "drop_profile_check": True,
    "profile_full_on_change": True,  # all relevant rows at session start / profile_version change
    "profile_digest": True,          # plan #3: ~80-token capsule every compact turn
    "profile_digest_chars": 320,
    "profile_rel_max": 2,            # plan #3: 1-2 rows that really match this message
    "board_changes_only": True,
    "stale_once_per_session": True,  # all modes: board_stale at most once per session...
    "stale_digest_hours": 24,        # ...and at most once per this many hours per account (daily digest)
    "drop_second_look_stats": True,  # moved to the turn_stats tool
    "one_interruption": True,        # plan #4: critical duties + at most one of (second_look, other duty)
    "duty_cooldown_turns": 5,
    "duty_max_shows": 3,
    "duty_expiry_turns": 20,
    "duty_reset_turns": 30,          # T72b: a duty held by max_shows/expiry is allowed again this many turns after its last show
    "overdue_cooldown_turns": 3,     # T72b: l1_overdue (critical) is shown at most this often unless escalated (MANDATORY) or its count moved a bucket
    "throttled_critical": ["l1_overdue"],
    "critical_duties": ["missed_turns", "l1_overdue", "profile_conflict", "profile_candidate", "duty_errors"],  # shown every turn until resolved (seal marks depend on them)
    "caps_check": True,              # plan #1: duties never name a tool/param this client lacks
    "metrics": True,                 # plan #7: per-turn size + confirmed-use log (ids/hashes only)
    # plan items kept OFF until the metric baseline exists:
    "ranked_briefing": False,        # #2 ranked items[] under a budget
    "briefing_budget_tokens": 350,
    "draft_second_look": False,      # #5 claim/evidence/fix checks with risk gating (not implemented yet)
    "cubes_only_relevant": False,    # #6 cubes only at a decision point (here: only when new this session)
}
_C = {"m": None, "v": dict(DEFAULTS)}


def cfg(k):
    try:
        m = os.path.getmtime(CFG_PATH)
        if m != _C["m"]:
            with open(CFG_PATH) as fh:
                d = json.load(fh)
            v = dict(DEFAULTS)
            v.update({a: b for a, b in d.items() if a in DEFAULTS})
            _C.update(m=m, v=v)
    except Exception:
        pass
    return _C["v"].get(k, DEFAULTS.get(k))


def _db(path):
    c = sqlite3.connect(path, timeout=10)
    c.execute("create table if not exists diet_sess(user text, session text, turns int, last_t real, prof_v text, board_sig text, stale_sig text, cubes_sig text, last_facts text, primary key(user, session))")
    c.execute("create table if not exists diet_user(user text primary key, stale_t real, stale_sig text, reset_t real, turns int default 0)")
    c.execute("create table if not exists diet_duty(user text, k text, shows int, last_turn int, first_turn int, primary key(user, k))")
    try:
        c.execute("alter table diet_duty add column sig text")
    except sqlite3.OperationalError:
        pass
    c.execute("create table if not exists diet_metrics(t real, user text, mode text, tokens int, sections text, facts int, cited int, used_prev int)")
    return c


def _h(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:10]


def _tok(x):
    return max(1, len(json.dumps(x, ensure_ascii=False, default=str)) // 4)


def session_reset(path, user):
    """step_zero page 1 = a new session for every session_id of this account."""
    try:
        c = _db(path)
        c.execute("insert into diet_user(user, reset_t) values(?,?) on conflict(user) do update set reset_t=excluded.reset_t", (user, time.time()))
        c.commit(); c.close()
    except Exception:
        pass


def session(path, user, sid):
    """-> (is_first_turn, row dict). Does not write."""
    c = _db(path)
    r = c.execute("select turns, last_t, prof_v, board_sig, stale_sig, cubes_sig, last_facts from diet_sess where user=? and session=?", (user, sid)).fetchone()
    u = c.execute("select reset_t from diet_user where user=?", (user,)).fetchone()
    c.close()
    if not r:
        return True, {}
    d = dict(zip(("turns", "last_t", "prof_v", "board_sig", "stale_sig", "cubes_sig", "last_facts"), r))
    idle = time.time() - (d["last_t"] or 0) > float(cfg("session_idle_min")) * 60
    reset = bool(u and u[0] and u[0] > (d["last_t"] or 0))
    return (idle or reset), d


def stale_gate(path, user, sid, stale):
    """board_stale (all modes): compare ids only, once per session, at most once per stale_digest_hours per account."""
    try:
        if not stale:
            return False
        sig = _h(sorted(str(x.get("id") if isinstance(x, dict) else x) for x in stale))
        now = time.time()
        c = _db(path)
        first, d = session(path, user, sid)
        u = c.execute("select stale_t, stale_sig from diet_user where user=?", (user,)).fetchone() or (0, None)
        show = True
        if cfg("stale_once_per_session") and not first and d.get("stale_sig") == sig:
            show = False
        if show and u[0] and now - u[0] < float(cfg("stale_digest_hours")) * 3600 and u[1] == sig:
            show = False
        if show:
            c.execute("insert into diet_user(user, stale_t, stale_sig) values(?,?,?) on conflict(user) do update set stale_t=excluded.stale_t, stale_sig=excluded.stale_sig", (user, now, sig))
            c.execute("insert into diet_sess(user, session, turns, last_t, stale_sig) values(?,?,0,?,?) on conflict(user, session) do update set stale_sig=excluded.stale_sig", (user, sid, d.get("last_t") or 0, sig))
            c.commit()
        c.close()
        return show
    except Exception:
        return True


_REF_RX = re.compile(r"\b([a-z_][a-z0-9_]{3,})\s*\(")
_PARAM_RX = re.compile(r"\b([a-z_][a-z0-9_]{2,})\s*=")
_REWRITE = {"memory_remember": "turn"}


def caps_fix(duties, tools, params):
    """Plan #1: a duty must not name a tool or turn param this client does not have. Known renames are
    rewritten (memory_remember( -> turn( ); unknown names are listed in unsupported, never silently kept."""
    out = []
    for d in duties:
        s = json.dumps(d, ensure_ascii=False)
        for old, new in _REWRITE.items():
            if old not in tools and old in s:
                s = s.replace(old + "(", new + "(").replace(old, new)
        try:
            d2 = json.loads(s)
        except Exception:
            d2 = d
        txt = json.dumps(d2, ensure_ascii=False)
        bad = sorted({m for m in _REF_RX.findall(txt) if "_" in m and m not in tools and m not in params})
        if bad and isinstance(d2, dict):
            d2["unsupported"] = bad
        out.append(d2)
    return out


def _dkey(d):
    if isinstance(d, dict):
        k = d.get("id") or d.get("kind")
        if k:
            return str(k) + ("|" + str(d.get("n")) if d.get("kind") == "missed_turns" else "")
        return "keys:" + ",".join(sorted(map(str, d.keys())))
    return "txt:" + re.sub(r"[\d\s]+", "", json.dumps(d, ensure_ascii=False))[:60]


def _critical(d):
    cr = set(cfg("critical_duties") or [])
    if isinstance(d, dict):
        return (d.get("id") in cr) or (d.get("kind") in cr) or d.get("severity") == "critical"
    return False


def _dsig(d):
    """State signature of a duty: its first number (due count) in buckets of 10. A new bucket = new state = show again."""
    txt = " ".join(str(d.get(k)) for k in ("do", "n", "l1_pending", "pending") if d.get(k) is not None) if isinstance(d, dict) else str(d)
    m = re.search(r"\d+", txt)
    return str(int(m.group()) // 10) if m else ""


def _escalated(d):
    return isinstance(d, dict) and str(d.get("do") or d.get("rule") or "").startswith("MANDATORY")


def gate_duties(c, user, turn_no, duties, has_check, scope=""):
    """Plan #4: dedupe + cooldown + max shows + expiry for non-critical duties; one interruption per turn.
    T72b: state is per account+scope (session); a held duty comes back after duty_reset_turns without a show or when its state signature
    (due count bucket) changes; throttled critical duties (l1_overdue) repeat at most every overdue_cooldown_turns unless escalated."""
    show, held = [], 0
    one = bool(cfg("one_interruption"))
    budget = 0 if (one and has_check) else (1 if one else 10 ** 6)
    uk = user + ("#" + scope if scope else "")
    thr = set(cfg("throttled_critical") or [])
    for d in duties:
        k = _dkey(d)
        sig = _dsig(d)
        r = c.execute("select shows, last_turn, first_turn, sig from diet_duty where user=? and k=?", (uk, k)).fetchone()
        shows, last, first = (r[:3] if r else (0, -10 ** 6, turn_no))
        if _critical(d):
            if k in thr and r and not _escalated(d) and sig == (r[3] or "") and turn_no - last < int(cfg("overdue_cooldown_turns")):
                held += 1; continue
            show.append(d)
            c.execute("insert or replace into diet_duty(user,k,shows,last_turn,first_turn,sig) values(?,?,?,?,?,?)", (uk, k, shows + 1, turn_no, first, sig)); continue
        if r and (sig != (r[3] or "") or turn_no - last >= int(cfg("duty_reset_turns"))):
            shows, last, first, r = 0, -10 ** 6, turn_no, None   # state moved on or long quiet: a fresh start
        if r and turn_no - first > int(cfg("duty_expiry_turns")):
            held += 1; continue
        if shows >= int(cfg("duty_max_shows")) or turn_no - last < int(cfg("duty_cooldown_turns")) or budget <= 0:
            held += 1
            if not r:
                c.execute("insert or replace into diet_duty(user,k,shows,last_turn,first_turn,sig) values(?,?,?,?,?,?)", (uk, k, 0, -10 ** 6, turn_no, sig))
            continue
        budget -= 1
        show.append(d)
        c.execute("insert or replace into diet_duty(user,k,shows,last_turn,first_turn,sig) values(?,?,?,?,?,?)", (uk, k, shows + 1, turn_no, first, sig))
    return show, held


_PAST = re.compile(r"\b(earlier|before|last time|previously|you said|we decided|as agreed|раньше|ранее|прошл\w+|в прошлый раз|ты говорил\w*|мы решили|договорились)\b", re.I)


def triggered_self_check(draft, checklist, cubes_sent, has_slq):
    """Only the checklist items the draft actually triggers."""
    out = []
    if not has_slq and draft and _PAST.search(draft) and "[ev:" not in draft and len(checklist) > 1:
        out.append(checklist[1])
    if cubes_sent and len(checklist) > 4:
        out.append(checklist[4])
    return out


def apply(path, resp, ctx):
    """resp: the full-mode dict. ctx: user, session, verbose, eligible, draft, checklist, slq(bool), prof_extra, tools, params.
    Returns (resp, mode). Writes session state + metrics. Never raises."""
    mode = "full"
    try:
        user, sid = ctx["user"], ctx.get("session") or "mcp"
        first, st = session(path, user, sid)
        c = _db(path)
        ur = c.execute("select turns from diet_user where user=?", (user,)).fetchone()
        turn_no = int((ur or [0])[0] or 0) + 1   # account-wide counter: duty cooldowns survive session changes
        if cfg("caps_check") and resp.get("duties"):
            resp["duties"] = caps_fix(resp["duties"], ctx.get("tools") or set(), ctx.get("params") or set())
        full_tok = _tok(resp)
        compact = bool(cfg("enabled")) and ctx.get("eligible") and not ctx.get("verbose") and not first and resp.get("verdict") == "pass"
        pe = ctx.get("prof_extra") or {}
        prof_v = resp.get("profile_version") or pe.get("profile_version")
        if compact:
            mode = "compact"
            ds = resp.get("duties") or []
            if any(isinstance(d, dict) and d.get("id") == "l1_overdue" for d in ds):   # same L1 ask twice (summary_due copy)
                resp["duties"] = [d for d in ds if not (isinstance(d, dict) and "l1_source_event_ids" in d and d.get("id") != "l1_overdue")]
            if resp.get("duties"):
                resp["duties"], held = gate_duties(c, user, turn_no, resp["duties"], bool(ctx.get("slq")), sid)
                if held:
                    resp["duties_held"] = held
            sd = resp.get("summary_due")   # T72b: l1_overdue (throttled) carries the overdue L1 ask; do not repeat it in summary_due every turn
            if isinstance(sd, dict) and int(sd.get("l1_pending") or 0) >= 20:
                sd = {k: v for k, v in sd.items() if k not in ("l1", "l1_pending", "l1_source_event_ids")}
                if sd: resp["summary_due"] = sd
                else: resp.pop("summary_due", None)
            if cfg("drop_static_self_check"):
                sc = triggered_self_check(ctx.get("draft") or "", ctx.get("checklist") or [], bool(resp.get("cubes")), bool(ctx.get("slq")))
                if sc:
                    resp["self_check"] = sc
                else:
                    resp.pop("self_check", None)
            if cfg("drop_profile_check"):
                resp.pop("profile_check", None)
            if not (cfg("profile_full_on_change") and prof_v and prof_v != st.get("prof_v")):
                rel = pe.get("profile_strict") or []
                resp["profile"] = rel[:int(cfg("profile_rel_max"))]
                if cfg("profile_digest") and pe.get("profile_digest"):
                    resp["profile_digest"] = pe["profile_digest"]
                resp.pop("profile_version", None) if prof_v == st.get("prof_v") else None
            if cfg("board_changes_only") and resp.get("board") is not None:
                bs = _h([(b.get("id"), b.get("status")) if isinstance(b, dict) else b for b in resp.get("board") or []])
                if bs == st.get("board_sig") and not resp.get("board_hint"):
                    resp.pop("board", None)
                st["board_sig"] = bs
            if cfg("cubes_only_relevant") and resp.get("cubes"):
                cs = _h([x.get("cube_id") for x in resp["cubes"]])
                if cs == st.get("cubes_sig"):
                    resp.pop("cubes", None)
                st["cubes_sig"] = cs
            if cfg("ranked_briefing") and resp.get("facts"):
                b, keep = int(cfg("briefing_budget_tokens")), []
                for f in resp["facts"]:
                    if _tok(keep + [f]) > b and keep:
                        break
                    keep.append(f)
                resp["facts"] = keep
            if cfg("drop_second_look_stats"):
                resp.pop("second_look_stats", None)
            for k in list(cfg("omit_empty") or []) + ["profile", "profile_duties", "profile_warning"]:
                if k in resp and resp[k] in (None, [], {}, ""):
                    resp.pop(k)
            if not resp.get("board") and not resp.get("board_hint"):
                resp.pop("board", None)
        elif "board" in resp and resp.get("board") is not None:
            st["board_sig"] = _h([(b.get("id"), b.get("status")) if isinstance(b, dict) else b for b in resp.get("board") or []])
        if resp.get("verdict") == "pass":
            facts_ids = [f.get("ev") for f in (ctx.get("facts") or []) if isinstance(f, dict)]
            c.execute("insert into diet_sess(user, session, turns, last_t, prof_v, board_sig, stale_sig, cubes_sig, last_facts) values(?,?,?,?,?,?,?,?,?) "
                      "on conflict(user, session) do update set turns=excluded.turns, last_t=excluded.last_t, prof_v=coalesce(excluded.prof_v, diet_sess.prof_v), "
                      "board_sig=excluded.board_sig, cubes_sig=excluded.cubes_sig, last_facts=excluded.last_facts",
                      (user, sid, 1 if first else int(st.get("turns") or 0) + 1, time.time(), prof_v, st.get("board_sig"), st.get("stale_sig"), st.get("cubes_sig"), json.dumps(facts_ids)))
            c.execute("insert into diet_user(user, turns) values(?,?) on conflict(user) do update set turns=excluded.turns", (user, turn_no))
            if cfg("metrics"):
                prev = set(json.loads(st.get("last_facts") or "[]")) if not first else set()
                cited = set(ctx.get("cited") or [])
                secs = {k: _tok(v) for k, v in resp.items()}
                secs["_full_tokens"] = full_tok
                c.execute("insert into diet_metrics values(?,?,?,?,?,?,?,?)", (time.time(), _h(user), mode, _tok(resp), json.dumps(secs),
                                                                            len(facts_ids), len(cited), len(cited & prev)))
        c.commit(); c.close()
    except Exception:
        pass
    return resp, mode


def stats(path, user, days=1.0):
    """Plan #7 baseline: tokens per turn by mode, confirmed use of facts sent on the previous turn."""
    try:
        c = _db(path)
        rows = c.execute("select mode, tokens, facts, cited, used_prev, sections from diet_metrics where user=? and t>?", (_h(user), time.time() - days * 86400)).fetchall()
        c.close()
        out = {}
        for mode, tk, f, ci, up, secs in rows:
            o = out.setdefault(mode, {"turns": 0, "tokens": 0, "facts_sent": 0, "cited": 0, "used_prev_facts": 0, "sections": {}})
            o["turns"] += 1; o["tokens"] += tk; o["facts_sent"] += f; o["cited"] += ci; o["used_prev_facts"] += up
            for k, v in json.loads(secs or "{}").items():
                o["sections"][k] = o["sections"].get(k, 0) + v
        for o in out.values():
            n = max(1, o["turns"])
            o["avg_tokens"] = round(o["tokens"] / n)
            o["confirmed_upt_per_1k"] = round(1000.0 * o["used_prev_facts"] / max(1, o["tokens"]), 3)
            o["avg_full_equivalent_tokens"] = round(o["sections"].get("_full_tokens", 0) / n)
            o["sections"] = {k: round(v / n) for k, v in sorted(o["sections"].items(), key=lambda x: -x[1])[:12] if k != "_full_tokens"}
        return out
    except Exception as e:
        return {"error": str(e)[:200]}
