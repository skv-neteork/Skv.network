import os
from fastapi import APIRouter, HTTPException, Request
router = APIRouter()

"""V4 Personal Memory — PostgreSQL-backed session storage."""
import asyncpg
import json
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")

async def _get_conn():
    return await asyncpg.connect(DATABASE_URL)

async def save_session(user_id: str, session_id: str, data: dict, project_ref: str = "general"):
    conn = await _get_conn()
    try:
        await conn.execute("""
            INSERT INTO user_sessions (user_id, session_id, project_ref, data, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id, session_id) 
            DO UPDATE SET data = $4, project_ref = $3, updated_at = NOW()
        """, user_id, session_id, project_ref, json.dumps(data))
        return {"status": "saved", "session_id": session_id, "project": project_ref}
    finally:
        await conn.close()

async def load_context(user_id: str, project: str):
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT data FROM user_sessions WHERE user_id = $1 AND project_ref = $2 ORDER BY updated_at DESC LIMIT 10",
            user_id, project
        )
        sessions = [json.loads(r['data']) for r in rows]
        return {
            "project": project,
            "sessions_count": len(sessions),
            "last_session": sessions[-1].get("query", "")[:100] if sessions else None,
            "summary": "\n".join([f'- {s.get("query","")[:80]}' for s in sessions[-5:]]),
            "recent_sessions": sessions[-5:]
        }
    finally:
        await conn.close()

async def list_projects(user_id: str):
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT DISTINCT project_ref FROM user_sessions WHERE user_id = $1", user_id
        )
        return [r['project_ref'] for r in rows]
    finally:
        await conn.close()


@router.post("/api/v4/sessions")
async def create_session(request: Request):
    data = await request.json()
    user_id = data.get("user_id", "anonymous")
    session_id = data.get("session_id", f"s_{int(__import__('time').time())}")
    project = data.get("project", "general")
    
    result = await save_session(user_id, session_id, data, project)
    return result

@router.get("/api/v4/users/{user_id}/projects/{project}/context")
async def get_context(user_id: str, project: str):
    return await load_context(user_id, project)

@router.get("/api/v4/users/{user_id}/projects")
async def get_projects(user_id: str):
    projects = await list_projects(user_id)
    return {"projects": [{"name": p} for p in projects]}
