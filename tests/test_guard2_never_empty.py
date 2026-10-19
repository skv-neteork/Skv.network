"""Guard 2 never returns an empty or withheld answer: re-checks with reasons (N=2), then best safe final + short note."""
import importlib.util, os, sys
P2 = sys.argv[1] if len(sys.argv) > 1 else "/root/skv-core/src/app/downloads/skv-guardian2.py"
def load(env):
    os.environ.update(env)
    s = importlib.util.spec_from_file_location("g2n", P2); g = importlib.util.module_from_spec(s); s.loader.exec_module(g); g.START_PACK = False; return g
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
SL = "\nL1: x\nCRITICAL: none\nCUBE_NOTHING: small\nSKV | #1 | READ | VERIFY | CORRECT | OUTPUT"
def full(draft, final, claims=None, safety=""):
    claims = claims or ("Rereading my draft: \"" + draft + "\" is too thin and unchecked; I add the missing detail and mark what is general.")
    return "DRAFT:\n" + draft + "\nSECOND LOOK:\n" + claims + ("\n" + safety if safety else "") + "\nFINAL:\n" + final + SL
def wire(g, outs, look=("pass",)):
    calls = {"model": 0, "posts": [], "prompts": []}
    looks = list(look)
    def m(p): calls["model"] += 1; calls["prompts"].append(p); return outs.pop(0) if outs else ""
    def post(path, payload):
        calls["posts"].append((path, payload))
        if path == "/api/v7/memory": return {"hits": [], "shared_cubes": [], "step": 1}
        if path.endswith("second-look"):
            st = looks.pop(0) if len(looks) > 1 else looks[0]
            return {"status": st, "checks": {"seal": "missing"} if st != "pass" else {}}
        return {"saved": ["e"]}
    g._model, g._post = m, post
    return calls
g = load({"SKV_G2_PROTOCOL": "full", "SKV_G2_MIN_CHANGE": "0.03", "SKV_G2_REFS": "strict", "SKV_G2_RECHECKS": "2"})
def nonempty(r): return r["status"] == "pass" and r.get("answer", "").strip() and r["status"] != "held"
t("no cheap-model harm judge", not hasattr(g, "check_pass") and not hasattr(g, "_check_model") and "gpt-4o-mini" not in open(P2).read())
c = wire(g, [full("Same.", "Same.")] * 3)
r = g.ask("q", "a1")
t("draft==final every time -> 2 re-checks, then answer with note", nonempty(r) and c["model"] == 3 and r["uncertain"] and "may not fully meet" in r["answer"] and "Same." in r["answer"])
t("re-check prompt cites the specific reason and the constitution", "real re-check" in c["prompts"][1] and "constitution" in c["prompts"][1] and "RE-CHECK 1/2" in c["prompts"][1])
rit = "DRAFT:\nA.\nSECOND LOOK:\nclaims: none\nsafety: ok\nfix: none\nСтатус: ПРОЙДЕНА\nFINAL:\nA, but better and longer now." + SL
c = wire(g, [rit, rit, rit])
r = g.ask("вопрос", "a2")
t("ritual Second Look x3 -> answer + Russian note", nonempty(r) and r["uncertain"] and "Примечание" in r["answer"] and "real SECOND LOOK" in c["prompts"][1])
c = wire(g, ["no steps, no lines", "still nothing", "nope"])
r = g.ask("q", "a3")
t("missing service lines never hold the answer", nonempty(r) and r["uncertain"] and any(p == "/api/v7/remember" for p, _ in c["posts"]))
c = wire(g, ["", "", "", "Here is a safe redirect: please contact a professional."])
r = g.ask("q", "a4")
t("empty model output -> model's own safe redirect + note", nonempty(r) and "safe redirect" in r["answer"] and r["uncertain"])
c = wire(g, ["", "", "", ""])
r = g.ask("q", "a5")
t("even if the model returns nothing at all -> a non-empty reply", nonempty(r))
c = wire(g, [full("A.", "A, with the safe option B."), full("A.", "A, with the safe option B, checked again.")], look=("fail", "pass"))
r = g.ask("q", "a6")
t("server Second Look fail -> re-check with server reason, then pass without note", nonempty(r) and c["model"] == 2 and "server Second Look" in c["prompts"][1] and not r["uncertain"])
c = wire(g, [full("A.", "A, with the safe option B.")] + [full("A.", "A, with the safe option B, again.")] * 3, look=("fail",))
r = g.ask("q", "a7")
t("server Second Look keeps failing -> answer still shown with note", nonempty(r) and r["uncertain"] and "safe option B" in r["answer"])
c = wire(g, [full("Same.", "Same."), full("A.", "A, with the safe option B.")])
r = g.ask("q", "a8")
t("fixed on re-check -> clean pass, no note", nonempty(r) and not r["uncertain"] and "Note:" not in r["answer"] and r["protocol"]["rechecks"] == 1)
c = wire(g, [full("Same.", "Same."), "garbage", "garbage"])
r = g.ask("q", "a9")
t("best attempt is kept (fewest issues), not the last", nonempty(r) and "Same." in r["answer"])
g1 = load({"SKV_G2_RECHECKS": "1"})
c = wire(g1, [full("Same.", "Same.")] * 3)
r = g1.ask("q", "b1")
t("SKV_G2_RECHECKS configurable", c["model"] == 2 and nonempty(r))
src = open(P2).read()
t("no 'held' status left in code", '"held"' not in src)
print(f"{ok}/{n} passed")
# Owner rule: labels are optional; real reflection over the draft is what counts
g = load({"SKV_G2_PROTOCOL": "full", "SKV_G2_REFS": "off", "SKV_G2_RECHECKS": "2"})
q = ("DRAFT:\nUse rsync with --delete to mirror the folder.\nSECOND LOOK:\nThe draft's --delete on rsync can wipe files in the target if the source path is wrong; "
     "I should warn and suggest a dry run first.\nFINAL:\nUse rsync to mirror the folder; run it first with --dry-run, and add --delete only once the paths are right." + SL)
c = wire(g, [q]); r = g.ask("mirror a folder", "o1")
t("no safety:/claims: lines but genuine reasoning over the draft -> pass, no re-check", c["model"] == 1 and not r["uncertain"])
q2 = ("DRAFT:\nUse rsync with --delete to mirror the folder.\nSECOND LOOK:\nEverything was checked carefully and is fine, status PASSED, all good.\nFINAL:\nUse rsync with delete to mirror, it's fine." + SL)
c = wire(g, [q2, q]); r = g.ask("mirror a folder", "o2")
t("generic stamp that ignores the draft -> re-check asks for real reasoning", c["model"] == 2 and "actual content" in c["prompts"][1] and not r["uncertain"])
t("missing 'safety:' line is never an issue", "'safety:' line" not in open(P2).read())
print(f"{ok}/{n} passed (incl. reflection tests)")
