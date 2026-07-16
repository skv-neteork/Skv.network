"""Personal Memory API — infinite context for users (auth + path-safe)."""
import json
import os
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.security import sanitize_path_component, safe_join

router = APIRouter(prefix="/api/v4/users", tags=["personal_memory"])

MEMORY_DIR = os.environ.get("SKV_MEMORY_DIR", "/app/app/runtime/memory")


class MemoryEntry(BaseModel):
    session_id: str
    query: str
    response: str
    cubes_used: list = []
    timestamp: float = None


class ProjectContext(BaseModel):
    project_name: str
    description: str = ""
    sessions: list = []


def _require_owner(request: Request, user_id: str) -> str:
    """IDOR protection: path user_id must match authenticated principal."""
    auth_uid = getattr(request.state, "user_id", None)
    if not auth_uid:
        raise HTTPException(status_code=401, detail="API token required")
    try:
        safe_uid = sanitize_path_component(user_id, allow_email=True)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    # Compare normalized forms (email or local-part)
    a = str(auth_uid).strip().lower()
    b = safe_uid.strip().lower()
    if a != b and a.split("@")[0] != b.split("@")[0]:
        raise HTTPException(status_code=403, detail="Access denied for this user_id")
    return safe_uid


def _get_memory_path(user_id: str, project: str) -> str:
    try:
        uid = sanitize_path_component(user_id, allow_email=True)
        # Flatten email for directory name
        uid_dir = uid.replace("@", "_at_").replace(".", "_")
        proj = sanitize_path_component(project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id or project")
    user_dir = safe_join(MEMORY_DIR, uid_dir)
    os.makedirs(user_dir, exist_ok=True)
    # proj already sanitized (no path separators); join under user_dir and re-check
    path = os.path.join(user_dir, f"{proj}.json")
    real_base = os.path.realpath(MEMORY_DIR)
    real_path = os.path.realpath(path)
    parent = os.path.realpath(os.path.dirname(path))
    if not parent.startswith(real_base + os.sep) and parent != real_base:
        raise HTTPException(status_code=400, detail="Invalid path")
    return path


def _load_memory(user_id: str, project: str) -> ProjectContext:
    path = _get_memory_path(user_id, project)
    # Re-validate final path under MEMORY_DIR
    real_base = os.path.realpath(MEMORY_DIR)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_base + os.sep) and real_path != real_base:
        raise HTTPException(status_code=400, detail="Invalid path")
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        return ProjectContext(**data)
    return ProjectContext(project_name=project)


def _save_memory(user_id: str, project: str, context: ProjectContext):
    path = _get_memory_path(user_id, project)
    real_base = os.path.realpath(MEMORY_DIR)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_base + os.sep) and os.path.dirname(real_path) != real_base:
        # allow file that doesn't exist yet if parent is under base
        parent = os.path.realpath(os.path.dirname(path))
        if not parent.startswith(real_base + os.sep) and parent != real_base:
            raise HTTPException(status_code=400, detail="Invalid path")
    with open(path, "w") as f:
        json.dump(context.dict(), f, ensure_ascii=False, indent=2)


@router.post("/{user_id}/projects/{project}/memory")
async def save_memory(user_id: str, project: str, entry: MemoryEntry, request: Request):
    user_id = _require_owner(request, user_id)
    try:
        sanitize_path_component(project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project name")

    context = _load_memory(user_id, project)
    entry.timestamp = entry.timestamp or time.time()
    context.sessions.append(entry.dict())

    if len(context.sessions) > 100:
        old = context.sessions[:-100]
        consolidated = old[::10]
        context.sessions = consolidated + context.sessions[-100:]

    _save_memory(user_id, project, context)
    return {
        "status": "saved",
        "project": project,
        "total_sessions": len(context.sessions),
    }


@router.get("/{user_id}/projects/{project}/memory")
async def load_memory(user_id: str, project: str, request: Request, last_n: int = 10):
    user_id = _require_owner(request, user_id)
    try:
        sanitize_path_component(project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project name")

    last_n = max(1, min(int(last_n or 10), 50))
    context = _load_memory(user_id, project)
    recent = context.sessions[-last_n:] if context.sessions else []

    agent_context = f"## Project: {project}\n"
    agent_context += f"Description: {context.description}\n"
    agent_context += f"Sessions: {len(context.sessions)}\n\n"

    if recent:
        agent_context += "### Recent sessions:\n"
        for s in recent:
            agent_context += f"- [{s.get('session_id', '?')}] {s.get('query', '')[:100]}\n"
            if s.get("cubes_used"):
                agent_context += f"  Cubes: {', '.join(s['cubes_used'][:5])}\n"

    return {
        "project": project,
        "total_sessions": len(context.sessions),
        "recent_sessions": len(recent),
        "context": agent_context,
        "sessions": recent,
    }


@router.get("/{user_id}/projects")
async def list_projects(user_id: str, request: Request):
    user_id = _require_owner(request, user_id)
    try:
        uid = sanitize_path_component(user_id, allow_email=True)
        uid_dir = uid.replace("@", "_at_").replace(".", "_")
        user_dir = safe_join(MEMORY_DIR, uid_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if not os.path.exists(user_dir):
        return {"user_id": user_id, "projects": []}

    projects = []
    for f in os.listdir(user_dir):
        if not f.endswith(".json"):
            continue
        if ".." in f or "/" in f or "\\" in f:
            continue
        path = os.path.join(user_dir, f)
        real_base = os.path.realpath(user_dir)
        real_path = os.path.realpath(path)
        if not real_path.startswith(real_base + os.sep):
            continue
        try:
            with open(path) as fp:
                data = json.load(fp)
            projects.append(
                {
                    "project": f.replace(".json", ""),
                    "sessions": len(data.get("sessions", [])),
                    "last_updated": max(
                        [s.get("timestamp", 0) for s in data.get("sessions", [])],
                        default=0,
                    ),
                }
            )
        except Exception:
            pass

    return {
        "user_id": user_id,
        "projects": sorted(projects, key=lambda p: p["last_updated"], reverse=True),
    }
