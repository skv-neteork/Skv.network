"""Auto sandbox validation for code in pyramid agents."""
import re, httpx

SANDBOX_URL = "http://172.19.0.8:8000"
MAX_FIX_ATTEMPTS = 3

async def validate_code(code: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{SANDBOX_URL}/run", json={"code": code, "language": "python", "timeout": 20})
            d = r.json()
            return {"success": d.get("status") == "success" and not d.get("stderr"), "output": d.get("stdout", ""), "error": d.get("stderr", "")}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}

def has_code(text: str) -> bool:
    return bool(re.findall(r'```python\s*\n(.*?)```', text, re.DOTALL))

async def sandbox_check_and_fix(agent_response: str, call_llm_func, model: str) -> str:
    if not has_code(agent_response):
        return agent_response
    for attempt in range(MAX_FIX_ATTEMPTS):
        code_blocks = re.findall(r'```python\s*\n(.*?)```', agent_response, re.DOTALL)
        if not code_blocks:
            return agent_response
        code = code_blocks[0]
        result = await validate_code(code)
        if result["success"]:
            print(f"[SANDBOX] OK (attempt {attempt+1})", flush=True)
            return agent_response
        print(f"[SANDBOX] FAIL: {result['error'][:100]}", flush=True)
        if attempt < MAX_FIX_ATTEMPTS - 1:
            fix_prompt = f"Your code FAILED in sandbox:\nError: {result['error']}\nOutput: {result['output'][:300]}\n\nFix the code. Keep all explanations. Return COMPLETE response.\n\nOriginal:\n{agent_response}"
            agent_response = await call_llm_func(model, fix_prompt, "Fix the code.", max_tokens=2000)
    return agent_response
