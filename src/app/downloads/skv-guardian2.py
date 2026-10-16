#!/usr/bin/env python3
"""SKV Guardian 2. Runs on the user machine, between their model and SKV.

The server guardian only flags a missed save. This one does the steps:
search, open, draft, Second Look, save. A failed check is not shown.
Keys stay in this process.
"""
import json, os, urllib.request

SKV = os.environ.get("SKV_URL", "https://skv.network")
SKV_KEY = os.environ.get("SKV_KEY", "")
LLM_URL = os.environ.get("LLM_URL", "https://api.polza.ai/v1/chat/completions")
LLM_KEY = os.environ.get("LLM_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat")

def _post(path, payload, auth=True):
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if auth and SKV_KEY:
        headers["Authorization"] = "Bearer " + SKV_KEY
    req = urllib.request.Request(SKV + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())

def _model(prompt):
    body = json.dumps({"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}).encode()
    req = urllib.request.Request(LLM_URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_KEY})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())["choices"][0]["message"]["content"]

def ask(user_id, message):
    found = _post("/api/v7/agent/run", {"user_id": user_id, "task": message})
    center = (found.get("center") or {})
    event_id = center.get("event_id") or ""
    span = found.get("span") or 0
    prompt = (
        "Answer only from this opened turn. Cite the event id. "
        "If status is not_found, say you do not know.\n"
        + json.dumps(found, ensure_ascii=False)[:2000]
        + "\nUser: " + message
    )
    draft = _model(prompt)
    look = _post("/api/v7/agent/second-look", {"user_id": user_id, "draft": draft, "event_id": event_id, "span": span})
    if look.get("status") != "pass":
        draft = _model(prompt + "\nFailed checks: " + json.dumps(look.get("checks"), ensure_ascii=False) + "\nFix and cite " + event_id)
        look = _post("/api/v7/agent/second-look", {"user_id": user_id, "draft": draft, "event_id": event_id, "span": span})
    if "L1" not in draft or "CRITICAL" not in draft:
        draft = _model(prompt + "\nВ конце добавь строку L1: выжимку и строку CRITICAL: важное или none.")
    l1 = ""
    for line in draft.splitlines():
        if line.strip().lstrip("*").startswith("L1"):
            l1 = line.split(":", 1)[-1].strip()[:500]
            break
    if not l1:
        return {"status": "held", "checks": [{"name": "l1", "ok": False, "note": "agent did not write L1"}], "draft": draft}
    if "CUBE:" not in draft and "CUBE_NOTHING" not in draft:
        draft = _model(prompt + "\nДобавь CUBE: тема | суть | правило или CUBE_NOTHING.")
    if "CUBE:" in draft:
        line = [x for x in draft.splitlines() if "CUBE:" in x][-1].split("CUBE:",1)[1]
        parts = [x.strip() for x in line.split("|")]
        if len(parts) >= 3:
            _post("/api/v7/experience/create", {"topic": parts[0][:80], "essence": parts[1][:200], "rules_markdown": parts[2][:500], "evidence": event_id})
    _post("/api/v7/remember", {"user_id": user_id, "query": message, "response": draft, "l1_summary": l1, "duty": "cube" if "CUBE:" in draft else "cube_nothing"})
    if look.get("status") != "pass":
        return {"status": "held", "checks": look.get("checks"), "draft": draft}
    return {"status": "pass", "answer": draft, "event_id": event_id, "span": span}

if __name__ == "__main__":
    import sys
    user = sys.argv[1]
    text = " ".join(sys.argv[2:])
    print(json.dumps(ask(user, text), ensure_ascii=False, indent=2))
