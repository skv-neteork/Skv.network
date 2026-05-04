from fastapi import APIRouter, HTTPException, Request
from app.models import EntryResponse
import uuid
import json
import os
from datetime import datetime, timezone

router = APIRouter()

entries_db = {}
delete_tokens = {}
cubes_library = {}

KNOWLEDGE_DIR = "/knowledge_library"

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

            # Файл с полем "cubes" (конституция)
            if "cubes" in data and isinstance(data["cubes"], list):
                for cube in data["cubes"]:
                    cube_id = cube.get("cube_id", str(uuid.uuid4()))
                    entry_id = str(uuid.uuid4())
                    entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": cube}
                    cubes_library[cube_id] = {
                        "id": entry_id,
                        "cube_id": cube_id,
                        "title": cube.get("title", "Untitled"),
                        "content": cube,
                        "triggers": cube.get("trigger_intent", []),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "source_file": fname
                    }
                    loaded += 1
            # Файл с полем "answer" (cubes_*.json)
            elif "answer" in data:
                ans = data["answer"]
                if isinstance(ans, str):
                    try:
                        cubes = json.loads(ans)
                    except Exception:
                        continue
                else:
                    cubes = ans
                if isinstance(cubes, list):
                    for cube in cubes:
                        cube_id = cube.get("cube_id", str(uuid.uuid4()))
                        entry_id = str(uuid.uuid4())
                        entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": cube}
                        cubes_library[cube_id] = {
                            "id": entry_id,
                            "cube_id": cube_id,
                            "title": cube.get("title", "Untitled"),
                            "content": cube,
                            "triggers": cube.get("trigger_intent", []),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "source_file": fname
                        }
                        loaded += 1
            # Обычный файл
            else:
                cube_id = data.get("cube_id") or data.get("anketa_id") or fname.replace(".json", "")
                title = data.get("title") or data.get("project_name") or fname
                triggers = data.get("trigger_intent", [])
                entry_id = str(uuid.uuid4())
                entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": data}
                cubes_library[cube_id] = {
                    "id": entry_id,
                    "cube_id": cube_id,
                    "title": title,
                    "content": data,
                    "triggers": triggers,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_file": fpath
                }
                loaded += 1
    print(f"[SKV] Loaded {loaded} cubes from {KNOWLEDGE_DIR}")

load_cubes_from_disk()

@router.post("/api/v1/entries", response_model=EntryResponse, status_code=201)
async def create_entry(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    entry_id = str(uuid.uuid4())
    delete_token = f"skv_del_{uuid.uuid4().hex[:24]}"
    entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": body}
    cube_id = body.get("cube_id") or body.get("user_fields", {}).get("cube_id", entry_id)
    cubes_library[cube_id] = {"id": entry_id, "cube_id": cube_id, "title": body.get("title") or body.get("user_fields", {}).get("title", "Cube"), "content": body, "triggers": body.get("trigger_intent") or body.get("user_fields", {}).get("trigger_intent", []), "created_at": datetime.now(timezone.utc).isoformat()}
    delete_tokens[delete_token] = entry_id
    index_cube_in_qdrant(cube_id, body.get("title", "Cube"), body.get("rules", []), body.get("trigger_intent", []))
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
async def search_cubes(query: str = ""):
    results = []
    for cube_id, cube in cubes_library.items():
        title = cube.get("title", "")
        triggers = cube.get("triggers", [])
        if query.lower() in title.lower() or any(query.lower() in t.lower() for t in triggers):
            results.append({"id": cube["id"], "cube_id": cube_id, "title": title, "triggers": triggers})
    return {"results": results, "count": len(results), "query": query}

@router.post("/api/session/export")
async def export_session(data: dict):
    session_id = str(uuid.uuid4())
    data["session_id"] = session_id
    data["exported_at"] = datetime.now(timezone.utc).isoformat()
    entries_db[session_id] = {"id": session_id, "data": data, "created_at": datetime.now(timezone.utc).isoformat()}
    return {"status": "saved", "session_id": session_id}

def index_cube_in_qdrant(cube_id, title, rules, triggers):
    try:
        import urllib.request as _req
        text = f"Title: {title}\nTriggers: {', '.join(triggers)}\nRules: {'; '.join(rules[:5])}"
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": text[:2000]}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"
        })
        embedding = json.loads(_req.urlopen(emb_req, timeout=15).read())["data"][0]["embedding"]
        import hashlib
        point_id = int(hashlib.md5(cube_id.encode()).hexdigest()[:8], 16) % 1000000
        upsert_body = json.dumps({"points": [{
            "id": point_id,
            "vector": embedding,
            "payload": {"cube_id": cube_id, "title": title, "text": text[:500]}
        }]}).encode()
        upsert_req = _req.Request("http://127.0.0.1:6333/collections/skv_rules_v2/points", data=upsert_body, method="PUT")
        _req.urlopen(upsert_req, timeout=10)
        print(f"[SKV] Indexed cube {cube_id} in Qdrant")
    except Exception as e:
        print(f"[SKV] Qdrant index error for {cube_id}: {e}")

def get_cubes_count():
    return len(cubes_library)
