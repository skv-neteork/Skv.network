"""Soft-archive superseded events (e.g. an old import replaced by a newer full one). Never purged.
Moves rows event_metadata -> event_superseded, drops their FTS rows, hides their vectors (semantic.mark_forgotten).
Usage inside skv_api: python ops_supersede.py USER PREFIX FROM TO [--apply] | --restore USER BATCH"""
import sqlite3, sys, json, time
sys.path.insert(0, "/app")
from app.account_memory import account_db_name
from app import semantic as sem
def db(user):
    c = sqlite3.connect("/data/skv/metadata_store/" + account_db_name(user) + ".db", timeout=60)
    c.execute("CREATE TABLE IF NOT EXISTS event_superseded AS SELECT * FROM event_metadata WHERE 0")
    have = {r[1] for r in c.execute("PRAGMA table_info(event_superseded)")}
    for col in [r[1] for r in c.execute("PRAGMA table_info(event_metadata)")] + ["superseded_at", "batch", "reason"]:
        if col not in have:
            c.execute(f"ALTER TABLE event_superseded ADD COLUMN {col} TEXT")
    return c
def archive(user, ids, batch, reason, apply):
    c = db(user); cols = ",".join(r[1] for r in c.execute("PRAGMA table_info(event_metadata)"))
    live = [i for i in ids if c.execute("SELECT 1 FROM event_metadata WHERE event_id=?", (i,)).fetchone()]
    if apply:
        for i in live:
            c.execute(f"INSERT INTO event_superseded ({cols}, superseded_at, batch, reason) SELECT {cols}, datetime('now'), ?, ? FROM event_metadata WHERE event_id=?", (batch, reason, i))
            c.execute("DELETE FROM event_metadata WHERE event_id=?", (i,))
            c.execute("DELETE FROM events_fts WHERE event_id=?", (i,))
        c.commit()
        sem.mark_forgotten(user, live, restore=False)
    c.close(); return live
def restore(user, batch):
    c = db(user); cols = ",".join(r[1] for r in c.execute("PRAGMA table_info(event_metadata)"))
    ids = [r[0] for r in c.execute("SELECT event_id FROM event_superseded WHERE batch=?", (batch,))]
    for i in ids:
        c.execute(f"INSERT OR IGNORE INTO event_metadata ({cols}) SELECT {cols} FROM event_superseded WHERE event_id=?", (i,))
        raw = c.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id=?", (i,)).fetchone()
        c.execute("INSERT INTO events_fts(event_id, raw_dialogue) VALUES (?,?)", (i, raw[0] if raw else ""))
        c.execute("DELETE FROM event_superseded WHERE event_id=?", (i,))
    c.commit(); c.close(); sem.mark_forgotten(user, ids, restore=True); return ids
if __name__ == "__main__":
    if sys.argv[1] == "--restore":
        print("restored", len(restore(sys.argv[2], sys.argv[3])))
    else:
        user, prefix, a, b = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
        ids = [f"{user}::{prefix}{n}" for n in range(a, b + 1)]
        batch = "sup_" + time.strftime("%Y%m%d_%H%M%S")
        live = archive(user, ids, batch, "old 2026-10-09 grok import, superseded by profile import 2026-10-19", "--apply" in sys.argv)
        print(json.dumps({"batch": batch, "count": len(live), "applied": "--apply" in sys.argv}))
