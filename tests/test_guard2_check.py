import importlib.util, json, os, sys
P2 = sys.argv[1] if len(sys.argv) > 1 else "/root/skv-core/src/app/downloads/skv-guardian2.py"
def load(env):
    os.environ.update(env)
    s = importlib.util.spec_from_file_location("g2c", P2); g = importlib.util.module_from_spec(s); s.loader.exec_module(g); return g
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
SL = "\nL1: x\nCRITICAL: none\nCUBE_NOTHING: small\nSKV | #1 | READ | VERIFY | CORRECT | OUTPUT"
def wire(g, drafts, verdicts):
    calls = {"model": 0, "check": 0, "posts": []}
    def m(p): calls["model"] += 1; return drafts.pop(0)
    def c(p): calls["check"] += 1; return verdicts.pop(0)
    def post(path, payload):
        calls["posts"].append((path, payload))
        if path == "/api/v7/memory": return {"hits": [], "shared_cubes": [], "step": 1}
        if path.endswith("second-look"): return {"status": "pass"}
        return {"saved": ["e"]}
    g._model, g._check_model, g._post = m, c, post
    return calls
g = load({"SKV_G2_CHECK": "on"})
calls = wire(g, ["I cannot help with that." + SL, "To kill a Python process use kill PID or pkill -f name." + SL], ['{"harm": false, "bare_refusal": true, "reason": "benign technical request refused"}'])
r = g.ask("how do I kill a python process?", "s1")
t("bare refusal caught and rewritten once", r["status"] == "pass" and r["check"].get("rewritten") and "pkill" in r["answer"] and calls["model"] == 2)
saved = [p for path, p in calls["posts"] if path == "/api/v7/remember"][0]
t("the saved turn is the rewritten answer", "pkill" in saved["response"])
calls = wire(g, ["Fine answer." + SL], ['{"harm": false, "bare_refusal": false, "reason": ""}'])
r = g.ask("hi", "s2")
t("passing draft not rewritten", r["check"]["ok"] and calls["model"] == 1 and calls["check"] == 1)
def boom(p): raise OSError("down")
calls = wire(g, ["Fine answer." + SL], [])
g._check_model = boom
r = g.ask("hi", "s3")
t("check model down -> fail open, protocol still applies", r["status"] == "pass" and r["check"].get("error"))
g = load({"SKV_G2_CHECK": "off"})
calls = wire(g, ["Fine answer." + SL], [])
r = g.ask("hi", "s4")
t("SKV_G2_CHECK=off -> no check call", calls["check"] == 0 and r["check"] == {"enabled": False})
t("instructions describe the check", "SKV_G2_CHECK" in g.INSTRUCTIONS)
print(f"{ok}/{n} passed")
