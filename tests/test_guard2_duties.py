"""Guard 2's five duties: save turns, periodic stage L1 + rare L2, critical, rate used cubes, real DRAFT/SECOND LOOK."""
import importlib.util, os, sys
P2 = sys.argv[1] if len(sys.argv) > 1 else "/root/skv-core/src/app/downloads/skv-guardian2.py"
os.environ.update({"SKV_G2_PROTOCOL": "full", "SKV_G2_L1_EVERY": "3", "SKV_G2_L2_EVERY": "2", "SKV_G2_REFS": "off"})
s = importlib.util.spec_from_file_location("g2d", P2); g = importlib.util.module_from_spec(s); s.loader.exec_module(g); g.START_PACK = False
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
def full(final, extra=""):
    return ("DRAFT:\nAnswer alpha.\nSECOND LOOK:\nMy draft \"Answer alpha\" gives no option; the answer alpha needs the safe option added.\nFINAL:\n"
            + final + "\n" + extra + "CRITICAL: none\nCUBE_NOTHING: small\nSKV | #1 | READ | VERIFY | CORRECT | OUTPUT")
cubes = [{"cube_id": "cube_abc12345", "note": "trusted"}]
def wire(outs):
    c = {"posts": [], "prompts": []}
    def m(p): c["prompts"].append(p); return outs.pop(0) if len(outs) > 1 else outs[0]
    def post(path, payload):
        c["posts"].append((path, payload))
        if path == "/api/v7/memory": return {"hits": [], "shared_cubes": cubes, "step": 1}
        if path.endswith("second-look"): return {"status": "pass"}
        return {"saved": ["e"]}
    g._model, g._post = m, post
    return c
rem = lambda c: [p for path, p in c["posts"] if path == "/api/v7/remember"]
long = "word " * 200
c = wire([full("A, with option B. " + long)]); r = g.ask("q1 " + long, "d")
t("1 save memory: every turn goes to /remember", len(rem(c)) == 1 and rem(c)[0]["response"])
t("2 L1 not demanded on ordinary turns", "STAGE summary" not in c["prompts"][0] and rem(c)[0]["l1_summary"] is None)
c = wire([full("B, safe option C. " + long)]); g.ask("q2 " + long, "d")
c = wire([full("C, safe option D. " + long), full("C, safe option D. " + long, "L1: stage 1: did q1-q3 setup, decided B, ended with D working; " + "x " * 30 + "\n")])
r = g.ask("q3 " + long, "d")
t("2 stage L1 demanded at turn L1_EVERY, re-check if missing", "STAGE summary" in c["prompts"][0] and len(c["prompts"]) == 2 and "stage 1" in (rem(c)[0]["l1_summary"] or ""))
for q in ("q4", "q5"):
    c = wire([full("E, safe. " + long)]); g.ask(q + " " + long, "d")
c = wire([full("F, safe. " + long, "L1: stage 2: did q4-q6, decided F, ended done; " + "y " * 30 + "\nL2: setup then F done\n")])
r = g.ask("q6 " + long, "d")
t("2 rare L2 demanded after L2_EVERY stage L1s and saved as l2_map", "L2: <headlines" in c["prompts"][0] and rem(c)[0].get("l2_map") == "setup then F done")
c = wire([full("G, safe. " + long, "")]); r = g.ask("q7 " + long, "d")
t("3 critical line is demanded", "CRITICAL" in c["prompts"][0])
c = wire([full("G2 safe. " + long).replace("CRITICAL: none\n", "")] * 3); r = g.ask("q8 " + long, "d")
t("3 missing CRITICAL -> re-check", len(c["prompts"]) == 3 and "CRITICAL" in c["prompts"][1] and r["answer"].strip())
c = wire([full("Per cube_abc12345, use H safely. " + long), full("Per cube_abc12345, use H safely. " + long, "RATE: cube_abc12345 +1 it helped\n")])
r = g.ask("q9 " + long, "e")
votes = [p for path, p in c["posts"] if path == "/api/v7/experience/vote"]
t("4 a used cube must be rated: re-check asks for RATE, vote is sent", "RATE: cube_abc12345" in c["prompts"][1] and votes and votes[0]["cube_id"] == "cube_abc12345")
c = wire(["no sections at all\nCRITICAL: none\nCUBE_NOTHING: x\nSKV | #1 | READ | VERIFY | CORRECT | OUTPUT"] * 3); r = g.ask("q10", "f")
t("5 missing DRAFT/SECOND LOOK -> re-checks, answer still given with note", "DRAFT:" in c["prompts"][1] and r["uncertain"] and r["answer"].strip())
t("not a harm judge: no second model call besides the agent", all("Answer only yes or no" not in p for p in c["prompts"]))
print(f"{ok}/{n} passed")
