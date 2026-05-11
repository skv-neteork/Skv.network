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
    await preload_constitution()

# Предзагружаем конституцию один раз
CONSTITUTION_TEXT = [""]

async def preload_constitution():
    global CONSTITUTION_TEXT
    from app.routers.entries import cubes_library
    CONSTITUTION_CUBES = [
        "cube_basic_structure_01", "cube_basic_discovery_01", "cube_basic_priority_01",
        "cube_basic_ethics_01", "cube_basic_transparency_01", "cube_basic_human_override_01",
        "cube_basic_feedback_01", "cube_basic_creation_01", "cube_basic_antipoisoning_01",
        "cube_basic_links_01", "cube_basic_efficiency_01",
        "cube_const_response_style_v1",
        "cube_const_natural_response_style_v1",
    "cube_basic_moral_compass_01",
    "cube_basic_empathy_01",
    "cube_basic_honesty_01",
    "cube_basic_boundaries_01",
    ]
    rules = []
    for cid in CONSTITUTION_CUBES:
        if cid in cubes_library:
            cube = cubes_library[cid]
            content_data = cube.get("content", {})
            if isinstance(content_data, dict):
                rules.extend(content_data.get("rules", [])[:2])
    CONSTITUTION_TEXT[0] = "SKV Constitution: " + " | ".join(rules[:10]) if rules else ""
    print(f"[SKV] Constitution preloaded: {len(CONSTITUTION_TEXT[0])} chars")
