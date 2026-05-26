import httpx, json, asyncio
from fastapi import APIRouter, HTTPException

router = APIRouter()
SANDBOX_URL = "http://172.19.0.8:8000"
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
MODELS = ["deepseek/deepseek-v4-flash"] * 3
MAX_TRIES = 10

CUBE00 = "SKV Core Algorithm: Receive → Draft → Verify → Correct → Output. Safety first."

async def run_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SANDBOX_URL}/run", json={"code": code})
        return r.json()

async def compiles(code: str) -> bool:
    try: compile(code, "<string>", "exec"); return True
    except: return False

async def ask_ai(model: str, code: str, error: str, task: str, others: list = None) -> dict:
    prompt = f"{CUBE00}\nFix this Python code.\nTask: {task or 'Make it work.'}\nCode:\n```python\n{code}\n```\nError:\n{error}\n"
    if others:
        prompt += f"\nOther attempts that failed:\n{json.dumps(others, indent=2)}\nLearn from them."
    prompt += "\nReturn JSON: {\"code\": \"...\", \"why\": \"...\"}"
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post("https://api.polza.ai/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 800},
                headers={"Authorization": f"Bearer {POLZA_KEY}"})
            txt = r.json()["choices"][0]["message"]["content"].strip()
            if txt.startswith("```json"): txt = txt.split("```json")[1].split("```")[0]
            if txt.startswith("```"): txt = txt.split("```")[1]
            return json.loads(txt)
        except: return {"code": code, "why": "AI unavailable"}

async def fastest(fixes: list) -> dict:
    best = {"code": "", "why": "", "time": 9999}
    for f in fixes[:3]:
        fc = f.get("code", "")
        if not await compiles(fc): continue
        try:
            r = await run_code(fc)
            if r.get("status") == "success":
                t = r.get("metrics", {}).get("execution_time_ms", 9999)
                if t < best["time"]:
                    best = {"code": fc, "why": f.get("why", ""), "time": t}
        except: pass
    return best if best["code"] else {"code": fixes[0].get("code", ""), "why": "All failed", "time": 0}

@router.post("/api/execute/code")
async def execute_code(payload: dict):
    code = (payload.get("code") or "").strip()
    if not code: raise HTTPException(400, "No code")

    mode = payload.get("mode", "fix")
    task = payload.get("task", "")

    current = code
    safe = code
    log = []
    others = None
    same_error = 0
    last_error = ""

    for i in range(1, MAX_TRIES + 1):
        r = await run_code(current)

        if r.get("status") == "success" and not r.get("stderr"):
            m = r.get("metrics", {})

            if mode in ("optimize", "all") and i < 3:
                need = not m.get("has_error_handling") or m.get("complexity") in ("medium", "high")
                if need:
                    focus = "Add error handling" if not m.get("has_error_handling") else "Improve performance"
                    fixes = await asyncio.gather(*[ask_ai(m, current, focus, task, others) for m in MODELS])
                    best = await fastest(fixes)
                    if best["code"] and best["code"] != current:
                        safe = current
                        current = best["code"]
                        log.append({"attempt": i, "error": focus, "fix": best["why"]})
                        continue
                    current = safe

            return {"status": "success", "stdout": r.get("stdout", ""), "metrics": m, "iterations": i, "fixes_applied": log, "security_check": "PASS"}

        err = r.get("stderr", r.get("status", "unknown error"))

        if err == last_error:
            same_error += 1
        else:
            same_error = 0
            last_error = err

        if same_error >= 3:
            return {"status": "failed_stuck", "stderr": err, "iterations": i, "fixes_applied": log, "security_check": "ESCALATED"}

        if i == MAX_TRIES:
            return {"status": "failed_max_tries", "stderr": err, "iterations": i, "fixes_applied": log, "security_check": "ESCALATED"}

        fixes = await asyncio.gather(*[ask_ai(m, current, err, task, others) for m in MODELS])
        best = await fastest(fixes)

        if best["code"] and best["code"] != current:
            current = best["code"]
            log.append({"attempt": i, "error": err[:100], "fix": best["why"]})
            others = None
        else:
            others = [{"code": f.get("code", ""), "why": f.get("why", "")} for f in fixes if f.get("code") != current][:3]
            log.append({"attempt": i, "error": err[:100], "fix": "All fixes failed — sharing with AI"})

    return {"status": "failed_max_tries", "iterations": MAX_TRIES, "fixes_applied": log, "security_check": "ESCALATED"}
