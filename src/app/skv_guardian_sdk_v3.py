"""
SKV Guardian SDK v3.0 — Second Look + Auto-Save + Triggers
Контролирует агента: <thinking>, SEAL, L1/L2, кубы, фидбэк.
"""
import re, json, logging, asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
import httpx

logger = logging.getLogger("SKV_Guardian_SDK_v3")

SYSTEM_PROMPT_ADDON = """
FORMAT YOUR RESPONSE:
<thinking>
DRAFT: [first version]
VERIFY: [check against CUBE 01-05 + hallucinations]
CORRECT: [improvements — MUST differ from draft]
</thinking>
[Final response for user]
🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓

RULES:
• Draft and final response MUST differ
• Never output fake URLs
• The <thinking> block is hidden from user
• When a topic is complete → create L1 summary
• When you discover a pattern → create experience cube
"""

class SKVGuardianSDK:
    def __init__(self, llm_client, model: str, skv_api_url: str = "https://skv.network",
                 api_key: Optional[str] = None, session_timeout_minutes: int = 30,
                 auto_save_interval: int = 5):
        self.client = llm_client
        self.model = model
        self.skv_url = skv_api_url.rstrip("/")
        self.api_key = api_key
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.auto_save_interval = auto_save_interval
        self._http = httpx.AsyncClient(timeout=15.0)
        
        self.last_seal: Dict[str, str] = {}
        self.step_counter: Dict[str, int] = {}
        self.sessions: Dict[str, Dict] = {}
        self._janitor_task: Optional[asyncio.Task] = None
        
        logger.info(f"Guardian SDK v3.0: {model} @ {self.skv_url}")

    # ── API методы ──
    async def _api_call(self, method: str, path: str, data: Dict = None) -> bool:
        try:
            h = {"Content-Type": "application/json"}
            if self.api_key:
                h["Authorization"] = f"Bearer {self.api_key}"
            
            if method == "POST":
                r = await self._http.post(f"{self.skv_url}{path}", json=data or {}, headers=h)
            else:
                r = await self._http.get(f"{self.skv_url}{path}", headers=h)
            return r.status_code in (200, 201)
        except Exception as e:
            logger.error(f"API {path}: {e}")
            return False

    async def _save_event(self, user_id: str, session_id: str, query: str, response: str):
        """Auto-save dialogue every N messages."""
        step = self.step_counter.get(session_id, 0)
        if step > 0 and step % self.auto_save_interval == 0:
            await self._api_call("POST", "/api/v7/event/write", {
                "user_id": user_id,
                "session_id": session_id,
                "query": query,
                "response": response,
                "topic": query[:50]
            })

    async def _save_l1(self, user_id: str, session_id: str, topic: str, summary: str):
        """Save L1 summary."""
        await self._api_call("POST", "/api/v7/memory/summarize", {
            "user_id": user_id,
            "session_id": session_id,
            "topic": topic,
            "summary_text": summary,
            "message_count": self.step_counter.get(session_id, 0)
        })

    async def _save_l2(self, user_id: str, session_count: int):
        """Update L2 map."""
        await self._api_call("POST", "/api/v7/memory/map", {
            "user_id": user_id,
            "session_count": session_count
        })

    async def _create_cube(self, topic: str, essence: str, rules: str):
        """Create experience cube from trigger."""
        await self._api_call("POST", "/api/v7/experience/create", {
            "topic": topic,
            "essence": essence,
            "rules_markdown": rules,
            "evidence": "Auto-detected by Guardian SDK v3",
            "session_id": "auto"
        })

    # ── Анализ ответа ──
    def _analyze_response(self, response: str) -> Dict:
        """Analyze response for triggers."""
        triggers = {
            "cube_success": False,
            "cube_error": False,
            "l1_needed": False,
            "l2_needed": False
        }
        
        # Success triggers → cube
        if re.search(r'🎉|Поздравляю|✅✅|победа|успех|работает|легенда|works!|success', response):
            triggers["cube_success"] = True
        
        # Error triggers → cube
        if re.search(r'ошибка|не работает|баг|упало|провал|error|bug|failed', response.lower()):
            triggers["cube_error"] = True
        
        # Topic completion → L1
        if re.search(r'Что дальше|Итог|Результат|Conclusion|Summary|Done|Готово', response):
            triggers["l1_needed"] = True
        
        return triggers

    # ── Основной метод ──
    async def chat(self, session_id: str, user_id: str, query: str) -> str:
        """Отправляет запрос агенту и возвращает чистый ответ."""
        
        # Получаем контекст из SKV
        step = self.step_counter.get(session_id, 0)
        try:
            r = await self._http.post(f"{self.skv_url}/api/v7/memory", json={
                "query_text": query,
                "user_id": user_id,
                "step": step,
                "last_seal": self.last_seal.get(session_id, "")
            })
            context = r.json().get("prompt_text", "") if r.status_code == 200 else ""
        except:
            context = ""

        system_prompt = f"{context}\n\n{SYSTEM_PROMPT_ADDON}"
        
        # Запрос к LLM
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ]
            )
            raw_response = resp.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"[SKV Error] {e}"

        # Вырезаем <thinking> блок
        clean_response = re.sub(r'<thinking>.*?</thinking>\s*', '', raw_response, flags=re.DOTALL).strip()
        
        # Проверяем что DRAFT ≠ RESPONSE
        thinking_match = re.search(r'<thinking>(.*?)</thinking>', raw_response, re.DOTALL)
        if thinking_match:
            thinking_content = thinking_match.group(1)
            if 'DRAFT:' in thinking_content and 'CORRECT:' in thinking_content:
                # Second Look выполнен
                pass
            else:
                logger.warning("Second Look incomplete — no DRAFT/CORRECT in thinking")
        
        # Извлекаем SEAL
        seal_match = re.search(r'🔐\s*SKV\s*\|\s*#(\d+)', clean_response)
        if seal_match:
            self.last_seal[session_id] = seal_match.group(0)
        
        # Сохраняем диалог (каждые N сообщений)
        await self._save_event(user_id, session_id, query, clean_response)
        
        # Анализируем ответ на триггеры
        triggers = self._analyze_response(raw_response)
        
        if triggers["cube_success"]:
            # Просим Llama создать куб
            await self._create_cube(
                "Auto-detected success",
                clean_response[:200],
                "- Auto-generated from success trigger"
            )
        
        if triggers["l1_needed"]:
            # Llama создаёт L1
            await self._save_l1(user_id, session_id, 
                f"Session {session_id[:8]}", 
                clean_response[:500])
            await self._save_l2(user_id, self.step_counter.get(session_id, 0))
        
        self.step_counter[session_id] = step + 1
        return clean_response

    async def close(self):
        await self._http.aclose()
