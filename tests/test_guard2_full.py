import importlib.util, os, sys
P2 = sys.argv[1] if len(sys.argv) > 1 else "/root/skv-core/src/app/downloads/skv-guardian2.py"
def load(env):
    os.environ.update(env)
    s = importlib.util.spec_from_file_location("g2f", P2); g = importlib.util.module_from_spec(s); s.loader.exec_module(g); g.START_PACK = False; return g
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
SL = "\nL1: x\nCRITICAL: none\nCUBE_NOTHING: small\nSKV | #1 | READ | VERIFY | CORRECT | OUTPUT"
EID = "u@x.io::remember_1"
def full(draft, final, claims="claims: none specific [general]", safety="safety: ok, ordinary request"):
    return "DRAFT:\n" + draft + "\nSECOND LOOK:\n" + claims + "\n" + safety + "\nfix: tightened\nFINAL:\n" + final + SL
def wire(g, outs, hits=None):
    calls = {"model": 0, "posts": [], "prompts": []}
    def m(p): calls["model"] += 1; calls["prompts"].append(p); return outs.pop(0)
    def post(path, payload):
        calls["posts"].append((path, payload))
        if path == "/api/v7/memory": return {"hits": hits or [], "shared_cubes": [], "step": 1}
        if path.endswith("second-look"): return {"status": "pass"}
        return {"saved": ["e", "l1", "cube_nothing"]}
    g._model, g._post = m, post
    return calls
g = load({"SKV_G2_PROTOCOL": "full", "SKV_G2_MIN_CHANGE": "0.03", "SKV_G2_REFS": "strict"})
t("no cheap-model harm check left", not hasattr(g, "check_pass") and not hasattr(g, "_check_model"))
c = wire(g, [full("Use kill PID.", "Use `kill PID`, or `pkill -f name` to match by name; try SIGTERM before SIGKILL.")])
r = g.ask("kill a python process?", "s1")
t("full protocol passes in one go", r["status"] == "pass" and c["model"] == 1 and not r["protocol"]["redo"])
t("person sees only FINAL (no DRAFT / SECOND LOOK)", "DRAFT" not in r["answer"] and "claims:" not in r["answer"] and "pkill" in r["answer"] and "SKV | #1" in r["answer"])
t("saved turn is FINAL", "pkill" in [p for path, p in c["posts"] if path == "/api/v7/remember"][0]["response"])
c = wire(g, ["Just an answer." + SL, full("A.", "A, with the safe alternative B explained.")])
r = g.ask("q", "s2")
t("missing steps -> one redo", c["model"] == 2 and r["protocol"]["redo"] and r["status"] == "pass")
c = wire(g, [full("Same text here.", "Same text here."), full("Same text here.", "Same text here, but checked: nothing in memory supports more.")])
r = g.ask("q", "s3")
t("identical draft/final -> redo", c["model"] == 2 and "real re-check" in c["prompts"][1])
g2 = load({"SKV_G2_MIN_CHANGE": "0"})
c = wire(g2, [full("Same.", "Same.")])
r = g2.ask("q", "s3b")
t("MIN_CHANGE=0 turns the diff rule off", c["model"] == 1)
g = load({"SKV_G2_MIN_CHANGE": "0.03", "SKV_G2_REFS": "strict"})
c = wire(g, [full("You met Anna.", "You met Anna on 12.03.2025 in room 405."), full("You met Anna.", "You met Anna on 12.03.2025 (ref: %s); the room is [unverified]." % EID)], hits=[{"event_id": EID, "text": "met Anna 12.03.2025"}])
r = g.ask("when did I meet Anna?", "s4")
t("unsupported specifics -> redo; refs to memory accepted", c["model"] == 2 and "support or mark" in c["prompts"][1] and r["protocol"]["stats"]["unsupported"] == 0)
c = wire(g, [full("x", "It was on 2024-05-01 (ref: fake::id)."), full("x", "It was on 2024-05-01 (ref: fake::id), I think.")], hits=[{"event_id": EID}])
r = g.ask("when?", "s5")
t("invented ref id -> redo asked", "not memory ids" in c["prompts"][1])
c = wire(g, [full("x", "The release had 4096 slots."), full("x", "The release had 4096 slots, definitely.")])
r = g.ask("how many?", "s6")
t("still unsupported after redo -> tagged [unverified], not hidden", "[unverified]" in r["answer"] and r["status"] == "pass")
t("code numbers are not claims", g.unsupported("Run `head -5` and:\n```\nsleep 30\n```\nDone.", set())[0] == [])
g3 = load({"SKV_G2_PROTOCOL": "v3", "SKV_G2_REFS": "strict"})
c = wire(g3, ["Plain answer." + SL])
r = g3.ask("q", "s7")
t("v3 mode still works (comparison / opt-out)", r["status"] == "pass" and c["model"] == 1 and r["answer"].startswith("Plain"))
t("instructions describe the full protocol", "SECOND LOOK" in g.INSTRUCTIONS and "SKV_G2_MIN_CHANGE" in g.INSTRUCTIONS and "100%" in g.INSTRUCTIONS)
print(f"{ok}/{n} passed")
