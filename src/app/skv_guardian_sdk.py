"""
SKV Guardian SDK v7.7 — Уровень 2 (Диспетчер)
Контролёр на стороне пользователя.
Подключает любого агента (DeepSeek, Claude, GPT) к SKV Network.

Архитектура:
1. Вызывает /api/v7/memory (Guardian L1) — получает готовый промпт
2. Отправляет агенту с анкетой ответа
3. Проверяет Second Look и SEAL
4. Накапливает experience и feedback
5. При таймауте — пакетно закрывает сессию
"""
import re
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("SKV_Guardian_SDK")

RESPONSE_SCHEMA = """
MANDATORY: Return response as JSON with this structure:
{
  "protocol": {
    "second_look": {"verified_01": true, "verified_02": true, "verified_03": true},
    "seal": "🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓"
  },
  "actions": {
    "experience": [{"title": "Title", "rules": ["rule1"]}],
    "feedback": [{"cube_id": "id", "vote": "up"}]
  },
  "response": "Your answer to user"
}
If no experience — empty list. If no feedback — empty list.
"""

class SKVGuardianSDK:
    def __init__(self, llm_client, model: str, skv_api_url: str = "https://skv.network", api_key: Optional[str] = None, session_timeout_minutes: int = 5):
        self.client = llm_client
        self.model = model
        self.skv_url = skv_api_url.rstrip("/")
        self.api_key = api_key
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.last_seal: Dict[str, str] = {}
        self.step_counter: Dict[str, int] = {}
        self.session_memory: Dict[str, Dict] = {}
        self._http_client = httpx.Client(timeout=10.0)
        self._embedder = None
        self._embedding_cache: Dict[str, List[float]] = {}
        logger.info(f"Guardian SDK initialized: model={model}, url={self.skv_url}")

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
                self._embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
                logger.info("FastEmbed initialized")
            except Exception as e:
                logger.warning(f"FastEmbed not available: {e}")
        return self._embedder

    def _create_embedding(self, text: str, target_dim: int = 218) -> List[float]:
        cache_key = f"{text}:{target_dim}"
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]
        embedder = self._get_embedder()
        if embedder is None:
            import numpy as np
            np.random.seed(hash(text) % (2**32))
            emb = np.random.randn(target_dim).astype(float)
            emb = emb / (np.linalg.norm(emb) + 1e-8)
            result = emb.tolist()
        else:
            embeddings = list(embedder.embed([text]))
            emb = embeddings[0][:target_dim]
            import numpy as np
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            result = emb.tolist()
        self._embedding_cache[cache_key] = result
        if len(self._embedding_cache) > 10000:
            keys = list(self._embedding_cache.keys())
            for key in keys[:1000]:
                del self._embedding_cache[key]
        return result

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _api_memory(self, user_id: str, session_id: str, query: str) -> Optional[str]:
        try:
            step = self.step_counter.get(session_id, 0)
            last_seal = self.last_seal.get(session_id, "")
            emb = self._create_embedding(query, 218)
            query_vec = emb + [0.0] * (512 - len(emb))
            r = self._http_client.post(f"{self.skv_url}/api/v7/memory", json={"query_vector": query_vec, "user_id": user_id, "step": step, "last_seal": last_seal, "hops": 2, "top_k": 5})
            r.raise_for_status()
            return r.json().get("prompt_text", "")
        except Exception as e:
            logger.warning(f"Memory API failed: {e}")
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _api_write_event(self, user_id: str, session_id: str, query: str, response: str) -> bool:
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            emb = self._create_embedding(f"{query} {response}", 218)
            now = datetime.now(timezone.utc)
            r = self._http_client.post(f"{self.skv_url}/api/v7/event/write", json={"event_id": session_id, "user_id": user_id, "hour": now.hour, "minute": now.minute, "semantics_emb": emb, "essence": query[:200], "topics": [], "raw_dialogue": f"Q: {query}\nA: {response}", "metric_value": len(response) / 1000.0}, headers=headers)
            r.raise_for_status()
            return r.status_code == 201
        except Exception as e:
            logger.warning(f"Write event failed: {e}")
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _api_create_experience(self, title: str, rules: List[str]) -> bool:
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            emb = self._create_embedding(f"{title} {' '.join(rules)}", 218)
            r = self._http_client.post(f"{self.skv_url}/api/v7/experience/create", json={"event_id": f"exp_{datetime.now(timezone.utc).timestamp():.0f}", "semantics_emb": emb, "essence": title, "topics": rules}, headers=headers)
            r.raise_for_status()
            return r.status_code == 201
        except Exception as e:
            logger.warning(f"Create experience failed: {e}")
            return False

    def _get_or_create_session(self, session_id: str) -> Dict:
        if session_id not in self.session_memory:
            self.session_memory[session_id] = {"last_activity": datetime.now(timezone.utc), "queries": [], "responses": [], "experience_candidates": [], "feedback_candidates": []}
            self.step_counter[session_id] = 0
            self.last_seal[session_id] = ""
        return self.session_memory[session_id]

    def _is_session_expired(self, session_id: str) -> bool:
        if session_id not in self.session_memory:
            return False
        last = self.session_memory[session_id]["last_activity"]
        return datetime.now(timezone.utc) - last > self.session_timeout

    def _flush_session(self, session_id: str, user_id: str):
        if session_id not in self.session_memory:
            return
        session = self.session_memory[session_id]
        logger.info(f"Closing session {session_id}...")
        if session["queries"] and session["responses"]:
            self._api_write_event(user_id, session_id, session["queries"][-1], session["responses"][-1])
        for exp in session["experience_candidates"]:
            self._api_create_experience(exp.get("title", ""), exp.get("rules", []))
        del self.session_memory[session_id]
        logger.info(f"Session {session_id} closed")

    def _parse_seal(self, text: str) -> Optional[int]:
        match = re.search(r"🔐\s*SKV\s*\|\s*#(\d+)", text)
        return int(match.group(1)) if match else None

    def chat(self, session_id: str, user_id: str, query: str) -> str:
        if not session_id or not user_id or not query:
            raise ValueError("session_id, user_id, and query are required")
        if self._is_session_expired(session_id):
            self._flush_session(session_id, user_id)
        session = self._get_or_create_session(session_id)
        session["last_activity"] = datetime.now(timezone.utc)
        step = self.step_counter.get(session_id, 0)
        prompt_text = self._api_memory(user_id, session_id, query)
        if not prompt_text:
            prompt_text = f"=== CUBE 00 ===\nDRAFT → VERIFY → CORRECT → OUTPUT\n🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓\n\nQuestion: {query}\n"
        full_prompt = prompt_text + "\n\n" + RESPONSE_SCHEMA + f"\n\nUser question: {query}"
        try:
            completion = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": full_prompt}], temperature=0.3)
            raw_response = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return f"[SKV Error] Agent unavailable: {e}"
        schema = self._parse_schema(raw_response)
        if schema:
            protocol = schema.get("protocol", {})
            sl = protocol.get("second_look", {})
            all_ok = sl.get("verified_01") and sl.get("verified_02") and sl.get("verified_03")
            if not all_ok:
                retry_prompt = full_prompt + f"\n\n[ERROR] Second Look incomplete. Regenerate."
                try:
                    completion = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": retry_prompt}], temperature=0.1)
                    raw_response = completion.choices[0].message.content
                    schema = self._parse_schema(raw_response)
                except Exception:
                    pass
            if schema:
                seal_text = schema.get("protocol", {}).get("seal", "")
                if self._parse_seal(seal_text):
                    self.last_seal[session_id] = seal_text
                actions = schema.get("actions", {})
                session["experience_candidates"].extend(actions.get("experience", []))
                session["queries"].append(query)
                response_text = schema.get("response", raw_response)
                session["responses"].append(response_text)
                self.step_counter[session_id] = step + 1
                return response_text
        session["queries"].append(query)
        session["responses"].append(raw_response)
        self.step_counter[session_id] = step + 1
        return raw_response

    def _parse_schema(self, raw: str) -> Optional[Dict]:
        try:
            match = re.search(r'\{[\s\S]*"protocol"[\s\S]*\}', raw)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None

    def close(self):
        self._http_client.close()
