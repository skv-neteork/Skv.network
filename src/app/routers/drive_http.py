"""HTTP for the per-user Drive folder. Tokens are vaulted and never returned."""
import base64
import json
import os

from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter(prefix="/api/v7", tags=["drive"])


def _who(request: Request):
    from app.chain_skills import chain_from_request
    uid, chain_id, chain_name, _kind = chain_from_request(request)
    if not uid:
        raise HTTPException(status_code=401, detail="API key required")
    if not chain_id:
        chain_id = "main"
    return uid, chain_id, chain_name or chain_id


def _client(user_id: str):
    from app import drive_files as drive
    raw = drive.VaultTokens().get(user_id)
    if not raw:
        return None
    try:
        token = json.loads(raw)
    except Exception:
        return None
    access = token.get("access_token") or token.get("token") or ""
    if not access:
        return None
    return drive.GoogleDrive(access)


def _bytes(content_b64: str = "", path: str = "", text: str = "") -> bytes:
    if content_b64:
        return base64.b64decode(content_b64)
    if text:
        return text.encode("utf-8")
    if path:
        real = os.path.realpath(path)
        allowed = ("/tmp/", "/data/skv/drive_staging/")
        if not any(real.startswith(root) for root in allowed):
            raise HTTPException(status_code=422, detail="path must be under staging or tmp")
        with open(real, "rb") as handle:
            return handle.read()
    return b""


@router.get("/drive/connect")
def drive_connect_start(request: Request):
    _who(request)
    from app import drive_files as drive
    return drive.oauth_start()


@router.post("/drive/connect")
def drive_connect_finish(request: Request, body: dict = Body(default={})):
    """Exchange a one-time code. The refresh token is written to the vault, not to the response."""
    uid, chain_id, chain_name = _who(request)
    from app import drive_files as drive
    code = (body or {}).get("code") or ""
    if not code:
        return drive.oauth_start()
    client_id = (os.environ.get("SKV_DRIVE_OAUTH_CLIENT_ID") or "").strip()
    secret = (os.environ.get("SKV_DRIVE_OAUTH_CLIENT_SECRET") or "").strip()
    redirect = (os.environ.get("SKV_DRIVE_OAUTH_REDIRECT") or "").strip()
    if not client_id or not secret or not redirect:
        return drive.oauth_start()
    import urllib.parse
    import urllib.request
    form = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }).encode()
    try:
        request_token = urllib.request.Request("https://oauth2.googleapis.com/token", data=form)
        with urllib.request.urlopen(request_token, timeout=30) as response:
            token = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "oauth_exchange_failed", "hint": drive.CONNECT_HINT}
    access = token.get("access_token") or ""
    return drive.connect_token(
        uid, chain_id, chain_name, json.dumps(token), drive.VaultTokens(), drive.GoogleDrive(access), tag_line=True,
    )


@router.post("/drive/sync")
def drive_sync(request: Request):
    uid, chain_id, chain_name = _who(request)
    from app import drive_files as drive
    client = _client(uid)
    if client is None:
        return {"ok": False, "error": "connect_drive", "hint": drive.CONNECT_HINT,
                "message": "Connect Drive to store files over 1 MB. " + drive.CONNECT_HINT}
    return drive.sync(uid, chain_id, chain_name, client, tag_line=True, force=True)


@router.post("/drive/read")
def drive_read(request: Request, body: dict = Body(default={})):
    uid, chain_id, _name = _who(request)
    from app import drive_files as drive
    file_id = (body or {}).get("file_id") or ""
    if not file_id:
        raise HTTPException(status_code=422, detail="file_id required")
    return drive.read_file(uid, chain_id, file_id, start=int((body or {}).get("start") or 0),
                           limit=int((body or {}).get("limit") or drive.READ_DEFAULT), client=_client(uid))


@router.post("/drive/put")
def drive_put(request: Request, body: dict = Body(default={})):
    uid, chain_id, chain_name = _who(request)
    from app import drive_files as drive
    payload = body or {}
    data = _bytes(payload.get("content_b64") or "", payload.get("path") or "", payload.get("text") or "")
    return drive.place(
        uid, chain_id, chain_name, data, payload.get("name") or "file", payload.get("description") or "",
        mime=payload.get("mime") or "application/octet-stream", client=_client(uid), tag_line=True,
    )


@router.get("/drive/list")
def drive_list(request: Request):
    uid, chain_id, _name = _who(request)
    from app import drive_files as drive
    return drive.list_files(uid, chain_id)


@router.get("/drive/search")
def drive_search(request: Request, q: str = ""):
    uid, chain_id, _name = _who(request)
    from app import drive_files as drive
    return {"ok": True, "files": drive.search(uid, chain_id, q)}
