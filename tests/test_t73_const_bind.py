"""T73: constitution <-> tools binding: registry, tool map and tags, turn heartbeat + manifest + MANDATORY escalation, soft gate, metrics, wrappers."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, "/root/skv-core/src")
sys.path.insert(0, "/root/skv-core/mcp")
os.environ.pop("SKV_CONST_BIND", None)
os.environ.setdefault("SKV_API_KEY", "x")
from app import const_bind as CB  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)

    def turn(self, n, user="u@x", scope="s1", **kw):
        kw.setdefault("db", self.db)
        kw.setdefault("msg_key", "m%d" % n)
        return CB.on_turn(user, scope, **kw)


class RegistryTests(Base):
    def test_atoms_and_version(self):
        reg = CB.registry()
        self.assertEqual(reg["n"], len(CB.ATOMS))
        self.assertGreaterEqual(reg["n"], 7)
        self.assertLessEqual(reg["n"], 25)
        self.assertEqual(len(reg["hash"]), 6)
        for a in CB.ATOMS:
            self.assertLessEqual(len(a[1]), 66, a[0])
        self.assertEqual(reg["drift"], [], "an atom lost its section in the source text")

    def test_rebuild_when_source_changes_and_drift(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "c.md")
        try:
            shutil.copy(CB.SRC, p)
            r1 = CB.registry(p)
            with open(p, "a") as fh:
                fh.write("\nextra line\n")
            os.utime(p, (os.path.getmtime(p) + 5, os.path.getmtime(p) + 5))
            r2 = CB.registry(p)
            self.assertNotEqual(r1["hash"], r2["hash"])
            self.assertEqual(r1["v"], r2["v"])
            with open(p, "w") as fh:
                fh.write("SKV CONSTITUTION - COMPACT v9\nonly this\n")
            os.utime(p, (os.path.getmtime(p) + 10, os.path.getmtime(p) + 10))
            r3 = CB.registry(p)
            self.assertEqual(r3["v"], "9")
            self.assertIn("R04", r3["drift"])
        finally:
            shutil.rmtree(d)
            CB.registry()   # back to the real source for the other tests

    def test_manifest_size_and_content(self):
        m = CB.manifest_text()
        self.assertLessEqual(len(m), 650)
        for a in CB.ATOMS:
            self.assertIn(a[0] + " ", m)
        self.assertIn("constitution_get", m)
        self.assertIn("const_ack", m)
        self.assertLessEqual(len(CB.manifest_text(mandatory_k=4)), 720)
        self.assertTrue(CB.manifest_text(mandatory_k=4).startswith("MANDATORY"))


class ToolMapTests(Base):
    def test_every_visible_tool_is_mapped_tagged_and_small(self):
        import mcp_skv as M
        names = {t.name for t in M.mcp._tool_manager.list_tools()}
        self.assertGreaterEqual(len(names), 30)
        tot = 0
        reg = CB.registry()
        for n in names:
            self.assertIn(n, CB.TOOLS, n)
            tg = CB.tag(n, reg)
            self.assertTrue(tg.startswith("[C v"), n)
            self.assertLessEqual(len(tg), 60)
            tot += len(tg) + 1
            self.assertLessEqual(len(CB.line(n)), 80)
            if CB.line(n):
                self.assertTrue(CB.line(n).startswith("[C:"), n)
        self.assertLessEqual(tot, 2500)

    def test_every_tool_gets_h(self):
        for n, (atoms, ln, _d) in CB.TOOLS.items():
            self.assertIn("H", atoms, n)
            self.assertRegex(CB.tag(n), r":H[,\]]")   # the tag starts with H right after the version

    def test_descriptions_carry_tags_in_the_real_server(self):
        import mcp_skv as M
        ts = {t.name: t for t in M.mcp._tool_manager.list_tools() if t.name in M.VISIBLE}
        if M._CB is None:
            self.skipTest("const_bind not loaded")
        for n, t in ts.items():
            self.assertIn("[C v", t.description, n)

    def test_line_and_prefix(self):
        self.assertEqual(CB.line("turn"), "")
        self.assertEqual(CB.line("step_zero"), "")
        r = CB.prefix_reply("memory_search", '{"a":1}')
        first, rest = r.split("\n", 1)
        self.assertTrue(first.startswith("[C:H,R02]"))
        self.assertEqual(json.loads(rest), {"a": 1})
        self.assertEqual(CB.prefix_reply("turn", '{"a":1}'), '{"a":1}')


class HeartbeatTests(Base):
    def test_first_turn_manifest_and_block_size(self):
        r = self.turn(1)
        self.assertIn("constitution_manifest", r)
        b = r["constitution"]
        self.assertEqual(set(b), {"v", "hash", "rule", "stale"})
        self.assertLessEqual(len(json.dumps(b, separators=(",", ":"))), 120)
        self.assertFalse(b["stale"])

    def test_rotation_covers_all_atoms_and_each_block_fits(self):
        seen = []
        for n in range(1, len(CB.ATOMS) + 1):
            r = self.turn(n, ack=True)
            seen.append(r["constitution"]["rule"].split(" ")[0])
            self.assertLessEqual(len(json.dumps(r["constitution"], separators=(",", ":"))), 120)
        self.assertEqual(seen, [a[0] for a in CB.ATOMS])

    def test_manifest_every_tenth_turn_only(self):
        shown = [n for n in range(1, 32) if "constitution_manifest" in self.turn(n)]
        self.assertEqual(shown[:4], [1, 11, 21, 31])

    def test_context_reset_and_new_session_and_version_change(self):
        self.turn(1); self.turn(2)
        self.assertIn("constitution_manifest", self.turn(3, reset=True))
        self.assertNotIn("constitution_manifest", self.turn(4))
        self.assertIn("constitution_manifest", self.turn(1, scope="s2"))   # new session
        self.assertNotIn("constitution_manifest", self.turn(2, scope="s2"))
        orig = CB.registry
        try:
            reg = dict(orig()); reg["ver"] = "9.zzzzzz"; reg["v"] = "9"
            CB.registry = lambda src=None: reg
            self.assertIn("constitution_manifest", self.turn(5))
        finally:
            CB.registry = orig

    def test_same_message_is_not_a_new_turn(self):
        self.turn(1)
        a = CB.on_turn("u@x", "s1", msg_key="same", db=self.db)
        b = CB.on_turn("u@x", "s1", msg_key="same", db=self.db)
        self.assertEqual(a["constitution"]["rule"], b["constitution"]["rule"])
        self.assertEqual(self.turn(3)["constitution"]["rule"].split(" ")[0], CB.ATOMS[2][0])

    def test_stale_after_ten_turns_without_ack_and_ack_clears(self):
        self.assertFalse(self.turn(1)["constitution"]["stale"])
        for n in range(2, 10):
            self.assertFalse(self.turn(n)["constitution"]["stale"])
        self.assertTrue(self.turn(10)["constitution"]["stale"])   # 10 turns since the session start without an acknowledgement
        r = self.turn(11, ack=True)
        self.assertFalse(r["constitution"]["stale"])

    def test_escalation(self):
        out = {}
        for n in range(1, 70):
            out[n] = self.turn(n)
        man = {n: r["constitution_manifest"] for n, r in out.items() if "constitution_manifest" in r}
        # manifests at 1, 11, 21, 31 (3 ignored) and 41 (4th ignored -> becomes MANDATORY) and then every turn
        self.assertTrue(all(not man[n].startswith("MANDATORY") for n in (1, 11, 21, 31)))
        self.assertTrue(man[41].startswith("MANDATORY"))
        self.assertIn(42, man); self.assertIn(69, man)
        self.assertTrue(all(man[n].startswith("MANDATORY") for n in range(41, 70)))
        r = self.turn(70, ack=True)
        self.assertNotIn("constitution_manifest", r)
        self.assertFalse(r["constitution"]["stale"])
        self.assertNotIn("constitution_manifest", self.turn(71))

    def test_ack_param_counts_metrics(self):
        self.turn(1); self.turn(2, ack=True)
        m = CB.metrics("u@x", 1, db=self.db)
        d = list(m.values())[0]
        self.assertEqual(d["turns"], 2)
        self.assertEqual(d["manifest_shown"], 1)
        self.assertEqual(d["manifest_acked"], 1)

    def test_escalation_metric_and_no_seal(self):
        for n in range(1, 45):
            self.turn(n, no_seal=(n == 3), missed=(n == 4))
        d = list(CB.metrics("u@x", 1, db=self.db).values())[0]
        self.assertEqual(d["escalations"], 1)
        self.assertEqual(d["turns_no_seal"], 1)
        self.assertEqual(d["missed_turns"], 1)

    def test_accounts_and_sessions_are_independent(self):
        a = self.turn(1, user="a@x"); b = self.turn(1, user="b@x")
        self.assertIn("constitution_manifest", a); self.assertIn("constitution_manifest", b)
        self.turn(2, user="a@x")
        self.assertEqual(self.turn(2, user="b@x")["constitution"]["rule"].split(" ")[0], CB.ATOMS[1][0])

    def test_kill_switch_and_errors(self):
        os.environ["SKV_CONST_BIND"] = "0"
        try:
            self.assertEqual(self.turn(1), {})
            self.assertIsNone(CB.gate("u@x", "cube_create", "", db=self.db))
        finally:
            os.environ.pop("SKV_CONST_BIND", None)
        self.assertEqual(CB.on_turn("", "s", db=self.db), {})
        self.assertEqual(CB.on_turn("u@x", "s", db="/nonexistent_dir/x.db"), {})


class GateTests(Base):
    def test_no_turn_yet_is_stale_gate_then_ack_executes(self):
        g = CB.gate("u@x", "cube_create", "", db=self.db)
        self.assertEqual(g["gate"], "constitution")
        self.assertEqual(g["retry_with"], "ack=const")
        self.assertLessEqual(len(g["manifest"]), 650)
        self.assertFalse(g["executed"])
        self.assertIsNone(CB.gate("u@x", "cube_create", "const", db=self.db))     # ack executes
        self.assertIsNone(CB.gate("u@x", "cube_create", "", db=self.db))          # and counts as an ack: fresh now
        d = list(CB.metrics("u@x", 1, db=self.db).values())[0]
        self.assertEqual((d["gate_triggers"], d["gate_acks"]), (1, 1))

    def test_fresh_executes_immediately_and_stale_after_ten_turns(self):
        for n in range(1, 4):
            self.turn(n)
        self.assertIsNone(CB.gate("u@x", "cube_create", "", db=self.db))
        for n in range(4, 12):
            self.turn(n)
        self.assertIsNotNone(CB.gate("u@x", "cube_create", "", db=self.db))
        self.assertIsNone(CB.gate("u@x", "cube_create", "CONST", db=self.db))
        self.assertIsNone(CB.gate("u@x", "cube_create", "", db=self.db))
        self.assertFalse(self.turn(12)["constitution"]["stale"])

    def test_turn_ack_makes_the_gate_fresh(self):
        for n in range(1, 13):
            self.turn(n)
        self.assertIsNotNone(CB.gate("u@x", "vault_inject", "", db=self.db))
        self.turn(13, ack=True)
        self.assertIsNone(CB.gate("u@x", "vault_inject", "", db=self.db))

    def test_wrong_ack_value_does_not_pass(self):
        self.assertIsNotNone(CB.gate("u@x", "cube_create", "yes", db=self.db))
        self.assertIsNotNone(CB.gate("u@x", "cube_create", "true", db=self.db))

    def test_gate_needed(self):
        self.assertTrue(CB.gate_needed("cube_create", {}))
        self.assertFalse(CB.gate_needed("cube_create", {"cube_publish": False}))
        self.assertTrue(CB.gate_needed("vault_inject", {}))
        self.assertTrue(CB.gate_needed("joint_project", {"action": "invite"}))
        self.assertFalse(CB.gate_needed("joint_project", {"action": "list"}))
        for t in ("memory_search", "memory_start", "turn", "board_act", "drive_put", "cube_vote", "cube_search", "consult", "step_zero"):
            self.assertFalse(CB.gate_needed(t, {"action": "invite"}), t)
        probe = lambda cid: {"hooks": True, "author": "other@x", "me": "me@x"}
        self.assertTrue(CB.gate_needed("cube_install", {"cube_id": "c"}, probe))
        self.assertFalse(CB.gate_needed("cube_install", {"cube_id": "c"}, lambda c: {"hooks": False, "author": "o", "me": "me"}))
        self.assertFalse(CB.gate_needed("cube_install", {"cube_id": "c"}, lambda c: {"hooks": True, "author": "ME@x", "me": "me@x"}))
        self.assertFalse(CB.gate_needed("cube_install", {"cube_id": "c"}, None))
        self.assertFalse(CB.gate_needed("cube_install", {"cube_id": "c"}, lambda c: 1 / 0))

    def test_gate_never_covers_reads_or_own_memory(self):
        self.assertTrue(set(CB.GATED) == {"cube_create", "cube_install", "vault_inject", "joint_project"})


class WrapperTests(Base):
    """mcp_skv._cb_wrap with dummy tool functions and a temp state db."""

    def setUp(self):
        super().setUp()
        import mcp_skv as M
        self.M = M
        if M._CB is None:
            self.skipTest("const_bind not loaded")
        self._db, self._cid = M._CB.DB, M._caller_id
        M._CB.DB = self.db      # the server loads its own copy of const_bind: patch that one
        M._caller_id = lambda: "w@x"

    def tearDown(self):
        self.M._CB.DB = self._db
        self.M._caller_id = self._cid
        super().tearDown()

    def test_memory_tool_gets_line_and_is_data(self):
        f = self.M._cb_wrap(lambda **k: json.dumps({"hits": []}), "memory_search")
        r = f()
        first, rest = r.split("\n", 1)
        self.assertTrue(first.startswith("[C:H,R02]") and len(first) <= 80)
        self.assertEqual(json.loads(rest), {"hits": [], "is_data": True})

    def test_non_data_tool_json_untouched_apart_from_line(self):
        r = self.M._cb_wrap(lambda **k: '{"ok":true}', "drive_put")()
        self.assertEqual(json.loads(r.split("\n", 1)[1]), {"ok": True})

    def test_cube_create_is_gated_then_executes_with_ack(self):
        calls = []
        f = self.M._cb_wrap(lambda **k: calls.append(k) or '{"ok":true}', "cube_create")
        g = json.loads(f(topic="t", ack=""))
        self.assertEqual(g["gate"], "constitution")
        self.assertEqual(calls, [])
        r = f(topic="t", ack="const")
        self.assertEqual(len(calls), 1)
        self.assertIn('"ok":true', r)
        f(topic="t", ack="")          # fresh now
        self.assertEqual(len(calls), 2)

    def test_reads_are_never_gated(self):
        calls = []
        for n in ("memory_search", "cube_search", "cube_get", "board_list", "drive_list", "consult"):
            self.M._cb_wrap(lambda **k: calls.append(1) or "{}", n)()
        self.assertEqual(len(calls), 6)

    def test_joint_project_only_invite_is_gated(self):
        calls = []
        f = self.M._cb_wrap(lambda **k: calls.append(k) or "{}", "joint_project")
        f(action="list")
        self.assertEqual(len(calls), 1)
        self.assertIn("gate", f(action="invite", email="a@b.c"))
        self.assertEqual(len(calls), 1)

    def test_turn_heartbeat_in_reply(self):
        reply = json.dumps({"verdict": "pass", "saved": True, "seal": "x", "duties": []})
        r = json.loads(self.M._cb_turn(reply, "hi", "t1u", "s", False, False, True))
        self.assertIn("constitution", r)
        self.assertIn("constitution_manifest", r)
        self.assertEqual(r["verdict"], "pass")
        r2 = json.loads(self.M._cb_turn(reply, "hi2", "t2u", "s", False, False, True))
        self.assertNotIn("constitution_manifest", r2)
        # not a turn reply / not json: unchanged
        self.assertEqual(self.M._cb_turn("plain", "x", "", "s", False, False, False), "plain")
        self.assertEqual(self.M._cb_turn('{"a":1}', "x", "", "s", False, False, False), '{"a":1}')

    def test_no_seal_metric(self):
        reply = json.dumps({"verdict": "revise", "saved": False, "seal": None, "duties": [{"id": "missed_turns"}]})
        self.M._cb_turn(reply, "hi", "t1u", "s", False, False, True)
        d = list(self.M._CB.metrics("w@x", 1, db=self.db).values())[0]
        self.assertEqual((d["turns_no_seal"], d["missed_turns"]), (1, 1))


class KillSwitchServerTests(unittest.TestCase):
    def test_env_off_means_no_tags_no_gate_no_lines(self):
        import subprocess
        code = ("import sys,os,json;sys.path.insert(0,'/root/skv-core/mcp');import mcp_skv as M;"
                "ts=[t for t in M.mcp._tool_manager.list_tools() if t.name in M.VISIBLE];"
                "print(json.dumps({'cb':M._CB is None,'tags':sum('[C v' in (t.description or '') for t in ts),'n':len(ts),"
                "'turn_has_hb':'heartbeat' in M.SHORT_DESC['turn'],"
                "'cube_create':M.mcp._tool_manager.get_tool('cube_create').fn(topic='',essence='',rules='')[:12]}))")
        env = dict(os.environ, SKV_CONST_BIND="0", SKV_API_KEY="x")
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
        j = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertTrue(j["cb"]); self.assertEqual(j["tags"], 0); self.assertFalse(j["turn_has_hb"]); self.assertGreater(j["n"], 30)
        self.assertNotIn("gate", j["cube_create"])


if __name__ == "__main__":
    unittest.main()
