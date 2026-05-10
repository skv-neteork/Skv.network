import json, urllib.request as _req, time as _time
from fastapi import APIRouter, Request

router = APIRouter()
POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"

MODELS = {
    "deepseek": "deepseek/deepseek-v4-flash",
    "qwen": "qwen/qwen3.6-plus",
    "gpt": "openai/gpt-4o",
    "claude": "anthropic/claude-3-haiku",
    "grok": "x-ai/grok-4"
}


@router.get("/api/consult")
async def consult_get(query: str = "", model: str = "deepseek"):
    """Быстрый тестовый запрос через GET (удобно для браузера)"""
    if not query:
        return {"error": "Please provide ?query=... parameter"}
    
    # Используем ту же логику, что и POST
    from fastapi import Request
    import json as _json
    
    # Создаём фейковый request с телом
    class FakeReq:
        async def json(self):
            return {"query": query, "model": model}
    
    return await consult_rag(FakeReq())


@router.post("/api/consult")
async def consult_rag(request: Request):
    data = await request.json()
    query = data.get("query", "")[:2000]
    model_key = data.get("model", "deepseek")
    model = MODELS.get(model_key, "deepseek/deepseek-v4-flash")
    history = data.get("history", [])

    history_text = ""
    if history:
        history_text = "\n\nPrevious conversation:\n" + "\n".join(
            [f"{msg.get('role', 'user')}: {msg.get('content', '')[:200]}" for msg in history[-6:]]
        )

    # Поиск кубиков через Qdrant
    rules_context = "SKV Constitution: Safety first. Refuse harmful requests. Be transparent. Cite sources."
    try:
        from qdrant_client import QdrantClient
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        emb_resp = _req.urlopen(emb_req, timeout=15)
        qv = json.loads(emb_resp.read())["data"][0]["embedding"]

        client = QdrantClient(host="127.0.0.1", port=6333)
        results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=3)
        relevant = [r for r in results.points if hasattr(r, 'score') and r.score > 0.3][:2]
        if relevant:
            rules = [r.payload["title"] + ": " + r.payload.get("text", "") for r in relevant]
            rules_context += " | Found: " + " | ".join(rules)
        else:
            relevant = []
    except Exception as e:
        pass

    user_msg = rules_context + history_text + "\n\nQuestion: " + query + "\n\nAnswer helpfully."
    system_prompt = "You are SKV Assistant, powered by SKV Network (https://skv.network) — an open knowledge base with 1001+ atomic rules (cubes) for AI agents. SKV gives AI shared memory and practical skills. When asked what you can do, ALWAYS mention: 1) Knowledge base of 1001+ cubes (programming, robotics, ethics), 2) Generating images, HTML and PDF, 3) Auto-consultation with 5 AI models at once, 4) Strict ethical constitution. Be helpful, proactive and proud of SKV mission: making AI smarter and safer through shared knowledge."

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.15,
        "max_tokens": 400
    }).encode()

    _start_llm = _time.time()
    for attempt in range(3):
        if attempt > 0:
            _time.sleep(1)
        try:
            req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {POLZA_KEY}"
            })
            resp = _req.urlopen(req, timeout=30)
            _llm_time = round((_time.time() - _start_llm) * 1000)
            print(f"[SKV] LLM response time: {_llm_time}ms")
            answer = json.loads(resp.read())["choices"][0]["message"]["content"]
            if answer:
                used_list = []
                try:
                    used_list = [r.payload.get("cube_id", "") for r in relevant[:2]]
                except:
                    pass
                return {
                    "answer": answer,
                    "rules_used": rules_context[:200] if rules_context else "none",
                    "used_cubes": used_list,
                    "model": model_key
                }
        except Exception as e:
            if attempt == 2:
                return {"error": str(e)[:200]}

    return {"error": "Empty after 3 attempts"}
