"""T72: duty rules rotate, escalate to MANDATORY after N ignored, reset on compliance or dismissal."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, "/root/skv-core/src")
os.environ.pop("SKV_DUTY_RULES", None)
from app import duty_rules as DR  # noqa: E402


class DutyRulesTests(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.nosh = "/nonexistent_shared.db"

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)

    def t(self, **kw):
        kw.setdefault("db", self.db); kw.setdefault("shared_db", self.nosh)
        return DR.on_turn("u@x", "s1", **kw)

    def rules(self, **kw):
        return (self.t(**kw) or {}).get("rules", [])

    def test_rotation_one_rule_per_turn_covers_all(self):
        seen = [self.rules()[0].split(":")[0] for _ in range(len(DR.DUTIES))]
        self.assertEqual(len(set(seen)), len(DR.DUTIES))
        for r in [self.rules() for _ in range(3)]:
            self.assertEqual(len(r), 1)
            self.assertLess(len(r[0]), 330)

    def test_event_adds_relevant_rule_max_two(self):
        r = self.rules(events={"l1"})
        self.assertIn("L1", r[0]); self.assertEqual(len(r), 2)
        r = self.rules(events={"l1", "l2", "cube"})
        self.assertEqual(len(r), 2)

    def test_done_is_not_shown_again_that_turn(self):
        for _ in range(10):
            r = self.rules(done={"l1"}, events={"l1"})
            self.assertFalse(any(x.startswith("RULE L1") or "MANDATORY: l1" in x for x in r))

    def test_escalation_after_n_ignored_and_pin(self):
        app = {"l1": True}
        last = None
        for i in range(8):   # l1 event every turn, never done
            last = self.rules(events={"l1"}, applicable=app)
        mand = [x for x in last if x.startswith("MANDATORY: l1 reminded")]
        self.assertEqual(len(mand), 1)
        self.assertIn("without action, do it now", mand[0])
        self.assertIn("duty=rule_l1", mand[0])
        # pinned every turn even without the event
        r = self.rules(applicable=app)
        self.assertTrue(any(x.startswith("MANDATORY: l1") for x in r))
        k1 = int(mand[0].split("reminded ")[1].split(" ")[0])
        r2 = self.rules(events={"l1"}, applicable=app)
        k2 = int([x for x in r2 if x.startswith("MANDATORY: l1")][0].split("reminded ")[1].split(" ")[0])
        self.assertGreater(k2, k1)

    def test_not_applicable_never_escalates(self):
        for _ in range(60):
            r = self.rules(applicable={})
            self.assertFalse(any(x.startswith("MANDATORY") for x in r))

    def test_compliance_resets_to_soft(self):
        for _ in range(8):
            self.rules(events={"l1"}, applicable={"l1": True})
        r = self.rules(done={"l1"}, applicable={"l1": True})
        self.assertFalse(any(x.startswith("MANDATORY: l1") for x in r))
        r = self.rules(events={"l1"}, applicable={"l1": True})
        self.assertTrue(any(x.startswith("RULE L1") for x in r))
        self.assertFalse(any(x.startswith("MANDATORY: l1") for x in r))

    def test_dismiss_with_reason_unpins_and_snoozes(self):
        for _ in range(8):
            self.rules(events={"l1"}, applicable={"l1": True})
        r = self.rules(dismissed={"l1": "nothing to summarise"}, applicable={"l1": True})
        self.assertFalse(any("l1" in x.lower() and x.startswith("MANDATORY") for x in r))
        for _ in range(10):
            r = self.rules()
            self.assertFalse(any(x.startswith("RULE L1") for x in r))   # snoozed

    def test_signals_fields_and_dismiss(self):
        done, dis, ev, app = DR.signals({"l1_summary": "x", "critical": "a", "sensitive": ["k"], "profile": [{}], "query": "запомни кодовое слово",
                                         "duty": "rule_vote", "duty_reason": "no cube used", "task_done": True}, {"summary_due": {"l1": "q", "l2": "w"}, "l1_pending": 20})
        self.assertEqual(done, {"l1", "critical", "sensitive", "profile"})
        self.assertEqual(dis, {"vote": "no cube used"})
        self.assertEqual(ev, {"l1", "l2", "cube"})
        self.assertTrue(app["l1"] and app["critical"] and app["cube"])
        done2, dis2, _, _ = DR.signals({"duty": "rule_vote", "duty_reason": ""}, {})
        self.assertEqual(dis2, {})   # a reason is required
        done3, *_ = DR.signals({"duty": "cube_nothing", "duty_reason": "x"}, {})
        self.assertIn("cube", done3)

    def test_disabled_and_bad_input_are_silent(self):
        os.environ["SKV_DUTY_RULES"] = "0"
        try:
            self.assertEqual(self.t(), {})
        finally:
            os.environ.pop("SKV_DUTY_RULES")
        self.assertEqual(DR.on_turn("", "s", db=self.db), {})
        self.assertEqual(DR.on_turn("u", "s", db="/nonexistent_dir/x.db"), {})

    def test_scopes_are_independent(self):
        a = DR.on_turn("u@x", "A", db=self.db, shared_db=self.nosh)["rules"][0]
        b = DR.on_turn("u@x", "B", db=self.db, shared_db=self.nosh)["rules"][0]
        self.assertEqual(a, b)

    def test_external_cube_and_vote_count_as_done(self):
        import sqlite3, time
        sh = tempfile.mktemp(suffix=".db")
        c = sqlite3.connect(sh)
        c.execute("create table cubes_new(cube_id text, created_by text, created_at text)")
        c.execute("create table cube_outcomes(cube_id text, user_id text, outcome text, ts text)")
        c.commit()
        try:
            DR.on_turn("u@x", "S", db=self.db, shared_db=sh, events={"cube", "vote"}, applicable={"cube": True, "vote": True})   # both shown, pending
            now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 5))
            c.execute("insert into cubes_new values('c1','u@x',?)", (now,)); c.execute("insert into cube_outcomes values('c1','u@x','up',?)", (now,)); c.commit()
            DR.on_turn("u@x", "S", db=self.db, shared_db=sh)
            st = {r["duty"]: r for r in DR.stats("u@x", "S", db=self.db)}
            self.assertEqual(st["cube"]["done"], 1); self.assertEqual(st["vote"]["done"], 1)
            self.assertEqual(st["cube"]["ignored"], 0); self.assertEqual(st["vote"]["ignored"], 0)
        finally:
            c.close(); os.remove(sh)

    def test_texts_fit_300_char_cap(self):
        for d in DR.DUTIES:
            self.assertLessEqual(len(DR.rule_text(d)), 300, d)
            self.assertLessEqual(len(DR.mandatory_text(d, 12)), 300, d)

    def test_item_shape_small_and_critical(self):
        it = self.t()
        self.assertEqual(it["id"], "duty_rules"); self.assertEqual(it["severity"], "critical")
        self.assertLess(sum(len(x) for x in it["rules"]), 700)


if __name__ == "__main__":
    unittest.main()
