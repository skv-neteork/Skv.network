"""SKV import → Google Drive queue.

Enqueue happens in import_dialogs.route_import_text (stubs + rows).
This module drains the queue:
  - list pending
  - complete(row, drive_url): set drive_url, status=done, replace [drive:pending:…] in memory
  - process: if /root/skv_drive/token.json (+ client) present, upload via Google API;
    otherwise return staging payloads for agent/MCP to upload then complete.

Heavy files stay on owner's Drive; SKV keeps link + description only.
Passwords never go here (vault). Staging under /data/skv/drive_staging/.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import time
import mimetypes
import urllib.request
from typing import Any, Optional

STAGING_ROOT = "/data/skv/drive_staging"
TOKEN_PATH = os.environ.get("SKV_DRIVE_TOKEN", "/root/skv_drive/token.json")
CLIENT_PATH = os.environ.get("SKV_DRIVE_CLIENT", "/root/skv_drive/client_secret.json")
META_BASE = "/data/skv/metadata_store"

_PENDING_RE = re.compile(r"\[drive:pending:([^\]]+)\]")


def _name(user_id: str) -> str:
    return "".join(c for c in (user_id or "") if c.isalnum() or c in ("_", "-"))


def _db_path(user_id: str) -> str:
    return os.path.join(META_BASE, _name(user_id) + ".db")


def _connect(user_id: str) -> sqlite3.Connection:
    path = _db_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS import_drive_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, source TEXT, event_id TEXT,
            kind TEXT, title TEXT, description TEXT,
            local_hint TEXT, drive_url TEXT, status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )
    return c


def stage_bytes(user_id: str, title: str, data: bytes, suffix: str = "") -> str:
    """Write payload to staging; return absolute path."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", (title or "blob"))[:80] or "blob"
    folder = os.path.join(STAGING_ROOT, _name(user_id) or "anon")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, f"{int(time.time())}_{safe}{suffix}")
    with open(path, "wb") as f:
        f.write(data or b"")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def list_queue(user_id: str, status: str = "pending", limit: int = 50) -> list[dict]:
    c = _connect(user_id)
    try:
        q = "SELECT * FROM import_drive_queue WHERE user_id=?"
        args: list[Any] = [user_id]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY id ASC LIMIT ?"
        args.append(int(limit))
        rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            hint = d.get("local_hint") or ""
            d["has_staging"] = hint.startswith("staging:") and os.path.isfile(hint[8:])
            d["has_url"] = bool(re.match(r"(?i)^https?://", hint))
            out.append(d)
        return out
    finally:
        c.close()


def _replace_stubs(user_id: str, pending_name: str, drive_url: str, event_id: str = "") -> int:
    """Replace [drive:pending:name] with [drive:url] in event_metadata (+ FTS if present)."""
    stub = f"[drive:pending:{pending_name}]"
    repl = f"[drive:{drive_url}]"
    c = _connect(user_id)
    n = 0
    try:
        if event_id:
            rows = c.execute(
                "SELECT event_id, raw_dialogue, essence FROM event_metadata WHERE event_id=?",
                (event_id,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT event_id, raw_dialogue, essence FROM event_metadata "
                "WHERE raw_dialogue LIKE ? OR essence LIKE ?",
                (f"%{stub}%", f"%{stub}%"),
            ).fetchall()
        for row in rows:
            eid, raw, ess = row[0], row[1] or "", row[2] or ""
            if stub not in raw and stub not in ess:
                continue
            new_raw = raw.replace(stub, repl)
            new_ess = ess.replace(stub, repl)
            c.execute(
                "UPDATE event_metadata SET raw_dialogue=?, essence=? WHERE event_id=?",
                (new_raw, new_ess, eid),
            )
            try:
                c.execute(
                    "UPDATE events_fts SET raw_dialogue=? WHERE event_id=?",
                    (new_raw, eid),
                )
            except sqlite3.Error:
                pass
            n += 1
        c.commit()
    finally:
        c.close()
    return n


def complete(
    user_id: str,
    queue_id: int,
    drive_url: str,
    drive_file_id: str = "",
) -> dict:
    """Mark queue row done and replace pending stub in memory."""
    drive_url = (drive_url or "").strip()
    if not drive_url:
        return {"ok": False, "error": "drive_url required"}
    c = _connect(user_id)
    try:
        row = c.execute(
            "SELECT * FROM import_drive_queue WHERE id=? AND user_id=?",
            (int(queue_id), user_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not found"}
        d = dict(row)
        if d.get("status") == "done" and d.get("drive_url"):
            return {"ok": True, "already": True, "item": d}
        title = d.get("title") or "file"
        # pending stub name matches title used at enqueue for url/datauri; fixed names for blobs
        pending_names = [title]
        kind = d.get("kind") or ""
        if kind == "data_uri":
            pending_names.append(title)  # datauri.mime
            pending_names.append(f"datauri_{title.split('.', 1)[-1]}" if "." in title else "datauri_bin")
        elif kind == "b64_blob":
            pending_names.append("b64_blob")
        elif kind == "large_message":
            pending_names.append("large_message")
        c.execute(
            "UPDATE import_drive_queue SET drive_url=?, status='done', "
            "description=CASE WHEN ?!='' THEN description||' id='||? ELSE description END, "
            "updated_at=datetime('now') WHERE id=?",
            (drive_url, drive_file_id, drive_file_id, int(queue_id)),
        )
        c.commit()
    finally:
        c.close()

    replaced = 0
    for name in pending_names:
        replaced += _replace_stubs(user_id, name, drive_url, event_id=d.get("event_id") or "")
    # also try basename of title (URL files)
    if "/" not in title and title not in pending_names:
        replaced += _replace_stubs(user_id, title, drive_url, event_id=d.get("event_id") or "")

    # cleanup staging file if any
    hint = d.get("local_hint") or ""
    if hint.startswith("staging:"):
        sp = hint[8:]
        try:
            if os.path.isfile(sp):
                os.remove(sp)
        except OSError:
            pass

    return {
        "ok": True,
        "id": int(queue_id),
        "drive_url": drive_url,
        "drive_file_id": drive_file_id or "",
        "stubs_replaced": replaced,
        "title": title,
        "kind": kind,
    }


def read_payload(user_id: str, queue_id: int, max_bytes: int = 8_000_000) -> dict:
    """Return bytes (base64) + mime guess for agent upload."""
    c = _connect(user_id)
    try:
        row = c.execute(
            "SELECT * FROM import_drive_queue WHERE id=? AND user_id=?",
            (int(queue_id), user_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not found"}
        d = dict(row)
    finally:
        c.close()
    hint = d.get("local_hint") or ""
    data = b""
    mime = "application/octet-stream"
    source = ""
    try:
        if hint.startswith("staging:") and os.path.isfile(hint[8:]):
            source = "staging"
            with open(hint[8:], "rb") as f:
                data = f.read(max_bytes + 1)
        elif re.match(r"(?i)^https?://", hint):
            source = "url"
            req = urllib.request.Request(hint, headers={"User-Agent": "SKV-DriveQueue/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                mime = resp.headers.get("Content-Type", mime).split(";")[0].strip() or mime
                data = resp.read(max_bytes + 1)
        elif hint.startswith("data:"):
            source = "data_uri"
            # rare: full data-uri kept in hint
            head, _, b64 = hint.partition(",")
            if ":" in head and ";" in head:
                mime = head.split(":", 1)[1].split(";", 1)[0] or mime
            data = base64.b64decode(b64 + "===")
        else:
            return {
                "ok": False,
                "error": "no_payload",
                "hint": hint[:120],
                "item": {k: d[k] for k in ("id", "kind", "title", "status", "event_id")},
            }
    except Exception as exc:
        return {"ok": False, "error": f"read_failed: {exc}", "item": {"id": d["id"], "title": d["title"]}}

    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    title = d.get("title") or "file"
    if mime == "application/octet-stream" and "." in title:
        guess, _ = mimetypes.guess_type(title)
        if guess:
            mime = guess
    return {
        "ok": True,
        "id": int(d["id"]),
        "title": title,
        "kind": d.get("kind"),
        "mime": mime,
        "source": source,
        "size": len(data),
        "truncated": truncated,
        "base64": base64.b64encode(data).decode("ascii"),
        "drive_folder": "SKV Import",
    }


def credentials_available() -> bool:
    return os.path.isfile(TOKEN_PATH) and os.path.isfile(CLIENT_PATH)


def _google_upload(folder_name: str, title: str, data: bytes, mime: str) -> dict:
    """Upload via google-api-python-client if installed + token present."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload
    except ImportError as exc:
        return {"ok": False, "error": f"google_api_missing: {exc}"}

    with open(TOKEN_PATH) as f:
        tok = json.load(f)
    with open(CLIENT_PATH) as f:
        client = json.load(f)
    installed = client.get("installed") or client.get("web") or client
    creds = Credentials(
        token=tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=tok.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=tok.get("client_id") or installed.get("client_id"),
        client_secret=tok.get("client_secret") or installed.get("client_secret"),
        scopes=tok.get("scopes") or ["https://www.googleapis.com/auth/drive.file"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        try:
            with open(TOKEN_PATH, "w") as f:
                json.dump({
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes or []),
                }, f)
        except OSError:
            pass

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    # find or create folder
    folder_id = None
    q = (
        "mimeType='application/vnd.google-apps.folder' and name=%r and trashed=false"
        % folder_name.replace("\\", "\\\\").replace("'", "\\'")
    )
    found = service.files().list(q=q, spaces="drive", fields="files(id,name)", pageSize=5).execute()
    files = found.get("files") or []
    if files:
        folder_id = files[0]["id"]
    else:
        meta = service.files().create(
            body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"},
            fields="id,webViewLink",
        ).execute()
        folder_id = meta["id"]

    body = {"name": title, "parents": [folder_id]}
    media = MediaInMemoryUpload(data, mimetype=mime or "application/octet-stream", resumable=False)
    created = service.files().create(body=body, media_body=media, fields="id,webViewLink,name").execute()
    return {
        "ok": True,
        "id": created.get("id"),
        "webViewLink": created.get("webViewLink") or f"https://drive.google.com/file/d/{created.get('id')}/view",
        "name": created.get("name"),
        "folder_id": folder_id,
    }


def process_one(user_id: str, queue_id: int, folder: str = "SKV Import") -> dict:
    """Try server-side Google upload for one row; else tell agent to upload."""
    if not credentials_available():
        payload = read_payload(user_id, queue_id)
        return {
            "ok": False,
            "need_agent_upload": True,
            "reason": "no_server_drive_credentials",
            "hint": "Place OAuth at /root/skv_drive/token.json + client_secret.json, "
                    "or upload via MCP user-Google-drive--skv then POST /import/drive/complete",
            "payload": payload if payload.get("ok") else payload,
        }
    payload = read_payload(user_id, queue_id)
    if not payload.get("ok"):
        return payload
    raw = base64.b64decode(payload["base64"])
    up = _google_upload(folder, payload["title"], raw, payload.get("mime") or "application/octet-stream")
    if not up.get("ok"):
        return up
    return complete(user_id, queue_id, up["webViewLink"], drive_file_id=up.get("id") or "")


def process_pending(user_id: str, limit: int = 10, folder: str = "SKV Import") -> dict:
    items = list_queue(user_id, status="pending", limit=limit)
    results = []
    for it in items:
        results.append(process_one(user_id, int(it["id"]), folder=folder))
    return {
        "ok": True,
        "credentials": credentials_available(),
        "pending": len(items),
        "results": results,
    }
