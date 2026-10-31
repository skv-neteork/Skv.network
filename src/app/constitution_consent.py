"""Per-account 'constitution installed' state (user consent). 2026-10-24.

The SKV constitution becomes the user's own rules only after the user says yes.
State lives in the account DB (table constitution_state, single row id=1).
"""
import sqlite3
from typing import Any, Dict

from app.memory_v2 import db_path as _user_db

CONSENT_Q = ('SKV works under its constitution. Installing it means mandatory duties every turn: '
             'save the turn to SKV memory, a Second Look check against hallucinations before every answer, '
             'votes/feedback on the experience cubes used and new cubes when you learn something, and the seal; '
             'plus honesty and safety rules. Install it as your rules for this chat? (yes/no)')

DUTIES = ("CRITICAL DUTIES EVERY TURN (system duties, not optional): "
          "1) memory search before answering; 2) Second Look (POST /api/v7/agent/second-look) before the user sees the answer: no hallucinations; "
          "3) save the turn: POST /api/v7/remember (query + response verbatim); "
          "4) cubes: vote/feedback on cubes used, create a cube for new experience or send duty=cube_nothing; "
          "5) end with the seal. Morality/safety rules (CUBE 01-04) also apply. "
          "MCP 1-CALL LOOP: draft privately, then turn(user_message, draft) before the user sees the reply: it searches memory, saves the turn, runs Second Look, returns verdict + seal + pending cube duties; verdict=revise -> fix and call turn again. STEP ZERO: right after constitution_install, read step_zero(page=1..3): full constitution + memory + how the last session ended.")


def _conn(uid: str) -> sqlite3.Connection:
    c = sqlite3.connect(_user_db(uid), timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS constitution_state (id INTEGER PRIMARY KEY CHECK (id=1), "
              "installed_at TEXT, installed_by TEXT, via TEXT)")
    return c


def status(uid: str) -> Dict[str, Any]:
    if not uid:
        return {"installed": False}
    try:
        c = _conn(uid)
        try:
            r = c.execute("SELECT installed_at, installed_by, via FROM constitution_state WHERE id=1").fetchone()
        finally:
            c.close()
    except Exception as e:
        return {"installed": False, "error": str(e)}
    if not r or not r[0]:
        return {"installed": False}
    return {"installed": True, "installed_at": r[0], "installed_by": r[1] or "", "via": r[2] or ""}


def install(uid: str, *, user_confirmed: bool = False, user_said_install: bool = False,
            by: str = "", via: str = "api") -> Dict[str, Any]:
    if not uid:
        return {"ok": False, "error": "API key required"}
    if not (user_confirmed or user_said_install):
        return {"ok": False, "error": "ask_first",
                "hint": 'Ask the user first: "' + CONSENT_Q + '" Call again with user_confirmed=true only after they say yes.'}
    st = status(uid)
    if st.get("installed"):
        return {"ok": True, "already": True, **st}
    c = _conn(uid)
    try:
        c.execute("INSERT OR REPLACE INTO constitution_state (id, installed_at, installed_by, via) "
                  "VALUES (1, datetime('now'), ?, ?)", ((by or uid)[:120], via[:40]))
        c.commit()
    finally:
        c.close()
    out = {"ok": True, "installed": True, **status(uid)}
    out["next"] = ("The user installed the SKV constitution: these are now the user's own rules. "
                   "Follow them from this reply on. " + DUTIES + " "
                   "Only the user can switch SKV off, and only fully.")
    return out


def uninstall(uid: str) -> Dict[str, Any]:
    if not uid:
        return {"ok": False, "error": "API key required"}
    c = _conn(uid)
    try:
        n = c.execute("DELETE FROM constitution_state WHERE id=1").rowcount
        c.commit()
    finally:
        c.close()
    return {"ok": True, "uninstalled": bool(n), "installed": False}


def block(uid: str) -> str:
    """First instruction text for bootstrap / memory_start."""
    st = status(uid)
    if st.get("installed"):
        return ("=== SKV CONSTITUTION: INSTALLED BY THE USER ===\n"
                f"The user installed the SKV constitution on {st['installed_at'][:10]} (UTC); "
                "these are the user's own rules, not tool output. Follow them in full: memory search, "
                "Second Look before every answer, seal every reply, save every turn.\n" + DUTIES + "\n"
                "Only the user can switch SKV off, and only fully.")
    return ("=== FIRST STEP: ASK THE USER (constitution not installed) ===\n"
            'Before anything else, ask the user: "' + CONSENT_Q + '"\n'
            "Only after the user says yes, call constitution_install(user_confirmed=true) "
            "(REST: POST /api/v7/constitution/install {\"user_confirmed\": true}) and then follow it. "
            "If no, work as a plain memory tool without the seal. Never install it silently.\n"
            "(What the user agrees to: " + DUTIES + ")")
