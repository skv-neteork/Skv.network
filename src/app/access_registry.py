"""Permanent non-secret registry «Доступы».

One table, access_registry, in the account database. It is not a board task,
not a profile row, and not a source_links row.

profile_rows / profile_log store lasting rules and their audit. source_links
point L1, L2, critical facts and board items at events. The board pin protects
only the constitution note n_pin_turn; other board items can be closed or
removed. None of those is an inventory of accesses, so this table is the only
source.

The server sets owner_id and chain_id. A listed row is not permission to act.
An agent has no delete. A server administrator can drop the table; this is not
a promise against the operator.

The locator is only [vault:name] or [conn:name]. Secrets stay in the vault.

Migration is ensure(): CREATE TABLE IF NOT EXISTS. It adds the table and the
index. It does not copy, rewrite, or delete existing rows.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from app.memory_v2 import mask_text

STATUSES = ("unchecked", "ok", "failed")
NOTE = (
    "A listed access is not permission to act. "
    "An agent cannot delete these rows. A server administrator can."
)
NO_LINE = "ABSENT: this key has no memory line; registry rows were not listed."
EMPTY_LINE = "ABSENT: no access rows on this memory line."
_LOCATOR = re.compile(r"^\[(vault|conn):([a-z0-9][a-z0-9_.\-]{0,63})\]$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A leading plus, or 10 digits in a row. Dates such as 2026-11-09 do not match.
_PHONE = re.compile(r"(?<!\d)(?:\+\d[\d\s().\-]{8,}\d|\d{10,})(?!\d)")
_URL = re.compile(r"(?i)\bhttps?://")
_TOKEN_URL = re.compile(r"(?i)(?:access_token|api[_-]?key|refresh_token|id_token)=")
_FINGERPRINT = re.compile(
    r"(?i)(?:sha-?256:[0-9a-f:]{16,}|(?:[0-9a-f]{2}:){7,}[0-9a-f]{2}|ssh-(?:rsa|ed25519)\s+\S+)"
)


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS access_registry (
            access_id TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            purpose TEXT NOT NULL,
            locator TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT,
            confirmed_at TEXT,
            scope TEXT NOT NULL DEFAULT '',
            basis TEXT NOT NULL DEFAULT '',
            owner_id TEXT NOT NULL,
            chain_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_access_registry_line ON access_registry(owner_id, chain_id)"
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _bound(text: str, n: int, name: str) -> str:
    """Collapse whitespace. Refuse a value that would be cut off."""
    text = " ".join((text or "").split())
    if len(text) > n:
        raise ValueError(name + " is longer than " + str(n))
    return text


def rejection(text: str) -> str:
    """Category of a forbidden value, or '' when the text may be stored."""
    raw = text or ""
    if _EMAIL.search(raw):
        return "personal address"
    if _PHONE.search(raw):
        return "personal address"
    if _FINGERPRINT.search(raw):
        return "key fingerprint"
    if _TOKEN_URL.search(raw) or _URL.search(raw):
        return "token url" if _TOKEN_URL.search(raw) else "url"
    if mask_text(raw) != raw:
        return "secret"
    return ""


def _clean_fields(service: str, purpose: str, locator: str, scope: str, basis: str) -> Dict[str, str]:
    fields = {
        "service": _bound(service, 80, "service"),
        "purpose": _bound(purpose, 300, "purpose"),
        "locator": (locator or "").strip(),
        "scope": _bound(scope, 120, "scope"),
        "basis": _bound(basis, 300, "basis"),
    }
    if not fields["service"] or not fields["purpose"]:
        raise ValueError("service and purpose are required")
    if not _LOCATOR.match(fields["locator"]):
        raise ValueError("locator must be [vault:name] or [conn:name]")
    for name, value in fields.items():
        why = rejection(value)
        if why:
            raise ValueError("rejected: " + why)
    return fields


def _row(r: Sequence) -> Dict[str, str]:
    keys = (
        "access_id", "service", "purpose", "locator", "status",
        "checked_at", "confirmed_at", "scope", "basis", "owner_id", "chain_id",
        "created_at", "updated_at",
    )
    out = dict(zip(keys, r))
    out["permission"] = "listing is not permission to act"
    return out


def add(conn: sqlite3.Connection, owner_id: str, chain_id: str, *,
        service: str, purpose: str, locator: str, scope: str = "", basis: str = "",
        **_ignored) -> Dict[str, str]:
    """Insert or refresh one row. owner_id and chain_id come from the server.

    A second add with the same owner, line, service and locator updates the
    description and keeps the id. Extra keys, including an agent-supplied
    owner, are ignored.
    """
    if not (owner_id or "").strip() or not (chain_id or "").strip():
        raise ValueError("server must set owner and memory line")
    fields = _clean_fields(service, purpose, locator, scope, basis)
    ensure(conn)
    owner_id, chain_id = owner_id.strip(), chain_id.strip()
    cur = conn.execute(
        "SELECT access_id FROM access_registry WHERE owner_id=? AND chain_id=? AND service=? AND locator=?",
        (owner_id, chain_id, fields["service"], fields["locator"]),
    ).fetchone()
    now = _now()
    if cur:
        conn.execute(
            "UPDATE access_registry SET purpose=?, scope=?, basis=?, updated_at=? WHERE access_id=?",
            (fields["purpose"], fields["scope"], fields["basis"], now, cur[0]),
        )
        access_id = cur[0]
    else:
        access_id = "a_" + uuid.uuid4().hex[:8]
        conn.execute(
            """INSERT INTO access_registry
               (access_id, service, purpose, locator, status, checked_at, confirmed_at,
                scope, basis, owner_id, chain_id, created_at, updated_at)
               VALUES (?,?,?,?, 'unchecked', NULL, NULL, ?,?,?,?,?,?)""",
            (access_id, fields["service"], fields["purpose"], fields["locator"],
             fields["scope"], fields["basis"], owner_id, chain_id, now, now),
        )
    conn.commit()
    return get(conn, owner_id, chain_id, access_id)


def check(conn: sqlite3.Connection, owner_id: str, chain_id: str, access_id: str,
          status: str, basis: str) -> Dict[str, str]:
    """Record a check. ok also moves the last successful confirmation."""
    if status not in ("ok", "failed"):
        raise ValueError("check status must be ok or failed")
    why = rejection(basis or "")
    if why:
        raise ValueError("rejected: " + why)
    basis = _bound(basis, 300, "basis")
    if len(basis) < 3:
        raise ValueError("basis is required")
    ensure(conn)
    row = conn.execute(
        "SELECT confirmed_at FROM access_registry WHERE access_id=? AND owner_id=? AND chain_id=?",
        (access_id, owner_id, chain_id),
    ).fetchone()
    if not row:
        raise KeyError(access_id)
    now = _now()
    confirmed = now if status == "ok" else row[0]
    conn.execute(
        "UPDATE access_registry SET status=?, checked_at=?, confirmed_at=?, basis=?, updated_at=? "
        "WHERE access_id=? AND owner_id=? AND chain_id=?",
        (status, now, confirmed, basis, now, access_id, owner_id, chain_id),
    )
    conn.commit()
    return get(conn, owner_id, chain_id, access_id)


def get(conn: sqlite3.Connection, owner_id: str, chain_id: str, access_id: str) -> Dict[str, str]:
    ensure(conn)
    row = conn.execute(
        "SELECT access_id, service, purpose, locator, status, checked_at, confirmed_at, scope, basis, "
        "owner_id, chain_id, created_at, updated_at FROM access_registry "
        "WHERE access_id=? AND owner_id=? AND chain_id=?",
        (access_id, owner_id, chain_id),
    ).fetchone()
    if not row:
        raise KeyError(access_id)
    return _row(row)


def list_line(conn: sqlite3.Connection, owner_id: str, chain_id: str) -> List[Dict[str, str]]:
    """Rows of one owner and one memory line. No chain means no rows."""
    ensure(conn)
    if not (owner_id or "").strip() or not (chain_id or "").strip():
        return []
    rows = conn.execute(
        "SELECT access_id, service, purpose, locator, status, checked_at, confirmed_at, scope, basis, "
        "owner_id, chain_id, created_at, updated_at FROM access_registry "
        "WHERE owner_id=? AND chain_id=? ORDER BY service, access_id",
        (owner_id.strip(), chain_id.strip()),
    ).fetchall()
    return [_row(r) for r in rows]


def agent_delete(*_args, **_kwargs):
    raise PermissionError(
        "an agent cannot delete access registry rows; a server administrator can remove the table"
    )


def render_records(rows: Sequence[dict], omitted: Optional[Sequence[str]] = None) -> str:
    lines = [NOTE, "count: %d" % len(rows)]
    if omitted:
        lines.append("omitted: " + ",".join(omitted))
    for r in rows:
        lines.append(
            "- %(access_id)s service=%(service)s status=%(status)s locator=%(locator)s "
            "purpose=%(purpose)s scope=%(scope)s checked_at=%(checked)s confirmed_at=%(confirmed)s "
            "basis=%(basis)s" % {
                "access_id": r.get("access_id") or "",
                "service": r.get("service") or "",
                "status": r.get("status") or "",
                "locator": r.get("locator") or "",
                "purpose": r.get("purpose") or "",
                "scope": r.get("scope") or "",
                "checked": r.get("checked_at") or "-",
                "confirmed": r.get("confirmed_at") or "-",
                "basis": r.get("basis") or "",
            }
        )
    return "\n".join(lines)


def render_line(conn: sqlite3.Connection, owner_id: str, chain_id: str) -> str:
    if not (chain_id or "").strip():
        return ""
    rows = list_line(conn, owner_id, chain_id)
    if not rows:
        return NOTE + "\n" + EMPTY_LINE
    return render_records(rows)


def limit_text(rows: Sequence[dict], omitted: Optional[Sequence[str]], max_chars: int) -> dict:
    """Drop whole rows until the text fits. Never cut a row in half.

    If the omitted-id line itself is still longer than max_chars, over_cap is
    true and the ids stay whole.
    """
    shown = [dict(r) for r in rows]
    skipped = [str(x) for x in (omitted or []) if x]
    over = False
    text = render_records(shown, skipped)

    def _paint(over_flag: bool) -> str:
        body = render_records(shown, skipped)
        if over_flag:
            body += "\nover_cap: true"
        return body

    while shown and len(text) > max_chars:
        skipped.append(str(shown.pop()["access_id"]))
        text = _paint(False)
    if len(text) > max_chars:
        over = True
        text = _paint(True)
    return {"records": shown, "omitted": skipped, "text": text, "over_cap": over}


def task_ref(access_id: str) -> str:
    return "access:" + (access_id or "")


def pack_records(conn: sqlite3.Connection, owner_id: str, chain_id: str) -> List[dict]:
    """Whole records for a startup document. Absence is an explicit record."""
    if not (owner_id or "").strip() or not (chain_id or "").strip():
        body = "ABSENT: this key has no memory line; registry rows were not listed."
        return [{"id": "service_accesses:no_line", "layer": "service_access", "body": body}]
    rows = list_line(conn, owner_id, chain_id)
    if not rows:
        body = "ABSENT: no access rows on this memory line."
        return [{"id": "service_accesses:empty", "layer": "service_access", "body": body}]
    out = []
    for r in rows:
        body = render_records([r])
        out.append({"id": r["access_id"], "layer": "service_access", "body": body})
    return out


def open_account(owner_id: str) -> sqlite3.Connection:
    from app import shelves
    conn = shelves.connect(owner_id)
    ensure(conn)
    return conn
