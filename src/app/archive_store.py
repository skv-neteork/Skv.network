"""Cold archive that really frees space (25.10, t625).

Raw text of events older than CUTOFF_DAYS (critical '>>>' lines stay hot) moves to event_archive.body_z (zlib),
event_metadata keeps the marker '[archived] <id>'. The event's rows are removed from the text-search indexes
(events_fts, events_fts_stem), the vector tables (personal_vectors, pvec_*) and the hnsw indexes (<account>,
<account>__chunks; L1 index untouched), the hnsw files are rebuilt without them, then FTS optimize + VACUUM.
Archived text stays readable: GET /event, memory_event, archive keyword search, RECALL_LATER (archive_recall.py).
Runs daily from the API process (scheduled, see v7_core._archive_loop) so index rebuilds share STORE.lock."""
import os, json, time, zlib, sqlite3
from datetime import datetime, timedelta

BASE = "/data/skv/metadata_store"
STATE = "/data/skv/archive_state.json"
MARK = "[archived] "
CUTOFF_DAYS = 90
SKIP = {"shared_master.db", "anonymous.db", "test_user.db", "test_user_backup_20260628.db"}
VEC_TABLES = ("personal_vectors", "pvec_mml12", "pvec_mpnet")
FTS_TABLES = ("events_fts", "events_fts_stem")
FMTS = ("%H:%M, %d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def z(text):
    return zlib.compress((text or "").encode("utf-8"), 9)


def unz(blob):
    return zlib.decompress(blob).decode("utf-8")


def text_of(raw, body_z):
    return unz(body_z) if body_z else (raw or "")


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS event_archive (event_id TEXT PRIMARY KEY, raw_dialogue TEXT, archived_at TEXT)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(event_archive)")}
    if "body_z" not in cols:
        conn.execute("ALTER TABLE event_archive ADD COLUMN body_z BLOB")
    if "purged" not in cols:
        conn.execute("ALTER TABLE event_archive ADD COLUMN purged INTEGER DEFAULT 0")


def _when(ts):
    for f in FMTS:
        try:
            return datetime.strptime((ts or "").strip()[:len(datetime(2000, 1, 1, 0, 0).strftime(f))], f)
        except Exception:
            pass
    return None


def candidates(conn, cutoff_days=CUTOFF_DAYS):
    cutoff = datetime.now() - timedelta(days=cutoff_days)
    out = []
    for eid, ts, raw in conn.execute("SELECT event_id, time_str, raw_dialogue FROM event_metadata "
                                     "WHERE raw_dialogue IS NOT NULL AND raw_dialogue != ''"):
        if raw.startswith("[archived]") or ">>>" in raw:
            continue
        w = _when(ts)
        if w is not None and w <= cutoff:
            out.append(eid)
    return out


def archive_rows(conn, ids):
    """Move raw text to event_archive (compressed) and leave the marker. Index cleanup is purge_rows()."""
    ensure(conn)
    n = 0
    for eid in ids:
        r = conn.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id=?", (eid,)).fetchone()
        if not r or not r[0] or r[0].startswith("[archived]"):
            continue
        conn.execute("INSERT OR REPLACE INTO event_archive (event_id, raw_dialogue, archived_at, body_z, purged) "
                     "VALUES (?, NULL, datetime('now'), ?, 0)", (eid, z(r[0])))
        conn.execute("UPDATE event_metadata SET raw_dialogue=? WHERE event_id=?", (MARK + eid, eid))
        n += 1
    return n


def migrate(conn):
    """Old plain-text archive rows -> compressed."""
    ensure(conn)
    rows = conn.execute("SELECT event_id, raw_dialogue FROM event_archive WHERE body_z IS NULL AND raw_dialogue IS NOT NULL").fetchall()
    for eid, raw in rows:
        conn.execute("UPDATE event_archive SET body_z=?, raw_dialogue=NULL WHERE event_id=?", (z(raw), eid))
    return len(rows)


def purge_rows(conn):
    """Delete archived events from FTS and vector tables. Returns ids still to drop from hnsw (purged=0)."""
    ensure(conn)
    ids = [r[0] for r in conn.execute("SELECT event_id FROM event_archive WHERE coalesce(purged,0)=0")]
    have = _tables(conn)
    for i in range(0, len(ids), 300):
        ch = ids[i:i + 300]
        qs = ",".join("?" * len(ch))
        for t in FTS_TABLES + VEC_TABLES:
            if t in have:
                conn.execute(f"DELETE FROM {t} WHERE event_id IN ({qs})", ch)
    return ids


def _rebuild(S, tag, idx, drop):
    """Rebuild one hnsw index without the dropped ids (hnswlib mark_deleted frees nothing on disk)."""
    import hnswlib, numpy as np
    with S.STORE.lock:
        e = S.STORE._load(tag, idx)
        if not e:
            return 0
        base = lambda x: x.rsplit("#", 1)[0] if "#" in x else x
        keep = [(lab, eid) for lab, eid in enumerate(e["ids"]) if eid != "__purged__" and base(eid) not in drop]
        removed = len(e["ids"]) - len(keep)
        if not removed:
            return 0
        old, vecs, ids, dead = e["index"], [], [], []
        for lab, eid in keep:
            try:
                v = old.get_items([lab])[0]
            except RuntimeError:   # soft-deleted (forget, restorable): keep it, still deleted
                try:
                    old.unmark_deleted(lab)
                    v = old.get_items([lab])[0]
                    old.mark_deleted(lab)
                    dead.append(len(ids))
                except RuntimeError:
                    continue
            vecs.append(v)
            ids.append(eid)
        new = hnswlib.Index(space="cosine", dim=S.MODELS[tag]["dim"])
        new.init_index(max_elements=max(len(ids), 16), ef_construction=200, M=16)
        if ids:
            new.add_items(np.asarray(vecs, dtype=np.float32), np.arange(len(ids)))
        for d in dead:
            new.mark_deleted(d)
        new.set_ef(100)
        e.update(index=new, ids=ids, pos={x: i for i, x in enumerate(ids)}, dirty=True)
        S.STORE.save(tag, idx)
        return removed


def compact_indexes(name, ids):
    from app import semantic as S
    drop, out = set(ids), {}
    if not drop:
        return out
    for tag in S.MODELS:
        for idx in (name, name + "__chunks"):
            try:
                n = _rebuild(S, tag, idx, drop)
                if n:
                    out[f"{tag}/{idx}"] = n
            except Exception as exc:
                print(f"[archive] rebuild {tag}/{idx} failed: {exc}", flush=True)
                raise
    return out


def vacuum(conn, force=False):
    have = _tables(conn)
    for t in FTS_TABLES:
        if t in have:
            try:
                conn.execute(f"INSERT INTO {t}({t}) VALUES('optimize')")
            except sqlite3.Error:
                pass
    conn.commit()
    free = conn.execute("PRAGMA freelist_count").fetchone()[0]
    total = conn.execute("PRAGMA page_count").fetchone()[0] or 1
    if force or free > 256 or free / total > 0.05:
        conn.execute("VACUUM")
        return True
    return False


def run_db(path, cutoff_days=CUTOFF_DAYS, name=None, only_ids=None, force_vacuum=False):
    """Archive + purge + compact one account DB. Idempotent (also migrates old plain rows)."""
    name = name or os.path.basename(path)[:-3]
    conn = sqlite3.connect(path, timeout=60)
    try:
        if "event_metadata" not in _tables(conn):
            return None
        ids = only_ids if only_ids is not None else candidates(conn, cutoff_days)
        moved = archive_rows(conn, ids)
        migrated = migrate(conn)
        todo = purge_rows(conn)
        conn.commit()
        idx = compact_indexes(name, todo)
        if todo:
            for i in range(0, len(todo), 300):
                ch = todo[i:i + 300]
                conn.execute("UPDATE event_archive SET purged=1 WHERE event_id IN (%s)" % ",".join("?" * len(ch)), ch)
            conn.commit()
        vac = vacuum(conn, force_vacuum) if (todo or force_vacuum) else False
        return {"moved": moved, "migrated": migrated, "purged": len(todo), "indexes": idx, "vacuum": vac}
    finally:
        conn.close()


def run_all(cutoff_days=CUTOFF_DAYS):
    res = {}
    for f in sorted(os.listdir(BASE)):
        if not f.endswith(".db") or f in SKIP:
            continue
        try:
            r = run_db(os.path.join(BASE, f), cutoff_days)
            if r and (r["moved"] or r["migrated"] or r["purged"]):
                res[f] = r
                print(f"[archive] {f} {r}", flush=True)
        except Exception as exc:
            res[f] = {"error": str(exc)}
            print(f"[archive] {f} failed: {exc}", flush=True)
    try:
        with open(STATE, "w") as fh:
            json.dump({"last_run": datetime.now().isoformat(timespec="seconds"), "result": res}, fh)
    except Exception:
        pass
    return res
