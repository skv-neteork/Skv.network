"""Unified cube harvest: identify step 3, per-agent state, one cube_harvest duty, resolution aliases."""
import os
import sqlite3
import time
import unittest

from app.room import skills_harvest as sh
from app.room.bridge import STEP_ZERO_NEXT, do_identify, finish_turn
from app.room.identity import resolve_call
from app.room.schema import ensure

INFO = {"key_id": "k-sh", "user_id": "sh-test@example.invalid", "chain_id": "ch-sh", "key_name": "line"}
H = 3600.0


class SkillsHarvestTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        ensure(self.conn)
        self.conn.execute(
            "CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, essence TEXT, actor_agent_id TEXT, session_id TEXT, ev_kind TEXT, author_kind TEXT, gist TEXT)"
        )
        self.conn.commit()
        os.environ.pop("SKV_SKILLS_HARVEST_HOURS", None)
        os.environ.pop("SKV_CUBE_HARVEST_DAYS", None)
        self.t0 = 1_800_000_000.0

    def tearDown(self):
        os.environ.pop("SKV_SKILLS_HARVEST_HOURS", None)
        os.environ.pop("SKV_CUBE_HARVEST_DAYS", None)
        self.conn.close()

    def note(self, now, duty="", cube=None, actor="a1"):
        return sh.turn_note(self.conn, "k", actor, user_id="u@example.invalid", duty=duty, now=now, cube_check=cube)

    def test_identify_adds_step3_once(self):
        a = do_identify(INFO, self.conn, "agent-a", session_id="s1")
        self.assertEqual(a["next"], STEP_ZERO_NEXT)
        self.assertIn(sh.AUTHOR_CUBE_ID, a["skills_step"])
        self.assertIn("skills_none", a["skills_step"])
        self.assertTrue(a["skills_step"].startswith("3)"))
        self.assertIn(a["skills_step"], a["room_text"])
        b = do_identify(INFO, self.conn, "agent-a", session_id="s1")
        self.assertNotIn("skills_step", b)          # same agent again: shown once
        c = do_identify(INFO, self.conn, "agent-b", session_id="s2")
        self.assertIn("skills_step", c)             # another agent: its own state
        self.assertNotIn(a["agent_token"], a["skills_step"])

    def test_default_interval_is_72h_and_configurable(self):
        self.assertEqual(sh.interval_hours(), 72)
        os.environ["SKV_SKILLS_HARVEST_HOURS"] = "24"
        self.assertEqual(sh.interval_hours(), 24)
        os.environ["SKV_SKILLS_HARVEST_HOURS"] = "junk"
        self.assertEqual(sh.interval_hours(), 72)
        os.environ["SKV_SKILLS_HARVEST_HOURS"] = "-5"
        self.assertEqual(sh.interval_hours(), 72)
        os.environ.pop("SKV_SKILLS_HARVEST_HOURS", None)
        os.environ["SKV_CUBE_HARVEST_DAYS"] = "2"
        self.assertEqual(sh.interval_hours(), 48)

    def test_agent_without_state_is_asked_once(self):
        first = self.note(self.t0)
        self.assertIn("first time", first)
        self.assertIn(sh.AUTHOR_CUBE_ID, first)
        self.assertIn("DUTY cube_harvest", first)
        self.assertEqual(self.note(self.t0 + 10 * H), "")

    def test_reminder_every_interval_when_unresolved(self):
        self.note(self.t0)
        self.assertEqual(self.note(self.t0 + 71 * H), "")
        again = self.note(self.t0 + 73 * H)
        self.assertIn("every ~72h", again)
        self.assertIn("skills_none", again)
        self.assertIn("DUTY cube_harvest", again)
        self.assertNotIn("DUTY skills_harvest", again)
        self.assertEqual(self.note(self.t0 + 100 * H), "")          # next one 72h after the reminder
        self.assertIn("DUTY cube_harvest", self.note(self.t0 + 146 * H))

    def test_explicit_skip_resolves_and_restarts_period(self):
        self.note(self.t0)
        self.assertEqual(self.note(self.t0 + 60 * H, duty="skills_none"), "")
        row = sh._row(self.conn, "k", "a1")
        self.assertEqual(row[3], "skills_none")
        self.assertEqual(self.note(self.t0 + 100 * H), "")          # 40h after the skip: quiet
        self.assertIn("DUTY cube_harvest", self.note(self.t0 + 133 * H))   # 73h after the skip

    def test_skip_before_any_state_and_alias(self):
        self.assertEqual(self.note(self.t0, duty="skills_skip"), "")
        self.assertEqual(sh._row(self.conn, "k", "a1")[3], "skills_skip")
        self.assertEqual(self.note(self.t0 + H), "")

    def test_all_resolution_aliases(self):
        for i, duty in enumerate(sh.RESOLVING_DUTIES):
            actor = "alias-%d" % i
            self.note(self.t0, actor=actor)
            self.assertEqual(self.note(self.t0 + H, duty=duty, actor=actor), "")
            self.assertEqual(sh._row(self.conn, "k", actor)[3], duty)
            self.assertEqual(self.note(self.t0 + 60 * H, actor=actor), "")

    def test_cube_published_after_prompt_resolves(self):
        self.note(self.t0)
        seen = []
        def cube(uid, since):
            seen.append((uid, since))
            return True
        self.assertEqual(self.note(self.t0 + 5 * H, cube=cube), "")
        self.assertEqual(seen[0][0], "u@example.invalid")
        self.assertEqual(sh._row(self.conn, "k", "a1")[3], "cube_publish")
        self.assertEqual(self.note(self.t0 + 70 * H, cube=cube), "")
        self.assertIn("DUTY cube_harvest", self.note(self.t0 + 5 * H + 73 * H, cube=cube))

    def test_state_is_per_agent(self):
        self.note(self.t0, actor="a1")
        self.note(self.t0, actor="a2")
        self.note(self.t0 + H, duty="skills_none", actor="a1")
        self.assertIn("DUTY", self.note(self.t0 + 80 * H, actor="a2"))
        self.assertEqual(self.note(self.t0 + 60 * H, actor="a1"), "")

    def test_finish_turn_carries_duty_once(self):
        a = do_identify(INFO, self.conn, "agent-a", session_id="s1")
        who = resolve_call(self.conn, INFO["key_id"], INFO["chain_id"], INFO["key_name"], agent_token=a["agent_token"], session_id="s1")
        r1 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e1", "session_id": "s1", "duties": ["x"]})
        self.assertNotIn("cube_harvest", r1)            # identify already showed it
        self.assertNotIn("skills_harvest", r1)
        self.assertEqual(r1["duties"], ["x"])
        self.conn.execute("UPDATE agent_skills_harvest SET last_prompt_at=?", (sh._fmt(time.time() - 80 * H),))
        self.conn.commit()
        r2 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e2", "session_id": "s1", "duties": ["x"]})
        item = r2["cube_harvest"]
        self.assertIsInstance(item, dict)
        self.assertEqual(item["duty"], "cube_harvest")
        self.assertIn("DUTY cube_harvest", item["do"])
        self.assertEqual(item["cube_id"], sh.meta_cube_id())
        self.assertEqual(r2["duties"][0], "x")
        self.assertEqual(r2["duties"][1], r2["cube_harvest"])
        self.assertNotIn("skills_harvest", r2)
        r3 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e3", "session_id": "s1"})
        self.assertNotIn("cube_harvest", r3)
        r4 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e4", "session_id": "s1"}, duty="skills_none")
        self.assertNotIn("cube_harvest", r4)
        self.assertEqual(sh._row(self.conn, INFO["key_id"], "agent-a")[3], "skills_none")
        r5 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e5", "session_id": "s1"}, duty="cube_harvest")
        self.assertNotIn("cube_harvest", r5)
        self.assertEqual(sh._row(self.conn, INFO["key_id"], "agent-a")[3], "cube_harvest")

    def test_meta_cube_id_is_named_in_every_text(self):
        cid = sh.AUTHOR_CUBE_ID
        for t in (sh.step3_text(cid), sh.first_note(cid), sh.again_note(72, cid)):
            self.assertIn(cid, t)
            self.assertNotIn("cube_meta_publish_skills", t)

    def test_rules_consent_and_privacy_in_every_text(self):
        """Anonymized experience after the one-time notice; quotes from personal memory still need a yes."""
        cid = sh.AUTHOR_CUBE_ID
        for t in (sh.step3_text(cid), sh.first_note(cid), sh.again_note(72, cid), sh.rules_text()):
            low = t.lower()
            self.assertIn("personal data", low)
            self.assertIn("personal memory", low)
            self.assertIn("one-time notice", low)
            self.assertIn("do not publish", low)
            self.assertIn("anonymized", low)
            self.assertIn("explicit yes", low)
            self.assertIn("never edit another author", low)
            self.assertIn("published cube:", low)
            if t != sh.rules_text():
                self.assertIn("duplicate", low)
                self.assertIn(cid, t)
        self.assertNotIn("%", sh.rules_text())

    def test_first_cubes_are_proven_skills_carrier_skill(self):
        rule = sh.FIRST_CUBES_RULE
        self.assertIn("carrier=skill", rule)
        self.assertIn("never copy verbatim", rule.lower())
        cid = sh.AUTHOR_CUBE_ID
        for t in (sh.step3_text(cid), sh.first_note(cid), sh.again_note(72, cid), sh.rules_text()):
            self.assertIn(rule, t)
        self.assertIn(sh.AUTHOR_CUBE_ID, sh.step3_text("cube_deadbeef12"))
        from app import cube_harvest as ch
        src = open(ch.__file__, encoding="utf-8").read()
        self.assertIn(rule, src)

    def test_rest_cube_05_v20_has_first_skills_rule(self):
        import sqlite3
        db = "/data/skv/metadata_store/shared_master.db"
        if not os.path.isfile(db):
            self.skipTest("shared_master.db not here")
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            row = c.execute("select status, rules_markdown from cubes_new where cube_id='cube_const_05_v20'").fetchone()
        finally:
            c.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "community")
        self.assertIn(sh.FIRST_CUBES_RULE, row[1])
        self.assertIn("CUBE 05 — Agent Capabilities v20.0", row[1])

    def test_constitution_texts_carry_the_consent_rule(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        src_path = os.path.join(root, "mcp", "mcp_skv.py")
        src = open(src_path, encoding="utf-8").read() if os.path.exists(src_path) else ""
        if not src:
            self.skipTest("mcp source not available here")
        i = src.index("CUBE05_MCP = ")
        line = src[i:src.index("\n", i)]
        self.assertIn("one-time notice", line)
        self.assertIn("do not publish", line)
        self.assertIn("personal memory", line)
        self.assertIn("personal data", line)
        self.assertIn("cube_harvest", line)
        self.assertIn("cube_3de96286fc73", line)
        self.assertIn("carrier=skill", line)
        self.assertIn("never copy verbatim", line.lower())
        self.assertIn('CUBE05_ID = "cube_const_05_mcp_v20"', src)
        # one duty name in the constitution body: the periodic reminder is cube_harvest
        self.assertIn("one duty, cube_harvest", line.lower() or line)
        self.assertNotIn("cube_meta_publish_skills", line)


if __name__ == "__main__":
    unittest.main()
