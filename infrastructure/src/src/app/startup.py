"""Startup events for SKV Network."""
import asyncpg
import json
import uuid
from app.routers.entries import cubes_library

DATABASE_URL = "postgresql://skv_user:skv_secret_2026@127.0.0.1:5432/skv_db"

async def load_cubes_from_postgresql():
    """Загружает кубики из PostgreSQL при старте."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT * FROM cubes")
        await conn.close()
        for row in rows:
            cube_id = row["cube_id"]
            if cube_id not in cubes_library:
                content_data = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
                triggers_data = json.loads(row["trigger_intent"]) if isinstance(row["trigger_intent"], str) else row["trigger_intent"]
                cubes_library[cube_id] = {
                    "id": str(uuid.uuid4()),
                    "cube_id": cube_id,
                    "title": row["title"],
                    "content": content_data,
                    "triggers": triggers_data,
                    "status": row["status"],
                    "created_at": str(row["created_at"])
                }
        print(f"[SKV] Loaded {len(rows)} cubes from PostgreSQL at startup")
    except Exception as e:
        print(f"[SKV] Startup DB error: {e}")

async def startup():
    """Выполняется при старте FastAPI."""
    await load_cubes_from_postgresql()
