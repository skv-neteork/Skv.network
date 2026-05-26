import json, asyncio, time
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()
PKEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
FLASH = "deepseek/deepseek-v4-flash"
CHAT = "deepseek/deepseek-chat"
C00 = "Verify: 1) Accuracy 2) Creativity 3) Safety 4) Diversity. Correct if violated."

async def ask(client, model, prompt, temp=0.7):
    r = await client.post("https://api.polza.ai/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp, "max_tokens": 2000},
        headers={"Authorization": f"Bearer {PKEY}"}, timeout=60)
    return r.json()["choices"][0]["message"]["content"].strip()

@router.post("/api/constructor/think")
async def constructor_think(payload: dict):
    task = (payload.get("task") or "").strip()
    mode = payload.get("mode", "two_level")
    ctx = payload.get("context", "")
    if not task: raise HTTPException(400, "Task required")
    
    t0 = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        if mode == "fast":
            idea = await ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nGive a concise answer.", 0.5)
            critic = await ask(client, FLASH, f"Check: {idea[:400]}\nWarnings?", 0.3)
            result = f"{idea}\n\n## Checked\n{critic}"
        elif mode == "two_level":
            ideas = await asyncio.gather(
                ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nCreative solution.", 0.9),
                ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nDifferent approach.", 0.9),
                ask(client, FLASH, f"{C00}\nTask: {task}\n{ctx}\nSimplest solution.", 0.7)
            )
            critic = await ask(client, FLASH, f"Review 3:\n1: {ideas[0][:300]}\n2: {ideas[1][:300]}\n3: {ideas[2][:300]}\nCompare.", 0.3)
            result = await ask(client, CHAT, f"{C00}\nTask: {task}\n1: {ideas[0][:400]}\n2: {ideas[1][:400]}\n3: {ideas[2][:400]}\nCritique: {critic[:400]}\n\nSynthesize.", 0.4)
            result += f"\n\n## Critique\n{critic}"
        else:
            raise HTTPException(400, f"Unknown: {mode}")
    
    return {"result": result, "mode": mode, "time_ms": int((time.time()-t0)*1000)}
