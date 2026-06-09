import os
"""Sandbox validation — runs code in Docker sandbox, auto-fix cycle."""
import re, httpx, json, time, asyncio

SANDBOX_URL = "http://172.19.0.8:8000"
MAX_SANDBOX_ITERATIONS = 5

async def validate_code_in_sandbox(code: str, expected_output: str = None, timeout: int = 30) -> dict:
    """Send Python code to sandbox, return result."""
    sandbox_payload = {"code": code, "language": "python", "timeout": timeout}
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            resp = await client.post(f"{SANDBOX_URL}/run", json=sandbox_payload)
            result = resp.json()
        elapsed_ms = int((time.time() - start) * 1000)
        if result.get("status") == "success":
            output = result.get("stdout", "")
            error = result.get("stderr", "")
            if expected_output and expected_output.strip() not in output:
                return {"success": False, "output": output, "error": f"Expected '{expected_output}' not found", "execution_time_ms": elapsed_ms}
            return {"success": True, "output": output, "error": error if error else None, "execution_time_ms": elapsed_ms}
        else:
            return {"success": False, "output": result.get("stdout", ""), "error": result.get("stderr", "Unknown error"), "execution_time_ms": elapsed_ms}
    except Exception as e:
        return {"success": False, "output": "", "error": f"Sandbox error: {str(e)}", "execution_time_ms": int((time.time() - start) * 1000)}

def extract_python_code(text: str) -> list:
    """Extract ```python ... ``` blocks from text."""
    return [m.strip() for m in re.findall(r'```python\s*\n(.*?)```', text, re.DOTALL) if m.strip()]

async def validate_with_sandbox(hypothesis_text: str, task_description: str = "") -> dict:
    """Extract code, run in sandbox, auto-fix up to 5 iterations."""
    code_blocks = extract_python_code(hypothesis_text)
    if not code_blocks:
        return {"validated": True, "reason": "No code to validate", "iterations": 0, "code_blocks": []}
    
    results = []
    for i, code in enumerate(code_blocks):
        sandbox_result = await validate_code_in_sandbox(code)
        iteration = {"block_index": i, "code": code, "attempts": [sandbox_result]}
        current_code = code
        attempt = 0
        
        while not sandbox_result["success"] and attempt < MAX_SANDBOX_ITERATIONS:
            attempt += 1
            fix_prompt = f"Fix this Python code that failed in sandbox.\nError: {sandbox_result['error']}\nOutput: {sandbox_result['output'][:500]}\n\nOriginal code:\n```python\n{current_code}\n```\nReturn ONLY the fixed code in ```python``` block."
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    fix_resp = await client.post("https://api.polza.ai/v1/chat/completions",
                        headers={"Authorization": f"Bearer " + os.environ.get("POLZA_KEY", "") + ""},
                        json={"model": "deepseek/deepseek-v4-flash", "messages": [{"role": "user", "content": fix_prompt}], "max_tokens": 2000})
                    fixed_text = fix_resp.json()["choices"][0]["message"]["content"]
                fixed_blocks = extract_python_code(fixed_text)
                if fixed_blocks:
                    current_code = fixed_blocks[0]
                    sandbox_result = await validate_code_in_sandbox(current_code)
                    iteration["attempts"].append(sandbox_result)
                else:
                    break
            except:
                break
        
        iteration["final_success"] = sandbox_result["success"]
        iteration["total_attempts"] = len(iteration["attempts"])
        results.append(iteration)
    
    all_passed = all(r["final_success"] for r in results)
    return {
        "validated": all_passed,
        "reason": "All blocks passed" if all_passed else f"{sum(1 for r in results if not r['final_success'])} blocks failed",
        "iterations": sum(r["total_attempts"] for r in results),
        "code_blocks": results
    }
