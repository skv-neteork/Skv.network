"""SKV v7 API: chat import endpoints.
Split from v7_router.py with behavior unchanged; shared helpers and state come from v7_core."""
from app.routers import v7_core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})


@router.post("/import/text")
async def agent_import_text(data: dict):
    from app.routers.import_dialogs import import_from_text
    if not data.get("user_id") and data.get("key"):
        data["user_id"] = _user_from_key(data["key"])
    return await import_from_text(data)

@router.get("/agent/import")
async def agent_get_import(key: str, text: str, source: str = "text_import"):
    from app.routers.import_dialogs import import_from_text
    return await import_from_text({"user_id": _user_from_key(key), "text": text, "source": source})


# Drive queue (T_GDRIVE) — MCP uses /api/v7/import/drive/*
@router.get("/import/drive/queue")
async def v7_drive_queue(status: str = "pending", limit: int = 50, key: str = "", user_id: str = ""):
    from app.routers.import_dialogs import import_drive_queue_list
    return await import_drive_queue_list(user_id=user_id, status=status, limit=limit, key=key)


@router.post("/import/drive/complete")
async def v7_drive_complete(data: dict):
    from app.routers.import_dialogs import import_drive_complete
    if not data.get("user_id") and data.get("key"):
        data = dict(data)
        data["user_id"] = _user_from_key(data["key"])
    return await import_drive_complete(data)


@router.post("/import/drive/process")
async def v7_drive_process(data: dict):
    from app.routers.import_dialogs import import_drive_process
    if not data.get("user_id") and data.get("key"):
        data = dict(data)
        data["user_id"] = _user_from_key(data["key"])
    return await import_drive_process(data)


@router.get("/import/drive/payload")
async def v7_drive_payload(id: int = 0, key: str = "", user_id: str = "", max_bytes: int = 4000000):
    from app.routers.import_dialogs import import_drive_payload
    return await import_drive_payload(user_id=user_id, id=id, key=key, max_bytes=max_bytes)
