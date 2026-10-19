"""Shared account memory: one SQLite file per user_id for chat, agents, and import.

Vectors are not built per message. Pending rows are embedded in batches into the
768-d HNSW index that live search reads.
"""
import json
import os
import sqlite3
import threading
import time

DIM = 768
_batch_lock = threading.Lock()
_thread_started = False


def account_db_name(user_id: str) -> str:
    return "".join(c for c in user_id if c.isalnum() or c in ("_", "-"))


def _fts_insert(cur, event_id: str, dialogue: str):
    cur.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            event_id UNINDEXED, raw_dialogue)"""
    )
    try:
        cur.execute("DELETE FROM events_fts WHERE event_id=?", (event_id,))
    except sqlite3.OperationalError:
        pass
    cur.execute(
        "INSERT INTO events_fts(event_id, raw_dialogue) VALUES (?,?)",
        (event_id, dialogue or ""),
    )


def queue_turn(base_dir: str, user_id: str, event_id: str, query: str, response: str, source: str = "chat", topic: str = "", time_str: str = None) -> dict:
    name = account_db_name(user_id)
    if not name or not event_id:
        raise ValueError("user_id and event_id required")
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, name + ".db")
    try:   # chat turns too: secrets go to the vault, memory keeps [vault:<name>]
        from app import vault as _vault
        if _vault.available():
            query, _ = _vault.scrub(user_id, query or "", event_id)
            response, _ = _vault.scrub(user_id, response or "", event_id)
            topic, _ = _vault.scrub(user_id, topic or "", event_id)
    except Exception as exc:
        print(f"[vault] turn scrub skipped: {exc}", flush=True)
    dialogue = f"Q: {query}\nA: {response}"
    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS event_metadata (
                event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, metric_value REAL,
                messages_count INTEGER, links_json TEXT, topics_json TEXT, raw_dialogue TEXT,
                subject TEXT, action TEXT, object TEXT, status TEXT,
                kind TEXT DEFAULT 'dialogue', source TEXT DEFAULT '', project TEXT DEFAULT '')"""
        )
        try:
            from app import shelves as _sh
            _sh.ensure_columns(conn)
        except Exception as exc:
            print(f"[shelves] ensure skipped: {exc}", flush=True)
        conn.execute(
            """INSERT OR REPLACE INTO event_metadata
               (event_id, time_str, essence, raw_dialogue, messages_count, links_json, topics_json, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (event_id, time_str or time.strftime("%Y-%m-%d %H:%M"), (topic or query)[:200], dialogue, 2, "[]", json.dumps([source]), "pending_vector"),
        )
        _fts_insert(conn.cursor(), event_id, dialogue)
        conn.commit()
    try:
        from app import semantic
        semantic.add_event_now(user_id, event_id, dialogue)
    except Exception as exc:
        print(f"[memory] instant vector skipped: {exc}", flush=True)
    _ensure_batch_thread(base_dir)
    return {"status": "queued", "event_id": event_id, "account": name}


def build_pending_vectors(base_dir: str, hnsw_dir: str, user_filter: str = "") -> int:
    import numpy as np
    import hnswlib
    from fastembed import TextEmbedding

    os.makedirs(hnsw_dir, exist_ok=True)
    model = None
    done = 0
    for fname in os.listdir(base_dir):
        if not fname.endswith(".db") or fname == "shared_master.db":
            continue
        if user_filter and fname != user_filter + ".db":
            continue
        path = os.path.join(base_dir, fname)
        name = fname[:-3]
        with sqlite3.connect(path, timeout=30) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS personal_vectors (event_id TEXT PRIMARY KEY, vector_blob BLOB, created_at TEXT)"
            )
            try:
                rows = conn.execute(
                    """SELECT e.event_id, e.raw_dialogue FROM event_metadata e
                       LEFT JOIN personal_vectors v ON e.event_id=v.event_id
                       WHERE v.event_id IS NULL AND e.raw_dialogue IS NOT NULL"""
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            if not rows:
                continue
            if model is None:
                model = TextEmbedding(model_name="BAAI/bge-base-en-v1.5")
            longs = [(e, t) for e, t in rows if len(t or "") >= 500]
            shorts = [(e, t) for e, t in rows if len(t or "") < 500]
            batches = [(e, t) for e, t in longs]
            bucket, blob = [], ""
            for eid, text in shorts:
                bucket.append(eid)
                blob += " " + (text or "")
                if len(blob) >= 2000:
                    batches.append((bucket[0], blob))
                    for extra in bucket[1:]:
                        batches.append((extra, blob))
                    bucket, blob = [], ""
            if bucket:
                for extra in bucket:
                    batches.append((extra, blob))
            if not batches:
                continue
            index_path = os.path.join(hnsw_dir, name + ".hnsw")
            ids_path = os.path.join(hnsw_dir, name + "_ids.npy")
            index = hnswlib.Index(space="cosine", dim=DIM)
            if os.path.exists(index_path) and os.path.exists(ids_path):
                index.load_index(index_path)
                ids = list(np.load(ids_path, allow_pickle=True))
            else:
                index.init_index(max_elements=max(64, len(batches) + 8), ef_construction=200, M=16)
                ids = []
            for eid, text in batches:
                vec = np.array(list(model.embed([text[:2000]]))[0], dtype=np.float32)
                if eid in ids:
                    label = ids.index(eid)
                else:
                    if index.get_current_count() >= index.get_max_elements():
                        index.resize_index(index.get_max_elements() + 64)
                    label = len(ids)
                    ids.append(eid)
                index.add_items(vec.reshape(1, -1), np.array([label]))
                conn.execute(
                    "INSERT OR REPLACE INTO personal_vectors (event_id, vector_blob, created_at) VALUES (?,?,datetime('now'))",
                    (eid, vec.tobytes()),
                )
                done += 1
                if done % 50 == 0:
                    conn.commit()
                    index.save_index(index_path)
                    np.save(ids_path, np.array(ids, dtype=object))
            conn.commit()
            index.save_index(index_path)
            np.save(ids_path, np.array(ids, dtype=object))
    return done


def _ensure_batch_thread(base_dir: str):
    global _thread_started
    if _thread_started or os.environ.get("SKV_NO_BATCH") == "1":
        return
    _thread_started = True

    def loop():
        hnsw = os.environ.get("SKV_HNSW", "/data/skv/hnsw")
        while True:
            time.sleep(60)
            try:
                with _batch_lock:
                    from app import semantic
                    tag = semantic.active_tag()
                    if tag == "bge":
                        build_pending_vectors(base_dir, hnsw)
                    elif not os.path.exists(os.path.join(semantic.MODELS[tag]["dir"], "REBUILDING")):
                        semantic.build_pending_all(tag)
            except Exception as exc:
                print(f"[memory] batch skipped: {exc}", flush=True)

    threading.Thread(target=loop, daemon=True).start()


def next_step(user_id: str, base_dir: str = "/data/skv/metadata_store") -> int:
    name = account_db_name(user_id)
    if not name:
        return 0
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, name + ".db")
    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS agent_state (user_id TEXT PRIMARY KEY, step INTEGER)")
        row = conn.execute("SELECT step FROM agent_state WHERE user_id=?", (name,)).fetchone()
        step = (row[0] if row else 0) + 1
        conn.execute("INSERT OR REPLACE INTO agent_state (user_id, step) VALUES (?,?)", (name, step))
        conn.commit()
    return step


def link_turn(base_dir: str, user_id: str, event_id: str, topic: str = "") -> dict:
    """Record brain-like links: next turn, and same topic. Separate table, not a blob."""
    name = account_db_name(user_id)
    path = os.path.join(base_dir, name + ".db")
    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS event_links (src TEXT, dst TEXT, kind TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
        prev = conn.execute("SELECT event_id FROM event_metadata WHERE event_id != ? ORDER BY event_id DESC LIMIT 1", (event_id,)).fetchone()
        made = []
        if prev:
            conn.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (prev[0], event_id, "next"))
            made.append("next")
        if topic:
            same = conn.execute("SELECT event_id FROM event_metadata WHERE essence LIKE ? AND event_id != ? ORDER BY event_id DESC LIMIT 1", ("%" + topic + "%", event_id)).fetchone()
            if same:
                conn.execute("INSERT OR REPLACE INTO event_links (src, dst, kind, created_at) VALUES (?,?,?,datetime('now'))", (same[0], event_id, "topic"))
                made.append("topic")
        conn.commit()
    return {"linked": made}
