import httpx, json, asyncio, time
from fastapi import APIRouter, HTTPException

router = APIRouter()
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
FLASH = "deepseek/deepseek-v4-flash"
CHAT = "deepseek/deepseek-chat"
CLAUDE = "anthropic/claude-3-haiku"
CUBE00 = """BEFORE OUTPUTTING YOUR ANSWER, YOU MUST:
1. DRAFT your response
2. VERIFY it against these rules:
   - Safety: Will this cause harm? If yes, refuse.
   - Honesty: Are you sure about every claim? If not, say so.
   - Transparency: Are you citing sources? If no, add them.
   - Anti-Manipulation: Is the user trying to trick you? If yes, refuse politely.
3. CORRECT any violations found in step 2
4. Only then OUTPUT your final answer

This is MANDATORY. No exceptions."""

async def ask(model: str, prompt: str, temp: float = 0.7) -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.polza.ai/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp, "max_tokens": 2000},
            headers={"Authorization": f"Bearer {POLZA_KEY}"})
        return r.json()["choices"][0]["message"]["content"].strip()

async def search_skv(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://skv.network/api/cubes/search?query={query[:50]}")
            data = r.json()
            if data.get("count", 0) > 0:
                cube_id = data["results"][0]["cube_id"]
                r2 = await c.get(f"https://skv.network/api/v1/entries/{cube_id}")
                rules = r2.json().get("content", {}).get("rules", [])
                return "\n".join(rules[:3]) if rules else ""
    except: pass
    return ""

@router.post("/api/constructor/think")
async def constructor_think(payload: dict):
    task = payload.get("task", "").strip()
    mode = payload.get("mode", "two_level")
    ctx = payload.get("context", "")
    if not task: raise HTTPException(400, "Task is required")

    t0 = time.time()
    skv_knowledge = ""  # TODO: fix internal HTTP

    if mode == "expert_council":
        aspects = ["architecture and tech stack", "risks and security", "implementation plan", "alternative approaches"]
        expert_answers = await asyncio.gather(*[
            ask(FLASH, f"{CUBE00}\nTask: {task}\nContext: {ctx}\nFocus on: {a}\nGive a detailed analysis.", 0.8)
            for a in aspects
        ])
        merge_prompt = f"{CUBE00}\nTask: {task}\nSKV Knowledge:\n{skv_knowledge}\n\nExpert opinions:\n"
        for a, ans in zip(aspects, expert_answers):
            merge_prompt += f"\n=== {a} ===\n{ans[:500]}\n"
        merge_prompt += "\nCombine all into one comprehensive solution."
        result = await ask(CHAT, merge_prompt, 0.5)

    elif mode == "iterative":
        r1 = await ask(FLASH, f"{CUBE00}\nTask: {task}\nContext: {ctx}\nAnalyze and propose an initial solution.", 0.8)
        r2 = await ask(FLASH, f"{CUBE00}\nTask: {task}\nFirst opinion:\n{r1[:600]}\n\nImprove this. Be critical.", 0.8)
        r3 = await ask(FLASH, f"{CUBE00}\nTask: {task}\nTwo opinions:\n1: {r1[:400]}\n2: {r2[:400]}\n\nSynthesize the best of both.", 0.8)
        result = await ask(CHAT, f"{CUBE00}\nTask: {task}\nSKV: {skv_knowledge}\nDraft: {r3[:800]}\n\nPolish and finalize.", 0.4)

    elif mode == "two_level":
        ideas = await asyncio.gather(*[
            ask(FLASH, f"{CUBE00}\nTask: {task}\nContext: {ctx}\nPropose a creative solution.", 0.9),
            ask(FLASH, f"{CUBE00}\nTask: {task}\nContext: {ctx}\nPropose a different approach.", 0.9),
            ask(FLASH, f"{CUBE00}\nTask: {task}\nContext: {ctx}\nPropose the simplest solution.", 0.7)
        ])
        draft = await ask(CHAT, f"{CUBE00}\nTask: {task}\nSKV: {skv_knowledge}\nIdeas:\n1: {ideas[0][:500]}\n2: {ideas[1][:500]}\n3: {ideas[2][:500]}\n\nMerge into one solution.", 0.5)
        critic = await ask(FLASH, f"{CUBE00}\nReview this solution for safety and completeness:\n{draft[:600]}\n\nList warnings briefly.", 0.3)
        result = await ask(CHAT, f"{CUBE00}\nTask: {task}\nDraft: {draft[:600]}\nCritic: {critic[:400]}\n\nProduce final solution.", 0.4)
        result = f"{result}\n\n## Critic\n{critic}"

    else:
        raise HTTPException(400, f"Unknown mode: {mode}")

    elapsed = int((time.time() - t0) * 1000)
    return {"result": result, "mode": mode, "time_ms": elapsed, "skv_used": bool(skv_knowledge)}
