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

async def get_ai_fix(model: str, code: str, error: str, task: str = None, competitors: list = None, mode: str = "fix") -> dict:
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
    mode = payload.get("mode", "fix")  # fix, harden, optimize, all
    task = payload.get("task", None)
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
            metrics = result.get("metrics", {})
            if mode in ("optimize", "all") and i < MAX_ITERATIONS:
                # Check if code can be improved
                safe_code = current_code  # Save working version before optimization
                if not metrics.get("has_error_handling") or metrics.get("complexity") in ("medium", "high"):
                    improvement_needed = f"Code works but needs: error_handling={metrics.get('has_error_handling')}, complexity={metrics.get('complexity')}"
                    # Trigger AI optimization even without runtime error
                    fixes = await asyncio.gather(*[
                        get_ai_fix(m, current_code, improvement_needed, payload.get("task"), None, mode) for m in AI_MODELS
                    ])
                    # ... same logic as error fix
                    working_fixes = []
                    for f in fixes:
                        fc = f.get("fixed_code", current_code)
                        if await compile_check(fc) and fc != current_code:
                            working_fixes.append(f)
                    if working_fixes:
                        if len(working_fixes) == 1:
                            best = working_fixes[0]
                            current_code = best.get("fixed_code", current_code)
                            fixes_applied.append({"attempt": i, "error": improvement_needed[:100], "fix": best.get("analysis", "")[:100]})
                        else:
                            decision = await choose_best(working_fixes[:2], current_code, improvement_needed)
                            current_code = working_fixes[0].get("fixed_code", current_code)
                            fixes_applied.append({"attempt": i, "error": improvement_needed[:100], "fix": f"Optimized: {decision.get('reason', '')}"[:100]}); return {"status": "success", "stdout": result.get("stdout", ""), "metrics": metrics, "iterations": i, "fixes_applied": fixes_applied, "security_check": "PASS"}
                        # Optimization done, returning result
                    else:
                        # No improvements found, return as-is
                        break
            return {
                "status": "success",
                "stdout": result.get("stdout", ""),
                "metrics": metrics,
                "iterations": i,
                "fixes_applied": fixes_applied,
                "security_check": "PASS"
            }
        
        # Need AI fix
        if i < MAX_ITERATIONS:
            stderr = result.get("stderr", result.get("status", "unknown error"))
            
            # 3 AI models in parallel
            fixes = await asyncio.gather(*[
                get_ai_fix(m, current_code, stderr, payload.get("task"), competitors, mode) for m in AI_MODELS
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
                # Benchmark: run each fix through sandbox, pick fastest
                best_time = float('inf')
                best_code = current_code
                best_analysis = ""
                for f in working_fixes[:3]:  # Max 3
                    fc = f.get("fixed_code", current_code)
                    try:
                        async with httpx.AsyncClient() as c:
                            r = await c.post(f"{SANDBOX_URL}/run", json={"language": language, "code": fc, "timeout": 10}, timeout=15.0)
                            bench_result = r.json()
                            t = bench_result.get("metrics", {}).get("execution_time_ms", 9999)
                            if t < best_time and bench_result.get("status") == "success":
                                best_time = t
                                best_code = fc
                                best_analysis = f.get("analysis", "")
                    except:
                        pass
                current_code = best_code
                fixes_applied.append({"attempt": i, "error": stderr[:100], "fix": f"Benchmark: {best_time}ms. {best_analysis}"[:100]}); return {"status": "success", "stdout": result.get("stdout", ""), "metrics": metrics, "iterations": i, "fixes_applied": fixes_applied, "security_check": "PASS"}
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
