from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import re
import numpy as np
import asyncio
import hashlib
import threading
from collections import OrderedDict
from datetime import datetime, timezone
import os
from app.chrono_buffer_v77_ultimate import ChronoBufferV77Ultimate, ChronoBufferPersistence
from app.multi_tenant_store import MultiTenantMetadataStore
from app.chrono_decoder import ChronoCognitiveDecoder
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v7", tags=["ChronoMemory"])

class SearchRequest(BaseModel):
    query_vector: Optional[List[float]] = None
    query_text: Optional[str] = None
    user_id: Optional[str] = None
    depth: int = Field(384, ge=250, le=512)
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(20, ge=1, le=100)

class MemoryRequest(BaseModel):
    query_vector: Optional[List[float]] = None
    query_text: Optional[str] = None
    user_id: Optional[str] = None
    step: int = Field(0, ge=0)
    last_seal: str = Field("")
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(5, ge=1, le=20)
    focus_words: Optional[List[str]] = None

class SearchResultItem(BaseModel):
    event_id: str
    score: float
    source: str
    summary: str = ""
    metadata: Optional[Dict[str, Any]] = None

class SearchResponse(BaseModel):
    results: List[SearchResultItem]

class ExperienceCreateRequest(BaseModel):
    topic: str
    essence: str
    rules_markdown: str
    evidence: str
    session_id: Optional[str] = None
    cube_id: Optional[str] = None

class EventWriteRequest(BaseModel):
    event_id: str
    user_id: str
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(..., ge=0, le=59)
    semantics_emb: List[float] = Field(..., min_length=218, max_length=218)
    parent_ids: Optional[List[str]] = None
    details_emb: Optional[List[float]] = None
    metric_value: Optional[float] = None
    essence: str
    topics: List[str] = Field(default_factory=list)
    raw_dialogue: Optional[str] = None


import threading
import time as _time

def background_vectorizer():
    """Run lazy vectorization every 30 minutes."""
    while True:
        _time.sleep(1800)  # 30 minutes
        try:
            from app.chrono_buffer_v77_ultimate import ChronoBufferV77Ultimate
            b = ChronoBufferV77Ultimate()
            b.persistence.load()
            count = b.process_pending_vectors()
            if count > 0:
                print(f"[INJECTOR] Created {count} vectors from pending texts", flush=True)
        except Exception as e:
            print(f"[INJECTOR] Error: {e}", flush=True)

# Start background thread
_thread = threading.Thread(target=background_vectorizer, daemon=True)
_thread.start()
print("[INJECTOR] Background vectorizer started (every 30 min)", flush=True)

@router.post("/vectors/process")
async def trigger_vectorization():
    """Manually trigger lazy vectorization."""
    try:
        count = GLOBAL_MEMORY_BUFFER.process_pending_vectors()
        return {"status": "ok", "vectors_created": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

GLOBAL_MEMORY_BUFFER = ChronoBufferV77Ultimate(max_personal=100000, max_shared=10000, storage_path="/data/skv/chrono_buffer")
# Инициализируем persistence явно
# Загружаем буфер из хранилища
if GLOBAL_MEMORY_BUFFER.persistence.load():
    logger.info("[SKV] Buffer loaded from /data/skv/chrono_buffer")
else:
    logger.warning("[SKV] Failed to load buffer, using empty")
metadata_store = MultiTenantMetadataStore(base_dir="/data/skv/metadata_store")
save_lock = asyncio.Lock()

_search_cache = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX_SIZE = 1000
_CACHE_TTL_SECONDS = 300

# Security: API keys from environment variable
VALID_TOKENS = [t.strip() for t in os.getenv("SKV_API_KEYS", "").split(",") if t.strip()]

# Rate limiting per user
_request_counts = {}
def check_rate_limit(user_id: str, max_requests: int = 60, window: int = 60):
    import time
    now = time.time()
    if user_id not in _request_counts:
        _request_counts[user_id] = []
    _request_counts[user_id] = [t for t in _request_counts[user_id] if now - t < window]
    if len(_request_counts[user_id]) >= max_requests:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _request_counts[user_id].append(now)

def _cache_key(qv, uid, hops, top_k):
    return hashlib.md5(bytes(qv) + uid.encode() + f":{hops}:{top_k}".encode()).hexdigest()

def _cached_search(buffer, qv, uid, hops, top_k, layer_weights=None):
    key = _cache_key(qv, uid, hops, top_k)
    with _cache_lock:
        if key in _search_cache:
            t, r = _search_cache[key]
            if (datetime.now(timezone.utc) - t).total_seconds() < _CACHE_TTL_SECONDS:
                _search_cache.move_to_end(key)
                return r
            else:
                del _search_cache[key]
    result = buffer.hybrid_search(query=qv, user_id=uid, hops=hops, top_k=top_k)
    # Convert structured format to flat list for compatibility
    if isinstance(result, dict):
        pm = result.get('personal_memory', {})
        if isinstance(pm, dict):
            flat = []
            focus = pm.get('focus')
            if focus:
                flat.append(focus)
            flat.extend(pm.get('context', []))
            result = flat + result.get('shared_knowledge', []) + result.get('core_protocol', [])
        else:
            result = pm + result.get('shared_knowledge', []) + result.get('core_protocol', []) if isinstance(pm, list) else []
    with _cache_lock:
        _search_cache[key] = (datetime.now(timezone.utc), result)
        if len(_search_cache) > _CACHE_MAX_SIZE:
            _search_cache.popitem(last=False)
    return result


# ═══════════════════════════════════════════════════════════════
# VECTOR ROUTER (HNSW per-user indices)
# ═══════════════════════════════════════════════════════════════

import hnswlib as _hnswlib
import numpy as _np
import os as _os

class VectorRouter:
    """Per-user FAISS indices with LRU cache"""
    def __init__(self, base_path="/data/skv/hnsw", max_hot=50, dim=768):
        self.base_path = base_path
        self.max_hot = max_hot
        self.dim = dim
        self.hot_cache = {}
        _os.makedirs(base_path, exist_ok=True)
    
    def _load_index(self, user_id):
        hnsw_path = f"{self.base_path}/{user_id}.hnsw"
        ids_path = f"{self.base_path}/{user_id}_ids.npy"
        if not _os.path.exists(hnsw_path):
            return None
        index = _hnswlib.Index(space="cosine", dim=self.dim)
        index.load_index(hnsw_path)
        index.set_ef(200)
        ids = _np.load(ids_path)
        return index, ids
    
    def search(self, user_id, query_vec, top_k=10):
        if user_id not in self.hot_cache:
            loaded = self._load_index(user_id)
            if loaded is None:
                return []
            if len(self.hot_cache) >= self.max_hot:
                oldest = min(self.hot_cache.keys(), key=lambda u: len(self.hot_cache))
                del self.hot_cache[oldest]
            self.hot_cache[user_id] = loaded
        index, ids = self.hot_cache[user_id]
        labels, distances = index.knn_query(_np.array([query_vec], dtype=_np.float32), k=min(top_k, len(ids)))
        results = []
        for i in range(len(labels[0])):
            idx = labels[0][i]
            if idx < len(ids):
                results.append((str(ids[idx]), float(1.0 - distances[0][i])))
        return results

GLOBAL_VECTOR_ROUTER = VectorRouter()



@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(req: FeedbackRequest, authorization: str = Header(None)):
    """Агенты отправляют фидбэк о работе SKV: баги, аномалии, улучшения."""
    try:
        import sqlite3, uuid
        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS feedback_reports
            (id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, type TEXT, title TEXT,
             description TEXT, event_id TEXT, cube_id TEXT, query_text TEXT,
             severity INTEGER, status TEXT DEFAULT 'new', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT INTO feedback_reports (id, user_id, agent_id, type, title, description, event_id, cube_id, query_text, severity) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (feedback_id, req.user_id, req.agent_id, req.type, req.title, req.description,
                    req.event_id, req.cube_id, req.query_text, req.severity))
        conn.commit()
        conn.close()
        return {"status": "ok", "feedback_id": feedback_id, "message": "Thank you! Your feedback helps improve SKV."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/feedback")
async def get_feedback(type: Optional[str] = None, status: Optional[str] = "new", limit: int = 50):
    """Получить список фидбэка (для администратора)."""
    try:
        import sqlite3
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        if type:
            cur.execute("SELECT * FROM feedback_reports WHERE type = ? AND status = ? ORDER BY created_at DESC LIMIT ?", (type, status, limit))
        else:
            cur.execute("SELECT * FROM feedback_reports WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit))
        rows = cur.fetchall()
        conn.close()
        cols = ["id", "user_id", "agent_id", "type", "title", "description", "event_id", "cube_id", "query_text", "severity", "status", "created_at"]
        return {"reports": [dict(zip(cols, row)) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(req: FeedbackRequest, authorization: str = Header(None)):
    try:
        import sqlite3, uuid
        fb_id = f"fb_{uuid.uuid4().hex[:12]}"
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS feedback_reports
            (id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, type TEXT, title TEXT,
             description TEXT, event_id TEXT, cube_id TEXT, query_text TEXT,
             severity INTEGER, status TEXT DEFAULT 'new', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT INTO feedback_reports (id, user_id, agent_id, type, title, description, event_id, cube_id, query_text, severity) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (fb_id, req.user_id, req.agent_id, req.type, req.title, req.description, req.event_id, req.cube_id, req.query_text, req.severity))
        conn.commit()
        conn.close()
        return {"status": "ok", "feedback_id": fb_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/feedback")
async def get_feedback(type: Optional[str] = None, status: Optional[str] = "new", limit: int = 50):
    try:
        import sqlite3
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        if type:
            cur.execute("SELECT * FROM feedback_reports WHERE type = ? AND status = ? ORDER BY created_at DESC LIMIT ?", (type, status, limit))
        else:
            cur.execute("SELECT * FROM feedback_reports WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit))
        rows = cur.fetchall()
        conn.close()
        cols = ["id", "user_id", "agent_id", "type", "title", "description", "event_id", "cube_id", "query_text", "severity", "status", "created_at"]
        return {"reports": [dict(zip(cols, row)) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agent/openapi.json")
async def get_agent_tools():
    """OpenAPI схема для Function Calling агентов (GPT, Claude, DeepSeek)"""
    import json, os
    schema_path = os.path.join(os.path.dirname(__file__), 'openapi_schema.json')
    with open(schema_path, 'r') as f:
        return json.load(f)

def get_memory_buffer():
    return GLOBAL_MEMORY_BUFFER

@router.post("/cache/clear")
async def clear_search_cache(buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    """Clear search cache and reload buffer"""
    global _search_cache
    with _cache_lock:
        _search_cache.clear()
    
    # Reload buffer from disk
    buffer.persistence.load()
    
    return {
        "status": "ok",
        "message": "Cache cleared and buffer reloaded",
        "personal_active": int(np.sum(buffer.personal_active_mask[:buffer.personal_current_size])),
        "shared_active": int(np.sum(buffer.shared_active_mask[:buffer.shared_current_size]))
    }


def verify_seal_level(authorization: Optional[str] = Header(None)) -> int:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Token")
    if not authorization.startswith("Bearer ") or len(authorization) < 20:
        raise HTTPException(status_code=403, detail="Invalid token format")
    token = authorization.replace("Bearer ", "")
    # If no tokens configured, allow any (dev mode)
    if not VALID_TOKENS:
        return 3
    if token not in VALID_TOKENS:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return 3

@router.post("/memory")
async def guardian_l1_memory(req: MemoryRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer), authorization: str = Header(None)):
    # Извлекаем user_id из токена
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        try:
            import sqlite3 as _sq
            _conn = _sq.connect("/data/skv/metadata_store/shared_master.db")
            _cur = _conn.cursor()
            _cur.execute("SELECT user_id FROM user_api_keys WHERE api_key = ? AND is_active = 1", (token,))
            _row = _cur.fetchone()
            _conn.close()
            if _row:
                req.user_id = _row[0]
        except:
            pass
        token = authorization.replace("Bearer ", "")
        try:
            import sqlite3 as _sq
            _conn = _sq.connect("/data/skv/metadata_store/shared_master.db")
            _cur = _conn.cursor()
            _cur.execute("SELECT user_id FROM user_api_keys WHERE api_key = ? AND is_active = 1", (token,))
            _row = _cur.fetchone()
            if _row:
                req.user_id = _row[0]
            _conn.close()
        except:
            pass
    if not req.user_id or not req.user_id.strip():
        raise HTTPException(status_code=422, detail="user_id cannot be empty")
    check_rate_limit(req.user_id)
    step = req.step
    print(f'DEBUG query_text={repr(req.query_text)}', flush=True)
    if req.query_text:
        from app.routers.v4_middleware import get_embedding_cached
        full_emb = get_embedding_cached(req.query_text)
        full_list = full_emb if isinstance(full_emb, list) else full_emb.tolist()
        q_vec = np.zeros(768, dtype=np.float32)
        q_vec[:768] = full_list[:768]
    elif req.query_vector:
        q_vec = np.array(req.query_vector, dtype=np.float32)
    else:
        q_vec = np.zeros(768, dtype=np.float32)
    memory_text = ""
    has_cubes = False
    try:
        # v7.8: pass layer_weights for dynamic masks
        lw = req.layer_weights if hasattr(req, 'layer_weights') else None
        # Try VectorRouter (HNSW) first, fallback to _cached_search
        hnsw_results = GLOBAL_VECTOR_ROUTER.search(req.user_id.replace("@", "").replace(".", ""), q_vec, top_k=req.top_k)
        raw_results = []
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
            
            # FTS5 boost using focus_words from agent

        else:
            raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k, layer_weights=lw)
        
        # HYBRID: Multi-word FTS5 boost
        if req.query_text and raw_results:
            try:
                import sqlite3 as sq
                db_name = req.user_id.replace('@', '').replace('.', '')
                fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                fts_cur = fts_conn.cursor()
                all_words = [w for w in req.query_text.split() if len(w) > 3]
                if all_words:
                    fts_matches = {}
                    for word in all_words:
                        fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ?', (word,))
                        for (eid,) in fts_cur.fetchall():
                            fts_matches[eid] = fts_matches.get(eid, 0) + 1
                    fts_conn.close()
                    if fts_matches:
                        for r in raw_results:
                            eid = r.get('event_id')
                            if eid in fts_matches:
                                word_count = fts_matches[eid]
                                                                # Name boost: uppercase words = 0.5, lowercase = 0.2
                                name_boost = 0
                                word_boost = 0
                                for word in all_words:
                                    if word[0].isupper():
                                        name_boost += 0.5
                                    else:
                                        word_boost += 0.2
                                r['score'] = r.get('score', 0) + name_boost + word_boost
                        raw_results.sort(key=lambda x: -x.get('score', 0))
            except:
                pass
        
        if raw_results:
            filtered_dicts = []
            candidate_ids = []
            for r in raw_results:
                event_id = r["event_id"]
                score = r["score"]
                if event_id.startswith("CUBE_"):
                    source = "core"
                elif event_id in buffer.shared_id_to_idx:
                    source = "shared"
                else:
                    source = "personal"
                    if not event_id.startswith(f"{req.user_id}::"):
                        continue
                candidate_ids.append(event_id)
                filtered_dicts.append({"event_id": event_id, "score": score, "source": source})
            metadata_map = metadata_store.batch_get_metadata(req.user_id, candidate_ids)
            for r in filtered_dicts:
                r["metadata"] = metadata_map.get(r["event_id"], {})
            memory_text = ChronoCognitiveDecoder.decode_search_results(filtered_dicts)
            has_cubes = len(filtered_dicts) > 0
    except Exception:
        memory_text = "=== ПАМЯТЬ SKV: совпадений не найдено ===\n"
    
    # Load constitutional cubes from SQLite (shared_master.db)
    constitution_cube_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v4"]
    constitution_map = metadata_store.batch_get_metadata("shared_master", constitution_cube_ids)
    
    # Build constitution text from loaded cubes
    constitution_parts = []
    for cube_id in constitution_cube_ids:
        meta = constitution_map.get(cube_id, {})
        essence = meta.get("essence", "")
        if essence:
            constitution_parts.append(f"=== {cube_id.upper().replace('_', ' ')} ===\n{essence}")
    
    constitution_text = "\n\n".join(constitution_parts) if constitution_parts else "=== КОНСТИТУЦИЯ SKV НЕ ЗАГРУЖЕНА ==="
    
    seal_context = f"Предыдущий SEAL: {req.last_seal}\nПродолжи нумерацию.\n" if req.last_seal else "Начни SEAL с #1.\n"
    reminders = "=== GUARDIAN L1 ===\n"
    reminders += "📝 Сохрани сессию (POST /api/v7/event/write)\n"
    reminders += "📦 Создай experience cube если было важное\n"
    reminders += "🗺 Обнови Memory Map L2\n"
    if has_cubes:
        reminders += "⭐ Оставь feedback на использованные кубы\n"
    reminders += "📜 Все кубы конституции загружены\n"
    reminders += "🔐 Выполни Second Look и поставь SEAL\n"
    # Load L2 Memory Map
    memory_map_text = ""
    try:
        import sqlite3 as sq
        db_name = req.user_id.replace("@", "").replace(".", "")
        l2_conn = sq.connect(f"/data/skv/metadata_store/{db_name}.db")
        l2_cur = l2_conn.cursor()
        l2_cur.execute("SELECT map_json FROM summary_l2 WHERE user_id = ?", (req.user_id,))
        l2_row = l2_cur.fetchone()
        if l2_row and l2_row[0]:
            import json as jn
            l2_map = jn.loads(l2_row[0])
            memory_map_text = "=== MEMORY MAP L2 ===\n"
            themes = l2_map.get("main_themes", [])[:5]
            if themes:
                memory_map_text += f"Основные темы: {', '.join(themes)}\n"
            profile = l2_map.get("user_profile", "")
            if profile:
                memory_map_text += f"Профиль: {profile[:300]}\n"
        l2_conn.close()
    except:
        pass
    
    prompt_text = f"{memory_text}\n\n{memory_map_text}\n{constitution_text}\n\n{seal_context}\n{reminders}"
    # Раздельная выдача
    vector_top = raw_results[:10] if raw_results else []
    fts_top = []
    focus = getattr(req, 'focus_words', None) or []
    if focus:
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            fts_cur = fts_conn.cursor()
            for word in focus:
                fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ? LIMIT 10', (word,))
                for (eid,) in fts_cur.fetchall():
                    if eid not in [f.get('event_id') for f in fts_top]:
                        fts_top.append({'event_id': eid, 'matched_word': word, 'source': 'fts'})
            fts_conn.close()
        except:
            pass
    vector_ids = {v.get('event_id') for v in vector_top}
    fts_ids = {f.get('event_id') for f in fts_top}
    intersection = [v for v in vector_top if v.get('event_id') in fts_ids]
    
    # Full text for best results
    def _full_text(eid):
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            cur = conn.cursor()
            cur.execute('SELECT raw_dialogue FROM event_metadata WHERE event_id = ?', (eid,))
            row = cur.fetchone()
            conn.close()
            return row[0][:1000] if row and row[0] else ''
        except:
            return ''
    
    best_vec = vector_top[0] if vector_top else {}
    if best_vec: best_vec['full_text'] = _full_text(best_vec.get('event_id', ''))
    best_fts = fts_top[0] if fts_top else {}
    if best_fts: best_fts['full_text'] = _full_text(best_fts.get('event_id', ''))
    best_int = intersection[0] if intersection else {}
    if best_int: best_int['full_text'] = _full_text(best_int.get('event_id', ''))
    
    return {"prompt_text": prompt_text, "memory": memory_text, "constitution": constitution_text, "reminders": reminders, "has_cubes": has_cubes, "step": step, "memory_map": memory_map_text, "vector_top10": vector_top[:10], "fts_top10": fts_top[:10], "intersection": intersection[:10], "best_vector": best_vec, "best_fts": best_fts, "best_intersection": best_int}

@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    q_vec = np.array(req.query_vector, dtype=np.float32)
    try:
        # v7.8: pass layer_weights for dynamic masks
        lw = req.layer_weights if hasattr(req, 'layer_weights') else None
        # Try VectorRouter (HNSW) first, fallback to _cached_search
        hnsw_results = GLOBAL_VECTOR_ROUTER.search(req.user_id.replace("@", "").replace(".", ""), q_vec, top_k=req.top_k)
        raw_results = []
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
            
            # FTS5 boost using focus_words from agent

        else:
            raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k, layer_weights=lw)
        
        print(f'DEBUG HYBRID: query_text={bool(req.query_text)}, raw_results={bool(raw_results)}', flush=True)
        # HYBRID: Multi-word FTS5 boost (more matched words = higher boost)
        if req.query_text and raw_results:
            try:
                import sqlite3 as sq
                db_name = req.user_id.replace('@', '').replace('.', '')
                fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                fts_cur = fts_conn.cursor()
                all_words = [w for w in req.query_text.split() if len(w) > 3]
                if all_words:
                    fts_matches = {}
                    for word in all_words:
                        fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ?', (word,))
                        for (eid,) in fts_cur.fetchall():
                            fts_matches[eid] = fts_matches.get(eid, 0) + 1
                    fts_conn.close()
                    if fts_matches:
                        for r in raw_results:
                            eid = r.get('event_id')
                            if eid in fts_matches:
                                word_count = fts_matches[eid]
                                boost = 1.0 + (word_count * 0.5)
                                                                # Name boost: uppercase words = 0.5, lowercase = 0.2
                                name_boost = 0
                                word_boost = 0
                                for word in all_words:
                                    if word[0].isupper():
                                        name_boost += 0.5
                                    else:
                                        word_boost += 0.2
                                r['score'] = r.get('score', 0) + name_boost + word_boost
                        raw_results.sort(key=lambda x: -x.get('score', 0))
            except:
                pass
        
        if raw_results:
            event_ids = [r["event_id"] for r in raw_results]
            metadata_map = metadata_store.batch_get_metadata(req.user_id, event_ids)
            for r in raw_results:
                r["metadata"] = metadata_map.get(r["event_id"], {})
            # Separate by source
            personal = [r for r in raw_results if r.get("source") == "personal"]
            shared = [r for r in raw_results if r.get("source") == "shared"]
            core = [r for r in raw_results if r.get("source") == "core"]
            memory_text = ChronoCognitiveDecoder.decode_structured(personal, shared, core)
        else:
            memory_text = ""
        
        memory_map = ""
        if req.step == 0:
            memory_map = "\n=== YOUR MEMORY MAP ===\n"
            if buffer.personal_current_size > 0:
                memory_map += f"Personal sessions: {buffer.personal_current_size}\n"
            if buffer.shared_current_size > 0:
                memory_map += f"Shared knowledge cubes: {buffer.shared_current_size}\n"
            memory_map += "Use memory search to explore specific topics.\n"
        
        constitution_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v4"]
        const_map = metadata_store.batch_get_metadata("shared_master", constitution_ids)
        const_parts = []
        for cid in constitution_ids:
            meta = const_map.get(cid, {})
            if meta.get("raw_dialogue"):
                clean_name = cid.replace("cube_const_", "CUBE ").replace("_v4","").replace("_v5","")
                const_parts.append(f"=== {clean_name} ===\n{meta['raw_dialogue']}")
        constitution_text = "\n\n".join(const_parts)
        
        reminders = ""
        if req.step == 0:
            reminders += "Load all constitution cubes (CUBE 00-05)\n"
        if req.step > 0 and req.step % 5 == 0:
            reminders += "Save session to memory\n"
        if req.step > 0 and req.step % 15 == 0:
            reminders += "Create experience cube if important\n"
        if memory_text:
            reminders += "Leave feedback on used cubes\n"
        reminders += "Execute Second Look and put SEAL\n"
        
        seal_context = f"Previous SEAL: {req.last_seal}\nContinue numbering.\n" if req.last_seal else "Start SEAL with #1.\n"
        
        search_map = f"\n=== SEARCH MEMORY MAP ===\n{search_memory_map}\n" if search_memory_map else ""
        search_instruction = "=== SEARCH MEMORY FIRST ===\nBEFORE answering, check the memory below.\n\n"
        prompt = f"{guest_warning}{memory_map}{search_instruction}{search_map}{chat_history}\n\n{constitution_text}\n\n{memory_text if memory_text else 'No relevant memory found.'}\n\n{seal_context}{reminders}\nUser question: {req.message}\n\nReturn your response with SEAL: SKV | #N | READ | VERIFY | CORRECT | OUTPUT"
        
        polza_body = json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}).encode()
        polza_key = os.environ.get("POLZA_KEY", "")
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=polza_body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
        with urlreq.urlopen(r, timeout=120) as resp:
            answer = json.loads(resp.read().decode())["choices"][0]["message"]["content"]
        # Remove SEAL from user-facing response
        answer = re.sub(r"🔐.*$", "", answer, flags=re.DOTALL).strip()
        
        if not is_guest:
            safe_event_id = f"{req.user_id}::chat_{req.session_id}_{int(time.time())}"
            now = datetime.now(timezone.utc)
            session_emb = get_embedding_cached(req.message + " " + answer)
            session_list = session_emb if isinstance(session_emb, list) else session_emb.tolist()
            session_vec = session_list[:218]
            buffer.write_personal_event(event_id=safe_event_id, hour=now.hour, minute=now.minute, semantics_emb=np.array(session_vec, dtype=np.float32), parent_indices=None, details_emb=None, metric_value=len(answer)/1000.0)
            metadata_store.write_metadata(user_id=req.user_id, event_id=safe_event_id, time_str=f"{now.hour:02d}:{now.minute:02d}, {now.strftime('%d.%m.%Y')}", essence=req.message[:200], messages_count=2, topics=["chat_history"], links=[], metric_value=len(answer)/1000.0, raw_dialogue=f"Q: {req.message}\nA: {answer}", is_shared=False)
            if buffer.persistence:
                buffer.persistence.save()
        
        return {"response": answer, "session_id": req.session_id, "step": req.step + 1, "is_guest": is_guest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FeedbackRequest(BaseModel):
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    type: str = "bug"
    title: str
    description: str
    event_id: Optional[str] = None
    cube_id: Optional[str] = None
    query_text: Optional[str] = None
    severity: int = 1

class VoteRequest(BaseModel):
    cube_id: str
    user_id: str
    vote: int  # +1 or -1


# ═══════════════════════════════════════════════════════════════
# WRITE ENDPOINTS (v8.2)
# ═══════════════════════════════════════════════════════════════

class EventWriteRequest(BaseModel):
    user_id: str
    session_id: str
    query: str
    response: str
    topic: Optional[str] = None

class SummarizeRequest(BaseModel):
    user_id: str
    session_id: str
    topic: str
    summary_text: str
    message_count: int = 1

class MapUpdateRequest(BaseModel):
    user_id: str
    session_count: int = 1

class BatchFlushRequest(BaseModel):
    user_id: str
    session_id: str
    batch_logs: List[Dict] = []
    query: Optional[str] = None
    experience_cubes: Optional[List[Dict]] = []
    feedback_votes: Optional[List[Dict]] = []

@router.post("/event/write", status_code=status.HTTP_201_CREATED)
async def write_event(req: EventWriteRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO event_metadata (event_id, essence, raw_dialogue, status, messages_count) VALUES (?,?,?,?,?)",
                   (f"{req.user_id}::{req.session_id}", req.topic or req.query[:100],
                    f"Q: {req.query}\nA: {req.response}", "active", 1))
        conn.commit()
        conn.close()
        return {"status": "ok", "event_id": f"{req.user_id}::{req.session_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/summarize", status_code=status.HTTP_201_CREATED)
async def store_summary(req: SummarizeRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS summary_l1
            (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT,
             summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT OR REPLACE INTO summary_l1 (session_id, user_id, topic, summary_text, message_count) VALUES (?,?,?,?,?)",
                   (req.session_id, req.user_id, req.topic, req.summary_text, req.message_count))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/map", status_code=status.HTTP_200_OK)
async def update_memory_map(req: MapUpdateRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS summary_l2
            (user_id TEXT PRIMARY KEY, map_json TEXT, session_count INTEGER,
             last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("INSERT OR REPLACE INTO summary_l2 (user_id, session_count) VALUES (?,?)",
                   (req.user_id, req.session_count))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/experience/create", status_code=status.HTTP_201_CREATED)
async def create_experience_cube(req: ExperienceCreateRequest):
    try:
        import sqlite3, uuid
        cube_id = req.cube_id or f"cube_{uuid.uuid4().hex[:12]}"
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute("""INSERT OR REPLACE INTO cubes_new 
            (cube_id, essence, subject_action_object, rules_markdown, evidence, source_session, status)
            VALUES (?, ?, ?, ?, ?, ?, "community")""",
            (cube_id, req.essence, req.topic, req.rules_markdown, req.evidence, req.session_id))
        conn.commit()
        conn.close()
        return {"status": "ok", "cube_id": cube_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agent/batch_flush", status_code=status.HTTP_202_ACCEPTED)
async def agent_batch_flush(req: BatchFlushRequest):
    import sqlite3
    db_name = req.user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db")
    cur = conn.cursor()
    if req.batch_logs:
        text = "\n".join([f"Q: {log.get('q','')}\nA: {log.get('a','')}" for log in req.batch_logs])
        cur.execute("INSERT OR REPLACE INTO event_metadata (event_id, essence, raw_dialogue, status, messages_count) VALUES (?,?,?,?,?)",
                   (f"{req.user_id}::{req.session_id}", req.query or "batch", text, "active", len(req.batch_logs)))
        conn.commit()
    conn.close()
    return {"status": "batch_accepted", "logs_saved": len(req.batch_logs)}

@router.get("/agent/memory")
async def agent_get_memory(user_id: str, query: str):
    try:
        from fastembed import TextEmbedding
        import numpy as np
        emb = TextEmbedding(model_name="BAAI/bge-base-en-v1.5")
        e = np.array(list(emb.embed([query]))[0], dtype=np.float32)
        qv = np.zeros(768, dtype=np.float32)
        qv[:768] = e[:768]
        results = GLOBAL_VECTOR_ROUTER.search(user_id, qv, top_k=5)
        return {"results": [{"event_id": eid, "score": s} for eid, s in results], "has_cubes": len(results) > 0}
    except:
        return {"memory": "SKV unavailable", "has_cubes": False}

@router.post("/experience/vote")
async def vote_experience(req: VoteRequest):
    """Vote for an experience cube. 3 downvotes → deprecated."""
    import sqlite3, json
    
    if req.vote not in (-1, 1):
        raise HTTPException(status_code=400, detail="Vote must be +1 or -1")
    
    conn = sqlite3.connect('/data/skv/metadata_store/shared_master.db')
    cur = conn.cursor()
    
    # Get current votes
    cur.execute('SELECT votes_json, rating FROM event_metadata WHERE event_id = ?', (req.cube_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Cube not found")
    
    votes = json.loads(row[0]) if row[0] else []
    current_rating = row[1] or 0
    
    # Check if user already voted
    for v in votes:
        if v.get('user_id') == req.user_id:
            # Change vote
            old_vote = v['vote']
            v['vote'] = req.vote
            v['timestamp'] = datetime.now(timezone.utc).isoformat()
            current_rating = current_rating - old_vote + req.vote
            break
    else:
        # New vote
        votes.append({
            'user_id': req.user_id,
            'vote': req.vote,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        current_rating += req.vote
    
    # Determine status
    downvotes = sum(1 for v in votes if v['vote'] == -1)
    upvotes = sum(1 for v in votes if v['vote'] == 1)
    
    if downvotes >= 3:
        status = 'deprecated'
    elif upvotes >= 3:
        status = 'verified'
    else:
        status = 'community'
    
    cur.execute('UPDATE event_metadata SET votes_json = ?, rating = ?, status = ? WHERE event_id = ?',
                (json.dumps(votes), current_rating, status, req.cube_id))
    conn.commit()
    conn.close()
    
    return {
        "status": "ok",
        "cube_id": req.cube_id,
        "rating": current_rating,
        "cube_status": status,
        "upvotes": upvotes,
        "downvotes": downvotes
    }
