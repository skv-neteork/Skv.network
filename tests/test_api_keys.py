"""Hashed API key checks (server, localhost). Prints no keys."""
import json, sqlite3, subprocess, sys, urllib.request, urllib.error
K = open("/root/skv_new_owner_key.txt").read().strip()
res = []
def code(tok, path="/api/v7/memory", body={"query_text": "skv", "probe": True}, method="POST"):
    r = urllib.request.Request("http://127.0.0.1:8000" + path, data=None if body is None else json.dumps(body).encode(), method=method,
                               headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
    try:
        return urllib.request.urlopen(r, timeout=60).status
    except urllib.error.HTTPError as e:
        return e.code
def check(n, ok):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n)
def inapp(py):
    return subprocess.run(["docker", "exec", "skv_api", "python3", "-c", py], capture_output=True, text=True).stdout.strip()
s = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
check("no plaintext keys stored", s.execute("select count(*) from user_api_keys where api_key not like 'h1$%'").fetchone()[0] == 0)
check("new key file value not in DB", s.execute("select count(*) from user_api_keys where api_key=?", (K,)).fetchone()[0] == 0)
check("current owner key works", code(K) == 200)
check("old owner key stays revoked", s.execute("select is_active from user_api_keys where key_prefix='sk_718c'").fetchone()[0] == 0)
tok = inapp("from app import api_keys as A; print(A.internal_token('denizchavdarov@gmail.com'))")
check("internal token works on /memory", code(tok) == 200)
check("internal token refused on /vault", code(tok, "/api/v7/vault", None, "GET") == 401)
check("internal token refused on /profile", code(tok, "/api/v7/profile", None, "GET") == 401)
check("tampered internal token refused", code(tok[:-2] + ("00" if not tok.endswith("00") else "11")) == 401)
old = inapp("from app import api_keys as A; print(A.internal_token('denizchavdarov@gmail.com', ttl_s=-5))")
check("expired internal token refused", code(old) == 401)
tmp = inapp("from app import api_keys as A; print(A.issue('keytest@local', 'test'))")
check("issued key works and is stored hashed", code(tmp, "/api/v7/vault", None, "GET") in (200,) and s.execute("select count(*) from user_api_keys where user_id='keytest@local' and api_key like 'h1$%'").fetchone()[0] == 1)
s.execute("delete from user_api_keys where user_id='keytest@local'"); s.commit()
check("deleted test key -> 401", code(tmp) == 401)
print(json.dumps({"passed": sum(res), "total": len(res)}))
sys.exit(0 if all(res) else 1)
