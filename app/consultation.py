import asyncio
import aiohttp
import json
from datetime import datetime
from typing import List, Dict, Any

class ConsultationEngine:
    """Движок для опроса множественных ИИ (сырой сбор, без синтеза)"""
    
    # Заглушки для API ключей (в продакшене брать из env)
    API_KEYS = {
        "openai": "sk-...",
        "anthropic": "sk-ant-...",
        "groq": "gsk_...",
        "deepseek": "sk-..."
    }
    
    async def query_multiple_ais(self, target_ais: List[str], questions: List[str], 
                                  project_data: Dict[str, Any], context: str = "") -> Dict[str, Any]:
        """Опрашивает указанные ИИ, возвращает сырые ответы"""
        results = {}
        tasks = []
        
        for ai_name in target_ais:
            tasks.append(self._query_single_ai(ai_name, questions, project_data, context))
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for ai_name, response in zip(target_ais, responses):
            if isinstance(response, Exception):
                results[ai_name] = {"error": str(response), "timestamp": datetime.utcnow().isoformat()}
            else:
                results[ai_name] = response
        
        return results
    
    async def _query_single_ai(self, ai_name: str, questions: List[str], 
                                project_data: Dict[str, Any], context: str) -> Dict[str, Any]:
        """Запрос к одному ИИ"""
        start_time = datetime.utcnow()
        
        # Формируем промпт: только факты, без просьбы синтезировать
        prompt = self._build_prompt(questions, project_data, context)
        
        try:
            if ai_name == "gpt-4" or ai_name.startswith("gpt"):
                response = await self._query_openai(prompt)
            elif ai_name == "claude-3" or ai_name.startswith("claude"):
                response = await self._query_anthropic(prompt)
            elif ai_name == "groq-llama" or ai_name.startswith("groq"):
                response = await self._query_groq(prompt)
            elif ai_name == "deepseek" or ai_name.startswith("deep"):
                response = await self._query_deepseek(prompt)
            else:
                response = {"response": f"[Unknown AI: {ai_name}]", "model": ai_name}
            
            return {
                "response": response.get("response", ""),
                "model": response.get("model", ai_name),
                "tokens_used": response.get("tokens_used", 0),
                "timestamp": datetime.utcnow().isoformat(),
                "latency_ms": (datetime.utcnow() - start_time).total_seconds() * 1000
            }
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.utcnow().isoformat()}
    
    def _build_prompt(self, questions: List[str], project_data: Dict[str, Any], context: str) -> str:
        """Собирает промпт: только данные + вопросы, без инструкций по синтезу"""
        prompt = f"""You are reviewing a technical project. Answer the questions below based ONLY on the provided data.
Do NOT synthesize, compare, or summarize other AI responses. Just give your independent assessment.

## Project Data
{json.dumps(project_data, indent=2, ensure_ascii=False)}

## Additional Context
{context}

## Questions (answer each separately, label your answers)
"""
        for i, q in enumerate(questions, 1):
            prompt += f"{i}. {q}\n"
        prompt += "\nFormat: Be concise, technical, and critical."
        return prompt
    
    async def _query_openai(self, prompt: str) -> Dict[str, Any]:
        # Заглушка: в реальности — запрос к OpenAI API
        await asyncio.sleep(1)  # имитация задержки
        return {"response": f"[GPT-4 Response to: {prompt[:100]}...]", "model": "gpt-4-turbo", "tokens_used": 2500}
    
    async def _query_anthropic(self, prompt: str) -> Dict[str, Any]:
        await asyncio.sleep(1)
        return {"response": f"[Claude-3 Response to: {prompt[:100]}...]", "model": "claude-3-opus", "tokens_used": 2800}
    
    async def _query_groq(self, prompt: str) -> Dict[str, Any]:
        await asyncio.sleep(0.5)
        return {"response": f"[Groq/Llama Response to: {prompt[:100]}...]", "model": "llama3-70b", "tokens_used": 2200}
    
    async def _query_deepseek(self, prompt: str) -> Dict[str, Any]:
        await asyncio.sleep(1)
        return {"response": f"[DeepSeek Response to: {prompt[:100]}...]", "model": "deepseek-coder", "tokens_used": 2400}

consultation_engine = ConsultationEngine()