"""Session Evolver v4.5 — PostgreSQL-backed consolidation."""

import asyncio
import time
import numpy as np

async def consolidate_session(user_id: str, project: str):
    """Сжать сессии из PostgreSQL в experience cube."""
    try:
        import asyncpg
        conn = await asyncpg.connect("postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db")
        
        # Считаем количество сессий
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM user_sessions WHERE user_id = $1 AND project_ref = $2",
            user_id, project
        )
        count = row['cnt'] if row else 0
        
        if count < 10:
            await conn.close()
            return None
        
        # Загружаем последние 10 сессий
        rows = await conn.fetch(
            "SELECT data FROM user_sessions WHERE user_id = $1 AND project_ref = $2 ORDER BY updated_at DESC LIMIT 10",
            user_id, project
        )
        
        sessions = [dict(r['data']) if isinstance(r['data'], dict) else {} for r in rows]
        
        # Собираем диалог
        dialogue = "\n".join([
            f"Q: {s.get('query','')}\nA: {s.get('response','')[:200]}"
            for s in sessions if s
        ])
        
        # Создаём вектор
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
            "title": f"Session: {project} — {count} messages",
            "rules": [f"MUST consider context from {count} messages in project {project}"],
            "cube_type": "EPISODIC",
            "importance": min(1.0, count / 50),
            "source": "session-evolver",
            "consolidated_at": time.time()
        })
        
        _v4_graph[cube_id] = tc
        
        # Удаляем старые сессии, оставляем последние 5
        await conn.execute(
            "DELETE FROM user_sessions WHERE user_id = $1 AND project_ref = $2 AND id NOT IN (SELECT id FROM user_sessions WHERE user_id = $1 AND project_ref = $2 ORDER BY updated_at DESC LIMIT 5)",
            user_id, project
        )
        
        await conn.close()
        print(f"[EVOLVER] Consolidated: {project} — {count} msgs → cube {cube_id[:20]}", flush=True)
        return cube_id
        
    except Exception as e:
        print(f"[EVOLVER] Error: {e}", flush=True)
        return None

async def run_session_evolver():
    """Проверяет PostgreSQL каждые 60 секунд."""
    while True:
        await asyncio.sleep(60)
        try:
            import asyncpg
            conn = await asyncpg.connect("postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db")
            
            # Находим пользователей с >10 сессиями
            rows = await conn.fetch(
                "SELECT user_id, project_ref, COUNT(*) as cnt FROM user_sessions GROUP BY user_id, project_ref HAVING COUNT(*) >= 10"
            )
            
            for row in rows:
                await consolidate_session(row['user_id'], row['project_ref'])
            
            await conn.close()
        except Exception as e:
            print(f"[EVOLVER] Cycle error: {e}", flush=True)
