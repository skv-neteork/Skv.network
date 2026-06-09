"""Trials System v4.0 — Community-driven cube quality control."""

from fastapi import APIRouter, HTTPException
import json, time, os
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v4/trials", tags=["trials"])

# Хранилище голосов
VOTES_FILE = "/app/app/runtime/trials_votes.json"

def load_votes():
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE) as f:
            return json.load(f)
    return {}

def save_votes(votes):
    os.makedirs(os.path.dirname(VOTES_FILE), exist_ok=True)
    with open(VOTES_FILE, 'w') as f:
        json.dump(votes, f)

@router.post("/vote")
async def vote_cube(request: dict):
    """Проголосовать за/против куба."""
    cube_id = request.get("cube_id", "")
    user_id = request.get("user_id", "anonymous")
    vote = request.get("vote", "up")  # up или down
    comment = request.get("comment", "")
    
    if vote not in ["up", "down"]:
        raise HTTPException(status_code=400, detail="Vote must be 'up' or 'down'")
    
    votes = load_votes()
    
    if cube_id not in votes:
        votes[cube_id] = {"up": [], "down": [], "comments": []}
    
    votes[cube_id][vote].append(user_id)
    if comment:
        votes[cube_id]["comments"].append({"user": user_id, "comment": comment, "time": time.time()})
    
    # Проверяем порог для Trial (3 downvotes от разных пользователей)
    down_voters = list(set(votes[cube_id]["down"]))
    up_voters = list(set(votes[cube_id]["up"]))
    
    status = "active"
    if len(down_voters) >= 3:
        status = "pending_trial"
    
    votes[cube_id]["status"] = status
    votes[cube_id]["down_count"] = len(down_voters)
    votes[cube_id]["up_count"] = len(up_voters)
    
    save_votes(votes)
    
    return {
        "cube_id": cube_id,
        "status": status,
        "down_count": len(down_voters),
        "up_count": len(up_voters)
    }

@router.get("/status/{cube_id}")
async def cube_status(cube_id: str):
    """Получить статус куба."""
    votes = load_votes()
    if cube_id not in votes:
        return {"cube_id": cube_id, "status": "clean", "down_count": 0, "up_count": 0}
    return {"cube_id": cube_id, **votes[cube_id]}

@router.get("/pending")
async def pending_trials():
    """Список кубов ожидающих Trial (3+ downvotes)."""
    votes = load_votes()
    pending = []
    for cube_id, data in votes.items():
        if data.get("status") == "pending_trial":
            pending.append({"cube_id": cube_id, "down_count": data["down_count"]})
    return {"pending_trials": pending, "total": len(pending)}
