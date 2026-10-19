"""API keys are stored hashed (api_key column = 'h1$' + sha256(key)); the plaintext is shown only once.
Lookups accept the plaintext key, so existing keys keep working after migration.
Internal self-calls (guardian tools calling /api/v7/*) use short-lived signed tokens instead of a stored key."""
import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time

MASTER_DB = "/data/skv/metadata_store/shared_master.db"
INTERNAL_TTL_S = 300
SQL_USER = ("SELECT user_id FROM user_api_keys WHERE api_key IN (?, ?) AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at > datetime('now')) UNION ALL SELECT ? WHERE ? IS NOT NULL LIMIT 1")
_secret = None


def hash_key(key):
    return "h1$" + hashlib.sha256((key or "").encode()).hexdigest()


def _internal_secret():
    global _secret
    if _secret is None:
        try:
            from app import vault
            raw = open(vault.KEY_FILE, "rb").read()
            _secret = hashlib.sha256(b"skv-internal-token|" + raw).digest()
        except Exception:
            _secret = secrets.token_bytes(32)   # per process; fine for the single uvicorn worker
    return _secret


def internal_token(user_id, ttl_s=INTERNAL_TTL_S):
    u = base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")
    exp = str(int(time.time()) + ttl_s)
    sig = hmac.new(_internal_secret(), f"{u}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"skint_{u}.{exp}.{sig}"


def internal_user(token):
    if not token or not token.startswith("skint_"):
        return None
    try:
        u, exp, sig = token[6:].split(".")
        good = hmac.new(_internal_secret(), f"{u}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        return base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode()
    except Exception:
        return None


def args(token):
    """Parameters for SQL_USER: plaintext, hash, internal user (twice)."""
    iu = internal_user(token)
    return (token or "", hash_key(token), iu, iu)


def args_keys_only(token):
    """Same as args() but internal tokens are not accepted (key management, account deletion)."""
    return (token or "", hash_key(token), None, None)


INTERNAL_DENY = ("/vault", "/profile", "/auth", "/account", "/sysperm")


def user_for(token, conn=None):
    if not token:
        return None
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=5)
    try:
        row = conn.execute(SQL_USER, args(token)).fetchone()
        return row[0] if row else None
    finally:
        if own:
            conn.close()


def ensure_schema(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_api_keys)")}
    for col in ("expires_at", "key_prefix", "label"):
        if col not in cols:
            conn.execute(f"ALTER TABLE user_api_keys ADD COLUMN {col} TEXT")


def migrate(conn=None):
    """Hash every plaintext key in place. Idempotent."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        n = 0
        for rid, k in conn.execute("SELECT rowid, api_key FROM user_api_keys WHERE api_key NOT LIKE 'h1$%'").fetchall():
            conn.execute("UPDATE user_api_keys SET api_key=?, key_prefix=COALESCE(key_prefix, ?) WHERE rowid=?", (hash_key(k), (k or "")[:7], rid))
            n += 1
        conn.commit()
        return n
    finally:
        if own:
            conn.close()


def issue(user_id, label="", conn=None, generate=None):
    """Create a key, store only its hash, return the plaintext once."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        key = generate() if generate else "sk_" + secrets.token_hex(16)
        conn.execute("INSERT INTO user_api_keys (user_id, api_key, is_active, created_at, key_prefix, label) VALUES (?,?,1,datetime('now'),?,?)",
                     (user_id, hash_key(key), key[:7], label or None))
        if own:
            conn.commit()
        return key
    finally:
        if own:
            conn.close()


def display(prefix, rowid):
    return f"{prefix or 'sk_'}… #{rowid}"
