"""HTTP file_claim / file_check / file_release. The client actor id is not accepted."""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v7", tags=["room"])


class FileBody(BaseModel):
    path: str
    base_hash: str = ""
    current_hash: str = ""
    new_hash: str = ""
    task_id: str = ""
    agent_token: str = ""
    session_id: str = ""
    minus: int = 0
    plus: int = 0
    old_hash: str = ""


class IdentifyBody(BaseModel):
    name: str = ""
    role: str = ""
    client_hint: str = ""
    session_id: str = ""


class RoomTurnBody(BaseModel):
    agent_token: str = ""
    session_id: str = "rest"
    context_state: str = "normal"
    kind: str = "turn"
    event_id: str = ""
    saved: bool = True
    verdict: str = ""
    note: str = ""


class StepZeroRoomBody(BaseModel):
    agent_token: str = ""
    session_id: str = "rest"
    force: bool = False
    context_state: str = "normal"


def _bearer(authorization: str):
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _info(authorization: str):
    from app.room.bridge import lookup_key
    info = lookup_key(_bearer(authorization))
    if not info:
        raise HTTPException(401, "API key required")
    return info


def _who(authorization: str, agent_token: str, session_id: str):
    from app.room.bridge import gate, lookup_key, open_account
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    info = lookup_key(token) if token else None
    if not info:
        raise HTTPException(401, "API key required")
    conn = open_account(info)
    who = gate(info, conn, agent_token or "", session_id or "skv-edit")
    if isinstance(who, dict) and who.get("error") == "IDENTIFY_REQUIRED":
        conn.close()
        raise HTTPException(428, "IDENTIFY_REQUIRED")
    if not isinstance(who, dict) or not who.get("ok"):
        conn.close()
        raise HTTPException(401, "agent_token required")
    return conn, info, who


@router.post("/agent/identify")
def http_identify(req: IdentifyBody, authorization: str = Header(None)):
    """Same identify as the MCP tool. A second call with the same name reuses the agent."""
    from app.room.bridge import do_identify, open_account
    info = _info(authorization)
    conn = open_account(info)
    try:
        try:
            return do_identify(info, conn, req.name, req.role or "assistant", req.client_hint or "", req.session_id or "")
        except ValueError as e:
            raise HTTPException(422, str(e))
    finally:
        conn.close()


@router.post("/agent/room")
def http_room_attach(req: RoomTurnBody, authorization: str = Header(None)):
    """After a client saved a turn over REST: stamp it and return while_away. Never refuses the save."""
    from app.room.bridge import open_account, rest_attach
    info = _info(authorization)
    conn = open_account(info)
    try:
        result = {
            "saved": bool(req.saved),
            "event_id": req.event_id or "",
            "verdict": req.verdict or "",
            "session_id": req.session_id or "rest",
            "note": req.note or "",
        }
        done = rest_attach(
            info, conn, result, req.agent_token or "", req.session_id or "rest",
            req.kind or "turn", req.context_state or "normal",
        )
        keep = {}
        for key in ("saved", "event_id", "while_away", "actor", "identify_hint", "room_warning", "room_step_zero"):
            if isinstance(done, dict) and done.get(key) not in (None, ""):
                keep[key] = done.get(key)
        return keep
    finally:
        conn.close()


@router.post("/agent/step_zero")
def http_step_zero_room(req: StepZeroRoomBody, authorization: str = Header(None)):
    """Room part of step_zero: the block about what other agents on this line did."""
    from app.room.bridge import open_account, rest_step_zero
    info = _info(authorization)
    conn = open_account(info)
    try:
        return rest_step_zero(
            info, conn, req.agent_token or "", req.session_id or "rest", bool(req.force), req.context_state or "normal",
        )
    finally:
        conn.close()


@router.post("/file_claim")
def http_file_claim(req: FileBody, authorization: str = Header(None)):
    from app.room.files import FileConflict, file_claim
    conn, info, who = _who(authorization, req.agent_token, req.session_id)
    try:
        try:
            return file_claim(conn, info["chain_id"], req.path, who["actor_id"], req.base_hash, req.task_id, info["key_id"], session_id=req.session_id)
        except FileConflict as e:
            raise HTTPException(409, "409 file claimed_by=%s" % e.owner)
        except ValueError as e:
            raise HTTPException(422, str(e))
    finally:
        conn.close()


@router.post("/file_check")
def http_file_check(req: FileBody, authorization: str = Header(None)):
    from app.room.files import file_check
    conn, info, who = _who(authorization, req.agent_token, req.session_id)
    try:
        del who
        return file_check(conn, info["chain_id"], req.path, req.current_hash or req.base_hash)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close()


@router.post("/file_release")
def http_file_release(req: FileBody, authorization: str = Header(None)):
    from app.room.files import FileConflict, file_release
    conn, info, who = _who(authorization, req.agent_token, req.session_id)
    try:
        try:
            return file_release(
                conn, info["chain_id"], req.path, who["actor_id"], req.new_hash or req.base_hash,
                info["key_id"], session_id=req.session_id, minus=req.minus, plus=req.plus, old_hash=req.old_hash,
            )
        except FileConflict as e:
            raise HTTPException(409, "409 file claimed_by=%s" % e.owner)
        except KeyError:
            raise HTTPException(404, "file claim not found")
        except ValueError as e:
            raise HTTPException(422, str(e))
    finally:
        conn.close()
