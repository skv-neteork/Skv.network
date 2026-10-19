import os, sys, importlib.util
sys.path.insert(0, "/app")
os.environ.pop("SKV_API_KEYS", None)
spec = importlib.util.spec_from_file_location("v7", os.environ.get("MOD", "/app/app/routers/v7_router.py")); v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
from fastapi import HTTPException
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
def code(h):
    try: v.verify_seal_level(h); return 200
    except HTTPException as e: return e.status_code
t("no dev mode: any 20+ char Bearer is refused", code("Bearer " + "x" * 40) == 403)
t("missing header refused", code(None) == 401)
src = open(os.environ.get("MOD", "/app/app/routers/v7_router.py")).read()
t("no 'allow any' branch left", "allow any (dev mode)" not in src)
print(f"{ok}/{n} passed")
