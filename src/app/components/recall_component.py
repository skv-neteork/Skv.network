"""Spontaneous recall as a pluggable component on the recall_later core.

The turn never waits. trigger() decides, run() queues a recall_later job,
and the next turn reads outputs. The keyword sidecar stays the fallback
when this component is off. SKV_RECALL_COMPONENT=0 turns it off.
"""
import hashlib
import json
import os
import re
import sqlite3
import time

from app.components.registry import register

_DEFAULT_DB = "/data/skv/metadata_store/recall_component.db"
NAME = "recall"
VERSION = "2"


class RecallComponent:
    name = NAME
    version = VERSION

    def enabled(self):
        return enabled()

    def trigger(self, state):
        return should_trigger(state)

    def run(self, state):
        return launch(state)

    def outputs(self, user, topic=""):
        return collect(user, topic)


def enabled():
    # SKV_RECALL_COMPONENT=0 turns the background recall off and leaves the keyword sidecar.
    return os.environ.get("SKV_RECALL_COMPONENT", "1").strip().lower() not in ("0", "off", "false", "no")


def every():
    try:
        n = int(os.environ.get("SKV_RECALL_COMPONENT_EVERY", "5") or 5)
    except (TypeError, ValueError):
        n = 5
    return max(1, n)


def job_cap():
    try:
        return float(os.environ.get("SKV_RECALL_JOB_CAP", "0.2") or 0.2)
    except (TypeError, ValueError):
        return 0.2


def day_cap():
    try:
        return float(os.environ.get("SKV_RECALL_DAY_CAP", "1") or 1)
    except (TypeError, ValueError):
        return 1.0


def min_gap():
    """Seconds between recall jobs for one user. 0 disables the gap (tests)."""
    try:
        return float(os.environ.get("SKV_RECALL_MIN_GAP", "60") or 0)
    except (TypeError, ValueError):
        return 60.0


def _path():
    return os.environ.get("SKV_RECALL_COMPONENT_DB") or _DEFAULT_DB


def user_key(uid):
    return hashlib.sha256((uid or "").encode()).hexdigest()[:16]


def _conn():
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=5)
    c.execute("""CREATE TABLE IF NOT EXISTS rc_state (
        user TEXT PRIMARY KEY, turns INTEGER, last_topic TEXT, last_sched INTEGER, skips INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS rc_job (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, job_id TEXT, created_at REAL,
        exclude_json TEXT, status TEXT, reserve REAL, delivered_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS rc_seen (
        user TEXT, ev TEXT, delivered_at REAL, PRIMARY KEY (user, ev)
    )""")
    return c


def _topic(text):
    try:
        from app.spontaneous_recall import scrub, topic_of
        return topic_of(scrub(text or ""))
    except Exception:
        return " ".join((text or "").split()[:8])[:200]


def should_trigger(state):
    """Every N turns, a topic change, or a new L1."""
    turns = int(state.get("turns") or 0)
    last = int(state.get("last_sched") or 0)
    topic = (state.get("topic") or "").strip()
    prev = (state.get("last_topic") or "").strip()
    changed = bool(prev) and bool(topic) and topic != prev
    return (turns - last) >= every() or bool(state.get("l1_new")) or changed


def _spent(c, user):
    start = time.time() - 86400
    row = c.execute(
        "SELECT coalesce(sum(reserve),0) FROM rc_job WHERE user=? AND created_at>?",
        (user, start),
    ).fetchone()
    return float(row[0] or 0)


def _shelf_exists(uid):
    """Do not create an account database just to look for a recall job."""
    try:
        from app.memory_v2 import db_path
        path = db_path(uid)
        return bool(path and os.path.isfile(path))
    except Exception:
        return False


def _statements(message, topic):
    """One search form. Secrets are scrubbed before anything is stored or queued."""
    raw = _scrub(message or topic or "").strip().rstrip("?").strip()
    if not raw or raw == "[secret]":
        blob = _scrub(topic or message or "")
        raw = "прошлые решения по этой теме" if re.search(r"[А-Яа-яЁё]", blob) else "past decisions on this topic"
    return [raw[:160]]


def launch(state, submit_fn=None):
    """Queue one recall_later job. Returns the job id or None. Does not wait.

    The day cap is reserved inside BEGIN IMMEDIATE before the job is submitted,
    so parallel turns cannot each pass the check. A second job inside min_gap
    seconds is not started. A failed submit refunds the reserve.
    """
    uid = state.get("uid") or ""
    user = user_key(uid)
    if not uid or not enabled() or not _shelf_exists(uid):
        return None
    cap = job_cap()
    c = _conn()
    rowid = None
    forms = None
    query = ""
    extra = {}
    try:
        c.execute("BEGIN IMMEDIATE")
        topic_s = _scrub(state.get("topic") or "")
        turns = int(state.get("turns") or 0)
        if _spent(c, user) + cap > day_cap() + 1e-9:
            c.execute(
                "INSERT INTO rc_state (user, turns, last_topic, last_sched, skips) VALUES (?,?,?,?,1) "
                "ON CONFLICT(user) DO UPDATE SET skips=coalesce(rc_state.skips,0)+1",
                (user, turns, topic_s, turns),
            )
            c.commit()
            return None
        gap = min_gap()
        if gap > 0:
            recent = c.execute(
                "SELECT 1 FROM rc_job WHERE user=? AND created_at>? LIMIT 1",
                (user, time.time() - gap),
            ).fetchone()
            if recent:
                c.execute(
                    "INSERT INTO rc_state (user, turns, last_topic, last_sched, skips) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(user) DO UPDATE SET turns=excluded.turns, last_topic=excluded.last_topic",
                    (user, turns, topic_s, int(state.get("last_sched") or 0), int(state.get("skips") or 0)),
                )
                c.commit()
                return None
        forms = _statements(state.get("message"), state.get("topic"))
        query = forms[0]
        if state.get("since"):
            extra["since"] = state.get("since")
        if state.get("until"):
            extra["until"] = state.get("until")
        excluded = [x for x in (state.get("exclude") or []) if x]
        if excluded:
            extra["exclude_event"] = excluded[-1]
        c.execute(
            "INSERT INTO rc_job (user, job_id, created_at, exclude_json, status, reserve, delivered_at) "
            "VALUES (?,?,?,?, 'queued', ?, NULL)",
            (user, "pending", time.time(), json.dumps(list(state.get("exclude") or [])), cap),
        )
        rowid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            "INSERT INTO rc_state (user, turns, last_topic, last_sched, skips) VALUES (?,?,?,?,0) "
            "ON CONFLICT(user) DO UPDATE SET turns=excluded.turns, last_topic=excluded.last_topic, last_sched=excluded.last_sched",
            (user, turns, topic_s, turns),
        )
        c.commit()
    except Exception:
        try:
            c.rollback()
        except Exception:
            pass
        rowid = None
        raise
    finally:
        if rowid is None:
            c.close()
    try:
        if submit_fn is None:
            from app.recall_later import submit as submit_fn
        try:
            jid = submit_fn(uid, query, search_as=forms, cost_cap=cap, **extra)
        except TypeError:
            jid = submit_fn(uid, query, search_as=forms, cost_cap=cap)
        c.execute("UPDATE rc_job SET job_id=? WHERE id=?", (str(jid), rowid))
        c.commit()
        return jid
    except Exception:
        try:
            c.execute("UPDATE rc_job SET reserve=0, status='error' WHERE id=?", (rowid,))
            c.commit()
        except Exception:
            pass
        return None
    finally:
        c.close()


_LEAK_FALLBACK = re.compile(
    r"(?i)\b(?:passwords?|passwds?|secrets?|tokens?|api[\s_-]*keys?)\b\s*(?:is|was|are|=|:)?\s*\S+"
)


def _scrub(text):
    """Same secret drop as spontaneous recall. A failed import still drops the token."""
    try:
        from app.spontaneous_recall import scrub
        return scrub(text or "")
    except Exception:
        return _LEAK_FALLBACK.sub("[secret]", text or "")[:200]


def _tail(eid):
    eid = eid or ""
    return eid.split("::")[-1] if eid else ""


def judge(report, exclude, seen, topic):
    """Keep 1-2 past moments that are on topic and not from this session."""
    try:
        from app.turn_context import on_topic
    except Exception:
        on_topic = lambda topic, text: True
    ex = set()
    for e in exclude or []:
        ex.add(e)
        ex.add(_tail(e))
    evidence = list((report or {}).get("evidence") or [])
    try:
        from app.search_pack import derank_quotes
        evidence = derank_quotes(evidence, id_key="ev")
    except Exception:
        pass
    out = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if not item.get("selected"):
            continue
        eid = item.get("ev") or ""
        tail = _tail(eid)
        if not tail or tail in seen or eid in ex or tail in ex:
            continue
        text = _scrub(item.get("text") or "")
        text = " ".join(text.split())[:200]
        if not text:
            continue
        if topic and not on_topic(topic, text):
            continue
        date = str(item.get("date") or "")[:16]
        why = _scrub(item.get("why") or "")[:160]
        out.append({
            "date": date,
            "ev": tail,
            "text": text,
            "why": why,
            "line": "recalled: %s %s [ev:%s]" % (date, text, tail),
        })
        if len(out) >= 2:
            break
    return out


def _last_job_age(uid):
    try:
        c = _conn()
        row = c.execute(
            "SELECT created_at FROM rc_job WHERE user=? ORDER BY id DESC LIMIT 1",
            (user_key(uid),),
        ).fetchone()
        c.close()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    return max(0.0, time.time() - float(row[0]))


def _clip_recalled(lines, cap=300):
    try:
        from app.turn_diet17 import estimate_tokens
    except Exception:
        return list(lines or [])[:2]
    kept = []
    used = 0.0
    for line in lines or []:
        text = str(line)
        cost = estimate_tokens(text)
        if kept and used + cost > cap:
            break
        if not kept and cost > cap:
            text = text[:400]
            cost = estimate_tokens(text)
        kept.append(text)
        used += cost
    return kept


def collect(user_uid, topic="", get_fn=None):
    """Read finished jobs and return new lines. Marks each ev seen. Never raises."""
    user = user_key(user_uid)
    lines = []
    collect.empty_hit = False
    try:
        c = _conn()
    except Exception:
        return lines
    try:
        rows = c.execute(
            "SELECT id, job_id, exclude_json FROM rc_job WHERE user=? AND status='queued' ORDER BY id",
            (user,),
        ).fetchall()
        seen = {r[0] for r in c.execute("SELECT ev FROM rc_seen WHERE user=?", (user,))}
        if get_fn is None:
            from app.recall_later import get as get_fn
        now = time.time()
        for rid, jid, raw_ex in rows:
            try:
                job = get_fn(user_uid, jid)
            except Exception:
                continue
            if not isinstance(job, dict):
                continue
            status = job.get("status") or ""
            if status not in ("done", "error"):
                continue
            try:
                exclude = json.loads(raw_ex or "[]")
            except Exception:
                exclude = []
            report = job.get("report") if isinstance(job.get("report"), dict) else {}
            picked = judge(report, exclude, seen, topic) if status == "done" else []
            evidence = report.get("evidence") if isinstance(report.get("evidence"), list) else []
            if status == "error" or not picked or not evidence:
                # An empty or failed job must not spend the day cap.
                c.execute(
                    "UPDATE rc_job SET reserve=0, status='delivered', delivered_at=? WHERE id=?",
                    (now, rid),
                )
                collect.empty_hit = True
                continue
            for item in picked:
                ev = item["ev"]
                if ev in seen:
                    continue
                seen.add(ev)
                c.execute(
                    "INSERT OR REPLACE INTO rc_seen (user, ev, delivered_at) VALUES (?,?,?)",
                    (user, ev, now),
                )
                lines.append(item["line"])
            c.execute(
                "UPDATE rc_job SET status='delivered', delivered_at=? WHERE id=?",
                (now, rid),
            )
        c.commit()
    finally:
        c.close()
    if lines:
        collect.empty_hit = False
    return lines[:2]


def _load_state(c, user):
    row = c.execute(
        "SELECT turns, last_topic, last_sched, skips FROM rc_state WHERE user=?",
        (user,),
    ).fetchone()
    if not row:
        return {"turns": 0, "last_topic": "", "last_sched": 0, "skips": 0}
    return {"turns": int(row[0] or 0), "last_topic": row[1] or "", "last_sched": int(row[2] or 0), "skips": int(row[3] or 0)}


def _agent_searched(uid, own_ids):
    if not _shelf_exists(uid):
        return False
    try:
        from app.recall_later import jobs
        now = time.time()
        for row in jobs(uid, limit=5) or []:
            if row.get("job_id") in own_ids:
                continue
            if now - float(row.get("created_at") or 0) < 900 and row.get("status") in ("queued", "running", "done"):
                return True
    except Exception:
        return False
    return False


def agent_has_recent_job(uid, within=300):
    """True when this user already queued a recall inside the window."""
    if not uid or not _shelf_exists(uid):
        return False
    try:
        from app.recall_later import jobs
        now = time.time()
        for row in jobs(uid, limit=5) or []:
            if now - float(row.get("created_at") or 0) < float(within or 0):
                if row.get("status") in ("queued", "running", "done"):
                    return True
    except Exception:
        return False
    return False


def _recent_ids(uid):
    """Newest dialogue ids. A queued job excludes them so it does not echo this chat."""
    try:
        from app.spontaneous_recall import recent_events
        out = []
        for ev in recent_events(uid, limit=8) or []:
            eid = (ev or {}).get("event_id") or ""
            if eid:
                out.append(eid)
        return out
    except Exception:
        return []


def _queue_weak(uid, message, session_ids=None, l1_new=False):
    """Queue one weak-fact job without moving the every-N turn counter."""
    user = user_key(uid)
    c = _conn()
    try:
        st = _load_state(c, user)
    finally:
        c.close()
    age = _last_job_age(uid)
    print("[17g-recall] weak=1 gap_s=%s" % ("none" if age is None else int(age)), flush=True)
    state = {
        "uid": uid,
        "message": message or "",
        "topic": _topic(message),
        "turns": st["turns"],
        "last_topic": st["last_topic"],
        "last_sched": st["last_sched"],
        "skips": st["skips"],
        "l1_new": bool(l1_new),
        "exclude": list(session_ids or []),
    }
    try:
        from app.turn_pack import date_window
        window = date_window(message)
        if window:
            state["since"] = window["since"]
            state["until"] = window["until"]
    except Exception:
        pass
    return launch(state)


def safety_net(result, uid, message="", l1_new=False, session_ids=None):
    """17g after the fact pack. Deliver a finished job, and queue one when the facts the agent sees are empty or weak.

    A saved turn keeps the existing every-N cadence. A context or unsaved turn only queues the weak-fact job, so the cadence is not doubled.
    Search skipped, an empty ack, a directive, or a job the agent already started does not queue another.
    """
    if not isinstance(result, dict) or not uid or not enabled():
        return result
    try:
        from app.turn_diet17 import get_meta
        if not (get_meta() or {}).get("on"):
            return result
    except Exception:
        return result
    skipped = bool(result.get("search_skipped"))
    try:
        from app.turn_diet17 import facts_are_weak, is_directive, is_strict_empty
        weak = facts_are_weak(result.get("facts"))
        meaningful = (
            not is_strict_empty(message)
            and not is_directive(message)
            and len((message or "").split()) >= 2
        )
    except Exception:
        weak = not (result.get("facts") or [])
        meaningful = len((message or "").split()) >= 2
    searched = bool(result.get("agent_searched")) or agent_has_recent_job(uid, 300)
    ids = list(session_ids) if session_ids is not None else _recent_ids(uid)
    saved = result.get("saved") is True and result.get("mode") != "context"
    if not saved:
        on_turn(result, uid, message, l1_new=False, session_ids=ids, launch_ok=False)
        try:
            from app.turn_diet17 import weak_recall_due
            due = weak_recall_due(bool(weak and meaningful), True, _last_job_age(uid), searched, skipped)
        except Exception:
            due = bool(weak and meaningful) and not searched and not skipped
        if due and not _agent_searched(uid, set()):
            try:
                _queue_weak(uid, message, ids, l1_new=l1_new)
            except Exception as exc:
                print("[17g-recall] skipped: %s" % type(exc).__name__, flush=True)
        return result
    return on_turn(
        result, uid, message,
        l1_new=l1_new,
        session_ids=ids,
        searched=searched,
        launch_ok=not searched and not skipped,
        facts_weak=bool(weak and meaningful and not skipped),
        skipped=skipped,
    )


def on_turn(result, uid, message="", l1_new=False, session_ids=None, searched=False, launch_ok=True, facts_weak=False, skipped=False):
    """Deliver ready lines, then maybe queue the next job. Never raises and never blocks on a model."""
    if not isinstance(result, dict) or not uid or not enabled():
        return result
    try:
        topic = _topic(message)
        lines = collect(uid, topic)
        if lines:
            result["recalled"] = _clip_recalled(lines)
        elif getattr(collect, "empty_hit", False):
            result["recalled"] = "nothing recalled"
        # A hint on the turn is not the agent choosing search. facts_weak is the safety net.
        if skipped or not launch_ok or searched:
            return result
        if facts_weak:
            age = _last_job_age(uid)
            try:
                from app.turn_diet17 import weak_recall_due
                due_weak = weak_recall_due(True, True, age, False, False)
            except Exception:
                due_weak = age is None or age >= 300
            if not due_weak:
                facts_weak = False
            else:
                print("[17g-recall] weak=1 gap_s=%s" % ("none" if age is None else int(age)), flush=True)
        user = user_key(uid)
        c = _conn()
        try:
            st = _load_state(c, user)
            st["turns"] = int(st["turns"]) + 1
            state = {
                "uid": uid,
                "message": message,
                "topic": topic,
                "turns": st["turns"],
                "last_topic": st["last_topic"],
                "last_sched": st["last_sched"],
                "l1_new": bool(l1_new),
                "exclude": list(session_ids or []),
            }
            try:
                from app.turn_pack import date_window
                window = date_window(message)
                if window:
                    state["since"] = window["since"]
                    state["until"] = window["until"]
            except Exception:
                pass
            due = should_trigger(state) or bool(facts_weak)
            own = {r[0] for r in c.execute("SELECT job_id FROM rc_job WHERE user=?", (user,))}
            if due and not _agent_searched(uid, own):
                launch(state)
            else:
                c.execute(
                    "INSERT INTO rc_state (user, turns, last_topic, last_sched, skips) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(user) DO UPDATE SET turns=excluded.turns, last_topic=excluded.last_topic",
                    (user, st["turns"], topic or st["last_topic"], st["last_sched"], st["skips"]),
                )
                c.commit()
        finally:
            c.close()
    except Exception as exc:
        print("[recall_component] skipped: %s" % type(exc).__name__, flush=True)
    return result


def apply(result, uid, message="", l1_new=False, session_ids=None, searched=False, launch_ok=True):
    return on_turn(result, uid, message, l1_new, session_ids, searched, launch_ok)


register(RecallComponent())
