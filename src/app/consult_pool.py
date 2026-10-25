"""Paid consultation. Two external agents, one task, nothing runs by itself."""
import json, os, sqlite3, time, urllib.request

POLZA = "https://api.polza.ai/v1/chat/completions"
CONSULTANTS = (
    ("claude", "anthropic/claude-sonnet-4.6"),
    ("gpt", "openai/gpt-4o"),
)
PROMPT = (
    "You are one of two independent consultants. You see only this task. "
    "No tools, no memory, no secrets. Give concrete advice: what to do, "
    "what to avoid, and the one check that proves it worked. Be short."
)


def _db(user_id):
    from app.account_memory import account_db_name, ensure_user_db
    ensure_user_db(user_id)
    path = "/data/skv/metadata_store/" + account_db_name(user_id)
    c = sqlite3.connect(path, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS consult_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT, tried TEXT, failed TEXT,
        claude TEXT, gpt TEXT, status TEXT, chosen TEXT, as_kind TEXT,
        created_at TEXT)""")
    return c


def _key():
    return os.environ.get("POLZA_KEY", "")


def _ask(model, task, tried, failed):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": "Task: %s\nTried: %s\nFailed: %s" % (task, tried or "-", failed or "-")},
        ],
        "max_tokens": 700,
    }).encode()
    req = urllib.request.Request(POLZA, data=body, headers={
        "Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    return data["choices"][0]["message"]["content"].strip()


def ask(user_id, task, tried="", failed="", consent=False):
    task = (task or "").strip()
    if not task:
        return {"status": "error", "reason": "task required"}
    if not consent:
        return {"status": "need_consent", "notice": "This sends the task to Claude and ChatGPT. Nothing else. Confirm to continue."}
    if not _key():
        return {"status": "error", "reason": "POLZA_KEY missing"}
    answers = {}
    for name, model in CONSULTANTS:
        try:
            answers[name] = _ask(model, task, tried, failed)
        except Exception as e:
            answers[name] = "error: " + str(e)[:160]
    c = _db(user_id)
    try:
        cur = c.execute(
            "INSERT INTO consult_pool (task, tried, failed, claude, gpt, status, created_at) VALUES (?,?,?,?,?,'open',?)",
            (task, tried, failed, answers.get("claude", ""), answers.get("gpt", ""), time.strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
        return {"status": "ok", "id": cur.lastrowid, "claude": answers.get("claude", ""), "gpt": answers.get("gpt", ""),
                "next": "accept with consult_accept, or ignore. Nothing runs by itself."}
    finally:
        c.close()


def accept(user_id, consult_id, which, as_kind="note"):
    which = (which or "").strip().lower()
    if which not in ("claude", "gpt"):
        return {"status": "error", "reason": "which is claude or gpt"}
    as_kind = "cube" if as_kind == "cube" else "note"
    c = _db(user_id)
    try:
        row = c.execute("SELECT task, claude, gpt, status FROM consult_pool WHERE id=?", (int(consult_id),)).fetchone()
        if not row:
            return {"status": "error", "reason": "not found"}
        if row[3] != "open":
            return {"status": "error", "reason": "already " + row[3]}
        text = row[1] if which == "claude" else row[2]
        c.execute("UPDATE consult_pool SET status=?, chosen=?, as_kind=? WHERE id=?", ("accepted", which, as_kind, int(consult_id)))
        c.commit()
        return {"status": "ok", "id": int(consult_id), "which": which, "as": as_kind, "task": row[0], "advice": text}
    finally:
        c.close()
