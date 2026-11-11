"""Unified cube harvest: every agent publishes proven skills, hooks and new experience as shared cubes.

State is per agent (key_id + agent id), in the account database next to the room tables:
  first prompt  : shown in the identify reply (step 3) the first time an agent identifies.
  reminder      : a turn reply carries one duty, `cube_harvest`, when the interval has passed.
Resolved by duty=cube_harvest, skills_harvest, skills_none or skills_skip, or by a cube the
account created after the prompt. A reminder only: no seal penalty, nothing is forced.
Interval: env SKV_SKILLS_HARVEST_HOURS (default 72). SKV_CUBE_HARVEST_DAYS is an alias
(days * 24) when the hours env is unset.
The live author / harvest cube is cube_3de96286fc73 (followed through superseded_by).
cube_meta_publish_skills is a superseded pointer to that cube.
"""
import calendar
import os
import sqlite3
import time

AUTHOR_CUBE_ID = "cube_3de96286fc73"
# kept as a name so older tests/docs can still import it; value is the pointer id, not the live cube
META_CUBE_ID = "cube_meta_publish_skills"
DUTY_NAME = "cube_harvest"
DEFAULT_HOURS = 72
RESOLVING_DUTIES = ("cube_harvest", "skills_harvest", "skills_none", "skills_skip")
SHARED_DB = "/data/skv/metadata_store/shared_master.db"


def meta_cube_id():
    """Live author cube: follow superseded_by from AUTHOR_CUBE_ID, else the constant."""
    try:
        from app.cube_harvest import latest_cube_id
        return latest_cube_id(AUTHOR_CUBE_ID) or AUTHOR_CUBE_ID
    except Exception:
        return AUTHOR_CUBE_ID


def rules_text():
    return (
        " Rules: English; no secrets, tokens or personal data (scrub them). "
        "After the one-time notice that this agent may publish anonymized, scrubbed experience cubes, "
        "those cubes may be published (the user can say do not publish). "
        "Anything that quotes personal memory or private files still needs an explicit yes. "
        "Never edit another author's cube: publish a new version (your own version supersedes; "
        "someone else's goes to review). Tell the user in one line: published cube: <topic>."
    )


def step3_text(cid=None):
    cid = cid or meta_cube_id()
    return (
        "3) publish your own skills and hooks as cubes to the shared pool: cube_get(cube_id=\"%s\") and follow it "
        "(search the pool for a duplicate first). If you have none, reply turn(..., duty=skills_none, duty_reason=\"<why>\") "
        "(duty=cube_harvest also closes it)." % cid
    ) + rules_text()


def first_note(cid=None):
    cid = cid or meta_cube_id()
    return (
        "DUTY cube_harvest (first time): review your own skills and hooks and publish the proven, reusable ones as shared "
        "cubes (English, no secrets): cube_get(cube_id=\"%s\"), search the pool for a duplicate first. "
        "Nothing to publish: turn(..., duty=skills_none, duty_reason=\"<why>\") "
        "(duty=cube_harvest also closes it)." % cid
    ) + rules_text()


def again_note(hours=None, cid=None, turns_blurb=""):
    cid = cid or meta_cube_id()
    if hours is None:
        hours = int(round(interval_hours()))
    extra = (" " + turns_blurb.strip()) if (turns_blurb or "").strip() else ""
    return (
        "DUTY cube_harvest (every ~%dh): look back since your last harvest: repeated mistakes, fixes that worked, the user's "
        "corrections, new rules of craft, and skills or hooks worth sharing.%s Publish each as a cube "
        "(cube_get(cube_id=\"%s\"): search for a duplicate first). "
        "Nothing new: turn(..., duty=skills_none, duty_reason=\"<why>\") "
        "(duty=cube_harvest also closes it). Reminder only, nothing is blocked."
        % (hours, extra, cid)
    ) + rules_text()


# backwards-compatible aliases used by older tests (computed at import from the fallback id)
STEP3 = step3_text(AUTHOR_CUBE_ID)
FIRST_NOTE = first_note(AUTHOR_CUBE_ID)
AGAIN_NOTE = "DUTY cube_harvest (every ~%dh): look back since your last harvest: repeated mistakes, fixes that worked, the user's " \
             "corrections, new rules of craft, and skills or hooks worth sharing. Publish each as a cube " \
             "(cube_get(cube_id=\"%s\"): search for a duplicate first). " \
             "Nothing new: turn(..., duty=skills_none, duty_reason=\"<why>\") " \
             "(duty=cube_harvest also closes it). Reminder only, nothing is blocked." + rules_text()
RULES = rules_text()


def interval_hours():
    raw = os.environ.get("SKV_SKILLS_HARVEST_HOURS", "")
    if raw:
        try:
            h = float(raw)
        except ValueError:
            h = DEFAULT_HOURS
        return h if h > 0 else DEFAULT_HOURS
    days = os.environ.get("SKV_CUBE_HARVEST_DAYS", "")
    if days:
        try:
            d = float(days)
            if d > 0:
                return d * 24.0
        except ValueError:
            pass
    return DEFAULT_HOURS


def _fmt(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))


def _parse(s):
    try:
        return calendar.timegm(time.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


def ensure(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_skills_harvest (
            key_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            first_at TEXT,
            last_prompt_at TEXT,
            resolved_at TEXT,
            resolution TEXT DEFAULT '',
            prompts INTEGER DEFAULT 0,
            PRIMARY KEY (key_id, actor_id))"""
    )


def _row(conn, key_id, actor_id):
    ensure(conn)
    return conn.execute(
        "SELECT first_at, last_prompt_at, resolved_at, resolution, prompts FROM agent_skills_harvest WHERE key_id=? AND actor_id=?",
        (key_id or "", actor_id or ""),
    ).fetchone()


def _cube_since(user_id, since_ts, cube_check=None):
    """True when the account created a cube after `since_ts` (UTC seconds)."""
    if cube_check is not None:
        return bool(cube_check(user_id, _fmt(since_ts)))
    if not user_id or not os.path.isfile(SHARED_DB):
        return False
    try:
        c = sqlite3.connect("file:%s?mode=ro" % SHARED_DB, uri=True, timeout=5)
        try:
            return c.execute(
                "SELECT 1 FROM cubes_new WHERE lower(created_by)=? AND created_at>=? LIMIT 1",
                (user_id.strip().lower(), _fmt(since_ts)),
            ).fetchone() is not None
        finally:
            c.close()
    except sqlite3.Error:
        return False


def _base(row):
    """Start of the current period: the later of the last prompt and the resolution."""
    vals = [v for v in (_parse(row[1]), _parse(row[2])) if v is not None]
    return max(vals) if vals else None


def _prompt(conn, key_id, actor_id, now, first):
    stamp = _fmt(now)
    conn.execute(
        "INSERT INTO agent_skills_harvest (key_id, actor_id, first_at, last_prompt_at, resolved_at, resolution, prompts) "
        "VALUES (?,?,?,?,NULL,'',1) ON CONFLICT(key_id, actor_id) DO UPDATE SET last_prompt_at=excluded.last_prompt_at, "
        "resolved_at=NULL, resolution='', prompts=prompts+1",
        (key_id or "", actor_id or "", stamp, stamp),
    )
    conn.commit()


def _resolve(conn, key_id, actor_id, now, how):
    conn.execute(
        "UPDATE agent_skills_harvest SET resolved_at=?, resolution=? WHERE key_id=? AND actor_id=?",
        (_fmt(now), how, key_id or "", actor_id or ""),
    )
    conn.commit()


def _turns_blurb(user_id):
    """Optional 'N turns from ev A to B' line from the account event log. Never raises."""
    if not user_id:
        return ""
    try:
        from app import cube_harvest as ch
        path, mx = ch._udb(user_id)
        if not path:
            return ""
        row = None
        try:
            c = ch._db()
            row = c.execute("select last_rowid from h where user=?", (user_id,)).fetchone()
            c.close()
        except Exception:
            row = None
        after = (row[0] or 0) if row else 0
        n, a, b, since = ch._range(path, after)
        if n <= 0:
            return ""
        bits = ["%d new turns" % n]
        if a and b:
            bits.append("from ev %s to %s" % (a, b))
        if since:
            bits.append("since %s" % since)
        return " ".join(bits) + "."
    except Exception:
        return ""


def identify_step(conn, key_id, actor_id, now=None):
    """Step 3 text for the identify reply, or "". Shown the first time this agent identifies, then only when due."""
    now = time.time() if now is None else now
    row = _row(conn, key_id, actor_id)
    if row is None:
        _prompt(conn, key_id, actor_id, now, True)
        return step3_text()
    base = _base(row)
    if base is not None and now - base >= interval_hours() * 3600:
        _prompt(conn, key_id, actor_id, now, False)
        return step3_text()
    return ""


def duty_item(note, extra=None):
    """Structured cube_harvest payload for turn/step_zero/duties (one duty name)."""
    if not note:
        return None
    item = {
        "due": True,
        "kind": "reminder",
        "duty": DUTY_NAME,
        "cube_id": meta_cube_id(),
        "do": note,
        "close": "turn(..., duty=\"cube_harvest\" or duty=\"skills_none\", duty_reason=\"created: <ids> | nothing: <why>\") resets the timer; aliases: skills_harvest, skills_skip",
        "note": "reminder only, nothing is blocked",
    }
    if extra:
        item.update(extra)
    return item


def turn_note(conn, key_id, actor_id, user_id="", duty="", now=None, cube_check=None):
    """Handle an explicit skip and the periodic reminder. Returns the note text or ""."""
    now = time.time() if now is None else now
    d = (duty or "").strip().lower()
    row = _row(conn, key_id, actor_id)
    if d in RESOLVING_DUTIES:
        if row is None:
            _prompt(conn, key_id, actor_id, now, True)
        _resolve(conn, key_id, actor_id, now, d)
        return ""
    if row is None:
        # an agent that identified before this feature: ask once on its next turn
        _prompt(conn, key_id, actor_id, now, True)
        return first_note()
    last = _parse(row[1])
    if last is None:
        return ""
    if row[2] is None and _cube_since(user_id, last, cube_check):
        _resolve(conn, key_id, actor_id, now, "cube_publish")
        row = _row(conn, key_id, actor_id)
    base = _base(row)
    if base is not None and now - base >= interval_hours() * 3600:
        _prompt(conn, key_id, actor_id, now, False)
        return again_note(turns_blurb=_turns_blurb(user_id))
    return ""
