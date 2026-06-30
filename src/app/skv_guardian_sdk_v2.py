"""
SKV Guardian SDK v2.0 — Production-Ready
Асинхронный контролёр с авто-summary, janitor, feedback.
Подключает любого агента к SKV Network.
"""
import re, json, logging, asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import httpx

logger = logging.getLogger("SKV_Guardian_SDK_v2")

RESPONSE_SCHEMA = """
Return JSON:
{
  "protocol": {
    "second_look": {"verified_01": true, "verified_02": true, "verified_03": true},
    "seal": "🔐 SKV | #N | READ ✓ | VERIFY ✓ | CORRECT ✓ | OUTPUT ✓"
  },
  "actions": {
    "experience": [{"title": "...", "rules": ["rule1"]}],
    "feedback": [{"cube_id": "id", "vote": "up"}]
  },
  "response": "Your answer to user"
}
"""

class SKVGuardianSDK:
    def __init__(self, llm_client, model: str, skv_api_url: str = "https://skv.network",
                 api_key: Optional[str] = None, session_timeout_minutes: int = 5,
                 use_summary: bool = True, janitor_interval_seconds: int = 60):
        self.client = llm_client
        self.model = model
        self.skv_url = skv_api_url.rstrip("/")
        self.api_key = api_key
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.use_summary = use_summary
        self._http = httpx.AsyncClient(timeout=15.0)
        self._janitor_interval = janitor_interval_seconds
        self._janitor_task: Optional[asyncio.Task] = None
        
        # Состояние сессий
        self.last_seal: Dict[str, str] = {}
        self.step_counter: Dict[str, int] = {}
        self.sessions: Dict[str, Dict] = {}
        
        logger.info(f"Guardian SDK v2.0: {model} @ {self.skv_url}")

    # ── Janitor (автоочистка) ──
    async def start_janitor(self):
        if not self._janitor_task:
            self._janitor_task = asyncio.create_task(self._janitor_loop())

    async def stop_janitor(self):
        if self._janitor_task:
            self._janitor_task.cancel()
            try: await self._janitor_task
            except asyncio.CancelledError: pass
            self._janitor_task = None

    async def _janitor_loop(self):
        while True:
            try:
                await asyncio.sleep(self._janitor_interval)
                now = datetime.now(timezone.utc)
                expired = [sid for sid, s in self.sessions.items()
                          if now - s["last_activity"] > self.session_timeout]
                for sid in expired:
                    await self._flush(sid, self.sessions[sid].get("user_id", "unknown"))
                if expired:
                    logger.info(f"Janitor cleaned {len(expired)} sessions")
            except asyncio.CancelledError: break
            except Exception as e: logger.error(f"Janitor: {e}")

    # ── API методы ──
    async def _api_memory(self, user_id: str, session_id: str, query: str) -> str:
        try:
            step = self.step_counter.get(session_id, 0)
            r = await self._http.post(f"{self.skv_url}/api/v7/memory", json={
                "query_text": query,
                "user_id": user_id,
                "step": step,
                "last_seal": self.last_seal.get(session_id, ""),
                "hops": 2, "top_k": 5
            })
            return r.json().get("prompt_text", "") if r.status_code == 200 else ""
        except: return ""

    async def _api_store_summary(self, user_id: str, session_id: str,
                                  summary_json: Dict, message_count: int) -> bool:
        try:
            h = {"Content-Type": "application/json"}
            if self.api_key: h["Authorization"] = f"Bearer {self.api_key}"
            r = await self._http.post(f"{self.skv_url}/api/v7/memory/summarize", json={
                "user_id": user_id, "session_id": session_id,
                "topic": summary_json.get("topic", ""),
                "summary_text": summary_json.get("summary", ""),
                "summary_json": summary_json,
                "message_count": message_count
            }, headers=h)
            return r.status_code == 200
        except: return False

    async def _api_create_experience(self, title: str, rules: List[str]) -> bool:
        try:
            h = {"Content-Type": "application/json"}
            if self.api_key: h["Authorization"] = f"Bearer {self.api_key}"
            r = await self._http.post(f"{self.skv_url}/api/v7/experience/create", json={
                "cube_id": f"cube_{datetime.now(timezone.utc).timestamp():.0f}",
                "creator_id": "agent",
                "topic": title,
                "essence": title,
                "raw_dialogue": " ".join(rules),
                "subject": "agent",
                "action": "create",
                "object": "experience"
            }, headers=h)
            return r.status_code == 201
        except: return False

    async def vote_experience(self, cube_id: str, vote: str = "up") -> bool:
        try:
            h = {"Content-Type": "application/json"}
            if self.api_key: h["Authorization"] = f"Bearer {self.api_key}"
            r = await self._http.post(f"{self.skv_url}/api/v7/experience/vote",
                                      json={"cube_id": cube_id, "vote": vote}, headers=h)
            return r.status_code == 200
        except: return False

    # ── Сессии ──
    def _get_session(self, session_id: str, user_id: str) -> Dict:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "last_activity": datetime.now(timezone.utc),
                "user_id": user_id,
                "history": [],
                "experience_candidates": [],
                "feedback_candidates": []
            }
            self.step_counter[session_id] = 0
            self.last_seal[session_id] = ""
        return self.sessions[session_id]

    async def _flush(self, session_id: str, user_id: str):
        if session_id not in self.sessions: return
        s = self.sessions[session_id]
        logger.info(f"Flushing session {session_id}...")

        # Feedback
        for fb in s.get("feedback_candidates", []):
            await self.vote_experience(fb.get("cube_id", ""), fb.get("vote", "up"))

        # Experience cubes
        for exp in s.get("experience_candidates", []):
            await self._api_create_experience(exp.get("title", ""), exp.get("rules", []))

        # Summary L1
        if self.use_summary and s["history"]:
            try:
                history_text = "\n".join([f"{m['role']}: {m['content']}" for m in s["history"]])
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Extract topic (3-5 words) and summary (2 sentences) as JSON: {\"topic\":\"...\",\"summary\":\"...\"}"},
                        {"role": "user", "content": history_text[:4000]}
                    ],
                    response_format={"type": "json_object"}
                )
                summary = json.loads(resp.choices[0].message.content)
                await self._api_store_summary(user_id, session_id, summary, len(s["history"]))
            except Exception as e:
                logger.error(f"Summary failed: {e}")
                # Fallback
                await self._api_store_summary(user_id, session_id,
                    {"topic": f"Session {session_id[:8]}", "summary": f"{len(s['history'])} messages"},
                    len(s["history"]))

        del self.sessions[session_id]
        self.step_counter.pop(session_id, None)
        self.last_seal.pop(session_id, None)
        logger.info(f"Session {session_id} flushed")

    # ── Основной метод ──
    async def chat(self, session_id: str, user_id: str, query: str) -> str:
        if not all([session_id, user_id, query]):
            raise ValueError("session_id, user_id, query required")

        # Проверка таймаута
        if session_id in self.sessions:
            if datetime.now(timezone.utc) - self.sessions[session_id]["last_activity"] > self.session_timeout:
                await self._flush(session_id, user_id)

        session = self._get_session(session_id, user_id)
        session["last_activity"] = datetime.now(timezone.utc)
        step = self.step_counter[session_id]

        # Получаем контекст из SKV
        prompt_context = await self._api_memory(user_id, session_id, query)
        if not prompt_context:
            prompt_context = "=== CUBE 00 ===\nDRAFT → VERIFY → CORRECT → OUTPUT\nNo past memories found."

        system_prompt = f"{prompt_context}\n\n{RESPONSE_SCHEMA}"
        session["history"].append({"role": "user", "content": query})

        # Запрос к LLM
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt}] + session["history"]
            )
            raw = resp.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"[SKV Error] {e}"

        session["history"].append({"role": "assistant", "content": raw})

        # Парсим JSON
        try:
            data = json.loads(raw)
            seal = data.get("protocol", {}).get("seal", "")
            if seal: self.last_seal[session_id] = seal

            exps = data.get("actions", {}).get("experience", [])
            if exps: session["experience_candidates"].extend(exps)

            fbs = data.get("actions", {}).get("feedback", [])
            if fbs: session["feedback_candidates"].extend(fbs)

            self.step_counter[session_id] = step + 1
            return data.get("response", raw)
        except:
            self.step_counter[session_id] = step + 1
            return raw

    async def close_session(self, session_id: str, user_id: str):
        await self._flush(session_id, user_id)

    async def close(self):
        await self.stop_janitor()
        await self._http.aclose()
