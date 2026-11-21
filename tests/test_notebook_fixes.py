"""Notebook reliability fixes. Temporary databases only. Nothing here opens the live shared pool."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import cube_dedup, cube_guard, cubes_v2, duty_rules, search_text  # noqa: E402
from app.room.clock import as_dt  # noqa: E402
from app.room.digest import build_while_away  # noqa: E402
from app.room.events import record_event  # noqa: E402
from app.room.identity import identify  # noqa: E402
from app.room.schema import ensure  # noqa: E402
from app.skill_pages import page_skill  # noqa: E402

T0 = as_dt("2026-11-09 08:00:00")


class RankingTests(unittest.TestCase):
    def test_blend_prefers_topic_and_recency(self):
        old_off = search_text.blend_score(0.9, 1000, 0.0)
        fresh_on = search_text.blend_score(0.4, 1, 1.0)
        old_on = search_text.blend_score(0.5, 1000, 1.0)
        fresh_off = search_text.blend_score(0.95, 1, 0.0)
        self.assertGreater(fresh_on, old_off)
        self.assertGreater(old_on, fresh_off)
        self.assertEqual(search_text.topic_cover("", "anything"), 1.0)

    def test_stored_rows_rank_fresh_on_topic_first(self):
        from app import recall_polish
        path = os.path.join(tempfile.mkdtemp(), "rank.db")
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, raw_dialogue TEXT, essence TEXT)")
        now = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        c.execute("INSERT INTO event_metadata VALUES (?,?,?,?)", ("old", "2020-01-01 00:00", "the bakery sold rye bread on monday", ""))
        c.execute("INSERT INTO event_metadata VALUES (?,?,?,?)", ("fresh", now, "queue worker retry the failed jobs", ""))
        c.commit()
        c.close()
        orig = recall_polish._open

        def _open(_uid):
            return sqlite3.connect(path)

        recall_polish._open = _open
        try:
            ranked = search_text._blend_fused("rank-user", "queue worker retry", [("old", 0.95), ("fresh", 0.4)], 5)
        finally:
            recall_polish._open = orig
        self.assertEqual(ranked[0][0], "fresh")
        self.assertGreater(ranked[0][1], ranked[1][1])


class SkillPageTests(unittest.TestCase):
    def test_pages_join_and_each_page_fits(self):
        text = ('"' * 17000) + "END"
        first = page_skill(text, 1)
        self.assertGreater(first["skill_pages"], 1)
        self.assertFalse(first["skill_complete"])
        self.assertNotIn("trimmed", first["skill_md"])
        joined = ""
        for i in range(1, first["skill_pages"] + 1):
            page = page_skill(text, i)
            body = {"cube_id": "cube_x", "essence": "e" * 132, "rules": "r" * 679, "skill_md": page["skill_md"],
                    "skill_page": page["skill_page"], "skill_pages": page["skill_pages"], "hint": page.get("hint") or ""}
            raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            self.assertLessEqual(len(raw), 9000)
            self.assertNotIn("…(trimmed)", page["skill_md"])
            joined += page["skill_md"]
        self.assertEqual(joined, text)
        short = page_skill("short skill body", 1)
        self.assertTrue(short["skill_complete"])
        self.assertEqual(short["skill_md"], "short skill body")
        self.assertEqual(short["skill_pages"], 1)


class LoopbackTests(unittest.TestCase):
    def test_loopback_stays_public_ip_goes(self):
        text = "bind 127.0.0.1 localhost ::1 and also 10.1.2.3 plus 999.1.1.1 and 127.4.5.6"
        out, found = cube_guard.mask_pii(text)
        self.assertIn("127.0.0.1", out)
        self.assertIn("localhost", out)
        self.assertIn("::1", out)
        self.assertIn("127.4.5.6", out)
        self.assertIn("999.1.1.1", out)
        self.assertNotIn("10.1.2.3", out)
        self.assertIn("[ip]", out)
        self.assertIn("ip", found)
        only, found_only = cube_guard.mask_pii("bind 127.0.0.1")
        self.assertEqual(only, "bind 127.0.0.1")
        self.assertNotIn("ip", found_only)
        report = cube_guard.field_report(rules="see 127.0.0.1 and localhost")
        self.assertFalse(any(x.get("reason") == "ip" for x in report))
        report_pub = cube_guard.field_report(rules="peer 10.1.2.3")
        self.assertTrue(any(x.get("reason") == "ip" for x in report_pub))
        scrub = cube_dedup.scrub_skill({"t": "host 127.0.0.1 localhost ::1 peer 10.9.8.7"})
        self.assertTrue(scrub["ok"])
        self.assertIn("127.0.0.1", scrub["fields"]["t"])
        self.assertIn("localhost", scrub["fields"]["t"])
        self.assertIn("::1", scrub["fields"]["t"])
        self.assertNotIn("10.9.8.7", scrub["fields"]["t"])
        self.assertIn("[ip]", scrub["fields"]["t"])


class ActorAndAwayTests(unittest.TestCase):
    def test_actor_column_on_a_new_cube(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE cubes_new (cube_id TEXT PRIMARY KEY, essence TEXT, subject_action_object TEXT, rules_markdown TEXT, evidence TEXT, status TEXT, created_by TEXT)")
        cubes_v2.ensure(c)
        c.execute("INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by) VALUES (?,?,?,?,?,?,?)",
                  ("cube_new", "a result", "topic", "rules", "evidence", "community", "owner@example.invalid"))
        cubes_v2.set_actor(c, "cube_new", "grok-build")
        row = c.execute("SELECT created_by, actor FROM cubes_new WHERE cube_id=?", ("cube_new",)).fetchone()
        self.assertEqual(row, ("owner@example.invalid", "grok-build"))
        cubes_v2.set_actor(c, "cube_new", "")
        self.assertEqual(c.execute("SELECT actor FROM cubes_new").fetchone()[0], "grok-build")

    def test_other_agent_sees_cube_write_as_grok_build(self):
        c = sqlite3.connect(":memory:")
        ensure(c)
        a = identify(c, "k", "ch", "b20-keepalive", role="build", session_id="win-a", now=T0)
        b = identify(c, "k", "ch", "grok-bot", session_id="win-b", now=T0 + timedelta(minutes=1))
        self.assertEqual(a["agent_id"], "grok-build")
        self.assertEqual(b["agent_id"], "grok-bot")
        record_event(c, "ch", "k", "grok-build", "win-a", kind="cube_write", text="wrote a cube",
                     event_id="cube-cube_abc", gist="grok-build wrote a cube", now=T0 + timedelta(minutes=2))
        away = build_while_away(c, "grok-bot", "k", "ch", "assistant", now=T0 + timedelta(minutes=3))
        self.assertIn("grok-build", away.get("text") or "")
        self.assertNotIn("b20-keepalive", away.get("text") or "")
        own = build_while_away(c, "grok-build", "k", "ch", "assistant", now=T0 + timedelta(minutes=3))
        self.assertFalse(own.get("text"))


class DutyAfterEndTests(unittest.TestCase):
    def test_l1_end_and_l2_open_the_cube_duty_without_marking_it_done(self):
        done, _dis, ev, app = duty_rules.signals({"l1_end": True, "task_done": False, "cube_created": False}, {})
        self.assertIn("cube", ev)
        self.assertTrue(app["cube"])
        self.assertNotIn("cube", done)
        done2, _d2, ev2, app2 = duty_rules.signals({"l2_map": "one headline", "cube_created": False}, {})
        self.assertIn("l2", done2)
        self.assertIn("cube", ev2)
        self.assertTrue(app2["cube"])
        self.assertNotIn("cube", done2)
        self.assertLessEqual(len(duty_rules.rule_text("cube")), 300)
        self.assertLessEqual(len(duty_rules.mandatory_text("cube", 12)), 300)
        self.assertIn("L1", duty_rules.rule_text("cube"))


if __name__ == "__main__":
    unittest.main()
