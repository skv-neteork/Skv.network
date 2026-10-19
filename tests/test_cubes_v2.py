"""Cubes v2 self-test (2026-10-19). Runs inside skv_api against a TEMP COPY of shared_master.db; never writes the live shared db.
Usage: docker exec -i -w /app -e MOD=/app/app/routers/v7_router.py skv_api python - < tests/test_cubes_v2.py"""
import asyncio, glob, importlib, importlib.util, os, sqlite3, sys, tempfile, types
sys.path.insert(0, "/app")
LIVE = "/data/skv/metadata_store/shared_master.db"
mod_path = os.environ.get("MOD")
if mod_path:
    spec = importlib.util.spec_from_file_location("app.routers._v7_under_test", mod_path)
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
else:
    v = importlib.import_module("app.routers.v7_router")
from fastapi import HTTPException
from app import cubes_v2 as cv
tmpd = tempfile.mkdtemp(); TMP = os.path.join(tmpd, "shared_master.db")
src = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True); dst = sqlite3.connect(TMP); src.backup(dst); dst.close(); src.close()
v.SHARED_DB = TMP
OWNER = sorted(v._owner_ids())[0]
U = ["cv2_a@example.invalid", "cv2_b@example.invalid", "cv2_c@example.invalid", "cv2_d@example.invalid", "cv2_e@example.invalid"]
A, B, C, D, E = U
res = []
def check(name, ok):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name, flush=True)
def run(coro):
    try:
        return 200, asyncio.run(coro)
    except HTTPException as e:
        return e.status_code, e.detail
def db():
    c = sqlite3.connect(TMP); cv.ensure(c); return c

c = db(); cv.ensure(c); c.commit()
check("ensure idempotent + columns", {"kind", "trust", "confirms", "shown"} <= cv._cols(c, "cubes_new"))
n_before = c.execute("select count(*) from cubes_new").fetchone()[0]

# duty per task
cv.on_remember(c, A, 1, topic="backup")
check("no duty without task end", not cv.duty_errors(c, A, 5))
cv.on_remember(c, A, 2, topic="python deploy", turn=True)
check("topic change before 5 turns does not open duty", not cv._state(c, A)["pending_cube"])
for i in range(5):
    cv.on_remember(c, A, 2, topic="python deploy", turn=True)
cv.on_remember(c, A, 2, topic="python deploy v2", turn=True)
check("topic change opens duty, grace step ok", not cv.duty_errors(c, A, 3))
check("silence is an error", any("task ended" in e for e in cv.duty_errors(c, A, 4)))
notes = cv.on_remember(c, A, 4, duty="cube_nothing", duty_reason="")
check("cube_nothing without reason keeps duty", cv.duty_errors(c, A, 5) and notes)
cv.on_remember(c, A, 5, duty="cube_nothing", duty_reason="routine fix, nothing changes the answer")
check("cube_nothing with reason closes", not cv.duty_errors(c, A, 9))
cv.on_remember(c, A, 10, task_done=True)
cv.on_remember(c, A, 11, wrote_cube=True)
check("task_done then cube closes", not cv.duty_errors(c, A, 20))
c.commit()

# pack 1 cover + 3 strong + 2 new
T = "cv2 test topic zeta"
ids = []
c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind) values ('cv2_cover','Culture: zeta craft',?, 'save, change, check','t','community',?, 'culture')", (T, OWNER))
for i in range(7):
    cid = "cv2_c%d" % i; ids.append(cid)
    c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, rating, shown) values (?,?,?,?,?,?,?,?,?,?)",
              (cid, "zeta trap %d" % i, T, "obvious/miss/instead/check", "t", "community", A, "warning", float(i), 10 if i >= 4 else 0))
c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind) values ('cv2_arch','zeta archived',?, 'x','t','archived',?, 'moment')", (T, A))
pack = cv.select_pack(c, T, B, step=3)
notes_ = [p["note"] for p in pack]
check("pack: cover first", pack and pack[0]["kind"] == "culture")
check("pack: 2 new 'rate this'", sum(n.startswith("new") for n in notes_) == 2)
check("pack: 3 strong", notes_.count("good") == 3)
check("pack: archived hidden", "cv2_arch" not in [p["cube_id"] for p in pack])
check("pack: data flag", all(p.get("data") for p in pack))
newids = [p["cube_id"] for p in pack if p["note"].startswith("new")]
check("rate duty pending", cv._state(c, B)["rate_pending"] == newids and not cv.duty_errors(c, B, 5))
check("unrated new cubes error after grace", any("not rated" in e for e in cv.duty_errors(c, B, 6)))
c.commit()

# votes / trust via endpoint
code, r = run(v.vote_experience(v.VoteRequest(cube_id=newids[0], user_id=B, vote=1, topic=T)))
check("vote ok, removes from rate list", code == 200 and newids[0] not in cv._state(db(), B)["rate_pending"])
code, r = run(v.vote_experience(v.VoteRequest(cube_id=newids[0], user_id=A, vote=1, topic=T)))
check("author cannot vote own cube", code == 403)
code, r = run(v.vote_experience(v.VoteRequest(cube_id=newids[0], user_id=E, vote=1, topic=T)))
check("vote without impression does not confirm", code == 200 and r["confirms"] == 1 and r["trust"] != "trusted")
c = db()
for u in (C, D):
    cv.record_impression(c, u, newids[0], "new")
c.commit(); c.close()
run(v.vote_experience(v.VoteRequest(cube_id=newids[0], user_id=C, vote=1, topic=T)))
code, r = run(v.vote_experience(v.VoteRequest(cube_id=newids[0], user_id=D, vote=1, topic=T)))
check("3 confirmations -> trusted/verified", r.get("trust") == "trusted" and r.get("cube_status") == "verified")
check("no new golden", r.get("cube_status") != "golden")
code, r = run(v.vote_experience(v.VoteRequest(cube_id=newids[0], user_id=C, vote=-1, topic=T, reason="did not help")))
check("changed vote drops trust", r.get("trust") != "trusted")

# court: second judge required
c = db()
eff = cv.apply_verdicts(c, ids[0], [("j1", "remove", "banal")])
check("one judge remove -> fix, not archived", eff == "fix" and c.execute("select status from cubes_new where cube_id=?", (ids[0],)).fetchone()[0] != "archived")
eff = cv.apply_verdicts(c, ids[0], [("j1", "remove", "banal"), ("j2", "remove", "banal")])
row = c.execute("select status from cubes_new where cube_id=?", (ids[0],)).fetchone()
check("two judges -> archived, never hard-deleted", eff == "remove" and row and row[0] == "archived" and c.execute("select 1 from cubes_archive where cube_id=?", (ids[0],)).fetchone())
eff = cv.apply_verdicts(c, ids[1], [("j1", "remove", "x"), ("j1", "remove", "x")])
check("same judge twice is not two judges", eff == "fix")
c.commit(); c.close()
code, r = run(v.court_verdict(v.CourtVerdictRequest(user_id=B, cube_id=ids[2], verdicts=[])))
check("court endpoint owner-only", code == 403)

# links
code, r = run(v.cube_link(v.CubeLinkRequest(src=ids[3], dst=ids[4], kind="against", user_id=B)))
check("against link ok", code == 200 and r["status"] == "ok")
c = db()
check("against -> court queue", c.execute("select 1 from court_queue where cube_id=?", (ids[4],)).fetchone())
c.close()
code, r = run(v.cube_link(v.CubeLinkRequest(src=ids[3], dst=ids[5], kind="progress", user_id=B)))
check("legacy progress link still ok", code == 200)
code, r = run(v.cube_link(v.CubeLinkRequest(src=ids[3], dst=ids[5], kind="bogus", user_id=B)))
check("unknown link kind 422", code == 422)
code, r = run(v.cube_link(v.CubeLinkRequest(src=ids[3], dst=ids[5], kind="solves", user_id=B)))
check("server link kind refused for agents", code == 403)
c = db(); p2 = cv.select_pack(c, T, E, 1, record=False); c.close()
check("pack marks dispute", any(p.get("disputed_with") for p in p2))

# experience/create
code, r = run(v.create_experience_cube(v.ExperienceCreateRequest(topic="cv2 legacy topic", essence="Old clients still publish without new fields", rules_markdown="obvious: x. miss: y. instead: z. check: w.", evidence="test", user_id=B)))
check("experience/create backward compatible (shared)", code == 201 or (code == 200 and r.get("status") == "ok" and r.get("shared")))
code, r = run(v.create_experience_cube(v.ExperienceCreateRequest(topic="cv2 legacy topic", essence="kind check", rules_markdown="a b c", evidence="t", user_id=B, kind="help_request")))
check("experience/create rejects non-experience kind", code == 422)
code, r = run(v.create_experience_cube(v.ExperienceCreateRequest(topic="cv2 private", essence="Private lifehack stays private", rules_markdown="use flag -x not -y", evidence="t", user_id=B, kind="lifehack", cube_publish=False)))
c = db()
check("experience/create cube_publish=false is private", code == 200 and r.get("shared") is False and not c.execute("select 1 from cubes_new where cube_id=?", (r.get("cube_id"),)).fetchone())
c.close()

# help flow
code, r = run(v.help_create(v.HelpCreateRequest(user_id=A, topic=T, question="Deploy hangs at migration step forever", tried="restart container", accept="deploy finishes under 2 min")))
check("help create", code == 201 or (code == 200 and r.get("help_id")))
hid = r["help_id"]
code, r2 = run(v.help_create(v.HelpCreateRequest(user_id=A, topic=T, question="Пароль не подходит", tried="", accept="")))
check("help must be English (publish filter)", code == 422)
c = db(); hh = cv.help_hits(c, B, T); c.commit(); c.close()
check("help_hits reach close-experience agent", any(h["help_id"] == hid for h in hh))
code, r = run(v.help_answer(hid, v.HelpAnswerRequest(user_id=A, essence="self", rules="x y z")))
check("requester cannot answer own help", code == 409)
code, r = run(v.help_answer(hid, v.HelpAnswerRequest(user_id=B, essence="Migration lock left by crashed run", rules="Check the lock table; delete stale lock row; rerun migration; verify lock is gone.")))
sid = r.get("solution_id")
check("answer -> candidate", code in (200, 201) and r.get("state") == "candidate")
code, r = run(v.help_verify(hid, v.HelpVerifyRequest(user_id=C, solution_id=sid, worked=True)))
check("only requester verifies", code == 403)
code, r = run(v.help_verify(hid, v.HelpVerifyRequest(user_id=A, solution_id=sid, worked=True)))
c = db()
check("verify -> solves + closed", r.get("state") == "solves" and c.execute("select status from help_requests where cube_id=?", (hid,)).fetchone()[0] == "closed"
      and c.execute("select 1 from cube_links where src=? and dst=? and kind='solves'", (sid, hid)).fetchone())
check("no reputation after 1 confirmation", not c.execute("select solved from agent_reputation where user_id=? and solved>0", (B,)).fetchone())
c.close()
code, r = run(v.solution_confirm(v.SolutionConfirmRequest(user_id=B, solution_id=sid)))
check("author cannot confirm own solution", code == 403)
run(v.solution_confirm(v.SolutionConfirmRequest(user_id=C, solution_id=sid)))
code, r = run(v.solution_confirm(v.SolutionConfirmRequest(user_id=D, solution_id=sid)))
c = db()
check("3 confirmations -> trusted + reputation", r.get("trusted") and c.execute("select solved from agent_reputation where user_id=?", (B,)).fetchone()[0] == 1)
c.close()
code, r = run(v.help_get(hid, user_id=E))
check("help get shows answers as DATA", code == 200 and r["answers"] and r["answers"][0]["data"])

# projects
code, r = run(v.project_create(v.ProjectCreateRequest(user_id=A, title="Внутренний проект", goal="сделать", topic="p", visibility="private")))
pid = r["project_id"]
code, r = run(v.project_node(pid, v.ProjectNodeRequest(user_id=A, title="Шаг 1")))
n1 = r["node_id"]
code, r = run(v.project_node(pid, v.ProjectNodeRequest(user_id=A, title="Шаг 2")))
n2 = r["node_id"]
code, r = run(v.project_get(pid, user_id=E))
check("private project hidden from outsiders", code == 403)
run(v.project_member(pid, v.ProjectMemberRequest(user_id=A, email=C, role="helper", node_id=n1)))
code, r = run(v.project_member(pid, v.ProjectMemberRequest(user_id=C, email=D, role="member")))
check("only owner invites", code == 403)
code, r = run(v.project_get(pid, user_id=C))
check("helper sees only its node", code == 200 and [n["node_id"] for n in r["nodes"]] == [n1])
code, r = run(v.project_node_status(pid, n2, v.ProjectNodeStatusRequest(user_id=C, status="done")))
check("helper cannot touch other nodes", code == 403)
run(v.project_node_status(pid, n1, v.ProjectNodeStatusRequest(user_id=A, status="done")))
code, r = run(v.project_get(pid, user_id=A))
check("progress counted by server", r["progress"]["done"] == 1 and r["progress"]["total"] == 2)
code, r = run(v.project_node(pid, v.ProjectNodeRequest(user_id=C, title="Шаг 1 лучше", parent_id=n1, supersedes=n1)))
check("helper edit = new node with supersedes", code in (200, 201) and r.get("supersedes") == n1)
code, r = run(v.project_help(pid, n2, v.ProjectHelpRequest(user_id=A, question="Where is the config")))
c = db()
check("private project help never in shared search", c.execute("select status from cubes_new where cube_id=?", (r["help_id"],)).fetchone()[0] == "quarantine")
c.close()
code, r = run(v.project_create(v.ProjectCreateRequest(user_id=A, title="Открытый", goal="x", topic="p", visibility="open")))
check("open project must be English", code == 422)

# fair 'rate this' slots
c = db()
T2 = "fairslot alpha"
for i, (shown, age) in enumerate([(0, "2026-01-01"), (0, "2026-02-01"), (3, "2025-12-01"), (12, "2025-01-01")]):
    c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, shown, created_at) values (?,?,?,?,?,?,?,?,?,?)",
              ("fs_%d" % i, "fair %d" % i, T2, "r", "t", "community", A, "warning", shown, age))
c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, shown, created_at) values ('fs_orphan','orphan fairslot tip','fairslot.beta.never','r','t','community',?, 'lifehack', 0, '2024-01-01')", (A,))
c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, shown) values ('fs_mine','mine',?,'r','t','community',?, 'moment', 0)", (T2, B))
cand = [r[0] for r in cv.new_candidates(c, T2, B, 8)]
check("rate slots: unrated + least shown first, FIFO", cand[:2] == ["fs_0", "fs_1"] and cand.index("fs_2") > cand.index("fs_1"))
check("rate slots: capped cube (12 shows, 0 ratings) excluded", "fs_3" not in cand)
check("rate slots: own cube excluded", "fs_mine" not in cand)
check("rate slots: never-queried topic surfaces via related word", "fs_orphan" in cand)
c.execute("insert or replace into cube_outcomes (cube_id, user_id, outcome, ts) values ('fs_3', ?, 'helped', '')", (C,))
check("a rating unlocks more impressions", "fs_3" in [r[0] for r in cv.new_candidates(c, T2, B, 8)])
check("viewer's already-rated cube not offered again", "fs_3" not in [r[0] for r in cv.new_candidates(c, T2, C, 8)])
c.execute("insert into cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, shown) values ('fs_dust','dust',?,'r','t','community',?, 'moment', 15)", (T2, A))
aged = cv.age_out(c)
check("age-out: 0 ratings after N impressions -> court", "fs_dust" in aged and c.execute("select 1 from court_queue where cube_id='fs_dust'").fetchone() and "fs_3" not in aged)
check("age-out is once", "fs_dust" not in cv.age_out(c))
st = cv.unrated_stats(c)
check("unrated stats", st["unrated"] >= 1 and st["aged_to_court"] >= 1 and "eligible_for_rate_slots" in st)
p3 = cv.select_pack(c, T2, B, 1, record=False)
check("pack uses fair slots", [p["cube_id"] for p in p3 if p["note"].startswith("new")] == ["fs_0", "fs_1"])
c.commit(); c.close()

# negative ratings -> court, with reasons; same owner or IP = one client
code, r = run(v.vote_experience(v.VoteRequest(cube_id="fs_1", user_id=B, vote=-1, topic=T2)))
check("negative rating without reason -> 422", code == 422)
def rq(ip):
    return types.SimpleNamespace(headers={"x-real-ip": ip}, client=None)
run(v.vote_experience(v.VoteRequest(cube_id="fs_1", user_id=B, vote=-1, topic=T2, reason="wrong flag, breaks build"), rq("10.0.0.1")))
run(v.vote_experience(v.VoteRequest(cube_id="fs_1", user_id=C, vote=-1, topic=T2, reason="same here"), rq("10.0.0.1")))
code, r = run(v.vote_experience(v.VoteRequest(cube_id="fs_1", user_id=D, vote=-1, topic=T2, reason="outdated"), rq("10.0.0.2")))
c = db()
check("same IP counts as one client (2 clients, not in court)", r.get("negative_clients") == 2 and not c.execute("select 1 from court_queue where cube_id='fs_1'").fetchone())
c.close()
code, r = run(v.vote_experience(v.VoteRequest(cube_id="fs_1", user_id=E, vote=-1, topic=T2, reason="harmful advice"), rq("10.0.0.3")))
c = db()
cq = c.execute("select reason from court_queue where cube_id='fs_1'").fetchone()
check("3 distinct negative clients -> court automatically", r.get("in_court") and cq and r.get("cube_status") == "deprecated")
check("court reason carries the complaints", cq and "harmful advice" in cq[0] and "outdated" in cq[0])
check("one owner = one client", cv._clusters([("x@a", "1.1.1.1"), ("X@a", "2.2.2.2"), ("y@b", "")]) == 2)
check("IP chain merges clients", cv._clusters([("a", "1"), ("b", "1"), ("b", "2"), ("c", "2"), ("d", "")]) == 2)
c.close()

# live db untouched by this test
lc = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
check("live shared db untouched (no test cubes)", not lc.execute("select 1 from cubes_new where cube_id like 'cv2_%'").fetchone())
lc.close()
for u in U:
    for f in glob.glob("/data/skv/metadata_store/" + "".join(ch for ch in u if ch.isalnum() or ch in "_-") + ".db*"):
        os.remove(f)
print(f"\n{sum(res)}/{len(res)} passed", flush=True)
sys.exit(0 if all(res) else 1)
