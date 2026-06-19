import sqlite3
import json
import os
from typing import Dict, Any, List, Optional

class MultiTenantMetadataStore:
    def __init__(self, base_dir: str = "/app/data/metadata_store"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.shared_db_path = f"{base_dir}/shared_master.db"
        self._init_table(self.shared_db_path)

    def _get_user_db_path(self, user_id: str) -> str:
        safe_user_id = "".join(c for c in user_id if c.isalnum() or c in ("_", "-"))
        return f"{self.base_dir}/{safe_user_id}.db"

    def _init_table(self, db_path: str):
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS event_metadata (
                    event_id TEXT PRIMARY KEY,
                    time_str TEXT NOT NULL,
                    essence TEXT NOT NULL,
                    metric_value REAL,
                    messages_count INTEGER NOT NULL,
                    links_json TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    raw_dialogue TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_id ON event_metadata(event_id)")
            conn.commit()

    def write_metadata(self, user_id: str, event_id: str, time_str: str, essence: str, 
                       messages_count: int, topics: List[str], links: List[str], 
                       metric_value: Optional[float] = None, raw_dialogue: Optional[str] = None,
                       is_shared: bool = False):
        db_path = self.shared_db_path if is_shared else self._get_user_db_path(user_id)
        self._init_table(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO event_metadata 
                (event_id, time_str, essence, metric_value, messages_count, links_json, topics_json, raw_dialogue)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, time_str, essence, metric_value, messages_count, 
                json.dumps(links), json.dumps(topics), raw_dialogue
            ))
            conn.commit()

    def batch_get_metadata(self, user_id: str, event_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not event_ids: return {}
        personal_ids = [eid for eid in event_ids if not eid.startswith("CUBE_") and "shared" not in eid]
        shared_ids = [eid for eid in event_ids if eid.startswith("CUBE_") or "shared" in eid]
        result_map = {}
        
        if personal_ids:
            p_db = self._get_user_db_path(user_id)
            if os.path.exists(p_db): self._fetch_chunk(p_db, personal_ids, result_map)
        if shared_ids:
            if os.path.exists(self.shared_db_path): self._fetch_chunk(self.shared_db_path, shared_ids, result_map)
        return result_map

    def _fetch_chunk(self, db_path: str, ids: List[str], result_map: dict):
        placeholders = ",".join("?" for _ in ids)
        query = f"SELECT * FROM event_metadata WHERE event_id IN ({placeholders})"
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(query, ids)
            for row in cursor.fetchall():
                eid = row[0]
                result_map[eid] = {
                    "time": row[1],
                    "essence": row[2],
                    "metric_value": row[3] if row[3] is not None else "нет",
                    "messages_count": row[4],
                    "links": json.loads(row[5]),
                    "topics": json.loads(row[6]),
                    "raw_dialogue": row[7]
                }

    def get_full_dialogue(self, user_id: str, event_id: str) -> Optional[str]:
        is_shared = event_id.startswith("CUBE_") or "shared" in event_id
        db_path = self.shared_db_path if is_shared else self._get_user_db_path(user_id)
        if not os.path.exists(db_path): return None
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()
            return row[0] if row else None
