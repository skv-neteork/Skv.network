"""One write path for chat, agent, and import. Tested on a DB copy before live use."""
import os
import sqlite3
from datetime import datetime

DATA = "/data/skv/metadata_store"
HNSW = "/data/skv/hnsw"
DIM = 768


def db_name(user_id: str) -> str:
    return user_id.replace("@", "").replace(".", "")


def remember_turn(user_id: str, event_id: str, query: str, response: str, source: str = "chat", topic: str = "", pinned: bool = False) -> dict:
    if not user_id or not event_id:
        raise ValueError("user_id and event_id required")
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, db_name(user_id) + ".db")
    dialogue = f"Q: {query}\nA: {response}"
    status = "critical_permanent" if pinned or ">>> ✅" in dialogue else "active"
    conn = sqlite3.connect(path, timeout=30)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS event_metadata (
            event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, metric_value REAL,
            messages_count INTEGER, links_json TEXT, topics_json TEXT, raw_dialogue TEXT,
            subject TEXT, action TEXT, object TEXT, status TEXT)"""
    )
    cur.execute(
        """INSERT OR REPLACE INTO event_metadata
           (event_id, time_str, essence, raw_dialogue, status, messages_count, links_json, topics_json, subject, action, object, metric_value)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, datetime.now().strftime("%Y-%m-%d %H:%M"), (topic or query)[:200], dialogue, status, 2, "[]", '["' + source + '"]', "", "", "", 0),
    )
    rowid = cur.execute("SELECT rowid FROM event_metadata WHERE event_id=?", (event_id,)).fetchone()[0]
    cur.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            event_id UNINDEXED, subject, action, object, raw_dialogue)"""
    )
    cur.execute("DELETE FROM events_fts WHERE rowid=?", (rowid,))
    cur.execute(
        "INSERT INTO events_fts(rowid, event_id, subject, action, object, raw_dialogue) VALUES (?,?,?,?,?,?)",
        (rowid, event_id, "", "", "", dialogue),
    )
    conn.commit()
    conn.close()
    vector_ok = _add_vector(db_name(user_id), event_id, dialogue[:2000])
    return {"status": "ok", "event_id": event_id, "pinned": status == "critical_permanent", "vector": vector_ok}


def _add_vector(name: str, event_id: str, text: str) -> bool:
    try:
        import numpy as np
        import hnswlib
        from app.routers.v4_middleware import get_embedding_cached
        vec = np.array(get_embedding_cached(text), dtype=np.float32)
        if vec.shape[0] != DIM:
            return False
        os.makedirs(HNSW, exist_ok=True)
        index_path = os.path.join(HNSW, f"{name}.hnsw")
        ids_path = os.path.join(HNSW, f"{name}_ids.npy")
        index = hnswlib.Index(space="cosine", dim=DIM)
        if os.path.exists(index_path) and os.path.exists(ids_path):
            index.load_index(index_path)
            ids = list(np.load(ids_path, allow_pickle=True))
        else:
            index.init_index(max_elements=64, ef_construction=200, M=16)
            ids = []
        if event_id in ids:
            label = ids.index(event_id)
        else:
            if index.get_current_count() >= index.get_max_elements():
                index.resize_index(index.get_max_elements() + 64)
            label = len(ids)
            ids.append(event_id)
        index.add_items(vec.reshape(1, -1), np.array([label]))
        index.save_index(index_path)
        np.save(ids_path, np.array(ids, dtype=object))
        return True
    except Exception as exc:
        print(f"[memory_write] vector skipped: {exc}", flush=True)
        return False
