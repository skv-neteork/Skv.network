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
