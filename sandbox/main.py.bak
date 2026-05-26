from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docker, time, logging

app = FastAPI()
client = docker.from_env()
logger = logging.getLogger("sandbox")

class CodeRequest(BaseModel):
    language: str = "python"
    code: str
    timeout: int = 10
    memory_mb: int = 128

@app.post("/run")
def run_code(req: CodeRequest):
    if req.language != "python":
        raise HTTPException(400, detail="Only python is supported currently")

    try:
        t_start = time.time()
        output = client.containers.run(
            "python:3.11-slim",
            command=["python", "-c", req.code],
            detach=False,
            network="none",
            mem_limit=f"{req.memory_mb}m",
            cpu_quota=50000,
            pids_limit=20,
            read_only=True,
            tmpfs={"/tmp": "rw,size=5m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            user="1000",
            remove=True
        )
        exec_time = (time.time() - t_start) * 1000
        output_str = output.decode("utf-8").strip()
        lines = req.code.count("\n") + 1
        has_error_handling = "try" in req.code and "except" in req.code
        has_type_hints = " -> " in req.code and "def " in req.code
        size_bytes = len(req.code.encode("utf-8"))
        complexity = "low" if lines <= 10 else ("medium" if lines <= 30 else "high")
        
        return {
            "status": "success",
            "stdout": output_str,
            "stderr": "",
            "exit_code": 0,
            "metrics": {
                "execution_time_ms": round(exec_time, 2),
                "lines": lines,
                "size_bytes": size_bytes,
                "has_error_handling": has_error_handling,
                "has_type_hints": has_type_hints,
                "complexity": complexity,
                "score": round(100 - exec_time/10 - lines*2 + (10 if has_error_handling else 0) + (10 if has_type_hints else 0), 1)
            }
        }
    except docker.errors.APIError as e:
        if "Timeout" in str(e) or "deadline" in str(e).lower():
            return {"status": "timeout", "stdout": "", "stderr": f"Timeout {req.timeout}s", "exit_code": -1}
        return {"status": "error", "stdout": "", "stderr": str(e), "exit_code": -1}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(500, detail="Sandbox internal error")
