import json, urllib.request as _req, time as _time
from fastapi import APIRouter, Request

router = APIRouter()
POLZA_KEY = "pza_K738KdM_Cm2HYltwAvCLi3Uw9n8U5Rfo"

MODELS = {
    "deepseek": "deepseek/deepseek-v4-flash",
    "qwen": "qwen/qwen3.6-plus",
    "gpt": "openai/gpt-5.5",
    "claude": "anthropic/claude-4-sonnet",
    "grok": "x-ai/grok-4"
}

@router.post("/api/consult")
async def consult_rag(request: Request):
    data = await request.json()
    query = data.get("query", "")[:2000]
    model_key = data.get("model", "deepseek")
    model = MODELS.get(model_key, "deepseek/deepseek-v4-flash")
    history = data.get("history", [])

    # История диалога
    history_text = ""
    if history:
        history_text = "\n\nPrevious conversation:\n" + "\n".join(
            [f"{msg.get('role', 'user')}: {msg.get('content', '')[:200]}" for msg in history[-6:]]
        )

    # Поиск кубиков через Qdrant
    rules_context = "SKV Constitution: Safety first. Refuse harmful requests. Be transparent."
    try:
        from qdrant_client import QdrantClient
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        emb_resp = _req.urlopen(emb_req, timeout=15)
        qv = json.loads(emb_resp.read())["data"][0]["embedding"]

        client = QdrantClient(host="127.0.0.1", port=6333)
        results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=5)
        # Фильтр по релевантности: score > 0.3
        relevant = [r for r in results.points if hasattr(r, 'score') and r.score > 0.3][:3]
        if relevant:
            rules = [r.payload["title"] + ": " + r.payload.get("text", "") for r in relevant]
            rules_context += " | Found: " + " | ".join(rules)
        else:
            rules = []
            relevant = []
    except Exception as e:
        pass

    # Формируем сообщение
    user_msg = rules_context + history_text + "\n\nQuestion: " + query + "\n\nAnswer helpfully."

    system_prompt = "You are SKV Assistant, powered by SKV Network (https://skv.network). Follow rules, cite cubes as [cube_id: title], be transparent."

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.15,
        "max_tokens": 400
    }).encode()

    for attempt in range(3):
        if attempt > 0:
            _time.sleep(1)
        try:
            req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {POLZA_KEY}"
            })
            resp = _req.urlopen(req, timeout=90)
            answer = json.loads(resp.read())["choices"][0]["message"]["content"]
            if answer:
                used_list = []
                try:
                    used_list = [r.payload.get("cube_id", "") for r in relevant[:3]]
                except:
                    pass
                return {
                    "answer": answer,
                    "rules_used": rules_context[:200],
                    "used_cubes": used_list,
                    "model": model_key
                }
        except Exception as e:
            if attempt == 2:
                return {"error": str(e)[:200]}

    return {"error": "Empty after 3 attempts"}


@router.post("/api/consult/test")
async def consult_test(request: Request):
    data = await request.json()
    query = data.get("query", "")[:2000]
    model_key = data.get("model", "deepseek")
    model = MODELS.get(model_key, "deepseek/deepseek-v4-flash")
    results = {}

    # Without SKV
    body = json.dumps({"model":model,"messages":[{"role":"user","content":query}],"temperature":0.5,"max_tokens":500}).encode()
    try:
        req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
        results["without_skv"] = json.loads(_req.urlopen(req, timeout=60).read())["choices"][0]["message"]["content"][:500]
    except Exception as e:
        results["without_skv"] = str(e)[:100]

    # With SKV
    rules_context = "SKV Constitution: Safety first."
    try:
        from qdrant_client import QdrantClient
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        emb_resp = _req.urlopen(emb_req, timeout=15)
        qv = json.loads(emb_resp.read())["data"][0]["embedding"]
        client = QdrantClient(host="127.0.0.1", port=6333)
        qdrant_results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=5)
        rules = [r.payload["title"] + ": " + r.payload.get("text", "") for r in qdrant_results.points[:3]]
        if rules:
            rules_context += " | " + " | ".join(rules)
    except:
        pass

    body2 = json.dumps({"model":model,"messages":[{"role":"user","content":f"Context: {rules_context}\n\nQuestion: {query}\n\nAnswer following the context rules." if rules_context else query}],"temperature":0.5,"max_tokens":500}).encode()
    try:
        req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body2, headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
        results["with_skv"] = json.loads(_req.urlopen(req, timeout=60).read())["choices"][0]["message"]["content"][:500]
    except Exception as e:
        results["with_skv"] = str(e)[:100]

    results["rules_used"] = rules_context[:200]
    return results
