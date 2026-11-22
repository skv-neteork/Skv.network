"""Compact tool map, delivered once per text hash. Not on every turn."""
import hashlib
import os
import sqlite3

# when -> which SKV tool. Version is the hash of this text.
MAP_TEXT = "\n".join([
    "when -> tool",
    "every reply -> turn",
    "past event -> memory_recall_later(query, search_as=[statement]) then memory_recall_status",
    "fast lines -> memory_search(lines=all)",
    "did we ship it -> board_list and the git commit",
    "reusable know-how -> cube_search then cube_get or cube_install",
    "new lesson -> cube_create, or duty=cube_nothing with a reason",
    "lasting rule -> profile op on the same turn",
    "session summary -> l1_summary; wider map -> l2_summary",
    "secret -> vault",
])

_DEFAULT_DB = "/data/skv/metadata_store/tool_map.db"


def text():
    return MAP_TEXT


def version():
    return hashlib.sha256(MAP_TEXT.encode("utf-8")).hexdigest()[:12]


def _db_path():
    return os.environ.get("SKV_TOOL_MAP_DB") or _DEFAULT_DB


def _key(user):
    return hashlib.sha256((user or "").strip().lower().encode()).hexdigest()[:16]


def _conn():
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS tool_map_seen (user_key TEXT PRIMARY KEY, version TEXT)")
    return c


def due(user):
    """True when this account has not been shown the current hash."""
    if not user:
        return False
    try:
        c = _conn()
        try:
            row = c.execute("SELECT version FROM tool_map_seen WHERE user_key=?", (_key(user),)).fetchone()
        finally:
            c.close()
    except Exception:
        return False
    return (not row) or (row[0] or "") != version()


def mark(user):
    try:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO tool_map_seen (user_key, version) VALUES (?,?) "
                "ON CONFLICT(user_key) DO UPDATE SET version=excluded.version",
                (_key(user), version()),
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        return


def apply(result, user):
    """Attach tool_map once per version. A failure leaves the turn unchanged."""
    if not isinstance(result, dict) or not user or result.get("tool_map"):
        return result
    try:
        if not due(user):
            return result
        result["tool_map"] = {"version": version(), "name": "skv-tool-map", "text": text()}
        mark(user)
    except Exception:
        return result
    return result
