"""
SKV security helpers — password hashing, path safety, secrets from env.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Secrets / DB URL (never hardcode production credentials in source)
# ---------------------------------------------------------------------------

_LEGACY_SALTS = (
    "skv_default_salt_2026",
    "skv_secret_salt_2026",
)


def get_database_url() -> str:
    """Return DATABASE_URL from environment. Empty if unset (callers must handle)."""
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("SKV_DATABASE_URL")
        or ""
    ).strip()


def require_database_url() -> str:
    url = get_database_url()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it via environment / secrets."
        )
    return url


def get_resend_api_key() -> str:
    return (
        os.getenv("RESEND_API_KEY")
        or os.getenv("RESEND_KEY")
        or ""
    ).strip()


def get_skv_salt() -> str:
    """Pepper for legacy SHA-256 hashes only. Prefer bcrypt for new passwords."""
    return os.getenv("SKV_SALT", "").strip()


# ---------------------------------------------------------------------------
# Password hashing — bcrypt primary, legacy SHA-256+salt for migration
# ---------------------------------------------------------------------------

def _bcrypt_available() -> bool:
    try:
        import bcrypt  # noqa: F401
        return True
    except ImportError:
        return False


def hash_password(password: str) -> str:
    """Hash password with bcrypt (preferred) or PBKDF2-HMAC-SHA256."""
    if not password:
        raise ValueError("password required")
    if _bcrypt_available():
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
    # stdlib fallback
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return "pbkdf2_sha256$600000$" + salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against bcrypt, PBKDF2, or legacy SHA-256+salt hashes."""
    if not password or not stored_hash:
        return False
    stored = stored_hash.strip()

    # bcrypt
    if stored.startswith("$2a$") or stored.startswith("$2b$") or stored.startswith("$2y$"):
        if not _bcrypt_available():
            return False
        import bcrypt
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
        except Exception:
            return False

    # pbkdf2_sha256$iterations$salt_hex$dk_hex
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iters_s, salt_hex, dk_hex = stored.split("$", 3)
            iters = int(iters_s)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(dk_hex)
            got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
            return hmac.compare_digest(got, expected)
        except Exception:
            return False

    # Legacy: sha256(password + salt) hex digests
    if re.fullmatch(r"[0-9a-fA-F]{64}", stored):
        candidates = []
        pepper = get_skv_salt()
        if pepper:
            candidates.append(pepper)
        candidates.extend(_LEGACY_SALTS)
        candidates.append("")  # unsalted legacy
        for salt in candidates:
            digest = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
            if hmac.compare_digest(digest, stored.lower()):
                return True
        return False

    return False


def needs_rehash(stored_hash: str) -> bool:
    """True if hash should be upgraded to bcrypt on next successful login."""
    if not stored_hash:
        return True
    s = stored_hash.strip()
    return not (s.startswith("$2a$") or s.startswith("$2b$") or s.startswith("$2y$"))


def generate_confirmation_code(nbytes: int = 3) -> str:
    """Cryptographically random confirmation code (hex, uppercase)."""
    return secrets.token_hex(nbytes).upper()


def generate_api_token() -> str:
    return f"sk_{secrets.token_urlsafe(32)}"


# ---------------------------------------------------------------------------
# Path safety (path traversal)
# ---------------------------------------------------------------------------

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_@.\-]{1,128}$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._\-]{1,200}$")


def sanitize_path_component(value: str, *, allow_email: bool = False) -> str:
    """Reject path traversal and unsafe characters in user-controlled path segments."""
    if value is None:
        raise ValueError("empty path component")
    raw = str(value).strip()
    if not raw or raw in (".", "..") or "/" in raw or "\\" in raw or "\x00" in raw:
        raise ValueError("invalid path component")
    if ".." in raw:
        raise ValueError("invalid path component")
    if allow_email:
        if not re.fullmatch(r"[A-Za-z0-9_@.\+\-]{1,200}", raw):
            raise ValueError("invalid identifier")
        return raw
    if not _SAFE_ID_RE.fullmatch(raw):
        raise ValueError("invalid path component")
    return raw


def sanitize_filename(filename: str) -> str:
    """Allow only a simple basename — no directories."""
    if filename is None:
        raise ValueError("empty filename")
    name = os.path.basename(str(filename).strip())
    if not name or name in (".", "..") or ".." in name or "/" in name or "\\" in name:
        raise ValueError("invalid filename")
    if not _SAFE_FILENAME_RE.fullmatch(name):
        raise ValueError("invalid filename")
    return name


def safe_join(base_dir: str, *parts: str) -> str:
    """
    Join base_dir with sanitized parts and ensure result stays under base_dir.
    Raises ValueError on traversal attempts.
    """
    if not parts:
        raise ValueError("missing path parts")
    base = Path(base_dir).resolve()
    cleaned = [sanitize_path_component(p) for p in parts]
    target = base.joinpath(*cleaned).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("path escapes base directory") from None
    return str(target)


def safe_file_under(base_dir: str, filename: str) -> str:
    """Resolve filename under base_dir; reject traversal."""
    name = sanitize_filename(filename)
    base = Path(base_dir).resolve()
    target = (base / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("path escapes base directory") from None
    return str(target)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def extract_bearer_or_api_key(headers) -> str:
    """Extract token from Authorization Bearer or X-API-Key."""
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (headers.get("X-API-Key") or headers.get("x-api-key") or "").strip()


def constant_time_equals(a: str, b: str) -> bool:
    if a is None or b is None:
        return False
    return hmac.compare_digest(str(a), str(b))
