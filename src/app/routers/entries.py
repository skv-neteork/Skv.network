POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"

from fastapi import APIRouter, HTTPException, Request, Response
from app.schemas.common import EntryResponse
import uuid
import json
import os
import hashlib
import asyncio
import asyncpg
from datetime import datetime, timezone
from app.cache import cache

router = APIRouter()

entries_db = {}
delete_tokens = {}
cubes_library = {}

KNOWLEDGE_DIR = "/knowledge_library"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://skv_user:skv_secret_2026@127.0.0.1:5432/skv_db")

async def _index_to_qdrant(cube_id, title, trigger_intent, rules):
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
        import urllib.request as _req
        import uuid as _uuid
        
        text = f"{title}: {' '.join(trigger_intent)} {' '.join(rules)}"[:500]
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": text}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        emb_resp = json.loads(_req.urlopen(emb_req, timeout=15).read())
        vector = emb_resp["data"][0]["embedding"]
        
        client = QdrantClient(host="127.0.0.1", port=6333)
        point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, cube_id))
        client.upsert(
            collection_name="skv_rules_v2",
            points=[PointStruct(id=point_id, vector=vector, payload={
                "cube_id": cube_id, "title": title,
                "triggers": trigger_intent, "text": " ".join(rules)
            })]
        )
        print(f"[SKV] Indexed in Qdrant: {cube_id}")
    except Exception as e:
        print(f"[SKV] Qdrant index error for {cube_id}: {e}")

async def _save_cube_to_db(cube_id, title, cube_type, priority, trigger_intent, rules, content, status="community"):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO cubes (cube_id, title, type, priority, version, trigger_intent, rules, content, status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (cube_id) DO UPDATE SET title=$2, type=$3, priority=$4, trigger_intent=$6, rules=$7, content=$8, status=$9, updated_at=NOW()",
            cube_id, title, cube_type, priority, "1.0.0", json.dumps(trigger_intent), json.dumps(rules), json.dumps(content), status
        )
        await conn.close()
        print(f"[SKV] Saved to DB: {cube_id}")
    except Exception as e:
        print(f"[SKV] DB save error for {cube_id}: {e}")

def load_cubes_from_disk():
    loaded = 0
    for root, dirs, files in os.walk(KNOWLEDGE_DIR):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r") as f:
                    data = json.load(f)
            except Exception:
                continue

            if "cubes" in data and isinstance(data["cubes"], list):
                for cube in data["cubes"]:
                    cube_id = cube.get("cube_id", str(uuid.uuid4()))
                    entry_id = str(uuid.uuid4())
                    entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": cube}
                    cubes_library[cube_id] = {
                        "id": entry_id, "cube_id": cube_id,
                        "title": cube.get("title", "Untitled"),
                        "content": cube,
                        "triggers": cube.get("trigger_intent", []),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "source_file": fname
                    }
                    loaded += 1
            else:
                cube_id = data.get("cube_id") or data.get("anketa_id") or fname.replace(".json", "")
                title = data.get("title") or data.get("project_name") or fname
                triggers = data.get("trigger_intent", [])
                entry_id = str(uuid.uuid4())
                entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": data}
                cubes_library[cube_id] = {
                    "id": entry_id, "cube_id": cube_id,
                    "title": title,
                    "content": data,
                    "triggers": triggers,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_file": fpath
                }
                loaded += 1
    print(f"[SKV] Loaded {loaded} cubes from {KNOWLEDGE_DIR}")

# load_cubes_from_disk()  # Disabled, using PostgreSQL

# === Эндпоинты ===

@router.post("/api/v1/entries", status_code=201)
async def create_entry(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    entry_id = str(uuid.uuid4())
    delete_token = f"skv_del_{uuid.uuid4().hex[:24]}"
    entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": body}

    # Массовая загрузка
    if "cubes" in body and isinstance(body["cubes"], list):
        loaded = []
        for cube_data in body["cubes"]:
            cid = cube_data.get("cube_id", f"{entry_id}_{len(loaded)}")
            c_entry_id = str(uuid.uuid4())
            entries_db[c_entry_id] = {"id": c_entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": cube_data}
            cubes_library[cid] = {"id": c_entry_id, "cube_id": cid, "title": cube_data.get("title", f"Cube"), "content": cube_data, "triggers": cube_data.get("trigger_intent", []), "created_at": datetime.now(timezone.utc).isoformat()}
            loaded.append({"cube_id": cid, "id": c_entry_id})
            # Авто-индексация в Qdrant
            try:
                import asyncio
                asyncio.create_task(_save_cube_to_db(cid, cube_data.get("title", "Cube"), cube_data.get("type", "experience"), cube_data.get("priority", 3), cube_data.get("trigger_intent", []), cube_data.get("rules", []), cube_data))
            except:
                pass
            # Сохраняем в БД и индексируем в Qdrant
            asyncio.create_task(_save_cube_to_db(cid, cube_data.get("title", "Cube"), cube_data.get("type", "experience"), cube_data.get("priority", 3), cube_data.get("trigger_intent", []), cube_data.get("rules", []), cube_data))
            asyncio.create_task(_index_to_qdrant(cid, cube_data.get("title", "Cube"), cube_data.get("trigger_intent", []), cube_data.get("rules", [])))
        delete_tokens[delete_token] = entry_id
        cache.clear()
        return {"id": entry_id, "public_url": f"/api/v1/entries/{entry_id}", "delete_token": delete_token, "cubes_loaded": len(loaded), "cubes": loaded}

    # Одиночная загрузка
    cube_id = body.get("cube_id") or body.get("user_fields", {}).get("cube_id", entry_id)
    cubes_library[cube_id] = {"id": entry_id, "cube_id": cube_id, "title": body.get("title") or body.get("user_fields", {}).get("title", "Cube"), "content": body, "triggers": body.get("trigger_intent") or body.get("user_fields", {}).get("trigger_intent", []), "created_at": datetime.now(timezone.utc).isoformat()}
    delete_tokens[delete_token] = entry_id
    cache.clear()
    # Сохраняем в БД и индексируем в Qdrant
    asyncio.create_task(_save_cube_to_db(cube_id, body.get("title", "Cube"), body.get("type", "experience"), body.get("priority", 3), body.get("trigger_intent", []), body.get("rules", []), body))
    asyncio.create_task(_index_to_qdrant(cube_id, body.get("title", "Cube"), body.get("trigger_intent", []), body.get("rules", [])))
    return {"id": entry_id, "public_url": f"/api/v1/entries/{entry_id}", "delete_token": delete_token}

@router.get("/api/v1/entries/{entry_id}")
async def get_entry(entry_id: str):
    entry = entries_db.get(entry_id) or cubes_library.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    data = entry.get("data") or entry.get("content") or entry
    return data

@router.get("/api/v1/entries/{entry_id}/export")
async def export_entry(entry_id: str):
    entry = entries_db.get(entry_id) or cubes_library.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    data = entry.get("data") or entry.get("content") or entry
    return data

@router.get("/api/cubes/search")
async def search_cubes(query: str = "", response: Response = None):
    cache_key = f"search:{hashlib.md5(query.encode()).hexdigest()[:12]}"
    cached = cache.get(cache_key)
    if cached:
        if response:
            response.headers["X-Cache-Status"] = "HIT"
        return cached

    results = []
    if query and len(query.strip()) > 0:
        try:
            from qdrant_client import QdrantClient
            import urllib.request as _req
            # Embed запрос
            emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
            emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
            })
            emb_resp = json.loads(_req.urlopen(emb_req, timeout=15).read())
            qv = emb_resp["data"][0]["embedding"]
            
            client = QdrantClient(host="127.0.0.1", port=6333)
            qdrant_results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=20)
            
            for r in qdrant_results.points:
                payload = r.payload
                results.append({
                    "id": str(r.id),
                    "cube_id": payload.get("cube_id", ""),
                    "title": payload.get("title", ""),
                    "triggers": payload.get("triggers", payload.get("trigger_intent", []))
                })
        except Exception as e:
            # Fallback: substring search
            for cube_id, cube in cubes_library.items():
                title = cube.get("title", "")
                triggers = cube.get("triggers", [])
                if query.lower() in title.lower() or any(query.lower() in t.lower() for t in triggers):
                    results.append({"id": cube.get("id", ""), "cube_id": cube_id, "title": title, "triggers": triggers})

    result = {"results": results, "count": len(results), "query": query}
    cache.set(cache_key, result, ttl=300)
    if response:
        response.headers["X-Cache-Status"] = "MISS"
    return result

@router.post("/api/session/export")
async def export_session(data: dict):
    session_id = str(uuid.uuid4())
    data["session_id"] = session_id
    data["exported_at"] = datetime.now(timezone.utc).isoformat()
    entries_db[session_id] = {"id": session_id, "data": data, "created_at": datetime.now(timezone.utc).isoformat()}
    return {"status": "saved", "session_id": session_id}

_feedback = {}

@router.post("/api/feedback")
async def feedback(cube_id: str, vote: str = "up", comment: str = ""):
    if cube_id not in cubes_library:
        raise HTTPException(status_code=404, detail="Cube not found")
    if cube_id not in _feedback:
        _feedback[cube_id] = {"upvotes": 0, "downvotes": 0, "reviews": []}
    if vote == "up":
        _feedback[cube_id]["upvotes"] += 1
    elif vote == "down":
        _feedback[cube_id]["downvotes"] += 1
        _feedback[cube_id]["reviews"].append({"comment": comment, "timestamp": datetime.now(timezone.utc).isoformat()})
    return {"status": "ok", "feedback": _feedback[cube_id]}

@router.get("/api/feedback/{cube_id}")
async def get_feedback(cube_id: str):
    return {"cube_id": cube_id, "feedback": _feedback.get(cube_id, {"upvotes": 0, "downvotes": 0, "reviews": []})}

def get_cubes_count():
    return len(cubes_library)
