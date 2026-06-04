"""Pyramid Engine — iterative 3-agent + critic loop"""
import asyncio
import httpx
import json
import time
import logging
import re

logger = logging.getLogger("skv.pyramid")

POLZA_API = "https://api.polza.ai/v1/chat/completions"
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
FLASH_MODEL = "deepseek/deepseek-v4-flash"
CRITIC_MODEL = "deepseek/deepseek-chat"

SYSTEM_FLASH = "You are a specialized AI agent in the SKV Pyramid. Follow your role strictly. Be concise."

PROMPT_F1_CREATIVE = """You are the CREATIVE agent. Your goal is to solve the problem by finding ANALOGIES to known systems.
If you encounter an unknown symbol or concept, find a known analog and infer properties from it.
Propose unconventional approaches. Be bold."""

PROMPT_F2_LOGIC = """You are the LOGIC & BOUNDARY agent. Your goal is to stress-test analogies and assumptions.
Where does the analogy break? What properties do NOT transfer?
Find counterexamples, edge cases, or singularities. Be rigorous."""

PROMPT_F3_SIMPLE = """You are the FIRST PRINCIPLES agent. Ignore analogies. Solve directly using base physics, math, dimensional analysis, or known formulas.
Be rigorous, literal, and mathematically exact."""

PROMPT_CRITIC = """You are the ORCHESTRATOR. You receive 3 perspectives: Creative (analogies), Logic (boundaries), and Simple (first principles).
Compare them. Identify agreements and disagreements.
CRITICAL: If Creative conflicts with Simple — ALWAYS trust Simple.
Decide if the solution is complete.

Return ONLY valid JSON:
{"satisfied": true/false, "consensus": "...", "guidance": "...", "keep": [...], "next_iteration": true/false}"""


async def call_llm(model: str, prompt: str, system: str = "", max_tokens: int = 1500) -> str:
    """Each call creates its own client — no shared state issues."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(POLZA_API,
                    json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens},
                    headers={"Authorization": f"Bearer {POLZA_KEY}"})
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"LLM call failed ({model}): {e}")
            if attempt == 2:
                return f"ERROR: {e}"
            await asyncio.sleep(2)
    return "ERROR: all retries failed"



class VetoError(Exception):
    """Critical algorithmic flaw detected."""
    pass

def validate_agent_response(response, agent_name):
    """Check for common issues before Critic evaluation."""
    issues = []
    
    # Check for stubs
    stubs = ['TODO', 'pass', '...', 'script from above', 'implement later']
    for stub in stubs:
        if stub in response:
            issues.append(f"STUB: found '{stub}'")
    
    # Check for Python syntax errors in code blocks
    import re
    code_blocks = re.findall(r'```python\s*\n(.*?)```', response, re.DOTALL)
    for i, code in enumerate(code_blocks):
        try:
            compile(code, f'<{agent_name}_block_{i}>', 'exec')
        except SyntaxError as e:
            issues.append(f"SYNTAX: {str(e)[:100]}")
    
    # Compute completeness score
    completeness = 1.0
    if issues:
        completeness = max(0.0, 1.0 - len(issues) * 0.2)
    
    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'completeness': completeness,
        'stability': 1.0 if len(issues) == 0 else 0.5
    }


async def run_pyramid(task: str, max_iterations: int = 5) -> dict:
    """Run iterative pyramid: 3 Flash agents + Critic loop"""
    start_time = time.time()
    logs = []
    iteration_context = task

    for i in range(max_iterations):
        logger.info(f"Pyramid Iteration {i+1}/{max_iterations}")
        logs.append(f"--- Iteration {i+1} ---")

        f1_prompt = f"{PROMPT_F1_CREATIVE}\n\nCONTEXT:\n{iteration_context}"
        f2_prompt = f"{PROMPT_F2_LOGIC}\n\nCONTEXT:\n{iteration_context}"
        f3_prompt = f"{PROMPT_F3_SIMPLE}\n\nCONTEXT:\n{iteration_context}"

        # All 3 calls happen in parallel, each with its own client
        f1_res, f2_res, f3_res = await asyncio.gather(
            call_llm(FLASH_MODEL, f1_prompt, SYSTEM_FLASH),
            call_llm(FLASH_MODEL, f2_prompt, SYSTEM_FLASH),
            call_llm(FLASH_MODEL, f3_prompt, SYSTEM_FLASH)
        )

        logs.append(f"F1 (Creative): {f1_res[:200]}")
        logs.append(f"F2 (Logic): {f2_res[:200]}")
        logs.append(f"F3 (Simple): {f3_res[:200]}")

        # Validate agents before Critic
        f1_check = validate_agent_response(f1_res, "Creative")
        f2_check = validate_agent_response(f2_res, "Logic")
        f3_check = validate_agent_response(f3_res, "Simple")
        
        all_valid = f1_check['valid'] and f2_check['valid'] and f3_check['valid']
        if not all_valid:
            issues = []
            if not f1_check['valid']: issues.extend(f1_check['issues'])
            if not f2_check['valid']: issues.extend(f2_check['issues'])
            if not f3_check['valid']: issues.extend(f3_check['issues'])
            print(f"[CRITIC] Issues: {issues}", flush=True)
        
        # Critic evaluation
        f1_sb = "PASS" if has_code(f1_res) and "PASS" in str(f1_res) else ("NO CODE" if not has_code(f1_res) else "FAIL")
        f2_sb = "PASS" if has_code(f2_res) and "PASS" in str(f2_res) else ("NO CODE" if not has_code(f2_res) else "FAIL")
        f3_sb = "PASS" if has_code(f3_res) and "PASS" in str(f3_res) else ("NO CODE" if not has_code(f3_res) else "FAIL")
        critic_prompt = f"""{PROMPT_CRITIC}

CREATIVE AGENT (sandbox: {f1_sb}):
{f1_res}

LOGIC AGENT (sandbox: {f2_sb}):
{f2_res}

SIMPLE AGENT (sandbox: {f3_sb}):
{f3_res}

ORIGINAL TASK: {task}"""

        critic_raw = await call_llm(CRITIC_MODEL, critic_prompt,
            "You are the SKV Orchestrator. Output ONLY JSON.", max_tokens=1000)

        # Parse critic JSON
        critic_json = {"satisfied": False, "guidance": critic_raw, "next_iteration": True}
        try:
            match = re.search(r'\{[\s\S]*\}', critic_raw)
            if match:
                critic_json = json.loads(match.group(0))
        except:
            pass

        logs.append(f"Critic: satisfied={critic_json.get('satisfied')}, guidance={critic_json.get('guidance', '')[:200]}")

        all_failed = all(sb == "FAIL" for sb in [f1_sb, f2_sb, f3_sb])
        if all_failed:
            critic_json["satisfied"] = False
            critic_json["next_iteration"] = True
            critic_json["guidance"] = "ALL agents failed sandbox! Fix imports, syntax, decorators."
        if critic_json.get("satisfied") or not critic_json.get("next_iteration", True):
            logger.info("Critic satisfied. Generating final answer.")
            break

        # Update context for next iteration
        keep_parts = "\n".join(critic_json.get("keep", []))
        iteration_context = f"{task}\n\n[Iteration {i+1} Guidance]: {critic_json.get('guidance', '')}\n[Parts to keep]: {keep_parts}"

        await asyncio.sleep(1.0)

    # Final synthesis
    final_prompt = f"""You are the Final Synthesizer.
Based on the task, 3 agent perspectives, and orchestrator guidance, write the FINAL, complete, rigorous answer.

TASK: {task}
CREATIVE: {f1_res}
LOGIC: {f2_res}
SIMPLE: {f3_res}
ORCHESTRATOR: {critic_json.get('guidance', '')}
KEEP: {critic_json.get('keep', [])}

Write the definitive answer. Include formulas, dimensional analysis, and physical interpretation where relevant."""

    final_answer = await call_llm(CRITIC_MODEL, final_prompt,
        "You are the final answer generator. Be rigorous and precise.", max_tokens=2500)

    elapsed = time.time() - start_time
    logger.info(f"Pyramid finished in {elapsed:.2f}s after {i+1} iterations.")

    return {
        "answer": final_answer,
        "iterations": i + 1,
        "time_ms": int(elapsed * 1000),
        "logs": logs,
        "critic_final": critic_json
    }
