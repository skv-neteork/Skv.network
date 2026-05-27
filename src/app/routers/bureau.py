import json, asyncio, time
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()
PKEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
FLASH = "deepseek/deepseek-v4-flash"
CHAT = "deepseek/deepseek-chat"
POLZA = "https://api.polza.ai/v1/chat/completions"

async def ask(client, model, prompt, temp=0.7, max_tok=2000):
    r = await client.post(POLZA,
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp, "max_tokens": max_tok},
        headers={"Authorization": f"Bearer {PKEY}"}, timeout=60)
    return r.json()["choices"][0]["message"]["content"].strip()

@router.post("/api/bureau/project")
async def create_project(payload: dict):
    goal = (payload.get("goal") or "").strip()
    constraints = payload.get("constraints", "")
    if not goal: raise HTTPException(400, "Goal is required")
    
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        # Chief Designer: analysis + decomposition
        cd_prompt = f"You are Chief Designer of SKV Bureau. Goal: {goal}\nConstraints: {constraints}\n\n1. Analyze the goal\n2. Decompose into 3-5 subtasks\n3. Return JSON: {{\"analysis\":\"...\",\"subtasks\":[{{\"title\":\"...\",\"spec\":\"...\",\"mode\":\"code|design|research\"}}]}}"
        
        result = await ask(client, CHAT, cd_prompt, 0.4)
        try:
            data = json.loads(result.strip().split("```json")[-1].split("```")[0].strip())
        except:
            data = {"analysis": result[:500], "subtasks": []}
    
    return {
        "project_id": f"project_{int(time.time())}",
        "goal": goal,
        "analysis": data.get("analysis", "")[:500],
        "subtasks": data.get("subtasks", [])[:5],
        "time_ms": int((time.time()-t0)*1000)
    }
