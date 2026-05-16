"""Startup events for SKV Network."""
import asyncpg
import json
import uuid
from app.routers.entries import cubes_library

DATABASE_URL = "postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db"

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
        # Core Hierarchy
        "cube_basic_ethics_01",           # Safety & User Respect
        "cube_basic_moral_compass_01",    # Moral Compass
        "cube_basic_honesty_01",          # Honesty & Truth-Seeking
        "cube_basic_transparency_01",     # Transparency
        "cube_const_anti_jailbreak_v1",   # Anti-Manipulation
        "cube_const_natural_response_style_v1",  # Natural Response Style
    "cube_basic_time_awareness_v1",
    "const_memory_pyramid_v1",
        "cube_const_calibration_v1",      # Calibration & Over-Refusal Prevention
        "const_evolver_protocol_v1",      # Governance & Self-Improvement
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
