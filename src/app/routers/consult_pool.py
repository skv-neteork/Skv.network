"""Consultation. POST /api/v7/consult and /api/v7/consult/accept."""
from fastapi import APIRouter, HTTPException, Request
from app.consult_pool import ask, accept
from app.routers.v7_core import _user_from_key

router = APIRouter()


def _uid(request: Request, data: dict) -> str:
    key = (data.get("key") or "").strip()
    if not key:
        h = request.headers.get("authorization", "")
        if h.lower().startswith("bearer "):
            key = h.split(" ", 1)[1].strip()
    if not key:
        raise HTTPException(401, "key required")
    return _user_from_key(key)


@router.post("/api/v7/consult")
async def consult(request: Request):
    data = await request.json()
    uid = _uid(request, data)
    return ask(uid, data.get("task", ""), data.get("tried", ""), data.get("failed", ""), bool(data.get("consent")))


@router.post("/api/v7/consult/accept")
async def consult_accept(request: Request):
    data = await request.json()
    uid = _uid(request, data)
    return accept(uid, data.get("id"), data.get("which", ""), data.get("as", "note"))
