"""Per-agent step_zero. One automatic full pack per session; force at most once per 10 minutes."""
import re
from datetime import timedelta

from app.room.clock import as_dt, iso, parse_iso
from app.room.copy import EMPTY_LANE, STARTER_VERSION
from app.room.digest import _OVERFLOW, build_while_away
from app.room.lanes import facts_for
from app.room.schema import ensure

_CITE_ID = re.compile(r"\[ev:([^\]@\s]+)")


def _logs(conn, actor_id):
    rows = conn.execute(
        "SELECT id, session_id, sent_at, kind, starter_version FROM step_zero_log WHERE actor_id=? ORDER BY id",
        (actor_id,),
    ).fetchall()
    return [{"id": r[0], "session_id": r[1] or "", "sent_at": parse_iso(r[2]), "kind": r[3], "starter_version": r[4] or ""} for r in rows]


def decide(conn, actor_id, session_id, context_state="normal", force=False, starter_version=STARTER_VERSION, now=None):
    ensure(conn)
    now_dt = as_dt(now)
    rows = _logs(conn, actor_id)
    session_fulls = [r for r in rows if r["session_id"] == session_id and r["kind"] == "full"]
    fulls = [r for r in rows if r["kind"] == "full" and r["sent_at"]]
    last_full = fulls[-1]["sent_at"] if fulls else None

    def too_soon(at):
        return bool(at) and (now_dt - at) < timedelta(minutes=10)

    if force:
        if too_soon(last_full):
            return None
        return "full"
    if (context_state or "") == "lost":
        if len(session_fulls) < 2:
            return "full"
        if not too_soon(last_full):
            return "full"
        return None
    if not rows or not session_fulls:
        if rows and rows[-1]["session_id"] == session_id and rows[-1]["kind"] == "delta":
            pass
        else:
            if not session_fulls:
                # first pack of this session (also the agent's first turn)
                if not rows or rows[-1]["session_id"] != session_id or not any(r["session_id"] == session_id for r in rows):
                    return "full"
    if not session_fulls:
        return "full"
    if not any(r["starter_version"] == starter_version and r["kind"] == "full" for r in session_fulls):
        return "full"
    last = rows[-1]
    if last["sent_at"] and now_dt - last["sent_at"] > timedelta(hours=12):
        return "delta"
    return None


def _mark(conn, actor_id, session_id, kind, starter_version, now):
    conn.execute(
        "INSERT INTO step_zero_log (actor_id, session_id, sent_at, kind, starter_version) VALUES (?,?,?,?,?)",
        (actor_id, session_id, iso(as_dt(now)), kind, starter_version),
    )
    conn.commit()


def _dedupe_pack_overflow(digest, printed_blob, unshown_ids):
    """Keep the overflow line from citing an ev the full pack already printed.

    The standalone digest is unchanged. Only the copy glued into the pack is rewritten.
    """
    lines = (digest or "").splitlines()
    idx = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("+") and "ещё с ev:" in s:
            idx = i
    if idx is None:
        return digest or ""
    printed = set(_CITE_ID.findall(printed_blob or ""))
    still = [e for e in (unshown_ids or []) if e and e not in printed]
    if not still:
        del lines[idx]
    else:
        lines[idx] = _OVERFLOW % (len(still), still[0], still[0])
    return "\n".join(lines).strip()


def step_zero_package(conn, actor_id, key_id, chain_id, role="assistant", session_id="mcp",
                      context_state="normal", force=False, starter_version=STARTER_VERSION, now=None, display_name=""):
    kind = decide(conn, actor_id, session_id, context_state, force, starter_version, now)
    away = build_while_away(conn, actor_id, key_id, chain_id, role, now)
    view = facts_for(conn, actor_id, key_id, chain_id, role, digest_ids=set(away.get("event_ids") or []))
    if kind is None:
        return {"kind": None, "text": "", "while_away": None, "proposed_upto": away.get("proposed_upto"), "step_zero": False}
    _mark(conn, actor_id, session_id, kind, starter_version, now)
    who = display_name or actor_id
    head = "You are %s, role %s." % (who, role)
    parts = [head]
    own_part = ""
    if kind == "full":
        own_part = view["own_empty"] or "\n".join(view["own_lines"][:8])
        parts.append(own_part)
        if view["others_block"]:
            parts.append(view["others_block"])
    if away.get("text"):
        digest = away["text"]
        if kind == "full":
            printed = (own_part or "") + "\n" + (view.get("others_block") or "")
            digest = _dedupe_pack_overflow(digest, printed, away.get("unshown_event_ids") or [])
        dlines = [ln for ln in digest.splitlines() if ln.strip()][:12]
        digest = "\n".join(dlines)[:1500]
        if digest:
            parts.append(digest)
    elif kind == "delta":
        parts.append("delta: idle for more than 12 h")
    text = "\n".join(p for p in parts if p)
    if kind == "full" and view["own_empty"] and EMPTY_LANE not in text:
        text += "\n" + EMPTY_LANE
    return {
        "kind": kind,
        "text": text,
        "while_away": away.get("text"),
        "proposed_upto": away.get("proposed_upto"),
        "step_zero": True,
        "others_block": view["others_block"],
        "own_empty": view["own_empty"],
        "event_ids": away.get("event_ids") or [],
    }
