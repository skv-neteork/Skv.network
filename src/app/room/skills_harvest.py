"""Skills and hooks harvest: every agent publishes its proven skills/hooks as shared cubes, then is reminded.

State is per agent (key_id + agent id), in the account database next to the room tables:
  first prompt  : shown in the identify reply (step 3) the first time an agent identifies.
  reminder      : a turn reply carries the duty `skills_harvest` when the interval has passed.
Resolved by a cube the account created after the prompt (cube_publish), or an explicit turn
duty=skills_none | skills_skip. A reminder only: no seal penalty, nothing is forced.
Interval: env SKV_SKILLS_HARVEST_HOURS (default 72).
"""
import calendar
import os
import sqlite3
import time

META_CUBE_ID = "cube_meta_publish_skills"
DEFAULT_HOURS = 72
RESOLVING_DUTIES = ("skills_none", "skills_skip")
SHARED_DB = "/data/skv/metadata_store/shared_master.db"

STEP3 = (
    "3) publish your own skills and hooks as cubes to the shared pool: cube_get(cube_id=\"%s\") and follow it "
    "(search the pool for a duplicate first). If you have none, reply turn(..., duty=skills_none, duty_reason=\"<why>\")." % META_CUBE_ID
)
FIRST_NOTE = (
    "DUTY skills_harvest (first time): review your own skills and hooks and publish the proven, reusable ones as shared "
    "cubes (English, no secrets): cube_get(cube_id=\"%s\"). Nothing to publish: turn(..., duty=skills_none, duty_reason=\"<why>\")." % META_CUBE_ID
)
AGAIN_NOTE = (
    "DUTY skills_harvest (every ~%dh): look back since your last harvest: repeated mistakes, fixes that worked, the user's "
    "corrections, new rules of craft. Publish each as a cube (cube_get(cube_id=\"%s\"): search for a duplicate first). "
    "Nothing new: turn(..., duty=skills_none, duty_reason=\"<why>\"). Reminder only, nothing is blocked."
)


def interval_hours():
    try:
        h = float(os.environ.get("SKV_SKILLS_HARVEST_HOURS", "") or DEFAULT_HOURS)
    except ValueError:
        h = DEFAULT_HOURS
    return h if h > 0 else DEFAULT_HOURS


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


def identify_step(conn, key_id, actor_id, now=None):
    """Step 3 text for the identify reply, or "". Shown the first time this agent identifies, then only when due."""
    now = time.time() if now is None else now
    row = _row(conn, key_id, actor_id)
    if row is None:
        _prompt(conn, key_id, actor_id, now, True)
        return STEP3
    base = _base(row)
    if base is not None and now - base >= interval_hours() * 3600:
        _prompt(conn, key_id, actor_id, now, False)
        return STEP3
    return ""


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
        return FIRST_NOTE
    last = _parse(row[1])
    if last is None:
        return ""
    if row[2] is None and _cube_since(user_id, last, cube_check):
        _resolve(conn, key_id, actor_id, now, "cube_publish")
        row = _row(conn, key_id, actor_id)
    base = _base(row)
    if base is not None and now - base >= interval_hours() * 3600:
        _prompt(conn, key_id, actor_id, now, False)
        return AGAIN_NOTE % (int(round(interval_hours())), META_CUBE_ID)
    return ""
