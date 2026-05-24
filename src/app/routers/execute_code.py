from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter()
SANDBOX_URL = "http://172.19.0.8:8000"

@router.post("/api/execute/code")
async def execute_code(payload: dict):
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{SANDBOX_URL}/run",
                json={
                    "language": payload.get("language", "python"),
                    "code": payload.get("code", ""),
                    "timeout": min(payload.get("timeout", 10), 15),
                    "memory_mb": min(payload.get("memory_mb", 128), 256)
                },
                timeout=20.0
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            raise HTTPException(408, "Sandbox execution timed out")
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
