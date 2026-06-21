from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import numpy as np
import asyncio
import hashlib
import threading
from collections import OrderedDict
from datetime import datetime, timezone
import os
from app.chrono_buffer_v77_ultimate import ChronoBufferV77Ultimate
from app.multi_tenant_store import MultiTenantMetadataStore
from app.chrono_decoder import ChronoCognitiveDecoder

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

GLOBAL_MEMORY_BUFFER = ChronoBufferV77Ultimate(max_personal=100000, max_shared=10000)
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
    with _cache_lock:
        _search_cache[key] = (datetime.now(timezone.utc), result)
        if len(_search_cache) > _CACHE_MAX_SIZE:
            _search_cache.popitem(last=False)
    return result

def get_memory_buffer():
    return GLOBAL_MEMORY_BUFFER

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
                "text": meta.get("essence", "")
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
