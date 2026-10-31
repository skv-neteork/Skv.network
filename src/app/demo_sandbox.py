"""Public demo sandbox (2026-10-31).

One shared demo account (DEMO_USER) whose key lives server-side in DEMO_KEY_FILE (mode 600).
Guests reach it through the MCP URL https://skv.network/mcp/k/demo/ -- the key itself is never published.
- strict allowlist of /api/v7 paths (memory + agent loop only; no profile/keys/vault/consult/court/joint/import...),
- per-guest and global rate limits, small request bodies,
- memory wiped every day (DEMO_WIPE_HOUR_UTC) and on demand: python3 -m app.demo_sandbox wipe
Everything written here is visible to every other guest: it is a public sandbox, not private memory.
"""
import hmac
import os
import sqlite3
import threading
import time
from collections import defaultdict, deque

DEMO_USER = os.environ.get("SKV_DEMO_USER", "demo@skv.network")
DEMO_KEY_FILE = "/data/skv/.demo_key"
MASTER_DB = "/data/skv/metadata_store/shared_master.db"
DEMO_WIPE_HOUR_UTC = int(os.environ.get("SKV_DEMO_WIPE_HOUR_UTC", "1"))   # 04:00 MSK
MAX_BODY = 16_000
PER_CLIENT_MIN = 60
PER_CLIENT_DAY = 800
GLOBAL_DAY = 8000

ALLOW_EXACT = {
    "/memory", "/memory/start", "/memory/dig", "/memory/lens", "/memory/map", "/memory/search/date",
    "/memory/on_this_day", "/memory/source", "/memory/l2/blocks", "/memory/profile", "/memory/recall_later",
    "/search", "/remember", "/remember/batch",
    "/agent/remember", "/agent/memory", "/agent/turn", "/agent/step", "/agent/seal_next", "/agent/pack",
    "/agent/batch_flush", "/agent/feedback",
    "/session/bootstrap", "/session/step_zero",
    "/board", "/board/focus", "/board/relevant",
    "/constitution/status", "/constitution/install", "/experience/installed", "/reputation", "/feedback", "/shelves", "/inbox",
}
ALLOW_GET_PREFIXES = ("/cube/", "/memory/recall_later/", "/event/", "/skills/")
DENY_ALWAYS_PREFIXES = ("/profile", "/vault", "/auth", "/account", "/sysperm")

_key_cache = {"mtime": None, "key": ""}
_lock = threading.Lock()
_min = defaultdict(deque)
_day = defaultdict(deque)
_global = deque()


def demo_key():
    try:
        st = os.stat(DEMO_KEY_FILE)
    except OSError:
        return ""
    if _key_cache["mtime"] != st.st_mtime:
        try:
            with open(DEMO_KEY_FILE) as f:
                _key_cache["key"] = f.read().strip()
            _key_cache["mtime"] = st.st_mtime
        except OSError:
            return ""
    return _key_cache["key"]


def is_demo_key(key):
    dk = demo_key()
    return bool(key and dk) and hmac.compare_digest(key.strip(), dk)


def is_demo_user(user):
    return bool(user) and user == DEMO_USER


def check(sub, method, body_len, client):
    """Return None when allowed, else (status, detail)."""
    if sub.startswith(DENY_ALWAYS_PREFIXES):
        return 403, "Public demo key: profile, keys, vault and account endpoints are disabled. Get your own free key at https://skv.network/profile"
    allowed = sub in ALLOW_EXACT or (method == "GET" and sub.startswith(ALLOW_GET_PREFIXES))
    if not allowed:
        return 403, "Not available in the public demo sandbox (memory + agent loop only). Get your own free key at https://skv.network/profile"
    if body_len > MAX_BODY:
        return 413, "Public demo: request body too large (max 16 KB)"
    now = time.time()
    with _lock:
        for dq, win in ((_min[client], 60), (_day[client], 86400), (_global, 86400)):
            while dq and now - dq[0] > win:
                dq.popleft()
        if len(_min[client]) >= PER_CLIENT_MIN or len(_day[client]) >= PER_CLIENT_DAY:
            return 429, "Public demo rate limit reached. Get your own free key at https://skv.network/profile"
        if len(_global) >= GLOBAL_DAY:
            return 429, "Public demo is busy today. Get your own free key at https://skv.network/profile"
        _min[client].append(now)
        _day[client].append(now)
        _global.append(now)
        if len(_min) > 5000:   # bound memory
            for k in [k for k, v in _min.items() if not v][:2500]:
                _min.pop(k, None)
                _day.pop(k, None)
    return None


_FTS_SHADOW = ("_data", "_idx", "_content", "_docsize", "_config")


def wipe():
    """Delete everything the demo account wrote (own DB rows, vectors, shared-master rows). Keeps the account and key."""
    from app import shelves as _sh
    out = {"events": 0, "tables": 0, "master_rows": 0}
    conn = _sh.connect(DEMO_USER)
    ids = []
    try:
        try:
            ids = [r[0] for r in conn.execute("SELECT event_id FROM event_metadata")]
        except Exception:
            ids = []
        try:
            ids += [r[0] for r in conn.execute("SELECT event_id FROM event_forgotten")]
        except Exception:
            pass
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in names:
            if t.startswith("sqlite_") or ("_fts" in t and t.endswith(_FTS_SHADOW)):
                continue
            try:
                conn.execute(f'DELETE FROM "{t}"')
                out["tables"] += 1
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    out["events"] = len(ids)
    if ids:
        try:
            from app import semantic as _sem
            _sem.purge_vectors(DEMO_USER, ids)
        except Exception as exc:
            print(f"[demo] vector purge skipped: {exc}", flush=True)
    m = sqlite3.connect(MASTER_DB, timeout=30)
    try:
        for (t,) in m.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            if t in ("users", "user_api_keys") or t.startswith("sqlite_"):
                continue
            cols = [r[1] for r in m.execute(f'PRAGMA table_info("{t}")')]
            for c in ("user_id", "owner", "created_by", "author", "email"):
                if c in cols:
                    try:
                        out["master_rows"] += m.execute(f'DELETE FROM "{t}" WHERE "{c}"=?', (DEMO_USER,)).rowcount
                    except Exception:
                        pass
        m.commit()
    finally:
        m.close()
    try:
        from app.routers import v7_memory as _vm
        with _vm._cache_lock:
            _vm._search_cache.clear()
    except Exception:
        pass
    print(f"[demo] wiped: {out}", flush=True)
    return out


def _wipe_loop():
    while True:
        now = time.gmtime()
        secs = ((DEMO_WIPE_HOUR_UTC - now.tm_hour) % 24) * 3600 - now.tm_min * 60 - now.tm_sec
        if secs <= 0:
            secs += 86400
        time.sleep(secs)
        try:
            if demo_key():
                wipe()
        except Exception as exc:
            print(f"[demo] wipe error: {exc}", flush=True)
        time.sleep(60)


def start_wipe_thread():
    threading.Thread(target=_wipe_loop, name="skv-demo-wipe", daemon=True).start()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "wipe":
        print(wipe())
