"""Guard 1 / Guard 2 / evolver checks (2026-10-19). Host: python3 tests/test_guards.py (needs the container for the router part)."""
import importlib.util, subprocess, sys, types, os
res = []
def check(n, ok): res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n, flush=True)
def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
g = load("g2", "/root/skv-core/src/app/downloads/skv-guardian2.py")
d = """Ответ про кубы, см. event x::remember_1.
L1: decided cubes v2
CRITICAL: none
CUBE: warning | skv.deploy | Restart only via safe_restart | docker restart kills imports; use ops/safe_restart.sh
RATE: cube_a +1 worked
RATE: cube_b -1 outdated flag
TASK_DONE
SKV | #3 | READ | VERIFY | CORRECT | OUTPUT"""
info, miss = g.parse(d, ["cube_a", "cube_b"])
check("guard2 parses service lines", not miss and info["cube"]["kind"] == "warning" and info["rates"]["cube_b"] == (-1, "outdated flag") and info["task_done"])
check("guard2 hides service lines, keeps seal and CUBE 05 mentions", "L1:" not in g.clean(d) and "RATE" not in g.clean(d) and "TASK_DONE" not in g.clean(d) and "SKV | #3" in g.clean(d) and "CUBE 05 rule" in g.clean("CUBE 05 rule\nL1: x"))
info, miss = g.parse("text\nL1: x\nCRITICAL: none\nRATE: cube_a -1\nSKV | #1 |", ["cube_a"])
check("guard2 requires cube or reasoned nothing, and a reason for -1", any("CUBE_NOTHING" in m for m in miss) and any("cube_a" in m for m in miss))
info, miss = g.parse("t\nL1: x\nCRITICAL: none\nCUBE_NOTHING: routine\n", [])
check("guard2 requires the seal", any("seal" in m for m in miss))
src = open("/root/skv-core/src/app/downloads/skv-guardian2.py").read()
check("guard2 saves before Second Look and never auto-writes cubes", src.index('_post("/api/v7/remember"') < src.index('second-look') and "Auto-detected" not in src)
sys.modules.setdefault("fastapi", types.SimpleNamespace(APIRouter=lambda **k: types.SimpleNamespace(get=lambda *a, **kw: (lambda f: f))))
gm = load("gm", "/root/skv-core/src/app/routers/guardian_middleware.py")
t = gm.SessionTracker(); t.MAX_SESSIONS = 50
for i in range(500):
    t.process_api_call("s%d" % i)
check("guard1 meta endpoint memory is bounded", len(t.sessions) <= 51)
check("guard1 meta reminders point to v7", "v4/memory/feedback" not in open("/root/skv-core/src/app/routers/guardian_middleware.py").read())
ev = load("ev", "/root/skv-core/ops/evolver.py")
called = []
ev.ask = lambda *a, **k: called.append(1)
ev.watch = lambda: None; ev.new_users = lambda: None; ev.send_digest = lambda: None
check("evolver judge prompt wraps cube as DATA", "<<CUBE_DATA>>" in open("/root/skv-core/ops/evolver.py").read())
es = open("/root/skv-core/ops/evolver.py").read()
main = es[es.index('if __name__ == "__main__":'):]
check("evolver --watch exits before court/age-out (no LLM cost hourly)", main.index("--watch") < main.index("SystemExit") < main.index("age_out()"))
r = subprocess.run("docker exec -i -w /app -e MOD=" + os.environ.get("MOD", "/app/app/routers/v7_router.py") + " skv_api python -", shell=True, input='''
import asyncio,sys;sys.path.insert(0,"/app")
import importlib.util as u
sp=u.spec_from_file_location("v",__import__("os").environ.get("MOD","/app/app/routers/v7_router.py"));v=u.module_from_spec(sp);sp.loader.exec_module(v)
r=asyncio.run(v.second_look(v.SecondLookRequest(user_id="nobody@example.invalid",draft="general answer",event_id="",span=0)))
h=[c for c in r["checks"] if c["name"]=="hallucination"][0]
r2=asyncio.run(v.second_look(v.SecondLookRequest(user_id="nobody@example.invalid",draft="no cite",event_id="u::remember_1",span=1)))
h2=[c for c in r2["checks"] if c["name"]=="hallucination"][0]
print("SL", h["ok"], h2["ok"])
''', capture_output=True, text=True, timeout=120, env={**os.environ})
check("second look: nothing opened -> no citation needed; opened turn must be cited", "SL True False" in r.stdout)
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
