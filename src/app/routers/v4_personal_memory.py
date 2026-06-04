"""V4 Personal Memory — персональная память проектов для пользователей."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import json, os, time
import numpy as np

router = APIRouter()

class SessionData(BaseModel):
    user_id: str
    project: str
    query: str
    response: str
    summary: Optional[str] = None
    agent: str = "unknown"

class ProjectContext(BaseModel):
    project: str
    sessions_count: int
    last_session: Optional[str] = None
    key_cubes: List[dict] = []
    summary: str = ""

# Хранилище сессий (в проде — RocksDB)
STORAGE_DIR = "/app/data/personal_memory"

def _get_user_dir(user_id: str) -> str:
    path = os.path.join(STORAGE_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path

@router.post("/api/v4/sessions")
async def save_session(data: SessionData):
    """Сохраняет сессию в персональную память пользователя."""
    try:
        from app.routers.v4_middleware import get_embedding_cached
        from app.routers.v4_graph import get_graph, _v4_graph
        from app.routers.tensor_cube import TensorCube
        
        user_dir = _get_user_dir(data.user_id)
        
        # Создаём вектор сессии
        text = f"{data.query} {data.response}"
        embedding = get_embedding_cached(text)
        
        # Сохраняем сессию как куб в общем графе
        session_id = f"session_{data.user_id}_{data.project}_{int(time.time())}"
        tc = TensorCube(session_id, np.array(embedding, dtype=np.float32))
        tc.metadata = {
            "title": f"Session: {data.query[:60]}",
            "type": "session",
            "user_id": data.user_id,
            "project": data.project,
            "agent": data.agent,
            "summary": data.summary or data.response[:200],
            "timestamp": time.time()
        }
        
        _graph = get_graph()
        _graph[session_id] = tc
        
        # Сохраняем на диск для персистентности
        session_file = os.path.join(user_dir, f"{data.project}.json")
        sessions = []
        if os.path.exists(session_file):
            sessions = json.load(open(session_file))
        sessions.append({
            "id": session_id,
            "query": data.query[:200],
            "summary": data.summary or data.response[:200],
            "agent": data.agent,
            "timestamp": time.time()
        })
        # Храним последние 100 сессий
        sessions = sessions[-100:]
        with open(session_file, 'w') as f:
            json.dump(sessions, f)
        
        return {"status": "saved", "session_id": session_id, "project": data.project}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v4/users/{user_id}/projects/{project}/context")
async def load_context(user_id: str, project: str):
    """Загружает контекст проекта для любого агента."""
    try:
        user_dir = _get_user_dir(user_id)
        session_file = os.path.join(user_dir, f"{project}.json")
        
        if not os.path.exists(session_file):
            return ProjectContext(project=project, sessions_count=0, summary="Новый проект").dict()
        
        sessions = json.load(open(session_file))
        
        # Формируем контекст для агента
        summary_parts = []
        for s in sessions[-5:]:  # последние 5 сессий
            summary_parts.append(f"- {s.get('query', '?')[:80]}: {s.get('summary', '?')[:80]}")
        
        return {
            "project": project,
            "sessions_count": len(sessions),
            "last_session": sessions[-1].get("query", "") if sessions else None,
            "summary": "\n".join(summary_parts),
            "recent_sessions": sessions[-5:]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v4/users/{user_id}/projects")
async def list_projects(user_id: str):
    """Список проектов пользователя."""
    user_dir = _get_user_dir(user_id)
    if not os.path.exists(user_dir):
        return {"projects": []}
    
    projects = []
    for f in os.listdir(user_dir):
        if f.endswith('.json'):
            proj_name = f[:-5]
            data = json.load(open(os.path.join(user_dir, f)))
            projects.append({
                "name": proj_name,
                "sessions": len(data),
                "last_active": data[-1].get("timestamp", 0) if data else 0
            })
    return {"projects": sorted(projects, key=lambda x: -x['last_active'])}

# ========== CUBE CREATION API ==========
class CubeCreate(BaseModel):
    title: str
    text: str
    user_id: str = "anonymous"
    shared: bool = False  # опубликовать в общий граф?

@router.post("/api/v4/cubes")
async def create_cube(data: CubeCreate):
    """Создаёт новый куб с авто-эмбеддингом через Polza API."""
    try:
        from app.routers.v4_middleware import get_embedding_cached
        from app.routers.v4_graph import get_graph
        from app.routers.tensor_cube import TensorCube
        import numpy as np, uuid, time
        
        # Генерируем эмбеддинг
        embedding = get_embedding_cached(data.text)
        
        # Создаём куб
        cube_id = f"cube_{uuid.uuid4().hex[:12]}"
        tc = TensorCube(cube_id, np.array(embedding, dtype=np.float32))
        tc.metadata = {
            "title": data.title,
            "text": data.text[:500],
            "user_id": data.user_id,
            "shared": data.shared,
            "usage_count": 0,
            "stability": 0.5,
            "created_at": time.time()
        }
        
        # Добавляем в граф
        _graph = get_graph()
        _graph[cube_id] = tc
        
        # Связываем с похожими кубами через cosine similarity
        for existing_id, existing_cube in list(_graph.items())[:50]:
            if existing_id != cube_id:
                sim = float(np.dot(tc.vector, existing_cube.vector))
                if sim > 0.7:
                    tc.add_connection(existing_id, sim)
                    existing_cube.add_connection(cube_id, sim)
        
        return {
            "status": "created",
            "cube_id": cube_id,
            "title": data.title,
            "connections": len(tc.connections),
            "total_cubes": len(_graph)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
