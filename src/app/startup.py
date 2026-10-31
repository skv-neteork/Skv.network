import os
"""Startup events for SKV Network."""
import asyncpg
import json
import uuid
from app.routers.entries import cubes_library

DATABASE_URL = os.getenv("DATABASE_URL", "")

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
    #await load_cubes_from_postgresql()
    await preload_constitution()

# Предзагружаем конституцию один раз
CONSTITUTION_TEXT = [""]

async def preload_constitution():
    """Preload a short constitution digest from the live source (SQLite cubes_new, the same rows
    GET /api/v7/constitution serves). The old version read the in-memory v4 cubes_library, which is
    no longer loaded at startup (PostgreSQL load disabled), so it always printed 0 chars."""
    global CONSTITUTION_TEXT
    text, src = "", ""
    try:
        from app.routers.v7_guards import get_constitution_v8
        d = await get_constitution_v8()
        parts = [f"{c['cube']}: {(c.get('essence') or '').strip()}" for c in d.get("cubes", []) if (c.get("essence") or "").strip()]
        if parts:
            text, src = "SKV Constitution: " + " | ".join(parts), f"cubes_new ({len(parts)} cubes)"
    except Exception as e:
        print(f"[SKV] Constitution preload (cubes_new) failed: {e}", flush=True)
    if not text:
        try:
            from app import memory_v2 as _mv2
            text, src = _mv2.constitution_compact() or "", "constitution_compact file"
        except Exception as e:
            print(f"[SKV] Constitution preload (compact file) failed: {e}", flush=True)
    CONSTITUTION_TEXT[0] = text
    print(f"[SKV] Constitution preloaded: {len(text)} chars from {src or 'nothing'}", flush=True)
