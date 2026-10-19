import sys, os, json, types
sys.path.insert(0, "/app")
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
from app import memory_v2 as mv, memory_v2_windows as mw
view = {"shared_cubes": [{"cube_id": "c%d" % i, "note": ("new, rate this" if i >= 4 else "strong"), "rules": "x" * 300} for i in range(6)],
        "hits": [{"text": "y" * 400} for _ in range(5)], "lens": {"clusters": []}}
mv._fit_followup(view, 50)
ids = [c["cube_id"] for c in view["shared_cubes"]]
t("budget trim keeps 'new, rate this' cubes", "c4" in ids and "c5" in ids)
mw.BASE_DIR if hasattr(mw, "BASE_DIR") else None
p = mw.first_pack("skvtest_nobody_%d@test.skv.invalid" % os.getpid(), {"map": 100, "raw": 100, "l1": 100, "l2": 100, "critical": 100})
t("first_pack for a brand-new account does not crash", p["windows"]["raw"] == [])
for f in __import__("glob").glob("/data/skv/metadata_store/skvtest_nobody_*"): os.remove(f)
g = open("/app/app/downloads/skv-guardian2.py").read()
t("guard2 asks for the concrete seal step", 'SKV | #%s |' in g and 'mem.get("step")' in g)
t("guard2 keeps session history", "_history" in g and "EARLIER IN THIS SESSION" in g)
t("guard2 documents sysperm", "/api/v7/sysperm/check" in g)
print(f"{ok}/{n} passed")
