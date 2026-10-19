import sys, os, shutil, sqlite3, tempfile, asyncio, importlib.util
sys.path.insert(0, "/app")
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
tmp = tempfile.mktemp(suffix=".db"); shutil.copy("/data/skv/metadata_store/shared_master.db", tmp)
from app import cubes_v2 as cv
c = sqlite3.connect(tmp); cv.ensure(c)
def add(cid, topic, ess, rules, created="2026-01-01 00:00:0%d"):
    c.execute("INSERT INTO cubes_new (cube_id, evidence, essence, subject_action_object, rules_markdown, status, rating, created_by, created_at, kind, trust, shown) VALUES (?,'test',?,?,?,'community',0,'author@x.io',?,'moment','new',0)", (cid, ess, topic, rules, created))
add("tq_bash1", "zzq_bashfiles", "Bash: find the largest files with du and sort", "du -ah dir | sort -rh | head -5 lists largest files", "2026-01-01 00:00:01")
add("tq_phys", "zzq_bashfiles", "Particle physics: quark confinement explained", "Gluon field energy grows with distance", "2026-01-01 00:00:00")
add("tq_bash2", "zzq_bashfiles", "Bash: human readable sizes for largest files", "Use sort -h with du -h for largest files", "2026-01-01 00:00:02")
add("tq_shell", "zzq_shelltips", "Largest files: find with -size and sort", "find dir -type f -printf '%s %p' | sort -n | tail -5 largest files", "2026-01-01 00:00:03")
add("tq_phys2", "zzq_physics", "Quarks and gluons", "Strong force", "2026-01-01 00:00:04")
c.commit()
Q = "bash one-liner to list the 5 largest files under a directory"
ids = [r[0] for r in cv.new_candidates(c, "zzq_bashfiles", "viewer@x.io", query=Q)]
t("off-topic physics never offered", "tq_phys" not in ids and "tq_phys2" not in ids)
t("relevant same-topic cubes offered, fair FIFO order", ids[:2] == ["tq_bash1", "tq_bash2"])
t("neighbour topic not used while same topic has relevant", "tq_shell" not in ids)
c.execute("UPDATE cubes_new SET shown=1 WHERE cube_id='tq_bash1'"); c.commit()
ids = [r[0] for r in cv.new_candidates(c, "zzq_bashfiles", "viewer@x.io", query=Q)]
t("fairness: least shown first among relevant", ids[0] == "tq_bash2")
ids = [r[0] for r in cv.new_candidates(c, "zzq_physics", "viewer@x.io", query=Q)]
t("fallback to neighbouring relevant topics when none in topic", "tq_shell" in ids and "tq_phys2" not in ids)
ids = [r[0] for r in cv.new_candidates(c, "zzq_physics", "viewer@x.io", query="", vec_scores={"tq_bash1": 0.72})]
t("vector similarity above threshold counts", "tq_bash1" in ids)
ids = [r[0] for r in cv.new_candidates(c, "zzq_physics", "viewer@x.io", query="", vec_scores={"tq_bash1": 0.3})]
t("vector below threshold ignored", "tq_bash1" not in ids)
pack = cv.select_pack(c, "zzq_bashfiles", "viewer@x.io", 1, record=False, query=Q)
t("pack rate slots are relevant", all(o["cube_id"] != "tq_phys" for o in pack if o["note"].startswith("new")))
c.close()
# disputed instead of deprecated
spec = importlib.util.spec_from_file_location("v7", os.environ.get("MOD", "/app/app/routers/v7_router.py")); v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
v.SHARED_DB = tmp
for i, u in enumerate(["u1@x.io", "u2@y.io", "u3@z.io"]):
    class R: headers = {"x-real-ip": "10.1.%d.1" % i}; client = None
    r = asyncio.run(v.vote_experience(v.VoteRequest(cube_id="tq_phys", user_id=u, vote=-1, reason="off-topic %d" % i), R()))
t("third downvote -> disputed, not deprecated", r["cube_status"] == "disputed" and r["in_court"])
c = sqlite3.connect(tmp)
t("disputed stays in the feed", c.execute("SELECT 1 FROM cubes_new WHERE cube_id='tq_phys' AND " + cv.HIDDEN_SQL).fetchone() is not None)
pack = cv.select_pack(c, "zzq_bashfiles", "viewer2@x.io", 1, record=False, query="")
t("pack marks disputed cubes", any("disputed: in court" in o["note"] for o in pack if o["cube_id"] == "tq_phys") or "tq_phys" not in [o["cube_id"] for o in pack])
class R: headers = {"x-real-ip": "10.9.9.9"}; client = None
r = asyncio.run(v.vote_experience(v.VoteRequest(cube_id="tq_phys", user_id="u4@w.io", vote=1), R()))
t("a later +1 does not lift the dispute before the court", r["cube_status"] == "disputed")
c.close(); os.remove(tmp)
print(f"{ok}/{n} passed")
