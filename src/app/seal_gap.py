"""Journal check for a seal already on a previous answer.

A seal is fresh only when this account's journal issued that n and code for
this clean text. Missing, a repeated n, or a code the journal did not issue
is an unsealed_gap: the answer text is still saved by the caller, the row is
marked here, and a duty stays until a later recap of that same text or
duty=unsealed_gap_nothing.

turns_no_seal is a different metric (this turn's draft had no seal and the
server asked for a revise). This module does not bump it.

The mark lives in this sidecar, not on the memory topic. topic=recap stays
recap so cube duties do not fire.

Env (tests point these at temp files; never the production log):
  SKV_SEAL_LOG     default /data/skv/skv_seals.log
  SKV_SEAL_GAP_DB  default /data/skv/metadata_store/seal_gap.db
"""
import hashlib
import json
import os
import re
import sqlite3
import time

DEFAULT_LOG = "/data/skv/skv_seals.log"
DEFAULT_DB = "/data/skv/metadata_store/seal_gap.db"
DUTY_ID = "unsealed_gap"
CLOSE_DUTY = "unsealed_gap_nothing"
PIN = "previous answer sent without seal: send recap"

_SEAL_RX = re.compile(r"(?:🔐\s*)?SKV\s*\|\s*#(\d+)\s*·\s*([0-9a-fA-F]{4})")
_STRIP_RX = re.compile(r"\n?🔐?\s*SKV\s*\|\s*#[^\n]*")
_sync_key = None


def log_path():
    return os.environ.get("SKV_SEAL_LOG") or DEFAULT_LOG


def db_path():
    return os.environ.get("SKV_SEAL_GAP_DB") or DEFAULT_DB


def scope(user, agent_token=""):
    """Same shape as turn_watch_rest.scope: account plus a hash of the token. The raw token is not stored."""
    user = user or "env"
    token = agent_token or ""
    if not token:
        return user
    return user + "#" + hashlib.sha256(token.encode()).hexdigest()[:10]


def strip_seals(text):
    return _STRIP_RX.sub("", text or "").rstrip()


def text_hash(text):
    return hashlib.sha256(strip_seals(text).encode("utf-8")).hexdigest()


def parse_seal(text):
    """Last SKV seal in the text: (n, code) or None. The code is 4 hex."""
    found = list(_SEAL_RX.finditer(text or ""))
    if not found:
        return None
    m = found[-1]
    return int(m.group(1)), m.group(2).lower()


def _connect():
    path = db_path()
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        return None
    c = sqlite3.connect(path, timeout=10)
    c.execute(
        "create table if not exists seal_journal("
        "user text not null, n integer not null, code text not null, text_hash text not null default '',"
        "event_id text default '', t integer, via text default '',"
        "primary key (user, n, text_hash))"
    )
    c.execute(
        "create table if not exists unsealed_gap("
        "scope text not null, text_hash text not null, ref text default '', reason text default '',"
        "event_id text default '', t integer, closed integer default 0,"
        "primary key (scope, text_hash))"
    )
    c.execute(
        "create table if not exists unsealed_counter(scope text primary key, total integer not null default 0)"
    )
    return c


def _sync_log(c):
    """Fold the append-only log into the table. Old lines have no text_hash. Never raises."""
    global _sync_key
    path = log_path()
    try:
        st = os.stat(path)
    except OSError:
        return
    key = (path, getattr(st, "st_mtime_ns", st.st_mtime), st.st_size)
    if _sync_key == key:
        return
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                user = str(o.get("user") or "")
                try:
                    n = int(o.get("seal") if o.get("seal") is not None else o.get("n"))
                except (TypeError, ValueError):
                    continue
                code = str(o.get("code") or "").lower()[:4]
                if not user or not code or len(code) != 4:
                    continue
                th = str(o.get("text_hash") or "")
                c.execute(
                    "insert or ignore into seal_journal(user, n, code, text_hash, event_id, t, via) values(?,?,?,?,?,?,?)",
                    (user, n, code, th, str(o.get("event_id") or ""), int(o.get("t") or 0), str(o.get("via") or "")),
                )
        c.commit()
        st2 = os.stat(path)
        _sync_key = (path, getattr(st2, "st_mtime_ns", st2.st_mtime), st2.st_size)
    except Exception:
        return


def _rows(c, user, n):
    _sync_log(c)
    return c.execute(
        "select n, code, text_hash, event_id, t from seal_journal where user=? and n=? order by t, rowid",
        (user or "", int(n)),
    ).fetchall()


def classify(user, text):
    """ok | missing | repeated | fabricated. ok carries the journal event_id when one was stored."""
    clean = strip_seals(text)
    th = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    parsed = parse_seal(text)
    base = {"status": "missing", "n": None, "code": None, "text_hash": th, "clean": clean, "event_id": "", "plan": "backfill"}
    if not parsed:
        return base
    n, code = parsed
    base["n"] = n
    base["code"] = code
    c = _connect()
    if c is None:
        base["status"] = "fabricated"
        return base
    try:
        rows = _rows(c, user, n)
    except Exception:
        base["status"] = "fabricated"
        return base
    finally:
        try:
            c.close()
        except Exception:
            pass
    if not rows:
        base["status"] = "fabricated"
        return base
    first_n, first_code, first_th, first_eid, _t = rows[0]
    hashed = [r for r in rows if r[2]]
    if first_th:
        if first_th == th and str(first_code).lower() == code:
            base["status"] = "ok"
            base["event_id"] = first_eid or ""
            base["plan"] = "link" if first_eid else "save_existing"
            return base
        base["status"] = "repeated"
        return base
    # Legacy log row: no text hash. Accept only a single row whose code matches.
    if len(rows) == 1 and str(first_code).lower() == code and not hashed:
        base["status"] = "ok"
        base["event_id"] = first_eid or ""
        base["plan"] = "link" if first_eid else "save_existing"
        return base
    base["status"] = "repeated"
    return base


def record_issued(user, n, code, text, event_id="", via="", scope_key=""):
    """Append the log and the table. Never raises. Callers keep their own seal counter."""
    try:
        code = str(code or "").lower()[:4]
        n = int(n)
        if not user or not code or len(code) != 4:
            return
        th = text_hash(text if text is not None else "")
        now = int(time.time())
        c = _connect()
        if c is None:
            return
        try:
            c.execute(
                "insert or ignore into seal_journal(user, n, code, text_hash, event_id, t, via) values(?,?,?,?,?,?,?)",
                (str(user), n, code, th, str(event_id or ""), now, str(via or "")),
            )
            if event_id:
                c.execute(
                    "update seal_journal set event_id=? where user=? and n=? and text_hash=? and coalesce(event_id,'')=''",
                    (str(event_id), str(user), n, th),
                )
            c.commit()
        finally:
            c.close()
        rec = {"t": now, "user": str(user), "seal": n, "code": code, "event_id": str(event_id or ""), "via": str(via or ""), "text_hash": th}
        if scope_key:
            rec["scope"] = scope_key
        path = log_path()
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        return


def attach_event(user, n, th, event_id):
    """Fill event_id on an existing journal row. Does not mint a new n."""
    try:
        if not event_id:
            return
        c = _connect()
        if c is None:
            return
        try:
            c.execute(
                "update seal_journal set event_id=? where user=? and n=? and text_hash=? and coalesce(event_id,'')=''",
                (str(event_id), str(user or ""), int(n), str(th or "")),
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        return


def total(scope_key):
    try:
        c = _connect()
        if c is None:
            return 0
        try:
            r = c.execute("select total from unsealed_counter where scope=?", (scope_key,)).fetchone()
            return int(r[0]) if r else 0
        finally:
            c.close()
    except Exception:
        return 0


def totals_for_user(user):
    """Sum every agent scope of this account. turn_stats has no token."""
    user = user or "env"
    try:
        c = _connect()
        if c is None:
            return 0
        try:
            rows = c.execute("select scope, total from unsealed_counter").fetchall()
        finally:
            c.close()
        n = 0
        prefix = user + "#"
        for sc, tot in rows:
            if sc == user or str(sc).startswith(prefix):
                n += int(tot or 0)
        return n
    except Exception:
        return 0


def _open_rows(c, scope_key):
    return c.execute(
        "select text_hash, ref, reason from unsealed_gap where scope=? and closed=0 order by t, rowid",
        (scope_key,),
    ).fetchall()


def _close_hash(c, scope_key, th):
    c.execute("update unsealed_gap set closed=1 where scope=? and text_hash=? and closed=0", (scope_key, th))


def _duty(rows):
    if not rows:
        return None
    refs = []
    for th, ref, reason in rows:
        label = ref or th[:8]
        refs.append("%s (%s)" % (label, reason or "unsealed"))
    return {
        "id": DUTY_ID,
        "kind": DUTY_ID,
        "severity": "critical",
        "n": len(rows),
        "pin": PIN,
        "refs": refs[:20],
        "do": PIN + ". Close: send a recap of that answer on a later turn, or duty=%s." % CLOSE_DUTY,
    }


def observe(user, agent_token, items, duty="", duty_reason=""):
    """Classify each previous answer. Open a gap once per new text. A later sight of the same text closes it.

    The detecting call does not close the rows it just opened. duty=unsealed_gap_nothing closes
    whatever is still open after that, including rows opened on this call, and the duty is omitted
    when nothing remains. The counter still counts each newly opened answer.
    """
    scope_key = scope(user, agent_token)
    out = {"unsealed_gaps": 0, "unsealed_gaps_total": total(scope_key), "duty": None, "results": [], "scope": scope_key}
    try:
        c = _connect()
        if c is None:
            return out
        try:
            pre = {r[0] for r in _open_rows(c, scope_key)}
            opened_now = set()
            new_n = 0
            results = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or item.get("answer") or "")
                ref = str(item.get("ref") or "")
                if not text.strip():
                    continue
                cl = classify(user, text)
                th = cl["text_hash"]
                results.append({"ref": ref, **cl})
                if cl["status"] == "ok":
                    if th in pre:
                        _close_hash(c, scope_key, th)
                        pre.discard(th)
                    continue
                if th in pre:
                    _close_hash(c, scope_key, th)
                    pre.discard(th)
                    continue
                if th in opened_now:
                    continue
                existed = c.execute(
                    "select closed from unsealed_gap where scope=? and text_hash=?",
                    (scope_key, th),
                ).fetchone()
                if existed:
                    continue
                c.execute(
                    "insert into unsealed_gap(scope, text_hash, ref, reason, event_id, t, closed) values(?,?,?,?,?,?,0)",
                    (scope_key, th, ref[:80], cl["status"], str(item.get("event_id") or ""), int(time.time())),
                )
                c.execute(
                    "insert into unsealed_counter(scope, total) values(?,1) on conflict(scope) do update set total=total+1",
                    (scope_key,),
                )
                opened_now.add(th)
                new_n += 1
            reason = str(duty_reason or "")
            if reason:
                for th, ref, _why in list(_open_rows(c, scope_key)):
                    if ref and ref in reason:
                        _close_hash(c, scope_key, th)
            if str(duty or "") == CLOSE_DUTY:
                c.execute("update unsealed_gap set closed=1 where scope=? and closed=0", (scope_key,))
            c.commit()
            left = _open_rows(c, scope_key)
            out["results"] = results
            out["unsealed_gaps"] = new_n
            out["unsealed_gaps_total"] = total(scope_key)
            out["duty"] = _duty(left)
            return out
        finally:
            c.close()
    except Exception:
        return out
