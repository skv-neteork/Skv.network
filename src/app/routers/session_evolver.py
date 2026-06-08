"""Session Evolver v4.1 — Realtime consolidation every 10 messages."""

import os, json, time, asyncio
import numpy as np

async def consolidate_session(user_id: str, project: str):
    """Сжать сессию в куб опыта при достижении 10 сообщений."""
    memory_path = f"/app/app/runtime/memory/{user_id}/{project}.json"
    
    if not os.path.exists(memory_path):
        return None
    
    with open(memory_path) as f:
        data = json.load(f)
    
    sessions = data.get("sessions", [])
    if len(sessions) < 10:
        return None
    
    # Берём последние 10 сообщений
    recent = sessions[-10:]
    
    # Собираем диалог
    dialogue = "\n".join([
        f"Q: {s.get('query','')}\nA: {s.get('response','')[:200]}"
        for s in recent
    ])
    
    # Создаём вектор из диалога
    try:
        from app.routers.v4_middleware import get_embedding_cached
        vector = get_embedding_cached(dialogue[:500])
    except:
        vector = [0.1] * 1536
    
    # Создаём куб опыта
    from app.routers.v4_graph import _v4_graph, get_graph
    from app.routers.tensor_cube import TensorCube
    
    get_graph()
    
    cube_id = f"evolved_{user_id}_{project}_{int(time.time())}"
    tc = TensorCube(cube_id, np.array(vector, dtype=np.float32), metadata={
        "title": f"Session: {project} — {len(sessions)} messages",
        "rules": [
            f"MUST consider context from {len(sessions)} previous messages",
            f"MUST reference project: {project}"
        ],
        "cube_type": "EPISODIC",
        "importance": min(1.0, len(sessions) / 50),  # Emotional tagging
        "source": "realtime-evolver",
        "consolidated_at": time.time(),
        "message_count": len(sessions)
    })
    
    _v4_graph[cube_id] = tc
    
    # Оставляем последние 5 сообщений, остальное — в кубе
    data["sessions"] = sessions[-5:]
    data["consolidated_cubes"] = data.get("consolidated_cubes", [])
    data["consolidated_cubes"].append(cube_id)
    
    with open(memory_path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[EVOLVER] Realtime consolidation: {project} → {cube_id[:20]} ({len(sessions)} msgs)", flush=True)
    return cube_id

async def run_session_evolver():
    """Фоновый воркер — проверяет сессии каждые 60 секунд."""
    while True:
        await asyncio.sleep(60)
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
            print(f"[EVOLVER] Error: {e}", flush=True)
