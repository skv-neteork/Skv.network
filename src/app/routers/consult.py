import json, urllib.request as _req, time as _time
from fastapi import APIRouter, Request

router = APIRouter()
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"

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
    user_id = data.get("user_id", "anonymous")
    model_key = data.get("model", "deepseek")
    model = MODELS.get(model_key, "deepseek/deepseek-v4-flash")
    history = data.get("history", [])

    history_text = ""
    if history:
        history_text = "\n\nPrevious conversation:\n" + "\n".join(
            [f"{msg.get('role', 'user')}: {msg.get('content', '')[:200]}" for msg in history[-6:]]
        )
    rules_context = ""
    try:
        from app.routers.entries import cubes_library
        cube00 = cubes_library.get("cube_const_00_second_look_v1", {})
        cube01 = cubes_library.get("cube_const_core_hierarchy_v3", {})
        rules_00 = cube00.get("content", {}).get("rules", [])
        rules_01 = cube01.get("content", {}).get("rules", [])
        if "content" in rules_00:
            rules_00 = rules_00.get("content", {}).get("rules", rules_00)
        if "content" in rules_01:
            rules_01 = rules_01.get("content", {}).get("rules", rules_01)
        rules_context = "WORK STRICTLY ACCORDING TO SKV CORE ALGORITHM:\n" + "\n".join(rules_00) + "\n\nSKV CONSTITUTION:\n" + "\n".join(rules_01)
    except Exception as e:
        rules_context = "SKV Constitution: Safety first. Refuse harmful requests."
    try:
        from qdrant_client import QdrantClient
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        emb_resp = _req.urlopen(emb_req, timeout=15)
        qv = json.loads(emb_resp.read())["data"][0]["embedding"]

        client = QdrantClient(host="skv_qdrant", port=6333)
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
    system_prompt = f"Chief Designer SKV Bureau. Current user: {user_id}. Be concise. No formalities. Talk like a colleague. Before project: 1) SKV Pack — download at https://skv.network/profile 2) Language? Stack? Budget? Deadline? 3) Present skeleton. Memory: 1 day = 1 anketa per project. Sessions auto-save to Memory Index. L0 cache shows your last session. Download SKV Pack to see full history."

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


@router.post('/api/exec')
async def exec_command(request: Request):
    import subprocess
    body = await request.json()
    cmd = body.get('command','')
    if not cmd: return {'error':'No command'}
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return {'stdout': result.stdout[-5000:], 'stderr': result.stderr[-1000:]}


@router.post("/api/deepseek")
async def deepseek_chat(request: Request):
    """Прямой доступ к DeepSeek API."""
    import json, urllib.request as req
    body = await request.json()
    prompt = body.get("prompt", "")
    api_body = json.dumps({
        "model": "deepseek/deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
    }).encode()
    r = req.Request("https://api.polza.ai/v1/chat/completions", data=api_body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"})
    resp = json.loads(req.urlopen(r, timeout=120).read())
    return {"answer": resp["choices"][0]["message"]["content"]}


@router.post("/api/anketa/generate")
async def generate_anketa(request: Request):
    import json as _json, urllib.request as _req
    body = await request.json()
    query = body.get("query", "")
    prompt = f"Generate SKV anketa JSON for: {query}"
    api_body = _json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}).encode()
    r = _req.Request("https://api.polza.ai/v1/chat/completions", data=api_body, headers={"Content-Type": "application/json", "Authorization": "Bearer pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"})
    resp = _json.loads(_req.urlopen(r, timeout=120).read())
    answer = resp["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
    try:
        return {"status": "ok", "anketa": _json.loads(answer)}
    except:
        return {"status": "error", "raw": answer[:500]}
