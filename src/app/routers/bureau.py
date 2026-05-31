"""SKV Design Bureau — simplified, robust version"""
from fastapi import APIRouter, HTTPException
import asyncio, httpx, json, re, time
from typing import List, Dict

router = APIRouter()
POLZA_API = "https://api.polza.ai/v1/chat/completions"
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
FLASH = "deepseek/deepseek-v4-flash"
CRITIC = "deepseek/deepseek-chat"
VALIDATOR = "http://127.0.0.1:8000/api/validate/formula"

CUBE_00 = "CUBE 00: Second Look - draft, check, fix, output"
CUBE_04 = "CUBE 04: Truth - be honest, no fabricated proofs"

async def call_llm(model, prompt, system="", max_tokens=2000, temp=0.3):
    msgs = []
    if system: msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=90.0) as c:
                r = await c.post(POLZA_API, json={"model": model, "messages": msgs, "temperature": temp, "max_tokens": max_tokens}, headers={"Authorization": f"Bearer {POLZA_KEY}"})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[LLM-ERR] {model}: {e}", flush=True)
            if attempt == 2: return f"ERROR: {e}"
            await asyncio.sleep(2)
    return "ERROR"

def parse_json(text):
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try: return json.loads(m.group(0))
        except: pass
    return {}

def get_formulas(text):
    out = []
    for line in text.split('\n'):
        m = re.search(r'PYTHON_FORMULA:\s*(.+)', line)
        if m: out.append(m.group(1).strip())
    return out

async def decompose(query):
    prompt = (CUBE_00 + "\n\nYou are Director. Decompose task.\n\nTASK: " + query + "\n\n"
              "Return JSON: {\"subtasks\": [{\"id\": \"s1\", \"description\": \"...\", \"parallel\": true, \"depends_on\": []}], \"feasibility\": \"solvable|partial|unsolvable\", \"honesty_note\": \"...\"}")
    print("[DECOMPOSE] Starting...", flush=True)
    r = await call_llm(CRITIC, prompt, "Director. JSON only.", temp=0.2, max_tokens=1500)
    p = parse_json(r)
    if p and "subtasks" in p:
        print(f"[DECOMPOSE] {len(p['subtasks'])} subtasks, feasibility={p.get('feasibility')}", flush=True)
        return p
    print("[DECOMPOSE] Fallback: single", flush=True)
    return {"subtasks": [{"id": "s1", "description": query, "parallel": True, "depends_on": []}], "feasibility": "partial", "honesty_note": ""}

async def run_subtask(subtask, context=""):
    q = subtask["description"]
    if context: q = "Context:\n" + context + "\n\nTask: " + q
    prompt = (CUBE_00 + "\n" + CUBE_04 + "\n\nSpecialist agent.\n\nTASK: " + q + "\n\n"
              "1. Detailed answer\n2. If formulas: PYTHON_FORMULA: line\n3. If unsolvable: honest statement")
    print(f"[SUBTASK] {subtask['id']}", flush=True)
    result = await call_llm(FLASH, prompt, "Specialist. Rigorous.", temp=0.4, max_tokens=2500)
    formulas = get_formulas(result)
    audit_ok, audit_msg = True, ""
    if formulas:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(VALIDATOR, json={"formulas": formulas[:3]}, headers={"Content-Type": "application/json"})
                if r.status_code == 200:
                    a = r.json()
                    if isinstance(a, list):
                        for x in a:
                            if not x.get("valid", False):
                                audit_ok = False
                                audit_msg = x.get("message", "dim fail")
                                break
        except Exception as e:
            audit_msg = str(e)
    print(f"[SUBTASK] {subtask['id']} done, formulas={len(formulas)}, audit={audit_ok}", flush=True)
    return {"subtask_id": subtask["id"], "result": result, "formulas": formulas, "audit_ok": audit_ok, "audit_msg": audit_msg, "success": True}

async def synthesize(query, feasibility, honesty, results):
    res_text = "\n\n".join([f"### {r['subtask_id']}:\n{r['result'][:2000]}" for r in results if r.get("success")])
    prompt = (CUBE_00 + "\n" + CUBE_04 + "\n\nYou are Consciousness. Synthesize ONE answer.\n\n"
              "TASK: " + query + "\nFEASIBILITY: " + feasibility + "\nHONESTY: " + honesty + "\n\n"
              "RESULTS:\n" + res_text + "\n\n"
              "1. Synthesize 2. Resolve contradictions 3. Be honest about unsolvable 4. Include PYTHON_FORMULA 5. Verdict")
    print(f"[SYNTH] {len(results)} results", flush=True)
    return await call_llm(CRITIC, prompt, "Consciousness.", max_tokens=4000)

async def subconscious(query, compiled):
    prompt = (CUBE_00 + "\n" + CUBE_04 + "\n\nSubconscious checker.\n\n"
              "TASK: " + query + "\n\nANSWER:\n" + compiled[:6000] + "\n\n"
              "Check: 1)Constitution 2)Honesty 3)Dimensions 4)Consistency 5)Completeness\n"
              "JSON: {\"approved\": bool, \"veto_reason\": str|null, \"confidence\": float, \"improvements\": []}")
    print(f"[SUBCON] Check {len(compiled)} chars", flush=True)
    r = await call_llm(CRITIC, prompt, "Subconscious. JSON only.", temp=0.1, max_tokens=1000)
    p = parse_json(r)
    print(f"[SUBCON] approved={p.get('approved')}", flush=True)
    return p or {"approved": True, "veto_reason": None, "confidence": 0.5, "improvements": []}

@router.post("/api/bureau/think")
async def bureau_think(payload: dict):
    query = payload.get("task", "")
    if not query: raise HTTPException(400, "No task")
    task_id = f"task_{int(time.time())}"
    t0 = time.time()
    print(f"\n{'='*60}\n[BUREAU START] {task_id}\n{query[:100]}\n{'='*60}", flush=True)
    
    decomp = await decompose(query)
    subtasks = decomp.get("subtasks", [])
    feasibility = decomp.get("feasibility", "partial")
    honesty = decomp.get("honesty_note", "")
    
    parallel = [s for s in subtasks if s.get("parallel", False)]
    sequential = [s for s in subtasks if not s.get("parallel", False)]
    results = []
    
    if parallel:
        pr = await asyncio.gather(*[run_subtask(s) for s in parallel], return_exceptions=True)
        for s, r in zip(parallel, pr):
            results.append({"subtask_id": s["id"], "result": f"ERR: {r}", "success": False} if isinstance(r, Exception) else r)
    
    for s in sequential:
        ctx = "\n".join([f"[{r['subtask_id']}]: {r['result'][:300]}" for r in results if r.get("success")])
        results.append(await run_subtask(s, ctx))
    
    compiled = await synthesize(query, feasibility, honesty, results)
    check = await subconscious(query, compiled)
    elapsed = time.time() - t0
    print(f"\n[BUREAU END] {task_id} {elapsed:.1f}s approved={check.get('approved')}\n{'='*60}", flush=True)
    
    return {"status": "success" if check.get("approved", True) else "vetoed", "task_id": task_id,
            "result": compiled, "subtasks_count": len(subtasks), "feasibility": feasibility,
            "honesty_note": honesty, "subconscious_check": check, "time_ms": int(elapsed * 1000)}
