"""V4 Personal Memory — PostgreSQL-backed session storage (auth + no hardcoded secrets)."""
import os
import json
import time
from fastapi import APIRouter, HTTPException, Request
import asyncpg

from app.security import get_database_url, sanitize_path_component

router = APIRouter()


async def _get_conn():
    url = get_database_url()
    if not url:
        raise HTTPException(status_code=503, detail="Database not configured")
    return await asyncpg.connect(url)


def _require_owner(request: Request, user_id: str) -> str:
    auth_uid = getattr(request.state, "user_id", None)
    if not auth_uid:
        raise HTTPException(status_code=401, detail="API token required")
    try:
        safe_uid = sanitize_path_component(user_id, allow_email=True)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    a = str(auth_uid).strip().lower()
    b = safe_uid.strip().lower()
    if a != b and a.split("@")[0] != b.split("@")[0]:
        raise HTTPException(status_code=403, detail="Access denied for this user_id")
    return safe_uid


async def save_session(user_id: str, session_id: str, data: dict, project_ref: str = "general"):
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO user_sessions (user_id, session_id, project_ref, data, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id, session_id)
            DO UPDATE SET data = $4, project_ref = $3, updated_at = NOW()
            """,
            user_id,
            session_id,
            project_ref,
            json.dumps(data),
        )
        return {"status": "saved", "session_id": session_id, "project": project_ref}
    finally:
        await conn.close()


async def load_context(user_id: str, project: str):
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT data FROM user_sessions WHERE user_id = $1 AND project_ref = $2 ORDER BY updated_at DESC LIMIT 10",
            user_id,
            project,
        )
        sessions = [json.loads(r["data"]) for r in rows]
        return {
            "project": project,
            "sessions_count": len(sessions),
            "last_session": sessions[-1].get("query", "")[:100] if sessions else None,
            "summary": "\n".join([f'- {s.get("query", "")[:80]}' for s in sessions[-5:]]),
            "recent_sessions": sessions[-5:],
        }
    finally:
        await conn.close()


async def list_projects(user_id: str):
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT DISTINCT project_ref FROM user_sessions WHERE user_id = $1",
            user_id,
        )
        return [r["project_ref"] for r in rows]
    finally:
        await conn.close()


@router.post("/api/v4/sessions")
async def create_session(request: Request):
    data = await request.json()
    auth_uid = getattr(request.state, "user_id", None)
    if not auth_uid:
        raise HTTPException(status_code=401, detail="API token required")

    # Never trust client-supplied user_id for writes
    user_id = str(auth_uid)
    session_id = str(data.get("session_id") or f"s_{int(time.time())}")[:128]
    project = str(data.get("project") or "general")
    try:
        project = sanitize_path_component(project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project name")

    # Strip privilege fields from stored payload
    safe_data = {k: v for k, v in data.items() if k not in ("api_key", "password", "password_hash")}
    safe_data["user_id"] = user_id

    result = await save_session(user_id, session_id, safe_data, project)
    return result


@router.get("/api/v4/users/{user_id}/projects/{project}/context")
async def get_context(user_id: str, project: str, request: Request):
    user_id = _require_owner(request, user_id)
    try:
        project = sanitize_path_component(project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project name")
    return await load_context(user_id, project)


@router.get("/api/v4/users/{user_id}/projects")
async def get_projects(user_id: str, request: Request):
    user_id = _require_owner(request, user_id)
    projects = await list_projects(user_id)
    return {"projects": [{"name": p} for p in projects]}
