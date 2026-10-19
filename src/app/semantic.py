"""Semantic memory index: switchable embedding model + per-user HNSW + RRF fusion.

Config (env wins over file):
  SKV_EMBED   = bge | mml12            (file /data/skv/embed_config.json {"active": ...})
  SKV_FUSION  = rrf | legacy           (file key "fusion")
Old bge index in /data/skv/hnsw is never touched by the mml12 path.
"""
import json
import os
import re
import sqlite3
import threading
import time

import numpy as np

CONFIG_PATH = "/data/skv/embed_config.json"
MODEL_CACHE = "/data/skv/models"
BASE_DIR = "/data/skv/metadata_store"
RRF_K = 60

MODELS = {
    "bge": {"name": "BAAI/bge-base-en-v1.5", "dim": 768, "dir": "/data/skv/hnsw", "table": "personal_vectors"},
    "mml12": {"name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "dim": 384,
              "dir": "/data/skv/hnsw_mml12", "table": "pvec_mml12"},
}


def _config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def active_tag():
    tag = os.environ.get("SKV_EMBED") or _config().get("active") or "bge"
    return tag if tag in MODELS else "bge"


def fusion_mode():
    return os.environ.get("SKV_FUSION") or _config().get("fusion") or "rrf"


def account_name(user_id):
    return "".join(c for c in (user_id or "") if c.isalnum() or c in ("_", "-"))


# ---------------- model ----------------
_models = {}
_model_lock = threading.Lock()


def get_model(tag, threads=None):
    with _model_lock:
        if tag not in _models:
            from fastembed import TextEmbedding
            os.makedirs(MODEL_CACHE, exist_ok=True)
            kw = {"model_name": MODELS[tag]["name"], "cache_dir": MODEL_CACHE}
            if threads:
                kw["threads"] = threads
            _models[tag] = TextEmbedding(**kw)
        return _models[tag]


def embed(texts, tag=None, threads=None, batch_size=16):
    tag = tag or active_tag()
    model = get_model(tag, threads)
    vecs = np.array(list(model.embed([(t or "")[:1000] for t in texts], batch_size=batch_size)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


# ---------------- index ----------------
class IndexStore:
    """Per (tag, index name) HNSW with ids; reloads when the file on disk changes."""

    def __init__(self):
        self.cache = {}
        self.lock = threading.RLock()

    def _paths(self, tag, name):
        d = MODELS[tag]["dir"]
        return os.path.join(d, name + ".hnsw"), os.path.join(d, name + "_ids.npy")

    def _load(self, tag, name, create=False):
        import hnswlib
        key = (tag, name)
        hp, ip = self._paths(tag, name)
        mtime = os.path.getmtime(hp) if os.path.exists(hp) and os.path.exists(ip) else None
        cached = self.cache.get(key)
        if cached and (cached["mtime"] == mtime or cached.get("dirty")):
            return cached
        if mtime is None:
            if not create:
                return None
            index = hnswlib.Index(space="cosine", dim=MODELS[tag]["dim"])
            index.init_index(max_elements=256, ef_construction=200, M=16)
            ids = []
        else:
            index = hnswlib.Index(space="cosine", dim=MODELS[tag]["dim"])
            index.load_index(hp, max_elements=0)
            ids = [str(x) for x in np.load(ip, allow_pickle=True)]
        index.set_ef(100)
        entry = {"index": index, "ids": ids, "pos": {e: i for i, e in enumerate(ids)}, "mtime": mtime}
        self.cache[key] = entry
        if len(self.cache) > 60:
            self.cache.pop(next(iter(self.cache)))
        return entry

    def search(self, tag, name, vec, k=20):
        with self.lock:
            e = self._load(tag, name)
            if not e or not e["ids"]:
                return []
            k = min(k, len(e["ids"]))
            labels, dists = e["index"].knn_query(np.asarray([vec], dtype=np.float32), k=k)
            return [(e["ids"][l], float(1.0 - d)) for l, d in zip(labels[0], dists[0]) if l < len(e["ids"])]

    def add(self, tag, name, ids, vecs, save=True):
        with self.lock:
            e = self._load(tag, name, create=True)
            idx = e["index"]
            need = len(e["ids"]) + len(ids)
            if need > idx.get_max_elements():
                idx.resize_index(max(need + 256, int(idx.get_max_elements() * 1.5)))
            labels = []
            for eid in ids:
                if eid in e["pos"]:
                    labels.append(e["pos"][eid])
                else:
                    e["pos"][eid] = len(e["ids"])
                    labels.append(len(e["ids"]))
                    e["ids"].append(eid)
            idx.add_items(np.asarray(vecs, dtype=np.float32), np.array(labels))
            e["dirty"] = True
            if save:
                self.save(tag, name)

    def save(self, tag, name):
        with self.lock:
            e = self.cache.get((tag, name))
            if not e:
                return
            hp, ip = self._paths(tag, name)
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            e["index"].save_index(hp + ".tmp")
            np.save(ip + ".tmp.npy", np.array(e["ids"], dtype=object))
            os.replace(hp + ".tmp", hp)
            os.replace(ip + ".tmp.npy", ip)
            e["mtime"] = os.path.getmtime(hp)
            e["dirty"] = False


STORE = IndexStore()


# ---------------- keyword (FTS5 bm25) ----------------
_TOKEN = re.compile(r"\w+", re.UNICODE)


def fts_ranked(user_id, query, limit=30):
    """bm25-ranked FTS5 hits for any of the query tokens (rare words weigh more)."""
    toks = []
    for t in _TOKEN.findall(query or ""):
        if len(t) >= 3 and t.lower() not in toks:
            toks.append(t.lower())
    if not toks:
        return []
    expr = " OR ".join('"' + t.replace('"', '') + '"' for t in toks[:12])
    path = os.path.join(BASE_DIR, account_name(user_id) + ".db")
    try:
        conn = sqlite3.connect(path, timeout=10)
        try:
            rows = conn.execute(
                "SELECT event_id, bm25(events_fts) FROM events_fts WHERE events_fts MATCH ? ORDER BY bm25(events_fts) LIMIT ?",
                (expr, limit)).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    out, seen = [], set()
    for eid, score in rows:
        if eid not in seen:
            seen.add(eid)
            out.append((eid, float(-score)))
    return out


def rrf(*ranked_lists, k=RRF_K):
    """Reciprocal Rank Fusion. Each list is [(id, score), ...] best first."""
    fused = {}
    for lst in ranked_lists:
        for rank, (eid, _s) in enumerate(lst):
            fused[eid] = fused.get(eid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: -x[1])


def semantic_events(user_id, query, k=20, tag=None):
    tag = tag or active_tag()
    vec = embed([query], tag)[0]
    return STORE.search(tag, account_name(user_id), vec, k=k), vec


def search_l1(user_id, vec, k=3, tag=None):
    tag = tag or active_tag()
    return STORE.search(tag, account_name(user_id) + "__l1", vec, k=k)


def search_cubes(vec, k=3, tag=None):
    tag = tag or active_tag()
    return STORE.search(tag, "__cubes", vec, k=k)


# ---------------- (re)building ----------------
def _ensure_table(conn, table):
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (event_id TEXT PRIMARY KEY, created_at TEXT)")


def build_user(tag, fname, threads=None, batch=32, progress=None, max_items=None):
    """Embed events and L1 of one account db that are missing in this model's index."""
    name = fname[:-3]
    path = os.path.join(BASE_DIR, fname)
    table = MODELS[tag]["table"]
    done = 0
    conn = sqlite3.connect(path, timeout=30)
    try:
        _ensure_table(conn, table)
        try:
            rows = conn.execute(
                f"SELECT e.event_id, e.raw_dialogue FROM event_metadata e LEFT JOIN {table} v ON e.event_id=v.event_id "
                f"WHERE v.event_id IS NULL AND e.raw_dialogue IS NOT NULL AND e.raw_dialogue != ''").fetchall()
        except sqlite3.OperationalError:
            rows = []
        try:
            l1 = conn.execute(
                f"SELECT 'l1:' || s.rowid, coalesce(s.topic,'') || ': ' || coalesce(s.summary_text,'') FROM summary_l1 s "
                f"LEFT JOIN {table} v ON v.event_id = 'l1:' || s.rowid WHERE v.event_id IS NULL AND s.summary_text IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            l1 = []
        if max_items:
            rows = rows[:max_items]
        for target, items in ((name, rows), (name + "__l1", l1)):
            for i in range(0, len(items), batch):
                chunk = items[i:i + batch]
                vecs = embed([t for _, t in chunk], tag, threads=threads, batch_size=batch)
                STORE.add(tag, target, [e for e, _ in chunk], vecs, save=False)
                conn.executemany(f"INSERT OR REPLACE INTO {table} (event_id, created_at) VALUES (?, datetime('now'))",
                                 [(e,) for e, _ in chunk])
                done += len(chunk)
                if done % 512 < batch:
                    STORE.save(tag, target)
                    conn.commit()
                if progress:
                    progress(name, done)
            if items:
                STORE.save(tag, target)
                conn.commit()
    finally:
        conn.commit()
        conn.close()
    return done


def build_cubes(tag, threads=None):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "shared_master.db"), timeout=30)
    try:
        rows = conn.execute(
            "SELECT cube_id, coalesce(subject_action_object,'') || '. ' || coalesce(essence,'') || '. ' || coalesce(rules_markdown,'') "
            "FROM cubes_new WHERE status != 'deprecated' AND cube_id NOT LIKE 'cube_const_%'").fetchall()
    finally:
        conn.close()
    if not rows:
        return 0
    vecs = embed([t for _, t in rows], tag, threads=threads)
    STORE.add(tag, "__cubes", [c for c, _ in rows], vecs, save=True)
    return len(rows)


def account_files():
    out = []
    for f in os.listdir(BASE_DIR):
        if f.endswith(".db") and f != "shared_master.db" and "backup" not in f:
            out.append(f)
    # small accounts first, big test archives last
    return sorted(out, key=lambda f: os.path.getsize(os.path.join(BASE_DIR, f)))


def add_event_now(user_id, event_id, text):
    """Embed one new turn right away (API process is the only writer once switched)."""
    tag = active_tag()
    if tag == "bge" or os.path.exists(os.path.join(MODELS[tag]["dir"], "REBUILDING")):
        return False
    name = account_name(user_id)
    vec = embed([text], tag)
    STORE.add(tag, name, [event_id], vec, save=True)
    conn = sqlite3.connect(os.path.join(BASE_DIR, name + ".db"), timeout=30)
    try:
        _ensure_table(conn, MODELS[tag]["table"])
        conn.execute(f"INSERT OR REPLACE INTO {MODELS[tag]['table']} (event_id, created_at) VALUES (?, datetime('now'))", (event_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def build_pending_all(tag=None):
    tag = tag or active_tag()
    n = 0
    for f in account_files():
        n += build_user(tag, f)
    return n


if __name__ == "__main__":
    # python -m app.semantic [tag]  -> full (re)embed with progress file
    import sys
    tag = sys.argv[1] if len(sys.argv) > 1 else "mml12"
    d = MODELS[tag]["dir"]
    os.makedirs(d, exist_ok=True)
    flag = os.path.join(d, "REBUILDING")
    open(flag, "w").write(str(time.time()))
    prog_path = os.path.join(d, "progress.json")
    state = {"tag": tag, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "accounts": {}, "status": "running"}
    t0 = time.time()

    def progress(name, done):
        state["accounts"][name] = done
        state["elapsed_s"] = round(time.time() - t0, 1)
        with open(prog_path + ".tmp", "w") as f:
            json.dump(state, f)
        os.replace(prog_path + ".tmp", prog_path)

    try:
        for f in account_files():
            n = build_user(tag, f, threads=1, progress=progress)
            progress(f[:-3], n)
            print(f"[reembed] {f}: {n}", flush=True)
        state["cubes"] = build_cubes(tag, threads=1)
        # catch turns that arrived meanwhile
        for f in account_files():
            build_user(tag, f, threads=1)
        state["status"] = "done"
    except Exception as exc:
        state["status"] = "error: " + str(exc)
        raise
    finally:
        progress("_end", 0)
        try:
            os.remove(flag)
        except OSError:
            pass
