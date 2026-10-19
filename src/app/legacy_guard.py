"""Legacy write guard (pure ASGI, 2026-10-19).

Every write (POST/PUT/PATCH/DELETE) outside /api/v7 needs an owner API key (SKV_SHELL_OWNERS), except:
- one-time secret pages /s/<token> (vault),
- a short list of compute-only endpoints (LLM consult/bureau, formula check, sandboxed code with its own token check).
For those compute endpoints a JSON "user_id" is never trusted: it becomes the key's user, or "anonymous" without a key,
so they cannot write into someone else's sessions.
"""
import json
import os
import sqlite3

KEYS_DB = "/data/skv/metadata_store/shared_master.db"
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
OPEN_PREFIXES = ("/api/v7/", "/s/")
OPEN_EXACT = {"/api/v7"}
COMPUTE_EXACT = {
    "/api/consult", "/api/deepseek", "/api/bureau/think", "/api/constructor/think",
    "/api/validate/formula", "/api/anketa/generate", "/api/v4/search", "/api/v4/search_memory",
    "/api/exec",            # already returns 403 (disabled)
    "/api/execute/code",    # sandboxed python, own token check in v4 AuthMiddleware
}


def owner_ids():
    return {u.strip().lower() for u in os.environ.get("SKV_SHELL_OWNERS", "denizchavdarov@gmail.com").split(",") if u.strip()}


def _header(scope, name):
    name = name.lower().encode()
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return ""


def _user_for(key):
    if not key or key.startswith("skint_"):
        return None
    try:
        conn = sqlite3.connect(KEYS_DB, timeout=5)
        try:
            from app import api_keys as _ak
            return _ak.user_for(key, conn)
        finally:
            conn.close()
    except Exception as e:
        print(f"[LEGACY-GUARD] key lookup failed: {e}", flush=True)
        return None


async def _deny(send, status, detail):
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class LegacyWriteGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "") or "/"
        if method not in WRITE_METHODS or path in OPEN_EXACT or path.startswith(OPEN_PREFIXES):
            return await self.app(scope, receive, send)
        key = ""
        auth = _header(scope, "authorization")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        key = key or _header(scope, "x-api-key").strip()
        user = _user_for(key)
        norm = path.rstrip("/") or "/"
        if norm not in COMPUTE_EXACT:
            if user and user.lower() in owner_ids():
                return await self.app(scope, receive, send)
            print(f"[LEGACY-GUARD] blocked {method} {path} user={user or '-'}", flush=True)
            return await _deny(send, 403, "Legacy write endpoints are owner-only. Use /api/v7 with your API key.")
        # compute endpoint: never trust user_id from the body
        body = b""
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        ctype = _header(scope, "content-type").lower()
        if body and ("json" in ctype or not ctype):
            try:
                data = json.loads(body)
            except Exception:
                data = None
            if isinstance(data, dict) and "user_id" in data:
                data["user_id"] = user or "anonymous"
                body = json.dumps(data).encode()
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-length"] + [
                    (b"content-length", str(len(body)).encode())]
        sent = False

        async def new_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        return await self.app(scope, new_receive, send)
