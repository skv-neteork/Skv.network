"""API keys are stored hashed (api_key column = 'h1$' + sha256(key)); plaintext is shown only once.

Kinds:
  agent   — named key = one memory chain (user-facing)
  session — profile UI login token (one active per user; rotated on each login)
  legacy  — old keys kept working until the user revokes them

Lookups accept the plaintext key. Internal self-calls use short-lived signed tokens.
"""
import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid

MASTER_DB = "/data/skv/metadata_store/shared_master.db"
INTERNAL_TTL_S = 300
SESSION_NAME = "__session__"
PRIMARY_NAME = "main"
LEGACY_PRIMARY_NAMES = ("основная",)  # 2026-10-24: old default name, accepted as alias of "main"
MAX_AGENT_KEYS = 20
SQL_USER = ("SELECT user_id FROM user_api_keys WHERE api_key IN (?, ?) AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at > datetime('now')) UNION ALL SELECT ? WHERE ? IS NOT NULL LIMIT 1")
_secret = None
_NAME_RE = re.compile(r"^[\w\u0400-\u04FF][\w\u0400-\u04FF .,\-]{0,63}$", re.UNICODE)


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
            _secret = secrets.token_bytes(32)
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
    iu = internal_user(token)
    return (token or "", hash_key(token), iu, iu)


def args_keys_only(token):
    return (token or "", hash_key(token), None, None)


INTERNAL_DENY = ("/vault", "/profile", "/auth", "/account", "/sysperm")


def user_for(token, conn=None):
    if not token:
        return None
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=5)
    try:
        row = conn.execute(SQL_USER, args(token)).fetchone()
        if row:
            try:   # account init: base schema in the user DB (cached, once per process)
                from app.account_memory import ensure_user_db
                ensure_user_db(row[0])
            except Exception as exc:
                print(f"[api_keys] ensure_user_db skipped: {exc}", flush=True)
        return row[0] if row else None
    finally:
        if own:
            conn.close()


def ensure_schema(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_api_keys)")}
    for col, decl in (
        ("expires_at", "TEXT"),
        ("key_prefix", "TEXT"),
        ("label", "TEXT"),
        ("chain_id", "TEXT"),
        ("kind", "TEXT"),
        ("name", "TEXT"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE user_api_keys ADD COLUMN {col} {decl}")


def migrate(conn=None):
    """Hash every plaintext key in place. Idempotent."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        n = 0
        for rid, k in conn.execute("SELECT rowid, api_key FROM user_api_keys WHERE api_key NOT LIKE 'h1$%'").fetchall():
            conn.execute(
                "UPDATE user_api_keys SET api_key=?, key_prefix=COALESCE(key_prefix, ?) WHERE rowid=?",
                (hash_key(k), (k or "")[:7], rid),
            )
            n += 1
        conn.commit()
        return n
    finally:
        if own:
            conn.close()


def normalize_name(name):
    n = (name or "").strip()
    if not n or n == SESSION_NAME:
        raise ValueError("name required")
    if n in LEGACY_PRIMARY_NAMES:
        n = PRIMARY_NAME
    if not _NAME_RE.match(n):
        raise ValueError("name: 1–64 letters/digits/spaces/._- (latin or cyrillic)")
    return n


def _new_chain_id():
    return "ch_" + uuid.uuid4().hex[:16]


def _insert(conn, user_id, key, *, name, kind, chain_id, label=None):
    conn.execute(
        "INSERT INTO user_api_keys (user_id, api_key, is_active, created_at, key_prefix, label, chain_id, kind, name) "
        "VALUES (?,?,1,datetime('now'),?,?,?,?,?)",
        (user_id, hash_key(key), key[:7], label if label is not None else name, chain_id, kind, name),
    )


def issue(user_id, label="", conn=None, generate=None):
    """Backward-compatible create. Prefer issue_named / issue_session."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        key = generate() if generate else "sk_" + secrets.token_hex(16)
        kind = "session" if label in ("login", "session") else "agent"
        name = SESSION_NAME if kind == "session" else (label or PRIMARY_NAME)
        chain = "session" if kind == "session" else _new_chain_id()
        _insert(conn, user_id, key, name=name, kind=kind, chain_id=chain, label=label or name)
        if own:
            conn.commit()
        return key
    finally:
        if own:
            conn.close()


def issue_session(user_id, conn=None):
    """One active session key for the profile UI. Revokes previous session/login keys of kind session."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        conn.execute(
            "UPDATE user_api_keys SET is_active=0 WHERE user_id=? AND is_active=1 AND "
            "(kind='session' OR name=?)",
            (user_id, SESSION_NAME),
        )
        key = "sk_" + secrets.token_hex(16)
        _insert(conn, user_id, key, name=SESSION_NAME, kind="session", chain_id="session", label="session")
        if own:
            conn.commit()
        return key
    finally:
        if own:
            conn.close()


def issue_named(user_id, name, conn=None, chain_id=None):
    """Create an agent key for a new memory chain. Name must be unique among active agent keys."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        name = normalize_name(name)
        n_active = conn.execute(
            "SELECT COUNT(*) FROM user_api_keys WHERE user_id=? AND is_active=1 AND kind='agent'",
            (user_id,),
        ).fetchone()[0]
        if n_active >= MAX_AGENT_KEYS:
            raise ValueError(f"limit {MAX_AGENT_KEYS} agent keys")
        exists = conn.execute(
            "SELECT rowid FROM user_api_keys WHERE user_id=? AND is_active=1 AND kind='agent' AND lower(name)=lower(?)",
            (user_id, name),
        ).fetchone()
        if exists:
            raise ValueError("name already exists — use rotate to reissue under the same name")
        key = "sk_" + secrets.token_hex(16)
        cid = chain_id or _new_chain_id()
        _insert(conn, user_id, key, name=name, kind="agent", chain_id=cid, label=name)
        if own:
            conn.commit()
        return {"api_key": key, "name": name, "chain_id": cid, "prefix": key[:7]}
    finally:
        if own:
            conn.close()


def rotate(user_id, key_id=None, name=None, conn=None):
    """Revoke the active agent key and issue a new one under the same name and chain_id."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        row = None
        if key_id is not None:
            row = conn.execute(
                "SELECT rowid, name, chain_id, kind FROM user_api_keys WHERE rowid=? AND user_id=? AND is_active=1",
                (int(key_id), user_id),
            ).fetchone()
        elif name:
            name = normalize_name(name)
            row = conn.execute(
                "SELECT rowid, name, chain_id, kind FROM user_api_keys WHERE user_id=? AND is_active=1 "
                "AND kind='agent' AND lower(name)=lower(?) ORDER BY rowid DESC LIMIT 1",
                (user_id, name),
            ).fetchone()
        if not row:
            raise ValueError("key not found")
        rid, nm, cid, kind = row
        if kind == "session" or nm == SESSION_NAME:
            raise ValueError("cannot rotate session key here — sign in again")
        if kind not in ("agent", "legacy", None, ""):
            raise ValueError("only agent/legacy keys can be rotated")
        conn.execute("UPDATE user_api_keys SET is_active=0 WHERE rowid=?", (rid,))
        key = "sk_" + secrets.token_hex(16)
        new_name = nm if nm and nm != SESSION_NAME else PRIMARY_NAME
        new_cid = cid or _new_chain_id()
        _insert(conn, user_id, key, name=new_name, kind="agent", chain_id=new_cid, label=new_name)
        if own:
            conn.commit()
        return {"api_key": key, "name": new_name, "chain_id": new_cid, "prefix": key[:7], "revoked_id": rid}
    finally:
        if own:
            conn.close()


def revoke(user_id, key_id=None, key_token=None, conn=None):
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        n = 0
        if key_id is not None:
            cur = conn.execute(
                "UPDATE user_api_keys SET is_active=0 WHERE rowid=? AND user_id=? AND is_active=1",
                (int(key_id), user_id),
            )
            n = cur.rowcount
        elif key_token:
            m = re.search(r"#(\d+)$", (key_token or "").strip())
            if m:
                cur = conn.execute(
                    "UPDATE user_api_keys SET is_active=0 WHERE rowid=? AND user_id=? AND is_active=1",
                    (int(m.group(1)), user_id),
                )
                n = cur.rowcount
            else:
                cur = conn.execute(
                    "UPDATE user_api_keys SET is_active=0 WHERE api_key IN (?, ?) AND user_id=? AND is_active=1",
                    (key_token, hash_key(key_token), user_id),
                )
                n = cur.rowcount
        if own:
            conn.commit()
        return n
    finally:
        if own:
            conn.close()




def rename(user_id, key_id, new_name, conn=None):
    """Change display name of an agent/legacy key. Secret and chain_id stay the same."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        new_name = normalize_name(new_name)
        row = conn.execute(
            "SELECT rowid, name, kind, chain_id FROM user_api_keys WHERE rowid=? AND user_id=? AND is_active=1",
            (int(key_id), user_id),
        ).fetchone()
        if not row:
            raise ValueError("key not found")
        rid, old_name, kind, cid = row
        if kind == "session" or old_name == SESSION_NAME:
            raise ValueError("cannot rename session key")
        if kind not in ("agent", "legacy", None, ""):
            raise ValueError("only agent/legacy keys can be renamed")
        if (old_name or "").lower() == new_name.lower():
            return {"id": rid, "name": old_name, "chain_id": cid, "changed": False}
        clash = conn.execute(
            "SELECT rowid FROM user_api_keys WHERE user_id=? AND is_active=1 AND kind='agent' "
            "AND lower(name)=lower(?) AND rowid!=?",
            (user_id, new_name, rid),
        ).fetchone()
        if clash:
            raise ValueError("name already exists")
        # also block clash with active legacy names
        clash2 = conn.execute(
            "SELECT rowid FROM user_api_keys WHERE user_id=? AND is_active=1 "
            "AND lower(COALESCE(name,''))=lower(?) AND rowid!=?",
            (user_id, new_name, rid),
        ).fetchone()
        if clash2:
            raise ValueError("name already exists")
        conn.execute(
            "UPDATE user_api_keys SET name=?, label=?, kind='agent' WHERE rowid=?",
            (new_name, new_name, rid),
        )
        if own:
            conn.commit()
        return {"id": rid, "name": new_name, "chain_id": cid, "changed": True, "old_name": old_name}
    finally:
        if own:
            conn.close()

def display(prefix, rowid):
    return f"{prefix or 'sk_'}… #{rowid}"


def list_keys(user_id, conn=None, include_session=False):
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=5)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT rowid, key_prefix, is_active, created_at, expires_at, label, chain_id, kind, name "
            "FROM user_api_keys WHERE user_id=? ORDER BY "
            "CASE WHEN kind='agent' THEN 0 WHEN kind='legacy' THEN 1 ELSE 2 END, created_at, rowid",
            (user_id,),
        ).fetchall()
        out = []
        for rid, p, a, c, e, lab, cid, kind, name in rows:
            kind = kind or ("session" if lab in ("login", "session") or name == SESSION_NAME else "agent")
            if kind == "session" and not include_session:
                continue
            disp_name = name or lab or (PRIMARY_NAME if kind == "agent" else kind)
            item = {
                "id": rid,
                "key": display(p, rid),
                "prefix": p,
                "active": bool(a),
                "created": c,
                "expires": e,
                "label": lab,
                "name": disp_name,
                "chain_id": cid,
                "kind": kind,
            }
            if kind == "legacy":
                item["note"] = "старый ключ от входа — можно отозвать; для агентов используй именованный ключ"
            out.append(item)
        return out
    finally:
        if own:
            conn.close()


def migrate_named(conn=None):
    """Attach names/kinds/chain_ids to existing keys. Keeps all currently active keys working."""
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=30)
    try:
        ensure_schema(conn)
        users = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM user_api_keys").fetchall()]
        stats = {"users": 0, "named": 0, "legacy": 0, "session": 0}
        for uid in users:
            stats["users"] += 1
            rows = conn.execute(
                "SELECT rowid, label, name, kind, chain_id, is_active, created_at FROM user_api_keys "
                "WHERE user_id=? ORDER BY created_at, rowid",
                (uid,),
            ).fetchall()
            primary_set = False
            spare = 0
            for rid, lab, name, kind, cid, active, created in rows:
                lab = lab or ""
                if kind and name and cid:
                    if kind == "agent" and active and name == PRIMARY_NAME:
                        primary_set = True
                    continue
                if lab in ("login", "session") or name == SESSION_NAME or kind == "session":
                    if lab == "session" or kind == "session" or name == SESSION_NAME:
                        new_kind = "session"
                        new_name = SESSION_NAME
                        new_cid = "session"
                        stats["session"] += 1
                    else:
                        new_kind = "legacy"
                        day = (created or "")[:10] or str(rid)
                        new_name = f"login {day}"
                        new_cid = cid or _new_chain_id()
                        stats["legacy"] += 1
                    conn.execute(
                        "UPDATE user_api_keys SET kind=?, name=?, chain_id=COALESCE(chain_id, ?), "
                        "label=COALESCE(NULLIF(label,''), ?) WHERE rowid=?",
                        (new_kind, new_name, new_cid, new_name, rid),
                    )
                    continue
                new_kind = "agent"
                if not primary_set and active:
                    new_name = PRIMARY_NAME
                    primary_set = True
                elif name and name != SESSION_NAME:
                    new_name = name
                elif lab and lab not in ("profile", "register", "login", "session", "test"):
                    new_name = lab
                elif lab == "register" and not primary_set:
                    new_name = PRIMARY_NAME
                    primary_set = True
                else:
                    if active and not primary_set:
                        new_name = PRIMARY_NAME
                        primary_set = True
                    else:
                        spare += 1
                        new_name = f"archive {spare}" if not active else f"spare {spare}"
                new_cid = cid or _new_chain_id()
                conn.execute(
                    "UPDATE user_api_keys SET kind=?, name=?, chain_id=?, label=COALESCE(NULLIF(label,''), ?) WHERE rowid=?",
                    (new_kind, new_name, new_cid, new_name, rid),
                )
                stats["named"] += 1
            active_agent = conn.execute(
                "SELECT COUNT(*) FROM user_api_keys WHERE user_id=? AND is_active=1 AND kind='agent'",
                (uid,),
            ).fetchone()[0]
            if active_agent == 0:
                row = conn.execute(
                    "SELECT rowid FROM user_api_keys WHERE user_id=? AND is_active=1 "
                    "AND COALESCE(kind,'') != 'session' ORDER BY created_at, rowid LIMIT 1",
                    (uid,),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE user_api_keys SET kind='agent', name=?, chain_id=COALESCE(chain_id, ?), label=? WHERE rowid=?",
                        (PRIMARY_NAME, _new_chain_id(), PRIMARY_NAME, row[0]),
                    )
                    stats["named"] += 1
        conn.commit()
        return stats
    finally:
        if own:
            conn.close()


def chain_for_token(token, conn=None):
    """Return (user_id, chain_id, name, kind) for an active key."""
    if not token:
        return None
    own = conn is None
    conn = conn or sqlite3.connect(MASTER_DB, timeout=5)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT user_id, chain_id, name, kind FROM user_api_keys WHERE api_key IN (?, ?) AND is_active=1 "
            "AND (expires_at IS NULL OR expires_at > datetime('now')) LIMIT 1",
            (token, hash_key(token)),
        ).fetchone()
        if not row:
            iu = internal_user(token)
            return (iu, None, None, "internal") if iu else None
        return row
    finally:
        if own:
            conn.close()
