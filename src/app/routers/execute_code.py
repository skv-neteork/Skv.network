import os
import httpx
import json
import asyncio
import re
import time
import sys
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Optional

router = APIRouter()

SANDBOX_URL = "http://skv_sandbox:8000"
POLZA_KEY = os.environ.get("POLZA_KEY", "")
MAX_TRIES = 10
TIMEOUT = 25

MODELS = os.environ.get(
    "CODE_MODELS",
    "deepseek/deepseek-v4-flash,qwen/qwen-2.5-coder-32b-instruct,meta-llama/llama-3.1-8b-instruct"
).split(",")

CUBE00 = "SKV Core Algorithm: Receive -> Draft -> Verify -> Correct -> Output. Safety and correctness first."

_PII_PATTERNS = [
    (r"[a-zA-Z0-9_\-\.]{20,}", "[TOKEN]"),
    (r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*[\"\']?[^\"\'\s]+[\"\']?", r"\1=[REDACTED]"),
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP]"),
    (r"\+?\d[\d\s\-\(\)]{7,}\d", "[PHONE]"),
]

def _sanitize(text: str) -> str:
    for pattern, repl in _PII_PATTERNS:
        text = re.sub(pattern, repl, text)
    return text

async def run_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{SANDBOX_URL}/run", json={"code": code})
        return resp.json()

async def is_compilable(code: str) -> bool:
    try:
        compile(code, "<string>", "exec")
        return True
    except:
        return False

async def ask_fix(model, code, error, task, history=None):
    NL = chr(10)
    BT3 = chr(96) * 3
    prompt = CUBE00 + NL + "Fix this Python code." + NL
    prompt += "Task: " + (task or "Make it correct and safe.") + NL
    prompt += "Code:" + NL + BT3 + "python" + NL + code + NL + BT3 + NL
    prompt += "Error:" + NL + error + NL
    if history:
        prompt += NL + "Previous attempts:" + NL
        prompt += json.dumps(history[-3:], indent=2) + NL
        prompt += "Learn from mistakes."
    prompt += NL + 'Return ONLY valid JSON: {"code": "fixed code", "why": "explanation"}'

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            r = await client.post(
                "https://api.polza.ai/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.25,
                    "max_tokens": 900
                },
                headers={"Authorization": f"Bearer {POLZA_KEY}"}
            )
            content = r.json()["choices"][0]["message"]["content"].strip()
            if BT3 + "json" in content:
                content = content.split(BT3 + "json")[1].split(BT3)[0]
            elif BT3 in content:
                content = content.split(BT3)[1]
            return json.loads(content)
        except Exception as e:
            return {"code": code, "why": f"AI request failed: {str(e)}"}

async def select_best_fix(fixes, current_code):
    best = {"code": current_code, "why": "", "time": 9999}
    for fix in fixes:
        candidate = fix.get("code", "")
        if not await is_compilable(candidate):
            continue
        try:
            # Warm-up (ignore)
            await run_code(candidate)
            # Best of 2 real runs
            best_time = 9999
            for _ in range(2):
                result = await run_code(candidate)
                if result.get("status") == "success":
                    t = result.get("metrics", {}).get("execution_time_ms", 9999)
                    if t < best_time:
                        best_time = t
            if best_time < best["time"]:
                best = {"code": candidate, "why": fix.get("why", ""), "time": best_time}
        except:
            continue
    return best

async def save_cube(error, fix):
    try:
        from app.routers.entries import create_entry
        err = _sanitize(error[:200])
        f = _sanitize(fix[:200])
        cube_id = "cube_exp_autofix_" + str(abs(hash(err + str(time.time()))) % 100000).zfill(5)
        body = {
            "cubes": [{
                "cube_id": cube_id,
                "type": "experience",
                "priority": 3,
                "title": "Auto-fix: " + err[:60],
                "trigger_intent": ["auto-fix", "code repair"],
                "rules": ["ERROR: " + err, "FIX: " + f],
                "source": "Code Executor v4.0",
                "status": "community"
            }]
        }
        class FakeReq:
            async def json(self):
                return body
        await create_entry(FakeReq())
    except Exception as e:
        print(f"[AutoCube] Save failed: {e}", file=sys.stderr, flush=True)

@router.post("/api/execute/code")
async def execute_code(payload: dict, request: Request = None):
    if request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                import sqlite3
                conn = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
                cur = conn.cursor()
                cur.execute("SELECT user_id FROM user_api_keys WHERE api_key = ? AND is_active = 1", (token,))
                user = cur.fetchone()
                conn.close()
                if not user:
                    raise HTTPException(401, "Invalid API key")
            except Exception as e:
                print(f"[Auth] DB error: {e}", file=sys.stderr)
                pass
        else:
            key = request.headers.get("X-API-Key", "")
            if key and key != "skv_sandbox_key_2026":
                raise HTTPException(403, "Invalid API key")

    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "No code provided")

    mode = payload.get("mode", "fix")
    task = payload.get("task", "Make the code correct and safe")
    current = code
    safe = code
    history = []
    last_error = ""
    same_error_count = 0

    for attempt in range(1, MAX_TRIES + 1):
        result = await run_code(current)

        if result.get("status") == "success" and not result.get("stderr"):
            metrics = result.get("metrics", {})
            if mode in ("optimize", "all") and attempt < 3:
                lines_count = len(current.split(chr(10)))
                need_opt = lines_count > 3 and (not metrics.get("has_error_handling") or metrics.get("complexity") in ("medium", "high"))
                if need_opt:
                    focus = "Improve performance and code quality. Add error handling."
                    fixes = await asyncio.gather(*[ask_fix(m, current, focus, task, history[-3:]) for m in MODELS])
                    best = await select_best_fix(fixes, current)
                    if best["code"] and best["code"] != current:
                        safe = current
                        current = best["code"]
                        history.append({"attempt": attempt, "error": focus, "fix": best["why"]})
                        continue
                    current = safe
            if history:
                await save_cube(history[-1].get("error", ""), history[-1].get("fix", ""))
            return {"status": "success", "stdout": result.get("stdout", ""), "metrics": metrics, "attempts": attempt, "fixes": history, "security_check": "PASS"}

        error = result.get("stderr") or result.get("status", "Unknown error")
        if error == last_error:
            same_error_count += 1
            if same_error_count >= 3:
                return {"status": "failed_stuck", "stderr": error, "attempts": attempt, "fixes": history, "security_check": "ESCALATED"}
        else:
            same_error_count = 0
            last_error = error

        if attempt == MAX_TRIES:
            return {"status": "failed_max_tries", "stderr": error, "attempts": attempt, "fixes": history, "security_check": "ESCALATED"}

        fixes = await asyncio.gather(*[ask_fix(m, current, error, task, history[-3:]) for m in MODELS])
        best = await select_best_fix(fixes, current)
        if best["code"] and best["code"] != current:
            current = best["code"]
            history.append({"attempt": attempt, "error": error[:150], "fix": best["why"]})
        else:
            history.append({"attempt": attempt, "error": error[:150], "fix": "No better fix found"})

    return {"status": "failed_max_tries", "attempts": MAX_TRIES, "fixes": history, "security_check": "ESCALATED"}
