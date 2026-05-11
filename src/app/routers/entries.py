import json, uuid, hashlib, asyncio, subprocess, psycopg2
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Response

POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"
DATABASE_URL = "postgresql://skv_user:skv_secret_2026@127.0.0.1:5432/skv_db"

router = APIRouter()
entries_db = {}
cubes_library = {}
delete_tokens = {}
_feedback = {}
cache = None  # Будет установлен из main.py

# --- Функция загрузки кубиков с диска (только для инициализации) ---
def load_cubes_from_disk():
    import os
    knowledge_dir = "/knowledge_library"
    if not os.path.exists(knowledge_dir):
        return
    for root, dirs, files in os.walk(knowledge_dir):
        for file in files:
            if file.endswith('.json'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    # Поддержка разных форматов файлов
                    cubes = data.get('cubes', [])
                    if not cubes and isinstance(data, list):
                        cubes = data
                    for cube in cubes:
                        if isinstance(cube, dict) and 'cube_id' in cube:
                            cid = cube['cube_id']
                            cubes_library[cid] = {
                                "id": str(uuid.uuid4()),
                                "cube_id": cid,
                                "title": cube.get('title', 'Untitled'),
                                "content": cube,
                                "triggers": cube.get('trigger_intent', []),
                                "created_at": datetime.now(timezone.utc).isoformat()
                            }
                except Exception as e:
                    print(f"[SKV] Disk load error: {e}")

# Загружаем кубики с диска при импорте модуля
load_cubes_from_disk()

# Загружаем кубики из БД синхронно при импорте
def load_cubes_from_db():
    try:
        import psycopg2, json as json_lib
        conn = psycopg2.connect(
            host="127.0.0.1", port=5432,
            dbname="skv_db", user="skv_user", password="skv_secret_2026"
        )
        cur = conn.cursor()
        cur.execute("SELECT cube_id, title, type, trigger_intent, rules, status, created_at, content FROM cubes")
        for row in cur.fetchall():
            cube_id = row[0]
            if cube_id not in cubes_library:
                triggers = row[3]
                if isinstance(triggers, str):
                    triggers = json_lib.loads(triggers)
                cubes_library[cube_id] = {
                    "id": str(uuid.uuid4()),
                    "cube_id": cube_id,
                    "title": row[1],
                    "content": (json_lib.loads(row["content"]) if row["content"] and row["content"] != '{}' else ({"rules": json_lib.loads(row["rules"])} if row["rules"] and row["rules"] != '[]' else {})) if isinstance(row["content"], str) else (row["content"] if row["content"] and row["content"] != {} else ({"rules": json_lib.loads(row["rules"])} if row["rules"] and row["rules"] != '[]' else {})),
                    "triggers": triggers if triggers else [],
                    "status": row[5] or "community",
                    "created_at": str(row[6]) if row[6] else ""
                }
        cur.close()
        conn.close()
        print(f"[SKV] Loaded {len(cubes_library)} cubes total (disk + DB)")
    except Exception as e:
        print(f"[SKV] DB load error: {e}")

load_cubes_from_db()

# --- Вспомогательная функция для сохранения в БД ---
async def _save_cube_to_db(cube_id, title, cube_type, priority, trigger_intent, rules, content, status="community"):
    try:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO cubes (cube_id, title, type, priority, version, trigger_intent, rules, content, status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (cube_id) DO UPDATE SET title=$2, type=$3, priority=$4, trigger_intent=$6, rules=$7, content=$8, status=$9, updated_at=NOW()",
            cube_id, title, cube_type, priority, "1.0.0", json.dumps(trigger_intent), json.dumps(rules), json.dumps(content), status
        )
        await conn.close()
        print(f"[SKV] Saved to DB: {cube_id}")
    except Exception as e:
        print(f"[SKV] DB save error for {cube_id}: {e}")

# --- Эндпоинты ---
@router.post("/api/v1/entries", status_code=201)
async def create_entry(request: Request):
    try:
        body = await request.json()
        print(f"[DEBUG] 📥 Request body keys: {list(body.keys())}")
        print(f"[DEBUG] 🔑 Has persona: {'persona' in body}")
        print(f"[DEBUG] 🔑 Has cubes: {'cubes' in body}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    entry_id = str(uuid.uuid4())
    delete_token = f"skv_del_{uuid.uuid4().hex[:24]}"
    entries_db[entry_id] = {"id": entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": body}

    # Массовая загрузка кубиков
    if "cubes" in body and isinstance(body["cubes"], list):
        loaded = []
        for cube_data in body["cubes"]:
            cid = cube_data.get("cube_id", f"{entry_id}_{len(loaded)}")
            c_entry_id = str(uuid.uuid4())
            entries_db[c_entry_id] = {"id": c_entry_id, "created_at": datetime.now(timezone.utc).isoformat(), "data": cube_data}
            
            # Сохраняем persona в каждом кубике
            merged_data = cube_data.copy()
            if "persona" in body:
                merged_data["persona"] = body["persona"]
            
            # Нормализация правил (если пришли как словари)
            raw_rules = cube_data.get("rules", [])
            normalized_rules = []
            for r in raw_rules:
                if isinstance(r, dict):
                    normalized_rules.append(r.get("rule", str(r)))
                elif isinstance(r, str):
                    normalized_rules.append(r)
                else:
                    normalized_rules.append(str(r))
            cube_data["rules"] = normalized_rules
            cubes_library[cid] = {"id": c_entry_id, "cube_id": cid, "title": cube_data.get("title", "Cube"), "content": merged_data, "triggers": cube_data.get("trigger_intent", []), "created_at": datetime.now(timezone.utc).isoformat()}
            loaded.append({"cube_id": cid, "id": c_entry_id})
            
            # Сохраняем в БД
            asyncio.create_task(_save_cube_to_db(cid, cube_data.get("title", "Cube"), cube_data.get("type", "experience"), cube_data.get("priority", 3), cube_data.get("trigger_intent", []), cube_data.get("rules", []), merged_data))
        
            # Сохраняем связи кубика (если есть based_on)
            if "links" in body and isinstance(body.get("links"), dict):
                links_data = body["links"]
                direct = links_data.get("direct", {})
                based_on = direct.get("based_on")
                if based_on:
                    try:
                        import psycopg2 as pg2
                        pg_conn = pg2.connect(
                            host="127.0.0.1", port=5432,
                            dbname="skv_db", user="skv_user", password="skv_secret_2026"
                        )
                        cur = pg_conn.cursor()
                        for cid in [c.get("cube_id") for c in body.get("cubes", [])]:
                            cur.execute(
                                "INSERT INTO cube_links (cube_id, linked_cube_id, link_type) VALUES (%s, %s, 'based_on') ON CONFLICT DO NOTHING",
                                (cid, based_on)
                            )
                        pg_conn.commit()
                        cur.close()
                        pg_conn.close()
                        print(f"[SKV] Links saved: {len(body.get('cubes', []))} cubes -> {based_on}")
                    except Exception as e:
                        print(f"[SKV] Link save error: {e}")

            # Косвенные связи: shared_cubes
            if "cubes" in body:
                try:
                    import psycopg2 as pg2
                    pg_conn = pg2.connect(
                        host="127.0.0.1", port=5432,
                        dbname="skv_db", user="skv_user", password="skv_secret_2026"
                    )
                    cur = pg_conn.cursor()
                    all_triggers = []
                    for c in body.get("cubes", []):
                        all_triggers.extend(c.get("trigger_intent", []))
                    
                    if all_triggers:
                        for trigger in all_triggers[:5]:
                            cur.execute(
                                "SELECT DISTINCT cube_id FROM cubes WHERE trigger_intent::text LIKE %s",
                                (f"%{trigger}%",)
                            )
                            related = cur.fetchall()
                            for row in related:
                                for cid in [c.get("cube_id") for c in body.get("cubes", [])]:
                                    if row[0] != cid:
                                        cur.execute(
                                            "INSERT INTO cube_links (cube_id, linked_cube_id, link_type) VALUES (%s, %s, 'shared_cubes') ON CONFLICT DO NOTHING",
                                            (cid, row[0])
                                        )
                    
                    pg_conn.commit()
                    cur.close()
                    pg_conn.close()
                    print(f"[SKV] Indirect links (shared_cubes) saved")
                except Exception as e:
                    print(f"[SKV] Indirect link error: {e}")

        # Автоматически сохраняем persona в профиль
        if "persona" in body:
            persona_data = body["persona"]
            user_id = persona_data.get("user_id", "unknown")
            try:
                pg_conn = psycopg2.connect(
                    host="127.0.0.1", port=5432,
                    dbname="skv_db", user="skv_user", password="skv_secret_2026"
                )
                cur = pg_conn.cursor()
                persona_json = json.dumps(persona_data)
                cur.execute(
                    "INSERT INTO user_personas (user_id, persona) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET persona = EXCLUDED.persona, updated_at = NOW()",
                    (user_id, persona_json)
                )
                pg_conn.commit()
                cur.close()
                pg_conn.close()
                print(f"[SKV] Persona saved for {user_id}")
            except Exception as e:
                import traceback
                print(f"[SKV] Persona save error: {e}")
                traceback.print_exc()
        
        # Обработка фидбэка
        if "feedback" in body and isinstance(body["feedback"], list):
            for fb in body["feedback"]:
                try:
                    fb_cube_id = fb.get("cube_id", "")
                    fb_vote = fb.get("vote", "up")
                    fb_comment = fb.get("comment", "").replace("'", "''")
                    if fb_cube_id and fb_vote in ("up", "down"):
                        pg_conn = psycopg2.connect(
                            host="127.0.0.1", port=5432,
                            dbname="skv_db", user="skv_user", password="skv_secret_2026"
                        )
                        cur = pg_conn.cursor()
                        cur.execute(
                            "INSERT INTO feedback (cube_id, vote, comment) VALUES (%s, %s, %s)",
                            (fb_cube_id, fb_vote, fb_comment)
                        )
                        pg_conn.commit()
                        cur.close()
                        pg_conn.close()
                except:
                    pass
        
        delete_tokens[delete_token] = entry_id
        if cache:
            cache.clear()
        return {"id": entry_id, "public_url": f"/api/v1/entries/{entry_id}", "delete_token": delete_token, "cubes_loaded": len(loaded), "cubes": loaded}

    # Одиночная загрузка
    cube_id = body.get("cube_id") or body.get("user_fields", {}).get("cube_id", entry_id)
    merged_content = body.copy()
    if "persona" in body:
        merged_content["persona"] = body["persona"]
    
    cubes_library[cube_id] = {"id": entry_id, "cube_id": cube_id, "title": body.get("title") or body.get("user_fields", {}).get("title", "Cube"), "content": merged_content, "triggers": body.get("trigger_intent") or body.get("user_fields", {}).get("trigger_intent", []), "created_at": datetime.now(timezone.utc).isoformat()}
    delete_tokens[delete_token] = entry_id
    if cache:
        cache.clear()
    asyncio.create_task(_save_cube_to_db(cube_id, body.get("title", "Cube"), body.get("type", "experience"), body.get("priority", 3), body.get("trigger_intent", []), body.get("rules", []), merged_content))
    return {"id": entry_id, "public_url": f"/api/v1/entries/{entry_id}", "delete_token": delete_token}

# Остальные эндпоинты (get_entry, search, feedback) оставляем из старого файла


@router.get("/api/v1/entries/{cube_id}/links")
async def get_cube_links(cube_id: str):
    """Возвращает все связи кубика"""
    try:
        conn = psycopg2.connect(
            host="127.0.0.1", port=5432,
            dbname="skv_db", user="skv_user", password="skv_secret_2026"
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT linked_cube_id, link_type FROM cube_links WHERE cube_id = %s UNION SELECT cube_id, link_type FROM cube_links WHERE linked_cube_id = %s",
            (cube_id, cube_id)
        )
        links = [{"cube_id": row[0], "link_type": row[1]} for row in cur.fetchall()]
        cur.close()
        conn.close()
        return {"cube_id": cube_id, "links": links}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/api/feedback")
async def feedback(request: Request):
    """Принимает оценку кубика (up/down). При 3 дизлайках запускает Trials."""
    try:
        data = await request.json()
        cube_id = data.get("cube_id")
        vote = data.get("vote", "up")
        comment = data.get("comment", "")
        
        if not cube_id or vote not in ("up", "down"):
            raise HTTPException(status_code=400, detail="cube_id and vote (up/down) required")
        
        import psycopg2 as pg2
        pg_conn = pg2.connect(
            host="127.0.0.1", port=5432,
            dbname="skv_db", user="skv_user", password="skv_secret_2026"
        )
        cur = pg_conn.cursor()
        cur.execute(
            "INSERT INTO feedback (cube_id, vote, comment) VALUES (%s, %s, %s)",
            (cube_id, vote, comment)
        )
        pg_conn.commit()
        
        # Проверяем, не пора ли запустить Trials
        cur.execute("SELECT COUNT(*) FROM feedback WHERE cube_id = %s AND vote = 'down'", (cube_id,))
        downvotes = cur.fetchone()[0]
        cur.close()
        pg_conn.close()
        
        return {
            "status": "ok",
            "cube_id": cube_id,
            "vote": vote,
            "downvotes": downvotes,
            "pending_trial": downvotes >= 3
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/api/v1/trials")
async def get_trials():
    """Возвращает список активных Trials (кубики с 3+ дизлайками)"""
    try:
        import psycopg2 as pg2
        pg_conn = pg2.connect(
            host="127.0.0.1", port=5432,
            dbname="skv_db", user="skv_user", password="skv_secret_2026"
        )
        cur = pg_conn.cursor()
        
        # Находим кубики с 3+ дизлайками
        cur.execute("""
            SELECT cube_id, COUNT(*) as downvotes
            FROM feedback 
            WHERE vote = 'down'
            GROUP BY cube_id 
            HAVING COUNT(*) >= 3
        """)
        
        trials = []
        for row in cur.fetchall():
            cube_id = row[0]
            # Получаем отзывы для этого кубика
            cur.execute("SELECT vote, comment, created_at FROM feedback WHERE cube_id = %s ORDER BY created_at DESC", (cube_id,))
            reviews = [{"vote": r[0], "comment": r[1], "date": str(r[2])} for r in cur.fetchall()]
            
            trials.append({
                "cube_id": cube_id,
                "downvotes": row[1],
                "reviews": reviews
            })
        
        cur.close()
        pg_conn.close()
        
        return {"trials": trials, "count": len(trials)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

def get_cubes_count():
    return len(cubes_library)

@router.get("/api/v1/entries/{entry_id}")
async def get_entry(entry_id: str):
    entry = entries_db.get(entry_id) or cubes_library.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def tokenize(text: str) -> set:
    """Разбивает текст на слова, убирая пунктуацию"""
    import re
    return set(re.findall(r'\w+', text.lower()))

def score_keyword_match(query: str, cube: dict) -> float:
    """Возвращает релевантность 0.0-1.0"""
    q_words = tokenize(query)
    if not q_words:
        return 0.0
    
    title = cube.get("title", "")
    triggers = cube.get("trigger_intent", [])
    cube_text = f"{title} {' '.join(triggers)}".lower()
    c_words = tokenize(cube_text)
    
    # Доля слов запроса, найденных в кубике
    overlap = len(q_words.intersection(c_words))
    base_score = overlap / len(q_words)
    
    # Бонус за точное вхождение фразы
    phrase_bonus = 0.0
    if query.lower() in title.lower():
        phrase_bonus = 0.5
    elif any(query.lower() in t.lower() for t in triggers):
        phrase_bonus = 0.3
    
    return min(1.0, base_score + phrase_bonus)


def tokenize(text: str) -> set:
    import re
    return set(re.findall(r'\b\w+\b', text.lower()))

def score_keyword_match(query: str, cube: dict) -> float:
    q = query.lower().strip()
    stop_words = {"how", "to", "the", "a", "an", "for", "and", "or", "in", "on", "at", "of", "is", "it", "by", "from", "with", "what", "when", "where", "why", "can", "do", "does", "i", "my", "me", "we", "you", "your"}
    q_words = [word for word in q.split() if len(word) > 2 and word not in stop_words]
    
    if not q_words:
        return 0.0
    
    title = cube.get("title", "").lower()
    triggers = [t.lower() for t in cube.get("trigger_intent", [])]
    all_text = f"{title} {' '.join(triggers)}"
    
    # Сильные совпадения
    if any(q in t for t in triggers):
        return 1.0
    if q in title:
        return 0.95
    
    # Подсчёт важных слов
    matched = 0
    for word in q_words:
        if word in title or any(word in trigger for trigger in triggers):
            matched += 1
    
    coverage = matched / len(q_words)
    
    if coverage >= 0.8:
        return 0.85
    if coverage >= 0.6:
        return 0.65
    if coverage >= 0.5 and any(w in all_text for w in ["leaking", "pipe", "faucet", "sink", "repair", "fix"]):
        return 0.55
    
    return 0.0

@router.get("/api/cubes/search")
async def search_cubes(query: str = "", response: Response = None):
    cache_key = f"search:{hashlib.md5(query.encode()).hexdigest()[:12]}"
    if cache:
        cached = cache.get(cache_key)
        if cached:
            if response:
                response.headers["X-Cache-Status"] = "HIT"
            return cached
    results = []
    if query and len(query.strip()) > 0:
        # Гибридный поиск: keyword с score + Qdrant fallback
        q_lower = query.lower()
        kw_candidates = []
        for cube_id, cube in cubes_library.items():
            s = score_keyword_match(q_lower, cube)
            if s >= 0.65:
                kw_candidates.append((s, cube_id, cube))
        
        kw_candidates.sort(key=lambda x: -x[0])
        
        # Если keyword дал хороший результат
        if kw_candidates and kw_candidates[0][0] >= 0.7:
            for s, cube_id, cube in kw_candidates[:5]:
                results.append({"id": cube["id"], "cube_id": cube_id, "title": cube.get("title", ""), "triggers": cube.get("triggers", [])})
        
        # Если keyword-поиск не нашёл ничего — пробуем Qdrant
        if len(results) == 0:
            try:
                import urllib.request as _req
                from qdrant_client import QdrantClient
                
                # Получаем embedding для запроса
                emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
                emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
                    "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
                })
                emb_resp = json.loads(_req.urlopen(emb_req, timeout=15).read())
                qv = emb_resp["data"][0]["embedding"]
                
                # Ищем в Qdrant
                client = QdrantClient(host="127.0.0.1", port=6333)
                qdrant_results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=10)
                
                for r in qdrant_results.points:
                    payload = r.payload
                    results.append({
                        "id": str(r.id),
                        "cube_id": payload.get("cube_id", ""),
                        "title": payload.get("title", ""),
                        "triggers": payload.get("triggers", payload.get("trigger_intent", []))
                    })
            except Exception as e:
                pass  # Qdrant недоступен — остаёмся с пустым результатом
    else:
        # Пустой запрос — возвращаем все кубики
        for cube_id, cube in cubes_library.items():
            results.append({"id": cube["id"], "cube_id": cube_id, "title": cube.get("title", ""), "triggers": cube.get("triggers", [])})
    result = {"results": results, "count": len(results), "query": query}
    if cache:
        cache.set(cache_key, result, ttl=300)
    if response:
        response.headers["X-Cache-Status"] = "MISS"
    return result

@router.get("/api/profile/{user_id}/persona")
async def get_persona(user_id: str, request: Request):
    auth_header = request.headers.get("Authorization", "")
    api_token = auth_header.replace("Bearer ", "")
    if not api_token:
        raise HTTPException(status_code=401, detail="API token required")
    try:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        user = await conn.fetchrow("SELECT email FROM users WHERE api_token = $1", api_token)
        if not user:
            await conn.close()
            raise HTTPException(status_code=403, detail="Invalid token")
        row = await conn.fetchrow("SELECT persona FROM user_personas WHERE user_id = $1", user_id)
        await conn.close()
        if row and row['persona']:
            persona_data = json.loads(row['persona']) if isinstance(row['persona'], str) else row['persona']
            return {"user_id": user_id, "persona": persona_data}
        return {"user_id": user_id, "persona": None, "message": "No persona found"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
