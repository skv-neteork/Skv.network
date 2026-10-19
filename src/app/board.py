"""Per-account pinned board: tasks, resources ([vault:name] refs only), notes.
Sent with /memory recall on the first recall of a session, every board_every recalls, and whenever it changed.
Config (memory_config.json): board_enabled (true), board_tokens (500), board_every (10)."""
import hashlib, re, uuid
from app import shelves as _sh

KINDS = ("task", "resource", "note")
STATUSES = ("open", "in_progress", "blocked", "done", "closed")
ACTIONS = ("add", "edit", "done", "undo", "progress", "block", "important", "unimportant", "remove")
HINT = 'Edit: POST /api/v7/board {"id":"T01","action":"add|edit|done|undo|progress|block|important|unimportant|remove","text":"Title: details"}. Secrets only as [vault:name].'


def _conn(uid):
    c = _sh.connect(uid)
    c.execute("CREATE TABLE IF NOT EXISTS board_items (item_id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, status TEXT, updated_at TEXT, removed INTEGER DEFAULT 0, important INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS board_state (id INTEGER PRIMARY KEY CHECK (id=1), session TEXT, recalls INTEGER, last_sent INTEGER, hash TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS board_history (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, action TEXT, text TEXT, ts TEXT)")
    return c


def _scrub(uid, text):
    try:
        from app import vault
        if vault.available():
            return vault.scrub(uid, text)[0]
    except Exception as e:
        print(f"[board] scrub skipped: {e}", flush=True)
    return text


def items(uid, include_closed=False):
    c = _conn(uid)
    try:
        rows = c.execute("SELECT item_id, kind, title, body, status, updated_at, important FROM board_items WHERE removed=0 ORDER BY important DESC, item_id").fetchall()
    finally:
        c.close()
    out = [dict(zip(("item_id", "kind", "title", "body", "status", "updated_at", "important"), r)) for r in rows]
    return out if include_closed else [i for i in out if i["status"] not in ("done", "closed")]


def history(uid, limit=30):
    c = _conn(uid)
    try:
        return [dict(zip(("item_id", "action", "text", "ts"), r)) for r in
                c.execute("SELECT item_id, action, text, ts FROM board_history ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        c.close()


def act(uid, item_id="", action="add", text="", kind="", title=""):
    action = (action or "add").lower()
    if action not in ACTIONS:
        raise ValueError("action: " + "|".join(ACTIONS))
    item_id = re.sub(r"[^A-Za-z0-9_.-]", "", item_id or "")[:40]
    text = _scrub(uid, (text or "")[:2000]); title = _scrub(uid, (title or "")[:200])
    if not title and ":" in text[:120]:
        title, text = [x.strip() for x in text.split(":", 1)]
    c = _conn(uid)
    try:
        row = c.execute("SELECT kind, title, body FROM board_items WHERE item_id=? AND removed=0", (item_id,)).fetchone() if item_id else None
        if action == "add" or (action == "edit" and not row):
            kind = kind if kind in KINDS else ("task" if re.match(r"^T\d", item_id) else "note")
            item_id = item_id or (kind[0] + "_" + uuid.uuid4().hex[:8])
            c.execute("INSERT OR REPLACE INTO board_items (item_id, kind, title, body, status, updated_at, removed, important) VALUES (?,?,?,?,?,datetime('now'),0,0)",
                      (item_id, kind, title or text[:80], text if title else "", "open" if kind == "task" else ""))
        else:
            if not row:
                raise KeyError(item_id or "id required")
            if action == "edit":
                c.execute("UPDATE board_items SET title=?, body=?, kind=?, updated_at=datetime('now') WHERE item_id=?",
                          (title or row[1], text if (title or text) else row[2], kind if kind in KINDS else row[0], item_id))
            elif action == "remove":
                c.execute("UPDATE board_items SET removed=1, updated_at=datetime('now') WHERE item_id=?", (item_id,))
            else:
                col, val = {"done": ("status", "done"), "undo": ("status", "open"), "progress": ("status", "in_progress"),
                            "block": ("status", "blocked"), "important": ("important", 1), "unimportant": ("important", 0)}[action]
                c.execute(f"UPDATE board_items SET {col}=?, updated_at=datetime('now') WHERE item_id=?", (val, item_id))
                if text or title:
                    c.execute("UPDATE board_items SET body=coalesce(body,'')||? WHERE item_id=?", (" | " + (title + ": " if title else "") + text, item_id))
        c.execute("INSERT INTO board_history (item_id, action, text, ts) VALUES (?,?,?,datetime('now'))", (item_id, action, ((title + ": ") if title else "") + text[:300]))
        c.execute("DELETE FROM board_history WHERE id NOT IN (SELECT id FROM board_history ORDER BY id DESC LIMIT 200)")
        c.commit()
    finally:
        c.close()
    return {"id": item_id, "action": action}


def render(uid, tokens=500):
    allit = items(uid, include_closed=True)
    if not allit:
        return ""
    done = [i for i in allit if i["status"] in ("done", "closed")][-5:]
    it = [i for i in allit if i not in done]
    lines = [HINT]
    for k, head in (("task", "TASKS"), ("resource", "RESOURCES"), ("note", "NOTES")):
        sel = [i for i in it if i["kind"] == k]
        if sel:
            lines.append(head + ":")
            for i in sel:
                st = (" !" if i["important"] else "") + (f" [{i['status']}]" if i["status"] else "")
                b = (i["body"] or "").replace("\n", " ")
                lines.append(f"- {i['item_id']}{st} {i['title']}" + (f": {b[:200]}" if b else ""))
    if done:
        lines.append("DONE: " + "; ".join(f"~~{i['item_id']} {i['title'][:50]}~~" for i in done))
    s = "\n".join(lines)
    lim = tokens * 4
    return s if len(s) <= lim else s[:lim].rsplit("\n", 1)[0] + "\n...(clipped; GET /api/v7/board for all)"


def for_recall(uid, session, cfg):
    if not cfg.get("board_enabled", True):
        return ""
    every = int(cfg.get("board_every", 10) or 10)
    text = render(uid, int(cfg.get("board_tokens", 500) or 500))
    h = hashlib.sha1(text.encode()).hexdigest()[:16]
    c = _conn(uid)
    try:
        sess, recalls, last, oldh = c.execute("SELECT session, recalls, last_sent, hash FROM board_state WHERE id=1").fetchone() or (None, 0, None, None)
        recalls = (recalls or 0) + 1
        due = bool(text) and (sess != session or last is None or recalls - last >= every or h != oldh)
        c.execute("INSERT OR REPLACE INTO board_state (id, session, recalls, last_sent, hash) VALUES (1,?,?,?,?)",
                  (session, recalls, recalls if due else last, h if due else oldh))
        c.commit()
    finally:
        c.close()
    return text if due else ""
