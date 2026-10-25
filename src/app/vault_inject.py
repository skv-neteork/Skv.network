"""Server-side secret inject. The agent never sees the value."""
import base64
import ipaddress
import socket
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from app import vault

ALLOWED = {"GET", "POST", "PUT", "PATCH", "DELETE"}
MAX_BODY = 8000
BLOCK = {
    "169.254.169.254", "metadata.google.internal", "fd00:ec2::254",
}


def _private(host):
    if not host or host.lower() in BLOCK:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return True
    return False


def _sub(text, name, secret):
    if not text:
        return ""
    return text.replace("[vault:%s]" % name, secret).replace("{{vault:%s}}" % name, secret)


def _scrub(text, secret, name):
    if not text or not secret:
        return text or ""
    ref = "[vault:%s]" % name
    out = text.replace(secret, ref)
    out = out.replace(urllib.parse.quote(secret, safe=""), ref)
    out = out.replace(urllib.parse.quote(secret, safe=""), ref)
    out = out.replace(base64.b64encode(secret.encode()).decode(), ref)
    return out


def inject(user_id, name, purpose, method, url, body="", headers=None, ip=""):
    name = vault.check_name(name)
    purpose = (purpose or "").strip()
    if not purpose:
        raise ValueError("purpose required")
    if len(purpose) > 200:
        raise ValueError("purpose too long")
    method = (method or "GET").upper()
    if method not in ALLOWED:
        raise ValueError("method must be GET POST PUT PATCH DELETE")
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("https url required")
    if parsed.port not in (None, 443):
        raise ValueError("port 443 only")
    if _private(parsed.hostname):
        raise ValueError("host blocked")
    c = vault._db()
    try:
        secret = vault._get(c, user_id, name)
        if secret is None:
            vault.log(user_id, name, "inject", purpose, ip, False, c)
            c.commit()
            return {"status": "fail", "reason": "no such secret"}
        vault.log(user_id, name, "inject_intent", purpose, ip, True, c)
        c.commit()
    finally:
        c.close()
    url2 = _sub(url, name, secret)
    body2 = _sub(body or "", name, secret)
    hdrs = {"User-Agent": "skv-vault-inject"}
    for k, v in (headers or {}).items():
        if str(k).lower() in ("host", "content-length"):
            continue
        hdrs[str(k)] = _sub(str(v), name, secret)
    data = body2.encode() if method != "GET" and body2 else None
    req = urllib.request.Request(url2, data=data, headers=hdrs, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler)
    try:
        with opener.open(req, timeout=20) as resp:
            raw = resp.read(MAX_BODY + 1)
            code = resp.status
    except Exception as e:
        msg = _scrub(str(e)[:300], secret, name)
        c = vault._db()
        try:
            vault.log(user_id, name, "inject_fail", purpose, ip, False, c)
            c.commit()
        finally:
            c.close()
        return {"status": "fail", "reason": msg}
    text = raw[:MAX_BODY].decode("utf-8", "replace")
    c = vault._db()
    try:
        vault.log(user_id, name, "inject_ok", purpose, ip, True, c)
        c.execute("UPDATE vault_secrets SET last_used_at=CURRENT_TIMESTAMP, use_count=use_count+1 WHERE user_id=? AND name=?", (user_id, name))
        c.commit()
    finally:
        c.close()
    return {"status": "ok", "code": code, "body": _scrub(text, secret, name), "truncated": len(raw) > MAX_BODY}
