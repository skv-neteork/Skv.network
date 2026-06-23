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
    query_vector: List[float] = Field(..., min_length=512, max_length=512)
    user_id: str = Field(...)
    depth: int = Field(384, ge=250, le=512)
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(20, ge=1, le=100)

class MemoryRequest(BaseModel):
    query_vector: List[float] = Field(..., min_length=512, max_length=512)
    user_id: str = Field(...)
    step: int = Field(0, ge=0)
    last_seal: str = Field("")
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(5, ge=1, le=20)

class SearchResultItem(BaseModel):
    event_id: str
    score: float
    source: str
    summary: str = ""
    metadata: Optional[Dict[str, Any]] = None

class SearchResponse(BaseModel):
    results: List[SearchResultItem]

class ExperienceCreateRequest(BaseModel):
    event_id: str
    semantics_emb: List[float] = Field(..., min_length=218, max_length=218)
    parent_ids: Optional[List[str]] = None
    details_emb: Optional[List[float]] = None
    essence: str
    topics: List[str] = Field(default_factory=list)

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

def _cached_search(buffer, qv, uid, hops, top_k):
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
        result = result.get('personal_memory', []) + result.get('shared_knowledge', []) + result.get('core_protocol', [])
    with _cache_lock:
        _search_cache[key] = (datetime.now(timezone.utc), result)
        if len(_search_cache) > _CACHE_MAX_SIZE:
            _search_cache.popitem(last=False)
    return result

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
async def guardian_l1_memory(req: MemoryRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    if not req.user_id or not req.user_id.strip():
        raise HTTPException(status_code=422, detail="user_id cannot be empty")
    check_rate_limit(req.user_id)
    q_vec = np.array(req.query_vector, dtype=np.float32)
    memory_text = ""
    has_cubes = False
    try:
        raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k)
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
    constitution_cube_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_05_v4"]
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
    step = req.step
    if step == 0:
        reminders += "Загрузи все кубы конституции (CUBE 00-05)\n"
    if step > 0 and step % 5 == 0:
        reminders += "Сохрани сессию в память\n"
    if step > 0 and step % 15 == 0:
        reminders += "Создай experience cube, если было важное\n"
    if has_cubes:
        reminders += "Оставь feedback на использованные кубы\n"
    reminders += "Выполни Second Look и поставь SEAL\n"
    prompt_text = f"{memory_text}\n\n{constitution_text}\n\n{seal_context}\n{reminders}"
    return {"prompt_text": prompt_text, "memory": memory_text, "constitution": constitution_text, "reminders": reminders, "has_cubes": has_cubes, "step": step}

@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    q_vec = np.array(req.query_vector, dtype=np.float32)
    try:
        raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k)
        filtered_results = []
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
            filtered_results.append(SearchResultItem(event_id=event_id, score=score, source=source))
        event_ids = [item.event_id for item in filtered_results]
        metadata_map = metadata_store.batch_get_metadata(req.user_id, event_ids)
        final_items = []
        for item in filtered_results:
            real_meta = metadata_map.get(item.event_id, {"essence": "Метаданные не найдены", "time": datetime.now(timezone.utc).strftime("%H:%M, %d.%m.%Y"), "metric_value": "нет", "links": [], "topics": [], "messages_count": 0})
            item_data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            item_data["metadata"] = real_meta
            item_data["summary"] = real_meta["essence"]
            final_items.append(SearchResultItem(**item_data))
        return SearchResponse(results=final_items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/event/write", status_code=status.HTTP_201_CREATED)
async def write_personal_event(req: EventWriteRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    parent_indices = []
    if req.parent_ids:
        for p_id in req.parent_ids:
            secure_p_id = f"{req.user_id}::{p_id}"
            if secure_p_id in buffer.personal_id_to_idx:
                parent_indices.append(buffer.personal_id_to_idx[secure_p_id])
            elif p_id in buffer.shared_id_to_idx:
                parent_indices.append(buffer.shared_id_to_idx[p_id])
    s_emb = np.array(req.semantics_emb, dtype=np.float32)
    d_emb = np.array(req.details_emb, dtype=np.float32) if req.details_emb else None
    secure_event_id = f"{req.user_id}::{req.event_id}"
    if secure_event_id in buffer.personal_id_to_idx:
        return {"status": "already_exists", "idx": buffer.personal_id_to_idx[secure_event_id], "event_id": secure_event_id}
    try:
        idx = buffer.write_personal_event(event_id=secure_event_id, hour=req.hour, minute=req.minute, semantics_emb=s_emb, parent_indices=parent_indices if parent_indices else None, details_emb=d_emb, metric_value=req.metric_value)
        async with save_lock:
            buffer.save()
        time_str = f"{req.hour:02d}:{req.minute:02d}, {datetime.now(timezone.utc).strftime('%d.%m.%Y')}"
        metadata_store.write_metadata(user_id=req.user_id, event_id=secure_event_id, time_str=time_str, essence=req.essence, messages_count=len(req.raw_dialogue.split('\n')) if req.raw_dialogue else 1, topics=req.topics, links=req.parent_ids or [], metric_value=req.metric_value, raw_dialogue=req.raw_dialogue, is_shared=False)
        return {"status": "created", "idx": idx, "event_id": secure_event_id}
    except RuntimeError:
        raise HTTPException(status_code=507, detail="Personal Matrix Buffer Full")

@router.post("/experience/create", status_code=status.HTTP_201_CREATED)
async def create_shared_experience(req: ExperienceCreateRequest, seal_level: int = Depends(verify_seal_level), buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    if seal_level < 3:
        raise HTTPException(status_code=403, detail="Insufficient Agent SEAL Level")
    parent_indices = [buffer.shared_id_to_idx[p_id] for p_id in req.parent_ids if p_id in buffer.shared_id_to_idx] if req.parent_ids else []
    s_emb = np.array(req.semantics_emb, dtype=np.float32)
    d_emb = np.array(req.details_emb, dtype=np.float32) if req.details_emb else None
    try:
        idx = buffer.write_shared_experience(event_id=req.event_id, semantics_emb=s_emb, parent_indices=parent_indices if parent_indices else None, details_emb=d_emb)
        async with save_lock:
            buffer.save()
        time_str = f"00:00, {datetime.now(timezone.utc).strftime('%d.%m.%Y')}"
        metadata_store.write_metadata(user_id="shared_master", event_id=req.event_id, time_str=time_str, essence=req.essence, messages_count=0, topics=req.topics, links=req.parent_ids or [], metric_value=None, raw_dialogue=None, is_shared=True)
        return {"status": "created", "idx": idx, "event_id": req.event_id}
    except RuntimeError:
        raise HTTPException(status_code=507, detail="Shared Matrix Buffer Full")

@router.get("/health")
async def health_check(buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    return {"status": "ok", "personal_size": buffer.personal_current_size, "shared_size": buffer.shared_current_size, "max_personal": buffer.max_personal, "max_shared": buffer.max_shared}

@router.get("/constitution")
async def get_constitution():
    """Returns all constitutional cubes from SQLite"""
    cube_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v4"]
    metadata_map = metadata_store.batch_get_metadata("shared_master", cube_ids)
    
    constitution = []
    for cube_id in cube_ids:
        meta = metadata_map.get(cube_id, {})
        if meta.get("essence"):
            constitution.append({
                "id": cube_id,
                "title": meta.get("essence", "").split("\n")[0],
                "text": meta.get("raw_dialogue", "")
            })
    
    return {"constitution": constitution}


@router.get("/event/{event_id}")
async def get_event_detail(event_id: str, user_id: str):
    if not (event_id.startswith(f"{user_id}::") or event_id.startswith("CUBE_")):
        raise HTTPException(status_code=403, detail="PII Access Denied")
    dialogue = metadata_store.get_full_dialogue(user_id, event_id)
    if not dialogue:
        raise HTTPException(status_code=404, detail="Event log not found")
    return {"event_id": event_id, "raw_dialogue": dialogue}

class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str
    step: int = 0
    last_seal: str = ""
    top_k: int = 5

@router.post("/chat")
async def chat_endpoint(req: ChatRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    try:
        import json, urllib.request as urlreq, time
        from app.chrono_decoder import ChronoCognitiveDecoder
        from app.routers.v4_middleware import get_embedding_cached
        
        is_guest = req.user_id.startswith("guest_")
        guest_warning = ""
        if is_guest:
            guest_warning = "GUEST MODE: Memory is temporary (24h). Register to save permanently.\n"
        
        emb = get_embedding_cached(req.message)
        emb_list = emb if isinstance(emb, list) else emb.tolist()
        query_vec = emb_list + [0.0] * (512 - len(emb_list))
        
        raw = buffer.hybrid_search(query=np.array(query_vec, dtype=np.float32), user_id=req.user_id, hops=2, top_k=req.top_k)
        if isinstance(raw, dict):
            raw_results = raw.get('personal_memory', []) + raw.get('shared_knowledge', []) + raw.get('core_protocol', [])
        else:
            raw_results = raw
        
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
        
        prompt = f"{guest_warning}{memory_map}\n{constitution_text}\n\n{memory_text if memory_text else 'No relevant memory found.'}\n\n{seal_context}{reminders}\nUser question: {req.message}\n\nReturn your response with SEAL: SKV | #N | READ | VERIFY | CORRECT | OUTPUT"
        
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

class VoteRequest(BaseModel):
    cube_id: str
    user_id: str
    vote: int  # +1 or -1

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
