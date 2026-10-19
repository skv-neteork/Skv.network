"""POST /api/v7/remember/batch: bulk import of turns (history, other chats) in one request.

One transaction for rows + FTS + links, one batched embedding call and one HNSW save for the whole batch
(single /remember saves the index per turn). Secrets go to the vault as in /remember. Order = item order
(rowid chronology); ts/occurred_at per item sets the event time. Max 500 items per call.
"""
import json
import os
import sqlite3
import time
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v7", tags=["ChronoMemory"])
BASE = "/data/skv/metadata_store"
MAX_ITEMS = int(os.environ.get("SKV_BATCH_MAX", "500"))


class BatchItem(BaseModel):
    query: str = ""
    response: str = ""
    topic: str = ""
    ts: str = ""
    occurred_at: str = ""
    kind: str = ""
    source: str = ""
    project: str = ""


class BatchRequest(BaseModel):
    user_id: str = ""
    items: List[BatchItem] = []
    topic: str = ""
    kind: str = "dialogue"
    source: str = ""
    project: str = ""


@router.post("/remember/batch")
def remember_batch(req: BatchRequest):   # sync: runs in the threadpool, does not block the event loop
    t0 = time.time()
    if not req.user_id:
        raise HTTPException(401, "API key required")
    items = [i for i in req.items if (i.query or i.response)]
    if not items:
        raise HTTPException(422, "items with query or response required")
    if len(items) > MAX_ITEMS:
        raise HTTPException(413, f"max {MAX_ITEMS} items per batch")
    from app.account_memory import account_db_name, _fts_insert
    from app.routers.v7_router import _event_time_str
    from app import shelves as _sh
    uid = req.user_id
    name = account_db_name(uid)
    path = os.path.join(BASE, name + ".db")
    times = [_event_time_str(i.ts or i.occurred_at) for i in items]   # 422 on a bad ts, before any write
    try:
        from app import vault as _vault
        vault_on = _vault.available()
    except Exception:
        vault_on = False
    base_ns = time.time_ns()
    ids, dialogues, vaulted = [], [], []
    conn = sqlite3.connect(path, timeout=60)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS event_metadata (
            event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, metric_value REAL,
            messages_count INTEGER, links_json TEXT, topics_json TEXT, raw_dialogue TEXT,
            subject TEXT, action TEXT, object TEXT, status TEXT,
            kind TEXT DEFAULT 'dialogue', source TEXT DEFAULT '', project TEXT DEFAULT '')""")
        _sh.ensure_columns(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS event_links (src TEXT, dst TEXT, kind TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
        prev = conn.execute("SELECT event_id FROM event_metadata ORDER BY event_id DESC LIMIT 1").fetchone()
        prev = prev[0] if prev else None
        last_topic = {}
        now = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        cur = conn.cursor()
        for n, (it, ts) in enumerate(zip(items, times)):
            eid = f"{uid}::remember_{base_ns + n}"
            q, a, topic = it.query, it.response, it.topic or req.topic
            if vault_on:
                try:
                    q, n1 = _vault.scrub(uid, q or "", eid)
                    a, n2 = _vault.scrub(uid, a or "", eid)
                    vaulted += list(n1 or []) + list(n2 or [])
                except Exception as e:
                    print(f"[batch] vault scrub skipped: {e}", flush=True)
            dialogue = f"Q: {q}\nA: {a}"
            kind = _sh.normalize_kind(it.kind or req.kind) or "dialogue"
            cur.execute("""INSERT OR REPLACE INTO event_metadata
                (event_id, time_str, essence, raw_dialogue, messages_count, links_json, topics_json, status, kind, source, project)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (eid, ts or now, (topic or q)[:200], dialogue, 2, "[]", json.dumps(["agent"]), "pending_vector",
                         kind, it.source or req.source or "", it.project or req.project or ""))
            _fts_insert(cur, eid, dialogue)
            if prev:
                cur.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (prev, eid, "next"))
            if topic:
                same = last_topic.get(topic)
                if same is None:
                    r = cur.execute("SELECT event_id FROM event_metadata WHERE essence LIKE ? AND event_id != ? ORDER BY event_id DESC LIMIT 1",
                                    ("%" + topic + "%", eid)).fetchone()
                    same = r[0] if r else None
                if same:
                    cur.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (same, eid, "topic"))
                last_topic[topic] = eid
            prev = eid
            ids.append(eid)
            dialogues.append(dialogue)
        conn.commit()
    finally:
        conn.close()
    t_db = time.time()
    vec_ok = False
    try:
        from app import semantic as sem
        tag = sem.active_tag()
        if tag != "bge" and not os.path.exists(os.path.join(sem.MODELS[tag]["dir"], "REBUILDING")):
            vecs = sem.embed(dialogues, tag, batch_size=32)
            sem.STORE.add(tag, sem.account_name(uid), ids, vecs, save=True)
            c2 = sqlite3.connect(path, timeout=60)
            try:
                sem._ensure_table(c2, sem.MODELS[tag]["table"])
                c2.executemany(f"INSERT OR REPLACE INTO {sem.MODELS[tag]['table']} (event_id, created_at) VALUES (?, datetime('now'))", [(i,) for i in ids])
                c2.commit()
            finally:
                c2.close()
            vec_ok = True
    except Exception as e:
        print(f"[batch] vectors deferred to the batch thread: {e}", flush=True)
    try:
        from app.account_memory import _ensure_batch_thread
        _ensure_batch_thread(BASE)
    except Exception:
        pass
    out = {"status": "ok", "saved": len(ids), "first": ids[0], "last": ids[-1], "vectors": "now" if vec_ok else "deferred",
           "ms": {"db": round((t_db - t0) * 1000), "total": round((time.time() - t0) * 1000)}}
    if vaulted:
        out["vaulted"] = list(dict.fromkeys(vaulted))
    return out
