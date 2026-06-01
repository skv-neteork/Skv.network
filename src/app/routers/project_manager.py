"""Project Manager — session memory, task tracking, interactive dialogue."""
import uuid
from datetime import datetime
from typing import Dict, List, Optional

_projects: Dict[str, dict] = {}

def create_project(query: str) -> dict:
    pid = str(uuid.uuid4())[:8]
    project = {
        "id": pid,
        "query": query,
        "created": datetime.now().isoformat(),
        "history": [{"role": "user", "content": query, "time": datetime.now().isoformat()}],
        "tasks": [],
        "answers": {},
        "status": "new"
    }
    _projects[pid] = project
    return project

def get_project(pid: str) -> Optional[dict]:
    return _projects.get(pid)

def add_message(project: dict, role: str, content: str):
    project["history"].append({"role": role, "content": content[:1000], "time": datetime.now().isoformat()})

def add_task(project: dict, description: str, task_type: str = "general", depends_on: List[str] = None) -> dict:
    task = {
        "id": f"t{len(project['tasks'])+1}",
        "description": description,
        "type": task_type,
        "status": "pending",
        "depends_on": depends_on or [],
        "result": None,
        "created": datetime.now().isoformat()
    }
    project["tasks"].append(task)
    return task

def get_pending_tasks(project: dict) -> List[dict]:
    completed = {t["id"] for t in project["tasks"] if t["status"] == "completed"}
    return [t for t in project["tasks"] if t["status"] == "pending" and all(d in completed for d in t["depends_on"])]

def get_context(project: dict, last_n: int = 5) -> str:
    messages = project["history"][-last_n:]
    return "\n".join([f"{m['role']}: {m['content'][:500]}" for m in messages])

def get_status(project: dict) -> str:
    total = len(project["tasks"])
    done = sum(1 for t in project["tasks"] if t["status"] == "completed")
    progress = sum(1 for t in project["tasks"] if t["status"] == "in_progress")
    pending = sum(1 for t in project["tasks"] if t["status"] == "pending")
    return f"Tasks: {total} total | {done} done | {progress} in progress | {pending} pending"
