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
