"""Consultation. POST /api/v7/consult, /api/v7/consult/accept, GET /api/v7/consult/history."""
from fastapi import APIRouter, HTTPException, Request
from app.consult_pool import ask, accept, history
from app.routers.v7_core import _user_from_key

router = APIRouter()


def _key(request: Request, data: dict) -> str:
    key = (data.get("key") or "").strip()
    if not key:
        h = request.headers.get("authorization", "")
        if h.lower().startswith("bearer "):
            key = h.split(" ", 1)[1].strip()
    if not key:
        key = (request.headers.get("x-api-key") or request.query_params.get("key") or "").strip()
    if not key:
        raise HTTPException(401, "key required")
    return key


# sync handlers: they make blocking HTTP calls and run in the threadpool
@router.post("/api/v7/consult")
def consult(request: Request, data: dict):
    key = _key(request, data)
    uid = _user_from_key(key)
    return ask(uid, data.get("task", ""), data.get("tried", ""), data.get("failed", ""), bool(data.get("consent")))


@router.post("/api/v7/consult/accept")
def consult_accept(request: Request, data: dict):
    key = _key(request, data)
    uid = _user_from_key(key)
    return accept(uid, data.get("id"), data.get("which", ""), data.get("as") or data.get("as_kind") or "note", key=key)


@router.get("/api/v7/consult/history")
def consult_history(request: Request, limit: int = 10):
    key = _key(request, {})
    return history(_user_from_key(key), limit)
