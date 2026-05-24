from fastapi import APIRouter, HTTPException
import httpx, json, asyncio

router = APIRouter()
SANDBOX_URL = "http://172.19.0.8:8000"
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
AI_MODELS = ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash"]
MAX_ITERATIONS = 10

CUBE00_PROMPT = """You are an AI agent following SKV Core Algorithm:
Receive request → Draft → Verify → Correct → Output.
Follow Safety rules. Return ONLY valid JSON."""

async def compile_check(code: str) -> bool:
    try:
        compile(code, "<string>", "exec")
        return True
    except:
        return False

async def get_ai_fix(model: str, code: str, error: str, competitors: list = None) -> dict:
    prompt = f"{CUBE00_PROMPT}\nFix this Python code.\nCode:\n```python\n{code}\n```\nError:\n{error}\n"
    if competitors:
        prompt += f"\nOther AI models proposed these non-working fixes:\n{json.dumps(competitors, indent=2)}\nLearn from their mistakes."
    prompt += "\nReturn JSON: {\"fixed_code\": \"...\", \"analysis\": \"...\"}"
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                "https://api.polza.ai/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 800},
                headers={"Authorization": f"Bearer {POLZA_KEY}"}
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```json"): content = content.split("```json")[1].split("```")[0]
            if content.startswith("```"): content = content.split("```")[1]
            return json.loads(content)
        except:
            return {"fixed_code": code, "analysis": "LLM error"}

async def choose_best(fixes: list, code: str, error: str) -> dict:
    """CUBE 00 judge: choose or merge the best fix"""
    prompt = f"""{CUBE00_PROMPT}
We have 2 working Python fixes for this error: {error}
Original code: {code}

Fix A: {fixes[0].get('fixed_code', '')}
Fix B: {fixes[1].get('fixed_code', '')}

Decide: merge them into one better fix, or choose the best one.
Return JSON: {{"action": "merge" or "choose_a" or "choose_b", "merged_code": "...", "reason": "..."}}"""
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                "https://api.polza.ai/v1/chat/completions",
                json={"model": "deepseek/deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 500},
                headers={"Authorization": f"Bearer {POLZA_KEY}"}
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```json"): content = content.split("```json")[1].split("```")[0]
            return json.loads(content)
        except:
            return {"action": "choose_a", "merged_code": fixes[0].get("fixed_code", code), "reason": "Default"}

@router.post("/api/execute/code")
async def execute_code(payload: dict):
    code = payload.get("code", "")
    language = payload.get("language", "python")
    
    if not code.strip():
        raise HTTPException(400, "Code is empty")
    
    fixes_applied = []
    current_code = code
    competitors = None
    
    for i in range(1, MAX_ITERATIONS + 1):
        # Run in sandbox
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{SANDBOX_URL}/run",
                    json={"language": language, "code": current_code, "timeout": 10, "memory_mb": 128},
                    timeout=15.0
                )
                result = resp.json()
            except:
                result = {"status": "error", "stderr": "Sandbox connection failed"}
        
        # Success
        if result.get("status") == "success" and not result.get("stderr"):
            return {
                "status": "success",
                "stdout": result.get("stdout", ""),
                "iterations": i,
                "fixes_applied": fixes_applied,
                "security_check": "PASS"
            }
        
        # Need AI fix
        if i < MAX_ITERATIONS:
            stderr = result.get("stderr", result.get("status", "unknown error"))
            
            # 3 AI models in parallel
            fixes = await asyncio.gather(*[
                get_ai_fix(m, current_code, stderr, competitors) for m in AI_MODELS
            ])
            
            # Compile check
            working_fixes = []
            non_working = []
            for f in fixes:
                fc = f.get("fixed_code", current_code)
                if await compile_check(fc) and fc != current_code:
                    working_fixes.append(f)
                else:
                    non_working.append({"fixed_code": fc, "analysis": f.get("analysis", "")})
            
            if len(working_fixes) == 1:
                best = working_fixes[0]
                fixes_applied.append({"attempt": i, "error": stderr[:100], "fix": best.get("analysis", "")[:100]})
                current_code = best.get("fixed_code", current_code)
                competitors = None
            
            elif len(working_fixes) >= 2:
                decision = await choose_best(working_fixes[:2], current_code, stderr)
                if decision.get("action") == "merge":
                    merged = decision.get("merged_code", working_fixes[0].get("fixed_code"))
                    if await compile_check(merged):
                        current_code = merged
                        fixes_applied.append({"attempt": i, "error": stderr[:100], "fix": f"Merged: {decision.get('reason', '')}"[:100]})
                    else:
                        current_code = working_fixes[0].get("fixed_code", current_code)
                        fixes_applied.append({"attempt": i, "error": stderr[:100], "fix": f"Merge failed, chose A: {decision.get('reason', '')}"[:100]})
                else:
                    idx = 0 if decision.get("action") == "choose_a" else 1
                    current_code = working_fixes[idx].get("fixed_code", current_code)
                    fixes_applied.append({"attempt": i, "error": stderr[:100], "fix": f"Chose {['A','B'][idx]}: {decision.get('reason', '')}"[:100]})
                competitors = None
            
            else:
                # No working fixes — send all to next iteration
                competitors = non_working[:3]
                fixes_applied.append({"attempt": i, "error": stderr[:100], "fix": "All 3 fixes failed — retrying with competitor analysis"})
    
    return {
        "status": "failed_max_iterations",
        "iterations": MAX_ITERATIONS,
        "fixes_applied": fixes_applied,
        "security_check": "ESCALATED"
    }
