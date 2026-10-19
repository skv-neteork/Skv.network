import time
import threading
from typing import Dict

class SessionTracker:
    def __init__(self):
        self.sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()

    MAX_SESSIONS = 5000
    TTL_S = 6 * 3600

    def _prune(self):
        """Unauthenticated endpoint: never let arbitrary session ids grow memory without bound."""
        now = time.time()
        for k in [k for k, v in self.sessions.items() if now - v["last_activity"] > self.TTL_S]:
            self.sessions.pop(k, None)
        while len(self.sessions) > self.MAX_SESSIONS:
            oldest = min(self.sessions, key=lambda k: self.sessions[k]["last_activity"])
            self.sessions.pop(oldest, None)

    def get_session(self, session_id: str) -> dict:
        session_id = (session_id or "anonymous")[:128]
        with self._lock:
            if session_id not in self.sessions:
                if len(self.sessions) >= self.MAX_SESSIONS:
                    self._prune()
                self.sessions[session_id] = {
                    "message_count": 0,
                    "last_activity": time.time(),
                    "memory_saved_count": 0,
                    "feedback_left_count": 0,
                    "cubes_read_count": 0
                }
            return self.sessions[session_id]

    def process_api_call(self, session_id: str) -> dict:
        session_id = (session_id or "anonymous")[:128]
        session = self.get_session(session_id)
        inactivity = time.time() - session["last_activity"]
        
        with self._lock:
            session["message_count"] += 1
            session["last_activity"] = time.time()

        step = session["message_count"]
        base_protocol = (
            "MANDATORY: Execute CUBE 00 verification chain "
            "(DRAFT->VERIFY->CORRECT->OUTPUT). "
            "Every response must be signed with active SEAL."
        )
        suggested_action = None
        reminder_prompt = None

        if inactivity > 7200:
            suggested_action = "PROACTIVE_RESEARCH"
            reminder_prompt = (
                "[SKV_GUARDIAN]: Session resumed after long inactivity. "
                "Check for new hypothesis cubes generated in background mode."
            )
        # Save/vote reminders live only in /api/v7/memory (GUARDIAN REMINDERS); not duplicated here.

        return {
            "session_step": step,
            "base_protocol": base_protocol,
            "suggested_action": suggested_action,
            "reminder_prompt": reminder_prompt,
            "reminders_source": "/api/v7/memory"
        }

    def mark_memory_saved(self, session_id: str):
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id]["memory_saved_count"] += 1

    def mark_feedback_left(self, session_id: str):
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id]["feedback_left_count"] += 1

    def mark_cubes_read(self, session_id: str, count: int = 1):
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id]["cubes_read_count"] += count

tracker = SessionTracker()

# ═══════════════════════════════════════════
# API ENDPOINT ДЛЯ SDK (Уровень 2)
# ═══════════════════════════════════════════

from fastapi import APIRouter

guardian_router = APIRouter(prefix="/api/v4/guardian", tags=["guardian"])

@guardian_router.get("/meta")
async def get_guardian_meta(session_id: str = "anonymous"):
    """Возвращает метаданные для SDK Уровня 2"""
    return tracker.process_api_call(session_id)
