"""Account feature status for Profile “My features”. Read-only. No new flags.

Missing tables count as zero. Status labels are exactly On, Off, Not set, Beta, or N/A.
Never returns secret values.
"""
import json
import os
import sqlite3

from app.feature_offer import (
    CHROME_NOTE, CHROME_URL, DEMO_URL, FEATURES, IMPORT_EXAMPLE, TRY,
)

_SESSION_NAME = "__session__"


def _open(path):
    if not path or not os.path.exists(path):
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    except Exception:
        return None


def _scalar(conn, sql, args=()):
    if conn is None:
        return 0
    try:
        row = conn.execute(sql, args).fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _recall_on(config_path):
    if config_path is None:
        try:
            from app.memory_v2 import config
            return bool(config().get("recall_later_enabled", True))
        except Exception:
            return True
    if not os.path.exists(config_path):
        return True
    try:
        raw = json.load(open(config_path, encoding="utf-8"))
    except Exception:
        return True
    if isinstance(raw, dict) and "recall_later_enabled" in raw:
        return bool(raw.get("recall_later_enabled"))
    return True


def _memory_key_count(conn, user_id):
    if conn is None:
        return 0
    try:
        rows = conn.execute(
            "SELECT COALESCE(is_active,1), COALESCE(kind,''), COALESCE(label,''), COALESCE(name,'') "
            "FROM user_api_keys WHERE user_id=?",
            (user_id,),
        ).fetchall()
    except Exception:
        return 0
    n = 0
    for active, kind, label, name in rows:
        if not active:
            continue
        kind = kind or ("session" if label in ("login", "session") or name == _SESSION_NAME else "agent")
        if kind in ("agent", "legacy"):
            n += 1
    return n


def _agents_on_one_key(conn):
    if conn is None:
        return 0
    try:
        rows = conn.execute("SELECT COUNT(*) FROM agents GROUP BY key_id").fetchall()
    except Exception:
        return 0
    return max((int(r[0] or 0) for r in rows), default=0)


def _constitution_on(conn):
    if conn is None:
        return False
    try:
        row = conn.execute("SELECT installed_at FROM constitution_state WHERE id=1").fetchone()
    except Exception:
        return False
    return bool(row and row[0])


def _seal_on(conn, user_id, installed_by=""):
    """On when this account's seal counter is positive.

    rest_turn stores the counter under constitution installed_by (usually the
    account id) or, before that, a hash of the key. The key hash is not
    recoverable here, so only the account id and installed_by are matched.
    """
    if conn is None:
        return False
    for uid in {user_id or "", installed_by or ""}:
        if uid and _scalar(conn, "SELECT n FROM ctr WHERE user=?", (uid,)) > 0:
            return True
    return False


def account_features(user_id, *, user_db=None, shared_db=None, seal_db=None, config_path=None):
    """Return the ten feature cards. Paths default to the live metadata store."""
    user_id = user_id or ""
    if user_db is None and user_id:
        from app.account_memory import account_db_name
        user_db = os.path.join("/data/skv/metadata_store", account_db_name(user_id) + ".db")
    if shared_db is None:
        shared_db = "/data/skv/metadata_store/shared_master.db"
    if seal_db is None:
        seal_db = "/data/skv/metadata_store/seal_counter.db"

    user = _open(user_db)
    shared = _open(shared_db)
    seal = _open(seal_db)
    try:
        keys = _memory_key_count(shared, user_id)
        imports = _scalar(user, "SELECT COUNT(*) FROM event_metadata WHERE kind='import'")
        agents = _agents_on_one_key(user)
        const_on = _constitution_on(user)
        installed_by = ""
        if user is not None:
            try:
                row = user.execute("SELECT installed_by FROM constitution_state WHERE id=1").fetchone()
                installed_by = (row[0] or "") if row else ""
            except Exception:
                installed_by = ""
        vault_n = _scalar(shared, "SELECT COUNT(*) FROM vault_secrets WHERE user_id=?", (user_id,))
        installed = _scalar(user, "SELECT COUNT(*) FROM chain_skills")
        published = _scalar(
            shared,
            "SELECT COUNT(*) FROM cubes_new WHERE lower(COALESCE(created_by,''))=lower(?)",
            (user_id,),
        )
        sealed = _seal_on(seal, user_id, installed_by)
        recall = _recall_on(config_path)
    finally:
        for conn in (user, shared, seal):
            if conn is not None:
                conn.close()

    status = {
        "memory": ("On" if keys >= 1 else "Not set", "Create a key on this page, then open Connect." if keys < 1 else ""),
        "chrome": ("Beta", CHROME_NOTE),
        "import": ("On" if imports else "Not set", ""),
        "lines": (
            "On" if keys >= 2 or agents >= 2 else "Not set",
            "" if keys >= 2 or agents >= 2 else "Create a second key, or have the agent call identify(name).",
        ),
        "recall": ("On" if recall else "Off", ""),
        "seal": ("On" if sealed else "Not set", ""),
        "constitution": ("On" if const_on else "Off", ""),
        "vault": ("On" if vault_n else "Not set", "%d name%s" % (vault_n, "" if vault_n == 1 else "s")),
        "cubes": ("On" if (installed or published) else "Not set", ""),
        "demo": ("N/A", "Shared, wiped daily, nothing private."),
    }
    cards = []
    for fid, name, anchor, benefit, try_key, action in FEATURES:
        st, detail = status[fid]
        card = {
            "id": fid,
            "name": name,
            "benefit": benefit,
            "status": st,
            "try_prompt": TRY.get(try_key, ""),
            "learn": "/features#" + anchor,
            "action": action,
            "detail": detail,
        }
        if fid == "chrome":
            card["href"] = CHROME_URL
        if fid == "demo":
            card["href"] = DEMO_URL
        if fid == "import":
            card["example"] = IMPORT_EXAMPLE
        cards.append(card)
    return {"ok": True, "features": cards}
