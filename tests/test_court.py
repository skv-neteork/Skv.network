"""Court judge test: strict parsing, abstain->third model, and a live planted trivial cube (cleaned up)."""
import importlib.util, sqlite3, sys
sp = importlib.util.spec_from_file_location("ev", "/root/skv-core/ops/evolver.py"); ev = importlib.util.module_from_spec(sp); sp.loader.exec_module(ev)
res = []
def check(n, ok): res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n, flush=True)
check("strict json ok", ev._strict_json('{"verdict":"remove","reason":"banal"}')["verdict"] == "remove")
check("broken json -> None", ev._strict_json('Here is my thinking... verdict: keep') is None)
check("line ok", ev._strict_line("VERDICT: fix | weak")["verdict"] == "fix")
check("prose line -> None", ev._strict_line("Here's a thinking process: keep") is None)
real_ask, real_post = ev.ask, ev._post
ev._post = lambda *a, **k: "rewritten"
def fake(table):
    return lambda model, prompt: table.get(model)
ev.ask = fake({ev.J1: {"verdict": "remove", "reason": "x"}, ev.J2: None, ev.J3: {"verdict": "remove", "reason": "y"}})
v = ev.judge("t", "r"); check("J2 unparsed = abstain, J3 decides remove", [x[1] for x in v["votes"]] == ["remove", "abstain", "remove"])
ev.ask = fake({ev.J1: {"verdict": "remove", "reason": "x"}, ev.J2: None, ev.J3: None})
v = ev.judge("t", "r"); check("both abstain -> no second remove", sum(x[1] == "remove" for x in v["votes"]) == 1 and v["rules"])
ev.ask = fake({ev.J1: None})
check("first judge unparsed -> skip", ev.judge("t", "r").get("skip"))
ev.ask, ev._post = real_ask, real_post
# live planted trivial cube
D = ev.DB; c = sqlite3.connect(D); CID = "cube_courttest02"
c.execute("insert or replace into cubes_new (cube_id,essence,subject_action_object,rules_markdown,evidence,status,created_by) values (?,?,?,?,?,?,?)",
          (CID, "Drink water", "courttest", "Drink water when thirsty.", "test", "community", "court_test"))
c.execute("insert or replace into court_queue values (?,?,datetime('now'))", (CID, "planted trivial")); c.commit()
ev.drain()
st = c.execute("select status from cubes_new where cube_id=?", (CID,)).fetchone()
votes = c.execute("select judge, verdict, reason from court_verdicts where cube_id=?", (CID,)).fetchall()
arch = c.execute("select count(*) from cubes_archive where cube_id=?", (CID,)).fetchone()[0]
print("live:", st, votes, "archived copies:", arch)
removers = {j for j, v, _ in votes if v == "remove"}
check("live: no unparsed vote counted as keep", all(v in ("keep", "fix", "remove", "abstain") for _, v, _ in votes))
check("live: archived iff two clear removes", (st[0] == "archived") == (len(removers) >= 2) and (arch == 1) == (len(removers) >= 2))
for t in ("cubes_new", "cubes_archive", "court_verdicts", "court_queue"):
    c.execute(f"delete from {t} where cube_id=?", (CID,))
c.commit()
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
