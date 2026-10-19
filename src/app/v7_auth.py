"""V7 API-key enforcement (pure ASGI).

Every /api/v7/* request needs a valid API key, except a short list of public
docs/auth paths. The user is taken from the key: any user_id in the JSON body
or query string is overwritten. Key sources: Authorization: Bearer, X-API-Key,
?key= / ?k= (GET only, legacy agents), or "key" in a JSON body (legacy POSTs).
Guest web chat (POST /agent/chat without a key, user_id guest_*) stays open.
"""
import json
import sqlite3
from urllib.parse import parse_qsl, urlencode, unquote

KEYS_DB = "/data/skv/metadata_store/shared_master.db"
PREFIX = "/api/v7"

PUBLIC_EXACT = {
    "", "/",
    "/agent/prompt", "/agent/openapi.json", "/constitution", "/agent/guardian.py",
    "/start", "/skills", "/agent/start",
    "/auth/register", "/auth/confirm", "/auth/login",
    # these check the key themselves (header or body + password)
    "/profile", "/profile/keys", "/profile/delete",
}
PUBLIC_PREFIXES = ("/skills/", "/profile/keys/")


def _lookup_user(key):
    if not key:
        return None
    try:
        conn = sqlite3.connect(KEYS_DB, timeout=5)
        try:
            row = conn.execute(
                "SELECT user_id FROM user_api_keys WHERE api_key = ? AND is_active = 1 LIMIT 1",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[V7AUTH] db error: {e}", flush=True)
        raise


def _header(scope, name):
    name = name.lower().encode()
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return ""


async def _send_json(send, status, payload):
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"www-authenticate", b"Bearer"),
    ]})
    await send({"type": "http.response.body", "body": body})


class V7AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not (path == PREFIX or path.startswith(PREFIX + "/")):
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET").upper()
        sub = path[len(PREFIX):]
        if method in ("OPTIONS", "HEAD") or sub in PUBLIC_EXACT or sub.startswith(PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)

        # --- find the key ---
        key = ""
        auth = _header(scope, "authorization")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        if not key:
            key = _header(scope, "x-api-key").strip()
        query = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        if not key and method == "GET":
            q = dict(query)
            key = (q.get("key") or q.get("k") or "").strip()

        # read JSON body for POST/PUT/PATCH/DELETE
        body = b""
        data = None
        has_body = method in ("POST", "PUT", "PATCH", "DELETE")
        if has_body:
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
            if not key and isinstance(data, dict) and isinstance(data.get("key"), str):
                key = data["key"].strip()

        try:
            user = _lookup_user(key) if key else None
        except Exception:
            return await _send_json(send, 503, {"detail": "Auth database unavailable"})

        if key and not user:
            return await _send_json(send, 401, {"detail": "Invalid API key"})
        if not user:
            # guest web chat keeps working, but only for guest_* ids
            guest_ok = (method == "POST" and sub == "/agent/chat" and isinstance(data, dict)
                        and str(data.get("user_id") or "").startswith("guest_"))
            if not guest_ok:
                return await _send_json(send, 401, {"detail": "API key required. Send Authorization: Bearer sk_... Get yours at /profile"})
        else:
            # event detail: only your own events
            if sub.startswith("/event/"):
                eid = unquote(sub[len("/event/"):])
                if not eid.startswith(f"{user}::"):
                    return await _send_json(send, 404, {"detail": "Event not found"})
            # override user_id in query string
            query = [(k, v) for k, v in query if k != "user_id"] + [("user_id", user)]
            scope = dict(scope)
            scope["query_string"] = urlencode(query).encode()
            # override user_id in JSON body
            if isinstance(data, dict):
                data["user_id"] = user
                body = json.dumps(data).encode()
                scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-length"] + [
                    (b"content-length", str(len(body)).encode())]
            scope.setdefault("state", {})
            try:
                scope["state"]["user_id"] = user
            except Exception:
                pass

        if has_body:
            sent = False

            async def new_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
            return await self.app(scope, new_receive, send)
        return await self.app(scope, receive, send)
