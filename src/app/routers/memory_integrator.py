"""Memory Integrator — saves Critic results to Memory Pyramid (L1→L2→Cubes)."""
import httpx, time, json

SKV_API = "https://skv.network/api/v1/entries"

async def save_to_memory(task_id: str, user_id: str, project_ref: str,
                         variants: list, critic_verdict: dict,
                         sandbox_results: dict = None) -> dict:
    """Save Critic results to SKV Memory Pyramid."""
    
    # L1: Key Moments
    key_moments = []
    selected = critic_verdict.get("selected_variant", "?")
    key_moments.append({"anchor": f"task_{task_id}_selection", "insight": f"Selected {selected}: {critic_verdict.get('reason', '')}"})
    
    if sandbox_results:
        key_moments.append({"anchor": f"task_{task_id}_sandbox", "insight": f"Sandbox: {sandbox_results.get('status', '?')} after {sandbox_results.get('iterations', 0)} iter"})
    
    # L2: Core Insights
    core_insights = []
    scores = critic_verdict.get("scores", {})
    best_score = max(scores.values()) if scores else 0
    if best_score >= 7:
        core_insights.append({"insight": f"High-quality solution (score {best_score}). Pattern: sandbox + critic = reliable.", "tags": ["quality", "sandbox"]})
    
    # Cubes
    cubes = []
    if core_insights:
        cubes.append({
            "cube_id": f"cube_bureau_{task_id[:16]}",
            "type": "experience", "priority": 3, "version": "1.0.0",
            "title": f"Bureau pattern: {critic_verdict.get('category', 'general')}",
            "trigger_intent": ["bureau", "critic", "sandbox"],
            "rules": [f"MUST run sandbox after Flash", f"MUST select variant with score >= 7"],
            "rationale": f"Extracted from task {task_id}. Best variant scored {best_score}/10.",
            "source": f"Bureau (user: {user_id})", "status": "community"
        })
    
    entry = {
        "title": f"Bureau Task {task_id}",
        "type": "project_anketa",
        "persona": {"user_id": user_id, "traits": ["bureau_director"]},
        "project": {"name": project_ref, "description": f"Task {task_id}"},
        "memory_index": {"project": project_ref, "session_number": task_id, "key_outcome": f"Selected {selected} (score {best_score})"},
        "key_moments": key_moments,
        "core_insights": core_insights,
        "cubes": cubes,
        "links": {"direct": {"based_on": project_ref}}
    }
    
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(SKV_API, json=entry, headers={"Content-Type": "application/json"})
        print(f"[MEMORY] Saved task {task_id} for user {user_id}", flush=True)
    except Exception as e:
        print(f"[MEMORY] Save failed: {e}", flush=True)
    
    return {"saved": True}

async def get_user_context(user_id: str, query: str) -> dict:
    """Pull relevant cubes and patterns for user."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://skv.network/api/cubes/search?query={query[:50]}&limit=5")
            return {"cubes": r.json() if r.status_code == 200 else []}
    except:
        return {"cubes": []}
