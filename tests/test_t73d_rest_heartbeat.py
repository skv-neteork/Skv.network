"""T73d: constitution heartbeat on REST /agent/turn (same const_bind.on_turn as MCP).

Run: PYTHONPATH=src python3 -m unittest tests.test_t73d_rest_heartbeat
"""
import inspect
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.pop("SKV_CONST_BIND", None)

from app import const_bind as CB  # noqa: E402
from app import rest_turn as RT  # noqa: E402

# test_rest_turn_watch patches RT._turn_inner / RT._req and does not restore them.
_REAL_TURN_INNER = RT._turn_inner
_REAL_REQ = RT._req


class HeartbeatHelper(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self._db = CB.DB
        CB.DB = self.db
        os.environ.pop("SKV_CONST_BIND", None)

    def tearDown(self):
        CB.DB = self._db
        if os.path.exists(self.db):
            os.remove(self.db)
        os.environ.pop("SKV_CONST_BIND", None)

    def hb(self, result=None, user="u@x", session="s1", msg="hi", ref="t1u", **kw):
        base = {"verdict": "pass", "saved": True, "seal": "🔐 SKV | #001·abcd", "duties": [],
                "facts": [], "cubes": [], "self_check": ["x"], "summary_due": None}
        if result is not None:
            base.update(result)
        return RT._const_heartbeat(base, user, session, msg, ref, **kw)

    def test_first_turn_adds_block_and_manifest_and_keeps_fields(self):
        r = self.hb()
        self.assertIn("constitution", r)
        self.assertIn("constitution_manifest", r)
        b = r["constitution"]
        self.assertEqual(set(b), {"v", "hash", "rule", "stale"})
        self.assertLessEqual(len(json.dumps(b, separators=(",", ":"))), 120)
        self.assertFalse(b["stale"])
        self.assertLessEqual(len(r["constitution_manifest"]), 650)
        # backward compatible: original fields stay, names unchanged
        for k in ("verdict", "saved", "seal", "duties", "facts", "cubes", "self_check", "summary_due"):
            self.assertIn(k, r)

    def test_l1_stays_in_duties_and_summary_due(self):
        due = {"l1": "send l1_summary at task start/end"}
        reminders = "MISSED? L1 summary — raw waiting; L1 5–7% of batch"
        r = self.hb({"summary_due": due, "duties": [due, reminders]})
        self.assertEqual(r["summary_due"], due)
        self.assertIn(due, r["duties"])
        self.assertIn(reminders, r["duties"])
        self.assertIn("constitution", r)

    def test_second_turn_no_manifest_rotation_and_ack(self):
        a = self.hb(ref="t1u", msg="m1")
        b = self.hb(ref="t2u", msg="m2")
        self.assertIn("constitution_manifest", a)
        self.assertNotIn("constitution_manifest", b)
        self.assertNotEqual(a["constitution"]["rule"], b["constitution"]["rule"])
        r = self.hb(ref="t3u", msg="m3", ack=True)
        self.assertFalse(r["constitution"]["stale"])
        d = list(CB.metrics("u@x", 1, db=self.db).values())[0]
        self.assertEqual(d["turns"], 3)
        self.assertEqual(d["manifest_shown"], 1)
        self.assertEqual(d["manifest_acked"], 1)

    def test_ack_const_alias_and_context_reset(self):
        self.hb(ref="t1u", msg="m1")
        self.hb(ref="t2u", msg="m2")
        r = self.hb(ref="t3u", msg="m3", reset=True)
        self.assertIn("constitution_manifest", r)
        r2 = self.hb(ref="t4u", msg="m4", ack=True)
        self.assertNotIn("constitution_manifest", r2)

    def test_same_message_is_not_a_new_turn(self):
        a = self.hb(ref="t5u", msg="same")
        b = self.hb(ref="t5u", msg="same")
        self.assertEqual(a["constitution"]["rule"], b["constitution"]["rule"])

    def test_stale_after_ten_and_every_tenth_manifest(self):
        shown = []
        stale_at = []
        for n in range(1, 12):
            r = self.hb(ref="t%du" % n, msg="m%d" % n)
            if "constitution_manifest" in r:
                shown.append(n)
            if r["constitution"]["stale"]:
                stale_at.append(n)
        self.assertEqual(shown, [1, 11])
        self.assertEqual(stale_at, [10, 11])

    def test_context_and_non_dict_and_no_user_untouched(self):
        ctx = {"mode": "context", "facts": []}
        self.assertIs(RT._const_heartbeat(ctx, "u@x", "s"), ctx)
        self.assertEqual(RT._const_heartbeat("plain", "u@x", "s"), "plain")
        v = {"verdict": "pass", "saved": True, "seal": "x"}
        self.assertEqual(RT._const_heartbeat(v, "", "s"), v)
        self.assertNotIn("constitution", v)

    def test_kill_switch_env(self):
        os.environ["SKV_CONST_BIND"] = "0"
        r = self.hb()
        self.assertNotIn("constitution", r)
        self.assertNotIn("constitution_manifest", r)
        self.assertEqual(r["verdict"], "pass")
        os.environ.pop("SKV_CONST_BIND")
        r2 = self.hb(ref="t2u", msg="m2")
        self.assertIn("constitution", r2)

    def test_kill_switch_file(self):
        cfg = tempfile.mktemp(suffix=".json")
        orig = CB.CFG_PATH
        try:
            with open(cfg, "w") as fh:
                json.dump({"enabled": False}, fh)
            CB.CFG_PATH = cfg
            CB._C.update(m=None, on=True)  # force reload
            r = self.hb()
            self.assertNotIn("constitution", r)
        finally:
            CB.CFG_PATH = orig
            CB._C.update(m=None, on=True)
            if os.path.exists(cfg):
                os.remove(cfg)

    def test_no_seal_and_missed_metrics(self):
        self.hb({"verdict": "revise", "saved": False, "seal": None,
                 "duties": [{"id": "missed_turns"}]}, wrote=True)
        d = list(CB.metrics("u@x", 1, db=self.db).values())[0]
        self.assertEqual((d["turns_no_seal"], d["missed_turns"]), (1, 1))

    def test_heartbeat_never_raises(self):
        r = RT._const_heartbeat({"verdict": "pass", "saved": True, "seal": "x"},
                                "u@x", "s", db_should_not_exist=True) if False else \
            RT._const_heartbeat({"verdict": "pass", "saved": True, "seal": "x"},
                                "u@x", "s")
        # broken db path
        saved = CB.DB
        try:
            CB.DB = "/nonexistent_dir/x.db"
            r = RT._const_heartbeat({"verdict": "pass", "saved": True, "seal": "x"}, "u@x", "s")
            self.assertEqual(r["verdict"], "pass")
            self.assertNotIn("constitution", r)
        finally:
            CB.DB = saved


class TurnInnerWiring(unittest.TestCase):
    """_turn_inner / turn() pass const_ack, ack, context_reset and attach the heartbeat; L1 fields stay."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "cb.db")
        self._cbdb = CB.DB
        CB.DB = self.db
        self._rtdb = RT.DB
        self._ctdb = RT.COMPACT_DB
        self._log = RT.SEAL_LOG
        RT.DB = os.path.join(self.tmp, "rt.db")
        RT.COMPACT_DB = os.path.join(self.tmp, "ct.db")
        RT.SEAL_LOG = os.path.join(self.tmp, "seals.log")
        self._next, self._code = RT._next_seal, RT.seal_code
        RT._next_seal = lambda key, user, same=False: 1
        RT.seal_code = lambda user, n, text: "abcd"
        RT._turn_inner = _REAL_TURN_INNER
        RT._req = _REAL_REQ
        self._req = RT._req
        due = {"l1": "send l1 at task start/end"}
        reminders = "MISSED? L1 summary — raw waiting"

        def fake_req(key, method, path, body=None, params=None, base=None):
            if path == "/constitution/status":
                return {"installed_by": "t73d@test"}
            if path == "/search":
                return {"results": []}
            if path == "/remember":
                return {"ok": True, "event_id": "t73d@test::ev1",
                        "summary_due": due, "reminders": reminders}
            if path == "/agent/second-look":
                return {"status": "pass"}
            if path == "/api/cubes/search":
                return {"results": []}
            return {}
        RT._req = fake_req
        self.due, self.reminders = due, reminders
        self._prof = mock.patch("app.profile.precheck", return_value={})
        self._prof.start()
        # board / profile.relevant / room already fail soft
        os.environ.pop("SKV_CONST_BIND", None)

    def tearDown(self):
        self._prof.stop()
        RT._req = _REAL_REQ
        RT._turn_inner = _REAL_TURN_INNER
        RT._next_seal = self._next
        RT.seal_code = self._code
        RT.DB, RT.COMPACT_DB, RT.SEAL_LOG = self._rtdb, self._ctdb, self._log
        CB.DB = self._cbdb
        os.environ.pop("SKV_CONST_BIND", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_saved_turn_has_heartbeat_and_l1_both_places(self):
        r = RT.turn("sk_x", "hello", "Hello back.")
        self.assertEqual(r["verdict"], "pass")
        self.assertTrue(r["saved"])
        self.assertIn("constitution", r)
        self.assertIn("constitution_manifest", r)
        self.assertEqual(set(r["constitution"]), {"v", "hash", "rule", "stale"})
        self.assertLessEqual(len(json.dumps(r["constitution"], separators=(",", ":"))), 120)
        self.assertEqual(r["summary_due"], self.due)
        self.assertTrue(any(self.due == d or str(d) == str(self.due) for d in r["duties"]))
        self.assertTrue(any(self.reminders in str(d) for d in r["duties"]))
        # no fields removed
        for k in ("verdict", "saved", "event_id", "seal", "facts", "cubes", "self_check", "duties", "summary_due"):
            self.assertIn(k, r)

    def test_context_mode_has_no_heartbeat(self):
        r = RT.turn("sk_x", "hello")
        self.assertEqual(r["mode"], "context")
        self.assertNotIn("verdict", r)
        self.assertNotIn("constitution", r)
        self.assertNotIn("constitution_manifest", r)

    def test_ack_const_and_const_ack_and_reset(self):
        RT.turn("sk_x", "m1", "a1", session_id="sessA")
        r2 = RT.turn("sk_x", "m2", "a2", session_id="sessA")
        self.assertNotIn("constitution_manifest", r2)
        r3 = RT.turn("sk_x", "m3", "a3", session_id="sessA", context_reset=True)
        self.assertIn("constitution_manifest", r3)
        r4 = RT.turn("sk_x", "m4", "a4", session_id="sessA", const_ack=True)
        self.assertFalse(r4["constitution"]["stale"])
        r5 = RT.turn("sk_x", "m5", "a5", session_id="sessB", ack="const")
        self.assertIn("constitution_manifest", r5)  # new session
        d = list(CB.metrics("t73d@test", 1, db=self.db).values())[0]
        self.assertGreaterEqual(d["manifest_acked"], 1)

    def test_kill_switch_leaves_turn_working(self):
        os.environ["SKV_CONST_BIND"] = "0"
        r = RT.turn("sk_x", "hello", "Hello back.", session_id="off")
        self.assertEqual(r["verdict"], "pass")
        self.assertTrue(r["saved"])
        self.assertNotIn("constitution", r)
        self.assertEqual(r["summary_due"], self.due)

    def test_unauthorized_unchanged(self):
        r = RT.turn("", "hello", "x")
        self.assertEqual(r["status"], 401)
        self.assertNotIn("constitution", r)

    def test_turn_signature_accepts_t73_params(self):
        names = inspect.signature(RT.turn).parameters
        for n in ("const_ack", "ack", "context_reset"):
            self.assertIn(n, names)

    def test_guards_request_and_handlers_accept_params(self):
        # Avoid importing v7_guards (it pulls the full API). Check the source instead.
        path = os.path.join(os.path.dirname(RT.__file__), "routers", "v7_guards.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("const_ack: bool = False", src)
        self.assertIn('ack: str = ""', src)
        self.assertIn("context_reset: bool = False", src)
        self.assertIn("const_ack=req.const_ack", src)
        self.assertIn("ack=req.ack", src)
        self.assertIn("context_reset=req.context_reset", src)
        self.assertIn("const_ack=const_ack, ack=ack, context_reset=context_reset", src)


if __name__ == "__main__":
    unittest.main()
