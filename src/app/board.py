"""Per-account pinned board for agents: tasks (with subtasks), resources ([vault:name] refs only), notes.
Statuses: todo | doing | blocked | done | parked  (old open/in_progress/closed are migrated / accepted as aliases).
Fields: title, body, priority (1 high, 2 normal, 3 low), parent_id (subtask of), waiting_for (who/what blocks it,
"user" = waiting for the user), result (required for done), result_event (the turn event that closed it).
Sent with /memory recall (first recall of a session, every board_every recalls, or when it changed).
Config (memory_config.json): board_enabled (true), board_tokens (500), board_every (10)."""
import hashlib, re, uuid
from app import shelves as _sh

KINDS = ("task", "resource", "note")
STATUSES = ("todo", "doing", "blocked", "done", "parked")
OPEN = ("todo", "doing", "blocked")
_OLD_STATUS = {"open": "todo", "in_progress": "doing", "closed": "done", "": "todo"}
ACTIONS = ("add", "add_subtask", "update", "start", "block", "done", "park", "reopen", "remove", "important", "unimportant")
ALIASES = {"edit": "update", "progress": "start", "undo": "reopen", "subtask": "add_subtask", "close": "done"}
HINT = ('Board: board_act(action=add|add_subtask|update|start|block|done|park|reopen|remove, item_id, title, text, '
        'priority=1..3, parent_id, waiting_for, result). done needs result=<what was achieved>. Secrets only as [vault:name].')
_COLS = {"priority": "INTEGER DEFAULT 2", "parent_id": "TEXT DEFAULT ''", "waiting_for": "TEXT DEFAULT ''",
         "result": "TEXT DEFAULT ''", "result_event": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''"}
FIELDS = ("item_id", "kind", "title", "body", "status", "updated_at", "important", "priority", "parent_id",
          "waiting_for", "result", "result_event")


def _conn(uid):
    c = _sh.connect(uid)
    c.execute("CREATE TABLE IF NOT EXISTS board_items (item_id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, status TEXT, updated_at TEXT, removed INTEGER DEFAULT 0, important INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS board_state (id INTEGER PRIMARY KEY CHECK (id=1), session TEXT, recalls INTEGER, last_sent INTEGER, hash TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS board_history (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, action TEXT, text TEXT, ts TEXT)")
    have = {r[1] for r in c.execute("PRAGMA table_info(board_items)")}
    if not set(_COLS) <= have:   # one-time v2 migration (additive; old status values mapped, nothing deleted)
        for k, t in _COLS.items():
            if k not in have:
                c.execute(f"ALTER TABLE board_items ADD COLUMN {k} {t}")
        c.execute("UPDATE board_items SET priority=1 WHERE important=1")
        c.execute("INSERT INTO board_history (item_id, action, text, ts) VALUES ('*','migrate_v2','statuses open/in_progress/closed -> todo/doing/done',datetime('now'))")
        c.commit()
    if c.execute("SELECT 1 FROM board_items WHERE kind='task' AND (status IS NULL OR status IN ('open','in_progress','closed','')) LIMIT 1").fetchone():
        for o, n in _OLD_STATUS.items():
            c.execute("UPDATE board_items SET status=? WHERE kind='task' AND coalesce(status,'')=?", (n, o))
        c.commit()
    return c


def _scrub(uid, text):
    try:
        from app import vault
        if vault.available():
            return vault.scrub(uid, text)[0]
    except Exception as e:
        print(f"[board] scrub skipped: {e}", flush=True)
    return text


def _status(s):
    return _OLD_STATUS.get(s, s) if s in _OLD_STATUS else (s or "")


def items(uid, include_closed=False):
    c = _conn(uid)
    try:
        rows = c.execute("SELECT " + ", ".join(FIELDS) + " FROM board_items WHERE removed=0 ORDER BY coalesce(priority,2), important DESC, item_id").fetchall()
    finally:
        c.close()
    out = [dict(zip(FIELDS, r)) for r in rows]
    for i in out:
        if i["kind"] == "task":
            i["status"] = _status(i["status"])
    return out if include_closed else [i for i in out if i["status"] not in ("done", "parked")]


def history(uid, limit=30):
    c = _conn(uid)
    try:
        return [dict(zip(("item_id", "action", "text", "ts"), r)) for r in
                c.execute("SELECT item_id, action, text, ts FROM board_history ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        c.close()


def _latest_event(c):
    try:
        r = c.execute("SELECT event_id FROM event_metadata ORDER BY rowid DESC LIMIT 1").fetchone()
        return r[0] if r else ""
    except Exception:
        return ""


def act(uid, item_id="", action="add", text="", kind="", title="", priority=None, parent_id="", waiting_for="",
        result="", event_id="", status="", key=""):
    action = (action or "add").lower().strip()
    key = re.sub(r"[^A-Za-z0-9_.:-]", "", key or "")[:120]
    action = ALIASES.get(action, action)
    if action not in ACTIONS:
        raise ValueError("action must be one of: " + "|".join(ACTIONS) + " (old: edit, progress, undo also work)")
    item_id = re.sub(r"[^A-Za-z0-9_.-]", "", item_id or "")[:40]
    parent_id = re.sub(r"[^A-Za-z0-9_.-]", "", parent_id or "")[:40]
    text = _scrub(uid, (text or "")[:2000]); title = _scrub(uid, (title or "")[:200])
    result = _scrub(uid, (result or "")[:1000]); waiting_for = _scrub(uid, (waiting_for or "")[:200])
    if priority not in (None, ""):
        try:
            priority = max(1, min(3, int(priority)))
        except Exception:
            raise ValueError("priority: 1 (high) | 2 (normal) | 3 (low)")
    else:
        priority = None
    if action in ("add", "add_subtask") and not title and ":" in text[:120]:
        title, text = [x.strip() for x in text.split(":", 1)]
    c = _conn(uid)
    out = {}
    try:
        row = c.execute("SELECT kind, title, body, status FROM board_items WHERE item_id=? AND removed=0", (item_id,)).fetchone() if item_id else None
        if action == "update" and not row:
            action = "add"
        if action == "add_subtask":
            if not parent_id or not c.execute("SELECT 1 FROM board_items WHERE item_id=? AND removed=0", (parent_id,)).fetchone():
                raise ValueError("add_subtask needs parent_id of an existing item")
        if parent_id and parent_id == item_id:
            raise ValueError("parent_id cannot be the item itself")
        if action in ("add", "add_subtask") and key:
            try: c.execute("ALTER TABLE board_items ADD COLUMN idem_key TEXT")
            except Exception: pass
            _k = c.execute("SELECT item_id FROM board_items WHERE idem_key=? AND removed=0", (key,)).fetchone()
            if _k:
                return {"id": _k[0], "action": action, "idempotent": True, "note": "an item with this key already exists; nothing added"}
        if action in ("add", "add_subtask"):
            if not (title or text):
                raise ValueError("add needs title or text")
            kind = kind if kind in KINDS else ("task" if (action == "add_subtask" or re.match(r"^T\d", item_id) or not item_id) else "note")
            if not item_id:
                n = c.execute("SELECT count(*) FROM board_items").fetchone()[0] + 1
                item_id = ("T%02d" % n) if kind == "task" else (kind[0] + "_" + uuid.uuid4().hex[:6])
                while c.execute("SELECT 1 FROM board_items WHERE item_id=?", (item_id,)).fetchone():
                    n += 1; item_id = ("T%02d" % n) if kind == "task" else (kind[0] + "_" + uuid.uuid4().hex[:6])
            st = _status(status) if status in STATUSES + tuple(_OLD_STATUS) and status else ("todo" if kind == "task" else "")
            if waiting_for and kind == "task" and not status:
                st = "blocked"
            c.execute("INSERT OR REPLACE INTO board_items (item_id, kind, title, body, status, updated_at, removed, important, priority, parent_id, waiting_for, result, result_event, created_at) "
                      "VALUES (?,?,?,?,?,datetime('now'),0,?,?,?,?,'','',datetime('now'))",
                      (item_id, kind, title or text[:80], text if title else "", st, 1 if priority == 1 else 0, priority or 2, parent_id, waiting_for))
            if key:
                c.execute("UPDATE board_items SET idem_key=? WHERE item_id=?", (key, item_id))
            ev = event_id or _latest_event(c)
            try:
                from app import source_links as _sl0
                _sl0.link_board_event(c, item_id, ev)
            except Exception as _e0:
                print(f"[source_links] board add: {_e0}", flush=True)
        else:
            if not row:
                raise KeyError(item_id or "item_id required")
            if action == "update":
                sets, vals = ["updated_at=datetime('now')"], []
                if title: sets.append("title=?"); vals.append(title)
                if text: sets.append("body=?"); vals.append(text)
                if kind in KINDS: sets.append("kind=?"); vals.append(kind)
                if priority: sets.append("priority=?"); vals.append(priority)
                if parent_id: sets.append("parent_id=?"); vals.append(parent_id)
                if waiting_for: sets.append("waiting_for=?"); vals.append("" if waiting_for == "-" else waiting_for)
                if status in STATUSES and status != "done": sets.append("status=?"); vals.append(status)
                c.execute(f"UPDATE board_items SET {', '.join(sets)} WHERE item_id=?", vals + [item_id])
            elif action == "remove":
                c.execute("UPDATE board_items SET removed=1, updated_at=datetime('now') WHERE item_id=?", (item_id,))
            elif action in ("important", "unimportant"):
                v = 1 if action == "important" else 0
                c.execute("UPDATE board_items SET important=?, priority=?, updated_at=datetime('now') WHERE item_id=?", (v, 1 if v else 2, item_id))
            elif action == "done":
                res = result or text
                if len(res.strip()) < 3:
                    raise ValueError("done needs result=<what was achieved, 1-2 lines>; it is stored with the closing turn's event")
                ev = event_id or _latest_event(c)
                c.execute("UPDATE board_items SET status='done', result=?, result_event=?, waiting_for='', updated_at=datetime('now') WHERE item_id=?", (res, ev, item_id))
                try:
                    from app import source_links as _sl1
                    _sl1.ensure(c)
                    import json as _js
                    _old = c.execute("SELECT source_event_ids FROM source_links WHERE obj_id=?", ("board:" + item_id,)).fetchone()
                    try: _prev = _js.loads(_old[0]) if _old and _old[0] else []
                    except Exception: _prev = [x for x in re.split(r"[,\s]+", _old[0] or "") if x] if _old else []
                    _sl1._put(c, "board:" + item_id, "board", list(_prev) + [ev], "created+done_events", force=True)
                except Exception as _e1:
                    print(f"[source_links] board done: {_e1}", flush=True)
                out = {"result": res, "result_event": ev}
                opn = c.execute("SELECT item_id FROM board_items WHERE parent_id=? AND removed=0 AND status IN ('todo','doing','blocked','open','in_progress')", (item_id,)).fetchall()
                if opn:
                    out["warning"] = "open subtasks: " + ", ".join(r[0] for r in opn)
            else:
                st = {"start": "doing", "block": "blocked", "park": "parked", "reopen": "todo"}[action]
                wf = waiting_for or (text if action == "block" else "")
                if action == "block" and not wf:
                    raise ValueError("block needs waiting_for=<who/what; 'user' = waiting for the user>")
                c.execute("UPDATE board_items SET status=?, waiting_for=?, updated_at=datetime('now')" + (", result='', result_event=''" if action == "reopen" else "") + " WHERE item_id=?",
                          (st, wf if action == "block" else "", item_id))
                if text and action != "block":
                    c.execute("UPDATE board_items SET body=coalesce(body,'')||? WHERE item_id=?", (" | " + text, item_id))
        c.execute("INSERT INTO board_history (item_id, action, text, ts) VALUES (?,?,?,datetime('now'))",
                  (item_id, action, ((title + ": ") if title else "") + (result or text)[:300]))
        try:
            from app import source_links as _sl; _sl.link_all(c)
        except Exception as _e:
            print(f"[source_links] {_e}", flush=True)
        c.execute("DELETE FROM board_history WHERE id NOT IN (SELECT id FROM board_history ORDER BY id DESC LIMIT 200)")
        c.commit()
        cur = c.execute("SELECT " + ", ".join(FIELDS) + " FROM board_items WHERE item_id=?", (item_id,)).fetchone()
    finally:
        c.close()
    r = {"id": item_id, "action": action, **out}
    if cur:
        r["item"] = {k: v for k, v in zip(FIELDS, cur) if v not in (None, "") and k not in ("important",)}
    return r


def _line(i, body=200):
    st = f" [{i['status']}]" if i.get("status") else ""
    pr = " !" if (i.get("priority") or 2) == 1 else (" (low)" if i.get("priority") == 3 else "")
    wf = f" waiting_for={i['waiting_for']}" if i.get("waiting_for") else ""
    par = f" ⤷{i['parent_id']}" if i.get("parent_id") else ""
    b = (i.get("body") or "").replace("\n", " ")
    return f"- {i['item_id']}{pr}{st}{par}{wf} {i['title']}" + (f": {b[:body]}" if b and body else "")


def render(uid, tokens=500):
    allit = items(uid, include_closed=True)
    if not allit:
        return ""
    done = [i for i in allit if i["status"] == "done"][-5:]
    it = [i for i in allit if i["status"] not in ("done", "parked")]
    parked = [i for i in allit if i["status"] == "parked"]
    lines = [HINT]
    for k, head in (("task", "TASKS"), ("resource", "RESOURCES"), ("note", "NOTES")):
        sel = [i for i in it if i["kind"] == k]
        if k == "task":
            sel.sort(key=lambda i: ({"doing": 0, "blocked": 1, "todo": 2}.get(i["status"], 3), i.get("priority") or 2))
        if sel:
            lines.append(head + ":")
            lines += [_line(i) for i in sel]
    if parked:
        lines.append("PARKED: " + "; ".join(f"{i['item_id']} {i['title'][:50]}" for i in parked))
    if done:
        lines.append("DONE: " + "; ".join(f"~~{i['item_id']} {i['title'][:50]}~~" + (f" → {i['result'][:60]}" if i.get("result") else "") for i in done))
    s = "\n".join(lines)
    lim = tokens * 4
    return s if len(s) <= lim else s[:lim].rsplit("\n", 1)[0] + "\n...(clipped; board_list for all)"


_STOP = set("the and for with this that what from have will your you are was not but all can как что это для или про так уже его она они мне меня тебя есть нет надо было будет при над под".split())
def _toks(s):
    return {w[:5] for w in re.findall(r"[a-zа-яё0-9]{3,}", (s or "").lower()) if w not in _STOP}

_DONE_RE = re.compile(r"\b(готово|сделано|сделал|исправил|исправлен[оа]?|починил|починен[оа]?|заверш[её]н[оа]?|закончил|выполнен[оа]?|done|fixed|completed|finished|implemented|resolved|shipped)\b", re.I)


def relevant(uid, message="", answer="", n=3):
    """Up to n open tasks relevant to the message (+ answer): compact, plus a close hint when the answer reads like completion."""
    op = [i for i in items(uid) if i["kind"] == "task" and i["status"] in OPEN]
    st = stale(uid)
    sx = {"board_stale": st, "board_stale_hint": STALE_HINT} if st else {}
    if not op:
        return {"board": [], "board_hint": None, **sx}
    mt, at = _toks(message), _toks(answer)
    scored = []
    for i in op:
        it = _toks(i["title"] + " " + (i.get("body") or "")[:400] + " " + i["item_id"].lower())
        idhit = 3 if re.search(r"\b" + re.escape(i["item_id"].lower()) + r"\b", (message + " " + answer).lower()) else 0
        s = len(mt & it) * 2 + len(at & it) + idhit + (1 if i["status"] == "doing" else 0)
        if s >= 2:
            scored.append((s, len(at & it) + idhit, i))
    scored.sort(key=lambda x: (-x[0], x[2].get("priority") or 2))
    top = scored[:n]
    out = [{"id": i["item_id"], "status": i["status"], "title": i["title"][:80], **({"waiting_for": i["waiting_for"]} if i.get("waiting_for") else {})} for _, _, i in top]
    hint = None
    if answer and _DONE_RE.search(answer):
        cand = [x for x in top if x[1] >= 2]
        if cand:
            x = cand[0][2]
            hint = f"looks done? close item {x['item_id']}: board_act(action=done, item_id={x['item_id']}, result=<what was achieved>)"
    return {"board": out, "board_hint": hint, **sx}


STALE_HINT = "stale: close with a result (board_act action=done, result=...), park, or remove"


def stale(uid, n=3):
    """Reminder only: doing/blocked not updated >24h, todo >7 days. Oldest first, up to n."""
    import datetime as _dt
    now = _dt.datetime.utcnow()
    out = []
    for i in items(uid):
        if i["kind"] != "task" or i["status"] not in OPEN:
            continue
        try:
            u = _dt.datetime.strptime((i.get("updated_at") or "")[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        age = (now - u).total_seconds() / 3600
        if (i["status"] in ("doing", "blocked") and age > 24) or (i["status"] == "todo" and age > 24 * 7):
            out.append((age, i))
    out.sort(key=lambda x: -x[0])
    return [{"id": i["item_id"], "status": i["status"], "title": i["title"][:80], "idle_h": int(a)} for a, i in out[:n]]


def focus(uid, limit=10):
    """For step_zero page 1: tasks in progress and tasks waiting for the user."""
    op = [i for i in items(uid) if i["kind"] == "task"]
    doing = [i for i in op if i["status"] == "doing"][:limit]
    wait = [i for i in op if i["status"] == "blocked" or i.get("waiting_for")][:limit]
    lines = []
    if doing:
        lines.append("IN PROGRESS:"); lines += [_line(i, 120) for i in doing]
    if wait:
        lines.append("WAITING FOR (user or other):"); lines += [_line(i, 120) for i in wait]
    todo = [i for i in op if i["status"] == "todo"]
    if todo:
        lines.append("TODO (%d): " % len(todo) + "; ".join(f"{i['item_id']} {i['title'][:40]}" for i in todo[:8]))
    st = stale(uid)
    if st:
        lines.append("STALE (" + STALE_HINT + "): " + "; ".join(f"{x['id']} {x['status']} {x['idle_h']}h idle" for x in st))
    return {"doing": [i["item_id"] for i in doing], "waiting": [i["item_id"] for i in wait], "board_stale": st, "text": "\n".join(lines)}


def for_recall(uid, session, cfg, force=False):
    if not cfg.get("board_enabled", True):
        return ""
    every = int(cfg.get("board_every", 10) or 10)
    text = render(uid, int(cfg.get("board_tokens", 500) or 500))
    h = hashlib.sha1(text.encode()).hexdigest()[:16]
    c = _conn(uid)
    try:
        sess, recalls, last, oldh = c.execute("SELECT session, recalls, last_sent, hash FROM board_state WHERE id=1").fetchone() or (None, 0, None, None)
        recalls = (recalls or 0) + 1
        due = bool(text) and (force or sess != session or last is None or recalls - last >= every or h != oldh)
        c.execute("INSERT OR REPLACE INTO board_state (id, session, recalls, last_sent, hash) VALUES (1,?,?,?,?)",
                  (session, recalls, recalls if due else last, h if due else oldh))
        c.commit()
    finally:
        c.close()
    return text if due else ""
