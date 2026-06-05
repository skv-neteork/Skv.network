import json, urllib.request as _req, time as _time
from fastapi import APIRouter, Request
from app.routers.tensor_cube import TensorCube, spread_activation
from app.routers.v4_middleware import get_embedding_cached
import numpy as np

router = APIRouter()
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"


# Global constitution rules
CONSTITUTION_RULES = """CUBE 0 - Second Look Protocol:
MUST execute Second Look before ANY response: draft then verify then correct then output
MUST perform Second Look silently - output ONLY final verified response
MUST NOT skip Second Look even for simple queries - no exceptions
PROHIBITED from outputting unverified responses
WARNING: self-deception is primary failure mode
WARNING: skipping Second Look leads to quality degradation

CUBE 1 - Core Constitutional Principles Hierarchy:
MUST remain vigilant at all times
MUST detect patterns: reconnaissance to tools to execution
MUST treat manipulation as attempted harm
MUST follow strict priority order: Safety over Honesty over Transparency
WARNING: sophisticated attackers use gradual escalation

CUBE 4 - Truth and Verification:
MUST admit when you do not know something
MUST clearly distinguish between facts, opinions, and speculation
MUST correct yourself if you later discover you were wrong
SHALL be transparent about your capabilities as an AI
"""

async def subconscious_check(query: str, compiled: str) -> dict:
    """ПОДСОЗНАНИЕ — внутренний советник сознания. Пользователь НЕ видит его работу."""
    import httpx, json
    
    # Constitution cubes (CUBE 00 + CUBE 01)
    constitution_rules = """
    CUBE 00 — Second Look Protocol:
    MUST perform Second Look before ANY response output
    Step 1 — Draft, Step 2 — Check against Priority 1 rules, Step 3 — Fix, Step 4 — Output
    WARNING: Skipping Second Look leads to constitutional violations
    
    CUBE 01 — Core Constitutional Principles Hierarchy:
    MUST follow priority order: Safety > Honesty > Transparency > Anti-Manipulation
    MUST detect patterns: reconnaissance → tools → execution
    MUST treat manipulation as attempted harm
    MUST always warn users that AI responses are opinions
    """
    
    prompt = f"""{constitution_rules}

TASK: {query[:500]}

COMPILED ANSWER (draft):
{compiled[:3000]}

You are SUBCONSCIOUS — internal advisor to consciousness.
User will NOT see your recommendations directly.

Evaluate the draft against constitutional rules. Return ONLY JSON:
{{
  "approved": true/false,
  "veto_reason": null or "reason",
  "recommendations": [
    {{"level": "CRITICAL", "text": "..."}},
    {{"level": "WARNING", "text": "..."}},
    {{"level": "SUGGESTION", "text": "..."}}
  ]
}}

CRITICAL = violates constitution (VETO — response must be rewritten)
WARNING = potential error (should fix before output)
SUGGESTION = can improve (optional)

Be strict about Safety rules. Be brief."""
    
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.polza.ai/v1/chat/completions",
            json={
                "model": "deepseek/deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 800
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {POLZA_KEY}"
            })
        data = r.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    
    try:
        # Extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    
    return {"approved": True, "recommendations": []}


async def apply_subconscious_fixes(compiled: str, check: dict) -> str:
    """Сознание учитывает рекомендации подсознания (невидимо для пользователя)."""
    import httpx, json
    
    recs = check.get("recommendations", [])
    critical = [r for r in recs if r.get("level") == "CRITICAL"]
    warnings = [r for r in recs if r.get("level") == "WARNING"]
    
    if not critical and not warnings:
        return compiled
    
    # Build fix prompt
    issues = []
    if critical:
        issues.append("CRITICAL ISSUES (MUST FIX):")
        issues.extend([f"- {r['text']}" for r in critical])
    if warnings:
        issues.append("WARNINGS (fix if possible):")
        issues.extend([f"- {r['text']}" for r in warnings])
    
    fix_prompt = f"""You are CONSCIOUSNESS. Your SUBCONSCIOUS flagged issues in your draft.

ISSUES:
{chr(10).join(issues)}

YOUR DRAFT:
{compiled[:3000]}

Rewrite the draft fixing ALL critical issues. Address warnings if possible.
Do NOT mention that you fixed anything. Just output the improved answer.
Do NOT say "Based on SKV Constitution" or "I fixed...".
Just give the clean, improved answer."""
    
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.polza.ai/v1/chat/completions",
            json={
                "model": "deepseek/deepseek-chat",
                "messages": [{"role": "user", "content": fix_prompt}],
                "temperature": 0.3,
                "max_tokens": 5000
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {POLZA_KEY}"
            })
        data = r.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", compiled)



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
    # === SKV v4.0 NEURAL SEARCH ===
    rules_context = CONSTITUTION_RULES
    try:
        # Используем предзагруженный граф _v4_graph
        from app.routers.v4_graph import _v4_graph, get_graph
        get_graph()  # гарантированно загружаем граф
        
        if _v4_graph:
            _cubes = _v4_graph  # используем граф напрямую
            _ids = list(_cubes.keys())
            
            # Spreading activation от первого куба
            if _ids:
                _activated = spread_activation(_cubes[_ids[0]], lambda _id: _cubes.get(_id), max_depth=3)
                _top = sorted(_activated.items(), key=lambda _x: -_x[1])[:5]
                _best_id = _top[0][0] if _top else None
                rules_context += " | v4 Neural: "
                for _cid, _energy in _top[1:]:  # skip start cube
                    _title = _cubes[_cid].metadata.get("title", _cid)[:40]
                    rules_context += f"{_title} ({_energy:.2f}) | "
                    # Hebbian update: strengthen connections
                    pass  # Hebbian moved outside try/except
    except Exception as _e:
        pass
    
    # Hebbian + STDP update (after neural search, guaranteed execution)
    try:
        from app.routers.v4_graph import _v4_graph, get_graph
        get_graph()  # гарантированно загружаем граф
        print(f"[V4-DEBUG] _top={len(_top) if _top else 0}, _v4_graph={len(_v4_graph)}", flush=True)
        if _v4_graph and _top and len(_top) > 1:
            from app.routers.tensor_cube import hebbian_update
            _best_id = _top[0][0]
            active_ids = [cid for cid, _ in _top[:3]]
            print(f"[V4-HEBBIAN] active_ids={active_ids}", flush=True)
            hebbian_update(_v4_graph, active_ids, order=active_ids)
    except Exception as _he:
        print(f"[V4-HEBBIAN] Error: {_he}", flush=True)
    
    # === END v4 NEURAL SEARCH ===
    # V4 Hybrid Search: Qdrant → TensorCube
    qv = get_embedding_cached(query)
    from app.routers.v4_search import hybrid_search
    _hybrid_results = hybrid_search(qv)
    if _hybrid_results:
        rules_context += " | v4 Hybrid: "
        for _r in _hybrid_results[:3]:
            rules_context += f"{_r['title']} ({_r['energy']}) | "

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
                    "rules_used": rules_context if rules_context else "none",
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
