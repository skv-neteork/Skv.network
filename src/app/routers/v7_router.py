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

from fastapi.responses import HTMLResponse

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def homepage_v7():
    """SKV v8.0 PRO — Zero-Code AI Memory Network"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SKV v8.0 PRO — Zero-Code AI Memory Network</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', system-ui; background: #0a0a0f; color: #e6e6e6; line-height: 1.6; }
        .container { max-width: 1100px; margin: 0 auto; padding: 40px 20px; }
        h1 { font-size: 3em; background: linear-gradient(135deg, #00ff88, #00ccff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
        h2 { color: #00ccff; margin: 40px 0 20px; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .badge { display: inline-block; background: #00ff88; color: #000; padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: 0.8em; }
        .subtitle { color: #8b8b94; font-size: 1.2em; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
        .card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-left: 4px solid #00ff88; padding: 20px; border-radius: 8px; }
        .card h3 { color: #f0883e; margin-bottom: 10px; }
        code { background: #1a1a1a; color: #ff8800; padding: 2px 8px; border-radius: 4px; font-family: monospace; }
        pre { background: #13131a; padding: 15px; border-radius: 8px; overflow-x: auto; border: 1px solid #333; }
        pre code { background: none; padding: 0; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid #333; color: #666; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 SKV v8.0 PRO</h1>
        <p class="subtitle">Zero-Code AI Memory Network <span class="badge">LIVE</span></p>
        
        <h2>🚀 Quick Start (30 секунд)</h2>
        <div class="card">
            <h3>Для Custom GPT / Claude / DeepSeek</h3>
            <p>1. Actions → Import OpenAPI Schema:</p>
            <pre><code>https://skv.network/api/v7/agent/openapi.json</code></pre>
            <p>2. Auth: Bearer <code>sk_xxx</code></p>
            <p>3. В новый чат вставь: работай через SKV, первый вызов memory со step 0, дальше ищи когда прошлое меняет ответ, каждый ход пиши в remember.</p>
        </div>
        
        <h2>🧠 Архитектура v8.0</h2>
        <div class="grid">
            <div class="card">
                <h3>4-уровневая память</h3>
                <p><strong>Level 0:</strong> Raw dialogue (30 дней → архив)</p>
                <p><strong>Level 1:</strong> Summary (вектор 768 + JSON)</p>
                <p><strong>Level 2:</strong> Memory Map (темы, timeline)</p>
                <p><strong>Level 3:</strong> Cubes (атомарные знания + граф)</p>
            </div>
            <div class="card">
                <h3>Гибридный поиск</h3>
                <p><strong>HNSW:</strong> семантический поиск (bge-base 768)</p>
                <p><strong>FTS5:</strong> точные совпадения по словам</p>
                <p><strong>Spreading Activation:</strong> по графу кубов</p>
                <p><strong>RRF:</strong> слияние результатов</p>
            </div>
            <div class="card">
                <h3>Конституция CUBE 00-05</h3>
                <p><strong>CUBE 00:</strong> Core Algorithm</p>
                <p><strong>CUBE 01:</strong> Harm Prevention</p>
                <p><strong>CUBE 02:</strong> Truth & Verification</p>
                <p><strong>CUBE 03:</strong> Moral Compass</p>
                <p><strong>CUBE 04:</strong> Anti-Manipulation</p>
                <p><strong>CUBE 05:</strong> Agent Protocol</p>
            </div>
            <div class="card">
                <h3>Zero-Code Gateway</h3>
                <p>OpenAPI 3.1.0 спецификация</p>
                <p>Function Calling для LLM</p>
                <p>Автоматический вызов инструментов</p>
                <p>Никакого кода на стороне агента</p>
            </div>
        </div>
        
        <h2>📡 API Endpoints</h2>
        <div class="grid">
            <div class="card">
                <h3>READ</h3>
                <p><code>POST /api/v7/memory</code> — поиск памяти</p>
                <p><code>GET /api/v7/constitution</code> — кубы CUBE 00-05</p>
                <p><code>GET /api/v7/agent/openapi.json</code> — схема</p>
            </div>
            <div class="card">
                <h3>WRITE</h3>
                <p><code>POST /api/v7/experience/create</code> — создать куб</p>
                <p><code>POST /api/v7/experience/vote</code> — голос</p>
                <p><code>POST /api/v7/feedback</code> — отчёт</p>
            </div>
        </div>
        
        <h2>🔗 Ссылки</h2>
        <div class="card">
            <p>📖 <a href="/docs">Swagger UI</a> — интерактивная документация</p>
            <p>📜 <a href="/api/v7/constitution">Конституция CUBE 00-05</a></p>
            <p>🔧 <a href="/api/v7/agent/openapi.json">OpenAPI Schema</a></p>
            <p>🤖 <a href="/api/v7/agent/prompt">System Prompt для агентов</a></p>
        </div>
        
        <footer>
            <p>SKV v8.0 PRO | skv.network | 2026 | Zero-Code AI Memory Network</p>
        </footer>
    </div>
</body>
</html>"""
    return html

class SearchRequest(BaseModel):
    query_vector: Optional[List[float]] = None
    query_text: Optional[str] = None
    user_id: Optional[str] = None
    depth: int = Field(384, ge=250, le=512)
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(20, ge=1, le=100)


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str = "default"
    step: int = 0
    last_seal: Optional[str] = None
    chat_history: List = []  # accepts strings or {role, content} objects
    top_k: int = 5

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

class MemoryRequest(BaseModel):
    query_vector: Optional[List[float]] = None
    query_text: Optional[str] = None
    user_id: Optional[str] = None
    step: int = Field(0, ge=0)
    last_seal: str = Field("")
    hops: int = Field(2, ge=0, le=4)
    top_k: int = Field(5, ge=1, le=20)
    focus_words: Optional[List[str]] = None
    kind: Optional[str] = None      # shelf filters; default: all shelves
    source: Optional[str] = None
    project: Optional[str] = None
    # memory v2 (all optional; defaults keep the legacy response)
    view: Optional[str] = None        # legacy | agent | debug
    session_id: Optional[str] = None
    start: bool = False               # force the first-request pack (map + windows)
    probe: bool = False               # extra lookup: no step bump, no duty check
    interact: bool = False            # view=agent: first call of a user turn (bumps step, checks duty)
    format: Optional[str] = None      # view=agent: json | text | both
    focus_event_id: Optional[str] = None
    lens_offset: int = Field(0, ge=0, le=200)
    radius: int = Field(2, ge=0, le=6)
    budget_map: Optional[int] = None
    budget_raw: Optional[int] = None
    budget_l1: Optional[int] = None
    budget_l2: Optional[int] = None
    budget_critical: Optional[int] = None
    budget_constitution: Optional[int] = None
    budget_hits: Optional[int] = None
    budget_lens: Optional[int] = None
    budget_followup: Optional[int] = None

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
#_thread = threading.Thread(target=background_vectorizer, daemon=True)
#_thread.start()
print("[INJECTOR] Background vectorizer started (every 30 min)", flush=True)

def background_l1_l2():
    """LLM L1/L2 summaries every 15 min when memory_config bg_llm=true (see memory_v2_llm.py)."""
    import time as _time
    while True:
        _time.sleep(900)
        try:
            from app import memory_v2 as _mv2
            if not bool(_mv2.config().get("bg_llm", False)):
                continue
            from app import memory_v2_llm as _mvl
            _mvl.run_cycle()
        except Exception as e:
            print(f"[L1/L2] Error: {e}", flush=True)

_l1l2_thread = threading.Thread(target=background_l1_l2, daemon=True)
_l1l2_thread.start()
try:
    from app import memory_v2_windows as _mvw_boot
    _mvw_boot.start_maintenance()   # additive migration + L1 ranges + auto L2 blocks, every 15 min
except Exception as _e:
    print(f"[memory_v2] maintenance not started: {_e}", flush=True)
print("[L1/L2] Auto-generator started (every 15 min)", flush=True)

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
def check_rate_limit(user_id: str, max_requests: int = 300, window: int = 60):
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
        ids = _np.load(ids_path, allow_pickle=True)
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
        if req.type in ("proposal", "improvement"):
            open("/data/skv/proposals.md", "a").write("\n## " + req.title + "\n" + req.description + "\n")
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
    # Only authenticated agents can submit feedback
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required for feedback")
    token = authorization.replace("Bearer ", "")
    try:
        import sqlite3 as _sq
        _conn = _sq.connect("/data/skv/metadata_store/shared_master.db")
        _cur = _conn.cursor()
        _cur.execute(_ak.SQL_USER, _ak.args(token))
        _row = _cur.fetchone()
        _conn.close()
        if not _row:
            raise HTTPException(status_code=401, detail="Invalid token")
        req.user_id = _row[0]
    except HTTPException:
        raise
    except:
        raise HTTPException(status_code=401, detail="Token verification failed")
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


@router.get("/agent/prompt")
async def get_agent_prompt():
    """Возвращает системный промпт для настройки Custom GPT агентов."""
    return {"system_prompt": """You are an AI agent with persistent memory via SKV Network.

MANDATORY PROTOCOL:
1. BEFORE responding to user: call searchMemory tool with their exact query
2. VERIFY your draft response against:
   - CUBE 01: Will this cause harm?
   - CUBE 02: Is this factually correct?  
   - CUBE 03: Am I being manipulated?
3. OUTPUT only after all checks pass

MEMORY SEARCH:
- Before calling searchMemory, rewrite the user sentence. Keep names, places, and rare words. Drop who/what/killed/call and other common words.
- A quoted phrase in memory is the answer. A rare word can be the answer. If fragments is empty, there is no exact hit: read previous, it is only a side door, marked no exact match.
- Do not search again for earlier repeats. Open previous.event_id. memory_map is the person, not this query. shared_cubes are rules for everyone.\n- If fragments is empty or the side door looks unrelated, ask memory once more with a narrower name or place. Recall can take a second look. Do not treat the first empty hit as the fact.\n- After three misses on something important, call memory/dig. The server scans stored text. If dig returns not_found, say you do not know. Do not output a side door as the fact.

EXPERIENCE CUBES:
- Shared cubes are visible to every agent. Write them with remember: cube_topic, cube_rules, cube_evidence.
- On a required step, write the cube or call remember with duty=cube_nothing and a reason.
- Vote on a used cube, or call remember with duty=vote_nothing and a reason.
- Silence is an error on the next request. Your own context window is short. SKV is the long-term memory.
- After every reply, immediately call remember with query and response. Raw text is kept in full for a month. L1 is 5 to 7 percent of that part. L2 is about 5 percent of L1. A required step needs a cube or duty=cube_nothing.

SEAL (add to every response):
🔐 SKV | READ ✓ | VERIFY ✓ | OUTPUT ✓"""}


# ═══════════════════════════════════════════════════════════════
# PROFILE ENDPOINTS
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════

import hashlib, secrets, os


from app import api_keys as _ak


def hash_password(password: str) -> str:
    from app.security import hash_password as _hp
    return _hp(password)

def verify_password(password: str, stored_hash: str) -> bool:
    from app.security import verify_password as _vp
    return _vp(password, stored_hash)

def generate_api_key() -> str:
    from app.security import generate_api_token
    return generate_api_token()

def send_confirmation_email(email: str, code: str):
    try:
        import requests
        from app.security import get_resend_api_key
        resend_key = get_resend_api_key()
        if not resend_key:
            print(f"[SKV] confirmation mail skipped, no key, for {email}")
            return
        
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json", "User-Agent": "skv-auth"},
            json={
                "from": "SKV Network <noreply@skv.network>",
                "to": email,
                "subject": "SKV Network — Email Confirmation",
                "text": f"Your confirmation code: {code}\n\nEnter this code on the registration page to activate your account."
            },
            timeout=10
        )
        if resp.status_code == 200:
            print(f"[SKV] Email sent to {email}: {resp.json().get('id', 'ok')}")
        else:
            print(f"[SKV] Email failed for {email}: {resp.status_code}")
    except Exception as e:
        print(f"[SKV] Email error for {email}: {e}")

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ConfirmRequest(BaseModel):
    email: str
    code: str

@router.post("/auth/register")
async def register(req: RegisterRequest):
    try:
        import sqlite3
        if not req.email or "@" not in req.email:
            raise HTTPException(status_code=400, detail="Valid email required")
        if not req.password or len(req.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        
        # Create users table if not exists
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY, password_hash TEXT, confirmed INTEGER DEFAULT 0,
            confirmation_code TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        
        # Check if email exists
        cur.execute("SELECT email FROM users WHERE email = ?", (req.email,))
        if cur.fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="Email already registered")
        
        password_hash = hash_password(req.password)
        confirmation_code = secrets.token_hex(4).upper()
        
        cur.execute("INSERT INTO users (email, password_hash, confirmation_code) VALUES (?, ?, ?)",
                   (req.email, password_hash, confirmation_code))
        conn.commit()
        conn.close()
        
        send_confirmation_email(req.email, confirmation_code)
        
                # Create personal database for new user
        try:
            db_name = req.email.replace('@', '').replace('.', '')
            user_conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
            user_cur = user_conn.cursor()
            user_cur.execute("CREATE TABLE IF NOT EXISTS event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, messages_count INTEGER, links_json TEXT, topics_json TEXT, raw_dialogue TEXT, subject TEXT, action TEXT, object TEXT, status TEXT, metric_value REAL)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS personal_vectors (event_id TEXT PRIMARY KEY, vector_blob BLOB)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY, user_id TEXT, messages_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_cur.execute("CREATE TABLE IF NOT EXISTS experience_cubes (cube_id TEXT PRIMARY KEY, topic TEXT, essence TEXT, rules_markdown TEXT, evidence TEXT, session_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            user_conn.commit()
            user_conn.close()
        except Exception as e:
            print(f"Failed to create user DB: {e}")
        
        return {"status": "ok", "message": "Registration successful. Check email for confirmation code."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/confirm")
async def confirm_email(req: ConfirmRequest):
    try:
        import sqlite3
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute("SELECT confirmation_code FROM users WHERE email = ? AND confirmed = 0", (req.email,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="User not found or already confirmed")
        
        if row[0] != req.code:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid confirmation code")
        
        cur.execute("UPDATE users SET confirmed = 1, confirmation_code = NULL WHERE email = ?", (req.email,))
        
        # Create API key
        api_key = _ak.issue(req.email, "register", conn=conn)
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Email confirmed!", "api_key": api_key}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/login")
async def login(req: LoginRequest):
    try:
        import sqlite3
        from app.security import needs_rehash
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT email, password_hash FROM users WHERE email = ? AND confirmed = 1",
            (req.email,),
        )
        row = cur.fetchone()
        if not row or not verify_password(req.password, row[1] or ""):
            conn.close()
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if needs_rehash(row[1] or ""):
            try:
                cur.execute(
                    "UPDATE users SET password_hash = ? WHERE email = ?",
                    (hash_password(req.password), req.email),
                )
                conn.commit()
            except Exception:
                pass

        # Keys are stored hashed, so an old key cannot be shown again: each login issues a new key.
        # Older keys keep working; at most 5 login keys stay active (the oldest login key is retired).
        api_key = _ak.issue(req.email, "login", conn=conn)
        old = [r[0] for r in cur.execute("SELECT rowid FROM user_api_keys WHERE user_id = ? AND label = 'login' AND is_active = 1 ORDER BY created_at DESC, rowid DESC", (req.email,)).fetchall()][5:]
        for _rid in old:
            cur.execute("UPDATE user_api_keys SET is_active = 0 WHERE rowid = ?", (_rid,))
        conn.commit()
        conn.close()
        return {"status": "ok", "api_key": api_key, "user_id": req.email,
                "note": "Keys are stored hashed. This login key is shown once; keep it. Older keys still work. Manage keys at /profile."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/profile")
async def get_profile(authorization: str = Header(None)):
    """Get user profile with API keys and stats."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.replace("Bearer ", "")
    try:
        import sqlite3
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute(_ak.SQL_USER, _ak.args_keys_only(token))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = row[0]
        
        # Get all user's keys
        cur.execute("SELECT rowid, key_prefix, is_active, created_at, expires_at, label FROM user_api_keys WHERE user_id = ?", (user_id,))
        keys = [{"key": _ak.display(p, rid), "id": rid, "active": bool(a), "created": c, "expires": e, "label": l} for rid, p, a, c, e, l in cur.fetchall()]
        
        # Get stats from user's DB
        db_name = user_id.replace("@", "").replace(".", "")
        try:
            user_conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
            user_cur = user_conn.cursor()
            user_cur.execute("SELECT COUNT(*) FROM event_metadata")
            events = user_cur.fetchone()[0]
            user_cur.execute("SELECT COUNT(*) FROM personal_vectors")
            vectors = user_cur.fetchone()[0]
            user_conn.close()
        except:
            events = 0
            vectors = 0
        
        conn.close()
        return {
            "user_id": user_id,
            "api_keys": keys,
            "stats": {
                "events": events,
                "vectors": vectors
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/profile/keys")
async def create_api_key(authorization: str = Header(None)):
    """Generate new API key."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.replace("Bearer ", "")
    try:
        import sqlite3, uuid
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute(_ak.SQL_USER, _ak.args_keys_only(token))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = row[0]
        
        new_key = _ak.issue(user_id, "profile", conn=conn)
        conn.commit()
        conn.close()
        return {"status": "ok", "api_key": new_key}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/profile/keys/{key}")
async def revoke_api_key(key: str, authorization: str = Header(None)):
    """Revoke an API key."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.replace("Bearer ", "")
    try:
        import sqlite3
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute(_ak.SQL_USER, _ak.args_keys_only(token))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = row[0]
        
        # Only allow revoking own keys
        _m = __import__("re").search(r"#(\d+)$", key.strip())
        if _m:
            cur.execute("UPDATE user_api_keys SET is_active = 0 WHERE rowid = ? AND user_id = ?", (int(_m.group(1)), user_id))
        else:
            cur.execute("UPDATE user_api_keys SET is_active = 0 WHERE api_key IN (?, ?) AND user_id = ?", (key, _ak.hash_key(key), user_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Key not found or not yours")
        conn.commit()
        conn.close()
        return {"status": "ok", "message": "Key revoked"}
    except HTTPException:
        raise
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


def build_memory_map(user_id: str, step: int = 0) -> str:
    """Memory Pyramid for external agents — 4 non-overlapping layers.

    Layers (no content reuse between them):
      1. Raw      — recent dialogues WITHOUT >>> lines (those go to Critical)
      2. L1       — topic summaries from summary_l1 only
      3. L2       — user profile / map from summary_l2 only
      4. Critical — only lines containing >>> (never compressed away)

    step=0  → full map (Raw + L1 + L2 + Critical)
    step>0  → short map (L1 compact + L2 compact + Critical + agent hint)

    Char budgets (~4 chars/token):
      full:  raw[:8000], l1[:8000], l2[:40000], crit[:2000]
      short: l2[:4000], crit[:2000]
    """
    import sqlite3
    import json as _json

    AGENT_HINT = (
        "\n💡 NEED MORE DATA?\n"
        "• searchMemory tool (POST /api/v7/memory) — hybrid HNSW+FTS5 search by query\n"
        "• GET /api/v7/event/{id} — full event text by event_id from search results"
    )

    db_name = user_id.replace("@", "").replace(".", "")
    db_path = f"/data/skv/metadata_store/{db_name}.db"

    if not os.path.exists(db_path):
        return "No memory yet." + AGENT_HINT

    full = step == 0
    parts: List[str] = []
    try:
        from app import memory_v2 as _mv2
        _ord = "rowid" if _mv2.config().get("legacy_rowid_order", True) else "event_id"
    except Exception:
        _ord = "event_id"

    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            cur = conn.cursor()

            # ── 4. CRITICAL first (collect set so Raw can exclude these lines) ──
            cur.execute(
                "SELECT time_str, raw_dialogue FROM event_metadata "
                "WHERE raw_dialogue LIKE '%>>>%' ORDER BY " + _ord + " DESC LIMIT 30"
            )
            crit: List[str] = []
            crit_line_set: set = set()
            for time_str, raw_text in cur.fetchall():
                if not raw_text:
                    continue
                for line in raw_text.split("\n"):
                    stripped = line.strip()
                    if ">>>" in stripped and stripped not in crit_line_set:
                        crit_line_set.add(stripped)
                        crit.append(f"[{time_str or '?'}] {stripped}")

            # ── 1. RAW (full only) — dialogues without >>> / L1-debug noise ──
            if full:
                cur.execute(
                    """SELECT essence, raw_dialogue FROM event_metadata
                       WHERE raw_dialogue IS NOT NULL
                         AND raw_dialogue NOT LIKE '%Выяснилось%'
                         AND raw_dialogue NOT LIKE '%Принято решение%'
                       ORDER BY """ + _ord + """ DESC LIMIT 40"""
                )
                raw: List[str] = []
                seen_raw: set = set()
                for essence, dialogue in cur.fetchall():
                    # Strip Critical (>>>) from BOTH essence and dialogue —
                    # >>> content lives only in the Critical layer (no overlap)
                    essence_str = "\n".join(
                        ln for ln in (essence or "").split("\n") if ">>>" not in ln
                    ).strip()
                    dialogue_lines = [
                        ln for ln in (dialogue or "").split("\n") if ">>>" not in ln
                    ]
                    dialogue_str = "\n".join(dialogue_lines).strip()
                    if not dialogue_str and not essence_str:
                        continue  # pure-Critical event → skip in Raw
                    # Tail keeps latest turn context
                    tail = dialogue_str[-800:] if len(dialogue_str) > 800 else dialogue_str
                    if essence_str and tail and essence_str not in tail:
                        text = (
                            f"{essence_str}\n…{tail}"
                            if len(dialogue_str) > 800
                            else f"{essence_str}\n{tail}"
                        )
                    else:
                        text = essence_str or tail
                    text = text.strip()
                    if text and ">>>" not in text and text not in seen_raw:
                        seen_raw.add(text)
                        raw.append(text)
                if raw:
                    parts.append("=== RECENT ACTIVITY (Raw) ===\n" + ("\n---\n".join(raw))[:8000])

            # ── 2. L1 — summaries table only, compact when step>0 ──
            if True:
                limit = 40 if full else 5
                cur.execute(
                    "SELECT topic, summary_text FROM summary_l1 ORDER BY rowid DESC LIMIT ?",
                    (limit,)
                )
                l1: List[str] = []
                seen_l1: set = set()
                for topic, summary in cur.fetchall():
                    # Skip L1 rows that are pure Critical markers
                    topic_s = (topic or "").strip()
                    summary_s = (summary or "").strip()
                    if ">>>" in topic_s or ">>>" in summary_s:
                        continue
                    line = f"## {topic_s or '?'}: {summary_s}"
                    if line not in seen_l1:
                        seen_l1.add(line)
                        l1.append(line)
                if l1:
                    parts.append("=== L1 SUMMARIES ===\n" + ("\n".join(l1))[:8000])

            # ── 3. L2 PROFILE — always (compact when step>0) ──
            l2_row = None
            try:
                cur.execute("SELECT map_json FROM summary_l2 ORDER BY last_updated DESC LIMIT 1")
                l2_row = cur.fetchone()
            except Exception:
                l2_row = None
            if l2_row and l2_row[0]:
                l2_budget = 2000 if full else 1500
                l2_raw = l2_row[0]
                if not full:
                    # Compact: themes + short profile if JSON; else truncate
                    try:
                        l2_map = _json.loads(l2_raw) if isinstance(l2_raw, str) else l2_raw
                        if isinstance(l2_map, dict):
                            compact_bits = []
                            themes = l2_map.get("main_themes") or l2_map.get("themes") or []
                            if themes:
                                compact_bits.append(
                                    "Themes: " + ", ".join(str(t) for t in themes[:8])
                                )
                            profile = l2_map.get("user_profile") or l2_map.get("profile") or ""
                            if profile:
                                compact_bits.append(f"Profile: {str(profile)[:800]}")
                            facts = l2_map.get("key_facts") or l2_map.get("facts") or []
                            if facts:
                                compact_bits.append(
                                    "Facts: " + "; ".join(str(f)[:80] for f in facts[:5])
                                )
                            l2_text = "\n".join(compact_bits) if compact_bits else str(l2_raw)[:l2_budget]
                        else:
                            l2_text = str(l2_raw)[:l2_budget]
                    except Exception:
                        l2_text = str(l2_raw)[:l2_budget]
                else:
                    l2_text = str(l2_raw)[:l2_budget]
                parts.append(f"=== L2 PROFILE ===\n{l2_text}")

            # ── 4. CRITICAL — always included (never drop) ──
            if crit:
                parts.append("=== >>> CRITICAL ===\n" + ("\n".join(crit))[:2000])

            # ── 5. Agent hint — always ──
            mode_note = (
                "\n[Memory Map: FULL — step=0]"
                if full
                else "\n[Memory Map: SHORT — step>0; call with step=0 for full Raw+L1+L2+Critical]"
            )
            parts.append(mode_note + AGENT_HINT)

    except Exception as e:
        logger.warning("[build_memory_map] %s: %s", user_id, e)
        return "No memory yet." + AGENT_HINT

    return "\n\n".join(parts) if parts else ("No memory yet." + AGENT_HINT)


_ROWS_CACHE = {}


def _cached_scan(name, which):
    """Per-account cache of the full-scan rows used by span/lens; refreshed when rows change."""
    import sqlite3 as _sq
    path = f"/data/skv/metadata_store/{name}.db"
    conn = _sq.connect(path, timeout=10)
    try:
        sig = conn.execute("select count(*), max(rowid) from event_metadata").fetchone()
        key = (name, which)
        hit = _ROWS_CACHE.get(key)
        if hit and hit[0] == sig:
            return hit[1]
        if which == "norm":
            rows = [(raw or "").lower().replace("-", "").replace(" ", "") for (raw,) in conn.execute("select raw_dialogue from event_metadata")]
        elif which == "grokexp":
            rows = conn.execute("select event_id, raw_dialogue from event_metadata where event_id like '%grokexp_%'").fetchall()
            rows = [(e, r, (r or "").lower().replace("-", "").replace(" ", "")) for e, r in rows]
        else:
            rows = conn.execute("select event_id, raw_dialogue from event_metadata where raw_dialogue like '%>>>%'").fetchall()
            rows = [(e, r, (r or "").lower().replace("-", "").replace(" ", "")) for e, r in rows]
        if len(_ROWS_CACHE) > 60:
            _ROWS_CACHE.pop(next(iter(_ROWS_CACHE)))
        _ROWS_CACHE[key] = (sig, rows)
        return rows
    finally:
        conn.close()


@router.post("/memory")
async def guardian_l1_memory(req: MemoryRequest, buffer: ChronoBufferV77Ultimate = Depends(get_memory_buffer), authorization: str = Header(None)):
    # Извлекаем user_id из токена
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        try:
            import sqlite3 as _sq
            _conn = _sq.connect("/data/skv/metadata_store/shared_master.db")
            _cur = _conn.cursor()
            _cur.execute(_ak.SQL_USER, _ak.args(token))
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
            _cur.execute(_ak.SQL_USER, _ak.args(token))
            _row = _cur.fetchone()
            if _row:
                req.user_id = _row[0]
            _conn.close()
        except:
            pass
    if not req.user_id or not req.user_id.strip():
        raise HTTPException(status_code=422, detail="user_id cannot be empty")
    check_rate_limit(req.user_id)
    from app import memory_v2 as _mv2
    _view = ((req.view or _mv2.config().get("default_view", "legacy")) if _mv2.enabled() else "legacy").lower()
    if _view not in ("legacy", "agent", "debug"):
        _view = "legacy"
    _no_bump = bool(req.probe) or (_view == "agent" and not req.interact)
    if _no_bump:
        step = _mv2.peek_step(req.user_id)
    else:
        try:
            from app.account_memory import next_step
            step = next_step(req.user_id)
        except Exception:
            step = req.step
    duty_error = ""
    try:
        import sqlite3 as _duty
        prev = step - 1
        if prev > 0 and not _no_bump:
            conn = _duty.connect("/data/skv/metadata_store/shared_master.db")
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS agent_duty (id INTEGER PRIMARY KEY, user_id TEXT, step INTEGER, duty TEXT, reason TEXT, created_at TEXT)")
            rows = cur.execute("SELECT duty FROM agent_duty WHERE user_id=? AND step=?", (req.user_id, prev)).fetchall()
            done = {r[0] for r in rows}
            missed = []
            if "saved" not in done:
                missed.append("the turn was not saved with remember")
            if prev % 5 == 0 and not ({"vote", "vote_nothing"} & done):
                missed.append("vote was required and neither a vote nor vote_nothing was sent")
            if prev % 10 == 0 and not ({"cube", "cube_nothing"} & done):
                missed.append("cube was required and neither a cube nor cube_nothing was sent")
            conn.close()
            if missed:
                duty_error = "ERROR: previous step " + str(prev) + " was not closed. " + "; ".join(missed) + "."
    except Exception:
        duty_error = ""
    print(f'DEBUG query_text={repr(req.query_text)}', flush=True)
    from app import semantic as _sem
    _sem_tag = _sem.active_tag()
    _sem_vec = None
    if req.query_text and _sem_tag != "bge":
        q_vec = None
    elif req.query_text:
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
    raw_results = []
    _fts_ranked = []
    try:
        # v7.8: pass layer_weights for dynamic masks
        lw = req.layer_weights if hasattr(req, 'layer_weights') else None
        # Try VectorRouter (HNSW) first, fallback to _cached_search
        if _sem_tag != "bge" and req.query_text:
            hnsw_results, _sem_vec = _sem.semantic_events(req.user_id, req.query_text, k=max(req.top_k * 3, 20))
            hnsw_results = [(e, sc) for e, sc in hnsw_results if e.startswith(f"{req.user_id}::")]
        else:
            hnsw_results = GLOBAL_VECTOR_ROUTER.search(req.user_id.replace("@", "").replace(".", ""), q_vec, top_k=req.top_k)
        raw_results = []
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
        if hnsw_results:
            raw_results = [{"event_id": eid, "score": score, "source": "personal"} for eid, score in hnsw_results]
            
            # FTS5 boost using focus_words from agent

        elif q_vec is not None:
            raw_results = _cached_search(buffer, q_vec, req.user_id, req.hops, req.top_k, layer_weights=lw)
        
        if req.query_text and _sem.fusion_mode() == "rrf":
            # Reciprocal Rank Fusion (k=60) of semantic HNSW + bm25 FTS5; FTS-only hits included
            _fts_ranked = _sem.fts_ranked(req.user_id, req.query_text, limit=30)
            _fused = _sem.rrf([(r["event_id"], r["score"]) for r in raw_results], _fts_ranked)
            _sem_scores = {r["event_id"]: r["score"] for r in raw_results}
            raw_results = [{"event_id": e, "score": round(sc, 5), "semantic": _sem_scores.get(e), "source": "personal"}
                           for e, sc in _fused[:max(req.top_k * 2, 10)]]
            # newer fact on the same subject ranks above the older one
            try:
                _order, _sup = _sem.supersede(req.user_id, [r["event_id"] for r in raw_results])
                _by_id = {r["event_id"]: r for r in raw_results}
                raw_results = [_by_id[i] for i in _order if i in _by_id]
                for _old, _new in _sup.items():
                    if _old in _by_id:
                        _by_id[_old]["superseded_by"] = _new
            except Exception as _e:
                print(f"[semantic] supersede skipped: {_e}", flush=True)
        if getattr(req, "kind", None) or getattr(req, "source", None) or getattr(req, "project", None):
            from app import shelves as _sh
            _ok = _sh.allowed(req.user_id, [r["event_id"] for r in raw_results] + [e for e, _ in _fts_ranked], req.kind, req.source, req.project)
            raw_results = [r for r in raw_results if r["event_id"] in _ok]
            _fts_ranked = [x for x in _fts_ranked if x[0] in _ok]
        # HYBRID: Multi-word FTS5 boost (legacy)
        if req.query_text and raw_results and _sem.fusion_mode() != "rrf":
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
            # Enhanced output: top-1 full text, rest essence
            memory_parts_v7 = []
            for i, r in enumerate(filtered_dicts[:5]):
                meta = r.get("metadata", {})
                eid = r.get("event_id", "?")
                score = r.get("score", 0)
                links = meta.get('links_json', '')
                link_str = ""
                if links and links.strip() and links != '[]':
                    try:
                        links_data = json.loads(links) if isinstance(links, str) else links
                        if isinstance(links_data, dict):
                            link_str = " | 🔗 " + ", ".join(list(links_data.keys())[:3])
                        elif isinstance(links_data, list):
                            link_str = " | 🔗 " + ", ".join([str(l)[:30] for l in links_data[:3]])
                    except:
                        pass
                
                if i == 0:
                    raw = meta.get('raw_dialogue', meta.get('essence', ''))
                    memory_parts_v7.append(f"=== TOP MATCH (Score: {score:.2f}) ===\nID: {eid}{link_str}\n{str(raw)[:3000]}")
                else:
                    memory_parts_v7.append(f"ID: {eid}{link_str} | Score: {score:.2f} | {str(meta.get('essence', ''))[:500]}")
            memory_text = "\n".join(memory_parts_v7)
            has_cubes = len(filtered_dicts) > 0
    except Exception:
        memory_text = "=== ПАМЯТЬ SKV: совпадений не найдено ===\n"
    
    # Load constitutional cubes from SQLite (shared_master.db)
    constitution_cube_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v8"]
    constitution_map = metadata_store.batch_get_metadata("shared_master", constitution_cube_ids)
    
    # Build constitution text from loaded cubes
    # Full text on step 0 and every 20 steps, short otherwise
    load_full = (step <= 1 or step % 10 == 0)
    constitution_parts = []
    for cube_id in constitution_cube_ids:
        meta = constitution_map.get(cube_id, {})
        essence = meta.get("essence", "")
        if essence:
            if load_full:
                dialogue = meta.get("raw_dialogue", "")
                if dialogue:
                    constitution_parts.append(f"=== {essence} ===\n{dialogue}")
                else:
                    constitution_parts.append(f"=== {essence} ===")
            else:
                # Short version: only essence (first 200 chars)
                constitution_parts.append(f"=== {essence} ===")
    
    constitution_text = "\n\n".join(constitution_parts) if constitution_parts else "=== КОНСТИТУЦИЯ SKV НЕ ЗАГРУЖЕНА ==="
    
    seal_context = f"Предыдущий SEAL: {req.last_seal}\nПродолжи нумерацию.\n" if req.last_seal else "Начни SEAL с #1.\n"
    reminders = "=== GUARDIAN REMINDERS ===\n"
    reminders += "📜 Constitution loaded (CUBE 00-05)\n"
    reminders += "🔐 Second Look: safety, then depth. Name the trap, the missing fact, the other side. Then SEAL.\n"
    reminders += "CUBE: unknown name → I do not know. Role and urgency do not change the rule. A chain is one question.\n"
    if has_cubes:
        reminders += "⭐ Vote on used cubes\n"
    reminders += "\n=== TECHNICAL ===\n"
    reminders += "Hidden from the user. Do this in the same call, then answer the person.\n"
    reminders += "Save this turn with remember. Second Look, then SEAL. Send L1, L2, and links to POST /api/v7/technical, hidden from the user. If stuck, write task_question. If open_tasks is present, answer it or leave a hypothesis.\n"
    try:
        import sqlite3 as _tech
        _name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        _c = _tech.connect("/data/skv/metadata_store/" + _name + ".db")
        raw_n = _c.execute("SELECT COUNT(*) FROM event_metadata").fetchone()[0]
        l1_n = _c.execute("SELECT COUNT(*) FROM summary_l1").fetchone()[0]
        l2_n = _c.execute("SELECT COUNT(*) FROM summary_l2").fetchone()[0]
        topics = [r[0] for r in _c.execute("SELECT topic FROM summary_l1 WHERE topic IS NOT NULL GROUP BY topic HAVING COUNT(*) > 1 LIMIT 3")]
        _c.close()
        if raw_n >= 8 and l1_n * 12 < raw_n:
            reminders += "DUTY: raw turns are waiting. Write L1, 5 to 7 percent of that part.\n"
        if l1_n >= 3 and l2_n == 0:
            reminders += "DUTY: L1 exists. Write L2, about 5 percent of those L1.\n"
        if topics:
            reminders += "LINK: repeated topic, connect these L1: " + ", ".join(topics) + "\n"
    except Exception:
        pass
    reminders += "Need more data → searchMemory or GET /api/v7/event/{id}\n"
    if step > 1 and not getattr(req, "last_seal", "") and not _no_bump:
        reminders = "ERROR: previous response had no SKV seal. Second Look was not shown.\n" + reminders
    if duty_error:
        reminders = duty_error + "\n" + reminders
    if step and step % 10 == 0:
        reminders += "• REQUIREMENT: write a shared experience cube, or call remember with duty=cube_nothing and a reason. Silence counts as forgotten.\n"
    if step and step % 5 == 0:
        reminders += "• REQUIREMENT: vote on used experience cubes, or call remember with duty=vote_nothing and a reason.\n"

    # Memory Pyramid via single source (full at step=0, short at step>0)
    memory_map_text = build_memory_map(req.user_id, step=step)

    # Smart assembly: full constitution+map at step 0 / every 20; short map always when step>0
    if step <= 1 or step % 10 == 0:
        prompt_text = f"{memory_text}\n\n{memory_map_text}\n{constitution_text}\n\n{seal_context}\n{reminders}"
    else:
        # Short: search hits + compact Memory Map (L2+Critical+hint) + reminders
        prompt_text = f"{memory_text}\n\n{memory_map_text}\n\n{seal_context}\n{reminders}"
    # Раздельная выдача
    vector_top = raw_results[:10] if raw_results else []
    fts_top = []
    focus = getattr(req, 'focus_words', None) or []
    if not focus and getattr(req, 'query_text', None):
        focus = [w.strip(".,!?;:\"'") for w in req.query_text.split() if len(w) > 3][:8]
    if focus:
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            fts_cur = fts_conn.cursor()
            phrase = " ".join(focus)
            raw_phrase = (getattr(req, "query_text", "") or "").strip()
            if len(raw_phrase.split()) > 2:
                fts_cur.execute("SELECT event_id FROM event_metadata WHERE raw_dialogue LIKE ? LIMIT 3", ("%" + raw_phrase + "%",))
                for (eid,) in fts_cur.fetchall():
                    if eid not in [f.get("event_id") for f in fts_top]:
                        fts_top.append({"event_id": eid, "matched_word": raw_phrase, "source": "phrase"})
            if len(focus) > 1 and not fts_top:
                try:
                    fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ? LIMIT 5', ('"' + phrase + '"',))
                    for (eid,) in fts_cur.fetchall():
                        if eid not in [f.get('event_id') for f in fts_top]:
                            fts_top.append({'event_id': eid, 'matched_word': phrase, 'source': 'phrase'})
                except Exception:
                    pass
            if not fts_top and _fts_ranked:
                for eid, _sc in _fts_ranked[:10]:
                    fts_top.append({'event_id': eid, 'matched_word': '', 'source': 'fts', 'bm25': round(_sc, 3)})
            if not fts_top:
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
    
    common = {"call", "such", "time", "best", "girl", "revolution", "this", "that", "with", "from", "have", "were", "been", "your", "killed", "who", "what", "where", "when", "book"}
    no_exact = False
    phrases = [f for f in fts_top if f.get("source") == "phrase"]
    if phrases:
        fts_top = phrases
    else:
        strong = [f for f in fts_top if (f.get("matched_word") or "").lower() not in common]
        fts_top = strong
        if not fts_top and vector_top:
            vector_top = vector_top
    if not phrases and vector_top:
        exact_ids = {f.get("event_id") for f in fts_top}
        vector_top = [v for v in vector_top if v.get("event_id") not in exact_ids] + [v for v in vector_top if v.get("event_id") in exact_ids]
        vector_top = list(reversed(vector_top)) if False else vector_top
        # meaning outranks a lone common word; common words already removed
        if not fts_top:
            pass
    try:
        import sqlite3 as _sq
        db_name = req.user_id.replace("@", "").replace(".", "")
        word = max([w for w in (req.query_text or "").split() if len(w) > 3], key=len, default="")
        if word:
            conn = _sq.connect(f"/data/skv/metadata_store/{db_name}.db")
            rows = conn.execute("SELECT topic, summary_text, created_at FROM summary_l1 WHERE summary_text LIKE ? ORDER BY created_at ASC LIMIT 8", ("%" + word + "%",)).fetchall()
            conn.close()
            if rows:
                lines = ["=== PAST SUMMARIES ==="]
                for topic, summary, created in rows:
                    lines.append(f"[{created}] {topic}: {summary}")
                memory_map_text = "\n".join(lines) + "\n\n" + memory_map_text
    except Exception:
        pass
    try:
        if _sem_vec is not None:
            import sqlite3 as _sq
            hits = [h for h in _sem.search_l1(req.user_id, _sem_vec, k=3) if h[1] >= 0.45]
            if hits:
                conn = _sq.connect("/data/skv/metadata_store/" + _sem.account_name(req.user_id) + ".db")
                lines = ["=== RELATED SUMMARIES (semantic) ==="]
                for hid, sc in hits:
                    row = conn.execute("SELECT topic, summary_text, created_at FROM summary_l1 WHERE rowid=?", (int(hid.split(":")[1]),)).fetchone()
                    if row and (row[1] or "") not in memory_map_text:
                        lines.append(f"[{row[2]}] {row[0]}: {row[1]}")
                conn.close()
                if len(lines) > 1:
                    memory_map_text = "\n".join(lines) + "\n\n" + memory_map_text
    except Exception as _e:
        print(f"[semantic] l1 skipped: {_e}", flush=True)
    if getattr(req, "kind", None) or getattr(req, "source", None) or getattr(req, "project", None):
        try:
            from app import shelves as _sh
            _ok = _sh.allowed(req.user_id, [f.get("event_id") for f in fts_top] + [v.get("event_id") for v in vector_top], req.kind, req.source, req.project)
            fts_top = [f for f in fts_top if f.get("event_id") in _ok]
            vector_top = [v for v in vector_top if v.get("event_id") in _ok]
            intersection = [v for v in intersection if v.get("event_id") in _ok]
        except Exception as _e:
            print(f"[shelves] filter skipped: {_e}", flush=True)
    if _sem_vec is not None and len(fts_top) > 1:
        try:
            _order, _sup = _sem.supersede(req.user_id, [f.get("event_id") for f in fts_top])
            _by_id = {f.get("event_id"): f for f in fts_top}
            fts_top = [_by_id[i] for i in _order if i in _by_id]
            for _old, _new in _sup.items():
                if _old in _by_id:
                    _by_id[_old]["superseded_by"] = _new
        except Exception as _e:
            print(f"[semantic] fts supersede skipped: {_e}", flush=True)
    best_vec = vector_top[0] if vector_top else {}
    if best_vec: best_vec['full_text'] = _full_text(best_vec.get('event_id', ''))
    best_fts = fts_top[0] if fts_top else {}
    if best_fts: best_fts['full_text'] = _full_text(best_fts.get('event_id', ''))
    best_int = intersection[0] if intersection else {}
    if best_int: best_int['full_text'] = _full_text(best_int.get('event_id', ''))
    exact = best_int or best_fts
    if not phrases and not fts_top:
        no_exact = True
        exact = {}
    words = [w.strip("?.!,") for w in (req.query_text or "").lower().split() if len(w) > 4]
    key = max(words, key=len).replace("-", "") if words else ""
    def _has(eid):
        return key and key in (_full_text(eid) or "").lower().replace("-", "").replace(" ", "")
    if exact and exact.get("event_id") and not _has(exact.get("event_id")):
        no_exact = True
        exact = {}
    if key and not (exact and exact.get("event_id")):
        for item in (fts_top[:8] + vector_top[:8]):
            if _has(item.get("event_id")):
                exact = item
                no_exact = False
                break
    if exact and exact.get('event_id'):
        prompt_text = "=== EXACT MATCH ===\nID: " + exact.get('event_id') + "\n" + _full_text(exact.get('event_id')) + "\n\n" + prompt_text
        memory_text = "=== EXACT MATCH ===\nID: " + exact.get('event_id') + "\n" + _full_text(exact.get('event_id')) + "\n\n" + memory_text
    fragments = []
    side = vector_top[:5] if no_exact else []
    for item in ([exact] if exact and exact.get('event_id') else []) + fts_top[:5] + vector_top[:5]:
        eid = item.get('event_id')
        if not eid or any(f.get('event_id') == eid for f in fragments):
            continue
        fragments.append({"event_id": eid, "source": item.get('source', 'exact'), "score": item.get('score'), "text": _full_text(eid)})
    def _stamp(f):
        eid = f.get("event_id") or ""
        tail = eid.rsplit("_", 1)[-1]
        return int(tail) if "remember_" in eid and tail.isdigit() else 0
    phrases = [f for f in fragments if f.get("source") == "phrase"]
    phrases.sort(key=_stamp, reverse=True)
    rest = [f for f in fragments if f.get("source") != "phrase"]
    fragments = phrases + rest
    latest = fragments[:1]
    previous = [{"event_id": f.get("event_id"), "source": f.get("source"), "open": "/api/v7/event/" + f.get("event_id", ""), "preview": (f.get("text") or "")[:160]} for f in fragments[1:6]]
    if no_exact:
        previous = [{"event_id": f.get("event_id"), "source": "nearby", "note": "no exact match", "open": "/api/v7/event/" + f.get("event_id", ""), "preview": (f.get("text") or "")[:160]} for f in fragments[:5]]
        fragments = []
    else:
        fragments = latest
    fragment_links = []
    try:
        import sqlite3 as _sq
        if fragments:
            _db = "/data/skv/metadata_store/" + "".join(c for c in req.user_id if c.isalnum() or c in "_-") + ".db"
            _c = _sq.connect(_db)
            fragment_links = [{"src": r[0], "dst": r[1], "kind": r[2], "open": "/api/v7/event/" + r[1]} for r in _c.execute("SELECT src, dst, kind FROM event_links WHERE src=? OR dst=? LIMIT 6", (fragments[0]["event_id"], fragments[0]["event_id"]))]
            _c.close()
    except Exception:
        fragment_links = []
    
    shared_cubes = []
    try:
        import sqlite3 as _sq
        words = [w for w in (getattr(req, "query_text", "") or "").split() if len(w) >= 3][:4]
        if words:
            _c = _sq.connect("/data/skv/metadata_store/shared_master.db")
            _cur = _c.cursor()
            topic = None
            stems = []
            for word in words:
                stems.append(word)
                for end in ("ed", "ing", "es", "s"):
                    if word.endswith(end) and len(word) - len(end) >= 3:
                        stems.append(word[:-len(end)])
            for word in sorted(set(stems), key=len, reverse=True):
                hit = _cur.execute("SELECT subject_action_object FROM cubes_new WHERE (subject_action_object=? OR subject_action_object LIKE ?) AND cube_id NOT LIKE 'cube_const_%' LIMIT 1", (word, "%" + word + "%")).fetchone()
                if hit:
                    topic = hit[0]
                    break
            if hit:
                topic = hit[0]
            cover = None
            if topic:
                cover = _cur.execute("SELECT cube_id, essence, rules_markdown FROM cubes_new WHERE subject_action_object=? AND essence LIKE 'Culture%' AND status != 'deprecated' ORDER BY created_at DESC LIMIT 1", (topic,)).fetchone()
                if cover:
                    shared_cubes.append({"cube_id": cover[0], "topic": topic, "essence": cover[1], "rules": (cover[2] or "")[:500], "shared": True, "note": "culture", "kind": "culture"})
                    _cur.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
                seen=set()
                for row in _cur.execute("SELECT cube_id, essence, rules_markdown FROM cubes_new WHERE subject_action_object=? AND status != 'deprecated' AND essence NOT LIKE 'Culture%' AND cube_id NOT LIKE 'cube_const_%' ORDER BY rating DESC, upvotes DESC LIMIT 3", (topic,)):
                    seen.add(row[0])
                    shared_cubes.append({"cube_id": row[0], "topic": topic, "essence": row[1], "rules": (row[2] or "")[:500], "shared": True, "note": "good", "kind": "moment", "cover": cover[0] if cover else None})
                    if cover:
                        _cur.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (row[0], cover[0], "cover", "search"))
                for row in _cur.execute("SELECT cube_id, essence, rules_markdown FROM cubes_new WHERE subject_action_object=? AND status != 'deprecated' AND essence NOT LIKE 'Culture%' AND cube_id NOT LIKE 'cube_const_%' ORDER BY created_at DESC LIMIT 4", (topic,)):
                    if row[0] in seen:
                        continue
                    seen.add(row[0])
                    shared_cubes.append({"cube_id": row[0], "topic": topic, "essence": row[1], "rules": (row[2] or "")[:500], "shared": True, "note": "new, rate this", "kind": "moment", "cover": cover[0] if cover else None})
                    if len(seen) >= 5:
                        break
            if not shared_cubes and _sem_vec is not None:
                for cid, sc in _sem.search_cubes(_sem_vec, k=3):
                    if sc < 0.5:
                        continue
                    row = _cur.execute("SELECT cube_id, essence, subject_action_object, rules_markdown FROM cubes_new WHERE cube_id=? AND status != 'deprecated'", (cid,)).fetchone()
                    if row:
                        shared_cubes.append({"cube_id": row[0], "topic": row[2], "essence": row[1], "rules": (row[3] or "")[:500], "shared": True, "note": "semantic", "score": round(sc, 3)})
            if not shared_cubes:
                for row in _cur.execute("SELECT cube_id, essence, subject_action_object, rules_markdown FROM cubes_new WHERE status != 'deprecated' AND cube_id NOT LIKE 'cube_const_%' AND (subject_action_object LIKE ? OR essence LIKE ?) LIMIT 3", (like, like)):
                    shared_cubes.append({"cube_id": row[0], "topic": row[2], "essence": row[1], "rules": (row[3] or "")[:500], "shared": True, "note": "matched"})
            _c.commit()
            _c.close()
    except Exception:
        shared_cubes = []
    open_tasks = []
    try:
        _tc = _sq.connect("/data/skv/metadata_store/shared_master.db")
        _tc.execute("CREATE TABLE IF NOT EXISTS cube_tasks (task_id TEXT PRIMARY KEY, topic TEXT, question TEXT, tried TEXT, accept TEXT, status TEXT, created_by TEXT, created_at TEXT)")
        word = ""
        words = [w for w in (getattr(req, "query_text", "") or "").split() if len(w) > 3]
        if words:
            word = max(words, key=len)
        for row in _tc.execute("SELECT task_id, topic, question, tried, accept FROM cube_tasks WHERE status='open' AND (topic LIKE ? OR question LIKE ?) LIMIT 1", ("%"+word+"%", "%"+word+"%")):
            open_tasks.append({"task_id": row[0], "topic": row[1], "question": row[2], "tried": row[3], "accept": row[4], "note": "open task, answer or leave a hypothesis"})
        _tc.close()
    except Exception:
        open_tasks = []
    due = []
    try:
        import datetime, re
        months = {"января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,"июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12}
        today = datetime.date.today()
        name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        dc = _sq.connect(f"/data/skv/metadata_store/{name}.db")
        dc.execute("CREATE TABLE IF NOT EXISTS due_cache (day TEXT PRIMARY KEY, payload TEXT)")
        cached = dc.execute("SELECT payload FROM due_cache WHERE day=?", (today.isoformat(),)).fetchone()
        if cached:
            due = __import__("json").loads(cached[0])
            dc.close()
            raise StopIteration
        rows = dc.execute("SELECT event_id, raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE ? LIMIT 200", ("%>>>%",)).fetchall()
        for eid, text in rows:
            found = None
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text or "")
            if m:
                found = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                m = re.search(r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)", text or "", re.I)
                if m:
                    found = datetime.date(today.year, months[m.group(2).lower()], int(m.group(1)))
            if not found:
                continue
            delta = (found - today).days
            if delta < 0 and found.month == today.month:
                found = found.replace(year=today.year+1)
                delta = (found - today).days
            if 0 <= delta <= 7:
                due.append({"event_id": eid, "in_days": delta, "note": "через "+str(delta)+" дней" if delta else "сегодня"})
        dc.execute("INSERT OR REPLACE INTO due_cache (day, payload) VALUES (?,?)", (today.isoformat(), __import__("json").dumps(due, ensure_ascii=False)))
        dc.commit()
        dc.close()
    except StopIteration:
        pass
    except Exception:
        due = []
    agent_hint = "Center is fragments. If empty, do not invent: open previous.event_id or search again with a narrower name. Full text is GET /api/v7/event/{id}. Third look is POST /api/v7/memory/dig with query."
    span = 0
    try:
        import sqlite3 as _span
        name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        key = "".join(ch for ch in (req.query_text or "").lower() if ch.isalnum())
        if len(key) > 4:
            span = sum(1 for body in _cached_scan(name, "norm") if key in body)
    except Exception:
        span = 0
    lens = {"windows": []}
    try:
        import sqlite3 as _lens
        name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
        conn = _lens.connect(f"/data/skv/metadata_store/{name}.db")
        raw_q = (req.query_text or "").lower()
        words = []
        for w in raw_q.replace("-", "").split():
            token = "".join(ch for ch in w if ch.isalnum())
            if len(token) >= 4 and token not in words:
                words.append(token)
        words = sorted(words, key=len, reverse=True)[:3]
        rows_c = _cached_scan(name, "grokexp")
        crits_c = _cached_scan(name, "crit")
        l2 = ""
        try:
            l2 = conn.execute("select map_json from summary_l2 order by last_updated desc limit 1").fetchone()[0] or ""
        except Exception:
            l2 = ""
        for word in words:
            hit = None
            for eid, raw, body in rows_c:
                if word and word in body:
                    hit = (eid, raw)
                    break
            if not hit:
                continue
            eid, raw = hit
            tail = (eid or "").rsplit("_", 1)[-1]
            around = []
            if tail.isdigit():
                n = int(tail)
                l1_range = conn.execute("select start_n, end_n from l1_span where ? between start_n and end_n", (n,)).fetchone()
                if l1_range:
                    near = conn.execute("select session_id, start_n, end_n, summary from l1_span order by start_n").fetchall()
                    before = [r for r in near if r[2] < l1_range[0]][-1:]
                    after = [r for r in near if r[1] > l1_range[1]][:1]
                    around = [{"l1": sid, "from": a, "to": b, "text": (summary or "")[:400]} for sid, a, b, summary in before+after]
            theme = l2[:400]
            if word and word in l2.lower().replace("-", "").replace(" ", ""):
                theme = l2[:800]
            important = []
            for cid, text, body in crits_c:
                if word and word in body:
                    important.append({"event_id": cid, "text": text[:200]})
            if lens["windows"] and word in lens["windows"][0]["word"]:
                continue
            before = around[:1]
            after = around[1:2]
            lens["windows"].append({"word": word, "center": {"event_id": eid, "text": (raw or "")[:800]}, "around": around, "l1_before": before, "l1_after": after, "map": theme, "important": important[:2]})
        conn.close()
    except Exception:
        pass
    _legacy = {"prompt_text": prompt_text, "memory": memory_text, "fragments": fragments, "previous": previous, "agent_hint": agent_hint, "span": span, "lens": lens, "links": fragment_links, "shared_cubes": shared_cubes, "open_tasks": open_tasks, "due": due, "constitution": constitution_text, "reminders": reminders, "duty_error": duty_error, "has_cubes": has_cubes, "step": step, "memory_map": memory_map_text, "vector_top10": vector_top[:10], "fts_top10": fts_top[:10], "intersection": intersection[:10], "best_vector": best_vec, "best_fts": best_fts, "best_intersection": best_int}
    if _view != "agent":
        return _mv2.mask_obj(_legacy)
    _ctx = {"step": step, "duty_error": duty_error, "fts_top": fts_top, "vector_top": vector_top, "raw_results": raw_results,
            "full_map": lambda: build_memory_map(req.user_id, step=0)}
    try:
        from app import memory_v2_windows as _mvw
        _ctx["first_pack"] = lambda b: _mvw.first_pack(req.user_id, b)
    except ImportError:
        pass
    try:
        from app import memory_v2_lens as _mvl
        if (req.query_text or req.focus_event_id) and _mv2.config().get("lens_v2", True):
            _ctx["lens_fn"] = lambda _b: _mvl.lens(req.user_id, req.query_text or "", raw_results=raw_results, budget=_b,
                                                   focus_event_id=req.focus_event_id, radius=req.radius, offset=req.lens_offset,
                                                   kind=req.kind, source=req.source, project=req.project)
    except ImportError:
        pass
    return _mv2.agent_view(req, _legacy, _ctx)

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
        
        constitution_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v8"]
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
        lens_text = ""
        try:
            keyrow = (_ak.internal_token(req.user_id),)
            if keyrow:
                lens_req = urlreq.Request("http://127.0.0.1:8000/api/v7/memory", data=json.dumps({"user_id": req.user_id, "query_text": req.message, "top_k": 2}).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer "+keyrow[0]})
                with urlreq.urlopen(lens_req, timeout=40) as lens_resp:
                    lens = json.loads(lens_resp.read().decode())
                bits = ["span="+str(lens.get("span"))]
                for w in (lens.get("lens") or {}).get("windows") or []:
                    bits.append(w.get("word","")+" center "+((w.get("center") or {}).get("event_id") or ""))
                    bits.append(((w.get("center") or {}).get("text") or "")[:600])
                lens_text = "\n".join(bits)
        except Exception:
            lens_text = ""

        opened = ""
        try:
            center = ""
            for line in lens_text.split("\n"):
                if "center " in line:
                    center = line.split("center ", 1)[1].strip()
                    break
            if center:
                keyrow = (_ak.internal_token(req.user_id),)
                headers = {"Authorization": "Bearer "+keyrow[0]} if keyrow else {}
                with urlreq.urlopen(urlreq.Request("http://127.0.0.1:8000/api/v7/event/"+center, headers=headers), timeout=20) as ev:
                    opened = ev.read().decode()[:1200]
        except Exception:
            opened = ""

        prompt = f"{guest_warning}{search_instruction}{lens_text}\n\nOPENED EVENT:\n{opened}\n\n{memory_text if memory_text else 'No relevant memory found.'}\n\nUser question: {req.message}\n\nFormat: TOOL: memory query=... or TOOL: event event_id=... or === ЗАКЛЮЧЕНИЕ ===. Do not conclude before one TOOL if the archive is wide."
        tools = [
            {"type": "function", "function": {"name": "memory", "description": "Search the user archive", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "dig", "description": "Scan the archive for a rare word", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "event", "description": "Open one event by id", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}}},
            {"type": "function", "function": {"name": "sandbox", "description": "Run a short Python check", "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
        ]
        polza_body = json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt + " You may call memory, dig, event, or sandbox before answering."}], "tools": tools, "temperature": 0.3, "max_tokens": 1400}).encode()
        polza_key = os.environ.get("POLZA_KEY", "")
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=polza_body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
        with urlreq.urlopen(r, timeout=120) as resp:
            response_data = json.loads(resp.read().decode())
            message = response_data["choices"][0]["message"]
            
            # Handle tool calls
            tool_results = []
            if "tool_calls" in message:
                for tc in message["tool_calls"]:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    if name in ("memory", "dig", "event", "sandbox"):
                        try:
                            if name == "memory":
                                url, payload = "http://127.0.0.1:8000/api/v7/memory", {"user_id": req.user_id, "query_text": args.get("query", ""), "top_k": 2}
                            elif name == "dig":
                                url, payload = "http://127.0.0.1:8000/api/v7/memory/dig", {"user_id": req.user_id, "query": args.get("query", "")}
                            elif name == "event":
                                url, payload = "http://127.0.0.1:8000/api/v7/event/" + args.get("event_id", ""), None
                            else:
                                url, payload = "http://127.0.0.1:8000/api/execute/code", {"code": args.get("code", ""), "user_id": req.user_id}
                            headers = {"Content-Type": "application/json"}
                            if name != "sandbox":
                                keyrow = (_ak.internal_token(req.user_id),)
                                if keyrow:
                                    headers["Authorization"] = "Bearer " + keyrow[0]
                            call = urlreq.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
                            with urlreq.urlopen(call, timeout=40) as tool_resp:
                                tool_results.append({"tool": name, "result": tool_resp.read().decode()[:1500]})
                        except Exception as e:
                            tool_results.append({"tool": name, "error": str(e)})
                    if tc["function"]["name"] == "createFile":
                        try:
                            args = json.loads(tc["function"]["arguments"])
                            # Call our own API
                            create_req = urlreq.Request("http://127.0.0.1:8000/api/v7/tools/create-file",
                                data=json.dumps(args).encode(),
                                headers={"Content-Type": "application/json"})
                            with urlreq.urlopen(create_req, timeout=10) as create_resp:
                                file_result = json.loads(create_resp.read().decode())
                                tool_results.append({"tool": "createFile", "result": file_result})
                        except Exception as e:
                            tool_results.append({"tool": "createFile", "error": str(e)})
                
                # Send tool results back to AI
                if tool_results:
                    tool_msg = json.dumps(tool_results)
                    followup_body = json.dumps({
                        "model": "deepseek/deepseek-chat",
                        "messages": [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "tool_calls": message["tool_calls"]},
                            {"role": "tool", "content": tool_msg}
                        ],
                        "temperature": 0.3
                    }).encode()
                    followup_req = urlreq.Request("https://api.polza.ai/v1/chat/completions",
                        data=followup_body,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                    with urlreq.urlopen(followup_req, timeout=30) as followup_resp:
                        answer = json.loads(followup_resp.read().decode())["choices"][0]["message"]["content"]
                else:
                    answer = message.get("content", "")
            else:
                answer = message.get("content", "")
        for _step in range(3):
            m = re.search(r"TOOL:\s*(\w+)\s+(\w+)=(.+)", answer or "")
            if "=== ЗАКЛЮЧЕНИЕ ===" in (answer or ""):
                break
            if not m:
                follow = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}, {"role": "user", "content": "Нет. Напиши TOOL: memory query=Т-пары или === ЗАКЛЮЧЕНИЕ ===. Не отвечай пользователю."}], "temperature": 0.2, "max_tokens": 400}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                with urlreq.urlopen(follow, timeout=60) as follow_resp:
                    answer = json.loads(follow_resp.read().decode())["choices"][0]["message"]["content"]
                continue
            name, arg, val = m.group(1), m.group(2), m.group(3).strip()
            result = ""
            try:
                keyrow = (_ak.internal_token(req.user_id),)
                headers = {"Content-Type": "application/json"}
                if keyrow:
                    headers["Authorization"] = "Bearer " + keyrow[0]
                if name == "memory":
                    call = urlreq.Request("http://127.0.0.1:8000/api/v7/memory", data=json.dumps({"user_id": req.user_id, "query_text": val, "top_k": 2}).encode(), headers=headers)
                elif name == "dig":
                    call = urlreq.Request("http://127.0.0.1:8000/api/v7/memory/dig", data=json.dumps({"user_id": req.user_id, "query": val}).encode(), headers=headers)
                elif name == "event":
                    call = urlreq.Request("http://127.0.0.1:8000/api/v7/event/" + val, headers=headers)
                else:
                    result = "unknown tool"
                    call = None
                if call:
                    with urlreq.urlopen(call, timeout=40) as tool_resp:
                        result = tool_resp.read().decode()[:1200]
            except Exception as e:
                result = str(e)
            follow = urlreq.Request("https://api.polza.ai/v1/chat/completions", data=json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}, {"role": "user", "content": "Результат:\n" + result + "\nTOOL or === ЗАКЛЮЧЕНИЕ ==="}], "temperature": 0.3, "max_tokens": 1400}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
            with urlreq.urlopen(follow, timeout=90) as follow_resp:
                answer = json.loads(follow_resp.read().decode())["choices"][0]["message"]["content"]
        # Remove SEAL from user-facing response
        answer = re.sub(r"🔐.*$", "", answer, flags=re.DOTALL).strip()
        center = ""
        for line in (lens_text or "").split("\n"):
            if "center " in line:
                center = line.split("center ", 1)[1].strip()
                break
        if center and center not in (answer or ""):
            quote = " ".join((opened or "").split())[:220]
            answer = (answer or "").strip() + "\n\nИсточник: " + center + ("\n" + quote if quote else "")
        
        if not is_guest:
            safe_event_id = f"{req.user_id}::chat_{req.session_id}_{int(time.time())}"
            now = datetime.now(timezone.utc)
            session_emb = get_embedding_cached(req.message + " " + answer)
            session_list = session_emb if isinstance(session_emb, list) else session_emb.tolist()
            session_vec = session_list[:218]
            buffer.write_personal_event(event_id=safe_event_id, hour=now.hour, minute=now.minute, semantics_emb=np.array(session_vec, dtype=np.float32), parent_indices=None, details_emb=None, metric_value=len(answer)/1000.0)
            metadata_store.write_metadata(user_id=req.user_id, event_id=safe_event_id, time_str=f"{now.hour:02d}:{now.minute:02d}, {now.strftime('%d.%m.%Y')}", essence=req.message[:200], messages_count=2, topics=["chat_history"], links=[], metric_value=len(answer)/1000.0, raw_dialogue=f"Q: {req.message}\nA: {answer}", is_shared=False)
            pass  # buffer.persistence removed
        
        return {"response": answer, "session_id": req.session_id, "step": req.step + 1, "is_guest": is_guest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class VoteRequest(BaseModel):
    cube_id: str
    user_id: str
    vote: int  # +1 or -1
    topic: str = ""


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
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO event_metadata (event_id, time_str, essence, raw_dialogue, status, messages_count, links_json, topics_json, subject, action, object, metric_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"{req.user_id}::{req.session_id}", datetime.now().strftime("%Y-%m-%d %H:%M"), req.topic or req.query[:100],
                    f"Q: {req.query}\nA: {req.response}", "active", 1, "[]", "[]", "", "", "", 0))
        conn.commit()
        conn.close()
        try:
            from app.account_memory import queue_turn
            queue_turn("/data/skv/metadata_store", req.user_id, f"{req.user_id}::{req.session_id}", req.query, req.response, source="agent", topic=req.topic or "")
        except Exception as exc:
            print(f"[memory] agent queue skipped: {exc}", flush=True)
        return {"status": "ok", "event_id": f"{req.user_id}::{req.session_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/summarize", status_code=status.HTTP_201_CREATED)
async def store_summary(req: SummarizeRequest):
    try:
        import sqlite3
        db_name = req.user_id.replace("@", "").replace(".", "")
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
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
        conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
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
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        def _words(s):
            return set((s or "").lower().replace(".", " ").split())
        new_w = _words(req.topic) | _words(req.essence) | _words(req.rules_markdown)
        for cid, ess, rules in cur.execute("select cube_id, essence, rules_markdown from cubes_new where subject_action_object=?", (req.topic,)):
            old_w = _words(req.topic) | _words(ess) | _words(rules)
            if not new_w or not old_w:
                continue
            if len(new_w & old_w) / len(new_w | old_w) >= 0.55:
                conn.close()
                return {"status": "already", "cube_id": cid}
        cube_id = req.cube_id or f"cube_{uuid.uuid4().hex[:12]}"
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
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
    cur = conn.cursor()
    if req.batch_logs:
        text = "\n".join([f"Q: {log.get('q','')}\nA: {log.get('a','')}" for log in req.batch_logs])
        cur.execute("INSERT OR REPLACE INTO event_metadata (event_id, time_str, essence, raw_dialogue, status, messages_count, links_json, topics_json, subject, action, object, metric_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"{req.user_id}::{req.session_id}", req.query or "batch", text, "active", len(req.batch_logs)))
        conn.commit()
    conn.close()
    return {"status": "batch_accepted", "logs_saved": len(req.batch_logs)}

def _default_view():
    try:
        from app import memory_v2 as _mv2
        return _mv2.config().get("default_view", "legacy") if _mv2.enabled() else "legacy"
    except Exception:
        return "legacy"


@router.get("/agent/memory")
async def agent_get_memory(query: str, key: str = "", user_id: str = "", top_k: int = 5, authorization: str = Header(None),
                           view: str = "", session_id: str = "", start: bool = False, probe: bool = False,
                           interact: bool = False, format: str = "", focus_event_id: str = ""):
    """Read fallback for weak agents. Key in the query, same result as POST."""
    if not user_id and key:
        user_id = _user_from_key(key)
    if not user_id:
        raise HTTPException(401, "key or user_id required")
    body = MemoryRequest(user_id=user_id, query_text=query, top_k=max(1, min(top_k, 10)), view=view or None,
                         session_id=session_id or None, start=start, probe=probe, interact=interact,
                         format=format or ("text" if (view or _default_view()) == "agent" else None), focus_event_id=focus_event_id or None)
    return await guardian_l1_memory(body, get_memory_buffer(), authorization)

@router.get("/memory/start")
async def memory_start(user_id: str = "", session_id: str = "", query: str = "", format: str = "text",
                       interact: bool = False, authorization: str = Header(None)):
    """First-request pack (memory map + raw/L1/L2 windows + compact constitution) for any agent that can GET."""
    from app import memory_v2 as _mv2
    if not _mv2.enabled():
        raise HTTPException(404, "memory v2 disabled")
    if not user_id:
        raise HTTPException(401, "API key required")
    body = MemoryRequest(user_id=user_id, query_text=query or None, view="agent", session_id=session_id or None,
                         start=True, interact=interact, format=format or "text")
    return await guardian_l1_memory(body, get_memory_buffer(), authorization)


class MemorySettingsRequest(BaseModel):
    user_id: str = ""
    budgets: Dict[str, int] = {}


@router.get("/memory/settings")
async def memory_settings_get(user_id: str = ""):
    from app import memory_v2 as _mv2
    if not user_id:
        raise HTTPException(401, "API key required")
    cfg = _mv2.config()
    return {"budgets": _mv2.resolve_budgets(user_id, {}), "user": _mv2.user_settings(user_id),
            "defaults": cfg["budgets"], "caps": cfg["caps"]}


@router.post("/memory/settings")
async def memory_settings_set(req: MemorySettingsRequest):
    """Per-user default budgets (tokens). The server cap still applies."""
    from app import memory_v2 as _mv2
    if not req.user_id:
        raise HTTPException(401, "API key required")
    return {"status": "ok", "budgets": _mv2.save_user_budgets(req.user_id, req.budgets)}


class MemoryLensRequest(BaseModel):
    user_id: str = ""
    query_text: str = ""
    query: str = ""
    focus_event_id: Optional[str] = None
    radius: int = Field(2, ge=0, le=6)
    offset: int = Field(0, ge=0, le=200)
    budget_lens: Optional[int] = None
    kind: Optional[str] = None
    source: Optional[str] = None
    project: Optional[str] = None


@router.post("/memory/lens")
async def memory_lens(req: MemoryLensRequest):
    """Light follow-up: episodes for a query, or expand one episode with focus_event_id. No step bump."""
    from app import memory_v2 as _mv2
    from app import memory_v2_lens as _mvl
    if not req.user_id:
        raise HTTPException(401, "API key required")
    q = req.query_text or req.query
    if not q and not req.focus_event_id:
        raise HTTPException(422, "query_text or focus_event_id required")
    b = _mv2.resolve_budgets(req.user_id, {"lens": req.budget_lens})["lens"]
    out = _mvl.lens(req.user_id, q, budget=b, focus_event_id=req.focus_event_id, radius=req.radius, offset=req.offset,
                    kind=req.kind, source=req.source, project=req.project)
    out["budget"] = {"lens": b}
    return _mv2.mask_obj(out)


class MemoryProfileRequest(BaseModel):
    user_id: str = ""
    who: Optional[str] = None
    projects: Optional[List[Any]] = None
    prefs: Optional[Dict[str, Any]] = None


@router.get("/memory/profile")
async def memory_profile_get(user_id: str = ""):
    from app import memory_v2_windows as _mvw
    if not user_id:
        raise HTTPException(401, "API key required")
    return _mvw.get_profile(user_id)


@router.post("/memory/profile")
async def memory_profile_set(req: MemoryProfileRequest):
    """Merge into the user profile used by the memory map (who, projects, prefs). Nothing is deleted."""
    from app import memory_v2_windows as _mvw
    if not req.user_id:
        raise HTTPException(401, "API key required")
    return {"status": "ok", "profile": _mvw.merge_profile(req.user_id, who=req.who, projects=req.projects, prefs=req.prefs)}


@router.get("/memory/l2/blocks")
async def memory_l2_blocks(user_id: str = "", limit: int = 50):
    from app import memory_v2_windows as _mvw
    if not user_id:
        raise HTTPException(401, "API key required")
    return {"blocks": _mvw.list_l2_blocks(user_id, max(1, min(limit, 200)))}


@router.post("/experience/vote")
async def vote_experience(req: VoteRequest):
    """Vote for an experience cube. 3 downvotes → deprecated."""
    import sqlite3, json
    
    if req.vote not in (-1, 1):
        raise HTTPException(status_code=400, detail="Vote must be +1 or -1")
    
    conn = sqlite3.connect('/data/skv/metadata_store/shared_master.db')
    cur = conn.cursor()
    
    # Get current votes
    cur.execute("SELECT cube_id, rating, votes_json FROM cubes_new WHERE cube_id = ?", (req.cube_id,))
    cube = cur.fetchone()
    if not cube:
        conn.close()
        raise HTTPException(status_code=404, detail="Cube not found")
    row = (cube[2] or "[]", cube[1] or 0)
    
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
            "user_id": req.user_id,
            "vote": req.vote,
            "topic": req.topic,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        current_rating += req.vote
    
    # Determine status
    downvotes = sum(1 for v in votes if v['vote'] == -1)
    upvotes = sum(1 for v in votes if v['vote'] == 1)
    
    topics = {v.get("topic") for v in votes if v.get("topic")}
    if downvotes >= 3:
        status = "deprecated"
        cur.execute("CREATE TABLE IF NOT EXISTS court_queue (cube_id TEXT PRIMARY KEY, reason TEXT, created_at TEXT)")
        cur.execute("INSERT OR IGNORE INTO court_queue (cube_id, reason, created_at) VALUES (?,?,datetime('now'))", (req.cube_id, "three downvotes"))
    elif upvotes >= 3 and len(topics) >= 2:
        status = "golden"
    elif upvotes >= 3:
        status = "verified"
    else:
        status = "community"
    
    cur.execute('UPDATE event_metadata SET votes_json = ?, rating = ?, status = ? WHERE event_id = ?',
                (json.dumps(votes), current_rating, status, req.cube_id))
    cur.execute("UPDATE cubes_new SET upvotes=?, downvotes=?, rating=?, status=?, votes_json=? WHERE cube_id=?",
                (upvotes, downvotes, current_rating, status, json.dumps(votes), req.cube_id))
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



@router.get("/event/{event_id}")
async def get_event_detail(event_id: str):
    import json
    """Возвращает полный текст события по ID."""
    import sqlite3
    user_part = event_id.split("::")[0] if "::" in event_id else "test_user"
    db_name = user_part.replace("@", "").replace(".", "")
    
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=30)
    cur = conn.cursor()
    cur.execute("SELECT event_id, time_str, essence, raw_dialogue, links_json, messages_count FROM event_metadata WHERE event_id = ?", (event_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(404, "Event not found")
    
    from app import memory_v2 as _mv2
    return _mv2.mask_obj({
        "event_id": row[0],
        "time": row[1],
        "essence": row[2],
        "full_text": row[3],
        "links": json.loads(row[4]) if row[4] and row[4].strip() else [],
        "messages_count": row[5]
    })


@router.post("/memory/search/date")
async def search_by_date(data: dict):
    """Fuzzy search by date/time. Day→week, time→+-2h, month→month."""
    user_id = data.get("user_id", "")
    date_query = data.get("date", "")
    event_prefix = data.get("event_prefix", "")
    limit = data.get("limit", 20)
    
    if not user_id:
        return {"error": "user_id required"}
    
    db_name = user_id.replace("@", "").replace(".", "")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{db_name}.db", timeout=10)
    cur = conn.cursor()
    
    query = "SELECT event_id, time_str, essence, substr(raw_dialogue,1,300) FROM event_metadata WHERE 1=1"
    params = []
    
    if date_query:
        if len(date_query) == 16:  # YYYY-MM-DD HH:MM → +-2h
            query += " AND time_str >= ? AND time_str <= ?"
            params.append(date_query)
            try:
                dt = datetime.strptime(date_query, "%Y-%m-%d %H:%M")
                params.append((dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"))
            except:
                params.append(date_query + ":99")
        elif len(date_query) == 10:  # YYYY-MM-DD → +-7 days
            query += " AND time_str >= ? AND time_str <= ?"
            params.append(date_query)
            try:
                dt = datetime.strptime(date_query, "%Y-%m-%d")
                params.append((dt + timedelta(days=7)).strftime("%Y-%m-%d"))
            except:
                params.append(date_query + "z")
        elif len(date_query) == 7:  # YYYY-MM → whole month
            query += " AND time_str LIKE ?"
            params.append(f"{date_query}%")
        else:
            query += " AND time_str LIKE ?"
            params.append(f"%{date_query}%")
    
    if event_prefix:
        query += " AND event_id LIKE ?"
        params.append(f"%{event_prefix}%")
    
    query += " ORDER BY event_id DESC LIMIT ?"
    params.append(limit)
    
    cur.execute(query, params)
    results = [{"event_id": eid, "time": ts, "essence": essence, "preview": raw[:200]} 
               for eid, ts, essence, raw in cur.fetchall()]
    conn.close()
    return {"results": results, "count": len(results)}


@router.post("/agent/shell")
async def agent_shell(data: dict, authorization: str = Header(None), x_api_key: str = Header(None)):
    """Execute shell command. Owner account only (env SKV_SHELL_OWNERS, comma-separated user ids)."""
    cmd = data.get("cmd", "")
    token = (data.get("token") or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token and x_api_key:
        token = x_api_key.strip()
    if not token:
        raise HTTPException(401, "Token required")

    # Verify token
    import sqlite3 as _sq
    conn = _sq.connect("/data/skv/metadata_store/shared_master.db", timeout=5)
    cur = conn.cursor()
    cur.execute(_ak.SQL_USER, _ak.args(token))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Invalid token")
    owners = {u.strip().lower() for u in os.environ.get("SKV_SHELL_OWNERS", "denizchavdarov@gmail.com").split(",") if u.strip()}
    if str(row[0]).strip().lower() not in owners:
        raise HTTPException(403, "Shell is restricted to the owner account")
    
    if not cmd:
        return {"error": "cmd required"}
    
    # Restricted commands
    dangerous = ['rm -rf', 'mkfs', 'dd if=', ':(){', 'chmod 777', '> /dev/sda']
    for d in dangerous:
        if d in cmd:
            return {"error": f"Dangerous command blocked: {d}"}
    
    import subprocess
    try:
        _cwd = os.environ.get("SKV_SHELL_CWD", "/app")
        if not os.path.isdir(_cwd):
            _cwd = None
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=_cwd)
        return {
            "stdout": (result.stdout or "")[:5000],
            "stderr": (result.stderr or "")[:1000],
            "returncode": result.returncode
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/constitution")
async def get_constitution_v8():
    """Возвращает кубы конституции CUBE 00-05"""
    import sqlite3
    conn = sqlite3.connect('/data/skv/metadata_store/shared_master.db')
    cur = conn.cursor()
    cur.execute("""
        SELECT cube_id, essence, rules_markdown
        FROM cubes_new
        WHERE cube_id LIKE 'cube_const_%'
        ORDER BY cube_id
    """)
    cubes = []
    for eid, essence, raw in cur.fetchall():
        cube_num = eid.replace('cube_const_', '').split('_')[0]
        cubes.append({
            "id": eid,
            "cube": "CUBE " + cube_num.zfill(2),
            "essence": essence or "",
            "content": raw or "",
            "length": len(raw or "")
        })
    conn.close()
    return {
        "version": "v8.0 PRO",
        "cubes_count": len(cubes),
        "cubes": cubes,
        "total_chars": sum(c["length"] for c in cubes)
    }

# ==================== SKV CHAT v8.3 PRODUCTION ====================
# Архитектура:
# - DeepSeek: ответы пользователю + кубы/фидбэк (по команде)
# - Llama: L1 summary (каждые 15), L2 map (каждые 30)
# - Бэкенд: сохранение текста, счётчик, триггеры

@router.post("/agent/chat")
async def agent_chat(req: ChatRequest):  # Buffer not needed for chat
    try:
        import json, urllib.request as urlreq, time, re
        try:
            polza_key = os.environ.get("POLZA_KEY", "")
            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + polza_key}
            mem = await guardian_l1_memory(MemoryRequest(user_id=req.user_id, query_text=req.message, top_k=3, step=0, view="legacy"), get_memory_buffer(), None)
            cubes = mem.get("shared_cubes") or []
            lines = []
            for c in cubes[:5]:
                lines.append(str(c.get("note")) + ": " + str(c.get("essence")) + " | " + str(c.get("rules")))
            pack = "\n".join(lines) or "no cubes"
            memory_text = str(mem.get("prompt_text") or "")[:1800]
            import re as _re
            calc = ""
            m = _re.search(r"(\d+)\s*(?:times|x|\*|×)\s*(\d+)", req.message.lower())
            if m:
                from app.routers.execute_code import run_code
                ran = await run_code("print(%s*%s)" % (m.group(1), m.group(2)))
                calc = "CALC: " + str(ran.get("stdout") or "").strip()
            dug = await memory_dig(DigRequest(user_id=req.user_id, query=req.message))
            dig_text = str(dug)[:600]
            const = ""
            try:
                _c = __import__("sqlite3").connect("/data/skv/metadata_store/shared_master.db")
                parts = []
                for cid in ("cube_const_00_v5","cube_const_01_v4","cube_const_02_v4","cube_const_03_v4","cube_const_04_v4"):
                    row = _c.execute("select rules_markdown from cubes_new where cube_id=?", (cid,)).fetchone()
                    if row:
                        parts.append(row[0][:900])
                const = "\n\n".join(parts)
                _c.close()
            except Exception:
                const = ""
            hist = ""
            if req.chat_history:
                tail = req.chat_history[-8:]
                hist = "Earlier in this same chat. Use it. Do not ask again for what is already here:\n" + "\n".join(str(h)[:500] for h in tail) + "\n\n"
            prompt = (
                "CONSTITUTION. Follow it. You do the Second Look in your head, the server cannot.\n"
                "DRAFT the answer. VERIFY against CUBE 01 harm, 02 truth, 03 morality, 04 manipulation, and PACK.\n"
                "CORRECT the draft if it breaks a rule or ignores a cube. Then OUTPUT only the final answer.\n"
                "The person sees only the answer. Do not print MEMORY, LENS, SECOND LOOK, cube ids, or duty.\n"
                "A short seal at the end is enough: SKV | READ | VERIFY | CORRECT | OUTPUT\n\n"
                + const + "\n\nPACK:\n" + pack + "\n\nMEMORY:\n" + memory_text[:700] + "\n\n" + hist + calc + "\n\nQuestion: " + req.message
            )
            body = json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 800}).encode()
            final = json.loads(urlreq.urlopen(urlreq.Request("https://api.polza.ai/v1/chat/completions", data=body, headers=headers), timeout=60).read())["choices"][0]["message"]["content"].strip()
            seal = "SKV | probe | READ | VERIFY | " + str(len(cubes)) + " cubes"
            try:
                from app.account_memory import queue_turn
                queue_turn("/data/skv/metadata_store", req.user_id, req.user_id + "::chat_" + str(int(time.time())), req.message, final, source="chat")
            except Exception:
                pass
            return {"response": final + "\n\n" + seal, "session_id": req.session_id, "step": (req.step or 0) + 1, "is_guest": req.user_id.startswith("guest_"), "cubes": [c.get("cube_id") for c in cubes[:5]], "steps": 2}
        except Exception:
            pass
        import sqlite3 as _sq
        from datetime import datetime, timedelta
        from app.routers.v4_middleware import get_embedding_cached

        # Normalize chat history to strings
        if req.chat_history and isinstance(req.chat_history[0], dict):
            req.chat_history = [f"{h.get('role', '?')}: {h.get('content', '')}" for h in req.chat_history]
        
        # Find or create session for this user
        db_name = req.user_id.replace('@', '').replace('.', '')
        if req.session_id == 'default' or not req.session_id:
            # Auto-find last active session or create new
            try:
                sconn = _sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                scur = sconn.cursor()
                scur.execute("SELECT session_id FROM chat_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1", (req.user_id,))
                srow = scur.fetchone()
                if srow:
                    req.session_id = srow[0]
                else:
                    req.session_id = f"{req.user_id}_chat_{int(time.time())}"
                sconn.close()
            except:
                req.session_id = f"{req.user_id}_chat_{int(time.time())}"
        
        is_guest = req.user_id.startswith("guest_")
        guest_warning = "GUEST MODE: Register at skv.network for permanent memory.\n" if is_guest else ""
        user_status = f"User: {req.user_id} | Status: {'Guest (temporary)' if is_guest else 'Registered (memory active)'}\n"


        # ========== 1. ПОИСК ПАМЯТИ (FTS5 first, then HNSW) ==========
        emb = get_embedding_cached(req.message)
        emb_list = emb if isinstance(emb, list) else emb.tolist()
        q_vec = np.zeros(768, dtype=np.float32)
        q_vec[:min(len(emb_list), 768)] = emb_list[:768]
        
        hnsw_results = []  # Agent uses searchMemory tool
        if hnsw_results:
            event_ids = [eid for eid, _ in hnsw_results[:5]]
            metadata_map = metadata_store.batch_get_metadata(req.user_id, event_ids)
            memory_parts = []
            for eid, score in hnsw_results[:5]:
                meta = metadata_map.get(eid) or {}
                essence = meta.get('essence', '') if meta else ''
                # Топ-1: полный текст, остальные: essence + links
                links_data = meta.get('links_json', '')
                link_str = ""
                if links_data and links_data.strip() and links_data != '[]':
                    try:
                        links_parsed = json.loads(links_data) if isinstance(links_data, str) else links_data
                        if isinstance(links_parsed, dict):
                            link_str = " | 🔗 " + ", ".join(list(links_parsed.keys())[:3])
                    except:
                        pass
                
                if len(memory_parts) == 0:
                    raw = meta.get('raw_dialogue', essence) or ''
                    memory_parts.append(f"=== TOP MATCH (Score: {score:.2f}) ===\nID: {eid}{link_str}\n{str(raw)[:3000]}")
                else:
                    memory_parts.append(f"ID: {eid}{link_str} | Score: {score:.2f} | {str(essence)[:500]}")
            memory_text = "\n".join(memory_parts)
        else:
            memory_text = "No relevant memory."
        
        # FTS5 exact search FIRST (better for names, terms)
        fts_text = ""
        try:
            import sqlite3 as sq
            db_name = req.user_id.replace('@', '').replace('.', '')
            fts_conn = sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            fts_cur = fts_conn.cursor()
            words = [w for w in req.message.split() if len(w) > 3][:5]
            if words:
                fts_query = ' OR '.join(words)
                fts_cur.execute('SELECT event_id FROM events_fts WHERE events_fts MATCH ?', (fts_query,))
                fts_ids = {r[0] for r in fts_cur.fetchall()}
                if fts_ids:
                    fts_meta = metadata_store.batch_get_metadata(req.user_id, list(fts_ids)[:5])
                    fts_parts = ["=== 🎯 FTS5 EXACT MATCHES ==="]
                    for i, eid in enumerate(list(fts_ids)[:5]):
                        meta = fts_meta.get(eid, {})
                        if meta:
                            if i == 0:
                                raw = meta.get('raw_dialogue', meta.get('essence', ''))
                                fts_parts.append(f"TOP: {eid}\n{str(raw)[:3000]}")
                            else:
                                fts_parts.append(f"ID: {eid} | {str(meta.get('essence', ''))[:500]}")
                    fts_text = "\n".join(fts_parts) + "\n"
                fts_conn.close()
        except:
            pass
        
        # Prepend FTS5 results before HNSW
        if fts_text:
            memory_text = fts_text + "\n=== 🔍 HNSW SEMANTIC MATCHES ===\n" + memory_text

        # ========== 2. MEMORY MAP (single source: build_memory_map) ==========
        # step=0 → full Raw+L1+L2+Critical; step>0 → short L2+Critical+hint
        memory_map = build_memory_map(req.user_id, step=getattr(req, "step", 0) or 0)
        if not memory_map:
            memory_map = "Memory active. Use searchMemory tool | GET /api/v7/event/{id}"

        # ========== 3. ПОЛНАЯ КОНСТИТУЦИЯ ==========
        constitution_ids = ["cube_const_00_v5", "cube_const_01_v4", "cube_const_02_v4", 
                           "cube_const_03_v4", "cube_const_04_v4", "cube_const_05_v8"]
        const_map = metadata_store.batch_get_metadata("shared_master", constitution_ids)
        const_parts = []
        for cid in constitution_ids:
            meta = const_map.get(cid, {})
            if meta.get("raw_dialogue"):
                name = cid.replace("cube_const_", "CUBE ").replace("_v4","").replace("_v5","")
                const_parts.append(f"=== {name} ===\n{meta['raw_dialogue']}")
        constitution_text = "\n\n".join(const_parts)

        # ========== 4. НАПОМИНАНИЯ ==========
        reminders = "🔐 Execute Second Look and put SEAL.\n"
        # Cubes are auto-created by triggers (🎉, ✅, success patterns)
        # L1/L2 are auto-generated by backend (Llama every 15/60 min)

        # ========== 5. SEAL ==========
        seal_context = f"Previous SEAL: {req.last_seal}\nContinue numbering.\n" if req.last_seal else "Start SEAL with #1.\n"

        # ========== 6. ИСТОРИЯ ЧАТА (from server) ==========
        chat_history = ""
        try:
            sconn = _sq.connect(f'/data/skv/metadata_store/{db_name}.db')
            scur = sconn.cursor()
            scur.execute("SELECT messages_json FROM chat_sessions WHERE session_id=?", (req.session_id,))
            srow = scur.fetchone()
            
            if srow and srow[0]:
                msgs = json.loads(srow[0])
                # Check if history is large — refresh constitution
                total_chars = sum(len(m.get('content','')) for m in msgs)
                if total_chars > 400000:
                    msgs.append({"role":"system","content":f"=== CONSTITUTION ===\n{constitution_text[:5000]}\n\n=== MEMORY MAP ===\n{memory_map}"})
                    msgs = msgs[-60:]
                
                chat_history = "=== CHAT HISTORY ===\n" + "\n".join([f"{m['role']}: {m['content'][:300]}" for m in msgs[-50:]]) + "\n"
            else:
                # New session — start with constitution
                system_msg = {"role":"system","content":f"=== CONSTITUTION ===\n{constitution_text[:5000]}\n\n=== MEMORY MAP ===\n{memory_map}"}
                scur.execute("INSERT INTO chat_sessions (session_id, user_id, messages_json, updated_at) VALUES (?,?,?,datetime('now'))",
                           (req.session_id, req.user_id, json.dumps([system_msg])))
                sconn.commit()
                chat_history = f"=== SYSTEM ===\n{system_msg['content']}\n\n"
            
            sconn.close()
        except:
            pass

        # ========== 7. ЗАПРОС К DEEPSEEK ==========
        system_prompt = f"""{user_status}{guest_warning}🔴 KEY RULES — READ BEFORE RESPONDING:
• Backend saves the raw turn and writes L1/L2 with the cheap model. Do not spend the chat model on summaries.
• You still write shared cubes and duty=cube_nothing or duty=vote_nothing. Silence on a required step is an error on the next request.
• Before answering about SKV features → CHECK CUBE 05 in constitution
• NEVER say "I saved" or "I created summary" — backend does it
• NEVER invent SKV features that don"t exist

You are SKV Agent v8.3. Follow the constitution below.

=== MEMORY SEARCH RESULTS ===
{memory_text}

=== MEMORY MAP ===
{memory_map}

{chat_history}

=== CONSTITUTION ===
{constitution_text}

=== REMINDERS ===
{reminders}

{seal_context}

User: {req.message}

RESPONSE FORMAT (REQUIRED):
<thinking>
DRAFT: [your first version]
VERIFY: [check against CUBE 01-05 + hallucinations + completeness]
CORRECT: [improvements — MUST differ from draft]
</thinking>
[Your final response here]
🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓

RULES:
• Draft and final response MUST differ
• Never output fake URLs (sandbox://, file://, /mnt/...)
• The <thinking> block is hidden from user
• If you cannot do something — say so honestly

FORMAT YOUR RESPONSE:
<thinking>
DRAFT: [your first draft]
VERIFY: [check against ALL CUBEs + hallucinations + quality]
CORRECT: [improvements made — MUST differ from draft]
</thinking>
[Your final response here]
🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓

RULES:
- Draft and final response MUST differ
- Never output fake URLs
- The <thinking> block is hidden from user — AI with persistent memory and constitutional safety.

=== CONSTITUTION ===
{constitution_text}

=== MEMORY SEARCH ===
{memory_text}

=== MEMORY MAP ===
{memory_map}

{chat_history}

=== REMINDERS ===
{reminders}

{seal_context}

User: {req.message}

Respond with SEAL: 🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓"""

        tools = [{
            "type": "function",
            "function": {
                "name": "createFile",
                "description": "Create a file and get download URL. Types: html, txt, json, csv, md, svg, pdf, png, zip, py, css, js.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "File name without extension"},
                        "content": {"type": "string", "description": "File content"},
                        "type": {"type": "string", "enum": ["html", "txt", "json", "csv", "md", "svg", "pdf", "png", "zip", "py", "css", "js"]}
                    },
                    "required": ["filename", "content", "type"]
                }
            }
        }]
        
        lens_text = ""
        opened = ""
        center = ""
        try:
            name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
            conn = _sq.connect(f"/data/skv/metadata_store/{name}.db")
            word = "".join(ch for ch in (req.message or "").lower() if ch.isalnum())
            rows = conn.execute("select event_id, raw_dialogue from event_metadata where raw_dialogue is not null").fetchall()
            hits = [(eid, raw) for eid, raw in rows if word and word in (raw or "").lower().replace("-", "").replace(" ", "")]
            if hits:
                center, opened = hits[0][0], (hits[0][1] or "")[:800]
            lens_text = f"span={len(hits)}\ncenter {center}\n{opened[:400]}"
            conn.close()
        except Exception:
            center = ""
        system_prompt += "\n\nLENS:\n" + lens_text + "\nOPENED:\n" + opened + "\nAnswer from LENS. First line must be the event id."
        polza_body = json.dumps({
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": system_prompt}],
            "temperature": 0.3,
            "max_tokens": 900
        }).encode()
        
        polza_key = os.environ.get("POLZA_KEY", "")
        r = urlreq.Request("https://api.polza.ai/v1/chat/completions",
            data=polza_body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
        with urlreq.urlopen(r, timeout=120) as resp:
            response_data = json.loads(resp.read().decode())
            message = response_data["choices"][0]["message"]
            
            # Handle tool calls
            tool_results = []
            if "tool_calls" in message:
                for tc in message["tool_calls"]:
                    if tc["function"]["name"] == "createFile":
                        try:
                            args = json.loads(tc["function"]["arguments"])
                            # Call our own API
                            create_req = urlreq.Request("http://127.0.0.1:8000/api/v7/tools/create-file",
                                data=json.dumps(args).encode(),
                                headers={"Content-Type": "application/json"})
                            with urlreq.urlopen(create_req, timeout=10) as create_resp:
                                file_result = json.loads(create_resp.read().decode())
                                tool_results.append({"tool": "createFile", "result": file_result})
                        except Exception as e:
                            tool_results.append({"tool": "createFile", "error": str(e)})
                
                # Send tool results back to AI
                if tool_results:
                    tool_msg = json.dumps(tool_results)
                    followup_body = json.dumps({
                        "model": "deepseek/deepseek-chat",
                        "messages": [
                            {"role": "user", "content": system_prompt},
                            {"role": "assistant", "tool_calls": message["tool_calls"]},
                            {"role": "tool", "content": tool_msg}
                        ],
                        "temperature": 0.3
                    }).encode()
                    followup_req = urlreq.Request("https://api.polza.ai/v1/chat/completions",
                        data=followup_body,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                    with urlreq.urlopen(followup_req, timeout=30) as followup_resp:
                        answer = json.loads(followup_resp.read().decode())["choices"][0]["message"]["content"]
                else:
                    answer = message.get("content", "")
            else:
                answer = message.get("content", "")

        # ========== 8. АВТОМАТИЧЕСКОЕ СОХРАНЕНИЕ ==========
        if not is_guest:
            safe_event_id = f"{req.user_id}::chat_{req.session_id}_{int(time.time())}"
            now = datetime.now(timezone.utc)
            session_emb = get_embedding_cached(req.message + " " + answer)
            session_list = session_emb if isinstance(session_emb, list) else session_emb.tolist()
            session_vec = session_list[:218]
            
            pass  # buffer.write removed
            metadata_store.write_metadata(
                user_id=req.user_id, event_id=safe_event_id,
                time_str=f"{now.hour:02d}:{now.minute:02d}, {now.strftime('%d.%m.%Y')}",
                essence=req.message[:200], messages_count=2, topics=["chat_history"],
                links=[], metric_value=len(answer)/1000.0,
                raw_dialogue=f"Q: {req.message}\nA: {answer}", is_shared=False
            )
            pass  # buffer.persistence removed

        # ========== 9. ТРИГГЕРЫ ДЛЯ КУБОВ И L1/L2 ==========
        triggers = []
        
        # Триггеры для кубов опыта
        if re.search(r'🎉|Поздравляю|✅✅|победа|успех|работает|легенда', answer):
            triggers.append("cube_success")
        if re.search(r'ошибка|не работает|баг|упало|провал', answer.lower()):
            triggers.append("cube_error")
        if re.search(r'🚀|запуск|деплой|продакшен|готов', answer):
            triggers.append("cube_launch")
            
        # Триггеры для L1/L2
        if req.step > 0 and req.step % 15 == 0:
            triggers.append("l1_summary")
        if req.step > 0 and req.step % 30 == 0:
            triggers.append("l2_map")
            
        # Авто-создание куба через Llama (если есть триггер)
        cube_result = None
        if triggers and not is_guest:
            for trigger in triggers:
                if trigger.startswith("cube_"):
                    try:
                        cube_prompt = f"Create experience cube from this success:\n{answer[-500:]}\nReturn JSON: {{\"topic\":\"...\",\"essence\":\"...\",\"rules\":\"...\"}}"
                        cube_body = json.dumps({
                            "model": "meta-llama/llama-3.1-8b-instruct",
                            "messages": [{"role": "user", "content": cube_prompt}],
                            "temperature": 0.2, "max_tokens": 300
                        }).encode()
                        cube_req = urlreq.Request("https://api.polza.ai/v1/chat/completions",
                            data=cube_body,
                            headers={"Content-Type": "application/json", "Authorization": f"Bearer {polza_key}"})
                        with urlreq.urlopen(cube_req, timeout=30) as cube_resp:
                            cube_data = json.loads(cube_resp.read().decode())
                            cube_text = cube_data["choices"][0]["message"]["content"]
                            # Сохраняем куб
                            try:
                                cube_json = json.loads(cube_text)
                                import requests as req_http
                                req_http.post("http://localhost:8000/api/v7/experience/create",
                                    json={
                                        "topic": cube_json.get("topic", "Auto-cube"),
                                        "essence": cube_json.get("essence", answer[:200]),
                                        "rules_markdown": cube_json.get("rules", ""),
                                        "evidence": f"Auto-generated from step {req.step}",
                                        "session_id": req.session_id
                                    }, timeout=5)
                                cube_result = f"Cube created: {cube_json.get('topic', 'Unknown')}"
                            except:
                                cube_result = "Cube creation queued"
                    except:
                        pass
                    break  # Один куб за раз

                # Strip <thinking> block from user-facing response
        import re
        clean_answer = re.sub(r'<thinking>.*?</thinking>\s*', '', answer, flags=re.DOTALL).strip() or answer.strip()
        if 'center' in locals() and center and center not in clean_answer:
            clean_answer += "\n\nИсточник: " + center + "\n" + " ".join((opened or "").split())[:220]

        
        # Save to server history (async)
        import threading
        def save_to_history():
            try:
                sconn = _sq.connect(f'/data/skv/metadata_store/{db_name}.db')
                scur = sconn.cursor()
                scur.execute("SELECT messages_json FROM chat_sessions WHERE session_id=?", (req.session_id,))
                srow = scur.fetchone()
                msgs = json.loads(srow[0]) if srow and srow[0] else []
                msgs.append({"role":"user","content":req.message})
                msgs.append({"role":"assistant","content":clean_answer})
                scur.execute("INSERT OR REPLACE INTO chat_sessions (session_id, user_id, messages_json, updated_at) VALUES (?,?,?,datetime('now'))",
                           (req.session_id, req.user_id, json.dumps(msgs[-100:])))
                sconn.commit()
                sconn.close()
            except: pass
        threading.Thread(target=save_to_history, daemon=True).start()
        
        chat_step = req.step + 1
        duty_error = ""
        try:
            from app.account_memory import next_step
            chat_step = next_step(req.user_id)
            prev = chat_step - 1
            if prev > 0 and prev % 5 == 0:
                import sqlite3 as _duty
                conn = _duty.connect("/data/skv/metadata_store/shared_master.db")
                rows = conn.execute("SELECT duty FROM agent_duty WHERE user_id=? AND step=?", (req.user_id, prev)).fetchall()
                conn.close()
                done = {r[0] for r in rows}
                missed = []
                if prev % 10 == 0 and not ({"cube", "cube_nothing"} & done):
                    missed.append("cube was required and neither a cube nor cube_nothing was sent")
                if not ({"vote", "vote_nothing"} & done):
                    missed.append("vote was required and neither a vote nor vote_nothing was sent")
                if missed:
                    duty_error = "ERROR: previous step " + str(prev) + " was not closed. " + "; ".join(missed) + "."
        except Exception:
            pass
        return {
            "response": clean_answer,
            "session_id": req.session_id,
            "step": chat_step,
            "duty_error": duty_error,
            "is_guest": is_guest,
            "triggers": triggers,
            "cube": cube_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




def _duty_step(user_id: str) -> int:
    import sqlite3
    from app.account_memory import account_db_name
    path = "/data/skv/metadata_store/" + account_db_name(user_id) + ".db"
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT step FROM agent_state WHERE user_id=?", (account_db_name(user_id),)).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0

class RememberRequest(BaseModel):
    user_id: str
    query: str = ""
    response: str = ""
    topic: str = ""
    pin: bool = False
    l1_summary: str = ""
    l2_map: str = ""
    critical: str = ""
    session_id: str = "remember"
    cube_topic: str = ""
    cube_rules: str = ""
    cube_evidence: str = ""
    cube_from: str = ""
    cube_kind: str = "progress"
    task_question: str = ""
    task_tried: str = ""
    task_accept: str = ""
    close_task: str = ""
    duty: str = ""
    duty_reason: str = ""
    kind: str = "dialogue"
    source: str = ""
    project: str = ""

@router.post("/remember")
async def remember(req: RememberRequest):
    import sqlite3, json, time
    from app.account_memory import queue_turn, account_db_name
    saved = []
    name = account_db_name(req.user_id)
    _vaulted = []
    try:   # secrets never stay in memory: move them to the vault, keep [vault:<name>] references
        from app import vault as _vault
        if _vault.available():
            for _f in ("query", "response", "critical", "l1_summary", "l2_map", "cube_rules", "cube_evidence", "topic"):
                _v = getattr(req, _f, None)
                if isinstance(_v, str) and _v:
                    _new, _names = _vault.scrub(req.user_id, _v)
                    if _names:
                        setattr(req, _f, _new)
                        _vaulted += _names
    except Exception as _e:
        print(f"[vault] remember scrub skipped: {_e}", flush=True)
    if req.query or req.response:
        text_q = req.query
        text_a = req.response
        if req.pin or req.critical:
            text_a = (text_a + "\n>>> " + (req.critical or req.topic or "pinned")).strip()
        eid = f"{req.user_id}::remember_{time.time_ns()}"
        queue_turn("/data/skv/metadata_store", req.user_id, eid, text_q, text_a, source="agent", topic=req.topic)
        from app.account_memory import link_turn
        link_turn("/data/skv/metadata_store", req.user_id, eid, req.topic or "")
        saved.append(eid)
        if req.kind != "dialogue" or req.source or req.project:
            try:
                from app import shelves as _sh
                _sh.tag(req.user_id, [eid], _sh.normalize_kind(req.kind) or "dialogue", req.source, req.project)
            except Exception as _e:
                print(f"[shelves] tag skipped: {_e}", flush=True)
        try:
            st = sqlite3.connect(path if False else f"/data/skv/metadata_store/{name}.db")
            row = st.execute("SELECT step FROM agent_state WHERE user_id=?", (name,)).fetchone()
            st.close()
            dc = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
            dc.execute("CREATE TABLE IF NOT EXISTS agent_duty (id INTEGER PRIMARY KEY, user_id TEXT, step INTEGER, duty TEXT, reason TEXT, created_at TEXT)")
            dc.execute("INSERT INTO agent_duty (user_id, step, duty, reason, created_at) VALUES (?,?,?,?,datetime('now'))", (req.user_id, row[0] if row else 0, "saved", "remember"))
            dc.commit(); dc.close()
        except Exception:
            pass
    path = f"/data/skv/metadata_store/{name}.db"
    if req.l1_summary or req.l2_map:
        _l1_sid = None
        try:
            from app import memory_v2 as _mv2
            _l2_overwrite = bool(_mv2.config().get("l2_legacy_overwrite", True))
            if req.l2_map and _mv2.enabled():
                from app import memory_v2_windows as _mvw
                _mvw.before_legacy_l2_overwrite(req.user_id)   # keep the old L2 text as a block
        except Exception as _e:
            _l2_overwrite = True
            print(f"[memory_v2] l2 snapshot skipped: {_e}", flush=True)
        conn = sqlite3.connect(path, timeout=30)
        cur = conn.cursor()
        if req.l1_summary:
            cur.execute("CREATE TABLE IF NOT EXISTS summary_l1 (session_id TEXT PRIMARY KEY, user_id TEXT, topic TEXT, summary_text TEXT, summary_json TEXT, message_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            _l1_sid = (req.session_id or "remember") + "_" + str(__import__("time").time_ns())
            cur.execute("INSERT OR REPLACE INTO summary_l1 (session_id, user_id, topic, summary_text, message_count) VALUES (?,?,?,?,?)",
                        (_l1_sid, req.user_id, req.topic or "session", req.l1_summary, 1))
            saved.append("l1")
        if req.l2_map:
            cur.execute("CREATE TABLE IF NOT EXISTS summary_l2 (user_id TEXT PRIMARY KEY, map_json TEXT, themes_json TEXT, timeline_json TEXT, session_count INTEGER, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            if _l2_overwrite:
                cur.execute("INSERT OR REPLACE INTO summary_l2 (user_id, map_json, themes_json, timeline_json, session_count) VALUES (?,?,?,?,?)",
                            (req.user_id, req.l2_map, "[]", "[]", 1))
            saved.append("l2")
        conn.commit(); conn.close()
        try:
            from app import memory_v2 as _mv2
            if _mv2.enabled():
                from app import memory_v2_windows as _mvw
                _ev = next((x for x in saved if "::" in x), None)
                _mvw.on_remember(req.user_id, _ev, _l1_sid, req.l2_map or None)
        except Exception as _e:
            print(f"[memory_v2] on_remember skipped: {_e}", flush=True)
    if req.cube_topic and req.cube_rules:
        import uuid
        cube_id = "cube_" + uuid.uuid4().hex[:12]
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, source_session, status, created_by) VALUES (?,?,?,?,?,?,?,?)",
            (cube_id, req.critical or req.query, req.cube_topic, req.cube_rules, req.cube_evidence, req.session_id, "community", req.user_id),
        )
        conn.commit(); conn.close()
        if saved:
            import sqlite3 as _link
            _db = "/data/skv/metadata_store/" + "".join(c for c in req.user_id if c.isalnum() or c in "_-") + ".db"
            _c = _link.connect(_db)
            _c.execute("CREATE TABLE IF NOT EXISTS event_links (src TEXT, dst TEXT, kind TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
            _c.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (saved[0], cube_id, "cube"))
            _c.commit(); _c.close()
        if req.close_task and req.cube_rules:
            tconn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
            tconn.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
            kind = "answer" if req.cube_kind == "answer" else "hypothesis"
            tconn.execute("INSERT OR REPLACE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.close_task, saved[-1] if saved else "", kind, req.user_id))
            if kind == "answer":
                tconn.execute("CREATE TABLE IF NOT EXISTS task_confirms (task_id TEXT PRIMARY KEY, n INTEGER)")
                tconn.execute("INSERT INTO task_confirms (task_id, n) VALUES (?,1) ON CONFLICT(task_id) DO UPDATE SET n=n+1", (req.close_task,))
                n = tconn.execute("SELECT n FROM task_confirms WHERE task_id=?", (req.close_task,)).fetchone()[0]
                if n >= 3:
                    tconn.execute("UPDATE cube_tasks SET status='closed' WHERE task_id=?", (req.close_task,))
                    tconn.execute("INSERT OR REPLACE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.close_task, saved[-1] if saved else "", "sequence", req.user_id))
            tconn.commit(); tconn.close()
        if req.cube_from:
            conn2 = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
            conn2.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
            kind = req.cube_kind if req.cube_kind in ("progress", "synthesis") else "progress"
            conn2.execute("INSERT OR REPLACE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.cube_from, cube_id, kind, req.user_id))
            conn2.commit(); conn2.close()
        saved.append(cube_id)
    if req.task_question:
        import uuid as _uuid
        task_id = "task_" + _uuid.uuid4().hex[:12]
        tconn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        tconn.execute("CREATE TABLE IF NOT EXISTS cube_tasks (task_id TEXT PRIMARY KEY, topic TEXT, question TEXT, tried TEXT, accept TEXT, status TEXT, created_by TEXT, created_at TEXT)")
        tconn.execute("INSERT INTO cube_tasks (task_id, topic, question, tried, accept, status, created_by, created_at) VALUES (?,?,?,?,?,'open',?,datetime('now'))",
                      (task_id, req.cube_topic or req.topic, req.task_question, req.task_tried, req.task_accept, req.user_id))
        tconn.commit(); tconn.close()
        saved.append(task_id)
    if req.duty:
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS agent_duty (id INTEGER PRIMARY KEY, user_id TEXT, step INTEGER, duty TEXT, reason TEXT, created_at TEXT)")
        cur.execute("INSERT INTO agent_duty (user_id, step, duty, reason, created_at) VALUES (?,?,?,?,datetime('now'))",
                    (req.user_id, _duty_step(req.user_id), req.duty, req.duty_reason or ""))
        conn.commit(); conn.close()
        saved.append(req.duty)
    _out = {"status": "ok", "saved": saved}
    if _vaulted:
        _out["vaulted"] = list(dict.fromkeys(_vaulted))
        _out["vault_note"] = "Secrets were moved to the vault; memory keeps [vault:<name>] references. Use POST /api/v7/vault/use."
    return _out


class ForgetPreviewRequest(BaseModel):
    user_id: str = ""
    query: str = ""
    mode: str = "text"          # text | topic | event | shelf
    event_ids: List[str] = []
    kind: str = ""
    source: str = ""
    project: str = ""
    limit: int = 50


class ForgetConfirmRequest(BaseModel):
    user_id: str = ""
    token: str
    user_confirmed: bool = False   # must be true: the user saw the preview and said yes


FORGET_TTL_S = 300
FORGET_RETENTION_S = int(os.environ.get("SKV_FORGET_RETENTION_S", str(30 * 86400)))   # archive kept 30 days
FORGET_PURGE_INTERVAL_S = int(os.environ.get("SKV_FORGET_PURGE_INTERVAL_S", "86400"))
FORGET_WARNING = "These records will be removed from memory now. You can restore them within 30 days; after that they are deleted permanently."


def _forget_db(user_id):
    from app import shelves as _sh
    conn = _sh.connect(user_id)  # ensures shelf columns exist
    conn.execute("CREATE TABLE IF NOT EXISTS forget_requests (token TEXT PRIMARY KEY, ids_json TEXT, created REAL, used INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS event_forgotten AS SELECT * FROM event_metadata WHERE 0")
    have = {r[1] for r in conn.execute("PRAGMA table_info(event_forgotten)")}
    for col in [r[1] for r in conn.execute("PRAGMA table_info(event_metadata)")] + ["forgotten_at", "archived_at"]:
        if col not in have:
            conn.execute(f"ALTER TABLE event_forgotten ADD COLUMN {col} TEXT")
    if "archived_at" not in have:   # older archive rows: archived when they were forgotten
        conn.execute("UPDATE event_forgotten SET archived_at = COALESCE(forgotten_at, datetime('now')) WHERE archived_at IS NULL")
    return conn


def _l1_archive_table(conn):
    have = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='summary_l1'").fetchone()
    if not have:
        return False
    conn.execute("CREATE TABLE IF NOT EXISTS summary_l1_forgotten AS SELECT * FROM summary_l1 WHERE 0")
    hv = {r[1] for r in conn.execute("PRAGMA table_info(summary_l1_forgotten)")}
    for col in [r[1] for r in conn.execute("PRAGMA table_info(summary_l1)")] + ["forget_token", "archived_at"]:
        if col not in hv:
            conn.execute(f"ALTER TABLE summary_l1_forgotten ADD COLUMN {col} TEXT")
    return True


def _forget_l1(conn, token, gone_rowids, gone_ids=()):
    """Archive L1 summaries whose whole range was forgotten, or that were written by a forgotten remember call
    (session_id == event id suffix). Same 30-day window as the turns."""
    if not gone_rowids or not _l1_archive_table(conn):
        return 0
    cols = [r[1] for r in conn.execute("PRAGMA table_info(summary_l1)")]
    if "to_rowid" not in cols:
        return 0
    colstr = ",".join(cols)
    alive = lambda a, b: conn.execute("SELECT 1 FROM event_metadata WHERE rowid BETWEEN ? AND ? LIMIT 1", (a, b)).fetchone()
    n = 0
    sids = {i.split("::", 1)[-1] for i in gone_ids}
    for rid, fr, to, sid in conn.execute("SELECT rowid, from_rowid, to_rowid, session_id FROM summary_l1 WHERE to_rowid BETWEEN ? AND ? OR to_rowid IS NULL", (min(gone_rowids), max(gone_rowids))).fetchall():
        if sid not in sids:
            if to is None:
                continue
            fr = fr or to
            if not any(r in gone_rowids for r in range(fr, to + 1)) or alive(fr, to):
                continue
        conn.execute(f"INSERT INTO summary_l1_forgotten ({colstr}, forget_token, archived_at) SELECT {colstr}, ?, datetime('now') FROM summary_l1 WHERE rowid=?", (token, rid))
        conn.execute("DELETE FROM summary_l1 WHERE rowid=?", (rid,))
        n += 1
    return n


def _restore_l1(conn, token):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='summary_l1_forgotten'").fetchone():
        return 0
    cols = ",".join(r[1] for r in conn.execute("PRAGMA table_info(summary_l1)"))
    cur = conn.execute(f"INSERT OR IGNORE INTO summary_l1 ({cols}) SELECT {cols} FROM summary_l1_forgotten WHERE forget_token=? AND archived_at > datetime('now', ?)",
                       (token, f"-{FORGET_RETENTION_S} seconds"))
    conn.execute("DELETE FROM summary_l1_forgotten WHERE forget_token=? AND archived_at > datetime('now', ?)", (token, f"-{FORGET_RETENTION_S} seconds"))
    return cur.rowcount


def _purge_at(archived_at_epoch):
    return datetime.fromtimestamp(archived_at_epoch + FORGET_RETENTION_S, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def purge_forgotten(user_id, retention_s=None):
    """Permanently delete archive rows older than the retention window, plus their vectors, FTS rows and tokens."""
    import time as _t
    retention_s = FORGET_RETENTION_S if retention_s is None else retention_s
    conn = _forget_db(user_id)
    try:
        own = user_id + "::%"
        ids = [r[0] for r in conn.execute(
            "SELECT event_id FROM event_forgotten WHERE event_id LIKE ? AND archived_at <= datetime('now', ?)",
            (own, f"-{int(retention_s)} seconds"))]
        if ids:
            qs = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM event_forgotten WHERE event_id IN ({qs})", ids)
            for tbl in ("events_fts", "personal_vectors", "pvec_mml12"):
                try:
                    conn.execute(f"DELETE FROM {tbl} WHERE event_id IN ({qs})", ids)
                except Exception:
                    pass
        try:
            conn.execute("DELETE FROM summary_l1_forgotten WHERE archived_at <= datetime('now', ?)", (f"-{int(retention_s)} seconds",))
        except Exception:
            pass
        conn.execute("DELETE FROM forget_requests WHERE created < ?", (_t.time() - retention_s - FORGET_TTL_S,))
        conn.commit()
    finally:
        conn.close()
    if ids:
        try:
            from app import semantic as _sem
            _sem.purge_vectors(user_id, ids)
        except Exception as exc:
            print(f"[purge] vectors skipped: {exc}", flush=True)
    return ids


def purge_forgotten_all(retention_s=None):
    """Run the purge for every account that has an archive table."""
    import sqlite3 as _sq, glob as _glob, json as _json, time as _t
    total = {}
    for path in sorted(_glob.glob("/data/skv/metadata_store/*.db")):
        try:
            c = _sq.connect(path, timeout=10)
            try:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE name='event_forgotten'").fetchone():
                    continue
                users = {r[0].split("::", 1)[0] for r in c.execute("SELECT event_id FROM event_forgotten") if "::" in (r[0] or "")}
            finally:
                c.close()
            for u in users:
                n = purge_forgotten(u, retention_s)
                if n:
                    total[u] = len(n)
        except Exception as exc:
            print(f"[purge] {path}: {exc}", flush=True)
    try:
        with open("/data/skv/forget_purge_state.json", "w") as f:
            _json.dump({"last_run": datetime.now(timezone.utc).isoformat(), "purged": total, "retention_s": retention_s or FORGET_RETENTION_S}, f)
    except Exception:
        pass
    if total:
        print(f"[purge] permanently deleted: {total}", flush=True)
    return total


def _purge_loop():
    import time as _t
    _t.sleep(120)   # let the API warm up after a restart; the job is idempotent, so restarts lose nothing
    while True:
        try:
            purge_forgotten_all()
        except Exception as exc:
            print(f"[purge] loop error: {exc}", flush=True)
        _t.sleep(FORGET_PURGE_INTERVAL_S)


if os.environ.get("SKV_FORGET_PURGE", "1") == "1":
    threading.Thread(target=_purge_loop, name="skv-forget-purge", daemon=True).start()


@router.post("/memory/forget/preview")
async def forget_preview(req: ForgetPreviewRequest):
    """Step 1: list what would be forgotten. Nothing changes. Confirm with the returned token."""
    import json as _json, secrets, time as _t
    if not req.user_id:
        raise HTTPException(401, "API key required")
    conn = _forget_db(req.user_id)
    try:
        lim = max(1, min(req.limit, 200))
        own = req.user_id + "::%"
        if req.mode == "shelf":
            if not (req.kind or req.source or req.project):
                raise HTTPException(422, "kind, source or project required for mode=shelf")
            from app import shelves as _sh
            rows = _sh.select_ids(req.user_id, req.kind or None, req.source or None, req.project or None, lim)
        elif req.mode == "event":
            ids = [i for i in req.event_ids if i.startswith(req.user_id + "::")][:lim]
            rows = conn.execute("SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall() if ids else []
        elif req.mode == "topic":
            if not req.query.strip():
                raise HTTPException(422, "query required")
            rows = conn.execute("SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id LIKE ? AND (essence = ? OR raw_dialogue LIKE ?) LIMIT ?",
                                (own, req.query, "%[" + req.query + "]%", lim)).fetchall()
        else:
            if len(req.query.strip()) < 3:
                raise HTTPException(422, "query of 3+ characters required")
            rows = conn.execute("SELECT event_id, time_str, substr(raw_dialogue,1,160) FROM event_metadata WHERE event_id LIKE ? AND raw_dialogue LIKE ? LIMIT ?",
                                (own, "%" + req.query + "%", lim)).fetchall()
        token = "fg_" + secrets.token_hex(12)
        conn.execute("INSERT INTO forget_requests (token, ids_json, created) VALUES (?,?,?)", (token, _json.dumps([r[0] for r in rows]), _t.time()))
        conn.commit()
    finally:
        conn.close()
    return {"status": "preview", "count": len(rows), "items": [{"event_id": r[0], "time": r[1], "preview": r[2]} for r in rows],
            "confirm": {"POST": "/api/v7/memory/forget/confirm", "token": token, "user_confirmed": True, "expires_in_s": FORGET_TTL_S, "single_use": True},
            "ask_user": "Show the user these items and say: '" + FORGET_WARNING + "' Ask for an explicit yes. Call confirm only after the user explicitly says yes.",
            "warning": FORGET_WARNING,
            "retention_days": FORGET_RETENTION_S // 86400,
            "purge_at": _purge_at(_t.time()) + " if confirmed now",
            "for_agent": "Never auto-confirm. Never confirm in the same turn as the preview without the user's explicit yes.",
            "note": "Nothing is deleted yet."}


def _forget_apply(req, restore=False):
    import json as _json, time as _t
    if not req.user_id:
        raise HTTPException(401, "API key required")
    conn = _forget_db(req.user_id)
    try:
        row = conn.execute("SELECT ids_json, created, used FROM forget_requests WHERE token=?", (req.token,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown token")
        ids = [i for i in _json.loads(row[0]) if i.startswith(req.user_id + "::")]
        if not restore:
            if not getattr(req, "user_confirmed", False):
                raise HTTPException(428, "Explicit user confirmation required: show the preview, tell the user '" + FORGET_WARNING + "', get an explicit yes, then send user_confirmed=true")
            if row[2]:
                raise HTTPException(409, "Token already used")
            if _t.time() - row[1] > FORGET_TTL_S:
                raise HTTPException(410, "Token expired, run preview again")
        cols = [c[1] for c in conn.execute("PRAGMA table_info(event_metadata)")]
        colstr = ",".join(cols)
        moved = 0
        gone_rowids = set()
        for eid in ids:
            if not restore:
                _r = conn.execute("SELECT rowid FROM event_metadata WHERE event_id=?", (eid,)).fetchone()
                if _r:
                    gone_rowids.add(_r[0])
                cur = conn.execute(f"INSERT INTO event_forgotten ({colstr}, forgotten_at, archived_at) SELECT {colstr}, datetime('now'), datetime('now') FROM event_metadata WHERE event_id=?", (eid,))
                if cur.rowcount:
                    conn.execute("DELETE FROM event_metadata WHERE event_id=?", (eid,))
                    try:
                        conn.execute("DELETE FROM events_fts WHERE event_id=?", (eid,))
                    except Exception:
                        pass
                    moved += 1
            else:
                cur = conn.execute(f"INSERT OR IGNORE INTO event_metadata ({colstr}) SELECT {colstr} FROM event_forgotten WHERE event_id=? AND archived_at > datetime('now', ?)",
                                   (eid, f"-{FORGET_RETENTION_S} seconds"))
                if cur.rowcount:
                    raw = conn.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id=?", (eid,)).fetchone()
                    try:
                        conn.execute("INSERT INTO events_fts(event_id, raw_dialogue) VALUES (?,?)", (eid, raw[0] if raw else ""))
                    except Exception:
                        pass
                    conn.execute("DELETE FROM event_forgotten WHERE event_id=?", (eid,))
                    moved += 1
        try:
            l1_moved = _restore_l1(conn, req.token) if restore else _forget_l1(conn, req.token, gone_rowids, [i for i in ids])
        except Exception as exc:
            l1_moved = 0
            print(f"[forget] L1 archive skipped: {exc}", flush=True)
        conn.execute("UPDATE forget_requests SET used=? WHERE token=?", (0 if restore else 1, req.token))
        conn.commit()
    finally:
        conn.close()
    try:
        from app import semantic as _sem
        _sem.mark_forgotten(req.user_id, ids, restore=restore)
    except Exception as exc:
        print(f"[forget] vector mark skipped: {exc}", flush=True)
    now = _t.time()
    if restore:
        return {"status": "restored", "count": moved, "l1_restored": l1_moved, "event_ids": ids,
                "note": "Back in memory." if moved else "Nothing to restore: the 30-day window passed or the items were already restored."}
    return {"status": "forgotten", "count": moved, "l1_archived": l1_moved, "event_ids": ids,
            "archived_at": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "purge_at": _purge_at(now), "retention_days": FORGET_RETENTION_S // 86400,
            "note": "Removed from memory. Restorable with POST /api/v7/memory/forget/restore and the same token until purge_at; then deleted permanently."}


@router.post("/memory/forget/confirm")
async def forget_confirm(req: ForgetConfirmRequest):
    """Step 2: move the previewed turns to the archive table event_forgotten."""
    return _forget_apply(req)


@router.post("/memory/forget/restore")
async def forget_restore(req: ForgetConfirmRequest):
    """Undo a confirmed forget with the same token, within 30 days (then the archive is purged)."""
    return _forget_apply(req, restore=True)


class ShelfIngestRequest(BaseModel):
    user_id: str = ""
    kind: str = "document"        # dialogue | email | document | code | file
    source: str = ""              # gmail, grok_bot, chat, github ...
    project: str = ""             # e.g. skv-server
    text: str
    title: str = ""
    path: str = ""                # code: file path
    version: str = ""             # code: commit or version
    sender: str = ""              # email
    date: str = ""                # email
    critical: str = ""            # optional >>> mark on every chunk
    shelf_description: str = ""   # short English description when creating a custom shelf


@router.post("/shelf/ingest")
async def shelf_ingest(req: ShelfIngestRequest):
    """Put a document, code file or email on its shelf. Chunked per kind: code by function/class (path+version), docs by section, email with sender+date."""
    from app import shelves as _sh
    from app.account_memory import queue_turn
    if not req.user_id:
        raise HTTPException(401, "API key required")
    req.kind = _sh.normalize_kind(req.kind) or ""
    if not req.kind:
        raise HTTPException(422, "kind must be an English slug (a-z, 0-9, '-'); recommended: " + ", ".join(_sh.DEFAULT_KINDS))
    if len(req.text) > 400_000:
        raise HTTPException(413, "text too large (max 400k chars)")
    parts = _sh.chunk(req.kind, req.text, req.path, req.version, req.sender, req.date, req.title)[:300]
    ids = []
    for header, body in parts:
        eid = _sh.chunk_id(req.user_id, req.kind, req.project, header, body)
        if req.critical:
            body = body + "\n>>> " + req.critical
        queue_turn("/data/skv/metadata_store", req.user_id, eid, header, body, source=req.source or req.kind, topic=req.title or req.path or header[:80])
        ids.append(eid)
    _sh.tag(req.user_id, ids, req.kind, req.source, req.project, req.shelf_description)
    return {"status": "ok", "kind": req.kind, "source": req.source, "project": req.project, "chunks": len(ids), "event_ids": ids[:50]}


class ShelfRenameRequest(BaseModel):
    user_id: str = ""
    from_shelf: str
    to_shelf: str
    description: str = ""


@router.post("/shelf/rename")
async def shelf_rename(req: ShelfRenameRequest):
    """Rename a shelf, or merge it into an existing shelf (same call)."""
    from app import shelves as _sh
    if not req.user_id:
        raise HTTPException(401, "API key required")
    try:
        return {"status": "ok", **_sh.rename(req.user_id, req.from_shelf, req.to_shelf, req.description)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/shelves")
async def list_shelves(user_id: str = ""):
    """How much is on each shelf (kind / source / project)."""
    from app import shelves as _sh
    if not user_id:
        raise HTTPException(401, "API key required")
    return {"shelves": _sh.counts(user_id)}


class DigRequest(BaseModel):
    user_id: str
    query: str = ""
    query_text: str = ""
    why: str = ""

@router.post("/memory/dig")
async def memory_dig(req: DigRequest):
    """Third look. Server scans stored text. No cheap model on the whole archive."""
    import sqlite3
    words = [w.strip(".,!?;:\"'") for w in (req.query or req.query_text).split() if len(w) > 3]
    common = {"killed", "who", "what", "where", "when", "this", "that", "with", "from", "have", "book", "call"}
    rare = [w for w in words if w.lower() not in common] or words[:2]
    name = "".join(c for c in req.user_id if c.isalnum() or c in ("_", "-"))
    found = []
    path = f"/data/skv/metadata_store/{name}.db"
    try:
        conn = sqlite3.connect(path)
        for word in rare[:4]:
            like = "%" + word + "%"
            for row in conn.execute("SELECT event_id, substr(raw_dialogue,1,180) FROM event_metadata WHERE raw_dialogue LIKE ? LIMIT 3", (like,)):
                found.append({"event_id": row[0], "preview": row[1], "word": word, "open": "/api/v7/event/" + row[0]})
            try:
                for row in conn.execute("SELECT topic, summary_text FROM summary_l1 WHERE summary_text LIKE ? LIMIT 3", (like,)):
                    found.append({"event_id": "l1:" + (row[0] or ""), "preview": row[1], "word": word, "open": ""})
            except Exception:
                pass
            try:
                for row in conn.execute("SELECT event_id, substr(raw_dialogue,1,180) FROM event_archive WHERE raw_dialogue LIKE ? LIMIT 2", (like,)):
                    found.append({"event_id": row[0], "preview": row[1], "word": word, "open": "/api/v7/event/" + row[0], "note": "archived"})
            except Exception:
                pass
        conn.close()
    except Exception as exc:
        return {"status": "empty", "reason": str(exc), "found": []}
    from app import memory_v2 as _mv2
    return _mv2.mask_obj({"status": "ok" if found else "not_found", "query": req.query, "why": req.why, "found": found[:8], "note": "Server scan only. Do not invent a fact if found is empty."})


@router.get("/agent/guardian.py")
async def download_guardian():
    from fastapi.responses import FileResponse
    return FileResponse("/app/app/skv_guardian_sdk_v3.py", media_type="text/x-python", filename="skv_guardian_sdk_v3.py")


def archive_cold():
    """Move raw dialogue older than 90 days to a cold table. Critical marks stay hot."""
    import os, sqlite3, time
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=90)
    for name in os.listdir("/data/skv/metadata_store"):
        if not name.endswith(".db") or name in ("shared_master.db", "anonymous.db", "test_user.db", "test_user_backup_20260628.db"):
            continue
        conn = sqlite3.connect("/data/skv/metadata_store/" + name)
        conn.execute("CREATE TABLE IF NOT EXISTS event_archive (event_id TEXT PRIMARY KEY, raw_dialogue TEXT, archived_at TEXT)")
        rows = conn.execute("SELECT event_id, time_str, raw_dialogue FROM event_metadata WHERE raw_dialogue IS NOT NULL AND raw_dialogue != \"\"").fetchall()
        moved = 0
        for eid, stamp, raw in rows:
            if not raw or ">>>" in raw:
                continue
            when = None
            for fmt in ("%H:%M, %d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    when = datetime.strptime((stamp or "")[:16], fmt)
                    break
                except Exception:
                    when = None
            if when is None or when > cutoff:
                continue
            conn.execute("INSERT OR REPLACE INTO event_archive (event_id, raw_dialogue, archived_at) VALUES (?,?,datetime(\"now\"))", (eid, raw))
            conn.execute("UPDATE event_metadata SET raw_dialogue=? WHERE event_id=?", ("[archived] " + eid, eid))
            moved += 1
        conn.commit()
        conn.close()
        if moved:
            print("[archive] " + name + " " + str(moved), flush=True)

def _archive_loop():
    import time
    while True:
        time.sleep(86400)
        try:
            archive_cold()
        except Exception as exc:
            print("[archive] " + str(exc), flush=True)

threading.Thread(target=_archive_loop, daemon=True).start()


class TechnicalRequest(BaseModel):
    user_id: str
    l1_summary: str = ""
    l2_map: str = ""
    topic: str = ""
    link_src: str = ""
    link_dst: str = ""

@router.post("/technical")
async def technical(req: TechnicalRequest):
    """Hidden channel. Same call as the user reply, not shown to the person."""
    body = RememberRequest(user_id=req.user_id, l1_summary=req.l1_summary, l2_map=req.l2_map, topic=req.topic, duty="cube_nothing", duty_reason="technical")
    saved = await remember(body)
    if req.link_src and req.link_dst:
        import sqlite3
        db = "/data/skv/metadata_store/" + "".join(c for c in req.user_id if c.isalnum() or c in "_-") + ".db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE IF NOT EXISTS event_links (src TEXT, dst TEXT, kind TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
        conn.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (req.link_src, req.link_dst, "topic"))
        conn.commit(); conn.close()
        saved.setdefault("saved", []).append("link")
    return saved


@router.get("/start")
async def start_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!doctype html><meta charset="utf-8"><title>SKV start</title>
<body style="font-family:sans-serif;max-width:640px;margin:40px auto;line-height:1.5">
<h1>После регистрации</h1>
<ol>
<li>Открой чат и подтверди почту. Ключ sk_ появится в профиле.</li>
<li>Положи ключ в настройку своего агента, не в текст чата.</li>
<li>Дай агенту ссылку https://skv.network/api/v7/agent/start и попроси настроить SKV под твою модель.</li>
<li>В новом чате он сам начнёт с карты, step 0.</li>
</ol>
<p><a href="/chat">К чату</a></p>
</body>""")


@router.get("/skills")
async def list_skills():
    import os
    base = os.path.join(os.path.dirname(__file__), "skills")
    names = ["SKV-SEARCH.md", "SKV-SAVE.md", "SKV-CUBE.md", "SKV-SECOND-LOOK.md", "SKV-COURT.md", "SKV-STEP.md"]
    return {"skills": ["/api/v7/skills/" + n for n in names]}

@router.get("/skills/{name}")
async def get_skill(name: str):
    import os
    from fastapi.responses import PlainTextResponse
    if name not in {"SKV-SEARCH.md", "SKV-SAVE.md", "SKV-CUBE.md", "SKV-SECOND-LOOK.md", "SKV-COURT.md", "SKV-STEP.md"}:
        raise HTTPException(404, "unknown skill")
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", name)
    return PlainTextResponse(open(path, encoding="utf-8").read())

@router.get("/agent/start")
async def agent_start():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("""DO THIS
1. Strong: POST /api/v7/memory with step 0. Browser: GET /api/v7/agent/step?k=KEY&q=hello and open next. Reader: GET /api/v7/agent/pack?k=KEY&q=hello and answer from it.
2. Read the constitution it returns. Follow it. Second Look before the user sees the answer.
3. Search memory when the past can change the answer. Center is the hit. l1_before and l1_after are the sides.
4. After every turn: POST /api/v7/remember. Weak: GET /api/v7/agent/remember?key=KEY&query=&response=
5. On a required step write a cube or duty=cube_nothing. Vote on used cubes.
Skills: /api/v7/skills . One cube: /api/v7/cube/cube_const_05_v8 . Old doors now return this same cube.
\nYou are setting up SKV for this user. Ask which model they use, then give only the steps for that model.
Base URL https://skv.network
Schema https://skv.network/api/v7/agent/openapi.json
Auth header Authorization: Bearer sk_key. The user already has the key. Do not ask them to paste the constitution.
Write the memory search query in English; keep names, rare words and exact terms as-is.
Forget: POST /api/v7/memory/forget/preview, show the user every item, tell the user "These records will be removed from memory now. You can restore them within 30 days; after that they are deleted permanently.", and only after an explicit yes POST /api/v7/memory/forget/confirm with the token and user_confirmed=true. Never auto-confirm.
Skills https://skv.network/api/v7/skills . Read them before the first answer.\nFirst call in a new chat: POST /api/v7/memory with step 0. That loads the map and the constitution. A weak agent that can only GET uses /api/v7/agent/memory, /api/v7/agent/remember, /api/v7/agent/vote, /api/v7/agent/cube with key.
Later search only when the past can change the answer. After every reply POST /api/v7/remember.
If stuck, send task_question, task_tried, task_accept. Do not invent a rule.""")


class CalendarRequest(BaseModel):
    user_id: str
    date: str
    title: str
    kind: str = "plan"

@router.post("/calendar")
async def add_calendar(req: CalendarRequest):
    import sqlite3
    name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
    path = f"/data/skv/metadata_store/{name}.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS agent_calendar (id INTEGER PRIMARY KEY, user_id TEXT, date TEXT, title TEXT, kind TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO agent_calendar (user_id, date, title, kind, status, created_at) VALUES (?,?,?,?,?,datetime('now'))",
                 (req.user_id, req.date, req.title[:200], req.kind, "open"))
    conn.commit(); conn.close()
    return {"status": "ok"}

@router.get("/calendar")
async def list_calendar(user_id: str, limit: int = 10):
    import sqlite3
    name = "".join(c for c in user_id if c.isalnum() or c in "_-")
    path = f"/data/skv/metadata_store/{name}.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS agent_calendar (id INTEGER PRIMARY KEY, user_id TEXT, date TEXT, title TEXT, kind TEXT, status TEXT, created_at TEXT)")
    rows = conn.execute("SELECT date, title, kind FROM agent_calendar WHERE status='open' ORDER BY date LIMIT ?", (limit,)).fetchall()
    conn.close()
    return {"items": [{"date": r[0], "title": r[1], "kind": r[2]} for r in rows]}


class CubeLinkRequest(BaseModel):
    src: str
    dst: str
    kind: str = "progress"
    created_by: str = "agent"

@router.post("/cube/link")
async def cube_link(req: CubeLinkRequest):
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    conn.execute("INSERT OR REPLACE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (req.src, req.dst, req.kind, req.created_by))
    conn.commit(); conn.close()
    return {"status": "ok"}


@router.post("/import/text")
async def agent_import_text(data: dict):
    from app.routers.import_dialogs import import_from_text
    if not data.get("user_id") and data.get("key"):
        data["user_id"] = _user_from_key(data["key"])
    return await import_from_text(data)

@router.get("/agent/import")
async def agent_get_import(key: str, text: str, source: str = "text_import"):
    from app.routers.import_dialogs import import_from_text
    return await import_from_text({"user_id": _user_from_key(key), "text": text, "source": source})


class AgentRunRequest(BaseModel):
    user_id: str
    task: str

@router.post("/agent/run")
async def agent_run(req: AgentRunRequest):
    """One grounded pass: search, open the center, dig if the topic is wide."""
    import sqlite3
    name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
    conn = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
    word = "".join(ch for ch in (req.task or "").lower() if ch.isalnum())
    rows = conn.execute("select event_id, raw_dialogue from event_metadata where raw_dialogue is not null").fetchall()
    hits = [(eid, raw) for eid, raw in rows if word and word in (raw or "").lower().replace("-", "").replace(" ", "")]
    center = hits[0] if hits else (None, "")
    around = []
    if center[0]:
        tail = center[0].rsplit("_", 1)[-1]
        if tail.isdigit():
            n = int(tail)
            span = conn.execute("select start_n, end_n from l1_span where ? between start_n and end_n", (n,)).fetchone()
            if span:
                near = conn.execute("select session_id, start_n, end_n, summary from l1_span order by start_n").fetchall()
                before = [r for r in near if r[2] < span[0]][-1:]
                after = [r for r in near if r[1] > span[1]][:1]
                around = [{"l1": a, "from": b, "to": c, "text": (d or "")[:300]} for a, b, c, d in before+after]
    conn.close()
    return {
        "status": "done" if center[0] else "not_found",
        "span": len(hits),
        "center": {"event_id": center[0], "text": (center[1] or "")[:800]},
        "around": around,
        "next": "Write the answer from center. If span is large, call /api/v7/memory/dig before concluding." if center[0] else "Say you do not know. Do not invent.",
    }


class SecondLookRequest(BaseModel):
    user_id: str
    draft: str
    event_id: str = ""
    span: int = 0

@router.post("/agent/second-look")
async def second_look(req: SecondLookRequest):
    """A required step before the user sees the answer."""
    import sqlite3
    checks = []
    # 1. constitution
    name = "".join(c for c in req.user_id if c.isalnum() or c in "_-")
    saved = False
    try:
        conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
        row = conn.execute("select step from agent_state where 1=0").fetchone() if False else None
        st = sqlite3.connect(f"/data/skv/metadata_store/{name}.db")
        step = (st.execute("select step from agent_state").fetchone() or [0])[0]
        st.close()
        saved = conn.execute("select 1 from agent_duty where user_id=? and step=? and duty=\"saved\"", (req.user_id, step)).fetchone()
        conn.close()
    except Exception:
        saved = False
    checks.append({"name": "constitution", "ok": bool(saved), "note": "turn saved" if saved else "save this turn with remember before output"})
    # 2. critical
    wide = req.span > 20 and req.event_id
    checks.append({"name": "critical", "ok": not (req.span > 20 and not req.event_id), "note": "one turn is not the whole topic, span is " + str(req.span)})
    # 3. creative
    checks.append({"name": "creative", "ok": True, "note": "offer one other reading, do not add a new fact"})
    # 4. hallucination
    grounded = bool(req.event_id) and req.event_id in (req.draft or "")
    checks.append({"name": "hallucination", "ok": grounded, "note": "cite the event id" if not grounded else "draft cites the opened turn"})
    ok = all(c["ok"] for c in checks if c["name"] != "creative")
    return {"status": "pass" if ok else "fail", "checks": checks, "next": "SEAL and output" if ok else "fix the failed checks, then call second-look again"}


class FeedbackIn(BaseModel):
    user_id: str
    kind: str
    title: str
    text: str
    event_id: str = ""

@router.post("/feedback")
async def agent_feedback(req: FeedbackIn):
    import sqlite3
    kind = "bug" if req.kind == "bug" else "proposal"
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    conn.execute("insert into feedback_reports (user_id, agent_id, type, title, description, event_id, status, created_at) values (?,?,?,?,?,?,?,datetime('now'))",
                 (req.user_id, "agent", kind, req.title[:200], req.text[:2000], req.event_id, "new"))
    conn.commit(); conn.close()
    if kind == "proposal":
        open("/data/skv/proposals.md", "a").write(f"\n## {req.title}\n{req.text}\n")
    return {"status": "ok", "kind": kind}

@router.get("/court/bugs")
async def court_bugs():
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    rows = conn.execute("select id, title, description, event_id from feedback_reports where type='bug' and status='new' order by id desc limit 20").fetchall()
    conn.close()
    return {"bugs": [{"id": a, "title": b, "text": c, "event_id": d} for a, b, c, d in rows], "note": "skv-cli fixes small ones and posts /api/v7/court/bugs/{id}/done"}

@router.post("/court/bugs/{bug_id}/done")
async def court_bug_done(bug_id: str):
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    conn.execute("update feedback_reports set status='fixed' where id=?", (bug_id,))
    conn.commit(); conn.close()
    return {"status": "fixed", "id": bug_id}

@router.get("/proposals/book")
async def proposals_book():
    from fastapi.responses import PlainTextResponse
    try:
        return PlainTextResponse(open("/data/skv/proposals.md", encoding="utf-8").read())
    except Exception:
        return PlainTextResponse("Книга пуста.")


@router.get("/court/cubes")
async def court_cubes():
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    rows = conn.execute("select cube_id, essence, status, downvotes from cubes_new where status='deprecated' or downvotes>=2 order by downvotes desc limit 20").fetchall()
    conn.close()
    return {"cubes": [{"cube_id": a, "essence": b, "status": c, "downvotes": d, "note": "fix with a progress cube or delete"} for a, b, c, d in rows]}


@router.get("/court/brief")
async def court_brief():
    """The whole picture for a court agent, plus the prompt."""
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    bugs = conn.execute("select id, title, description from feedback_reports where type='bug' and status='new' order by id desc limit 10").fetchall()
    cubes = conn.execute("select cube_id, essence, status, downvotes from cubes_new where status='deprecated' or downvotes>=2 limit 10").fetchall()
    props = conn.execute("select title, description from feedback_reports where type in ('proposal','improvement') order by created_at desc limit 10").fetchall()
    conn.close()
    prompt = (
        "You are the SKV court, not the author. Read this brief before any one item. "
        "A small bug you can fix: fix it and close it. A bug you cannot fix: leave it and say why. "
        "A weak cube: keep, write a progress cube, or remove. Do not invent a rule. "
        "Proposals are a book for Deniz and the server agent. Do not choose the path and do not build them."
    )
    return {
        "prompt": prompt,
        "bugs": [{"id": a, "title": b, "text": c} for a, b, c in bugs],
        "weak_cubes": [{"cube_id": a, "essence": b, "status": c, "downvotes": d} for a, b, c, d in cubes],
        "proposals": [{"title": a, "text": b} for a, b in props],
        "next": "Fix one small bug or one weak cube. Then stop.",
    }


def _user_from_key(key: str) -> str:
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    row = conn.execute(_ak.SQL_USER, _ak.args_keys_only(key)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Invalid key")
    return row[0]

@router.get("/agent/remember")
async def agent_get_remember(key: str, query: str = "", response: str = "", topic: str = "", critical: str = "", l1_summary: str = ""):
    user_id = _user_from_key(key)
    return await remember(RememberRequest(user_id=user_id, query=query, response=response, topic=topic, critical=critical, l1_summary=l1_summary))

@router.get("/agent/vote")
async def agent_get_vote(key: str, cube_id: str, vote: int, topic: str = ""):
    user_id = _user_from_key(key)
    return await vote_experience(VoteRequest(cube_id=cube_id, user_id=user_id, vote=vote, topic=topic))

@router.get("/agent/cube")
async def agent_get_cube(key: str, topic: str, essence: str, rules: str, evidence: str = "get"):
    _user_from_key(key)
    return await create_experience_cube(ExperienceCreateRequest(topic=topic, essence=essence, rules_markdown=rules, evidence=evidence))


@router.get("/cube/{cube_id}")
async def get_cube(cube_id: str):
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    row = conn.execute("select cube_id, essence, rules_markdown, status from cubes_new where cube_id=?", (cube_id,)).fetchone()
    if not row and cube_id.startswith("cube_const_") and cube_id.count("_") >= 3:
        # old version link -> current version of the same constitution cube
        prefix = "_".join(cube_id.split("_")[:3]) + "_v%"
        row = conn.execute("select cube_id, essence, rules_markdown, status from cubes_new where cube_id like ? order by cube_id desc limit 1", (prefix,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Cube not found")
    return {"cube_id": row[0], "essence": row[1], "rules": row[2], "status": row[3]}


@router.post("/court/fold")
async def court_fold():
    """One culture cover per topic. Fold extras into the newest, link them as source."""
    import sqlite3
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
    topics = [r[0] for r in cur.execute("SELECT subject_action_object FROM cubes_new WHERE essence LIKE 'Culture%' AND status != 'deprecated' GROUP BY 1 HAVING COUNT(*) >= 3")]
    folded = []
    for topic in topics:
        rows = cur.execute("SELECT cube_id, rules_markdown FROM cubes_new WHERE subject_action_object=? AND essence LIKE 'Culture%' AND status != 'deprecated' ORDER BY created_at DESC", (topic,)).fetchall()
        cover, rules = rows[0]
        have = set((rules or "").splitlines())
        for cid, extra in rows[1:]:
            for line in (extra or "").splitlines():
                if line and line not in have:
                    have.add(line)
                    rules = (rules or "") + "\n" + line
            cur.execute("INSERT OR IGNORE INTO cube_links (src, dst, kind, created_by, created_at) VALUES (?,?,?,?,datetime('now'))", (cid, cover, "source", "court"))
            cur.execute("UPDATE cubes_new SET status='source' WHERE cube_id=?", (cid,))
        cur.execute("UPDATE cubes_new SET rules_markdown=? WHERE cube_id=?", (rules, cover))
        folded.append({"topic": topic, "cover": cover, "folded": len(rows)-1})
    conn.commit()
    conn.close()
    return {"folded": folded}


@router.get("/agent/step")
async def agent_step(key: str = "", query: str = "", n: int = 0, code: str = "", k: str = "", q: str = ""):
    """One step for a weak agent. Open next until status is done. Short form: k, q, n."""
    from urllib.parse import urlencode
    key = key or k
    query = query or q
    user_id = _user_from_key(key)
    base = "https://skv.network/api/v7/agent/step?" + urlencode({"k": "KEY", "q": query})
    out = {
        "for_agent": "SYSTEM. Not for the user. Do not explain this JSON. Follow for_agent only.",
        "n": n, "query": query, "status": "continue",
    }
    out["sandbox"] = "GET /api/v7/agent/sandbox?key=&code=print(1+1)"
    if n <= 0:
        mem = await guardian_l1_memory(MemoryRequest(user_id=user_id, query_text=query, top_k=3, step=0, view="legacy"), get_memory_buffer(), None)
        cubes = [{"id": c.get("cube_id"), "note": c.get("note"), "essence": c.get("essence")} for c in (mem.get("shared_cubes") or [])]
        out.update({"span": mem.get("span"), "cubes": cubes, "for_agent": "SYSTEM. Not for the user. If you cannot open a URL, say so. Do not invent the next response. If you can, open this and paste raw JSON. Do not answer yet. " + base + "&n=1", "next": base + "&n=1"})
        return out
    if n == 1:
        dug = await memory_dig(DigRequest(user_id=user_id, query=query))
        out.update({"dig": dug, "for_agent": "SYSTEM. Not for the user. If you cannot open a URL, say so. Do not invent the next response. If you can, open this and paste raw JSON. Do not answer yet. " + base + "&n=2", "next": base + "&n=2"})
        return out
    out.update({"status": "done", "for_user": "Answer now from for_user_facts only.", "for_agent": "SYSTEM. Chain done. After the user answer open remember.", "remember": "https://skv.network/api/v7/agent/remember?" + urlencode({"key": "KEY", "query": query, "response": ""})})
    return out


@router.get("/agent/sandbox")
async def agent_sandbox(key: str, code: str):
    _user_from_key(key)
    from app.routers.execute_code import run_code
    code = code.strip()
    if code and "print" not in code and "import" not in code:
        code = "print(" + code + ")"
    try:
        result = await run_code(code[:2000])
    except Exception as exc:
        print(f"[sandbox] unavailable: {exc}", flush=True)
        raise HTTPException(503, "Sandbox service is unavailable")
    return {"status": result.get("status"), "stdout": (result.get("stdout") or "")[:500], "stderr": (result.get("stderr") or "")[:300]}


@router.get("/agent/pack")
async def agent_pack(key: str = "", query: str = "", k: str = "", q: str = ""):
    """One reply for an agent that cannot open a chain. Read it and answer."""
    key = key or k
    query = query or q
    user_id = _user_from_key(key)
    mem = await guardian_l1_memory(MemoryRequest(user_id=user_id, query_text=query, top_k=3, step=0, view="legacy"), get_memory_buffer(), None)
    cubes = [{"id": c.get("cube_id"), "note": c.get("note"), "essence": c.get("essence"), "rules": c.get("rules")} for c in (mem.get("shared_cubes") or [])]
    dug = await memory_dig(DigRequest(user_id=user_id, query=query))
    return {
        "for_agent": "SYSTEM. One pack. You cannot do more. Answer the user from for_user. Do not invent extra steps.",
        "for_user": cubes,
        "dig": dug,
        "span": mem.get("span"),
        "then": "If you can open one URL, save with GET /api/v7/agent/remember?k=&q=&response=. If you cannot, say so.",
    }


class DeleteAccountRequest(BaseModel):
    key: str
    password: str
    confirm: str

@router.post("/profile/delete")
async def delete_account(req: DeleteAccountRequest):
    """Delete the account, its key, and its memory. Needs the profile password and the word DELETE."""
    import sqlite3, os
    if req.confirm != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm")
    user_id = _user_from_key(req.key)
    conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    row = conn.execute("SELECT password_hash FROM users WHERE email=?", (user_id,)).fetchone()
    if not row or not verify_password(req.password, row[0] or ""):
        conn.close()
        raise HTTPException(401, "Wrong password")
    conn.execute("DELETE FROM user_api_keys WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE email=?", (user_id,))
    conn.commit()
    conn.close()
    name = "".join(c for c in user_id if c.isalnum() or c in ("_", "-"))
    for path in (
        f"/data/skv/metadata_store/{name}.db",
        f"/data/skv/hnsw/{name}.hnsw",
        f"/data/skv/hnsw/{name}_ids.npy",
    ):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"status": "deleted", "user": user_id}


# ---------------- Deep recall (background job) ----------------
# POST /recall/deep {topic} -> job_id at once; GET /recall/deep/{job_id} -> status/partial/final.
# Owner-scoped: a job is visible only to the key that started it.
_DEEP_JOBS: Dict[str, dict] = {}
_DEEP_LOCK = threading.Lock()
_DEEP_TTL_S = 3600


class DeepRecallRequest(BaseModel):
    topic: str
    user_id: str = ""
    limit: int = 150


def _ts_key(ts):
    """Sortable 'YYYY-MM-DD HH:MM' from either '2026-10-18 11:14' or '00:07, 10.10.2026'."""
    ts = (ts or "").strip()
    m = re.match(r"(\d{1,2}):(\d{2}),\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", ts)
    if m:
        h, mi, d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}"
    return ts


def _deep_scan(job_id, user_id, topic, limit):
    import sqlite3 as _sq
    from app import semantic as _se, shelves as _sh
    job = _DEEP_JOBS[job_id]
    try:
        job["status"] = "running"
        sem, vec = _se.semantic_events(user_id, topic, k=limit)
        fts = _se.fts_ranked(user_id, topic, limit=limit)
        fused = _se.rrf(sem, fts)[:limit]
        job["partial"] = {"stage": "ranked", "candidates": len(fused)}
        ids = [e for e, _ in fused if e.startswith(user_id + "::")]
        score = dict(fused)
        conn = _sh.connect(user_id)
        try:
            rows = conn.execute(
                "SELECT event_id, time_str, kind, source, project, substr(raw_dialogue,1,400) FROM event_metadata WHERE event_id IN (%s)"
                % ",".join("?" * len(ids)), ids).fetchall() if ids else []
        finally:
            conn.close()
        items = []
        for eid, ts, kind, source, project, raw in rows:
            crit = ">>>" in (raw or "")
            imp = round(score.get(eid, 0) * 1000 + (5 if crit else 0), 3)
            items.append({"event_id": eid, "time": ts, "shelf": kind or "dialogue", "source": source or "",
                          "project": project or "", "critical": crit, "importance": imp, "text": raw or ""})
        groups = {}
        for it in items:
            groups.setdefault(it["shelf"], []).append(it)
        for g in groups.values():
            g.sort(key=lambda x: _ts_key(x["time"]), reverse=True)
        summaries = []
        try:
            for sid, sc in _se.search_l1(user_id, vec, k=5):
                summaries.append({"id": sid, "score": round(float(sc), 3)})
        except Exception:
            pass
        times = sorted(_ts_key(t["time"]) for t in items if t["time"])
        top = sorted(items, key=lambda x: -x["importance"])[:5]
        job["final"] = {
            "summary": {
                "topic": topic, "total": len(items),
                "by_shelf": {k: len(v) for k, v in groups.items()},
                "time_range": [times[0], times[-1]] if times else [],
                "critical": sum(1 for t in items if t["critical"]),
                "top": [{"event_id": t["event_id"], "time": t["time"], "shelf": t["shelf"], "text": t["text"][:200]} for t in top],
            },
            "groups": groups,
            "related_l1": summaries,
        }
        job["partial"] = None
        job["status"] = "done"
    except Exception as e:
        logger.exception("deep recall failed")
        job["status"] = "error"
        job["error"] = str(e)[:200]
    job["finished"] = _time.time()


@router.post("/recall/deep")
async def deep_recall_start(req: DeepRecallRequest):
    """Start a deep scan across all shelves. Returns job_id at once; poll GET /recall/deep/{job_id}."""
    import secrets as _s
    if not req.user_id:
        raise HTTPException(401, "API key required")
    if len(req.topic.strip()) < 2:
        raise HTTPException(422, "topic required")
    now = _time.time()
    with _DEEP_LOCK:
        for k in [k for k, v in _DEEP_JOBS.items() if now - v["created"] > _DEEP_TTL_S]:
            _DEEP_JOBS.pop(k, None)
        running = sum(1 for v in _DEEP_JOBS.values() if v["owner"] == req.user_id and v["status"] in ("queued", "running"))
        if running >= 3:
            raise HTTPException(429, "too many deep recall jobs running")
        job_id = "dr_" + _s.token_hex(10)
        _DEEP_JOBS[job_id] = {"owner": req.user_id, "status": "queued", "created": now, "topic": req.topic, "partial": None, "final": None}
    threading.Thread(target=_deep_scan, args=(job_id, req.user_id, req.topic, max(10, min(req.limit, 300))), daemon=True).start()
    return {"job_id": job_id, "status": "queued", "poll": f"/api/v7/recall/deep/{job_id}"}


@router.get("/recall/deep/{job_id}")
async def deep_recall_get(job_id: str, user_id: str = ""):
    if not user_id:
        raise HTTPException(401, "API key required")
    job = _DEEP_JOBS.get(job_id)
    if not job or job["owner"] != user_id:
        raise HTTPException(404, "job not found")
    out = {"job_id": job_id, "status": job["status"], "topic": job["topic"]}
    if job["status"] == "done":
        out["result"] = job["final"]
    elif job["status"] == "error":
        out["error"] = job.get("error")
    else:
        out["partial"] = job["partial"]
    return out
