# Checks the v7 endpoints the Guard 2 extension relies on (run inside skv_api). Prints no keys.
import json, httpx
K = json.load(open("/data/skv/.jp_test_keys.json"))
def find_main(d):
    for acc, v in (d.items() if isinstance(d, dict) else []):
        if isinstance(v, dict) and isinstance(v.get("main"), str): return v["main"]
    raise SystemExit("no main key: structure " + str({k: (list(v) if isinstance(v, dict) else type(v).__name__) for k, v in d.items()}))
key = find_main(K)
B = "http://127.0.0.1:8000/api/v7"; H = {"Authorization": "Bearer " + key}
ok = 0; n = 0
def chk(name, cond, info=""):
    global ok, n; n += 1; ok += bool(cond); print(("PASS " if cond else "FAIL ") + name, "" if cond else str(info)[:300])
c = httpx.Client(timeout=90)
r = c.post(B + "/session/step_zero", json={}, headers=H); d = r.json()
chk("step_zero call 1 (bootstrap)", r.status_code == 200 and (d.get("step_zero") or {}).get("call") == 1, {k: d.get(k) for k in list(d)[:6]})
nxt = (d.get("step_zero") or {}).get("next_call"); print("  next_call:", str(nxt)[:160])
r = c.post(B + "/session/bootstrap", json={"part": "board"}, headers=H); d2 = r.json()
chk("call 2: /session/bootstrap part=board", r.status_code == 200 and "error" not in d2, list(d2)[:8])
body = {"user_message": "ext 0.1.6 check: what is my test note? password=[SECRET]", "draft": "Checked the Guard 2 path at the API level.", "source": "guard2_ext:chatgpt"}
r = c.post(B + "/agent/turn", json=body, headers=H); t = r.json()
chk("turn: 200 and verdict", r.status_code == 200 and t.get("verdict"), {k: t.get(k) for k in ("error", "verdict", "saved", "next_action")})
chk("turn: saved + seal (fields the badge uses)", t.get("saved") and t.get("seal"), {k: t.get(k) for k in ("saved", "seal", "error")})
r = c.post(B + "/agent/turn", json={"user_message": "test note", "query": "test note"}, headers=H); t2 = r.json()
chk("context (Insert memory): facts list shape", r.status_code == 200 and isinstance(t2.get("facts", []), list), list(t2)[:10])
r = c.post(B + "/agent/turn", json=body, headers={"Authorization": "Bearer sk_invalid_000000000000"})
chk("bad key -> 401 (badge shows 'not saved')", r.status_code == 401, r.status_code)
r = c.post(B + "/constitution/install", json={"user_confirmed": False}, headers=H)
chk("constitution/install route exists", r.status_code != 404, r.status_code)
print("EXT API RESULT %d/%d" % (ok, n))
