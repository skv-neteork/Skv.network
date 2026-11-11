"""Skills/hooks harvest: identify step 3, per-agent state, periodic skills_harvest duty, resolution."""
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
        self.t0 = 1_800_000_000.0

    def tearDown(self):
        os.environ.pop("SKV_SKILLS_HARVEST_HOURS", None)
        self.conn.close()

    def note(self, now, duty="", cube=None, actor="a1"):
        return sh.turn_note(self.conn, "k", actor, user_id="u@example.invalid", duty=duty, now=now, cube_check=cube)

    def test_identify_adds_step3_once(self):
        a = do_identify(INFO, self.conn, "agent-a", session_id="s1")
        self.assertEqual(a["next"], STEP_ZERO_NEXT)
        self.assertIn("cube_meta_publish_skills", a["skills_step"])
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

    def test_agent_without_state_is_asked_once(self):
        first = self.note(self.t0)
        self.assertIn("first time", first)
        self.assertIn("cube_meta_publish_skills", first)
        self.assertEqual(self.note(self.t0 + 10 * H), "")

    def test_reminder_every_interval_when_unresolved(self):
        self.note(self.t0)
        self.assertEqual(self.note(self.t0 + 71 * H), "")
        again = self.note(self.t0 + 73 * H)
        self.assertIn("every ~72h", again)
        self.assertIn("skills_none", again)
        self.assertEqual(self.note(self.t0 + 100 * H), "")          # next one 72h after the reminder
        self.assertIn("DUTY skills_harvest", self.note(self.t0 + 146 * H))

    def test_explicit_skip_resolves_and_restarts_period(self):
        self.note(self.t0)
        self.assertEqual(self.note(self.t0 + 60 * H, duty="skills_none"), "")
        row = sh._row(self.conn, "k", "a1")
        self.assertEqual(row[3], "skills_none")
        self.assertEqual(self.note(self.t0 + 100 * H), "")          # 40h after the skip: quiet
        self.assertIn("DUTY skills_harvest", self.note(self.t0 + 133 * H))   # 73h after the skip

    def test_skip_before_any_state_and_alias(self):
        self.assertEqual(self.note(self.t0, duty="skills_skip"), "")
        self.assertEqual(sh._row(self.conn, "k", "a1")[3], "skills_skip")
        self.assertEqual(self.note(self.t0 + H), "")

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
        self.assertIn("DUTY skills_harvest", self.note(self.t0 + 5 * H + 73 * H, cube=cube))

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
        self.assertNotIn("skills_harvest", r1)            # identify already showed it
        self.assertEqual(r1["duties"], ["x"])
        self.conn.execute("UPDATE agent_skills_harvest SET last_prompt_at=?", (sh._fmt(time.time() - 80 * H),))
        self.conn.commit()
        r2 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e2", "session_id": "s1", "duties": ["x"]})
        self.assertIn("DUTY skills_harvest", r2["skills_harvest"])
        self.assertEqual(r2["duties"][0], "x")
        self.assertEqual(r2["duties"][1], r2["skills_harvest"])
        r3 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e3", "session_id": "s1"})
        self.assertNotIn("skills_harvest", r3)
        r4 = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "e4", "session_id": "s1"}, duty="skills_none")
        self.assertNotIn("skills_harvest", r4)
        self.assertEqual(sh._row(self.conn, INFO["key_id"], "agent-a")[3], "skills_none")

    def test_meta_cube_id_is_named_in_every_text(self):
        for t in (sh.STEP3, sh.FIRST_NOTE, sh.AGAIN_NOTE % (72, sh.META_CUBE_ID)):
            self.assertIn(sh.META_CUBE_ID, t)


if __name__ == "__main__":
    unittest.main()
