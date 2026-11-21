"""Author-cube CORE on an experience-cube reminder, once per episode.

The live cube is whoever links_json.superseded_by reaches from cube_688c0ebbb3be.
CORE is chain_skills.core_only, capped at SKILL_MD_CAP. A failure leaves the
reminder as it was. The cache stores a user hash, the cube id, and a sent flag,
not the manual.

SKV_CUBE_REMINDER_CORE=0 turns the inline CORE off and leaves the existing cube_get wording.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3

MARK = "AUTHOR CUBE CORE ("
# Room for one CORE block past a compact response cap (SKILL_MD_CAP plus the header).
CORE_SLACK = 6200
_DEFAULT_DB = "/data/skv/metadata_store/cube_reminder_core.db"
_SHARED = "/data/skv/metadata_store/shared_master.db"


def enabled():
    # SKV_CUBE_REMINDER_CORE=0 turns the inline CORE off and leaves the existing cube_get wording.
    return os.environ.get("SKV_CUBE_REMINDER_CORE", "1").strip().lower() not in ("0", "off", "false", "no")


def is_cube_reminder(text):
    t = text or ""
    return (
        t.startswith("RULE experience cube")
        or t.startswith("MANDATORY: cube ")
        or "CUBE NUDGE:" in t
        or t.startswith("• CUBE DUTY:")
    )


def carries_core(obj):
    if isinstance(obj, str):
        return MARK in obj
    if isinstance(obj, dict):
        return any(carries_core(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(carries_core(v) for v in obj)
    return False


def shrink_text(text, cap):
    """Trim one duty field. A string that already carries CORE stays whole."""
    if not isinstance(text, str):
        return text
    if MARK in text or len(text) <= cap:
        return text
    return text[:cap] + "…(trimmed)"


def clip_duty(d, cap=300):
    """REST/MCP duty line. CORE reminders are not cut to the short duty cap."""
    s = d if isinstance(d, str) else str(d)
    if MARK in s:
        return s
    return s[:cap]


def _user_key(user):
    return hashlib.sha256((user or "").strip().lower().encode()).hexdigest()[:16]


def _db_path(explicit=None):
    return explicit or os.environ.get("SKV_CUBE_REMINDER_CORE_DB") or _DEFAULT_DB


def _db(path=None):
    c = sqlite3.connect(_db_path(path), timeout=10, isolation_level=None)
    c.execute(
        "create table if not exists crc_ep(user_key text primary key, cube_id text, episode int default 1, sent int default 0)"
    )
    return c


def resolve_live(shared_db=None):
    """Follow superseded_by from cube_688c0ebbb3be. Returns (cube_id, version_hop). Raises if the DB cannot be read."""
    from app.cube_harvest import CUBE_ID
    cid = CUBE_ID
    hops = 1
    path = shared_db or _SHARED
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    try:
        for _ in range(20):
            r = c.execute(
                "select coalesce(status,''), links_json from cubes_new where cube_id=?",
                (cid,),
            ).fetchone()
            if not r or r[0] != "superseded":
                break
            try:
                nxt = (json.loads(r[1] or "{}") or {}).get("superseded_by")
            except Exception:
                nxt = None
            if not isinstance(nxt, str) or not nxt.strip() or nxt.strip() == cid:
                break
            cid = nxt.strip()
            hops += 1
        return cid, hops
    finally:
        c.close()


def load_core(cube_id, shared_db=None):
    """core_only(skill_md), capped at SKILL_MD_CAP. Empty when the cube has no manual. Raises if the DB cannot be read."""
    from app.chain_skills import SKILL_MD_CAP, core_only
    path = shared_db or _SHARED
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    try:
        r = c.execute("select skill_md from cubes_new where cube_id=?", (cube_id,)).fetchone()
    finally:
        c.close()
    if not r:
        return ""
    text = (core_only(r[0] or "") or "").strip()
    if len(text) > SKILL_MD_CAP:
        text = text[:SKILL_MD_CAP]
    return text


def _block(cube_id, version, body):
    head = "%s%s, v%d):" % (MARK, cube_id, int(version or 1))
    if not (body or "").strip():
        return head + " missing"
    return head + "\n" + body


def _should_send(c, user, cube_id):
    """True the first time this episode should carry CORE for this agent and live cube."""
    key = _user_key(user)
    row = c.execute("select cube_id, episode, sent from crc_ep where user_key=?", (key,)).fetchone()
    if row and row[0] == cube_id and row[2]:
        return False
    episode = 1
    if row:
        episode = int(row[1] or 1)
        if row[0] != cube_id:
            episode += 1
    c.execute(
        "insert or replace into crc_ep(user_key, cube_id, episode, sent) values(?,?,?,1)",
        (key, cube_id, episode),
    )
    return True


def note_complied(user, db=None):
    """A publish or cube_nothing-with-reason starts a new episode. Never raises."""
    if not (user or "").strip():
        return
    try:
        c = _db(db)
        try:
            key = _user_key(user)
            row = c.execute("select cube_id, episode from crc_ep where user_key=?", (key,)).fetchone()
            if row:
                c.execute(
                    "update crc_ep set sent=0, episode=? where user_key=?",
                    (int(row[1] or 1) + 1, key),
                )
            else:
                c.execute(
                    "insert into crc_ep(user_key, cube_id, episode, sent) values(?,?,1,0)",
                    (key, ""),
                )
        finally:
            c.close()
    except Exception:
        return


def decorate(text, user, shared_db=None, db=None):
    """Append CORE once per episode. Off, or any lookup error: the reminder unchanged."""
    if not text or not is_cube_reminder(text):
        return text
    if not enabled():
        return text
    try:
        cid, ver = resolve_live(shared_db)
        body = load_core(cid, shared_db)
        c = _db(db)
        try:
            if not _should_send(c, user or "", cid):
                return text
        finally:
            c.close()
        return text.rstrip() + "\n\n" + _block(cid, ver, body)
    except Exception:
        return text


def decorate_rules(rules, user, shared_db=None, db=None):
    out = []
    for r in rules or []:
        if isinstance(r, str):
            out.append(decorate(r, user, shared_db=shared_db, db=db))
        else:
            out.append(r)
    return out
