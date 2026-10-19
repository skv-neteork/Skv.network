"""SKV vault: encrypted per-user secrets, references in memory, one-time reveal links.

- Secrets are encrypted with AES-256-GCM. The master key is a separate file (not in /data/skv, not in backups of
  the data dir): SKV_VAULT_KEY_FILE, default /run/skv_vault/master.key (host /root/skv_vault, mounted read-only).
- Memory never stores the value. It stores a reference: [vault:<name>].
- Every use / reveal / change is logged in vault_log (no values).
- Reveal links: https://skv.network/s/<token>; only the token hash is stored; single open; default 5 min, max 60 min.
"""
import base64
import hashlib
import os
import re
import secrets
import sqlite3
import time

MASTER_DB = "/data/skv/metadata_store/shared_master.db"
KEY_FILE = os.environ.get("SKV_VAULT_KEY_FILE", "/run/skv_vault/master.key")
PUBLIC_BASE = os.environ.get("SKV_PUBLIC_BASE", "https://skv.network")
REVEAL_DEFAULT_S = 300
REVEAL_MAX_S = 3600
REVEAL_MAX_FAILS = 5
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")
REF_RX = re.compile(r"\[vault:([a-z0-9][a-z0-9_.\-]{0,63})\]")

_aead = None


def available():
    try:
        _cipher()
        return True
    except Exception:
        return False


def _cipher():
    global _aead
    if _aead is None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = base64.b64decode(open(KEY_FILE).read().strip())
        if len(raw) != 32:
            raise RuntimeError("vault master key must be 32 bytes")
        _aead = AESGCM(raw)
    return _aead


def _db():
    c = sqlite3.connect(MASTER_DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS vault_secrets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT, note TEXT,
        nonce BLOB, ct BLOB, key_version INTEGER DEFAULT 1, fingerprint TEXT, source_event_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_used_at TEXT, use_count INTEGER DEFAULT 0, UNIQUE(user_id, name))""")
    c.execute("""CREATE TABLE IF NOT EXISTS vault_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, user_id TEXT, name TEXT,
        action TEXT, purpose TEXT, ip TEXT, ok INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS vault_reveals (
        token_hash TEXT PRIMARY KEY, user_id TEXT, name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT, opened_at TEXT, require_login INTEGER DEFAULT 0, fails INTEGER DEFAULT 0, ip_open TEXT)""")
    cols = {r[1] for r in c.execute("PRAGMA table_info(vault_reveals)")}
    for col, ddl in (("payload_nonce", "BLOB"), ("payload_ct", "BLOB")):
        if col not in cols:
            c.execute(f"ALTER TABLE vault_reveals ADD COLUMN {col} {ddl}")
    c.execute("PRAGMA secure_delete=ON")
    return c


def log(user_id, name, action, purpose="", ip="", ok=True, conn=None):
    own = conn is None
    conn = conn or _db()
    try:
        conn.execute("INSERT INTO vault_log (user_id, name, action, purpose, ip, ok) VALUES (?,?,?,?,?,?)",
                     (user_id, name, action, (purpose or "")[:200], (ip or "")[:64], 1 if ok else 0))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _fp(value):
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def check_name(name):
    name = (name or "").strip().lower()
    if not NAME_RX.match(name):
        raise ValueError("name: 1-64 chars a-z 0-9 _ . - (start with a letter or digit)")
    return name


def put(user_id, name, value, kind="secret", note="", source_event_id=None, ip="", overwrite=True):
    name = check_name(name)
    if not value or len(value) > 16384:
        raise ValueError("value: 1-16384 chars")
    nonce = secrets.token_bytes(12)
    ct = _cipher().encrypt(nonce, value.encode(), f"{user_id}|{name}".encode())
    c = _db()
    try:
        ex = c.execute("SELECT fingerprint FROM vault_secrets WHERE user_id=? AND name=?", (user_id, name)).fetchone()
        if ex and not overwrite:
            return {"name": name, "status": "exists", "same_value": ex[0] == _fp(value)}
        c.execute("""INSERT INTO vault_secrets (user_id, name, kind, note, nonce, ct, fingerprint, source_event_id)
                     VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(user_id, name) DO UPDATE SET kind=excluded.kind, note=excluded.note,
                     nonce=excluded.nonce, ct=excluded.ct, fingerprint=excluded.fingerprint, updated_at=CURRENT_TIMESTAMP""",
                  (user_id, name, (kind or "secret")[:40], (note or "")[:300], nonce, ct, _fp(value), source_event_id))
        log(user_id, name, "update" if ex else "create", note, ip, True, c)
        c.commit()
        return {"name": name, "status": "updated" if ex else "created", "ref": f"[vault:{name}]"}
    finally:
        c.close()


def listing(user_id):
    c = _db()
    try:
        rows = c.execute("SELECT name, kind, note, created_at, updated_at, last_used_at, use_count, source_event_id FROM vault_secrets WHERE user_id=? ORDER BY name", (user_id,)).fetchall()
    finally:
        c.close()
    return [{"name": r[0], "ref": f"[vault:{r[0]}]", "kind": r[1], "note": r[2], "created_at": r[3], "updated_at": r[4],
             "last_used_at": r[5], "use_count": r[6], "from_event": r[7]} for r in rows]


def _get(c, user_id, name):
    row = c.execute("SELECT nonce, ct FROM vault_secrets WHERE user_id=? AND name=?", (user_id, name)).fetchone()
    if not row:
        return None
    return _cipher().decrypt(row[0], row[1], f"{user_id}|{name}".encode()).decode()


def use(user_id, name, purpose="", ip=""):
    name = check_name(name)
    c = _db()
    try:
        v = _get(c, user_id, name)
        log(user_id, name, "use", purpose, ip, v is not None, c)
        if v is not None:
            c.execute("UPDATE vault_secrets SET last_used_at=CURRENT_TIMESTAMP, use_count=use_count+1 WHERE user_id=? AND name=?", (user_id, name))
        c.commit()
        return v
    finally:
        c.close()


def delete(user_id, name, ip=""):
    name = check_name(name)
    c = _db()
    try:
        n = c.execute("DELETE FROM vault_secrets WHERE user_id=? AND name=?", (user_id, name)).rowcount
        c.execute("UPDATE vault_reveals SET opened_at='deleted' WHERE user_id=? AND name=? AND opened_at IS NULL", (user_id, name))
        log(user_id, name, "delete", "", ip, bool(n), c)
        c.commit()
        return bool(n)
    finally:
        c.close()


def history(user_id, limit=50):
    c = _db()
    try:
        rows = c.execute("SELECT ts, name, action, purpose, ip, ok FROM vault_log WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    finally:
        c.close()
    return [{"ts": r[0] + " UTC", "name": r[1], "action": r[2], "purpose": r[3], "ip": r[4], "ok": bool(r[5])} for r in rows]


# ---------------- reveal links ----------------
def _th(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_reveal(user_id, name, ttl_s=REVEAL_DEFAULT_S, require_login=False, ip=""):
    name = check_name(name)
    ttl = max(30, min(int(ttl_s or REVEAL_DEFAULT_S), REVEAL_MAX_S))
    c = _db()
    try:
        if not c.execute("SELECT 1 FROM vault_secrets WHERE user_id=? AND name=?", (user_id, name)).fetchone():
            return None
        token = secrets.token_urlsafe(24)
        c.execute("INSERT INTO vault_reveals (token_hash, user_id, name, expires_at, require_login) VALUES (?,?,?,datetime('now', ?),?)",
                  (_th(token), user_id, name, f"+{ttl} seconds", 1 if require_login else 0))
        exp = c.execute("SELECT expires_at FROM vault_reveals WHERE token_hash=?", (_th(token),)).fetchone()[0]
        log(user_id, name, "reveal_link", f"ttl={ttl}s login={bool(require_login)}", ip, True, c)
        c.commit()
        return {"url": f"{PUBLIC_BASE}/s/{token}", "expires_at": exp + " UTC", "ttl_s": ttl, "single_open": True, "require_login": bool(require_login)}
    finally:
        c.close()



def _payload_cipher(token):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(hashlib.sha256(b"skv-reveal-payload|" + token.encode()).digest())


def create_transient_reveal(user_id, label, value, ttl_s=REVEAL_DEFAULT_S, require_login=False, ip=""):
    """One-time payload that is NOT stored in vault_secrets. Ciphertext is wiped after open or expiry.
    The payload is encrypted with a key derived from the token itself, so deleting the row makes it unrecoverable."""
    label = check_name(label)
    if not value or len(value) > 16384:
        raise ValueError("value: 1-16384 chars")
    ttl = max(30, min(int(ttl_s or REVEAL_DEFAULT_S), REVEAL_MAX_S))
    token = secrets.token_urlsafe(24)
    nonce = secrets.token_bytes(12)
    ct = _payload_cipher(token).encrypt(nonce, value.encode(), f"transient|{user_id}|{label}".encode())
    c = _db()
    try:
        c.execute("INSERT INTO vault_reveals (token_hash, user_id, name, expires_at, require_login, payload_nonce, payload_ct) VALUES (?,?,?,datetime('now', ?),?,?,?)",
                  (_th(token), user_id, label, f"+{ttl} seconds", 1 if require_login else 0, nonce, ct))
        exp = c.execute("SELECT expires_at FROM vault_reveals WHERE token_hash=?", (_th(token),)).fetchone()[0]
        log(user_id, label, "reveal_link", f"transient ttl={ttl}s", ip, True, c)
        c.commit()
        return {"url": f"{PUBLIC_BASE}/s/{token}", "expires_at": exp + " UTC", "ttl_s": ttl, "single_open": True, "transient": True, "require_login": bool(require_login)}
    finally:
        c.close()


def wipe_transient(conn, th):
    """Overwrite ciphertext with zeros then NULL (secure_delete on), so the payload cannot be recovered."""
    row = conn.execute("SELECT length(payload_ct), length(payload_nonce) FROM vault_reveals WHERE token_hash=?", (th,)).fetchone()
    if not row or row[0] is None:
        return
    zc = b"\x00" * int(row[0]); zn = b"\x00" * int(row[1] or 0)
    conn.execute("UPDATE vault_reveals SET payload_ct=?, payload_nonce=? WHERE token_hash=?", (zc, zn, th))
    conn.execute("UPDATE vault_reveals SET payload_ct=NULL, payload_nonce=NULL WHERE token_hash=?", (th,))


def purge_expired_reveals():
    c = _db()
    try:
        rows = c.execute("SELECT token_hash FROM vault_reveals WHERE payload_ct IS NOT NULL AND (opened_at IS NOT NULL OR expires_at <= datetime('now'))").fetchall()
        for (th,) in rows:
            wipe_transient(c, th)
        c.commit()
        return len(rows)
    finally:
        c.close()


def reveal_state(token):
    c = _db()
    try:
        r = c.execute("SELECT user_id, name, expires_at > datetime('now'), opened_at, require_login FROM vault_reveals WHERE token_hash=?", (_th(token or ""),)).fetchone()
    finally:
        c.close()
    if not r or r[3] or not r[2]:
        return None
    return {"name": r[1], "require_login": bool(r[4])}


def open_reveal(token, email="", password="", ip=""):
    """Consume the link (single open) and return (status, value)."""
    th = _th(token or "")
    c = _db()
    try:
        r = c.execute("SELECT user_id, name, require_login, fails FROM vault_reveals WHERE token_hash=? AND opened_at IS NULL AND expires_at > datetime('now')", (th,)).fetchone()
        if not r:
            return "gone", None
        uid, name, need_login, fails = r
        if need_login:
            from app.security import verify_password
            row = c.execute("SELECT password_hash FROM users WHERE email=?", (uid,)).fetchone()
            if (email or "").strip().lower() != uid.lower() or not row or not verify_password(password or "", row[0] or ""):
                fails += 1
                burned = fails >= REVEAL_MAX_FAILS
                c.execute("UPDATE vault_reveals SET fails=?, opened_at=? WHERE token_hash=?", (fails, "burned" if burned else None, th))
                log(uid, name, "reveal_login_fail", f"fails={fails}", ip, False, c)
                c.commit()
                return ("burned" if burned else "login"), None
        n = c.execute("UPDATE vault_reveals SET opened_at=datetime('now'), ip_open=? WHERE token_hash=? AND opened_at IS NULL", ((ip or "")[:64], th)).rowcount
        if n != 1:
            return "gone", None
        pay = c.execute("SELECT payload_nonce, payload_ct FROM vault_reveals WHERE token_hash=?", (th,)).fetchone()
        if pay and pay[1] is not None:
            try:
                v = _payload_cipher(token).decrypt(pay[0], pay[1], f"transient|{uid}|{name}".encode()).decode()
            except Exception:
                v = None
            wipe_transient(c, th)
            log(uid, name, "reveal_open", "transient", ip, v is not None, c)
            c.commit()
            return ("ok", v) if v is not None else ("gone", None)
        v = _get(c, uid, name)
        log(uid, name, "reveal_open", "", ip, v is not None, c)
        c.commit()
        return ("ok", v) if v is not None else ("gone", None)
    finally:
        c.close()


# ---------------- auto-move secrets out of memory text ----------------
_AUTO = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), 0),
    ("skv_key", re.compile(r"\bsk_[A-Za-z0-9]{16,}\b"), 0),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"), 0),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), 0),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    ("bearer", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-]{16,})"), 1),
    (None, re.compile(r"(?i)\b(api[_-]?key|apikey|password|passwd|пароль|secret|token|ssh_pass|private[_-]?key)(\s*[:=]\s*)([\"']?)([^\s\"',;]{6,})"), 4),
]
_PLACEHOLDER = re.compile(r"(?i)^(\[|\$|<|\{|your_|xxx|\*\*\*|changeme|example|placeholder|none|null|true|false|masked)")


def scrub(user_id, text, source_event_id=None):
    """Replace secrets in text with [vault:name] and store them encrypted. Returns (text, [names])."""
    if not text or not isinstance(text, str) or not available():
        return text, []
    names = []

    def store(label, value):
        if not value or _PLACEHOLDER.match(value) or value.startswith("[vault:"):
            return None
        name = f"auto_{label}_{_fp(value)}"
        try:
            put(user_id, name, value, kind=label, note="moved from memory automatically", source_event_id=source_event_id, overwrite=False)
            names.append(name)
            return f"[vault:{name}]"
        except Exception as e:
            print(f"[vault] scrub skipped: {e}", flush=True)
            return None

    for label, rx, grp in _AUTO:
        def rep(m, label=label, grp=grp):
            g1 = m.group(1).lower() if label is None else ""
            lab = label or ("password" if g1 == "пароль" else re.sub(r"[^a-z0-9]+", "_", g1).strip("_") or "secret")
            val = m.group(grp)
            ref = store(lab, val)
            if not ref:
                return m.group(0)
            return m.group(0)[: m.start(grp) - m.start(0)] + ref + m.group(0)[m.end(grp) - m.start(0):]
        text = rx.sub(rep, text)
    return text, list(dict.fromkeys(names))
