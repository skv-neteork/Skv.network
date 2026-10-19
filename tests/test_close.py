import os,sys,types,json,sqlite3,importlib.util
R="/root/skv-core/src/app/"
ok=0;n=0
def t(name,c):
    global ok,n;n+=1;ok+=bool(c);print(("PASS " if c else "FAIL ")+name)
v=open(R+"routers/v7_router.py").read()
seg=v[v.index("async def agent_run"):v.index("class SecondLookRequest")]
t("agent_run uses /memory recall first", seg.index("guardian_l1_memory")<seg.index("word ="))
sys.modules.setdefault("fastapi",types.SimpleNamespace(APIRouter=lambda **k:types.SimpleNamespace(get=lambda *a,**kw:(lambda f:f))))
sp=importlib.util.spec_from_file_location("gm",R+"routers/guardian_middleware.py");gm=importlib.util.module_from_spec(sp);sp.loader.exec_module(gm)
tr=[x for x in vars(gm).values() if isinstance(x,type) and hasattr(x,"mark_memory_saved")][0]()
fn=[getattr(tr,m) for m in dir(tr) if not m.startswith("_") and m not in("mark_memory_saved",) and callable(getattr(tr,m))]
outs=[]
for i in range(16):
    for f in fn:
        try: r=f("s1")
        except TypeError: continue
        if isinstance(r,dict) and "session_step" in r: outs.append(r)
t("meta no save/vote duplicate", outs and all(o["reminder_prompt"] is None for o in outs) and outs[-1]["reminders_source"]=="/api/v7/memory")
t("dead middleware removed", not os.path.exists(R+"middleware_guardian.py"))
c=sqlite3.connect("/data/skv/metadata_store/shared_master.db")
t("CUBE 05 v9 describes Guard 2", "GUARD 2 (v3)" in c.execute("select rules_markdown from cubes_new where cube_id='cube_const_05_v9'").fetchone()[0])
t("schema points to Guard 2 v3", "Guard 2 v3" in open(R+"routers/openapi_schema.json").read())
print(f"{ok}/{n} passed")
