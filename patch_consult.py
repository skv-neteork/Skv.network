import re

with open('/root/skv-core/app/main.py', 'r') as f:
    content = f.read()

# Find the old consult function
old_start = content.find('@app.post("/api/consult")')
old_end = content.find('@app.post("/api/trial")')

new_consult = '''@app.post("/api/consult")
async def consult(request: Request):
    """RAG-powered: search Qdrant rules, inject as context, generate answer."""
    import urllib.request as _req
    data = await request.json()
    query = data.get("query", "")[:2000]
    model = data.get("model", "deepseek-v4-flash")
    
    rules_context = ""
    try:
        from qdrant_client import QdrantClient
        POLZA_KEY = "pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
        emb_body = json.dumps({"model": "text-embedding-3-small", "input": query}).encode()
        emb_req = _req.Request("https://api.polza.ai/v1/embeddings", data=emb_body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {POLZA_KEY}"
        })
        emb_resp = _req.urlopen(emb_req, timeout=15)
        qv = json.loads(emb_resp.read())["data"][0]["embedding"]
        
        client = QdrantClient(host="skv_qdrant", port=6333)
        results = client.query_points(collection_name="skv_rules_v2", query=qv, limit=5)
        rules = [r.payload["title"] + ": " + r.payload["text"] for r in results.points[:3]]
        if rules:
            rules_context = " | ".join(rules)
    except:
        pass
    
    user_msg = query
    if rules_context:
        user_msg = "Context: " + rules_context + "\\n\\nQuestion: " + query + "\\n\\nAnswer helpfully in one sentence."
    
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": user_msg}],
        "temperature": 0.5, "max_tokens": 500
    }).encode()
    
    for attempt in range(3):
        try:
            req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer pza_LjwfFSaGiO54TOspk13LNRyXA_xhufNR"
            })
            resp = _req.urlopen(req, timeout=90)
            answer = json.loads(resp.read())["choices"][0]["message"]["content"]
            if answer:
                return {"answer": answer, "rules_used": rules_context[:200] if rules_context else "none"}
        except Exception as e:
            if attempt == 2:
                return {"error": str(e)[:200]}
    return {"error": "Empty after 3 attempts"}

'''

content = content[:old_start] + new_consult + content[old_end:]
with open('/root/skv-core/app/main.py', 'w') as f:
    f.write(content)
print('Consult patched')
