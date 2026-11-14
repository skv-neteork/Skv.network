"""T73: GET /api/v7/const/metrics: the caller's own constitution-binding counters per day (read-only)."""
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v7", tags=["constitution"])


@router.get("/const/metrics")
def const_metrics(request: Request, days: int = 7):
    from app.chain_skills import chain_from_request
    uid = chain_from_request(request)[0]
    if not uid:
        raise HTTPException(status_code=401, detail="API key required")
    from app import const_bind as cb
    reg = cb.registry()
    return {"ok": True, "user": uid, "enabled": cb.enabled(), "constitution": {"v": reg["v"], "hash": reg["hash"], "atoms": reg["n"], "drift": reg["drift"]},
            "stale_now": cb.is_stale(uid), "days": cb.metrics(uid, days),
            "keys": {"turns": "turns with the heartbeat", "manifest_shown": "manifests shown", "manifest_acked": "acknowledged (const_ack / ack=const)",
                     "escalations": "MANDATORY escalations", "gate_triggers": "irreversible calls held for the manifest", "gate_acks": "held calls repeated with ack=const",
                     "drive_put_invalid_path": "drive_put path rejected", "turns_no_seal": "turn with a draft but no seal (revise)", "missed_turns": "missed_turns duty shown"}}
