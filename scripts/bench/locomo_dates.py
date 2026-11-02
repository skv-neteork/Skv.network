"""Set locomo_test@skv event time_str to original LoCoMo session dates (ids unchanged).
Usage: python3 locomo_dates.py [--apply]   rollback: copy the .bak_dates_20261102 db back."""
import json, sys, sqlite3, hashlib, shutil, os
from datetime import datetime
sys.path.insert(0, "/app")
from app.memory_v2 import db_path
UID = "locomo_test@skv"
c = json.load(open("/data/skv/bench/locomo10.json"))[0]["conversation"]
msgs = []
i = 1
while f"session_{i}" in c:
    dt = datetime.strptime(c[f"session_{i}_date_time"], "%I:%M %p on %d %B, %Y")
    for t in c[f"session_{i}"]:
        role = "user" if t.get("speaker") == c.get("speaker_a") else "assistant"
        msgs.append((role, t.get("text") or "", dt))
    i += 1
m = {}
for k, (role, txt, dt) in enumerate(msgs):
    if role == "user" and k + 1 < len(msgs) and msgs[k + 1][0] == "assistant":
        h = hashlib.sha1((txt + "\x00" + msgs[k + 1][1]).encode("utf-8", "replace")).hexdigest()[:12]
        m.setdefault(f"{UID}::locomo_{h}", dt)
p = db_path(UID)
conn = sqlite3.connect(p)
rows = conn.execute("SELECT event_id, time_str FROM event_metadata").fetchall()
hit = [e for e, _ in rows if e in m]
print("events", len(rows), "mapped", len(hit), "pairs", len(m))
miss = [e for e, _ in rows if e not in m]
print("unmapped sample", miss[:5])
if "--apply" in sys.argv:
    bak = p + ".bak_dates_20261102"
    if not os.path.exists(bak):
        b = sqlite3.connect(bak); conn.backup(b); b.close()
    for e in hit:
        conn.execute("UPDATE event_metadata SET time_str=? WHERE event_id=?", (m[e].strftime("%Y-%m-%d %H:%M"), e))
    conn.commit()
    print("applied; backup", bak)
    print(conn.execute("SELECT min(time_str), max(time_str), count(distinct time_str) FROM event_metadata").fetchone())
