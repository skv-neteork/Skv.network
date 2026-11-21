"""Append-only capture pointers. Structured data the caller already has. No model call and no summary."""
import json
import os
import sqlite3
import time

DEFAULT_PATH = "/data/skv/metadata_store/signal_log.db"


def ensure(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            ref TEXT,
            cube_id TEXT,
            extra_json TEXT,
            ts REAL NOT NULL)"""
    )


def append_pointer(conn, kind, ref="", cube_id="", extra=None, ts=None):
    """Write one capture pointer. extra is stored as given. This function does not call a model."""
    ensure(conn)
    ts = time.time() if ts is None else float(ts)
    extra_json = json.dumps(extra, ensure_ascii=False, sort_keys=True) if extra else ""
    cur = conn.execute(
        "INSERT INTO signal_log (kind, ref, cube_id, extra_json, ts) VALUES (?,?,?,?,?)",
        (str(kind)[:80], str(ref)[:300], str(cube_id)[:200], extra_json[:1000], ts),
    )
    return {"ok": True, "id": cur.lastrowid, "model_called": False}


def append_pointer_file(kind, ref="", cube_id="", extra=None, path=None):
    path = path or DEFAULT_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        row = append_pointer(conn, kind, ref, cube_id, extra)
        conn.commit()
        return row
    finally:
        conn.close()
