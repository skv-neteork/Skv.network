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
        # Wrap user code with timing
        wrapped = f"import time as _t\n_t0=_t.perf_counter()\n{req.code}\n_t1=_t.perf_counter()\nprint('\\n__SKV_TIME__='+str((_t1-_t0)*1000))"
        
        t_start = time.time()
        output = client.containers.run(
            "python:3.11-slim",
            command=["python", "-c", wrapped],
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
        total_time = (time.time() - t_start) * 1000
        output_str = output.decode("utf-8").strip()
        
        # Extract code time
        code_time = 0
        if "__SKV_TIME__=" in output_str:
            try:
                parts = output_str.rsplit("__SKV_TIME__=", 1)
                output_str = parts[0].strip()
                code_time = float(parts[1].strip())
            except:
                pass
        
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
                "execution_time_ms": round(code_time, 2),
                "total_time_ms": round(total_time, 2),
                "lines": lines,
                "size_bytes": size_bytes,
                "has_error_handling": has_error_handling,
                "has_type_hints": has_type_hints,
                "complexity": complexity,
                "score": round(100 - total_time/10 - lines*2 + (10 if has_error_handling else 0) + (10 if has_type_hints else 0), 1)
            }
        }
    except docker.errors.APIError as e:
        if "Timeout" in str(e) or "deadline" in str(e).lower():
            return {"status": "timeout", "stdout": "", "stderr": f"Timeout {req.timeout}s", "exit_code": -1}
        return {"status": "error", "stdout": "", "stderr": str(e), "exit_code": -1}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(500, detail="Sandbox internal error")
