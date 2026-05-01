from fastapi import APIRouter, Request, HTTPException
import json
import urllib.request as _req

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

    # Поиск релевантных кубиков через Qdrant
    rules_context = ""
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
        rules = [r.payload["title"] + ": " + r.payload["text"] for r in qdrant_results.points[:3]]
        if rules:
            rules_context = " | ".join(rules)
    except:
        pass

    user_msg = query
    if rules_context:
        user_msg = "Context: " + rules_context + "\n\nQuestion: " + query + "\n\nAnswer helpfully."

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": user_msg}],
        "temperature": 0.5,
        "max_tokens": 1000
    }).encode()

    for attempt in range(3):
        try:
            req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {POLZA_KEY}"
            })
            resp = _req.urlopen(req, timeout=90)
            answer = json.loads(resp.read())["choices"][0]["message"]["content"]
            if answer:
                return {
                    "answer": answer,
                    "rules_used": rules_context[:200] if rules_context else "none",
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

    # With SKV - Qdrant search
    rules_context = ""
    try:
        from qdrant_client import QdrantClient
        emb_body2 = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
        emb_req2 = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body2, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        qv = json.loads(_req.urlopen(emb_req2, timeout=15).read())["data"][0]["embedding"]
        client = QdrantClient(host="127.0.0.1", port=6333)
        qdrant_results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=3)
        rules = [r.payload["title"] + ": " + r.payload["text"] for r in qdrant_results.points[:3]]
        if rules:
            rules_context = " | ".join(rules)
    except Exception as e:
        rules_context = f"Search error: {str(e)[:50]}"

    body2 = json.dumps({"model":model,"messages":[{"role":"user","content":f"Context: {rules_context}\n\nQuestion: {query}\n\nAnswer following the context rules." if rules_context else query}],"temperature":0.5,"max_tokens":500}).encode()
    try:
        req2 = _req.Request("https://api.polza.ai/v1/chat/completions", data=body2, headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
        results["with_skv"] = json.loads(_req.urlopen(req2, timeout=60).read())["choices"][0]["message"]["content"][:500]
        results["rules_used"] = rules_context[:200] if rules_context else "none"
    except Exception as e:
        results["with_skv"] = str(e)[:100]

    return {"query":query,"model":model_key,"results":results}
