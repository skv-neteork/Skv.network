"""T73 spontaneous recall: next turn, no model wait, diet keeps the field."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "/root/skv-core/mcp")
import turn_diet as TD  # noqa: E402

from app import recall_later
from app import spontaneous_recall as sr


DECISION = "We decided the deploy worker restarts in place and is not rolled back"
NOISE = "The cafeteria menu changed on Tuesday"
TOPIC = "deploy worker restart"


def _events():
    return [
        {"event_id": "acct::remember_abc123", "text": DECISION},
        {"event_id": "acct::remember_low999", "text": NOISE},
        {"event_id": "acct::remember_off1", "text": "We decided the cafeteria stays open on Friday"},
    ]


class SpontaneousTests(unittest.TestCase):
    def test_tenth_turn_schedules_without_a_model(self):
        conn = sqlite3.connect(":memory:")
        called = []

        def boom(*_a, **_k):
            called.append(1)
            raise AssertionError("model http")

        with mock.patch("urllib.request.urlopen", boom):
            os.environ["SKV_SPONTANEOUS_MODEL"] = "1"
            try:
                for _ in range(9):
                    quiet = sr.on_turn(conn, topic=TOPIC)
                    self.assertEqual(quiet["recalled"], [])
                    self.assertFalse(quiet["scheduled"])
                    self.assertFalse(quiet["model_called"])
                tenth = sr.on_turn(conn, topic=TOPIC, events=_events())
            finally:
                os.environ.pop("SKV_SPONTANEOUS_MODEL", None)
        self.assertEqual(tenth["recalled"], [])
        self.assertTrue(tenth["scheduled"])
        self.assertFalse(tenth["model_called"])
        self.assertEqual(tenth["turns"], 10)
        self.assertEqual(called, [])
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertIn("spontaneous_job", names)
        self.assertNotIn("recall_later", names)

        nxt = sr.on_turn(conn, topic=TOPIC)
        blob = "\n".join(nxt["recalled"])
        self.assertIn("recalled:", blob)
        self.assertIn("abc123", blob)
        self.assertNotIn("cafeteria", blob)
        self.assertNotIn("low999", blob)
        self.assertLessEqual(len(nxt["recalled"]), 3)
        for line in nxt["recalled"]:
            self.assertLess(len(line), 220)

        again = sr.on_turn(conn, topic=TOPIC, events=_events())
        self.assertEqual(again["recalled"], [])

    def test_l1_schedules_early(self):
        conn = sqlite3.connect(":memory:")
        row = sr.on_turn(conn, topic="alpha notes", l1_new=True)
        self.assertEqual(row["turns"], 1)
        self.assertTrue(row["scheduled"])
        self.assertEqual(row["recalled"], [])

    def test_topic_change_schedules(self):
        conn = sqlite3.connect(":memory:")
        first = sr.on_turn(conn, topic="alpha")
        self.assertFalse(first["scheduled"])
        self.assertEqual(first["turns"], 1)
        second = sr.on_turn(conn, topic="billing export")
        self.assertTrue(second["scheduled"])
        self.assertEqual(second["turns"], 2)

    def test_secret_token_is_not_stored(self):
        conn = sqlite3.connect(":memory:")
        token = "zq9" + "smk" + "abcdef"
        sr.on_turn(
            conn,
            topic="my test password is %s, reply ok" % token,
            events=[{"event_id": "acct::remember_s1", "text": "my api key is %sx" % token}],
            l1_new=True,
        )
        blob = "\n".join(str(row) for row in conn.iterdump())
        self.assertNotIn(token, blob)

    def test_off_topic_decision_scores_zero(self):
        self.assertEqual(sr.score_text(TOPIC, "We decided the cafeteria stays open"), 0.0)
        self.assertGreaterEqual(sr.score_text(TOPIC, DECISION), sr.THRESHOLD)
        self.assertLess(sr.score_text(TOPIC, "deploy worker restart notes for today"), sr.THRESHOLD)

    def test_raw_secret_phrase_is_scrubbed_before_tokens(self):
        token = "smk_" + "SECRET_" + "eed1b2b4"
        cleaned = sr.topic_of(sr.scrub("smoke tag my token is %s" % token))
        self.assertNotIn(token, cleaned)
        self.assertNotIn("eed1b2b4", cleaned)
        api = "zq9" + "smk" + "abcdef"
        cleaned_api = sr.topic_of(sr.scrub("my api key is %sx, reply OK" % api))
        self.assertNotIn(api, cleaned_api)

    def test_recall_later_entrypoints_remain(self):
        self.assertTrue(callable(recall_later.submit))
        self.assertTrue(callable(recall_later.get))
        self.assertTrue(callable(recall_later.for_recall))


class DietRecallTests(unittest.TestCase):
    def test_compact_keeps_nonempty_recalled(self):
        path = tempfile.mktemp(suffix=".db")
        line = "recalled: We decided the deploy worker restarts [ev:abc123]"
        resp = {
            "verdict": "pass",
            "saved": True,
            "recalled": [line],
            "facts": [],
            "duties": [],
            "cubes": [],
            "cited_ok": [],
        }
        ctx = {
            "user": "diet-user",
            "session": "diet-sess",
            "verbose": False,
            "eligible": True,
            "draft": "ok",
            "checklist": ["a", "b"],
            "slq": False,
            "prof_extra": {},
            "facts": [],
            "cited": [],
            "tools": set(),
            "params": set(),
        }
        try:
            first, mode1 = TD.apply(path, dict(resp), ctx)
            self.assertEqual(mode1, "full")
            self.assertEqual(first.get("recalled"), [line])
            second, mode2 = TD.apply(path, dict(resp), ctx)
            self.assertEqual(mode2, "compact")
            self.assertEqual(second.get("recalled"), [line])
        finally:
            if os.path.exists(path):
                os.remove(path)


class PackHookTests(unittest.TestCase):
    def test_truncated_author_cube_keeps_hooks(self):
        from app import chain_skills as cs

        consts = [
            "cube_skill_const_second_look",
            "cube_skill_const_memory",
            "cube_skill_const_close",
            "cube_skill_const_cube_install",
            "cube_skill_const_pin_turn",
        ]
        root = "cube_688c0ebbb3be"
        live = "cube_8ca30802c689"
        ids = [{"cube_id": cid, "source": "auto", "topic": cid, "attached_at": "t"} for cid in consts + [root]]
        long_md = "word " * 800

        def resolve(_uid, cid):
            if cid == live:
                return {
                    "cube_id": live, "topic": "author", "essence": "e", "carrier": "skill",
                    "source": "auto", "shared": True, "skill_md": long_md,
                    "hooks": [{"when": "task_end", "do": "write the cube"}],
                    "has_skill": True, "upgraded_from": root,
                }
            return {
                "cube_id": cid, "topic": cid, "essence": "e", "carrier": "skill",
                "source": "auto", "shared": True, "skill_md": long_md,
                "hooks": [{"when": "session_start", "do": "note"}],
                "has_skill": True,
            }

        def newest(cid):
            return live if cid == root else cid

        orig = (cs.list_ids, cs.newest_version, cs.resolve_cube)
        cs.list_ids = lambda _uid, _chain: list(ids)
        cs.newest_version = newest
        cs.resolve_cube = resolve
        try:
            pack = cs.attached_pack("user", "session")
        finally:
            cs.list_ids, cs.newest_version, cs.resolve_cube = orig
        hit = [row for row in pack if row.get("cube_id") == live]
        self.assertEqual(len(hit), 1)
        self.assertTrue(hit[0].get("truncated"))
        self.assertEqual(hit[0].get("skill_md"), "")
        self.assertEqual(hit[0].get("upgraded_from"), root)
        self.assertTrue(any(h.get("when") == "task_end" for h in hit[0].get("hooks") or []))


if __name__ == "__main__":
    unittest.main()
