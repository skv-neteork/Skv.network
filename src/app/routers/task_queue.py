from fastapi import APIRouter, Request
import uuid
from datetime import datetime

router = APIRouter()

_tasks = {}

@router.post("/api/queue/consult")
async def queue_consult(request: Request):
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {"status": "queued", "created_at": datetime.utcnow().isoformat()}
    return {"status": "queued", "task_id": task_id}

@router.get("/api/queue/status/{task_id}")
async def queue_status_check(task_id: str):
    task = _tasks.get(task_id, {"status": "unknown"})
    return task

@router.post("/api/queue/tools")
async def queue_tools(request: Request):
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {"status": "queued", "created_at": datetime.utcnow().isoformat()}
    return {"status": "queued", "task_id": task_id}
