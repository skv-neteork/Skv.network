"""Additive room tables. Old events stay actor NULL: nothing is back-filled."""
import sqlite3

EVENT_COLUMNS = (
    ("actor_agent_id", "TEXT"),
    ("session_id", "TEXT"),
    ("ev_kind", "TEXT"),
    ("author_kind", "TEXT"),
    ("gist", "TEXT"),
)
BOARD_COLUMNS = (
    ("created_by", "TEXT DEFAULT ''"),
    ("claimed_by", "TEXT DEFAULT ''"),
    ("lease_until", "TEXT DEFAULT ''"),
    ("rev", "INTEGER DEFAULT 0"),
)


def _cols(conn, table):
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    except sqlite3.Error:
        return set()


def _add(conn, table, columns):
    have = _cols(conn, table)
    if not have:
        return False
    for name, ddl in columns:
        if name not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))
    return True


def ensure_event_columns(conn):
    """Stamp columns on event_metadata. NULL actor means legacy."""
    _add(conn, "event_metadata", EVENT_COLUMNS)
    conn.commit()


def ensure(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agents (
            id TEXT NOT NULL,
            key_id TEXT NOT NULL,
            chain_id TEXT NOT NULL,
            name TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            role TEXT NOT NULL,
            token_hash TEXT DEFAULT '',
            client_hint TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            PRIMARY KEY (key_id, id))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS step_zero_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT,
            session_id TEXT,
            sent_at TEXT,
            kind TEXT,
            starter_version TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_cursors (
            actor_id TEXT NOT NULL,
            chain_id TEXT NOT NULL,
            delivered_upto INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (actor_id, chain_id))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS resource_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id TEXT,
            path TEXT,
            actor_id TEXT,
            task_id TEXT,
            base_hash TEXT,
            lease_until TEXT,
            released_at TEXT,
            new_hash TEXT)"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_resource_open
           ON resource_claims(chain_id, path)
           WHERE released_at IS NULL OR released_at = ''"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_pack_seen (
            key_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            seen_at TEXT,
            PRIMARY KEY (key_id, actor_id))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS identify_misses (
            key_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            n INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (key_id, session_id))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS room_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            chain_id TEXT,
            key_id TEXT,
            actor_agent_id TEXT,
            session_id TEXT,
            ev_kind TEXT,
            author_kind TEXT,
            gist TEXT,
            essence TEXT,
            body TEXT,
            path TEXT,
            task_id TEXT,
            target_actor TEXT,
            created_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS room_touches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id TEXT,
            key_id TEXT,
            actor_id TEXT,
            path TEXT,
            task_id TEXT,
            at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS board_items (
            item_id TEXT PRIMARY KEY,
            kind TEXT,
            title TEXT,
            body TEXT,
            status TEXT,
            updated_at TEXT,
            removed INTEGER DEFAULT 0,
            important INTEGER DEFAULT 0,
            priority INTEGER DEFAULT 2,
            parent_id TEXT DEFAULT '',
            waiting_for TEXT DEFAULT '',
            result TEXT DEFAULT '',
            result_event TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            claimed_by TEXT DEFAULT '',
            lease_until TEXT DEFAULT '',
            rev INTEGER DEFAULT 0)"""
    )
    _add(conn, "event_metadata", EVENT_COLUMNS)
    _add(conn, "board_items", BOARD_COLUMNS)
    conn.commit()
    return conn
