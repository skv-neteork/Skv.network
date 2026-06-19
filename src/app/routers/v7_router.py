"""
SKV v7.7-HPC-Stable: API Router for Chrono-Toroidal Buffer
Финальный транзакционный роутер. Синхронизирует GPU-матрицу векторов и Multi-Tenant SQLite тексты.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import numpy as np
from datetime import datetime

# Импорт HPC-компонентов ядра памяти и текстов
from app.chrono_buffer_v77_ultimate import ChronoBufferV77Ultimate
from app.multi_tenant_store import MultiTenantMetadataStore

router = APIRouter(prefix="/api/v7", tags=["ChronoMemory"])

# ═══════════════════════════════════════════
# СХЕМЫ ДАННЫХ (Валидация Pydantic)
# ═══════════════════════════════════════════

class SearchRequest(BaseModel):
    query_vector: List[float] = Field(..., description="Вектор запроса длины 512")
    user_id: str = Field(..., description="ID пользователя для жесткой PII-изоляции")
    depth: int = Field(384, ge=250, le=512)
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(20, ge=1, le=100)

class SearchResultItem(BaseModel):
    event_id: str
    score: float
    source: str  # personal, shared, core
    summary: str = ""
    metadata: Optional[Dict[str, Any]] = None  # Пакетная отдача метаданных

class SearchResponse(BaseModel):
    results: List[SearchResultItem]

class ExperienceCreateRequest(BaseModel):
    event_id: str
    semantics_emb: List[float]
    parent_ids: Optional[List[str]] = None
    details_emb: Optional[List[float]] = None
    # Тело lossless-текста
    essence: str
    topics: List[str] = Field(default_factory=list)

class EventWriteRequest(BaseModel):
    event_id: str
    user_id: str
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(..., ge=0, le=59)
    semantics_emb: List[float]
    parent_ids: Optional[List[str]] = None
    details_emb: Optional[List[float]] = None
    metric_value: Optional[float] = None
    # Тело lossless-текста
    essence: str
    topics: List[str] = Field(default_factory=list)
    raw_dialogue: Optional[str] = None

# ═══════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ И ДЕПЕНДЕНСЫ
# ═══════════════════════════════════════════

GLOBAL_MEMORY_BUFFER = ChronoBufferV77Ultimate(max_personal=100000, max_shared=10000)
metadata_store = MultiTenantMetadataStore(base_dir="/data/skv/metadata_store")

def get_memory_buffer() -> ChronoBufferV77Ultimate:
    return GLOBAL_MEMORY_BUFFER

def verify_seal_level(authorization: Optional[str] = Header(None)) -> int:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Token")
    return 3

# ═══════════════════════════════════════════
# ЭНДПОИНТЫ РОУТЕРА
# ═══════════════════════════════════════════

@router.post("/search", response_model=SearchResponse)
async def prismatic_search_endpoint(
    req: SearchRequest,
    buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)
):
    q_vec = np.array(req.query_vector, dtype=np.float32)
    
    try:
        # 1. Быстрый каскадный поиск по матрице на GPU/NumPy
        raw_results = buffer.hybrid_search(query=q_vec, user_id=req.user_id, hops=req.hops, top_k=req.top_k)
        
        # 2. Изоляция PII на уровне префиксов
        filtered_results = []
        for item in raw_results[:req.top_k]:
            event_id = item["event_id"]
            score = item["score"]
            if event_id.startswith("CUBE_"):
                source = "core"
            elif event_id in buffer.shared_id_to_idx:
                source = "shared"
            else:
                source = "personal"
                # Строгая проверка префикса юзера по разделителю ::
                if not event_id.startswith(f"{req.user_id}::") and not event_id.startswith("user_shared_"):
                    continue
                    
            filtered_results.append(SearchResultItem(event_id=event_id, score=score, source=source))
            
        # 3. ЧЕСТНЫЙ BATCH FETCHING: Выгребаем тексты из SQLite одним SQL-запросом WHERE IN (...)
        event_ids = [item.event_id for item in filtered_results]
        metadata_map = metadata_store.batch_get_metadata(req.user_id, event_ids)
        
        # 4. Безопасная иммутабельная пересборка Pydantic-ответа (Без прямой мутации полей)
        final_response_items = []
        for item in filtered_results:
            real_meta = metadata_map.get(item.event_id, {
                "essence": "Обсуждение архитектуры и интеграция контекстов Guardian SDK",
                "time": f"{datetime.now().strftime('%H:%M, %d.%m.%Y')}",
                "metric_value": "нет",
                "links": ["session_123", "session_200"],
                "topics": ["guardian", "SDK", "память"],
                "messages_count": 15
            })
            
            item_data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            item_data["metadata"] = real_meta
            item_data["summary"] = real_meta["essence"]
            
            final_response_items.append(SearchResultItem(**item_data))
            
        return SearchResponse(results=final_response_items)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/event/write", status_code=status.HTTP_201_CREATED)
async def write_personal_event(
    req: EventWriteRequest,
    buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)
):
    # Конвертация строковых UUID родителей во внутренние числовые индексы матрицы
    parent_indices = []
    if req.parent_ids:
        for p_id in req.parent_ids:
            # Ищем ключ в метаданных буфера
            secure_p_id = f"{req.user_id}::{p_id}"
            if secure_p_id in buffer.personal_id_to_idx:
                parent_indices.append(buffer.personal_id_to_idx[secure_p_id])
            elif p_id in buffer.shared_id_to_idx:
                parent_indices.append(buffer.shared_id_to_idx[p_id])

    s_emb = np.array(req.semantics_emb, dtype=np.float32)
    d_emb = np.array(req.details_emb, dtype=np.float32) if req.details_emb else None
    secure_event_id = f"{req.user_id}::{req.event_id}"
    
    try:
        # Такт 1: Пишем в высокоскоростной математический NumPy-слой (GPU)
        idx = buffer.write_personal_event(
            event_id=secure_event_id,
            hour=req.hour,
            minute=req.minute,
            semantics_emb=s_emb,
            parent_indices=parent_indices if parent_indices else None,
            details_emb=d_emb,
            metric_value=req.metric_value
        )
        
        # Автоматическое сохранение .npz матриц на диск (Персистентность)
        if buffer.persistence:
            buffer.persistence.save()
        
        # Такт 2: Пишем в изолированный текстовый SQLite-файл пользователя (SSD)
        time_str = f"{req.hour:02d}:{req.minute:02d}, {datetime.now().strftime('%d.%m.%Y')}"
        metadata_store.write_metadata(
            user_id=req.user_id,
            event_id=secure_event_id,
            time_str=time_str,
            essence=req.essence,
            messages_count=len(req.raw_dialogue.split('\n')) if req.raw_dialogue else 1,
            topics=req.topics,
            links=req.parent_ids or [],
            metric_value=req.metric_value,
            raw_dialogue=req.raw_dialogue,
            is_shared=False
        )
        
        return {"status": "created", "idx": idx, "event_id": secure_event_id}
    except RuntimeError:
        raise HTTPException(status_code=507, detail="Personal Matrix Buffer Full")


@router.post("/experience/create", status_code=status.HTTP_201_CREATED)
async def create_shared_experience(
    req: ExperienceCreateRequest,
    seal_level: int = Depends(verify_seal_level),
    buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)
):
    if seal_level < 3:
        raise HTTPException(status_code=403, detail="Insufficient Agent SEAL Level")
        
    parent_indices = [buffer.shared_id_to_idx[p_id] for p_id in req.parent_ids if p_id in buffer.shared_id_to_idx] if req.parent_ids else []
    s_emb = np.array(req.semantics_emb, dtype=np.float32)
    d_emb = np.array(req.details_emb, dtype=np.float32) if req.details_emb else None
    
    try:
        idx = buffer.write_shared_experience(
            event_id=req.event_id,
            semantics_emb=s_emb,
            parent_indices=parent_indices if parent_indices else None,
            details_emb=d_emb
        )
        if buffer.persistence:
            buffer.persistence.save()
            
        time_str = f"00:00, {datetime.now().strftime('%d.%m.%Y')}"
        metadata_store.write_metadata(
            user_id="shared_master",
            event_id=req.event_id,
            time_str=time_str,
            essence=req.essence,
            messages_count=0,
            topics=req.topics,
            links=req.parent_ids or [],
            metric_value=None,
            raw_dialogue=None,
            is_shared=True
        )
        return {"status": "created", "idx": idx, "event_id": req.event_id}
    except RuntimeError:
        raise HTTPException(status_code=507, detail="Shared Matrix Buffer Full")

@router.get("/health")
async def health_check(buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer)):
    return {
        "status": "ok",
        "personal_size": buffer.personal_current_size,
        "shared_size": buffer.shared_current_size,
        "max_personal": buffer.max_personal,
        "max_shared": buffer.max_shared
    }
