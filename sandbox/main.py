from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import docker
import logging

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
            timeout=req.timeout,
            remove=True
        )
        return {
            "status": "success",
            "stdout": output.decode("utf-8").strip(),
            "stderr": "",
            "exit_code": 0
        }
    except docker.errors.APIError as e:
        if "Timeout" in str(e) or "deadline" in str(e).lower():
            return {"status": "timeout", "stdout": "", "stderr": f"Execution exceeded {req.timeout}s", "exit_code": -1}
        return {"status": "error", "stdout": "", "stderr": str(e), "exit_code": -1}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(500, detail="Sandbox internal error")
