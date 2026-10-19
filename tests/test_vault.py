"""Vault self-test (runs on the server against localhost). Prints no secret values."""
import json, os, re, secrets, sqlite3, sys, urllib.request, urllib.error
BASE = os.environ.get("SKV_BASE", "http://127.0.0.1:8000")
K = os.environ.get("SKV_KEY") or open("/root/skv_new_owner_key.txt").read().strip()
res = []
def call(m, p, b=None, key=True, raw=False):
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = "Bearer " + K
    r = urllib.request.Request(BASE + p, data=None if b is None else json.dumps(b).encode(), headers=h, method=m)
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            body = x.read().decode(); hd = dict(x.headers); code = x.status
    except urllib.error.HTTPError as e:
        body = e.read().decode(); hd = dict(e.headers); code = e.code
    if raw:
        return code, body, hd
    try:
        return code, json.loads(body)
    except Exception:
        return code, body
def check(name, ok):
    res.append(ok); print(("PASS " if ok else "FAIL ") + name)
val = "selftest_" + secrets.token_hex(12)
c, _ = call("GET", "/api/v7/vault", key=False); check("no key -> 401", c == 401)
c, r = call("POST", "/api/v7/vault", {"name": "vault_selftest", "value": val, "note": "self-test"}); check("put", c == 200 and r.get("ref") == "[vault:vault_selftest]")
c, r = call("GET", "/api/v7/vault"); check("list has name, no value", c == 200 and any(s["name"] == "vault_selftest" for s in r["secrets"]) and val not in json.dumps(r))
c, r = call("POST", "/api/v7/vault/use", {"name": "vault_selftest", "purpose": "self-test"}); check("use returns value", c == 200 and r.get("value") == val)
s = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
check("db has ciphertext only", s.execute("select count(*) from vault_secrets where cast(ct as text) like ? or note like ?", ("%" + val + "%", "%" + val + "%")).fetchone()[0] == 0)
c, r = call("POST", "/api/v7/vault/reveal", {"name": "vault_selftest", "ttl_s": 120}); check("reveal link", c == 200 and r["url"].startswith("https://skv.network/s/") and r["single_open"])
tok = r["url"].rsplit("/", 1)[1]
check("token not stored in plaintext", s.execute("select count(*) from vault_reveals where token_hash=?", (tok,)).fetchone()[0] == 0)
c, b, hd = call("GET", "/s/" + tok, key=False, raw=True); check("page GET 200, not consumed", c == 200 and "Reveal" in b and val not in b)
check("page headers no-store/no-referrer", {k.lower(): v for k, v in hd.items()}.get("cache-control") == "no-store" and {k.lower(): v for k, v in hd.items()}.get("referrer-policy") == "no-referrer") == "no-store" and hd.get("Referrer-Policy") == "no-referrer")
c, b, hd = call("GET", "/s/" + tok, key=False, raw=True); check("second GET still available (link previews do not burn it)", "Reveal" in b)
c, r = call("POST", "/s/" + tok, {}, key=False); check("open -> value", c == 200 and r.get("status") == "ok" and r.get("value") == val)
c, r = call("POST", "/s/" + tok, {}, key=False); check("second open -> gone", r.get("status") == "gone" and "value" not in r)
c, b, hd = call("GET", "/s/" + tok, key=False, raw=True); check("page after open -> gone", "already opened" in b)
c, r = call("POST", "/api/v7/vault/reveal", {"name": "vault_selftest", "ttl_s": 120, "require_login": True}); tok2 = r["url"].rsplit("/", 1)[1]
c, r = call("POST", "/s/" + tok2, {"email": "x@y.z", "password": "wrong"}, key=False); check("login link: wrong login refused", r.get("status") == "login" and "value" not in r)
c, r = call("POST", "/api/v7/vault/reveal", {"name": "vault_selftest", "ttl_s": 99999}); check("ttl capped at 3600", r.get("ttl_s") == 3600)
c, r = call("POST", "/api/v7/vault/reveal", {"name": "vault_selftest", "ttl_s": 30}); tok3 = r["url"].rsplit("/", 1)[1]
s.execute("update vault_reveals set expires_at=datetime('now','-1 second') where token_hash=?", (__import__("hashlib").sha256(tok3.encode()).hexdigest(),)); s.commit()
c, r = call("POST", "/s/" + tok3, {}, key=False); check("expired link -> gone", r.get("status") == "gone")
# auto-move from remember
fake = "Zq" + secrets.token_hex(8)
c, r = call("POST", "/api/v7/remember", {"topic": "skv_eval_vault", "query": "EVAL_ONLY vault test", "response": f"EVAL_ONLY server password={fake} keep it"})
names = r.get("vaulted") or []
check("remember moves secret to vault", c == 200 and len(names) == 1 and names[0].startswith("auto_password_"))
eid = next(i for i in r["saved"] if "::" in i)
d = sqlite3.connect("/data/skv/metadata_store/denizchavdarovgmailcom.db")
raw = d.execute("select raw_dialogue from event_metadata where event_id=?", (eid,)).fetchone()[0]
check("memory keeps reference, not value", fake not in raw and f"[vault:{names[0]}]" in raw)
check("fts has no value", d.execute("select count(*) from events_fts where raw_dialogue like ?", ("%" + fake + "%",)).fetchone()[0] == 0)
c, r = call("POST", "/api/v7/vault/use", {"name": names[0], "purpose": "self-test"}); check("auto secret usable", r.get("value") == fake)
c, r = call("GET", "/api/v7/vault/log?limit=30"); check("log has use/reveal_open, no values", c == 200 and {"use", "reveal_open", "create"} <= {x["action"] for x in r["log"]} and val not in json.dumps(r) and fake not in json.dumps(r))

# transient reveal: not stored in vault_secrets; wiped after open
tv = "transient_" + secrets.token_hex(8)
c, r = call("POST", "/api/v7/vault/reveal/transient", {"label": "vault_selftest_transient", "value": tv, "ttl_s": 120})
check("transient link", c == 200 and r.get("transient") and r["url"].startswith("https://skv.network/s/"))
check("transient not in vault_secrets", s.execute("select count(*) from vault_secrets where name=?", ("vault_selftest_transient",)).fetchone()[0] == 0)
ttok = r["url"].rsplit("/", 1)[1]
c, r = call("POST", "/s/" + ttok, {}, key=False); check("transient open", c == 200 and r.get("value") == tv)
c, r = call("POST", "/s/" + ttok, {}, key=False); check("transient second open gone", r.get("status") == "gone")
check("transient payload wiped", s.execute("select payload_ct from vault_reveals where token_hash=?", (__import__("hashlib").sha256(ttok.encode()).hexdigest(),)).fetchone()[0] is None)

# cleanup: test event via forget flow, test secrets via delete
c, p = call("POST", "/api/v7/memory/forget/preview", {"mode": "event", "event_ids": [eid]})
c, f = call("POST", "/api/v7/memory/forget/confirm", {"token": p["confirm"]["token"], "user_confirmed": True}); check("cleanup forget", f.get("count") == 1)
for n in ("vault_selftest", names[0]):
    c, r = call("DELETE", "/api/v7/vault/" + n); check("delete " + n, c == 200)
c, r = call("POST", "/api/v7/vault/use", {"name": "vault_selftest"}); check("deleted -> 404", c == 404)
print(json.dumps({"passed": sum(res), "total": len(res)}))
sys.exit(0 if all(res) else 1)
