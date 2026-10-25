"""Vault endpoints. /api/v7/vault* need the owner's API key (V7AuthMiddleware puts the key's user into ?user_id).
/s/<token> is the public one-time reveal page."""
import html

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app import vault

router = APIRouter()


def _uid(request: Request):
    uid = (request.query_params.get("user_id") or "").strip()
    if not uid or uid.startswith("guest_"):
        raise HTTPException(401, "API key required")
    return uid


def _ip(request: Request):
    h = request.headers
    return (h.get("x-real-ip") or (h.get("x-forwarded-for") or "").split(",")[0] or (request.client.host if request.client else "")).strip()


def _need():
    if not vault.available():
        raise HTTPException(503, "Vault is not configured on this server")


class VaultPut(BaseModel):
    name: str
    value: str
    kind: str = "secret"
    note: str = ""
    user_id: str = ""


class VaultName(BaseModel):
    name: str
    purpose: str = ""
    user_id: str = ""



class VaultTransient(BaseModel):
    label: str
    value: str
    ttl_s: int = vault.REVEAL_DEFAULT_S
    require_login: bool = False
    user_id: str = ""


@router.post("/api/v7/vault/reveal/transient")
async def vault_reveal_transient(req: VaultTransient, request: Request):
    """One-time payload that is NOT stored in the vault. Ciphertext is wiped after open or expiry. Owner only."""
    _need()
    uid = _uid(request)
    try:
        r = vault.create_transient_reveal(uid, req.label, req.value, req.ttl_s, req.require_login, _ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return r

class VaultReveal(BaseModel):
    name: str
    ttl_s: int = vault.REVEAL_DEFAULT_S
    require_login: bool = False
    user_id: str = ""


@router.get("/api/v7/vault")
async def vault_list(request: Request):
    """Names and metadata of your secrets. Values are never listed."""
    _need()
    uid = _uid(request)
    return {"secrets": vault.listing(uid), "how": {"inject": "POST /api/v7/vault/inject {name, purpose, method, url, body}", "reveal_link": "POST /api/v7/vault/reveal {name, ttl_s<=3600, require_login}",
            "store": "POST /api/v7/vault {name, value, kind, note}", "delete": "DELETE /api/v7/vault/<name>", "log": "GET /api/v7/vault/log"},
            "rule": "Memory keeps only [vault:<name>] references. Never paste a secret value into memory, chat or cubes."}


@router.post("/api/v7/vault")
async def vault_put(req: VaultPut, request: Request):
    _need()
    uid = _uid(request)
    try:
        return vault.put(uid, req.name, req.value, req.kind, req.note, ip=_ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e))


class VaultInject(BaseModel):
    name: str
    purpose: str
    method: str = "POST"
    url: str
    body: str = ""
    headers: dict = {}
    user_id: str = ""


@router.post("/api/v7/vault/inject")
async def vault_inject(req: VaultInject, request: Request):
    """Agent path. Server substitutes the secret and sends the request. Returns status only, never the value."""
    _need()
    uid = _uid(request)
    from app.vault_inject import inject
    try:
        return inject(uid, req.name, req.purpose, req.method, req.url, req.body, req.headers, _ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/api/v7/vault/use")
async def vault_use(req: VaultName, request: Request):
    """Closed for agents. A secret is never returned. Use inject, or a reveal link for a human."""
    _need()
    return JSONResponse({"status": "closed", "reason": "use no longer returns a secret. Call inject, or open a reveal link."}, status_code=410)


@router.post("/api/v7/vault/reveal")
async def vault_reveal(req: VaultReveal, request: Request):
    """One-time link for a human: opens once, shows the value about 10 s, then wipes it. Default 5 min, max 60 min."""
    _need()
    uid = _uid(request)
    try:
        r = vault.create_reveal(uid, req.name, req.ttl_s, req.require_login, _ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not r:
        raise HTTPException(404, "No such secret")
    return r


@router.delete("/api/v7/vault/{name}")
async def vault_delete(name: str, request: Request):
    _need()
    uid = _uid(request)
    try:
        ok = vault.delete(uid, name, _ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not ok:
        raise HTTPException(404, "No such secret")
    return {"status": "deleted", "name": name}


@router.get("/api/v7/vault/log")
async def vault_log(request: Request, limit: int = 50):
    _need()
    return {"log": vault.history(_uid(request), max(1, min(limit, 500)))}


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>SKV one-time secret</title>
<style>body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;max-width:560px;margin:40px auto;padding:0 16px}
.box{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px}button{background:#238636;color:#fff;border:0;border-radius:6px;padding:10px 16px;font-size:16px}
input{width:100%;box-sizing:border-box;margin:6px 0;padding:8px;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px}
code{display:block;word-break:break-all;background:#0d1117;padding:12px;border-radius:6px;font-size:16px;margin:12px 0}.muted{color:#8b949e;font-size:14px}</style></head>
<body><div class="box"><h2>SKV one-time secret</h2>__BODY__</div></body></html>"""

_GONE = "<p>This link was already opened, has expired, or does not exist.</p><p class='muted'>Ask the owner for a new link.</p>"


@router.get("/s/{token}", include_in_schema=False)
async def reveal_page(token: str):
    st = vault.reveal_state(token)
    if not st:
        body = _GONE
    else:
        login = ("<p class='muted'>The owner asked for a login check.</p><input id='em' type='email' placeholder='email' autocomplete='username'>"
                 "<input id='pw' type='password' placeholder='password' autocomplete='current-password'>") if st["require_login"] else ""
        body = (f"<p>Secret: <b>{html.escape(st['name'])}</b></p><p class='muted'>It opens once. After you press the button it is shown for about 10 seconds and then wiped. "
                "Make sure nobody is looking at your screen.</p>" + login +
                "<button id='go'>Reveal</button><div id='out'></div>"
                "<script>const go=document.getElementById('go'),out=document.getElementById('out');"
                "go.onclick=async()=>{go.disabled=true;const em=document.getElementById('em'),pw=document.getElementById('pw');"
                "const r=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:em?em.value:'',password:pw?pw.value:''})});"
                "const d=await r.json().catch(()=>({status:'gone'}));"
                "if(d.status==='login'){out.innerHTML='<p>Wrong login. Try again.</p>';go.disabled=false;return}"
                "if(d.status!=='ok'){document.querySelector('.box').innerHTML=\"<h2>SKV one-time secret</h2>" + _GONE.replace('"', '\\"') + "\";return}"
                "go.remove();if(em){em.remove();pw.remove()}const c=document.createElement('code');c.textContent=d.value;d.value='';"
                "const b=document.createElement('button');b.textContent='Copy';b.onclick=()=>navigator.clipboard.writeText(c.textContent);"
                "const t=document.createElement('p');t.className='muted';out.append(c,b,t);let n=10;"
                "const tick=()=>{t.textContent='Wiped in '+n+' s';if(n--<=0){c.textContent='';out.innerHTML='<p>Wiped. This link is used up.</p>';return}setTimeout(tick,1000)};tick();"
                "document.addEventListener('visibilitychange',()=>{if(document.hidden&&c.textContent){n=0}});};</script>")
    return HTMLResponse(_PAGE.replace("__BODY__", body), headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"})


class RevealOpen(BaseModel):
    email: str = ""
    password: str = ""


@router.post("/s/{token}", include_in_schema=False)
async def reveal_open(token: str, req: RevealOpen, request: Request):
    if not vault.available():
        return JSONResponse({"status": "gone"}, headers={"Cache-Control": "no-store"})
    st, val = vault.open_reveal(token, req.email, req.password, _ip(request))
    body = {"status": st}
    if st == "ok":
        body["value"] = val
    return JSONResponse(body, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
