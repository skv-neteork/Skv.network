"""Auto-consolidation: сжатие длинных сессий в кубы опыта."""
import json, os, asyncio
from datetime import datetime, timezone

async def consolidate_session(user_id: str, project: str, max_messages: int = 50):
    """Сжать сессию в куб опыта если она превысила лимит."""
    memory_path = f"/app/app/runtime/memory/{user_id}/{project}.json"
    
    if not os.path.exists(memory_path):
        return None
    
    with open(memory_path) as f:
        data = json.load(f)
    
    sessions = data.get("sessions", [])
    if len(sessions) < max_messages:
        return None
    
    # Собираем все запросы и ответы
    dialogue = "\n".join([
        f"Q: {s.get('query','')}\nA: {s.get('response','')[:200]}"
        for s in sessions[-max_messages:]
    ])
    
    # Создаём куб опыта из сессии
    cube = {
        "cube_id": f"session_{user_id}_{project}_{int(datetime.now().timestamp())}",
        "type": "experience",
        "priority": 2,
        "title": f"Session: {project} — {datetime.now().strftime('%Y-%m-%d')}",
        "trigger_intent": [project, user_id],
        "rules": [
            f"MUST consider previous context from {len(sessions)} sessions",
            f"MUST reference key decisions from project {project}"
        ],
        "rationale": f"Auto-consolidated from {len(sessions)} sessions in project {project}",
        "source": "session_evolver",
        "metadata": {
            "cube_type": "EPISODIC",
            "session_count": len(sessions),
            "consolidated_at": datetime.now(timezone.utc).isoformat()
        }
    }
    
    # Сохраняем куб в граф
    try:
        from app.routers.v4_graph import _v4_graph, get_graph
        from app.routers.tensor_cube import TensorCube
        import numpy as np
        
        get_graph()
        
        # Создаём вектор из текста диалога
        from app.routers.v4_middleware import get_embedding_cached
        vector = get_embedding_cached(dialogue[:500])
        
        tc = TensorCube(cube["cube_id"], vector, metadata=cube["metadata"])
        tc.metadata["title"] = cube["title"]
        tc.metadata["rules"] = cube["rules"]
        tc.metadata["cube_type"] = "EPISODIC"
        
        _v4_graph[cube["cube_id"]] = tc
        
        # Оставляем последние 10 сообщений, остальное заменяем ссылкой на куб
        data["sessions"] = sessions[-10:]
        data["consolidated_cube"] = cube["cube_id"]
        
        with open(memory_path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[EVOLVER] Session consolidated: {project} → {cube['cube_id'][:20]}", flush=True)
        return cube["cube_id"]
        
    except Exception as e:
        print(f"[EVOLVER] Consolidation error: {e}", flush=True)
        return None

async def run_session_evolver():
    """Фоновый воркер: проверяет сессии раз в час."""
    while True:
        await asyncio.sleep(3600)
        try:
            memory_dir = "/app/app/runtime/memory"
            if not os.path.exists(memory_dir):
                continue
            
            for user_id in os.listdir(memory_dir):
                user_dir = os.path.join(memory_dir, user_id)
                if not os.path.isdir(user_dir):
                    continue
                
                for fname in os.listdir(user_dir):
                    if fname.endswith('.json'):
                        project = fname.replace('.json', '')
                        await consolidate_session(user_id, project)
        except Exception as e:
            print(f"[EVOLVER] Cycle error: {e}", flush=True)
