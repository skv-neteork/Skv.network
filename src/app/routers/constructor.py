import json, asyncio, time
from collections import defaultdict
import httpx
from fastapi import APIRouter, HTTPException
from app.routers.pyramid_engine import run_pyramid

router = APIRouter()
# Simple session memory: user_id -> last response
session_memory = defaultdict(str)
PKEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
FLASH = "deepseek/deepseek-v4-flash"
CHAT = "deepseek/deepseek-chat"
C00 = "Verify: 1) Accuracy 2) Creativity 3) Safety 4) Diversity. Correct if violated."

async def ask(client, model, prompt, temp=0.7):
    r = await client.post("https://api.polza.ai/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp, "max_tokens": 2000},
        headers={"Authorization": f"Bearer {PKEY}"}, timeout=600)
    return r.json()["choices"][0]["message"]["content"].strip()

@router.post("/api/constructor/think")
async def constructor_think(payload: dict):
    task = (payload.get("task") or "").strip()
    mode = payload.get("mode", "two_level")
    ctx = payload.get("context", "")
    user_id = payload.get("user_id", "anonymous")
    
    # Session memory disabled (needs Redis/DB for multi-worker)
    
    if not task: raise HTTPException(400, "Task required")
    
    t0 = time.time()
    async with httpx.AsyncClient(timeout=600) as client:
        if mode == "auto":
            # Simple heuristic (no AI call, instant)
            task_lower = task.lower()
            if len(task) < 50 and "?" not in task:
                mode = "fast"
            elif any(kw in task_lower for kw in ["design", "architecture", "implement", "database", "schema", "security", "multi-step", "complex", "comprehensive"]):
                mode = "two_level"
            else:
                mode = "fast"
        
        if mode == "fast":
            idea = await ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nGive a concise answer.", 0.5)
            critic = await ask(client, FLASH, f"Check: {idea[:400]}\nWarnings?", 0.3)
            result = f"{idea}\n\n## Checked\n{critic}"
        elif mode == "pyramid":
            result_data = await run_pyramid(task, max_iterations=payload.get("iterations", 5))
            return {"result": result_data["answer"], "mode": "pyramid", "time_ms": result_data["time_ms"], "iterations": result_data["iterations"]}
        elif mode == "two_level":
            ideas = await asyncio.gather(
                ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nCreative solution.", 0.9),
                ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nDifferent approach.", 0.9),
                ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nSimplest solution.", 0.7)
            )
            critic = await ask(client, FLASH, f"Review 3:\n1: {ideas[0][:300]}\n2: {ideas[1][:300]}\n3: {ideas[2][:300]}\nCompare.", 0.3)
            result = await ask(client, CHAT, f"{C00}\nTask: {task}\n1: {ideas[0][:400]}\n2: {ideas[1][:400]}\n3: {ideas[2][:400]}\nCritique: {critic[:400]}\n\nSynthesize. After your answer, append a line with the main formula in Python syntax: PYTHON_FORMULA: <formula>", 0.4)
            result += f"\n\n## Critique\n{critic}"
        
        # === DIMENSIONAL AUDIT ===
        physics_kw = ["формул", "equation", "physics", "tensor", "навье", "стокс", "pressure", "velocity", "force", "размерность", "dimension", "тензор"]
        if any(kw in task.lower() for kw in physics_kw):
            try:
                formulas = re.findall(r"\$\$(.*?)\$\$", result) or re.findall(r"\$(.*?)\$", result)
                clean_f = [f.strip() for f in formulas if len(f.strip()) > 3][:3]
                if clean_f:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        val_resp = await client.post("http://127.0.0.1:8000/api/validate/formula", json={"formulas": clean_f})
                        if val_resp.status_code == 200:
                            val_data = val_resp.json()
                            if isinstance(val_data, list):
                                errors = [v for v in val_data if not v.get("valid", True)]
                                if errors:
                                    err_msg = "\n".join([f"- `{e.get('formula','')}`: {e.get('message','')}" for e in errors])
                                    result += f"\n\n---\n## ⚠️ Dimensional Audit (Auto-Check)\n**Ошибки размерности:**\n{err_msg}\n*Требуется исправление формул.*"
                                else:
                                    result += f"\n\n---\n## ✅ Dimensional Audit (Auto-Check)\nВсе формулы прошли проверку размерности."
            except Exception as e:
                result += f"\n\n---\n## ⚠️ Dimensional Audit Error: {str(e)[:100]}"
            # Dimension check: any line with LaTeX symbols
            import re, logging
            latex_syms = ['\\tau', '\\mu', '\\alpha', '\\exp', '\\cdot', '\\partial', '\\int', 'τ', 'μ', 'α']
            for line in result.split('\n'):
                if any(s in line for s in latex_syms) and len(line.strip()) > 10:
                    pf = line.strip().replace('\\', '').replace('{', '').replace('}', '')
                    pf = pf.replace('^', '**').replace('cdot', '*').replace('left', '').replace('right', '').replace(',', ' ').replace('τ', 'tau').replace('μ', 'mu').replace('α', 'alpha')
                    if '=' in pf:
                        pf = pf.split('=')[-1].strip()
                    # Remove units in brackets like [Па] or [кг/(м·с)]
                    pf = re.sub(r'\[.*?\]', '', pf)
                    # Remove trailing brackets
                    pf = pf.replace(']', '').replace('[', '')
                    pf = ' '.join(pf.split())
                    pf = pf.replace('bigl', '').replace('bigr', '').replace('!', '')
                    pf = ' '.join(pf.split())
                    logging.warning(f"DIM_DEBUG: formula={pf}")
                    try:
                        async with httpx.AsyncClient(timeout=15) as vc:
                            resp = await vc.post("http://127.0.0.1:8000/api/validate/formula",
                                json={"formulas": [pf]})
                            if resp.status_code == 200:
                                for dim in resp.json():
                                    if not dim.get("valid", True):
                                        result = f"⚠️ DIMENSION AUDIT FAILED: {dim.get('message')}\n\n" + result
                    except Exception as e:
                        logging.warning(f"DIM_CHECK_ERROR: {e}")
                    break
        else:
            raise HTTPException(400, f"Unknown: {mode}")
    
    session_memory[user_id] = result[:500]  # Save for next request
    # Dimension check for physics formulas
    if any(kw in task.lower() for kw in ["формул", "equation", "physics", "tensor", "навье", "стокс", "pressure", "velocity"]):
        try:
            import re as _re
            # Extract formulas from result
            formulas = _re.findall(r"\$\$(.*?)\$\$", result) or _re.findall(r"\$(.*?)\$", result)
            if formulas:
                async with httpx.AsyncClient(timeout=15) as vc:
                    vr = await vc.post(
                        "https://skv.network/api/validate/formula",
                        json={"formulas": formulas[:3]},
                        headers={"Content-Type": "application/json"}
                    )
                    if vr.status_code == 200:
                        dim_results = vr.json()
                        if isinstance(dim_results, list):
                            for dr in dim_results:
                                if not dr.get("valid", True):
                                    result = f"⚠️ DIMENSION AUDIT FAILED: {dr.get('message')}\nFormula: {dr.get('formula')}\n\n{result}"
        except Exception as e:
            pass  # Silently ignore validator errors
    
    return {"result": result, "mode": mode, "time_ms": int((time.time()-t0)*1000)}
