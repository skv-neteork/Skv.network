"""Stamp the stable actor on a new cube and tell the other agent on the account.

The account email stays in created_by. actor is the identify name (grok-build,
grok-bot), never a per-window session name. A missing or bad token leaves actor
empty. This module does not guess the most recently seen agent.
"""


def resolve_actor(api_key, agent_token="", session_id=""):
    """Actor id from a real agent_token. Empty when the token is missing or bad."""
    agent_token = (agent_token or "").strip()
    session_id = (session_id or "").strip()
    api_key = (api_key or "").strip()
    if not agent_token or not api_key:
        return ""
    try:
        from app.room.bridge import gate, lookup_key, open_account
        info = lookup_key(api_key)
        if not info:
            return ""
        conn = open_account(info)
        try:
            who = gate(info, conn, agent_token=agent_token, session_id=session_id or "mcp")
        finally:
            conn.close()
        if not isinstance(who, dict) or not who.get("ok") or who.get("implicit") or who.get("error"):
            return ""
        return str(who.get("actor_id") or "")[:80]
    except Exception:
        return ""


def announce(api_key, cube_id, actor, session_id="", topic=""):
    """After the cube commit: one room event the other agent can see in while_away."""
    if not (api_key or "").strip() or not cube_id or not (actor or "").strip():
        return None
    try:
        from app.room.bridge import lookup_key, open_account
        from app.room.events import record_event
        info = lookup_key(api_key)
        if not info:
            return None
        conn = open_account(info)
        try:
            label = (topic or cube_id)[:40]
            gist = ("%s wrote %s" % (actor, label))[:100]
            return record_event(
                conn, info.get("chain_id") or "", info.get("key_id") or "", actor,
                session_id or "", kind="cube_write", text=gist,
                event_id="cube-%s" % cube_id, gist=gist,
            )
        finally:
            conn.close()
    except Exception as exc:
        print("[cube_actor] announce skipped: %s" % type(exc).__name__, flush=True)
        return None
