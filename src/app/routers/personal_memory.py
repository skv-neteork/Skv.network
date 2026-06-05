"""Personal Memory API — бесконечный контекст для пользователей."""
import json, os, time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v4/users", tags=["personal_memory"])

MEMORY_DIR = "/app/app/runtime/memory"

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


def _get_memory_path(user_id: str, project: str) -> str:
    """Путь к файлу памяти проекта."""
    user_dir = os.path.join(MEMORY_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, f"{project}.json")


def _load_memory(user_id: str, project: str) -> ProjectContext:
    """Загрузить память проекта."""
    path = _get_memory_path(user_id, project)
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        return ProjectContext(**data)
    return ProjectContext(project_name=project)


def _save_memory(user_id: str, project: str, context: ProjectContext):
    """Сохранить память проекта."""
    path = _get_memory_path(user_id, project)
    with open(path, 'w') as f:
        json.dump(context.dict(), f, ensure_ascii=False, indent=2)


@router.post("/{user_id}/projects/{project}/memory")
async def save_memory(user_id: str, project: str, entry: MemoryEntry):
    """Сохранить сессию в память проекта."""
    context = _load_memory(user_id, project)
    
    entry.timestamp = entry.timestamp or time.time()
    context.sessions.append(entry.dict())
    
    # Ограничим глубину хранения — последние 100 сессий
    if len(context.sessions) > 100:
        # Оставляем каждую 10-ю из старых (консолидация)
        old = context.sessions[:-100]
        consolidated = old[::10]
        context.sessions = consolidated + context.sessions[-100:]
    
    _save_memory(user_id, project, context)
    
    return {
        "status": "saved",
        "project": project,
        "total_sessions": len(context.sessions)
    }


@router.get("/{user_id}/projects/{project}/memory")
async def load_memory(user_id: str, project: str, last_n: int = 10):
    """Загрузить память проекта для агента."""
    context = _load_memory(user_id, project)
    
    # Возвращаем последние N сессий + описание проекта
    recent = context.sessions[-last_n:] if context.sessions else []
    
    # Формируем контекст для агента
    agent_context = f"## Проект: {project}\n"
    agent_context += f"Описание: {context.description}\n"
    agent_context += f"Сессий: {len(context.sessions)}\n\n"
    
    if recent:
        agent_context += "### Последние сессии:\n"
        for s in recent:
            agent_context += f"- [{s.get('session_id','?')}] {s.get('query','')[:100]}\n"
            if s.get('cubes_used'):
                agent_context += f"  Кубы: {', '.join(s['cubes_used'][:5])}\n"
    
    return {
        "project": project,
        "total_sessions": len(context.sessions),
        "recent_sessions": len(recent),
        "context": agent_context,
        "sessions": recent
    }


@router.get("/{user_id}/projects")
async def list_projects(user_id: str):
    """Список всех проектов пользователя."""
    user_dir = os.path.join(MEMORY_DIR, user_id)
    if not os.path.exists(user_dir):
        return {"user_id": user_id, "projects": []}
    
    projects = []
    for f in os.listdir(user_dir):
        if f.endswith('.json'):
            path = os.path.join(user_dir, f)
            try:
                with open(path) as fp:
                    data = json.load(fp)
                projects.append({
                    "project": f.replace('.json', ''),
                    "sessions": len(data.get('sessions', [])),
                    "last_updated": max(
                        [s.get('timestamp', 0) for s in data.get('sessions', [])],
                        default=0
                    )
                })
            except:
                pass
    
    return {
        "user_id": user_id,
        "projects": sorted(projects, key=lambda p: p['last_updated'], reverse=True)
    }
