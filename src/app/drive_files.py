"""Per-user Google Drive for files over 1 MB.

The account connects its own Google account. The refresh token lives in the
vault ([vault:drive_oauth]). SKV stores a link, the name, the size, the mime
type, a short description and a vector of that description. The file bytes
stay on Drive.

Scope is https://www.googleapis.com/auth/drive. drive.file cannot see a file
a person drops into a folder by hand, and Google has no folder-only scope.
After one lookup that finds or creates the folder named SKV, every list, read
and create is pinned to that folder or to the line folder SKV/<line name>.

Each memory line has its own subfolder. Another line of the same account, and
every other account, does not see the files. A heavy file with no connection
is not stored: the answer is to connect Drive.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
import urllib.parse
from typing import Any, Optional

log = logging.getLogger("skv.drive")

HEAVY_BYTES = 1_000_000  # strictly greater than 1 MB leaves memory
READ_DEFAULT = 256 * 1024
READ_MAX = 1_000_000
DAY_S = 86400
SKV_FOLDER = "SKV"
VAULT_NAME = "drive_oauth"
SCOPE = "https://www.googleapis.com/auth/drive"
CONNECT_HINT = "подключи Drive"
META_BASE = "/data/skv/metadata_store"
CALL_CHAIN: contextvars.ContextVar = contextvars.ContextVar("skv_drive_chain", default=None)

_SECRET_KEYS = {"token", "access_token", "refresh_token", "client_secret", "id_token", "client_secret_json"}
_TEXT_MIME = ("text/", "application/json", "application/xml", "application/javascript")


def db_path(user_id: str) -> str:
    name = "".join(c for c in (user_id or "") if c.isalnum() or c in ("_", "-")) or "anon"
    return os.path.join(META_BASE, name + ".db")


def line_folder_name(chain_id: str, chain_name: str = "") -> str:
    raw = (chain_name or chain_id or "main").strip()
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw).strip(" .")[:80]
    return safe or "main"


def child_query(folder_id: str) -> str:
    """Drive files.list query. Empty parent is refused: that would scan the whole disk."""
    folder_id = (folder_id or "").strip()
    if not folder_id:
        raise ValueError("list needs the SKV folder")
    safe = folder_id.replace("\\", "\\\\").replace("'", "\\'")
    return "'%s' in parents and trashed=false" % safe


def root_skv_query() -> str:
    """The only root lookup: the one folder named SKV. Nothing else at root is listed."""
    return "mimeType='application/vnd.google-apps.folder' and name='SKV' and 'root' in parents and trashed=false"


def auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    if not client_id or not redirect_uri:
        raise ValueError("oauth client id and redirect uri are required")
    q = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": state or "",
    })
    return "https://accounts.google.com/o/oauth2/v2/auth?" + q


def public(obj: Any) -> Any:
    """Drop token fields before a response or a log line."""
    if isinstance(obj, dict):
        return {k: public(v) for k, v in obj.items() if k not in _SECRET_KEYS}
    if isinstance(obj, list):
        return [public(x) for x in obj]
    return obj


def _hash_vec(text: str, dim: int = 32) -> list:
    vec = [0.0] * dim
    for word in re.findall(r"[a-z0-9]{3,}", (text or "").lower()):
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        vec[digest[0] % dim] += 1.0
        vec[digest[1] % dim] += 0.5
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 5) for x in vec]


def vector_of(text: str, embedder=None) -> list:
    if embedder is not None:
        try:
            raw = embedder(text or "")
            if raw is not None:
                return [round(float(x), 5) for x in list(raw)]
        except Exception as exc:
            log.info("drive embed fallback: %s", type(exc).__name__)
    try:
        from app import semantic as _sem
        vecs = _sem.embed([(text or "")[:1000]])
        row = vecs[0]
        return [round(float(x), 5) for x in list(row)]
    except Exception:
        return _hash_vec(text)


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _toks(text: str) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def pdf_to_text(data: bytes) -> str:
    """Pull literal strings from a simple PDF content stream. No third-party parser."""
    if not data:
        return ""
    parts = []
    for match in re.finditer(br"\((?:\\.|[^\\)]){0,2000}\)\s*Tj", data):
        raw = match.group(0)
        inner = raw[: raw.rfind(b")")][1:]
        inner = inner.replace(b"\\n", b"\n").replace(b"\\r", b"\r").replace(b"\\(", b"(").replace(b"\\)", b")")
        parts.append(inner.decode("latin1", "replace"))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _is_text(mime: str) -> bool:
    mime = (mime or "").lower()
    return mime.startswith(_TEXT_MIME) or mime in ("application/pdf",)


class MemTokens:
    """Test double. The vault wrapper is VaultTokens."""

    def __init__(self):
        self.data = {}

    def put(self, user_id: str, value: str) -> str:
        self.data[user_id] = value
        return "[vault:%s]" % VAULT_NAME

    def get(self, user_id: str) -> Optional[str]:
        return self.data.get(user_id)


class VaultTokens:
    def put(self, user_id: str, value: str) -> str:
        from app import vault
        saved = vault.put(user_id, VAULT_NAME, value, kind="oauth", note="Google Drive token for the SKV folder")
        return saved.get("ref") or ("[vault:%s]" % VAULT_NAME)

    def get(self, user_id: str) -> Optional[str]:
        from app import vault
        return vault.use(user_id, VAULT_NAME, purpose="drive folder sync")


class GoogleDrive:
    """REST client. Callers must pass a folder id from the SKV tree. Tokens stay in the vault store."""

    def __init__(self, access_token: str):
        self._token = access_token or ""

    def _req(self, url: str, method: str = "GET", body: Optional[bytes] = None, headers: Optional[dict] = None) -> dict:
        import urllib.request
        hdrs = {"Authorization": "Bearer " + self._token}
        if headers:
            hdrs.update(headers)
        request = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def ensure_folder(self, name: str, parent_id: Optional[str]) -> str:
        if parent_id:
            query = child_query(parent_id) + " and mimeType='application/vnd.google-apps.folder' and name='%s'" % name.replace("'", "\\'")
        else:
            if name != SKV_FOLDER:
                raise ValueError("root lookup is only the SKV folder")
            query = root_skv_query()
        found = self._req("https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode({
            "q": query, "fields": "files(id,name)", "pageSize": "5", "spaces": "drive",
        }))
        files = found.get("files") or []
        if files:
            return files[0]["id"]
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            meta["parents"] = [parent_id]
        created = self._req("https://www.googleapis.com/drive/v3/files", method="POST",
                            body=json.dumps(meta).encode("utf-8"),
                            headers={"Content-Type": "application/json"})
        return created["id"]

    def list_folder(self, folder_id: str) -> list:
        query = child_query(folder_id)
        found = self._req("https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode({
            "q": query,
            "fields": "files(id,name,mimeType,size,md5Checksum,modifiedTime,webViewLink)",
            "pageSize": "200",
            "spaces": "drive",
        }))
        out = []
        for item in found.get("files") or []:
            mime = item.get("mimeType") or ""
            out.append({
                "id": item.get("id"),
                "name": item.get("name") or "",
                "mime": mime,
                "kind": "folder" if mime == "application/vnd.google-apps.folder" else "file",
                "size": int(item.get("size") or 0),
                "md5": item.get("md5Checksum") or "",
                "modified": item.get("modifiedTime") or "",
                "web_link": item.get("webViewLink") or ("https://drive.google.com/file/d/%s/view" % item.get("id")),
            })
        return out

    def put(self, parent_id: str, name: str, data: bytes, mime: str) -> dict:
        child_query(parent_id)
        boundary = "skvdrive"
        meta = json.dumps({"name": name, "parents": [parent_id]}).encode("utf-8")
        body = b"".join([
            b"--" + boundary.encode() + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n",
            meta, b"\r\n--" + boundary.encode() + b"\r\nContent-Type: " + (mime or "application/octet-stream").encode() + b"\r\n\r\n",
            data or b"", b"\r\n--" + boundary.encode() + b"--",
        ])
        created = self._req(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType,size,md5Checksum,modifiedTime,webViewLink",
            method="POST", body=body, headers={"Content-Type": "multipart/related; boundary=%s" % boundary},
        )
        return {
            "id": created.get("id"),
            "name": created.get("name") or name,
            "mime": created.get("mimeType") or mime,
            "kind": "file",
            "size": int(created.get("size") or len(data or b"")),
            "md5": created.get("md5Checksum") or hashlib.md5(data or b"").hexdigest(),
            "modified": created.get("modifiedTime") or "",
            "web_link": created.get("webViewLink") or ("https://drive.google.com/file/d/%s/view" % created.get("id")),
        }

    def download(self, file_id: str, start: int = 0, end: Optional[int] = None) -> bytes:
        import urllib.request
        headers = {"Authorization": "Bearer " + self._token}
        if end is not None:
            headers["Range"] = "bytes=%s-%s" % (int(start), int(end) - 1)
        elif start:
            headers["Range"] = "bytes=%s-" % int(start)
        request = urllib.request.Request(
            "https://www.googleapis.com/drive/v3/files/%s?alt=media" % urllib.parse.quote(file_id),
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()


class MemoryDrive:
    """In-memory Drive. parent None is the disk root, used once to hold the SKV folder."""

    def __init__(self):
        self.nodes = {}
        self._n = 0

    def _new(self, kind, name, parent_id, data=b"", mime=""):
        self._n += 1
        node_id = "gd" + str(self._n)
        self.nodes[node_id] = {
            "id": node_id,
            "kind": kind,
            "name": name,
            "parent": parent_id,
            "data": bytes(data or b""),
            "mime": mime or ("application/vnd.google-apps.folder" if kind == "folder" else "application/octet-stream"),
            "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return node_id

    def ensure_folder(self, name: str, parent_id: Optional[str]) -> str:
        for node in self.nodes.values():
            if node["kind"] == "folder" and node["name"] == name and node["parent"] == parent_id:
                return node["id"]
        return self._new("folder", name, parent_id)

    def list_folder(self, folder_id: str) -> list:
        child_query(folder_id)
        out = []
        for node in self.nodes.values():
            if node["parent"] != folder_id:
                continue
            out.append(self._public_node(node))
        return out

    def put(self, parent_id: str, name: str, data: bytes, mime: str) -> dict:
        child_query(parent_id)
        node_id = self._new("file", name, parent_id, data, mime)
        return self._public_node(self.nodes[node_id])

    def replace(self, file_id: str, data: bytes, modified: str = "") -> dict:
        node = self.nodes[file_id]
        node["data"] = bytes(data or b"")
        node["modified"] = modified or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return self._public_node(node)

    def remove(self, file_id: str) -> None:
        self.nodes.pop(file_id, None)

    def download(self, file_id: str, start: int = 0, end: Optional[int] = None) -> bytes:
        data = self.nodes[file_id]["data"]
        if end is None:
            return data[start:]
        return data[start:end]

    def _public_node(self, node: dict) -> dict:
        data = node["data"]
        return {
            "id": node["id"],
            "name": node["name"],
            "mime": node["mime"],
            "kind": node["kind"],
            "size": len(data),
            "md5": hashlib.md5(data).hexdigest(),
            "modified": node["modified"],
            "web_link": "https://drive.google.com/file/d/%s/view" % node["id"],
        }


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS drive_account (
            user_id TEXT PRIMARY KEY, vault_ref TEXT, scope TEXT,
            skv_folder_id TEXT, connected_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS drive_lines (
            chain_id TEXT PRIMARY KEY, folder_id TEXT, folder_name TEXT,
            last_sync INTEGER DEFAULT 0, scanned_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS drive_files (
            chain_id TEXT, drive_file_id TEXT, name TEXT, size INTEGER, mime TEXT,
            description TEXT, description_source TEXT, md5 TEXT, modified_time TEXT,
            web_link TEXT, status TEXT, vector_json TEXT, event_id TEXT,
            memory_text TEXT, scanned_at TEXT,
            PRIMARY KEY (chain_id, drive_file_id))"""
    )


def _open(user_id: str, conn: Optional[sqlite3.Connection] = None) -> tuple:
    own = conn is None
    if own:
        os.makedirs(META_BASE, exist_ok=True)
        conn = sqlite3.connect(db_path(user_id), timeout=30)
        conn.row_factory = sqlite3.Row
    ensure(conn)
    return conn, own


def _table(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(row)


def connected(user_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Read-only. Does not create an account database."""
    own = conn is None
    try:
        if own:
            path = db_path(user_id)
            if not os.path.isfile(path):
                return False
            conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
        if not _table(conn, "drive_account"):
            return False
        row = conn.execute("SELECT vault_ref, skv_folder_id FROM drive_account WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row[0] and row[1])
    except sqlite3.Error:
        return False
    finally:
        if own and conn is not None:
            conn.close()


def _memory_text(link: str, name: str, size: int, mime: str, description: str) -> str:
    return "[drive:%s] %s | %s bytes | %s\n%s" % (link, name, int(size or 0), mime or "", (description or "")[:500])


def _write_event(conn, user_id: str, chain_id: str, event_id: str, text: str, tag: bool) -> None:
    try:
        # Do not create a short event_metadata. The account schema owns that table.
        if not _table(conn, "event_metadata"):
            return
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        conn.execute(
            "INSERT OR REPLACE INTO event_metadata (event_id, time_str, essence, raw_dialogue, status) VALUES (?,?,?,?,?)",
            (event_id, stamp, (text or "")[:200], text, "active"),
        )
    except sqlite3.Error as exc:
        log.info("drive memory row skipped: %s", type(exc).__name__)
        return
    if tag and user_id and chain_id and "::" in event_id:
        try:
            from app import memory_lines as lines
            lines.tag(user_id, chain_id, [event_id])
        except Exception as exc:
            log.info("drive line tag skipped: %s", type(exc).__name__)


def _upsert_file(conn, chain_id: str, meta: dict, description: str, source: str, embedder, user_id: str, tag: bool) -> dict:
    link = meta.get("web_link") or ("https://drive.google.com/file/d/%s/view" % meta["id"])
    memory = _memory_text(link, meta.get("name") or "", int(meta.get("size") or 0), meta.get("mime") or "", description)
    vec = vector_of(description or meta.get("name") or "", embedder)
    event_id = "%s::drive_%s" % (re.sub(r"[^a-z0-9_]", "", (user_id or "u").lower()) or "u", meta["id"])
    scanned = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    _write_event(conn, user_id, chain_id, event_id, memory, tag)
    conn.execute(
        """INSERT INTO drive_files (chain_id, drive_file_id, name, size, mime, description, description_source,
            md5, modified_time, web_link, status, vector_json, event_id, memory_text, scanned_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(chain_id, drive_file_id) DO UPDATE SET
            name=excluded.name, size=excluded.size, mime=excluded.mime, description=excluded.description,
            description_source=excluded.description_source, md5=excluded.md5, modified_time=excluded.modified_time,
            web_link=excluded.web_link, status=excluded.status, vector_json=excluded.vector_json,
            event_id=excluded.event_id, memory_text=excluded.memory_text, scanned_at=excluded.scanned_at""",
        (chain_id, meta["id"], meta.get("name") or "", int(meta.get("size") or 0), meta.get("mime") or "",
         description, source, meta.get("md5") or "", meta.get("modified") or "", link, "live",
         json.dumps(vec), event_id, memory, scanned),
    )
    return {"drive_file_id": meta["id"], "web_link": link, "event_id": event_id, "memory_text": memory, "vector": vec}


def _preview(client, meta: dict) -> str:
    mime = (meta.get("mime") or "").lower()
    try:
        raw = client.download(meta["id"], 0, 4096)
    except Exception:
        raw = b""
    if mime == "application/pdf" or raw[:4] == b"%PDF":
        text = pdf_to_text(raw)
    elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
        text = raw.decode("utf-8", "replace")
    else:
        text = ""
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        return "%s. %s" % (meta.get("name") or "file", text[:180])
    return "%s (%s, %s bytes)" % (meta.get("name") or "file", mime or "file", int(meta.get("size") or 0))


def _board_body(chain_id: str, chain_name: str, rows: list, scanned_at: str) -> str:
    lines = ["chain:%s" % chain_id, "Мой Drive — %s" % (chain_name or chain_id), "scanned: %s" % (scanned_at or "")]
    shown = 0
    for row in rows:
        if shown >= 30:
            break
        lines.append("- %s | %s bytes | %s | %s | %s" % (
            row[0], int(row[1] or 0), row[2], (row[3] or "")[:80], row[4] or ""))
        shown += 1
    extra = len(rows) - shown
    if extra > 0:
        lines.append("+%s more" % extra)
    return "\n".join(lines)[:2000]


def _refresh_board(user_id: str, chain_id: str, chain_name: str, conn, board_fn) -> None:
    if board_fn is False:
        return
    rows = conn.execute(
        "SELECT name, size, status, description, scanned_at FROM drive_files WHERE chain_id=? ORDER BY name",
        (chain_id,),
    ).fetchall()
    scanned = ""
    line = conn.execute("SELECT scanned_at FROM drive_lines WHERE chain_id=?", (chain_id,)).fetchone()
    if line:
        scanned = line[0] or ""
    body = _board_body(chain_id, chain_name, rows, scanned)
    item_id = "drv_" + hashlib.sha256(chain_id.encode("utf-8")).hexdigest()[:12]
    if board_fn is not None:
        board_fn(user_id, item_id, "Мой Drive", body)
        return
    try:
        from app import board as board_mod
        board_mod.act(user_id, item_id=item_id, action="update", title="Мой Drive", text=body, kind="resource")
    except Exception as exc:
        log.info("drive board skipped: %s", type(exc).__name__)


def connect_token(user_id: str, chain_id: str, chain_name: str, token_value: str, store, client,
                  conn: Optional[sqlite3.Connection] = None, embedder=None, board_fn=None, tag_line: bool = False,
                  now: Optional[float] = None) -> dict:
    """Save the token in the store and scan the line folder. The return value has no token."""
    if not token_value:
        return {"ok": False, "error": "token required"}
    ref = store.put(user_id, token_value)
    conn, own = _open(user_id, conn)
    try:
        root_id = client.ensure_folder(SKV_FOLDER, None)
        folder_name = line_folder_name(chain_id, chain_name)
        folder_id = client.ensure_folder(folder_name, root_id)
        conn.execute(
            "INSERT OR REPLACE INTO drive_account (user_id, vault_ref, scope, skv_folder_id, connected_at) VALUES (?,?,?,?,?)",
            (user_id, ref, SCOPE, root_id, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())),
        )
        conn.execute(
            "INSERT OR REPLACE INTO drive_lines (chain_id, folder_id, folder_name, last_sync, scanned_at) VALUES (?,?,?,?,?)",
            (chain_id, folder_id, folder_name, 0, ""),
        )
        conn.commit()
        log.info("drive connected vault=%s chain=%s", ref, chain_id)
        result = sync(user_id, chain_id, chain_name, client, conn=conn, embedder=embedder, board_fn=board_fn,
                      tag_line=tag_line, force=True, now=now)
        result["vault"] = ref
        result["scope"] = SCOPE
        result["folder"] = SKV_FOLDER + "/" + folder_name
        return public(result)
    finally:
        if own:
            conn.close()


def _line_folder(conn, client, chain_id: str, chain_name: str, user_id: str) -> Optional[str]:
    row = conn.execute("SELECT skv_folder_id FROM drive_account WHERE user_id=?", (user_id,)).fetchone()
    if not row or not row[0]:
        return None
    known = conn.execute("SELECT folder_id, folder_name FROM drive_lines WHERE chain_id=?", (chain_id,)).fetchone()
    if known and known[0]:
        return known[0]
    folder_name = line_folder_name(chain_id, chain_name)
    folder_id = client.ensure_folder(folder_name, row[0])
    conn.execute(
        "INSERT OR REPLACE INTO drive_lines (chain_id, folder_id, folder_name, last_sync, scanned_at) VALUES (?,?,?,?,?)",
        (chain_id, folder_id, folder_name, 0, ""),
    )
    return folder_id


def sync(user_id: str, chain_id: str, chain_name: str, client, conn: Optional[sqlite3.Connection] = None,
         embedder=None, board_fn=None, tag_line: bool = False, force: bool = False, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else float(now)
    conn, own = _open(user_id, conn)
    try:
        if not connected(user_id, conn):
            return {"ok": False, "error": "connect_drive", "hint": CONNECT_HINT,
                    "message": "Connect Drive to store files over 1 MB. " + CONNECT_HINT}
        line = conn.execute("SELECT last_sync FROM drive_lines WHERE chain_id=?", (chain_id,)).fetchone()
        if line and not force and (now - int(line[0] or 0)) < DAY_S:
            return {"ok": True, "skipped": True, "reason": "fresh", "chain_id": chain_id}
        folder_id = _line_folder(conn, client, chain_id, chain_name, user_id)
        if not folder_id:
            return {"ok": False, "error": "connect_drive", "hint": CONNECT_HINT}
        seen = []
        for meta in client.list_folder(folder_id):
            if meta.get("kind") == "folder" or (meta.get("mime") or "").endswith(".folder"):
                continue
            seen.append(meta["id"])
            prev = conn.execute(
                "SELECT md5, modified_time, description, description_source FROM drive_files WHERE chain_id=? AND drive_file_id=?",
                (chain_id, meta["id"]),
            ).fetchone()
            changed = (not prev) or prev[0] != (meta.get("md5") or "") or (prev[1] or "") != (meta.get("modified") or "")
            if not changed:
                conn.execute(
                    "UPDATE drive_files SET status='live', scanned_at=? WHERE chain_id=? AND drive_file_id=?",
                    (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)), chain_id, meta["id"]),
                )
                continue
            if prev and prev[3] == "given":
                description, source = prev[2] or "", "given"
            else:
                description, source = _preview(client, meta), "auto"
            _upsert_file(conn, chain_id, meta, description, source, embedder, user_id, tag_line)
        if seen:
            marks = ",".join("?" * len(seen))
            conn.execute(
                "UPDATE drive_files SET status='dead' WHERE chain_id=? AND status!='dead' AND drive_file_id NOT IN (%s)" % marks,
                (chain_id, *seen),
            )
        else:
            conn.execute("UPDATE drive_files SET status='dead' WHERE chain_id=? AND status!='dead'", (chain_id,))
        scanned = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
        conn.execute("UPDATE drive_lines SET last_sync=?, scanned_at=? WHERE chain_id=?", (int(now), scanned, chain_id))
        conn.commit()
        _refresh_board(user_id, chain_id, chain_name, conn, board_fn)
        conn.commit()
        live = conn.execute("SELECT count(*) FROM drive_files WHERE chain_id=? AND status='live'", (chain_id,)).fetchone()[0]
        dead = conn.execute("SELECT count(*) FROM drive_files WHERE chain_id=? AND status='dead'", (chain_id,)).fetchone()[0]
        return public({"ok": True, "chain_id": chain_id, "live": live, "dead": dead, "scanned_at": scanned})
    finally:
        if own:
            conn.close()


def place(user_id: str, chain_id: str, chain_name: str, content: bytes, name: str, description: str,
          mime: str = "application/octet-stream", client=None, conn: Optional[sqlite3.Connection] = None,
          embedder=None, board_fn=None, tag_line: bool = False, now: Optional[float] = None) -> dict:
    """Over 1 MB goes to the line folder. At or under 1 MB stays with the caller, not in this table."""
    content = content or b""
    size = len(content)
    if size <= HEAVY_BYTES:
        return {"ok": True, "where": "memory", "size": size, "name": name or "file",
                "description": description or "", "stored_in_db": False}
    conn, own = _open(user_id, conn)
    try:
        if client is None or not connected(user_id, conn):
            return {"ok": False, "error": "connect_drive", "hint": CONNECT_HINT,
                    "message": "This file is over 1 MB. Connect Drive to store it. " + CONNECT_HINT,
                    "stored_in_db": False}
        maybe = sync(user_id, chain_id, chain_name, client, conn=conn, embedder=embedder, board_fn=False,
                     tag_line=tag_line, force=False, now=now)
        if not maybe.get("ok") and maybe.get("error") == "connect_drive":
            return maybe
        folder_id = _line_folder(conn, client, chain_id, chain_name, user_id)
        meta = client.put(folder_id, name or "file", content, mime or "application/octet-stream")
        saved = _upsert_file(conn, chain_id, meta, description or _preview(client, meta), "given", embedder, user_id, tag_line)
        conn.commit()
        _refresh_board(user_id, chain_id, chain_name, conn, board_fn)
        conn.commit()
        return public({"ok": True, "where": "drive", "size": size, "name": meta.get("name") or name,
                       "web_link": saved["web_link"], "drive_file_id": saved["drive_file_id"],
                       "event_id": saved["event_id"], "vault": "[vault:%s]" % VAULT_NAME, "stored_in_db": False})
    finally:
        if own:
            conn.close()


def read_file(user_id: str, chain_id: str, file_id: str, start: int = 0, limit: int = READ_DEFAULT,
              client=None, conn: Optional[sqlite3.Connection] = None) -> dict:
    start = max(0, int(start or 0))
    limit = max(1, min(int(limit or READ_DEFAULT), READ_MAX))
    conn, own = _open(user_id, conn)
    try:
        row = conn.execute(
            "SELECT name, mime, size, status, web_link FROM drive_files WHERE chain_id=? AND drive_file_id=?",
            (chain_id, file_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        if row[3] == "dead":
            return {"ok": False, "error": "dead", "name": row[0]}
        if client is None:
            return {"ok": False, "error": "connect_drive", "hint": CONNECT_HINT}
        mime = row[1] or ""
        if mime == "application/pdf":
            raw = client.download(file_id, 0, min(int(row[2] or 0), 2_000_000) or None)
            text = pdf_to_text(raw)
            chunk = text[start:start + limit]
            return {"ok": True, "name": row[0], "mime": mime, "kind": "pdf", "text": chunk,
                    "next": start + limit if start + limit < len(text) else None, "web_link": row[4]}
        if mime.startswith("text/") or mime in ("application/json", "application/xml"):
            raw = client.download(file_id, start, start + limit + 1)
            text = raw.decode("utf-8", "replace")
            more = len(raw) > limit
            if more:
                text = text[:limit]
            return {"ok": True, "name": row[0], "mime": mime, "kind": "text", "text": text,
                    "next": start + limit if more else None, "web_link": row[4]}
        raw = client.download(file_id, start, start + limit + 1)
        more = len(raw) > limit
        chunk = raw[:limit]
        import base64
        return {"ok": True, "name": row[0], "mime": mime, "kind": "bytes",
                "base64": base64.b64encode(chunk).decode("ascii"),
                "next": start + limit if more else None, "web_link": row[4]}
    finally:
        if own:
            conn.close()


def search(user_id: str, chain_id: str, query: str, limit: int = 5, conn: Optional[sqlite3.Connection] = None) -> list:
    """Find this line's live files by description. Other chains and other databases are invisible."""
    query = (query or "").strip()
    if not query or not chain_id:
        return []
    own = conn is None
    if own:
        path = db_path(user_id)
        if not os.path.isfile(path):
            return []
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    try:
        if not _table(conn, "drive_files"):
            return []
        rows = conn.execute(
            """SELECT drive_file_id, name, size, mime, description, web_link, vector_json, event_id, memory_text, scanned_at
               FROM drive_files WHERE chain_id=? AND status='live'""",
            (chain_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if own:
            conn.close()
    qtoks = _toks(query)
    qvec = _hash_vec(query)
    scored = []
    for row in rows:
        description = row[4] or ""
        blob = description + " " + (row[1] or "")
        toks = _toks(blob)
        if not qtoks or not toks:
            overlap = 0.0
        else:
            overlap = len(qtoks & toks) / len(qtoks)
        try:
            vec = json.loads(row[6] or "[]")
        except Exception:
            vec = []
        cos = _cosine(qvec, vec) if len(vec) == len(qvec) else 0.0
        if query.lower() in blob.lower():
            overlap = 1.0
        score = overlap * 0.75 + cos * 0.25
        if score <= 0:
            continue
        scored.append((score, {
            "drive_file_id": row[0], "name": row[1], "size": row[2], "mime": row[3],
            "description": description, "web_link": row[5], "event_id": row[7],
            "memory_text": row[8] or "", "scanned_at": row[9] or "", "score": round(score, 4),
        }))
    scored.sort(key=lambda item: -item[0])
    return [item[1] for item in scored[: max(1, int(limit or 5))]]


def list_files(user_id: str, chain_id: str, conn: Optional[sqlite3.Connection] = None) -> dict:
    conn, own = _open(user_id, conn)
    try:
        line = conn.execute("SELECT folder_name, scanned_at FROM drive_lines WHERE chain_id=?", (chain_id,)).fetchone()
        rows = conn.execute(
            """SELECT name, size, description, status, scanned_at, web_link, drive_file_id
               FROM drive_files WHERE chain_id=? ORDER BY name""",
            (chain_id,),
        ).fetchall()
        files = [{"name": r[0], "size": r[1], "description": r[2], "status": r[3],
                  "scanned_at": r[4], "web_link": r[5], "drive_file_id": r[6]} for r in rows]
        return {"ok": True, "title": "Мой Drive", "chain_id": chain_id,
                "folder": (SKV_FOLDER + "/" + line[0]) if line else "",
                "scanned_at": line[1] if line else "", "files": files}
    finally:
        if own:
            conn.close()


def oauth_start(state: str = "") -> dict:
    client_id = (os.environ.get("SKV_DRIVE_OAUTH_CLIENT_ID") or "").strip()
    redirect = (os.environ.get("SKV_DRIVE_OAUTH_REDIRECT") or "").strip()
    if not client_id or not redirect:
        return {
            "ok": False,
            "error": "oauth_client_missing",
            "scope": SCOPE,
            "need": [
                "A Google OAuth client id and secret for this SKV server",
                "Redirect URI in SKV_DRIVE_OAUTH_REDIRECT",
                "Client id in SKV_DRIVE_OAUTH_CLIENT_ID",
                "The secret only in the vault or the server env, not in git",
                "Consent for scope " + SCOPE + " (the SKV folder only, enforced in code)",
            ],
        }
    return {"ok": True, "url": auth_url(client_id, redirect, state), "scope": SCOPE, "vault": "[vault:%s]" % VAULT_NAME}


def dump_text(conn: sqlite3.Connection) -> str:
    """Every stored column, for the test that the file bytes and the token are absent."""
    chunks = []
    for name in ("drive_account", "drive_lines", "drive_files", "event_metadata"):
        if not _table(conn, name):
            continue
        for row in conn.execute("SELECT * FROM %s" % name):
            chunks.append(" ".join("" if v is None else str(v) for v in row))
    return "\n".join(chunks)
