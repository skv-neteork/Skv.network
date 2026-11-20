"""Pure tests for turn fact context. No network and no app package import."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "app"))
import turn_context as tc


class BuildSearch(unittest.TestCase):
    def test_short_followup_keeps_topic_and_does_not_invent_search_as(self):
        q, sa = tc.build_search("do everything", None, ["what did we decide about the cube store?"])
        self.assertIn("cube", q.lower())
        self.assertIn("store", q.lower())
        self.assertTrue(q.lower().startswith("do everything"))
        self.assertNotIn("?", q)
        self.assertEqual(sa, [])

    def test_agent_search_as_is_kept_and_capped(self):
        q, sa = tc.build_search(
            "do everything",
            "cube store is free | vault was added later | server moved | extra form",
            ["cube store plan"],
        )
        self.assertEqual(sa, ["cube store is free", "vault was added later", "server moved"])
        self.assertTrue(q.lower().startswith("do everything"))
        self.assertIn("cube", q.lower())

    def test_substantive_question_does_not_gain_search_as(self):
        msg = "what did we decide about the cube store?"
        q, sa = tc.build_search(msg, "", ["unrelated weekend plan for the picnic"])
        self.assertEqual(sa, [])
        self.assertTrue(q.lower().startswith("what did we decide about the cube store?"))
        self.assertIn("picnic", q.lower())

    def test_short_and_multi_flags(self):
        self.assertTrue(tc.is_short("do everything"))
        self.assertTrue(tc.is_short("сделай всё"))
        self.assertTrue(tc.is_short("делай"))
        self.assertFalse(tc.is_short("what did we decide about the cube store?"))
        self.assertFalse(tc.is_multi("what did we decide about the cube store?"))
        self.assertTrue(tc.is_multi("when did the server move and when was the vault added?"))
        self.assertTrue(tc.is_multi("how many times did we move, and in which years 2024 and 2025?"))


class Rank(unittest.TestCase):
    def test_durable_layers_outrank_one_echo(self):
        hits = [
            {"event_id": "remember_9", "score": 0.99, "summary": "Q: do everything\nA: ok", "time": "2026-11-20 01:00:00", "source": "search"},
            {"event_id": "remember_2", "score": 0.2, "summary": "[decision] cube store stays free", "time": "2026-11-14", "source": "decision", "layer": "decision"},
            {"event_id": "remember_3", "score": 0.2, "summary": "[critical] cube store rating", "time": "2026-11-14", "source": "critical", "layer": "critical"},
            {"event_id": "remember_8", "score": 0.95, "summary": "Q: another echo\nA: yes", "time": "2026-11-20 02:00:00", "source": "search"},
        ]
        out = tc.rank(hits, "cube store", {"remember_9", "remember_8"}, False, limit=5)
        self.assertEqual(out[0]["layer"], "decision")
        self.assertEqual(out[1]["layer"], "critical")
        echoes = [h for h in out if h["layer"] == "echo"]
        self.assertEqual(len(echoes), 1)
        self.assertLess(echoes[0]["score"], out[0]["score"])
        self.assertNotIn("2026-11-14", out[0]["summary"][:4])

    def test_three_durables_drop_echoes(self):
        hits = [
            {"event_id": "prof:1", "score": 0.4, "summary": "[decision] cube store stays free", "source": "decision", "layer": "decision", "time": "2026-11-14"},
            {"event_id": "remember_4", "score": 0.4, "summary": "[critical] cube store", "source": "critical", "layer": "critical", "time": "2026-11-14"},
            {"event_id": "l1:s", "score": 0.4, "summary": "[l1] cube store plan", "source": "l1", "layer": "l1", "time": "2026-11-14"},
            {"event_id": "remember_9", "score": 0.99, "summary": "Q: hi A: hi", "source": "search", "time": "2026-11-20"},
        ]
        out = tc.rank(hits, "cube store", {"remember_9"}, False)
        self.assertTrue(all(h["layer"] != "echo" for h in out))
        self.assertEqual(out[0]["score"], out[1]["score"])

    def test_multi_event_returns_distinct_dates(self):
        hits = [
            {"event_id": "remember_%d" % i, "score": 1 - i / 10, "summary": "event %d about the server move and the vault" % i,
             "time": "2026-11-%02d 09:0%d:00" % (i, i), "source": "search"}
            for i in (1, 1, 2, 3)
        ]
        msg = "when did the server move and when was the vault added?"
        out = tc.rank(hits, msg, set(), True, limit=5)
        days = []
        for h in out:
            self.assertRegex(h["summary"], r"^2026-11-\d\d ")
            days.append(h["summary"][:10])
        self.assertGreaterEqual(len(set(days)), 3)
        self.assertLessEqual(len(out), 5)

    def test_single_event_does_not_prefix_or_grow_past_five(self):
        hits = [
            {"event_id": "remember_%d" % i, "score": 0.5, "summary": "cube store note %d" % i, "time": "2026-11-%02d" % (i + 1), "source": "search"}
            for i in range(8)
        ]
        out = tc.rank(hits, "what did we decide about the cube store?", set(), False, limit=5)
        self.assertEqual(len(out), 5)
        self.assertFalse(any(h["summary"].startswith("2026-") for h in out))


class Sqlite(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, raw_dialogue TEXT)")
        self.conn.execute("CREATE TABLE profile_rows (id TEXT, kind TEXT, status TEXT, text TEXT, source_event_ids TEXT, updated_at TEXT)")
        self.conn.execute("CREATE TABLE critical_auto (kind TEXT, value TEXT, context TEXT, event_id TEXT, time_str TEXT)")
        self.conn.execute("CREATE TABLE summary_l1 (session_id TEXT, topic TEXT, summary_text TEXT, created_at TEXT, to_rowid INTEGER)")
        self.conn.execute("CREATE TABLE summary_l2_blocks (id INTEGER PRIMARY KEY, text TEXT, period_from TEXT, created_at TEXT, to_rowid INTEGER)")
        self.conn.execute("CREATE TABLE summary_l2 (map_json TEXT, last_updated TEXT)")
        self.conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("remember_1", "2026-11-01 10:00:00", "Q: old picnic plan\nA: later"))
        self.conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("remember_2", "2026-11-20 10:00:00", "Q: ship the cube store this week\nA: yes"))
        self.conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("remember_3", "2026-11-20 11:00:00", "Q: the vault was added next to the cube store\nA: yes"))
        self.conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("remember_4", "2026-11-20 12:00:00", "Q: echo two about nothing\nA: b"))
        self.conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("remember_5", "2026-11-20 13:00:00", "Q: [lightweight] ping\nA: pong"))
        self.conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("remember_6", "2026-11-20 14:00:00", "Q: do everything\nA: working"))
        self.conn.execute(
            "INSERT INTO profile_rows VALUES (?,?,?,?,?,?)",
            ("p1", "decision", "active", "The cube store stays free and rated", "remember_2", "2026-11-14"),
        )
        self.conn.execute(
            "INSERT INTO critical_auto VALUES (?,?,?,?,?)",
            ("fact", "cube store", "rating is required", "remember_2", "2026-11-14"),
        )
        self.conn.execute(
            "INSERT INTO summary_l1 VALUES (?,?,?,?,?)",
            ("s1", "cube", "cube store plan agreed", "2026-11-14", 2),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_recent_from_conn(self):
        texts, echoes = tc.recent_from_conn(self.conn, "do everything")
        self.assertIn("remember_6", echoes)
        self.assertIn("remember_4", echoes)
        self.assertNotIn("remember_2", echoes)
        self.assertTrue(any("cube store" in t for t in texts))
        self.assertTrue(all("do everything" != t for t in texts))
        self.assertTrue(all("[lightweight]" not in t for t in texts))

    def test_layers_and_neighbours(self):
        layers = tc.layer_from_conn(self.conn, "what did we decide about the cube store?")
        kinds = {h["layer"] for h in layers}
        self.assertIn("decision", kinds)
        self.assertIn("critical", kinds)
        self.assertIn("l1", kinds)
        self.assertTrue(any(h["event_id"] == "remember_2" for h in layers if h["layer"] == "decision"))
        near = tc.neighbours(self.conn, "remember_2", "cube store ship")
        ids = {h["event_id"] for h in near}
        self.assertIn("remember_3", ids)
        self.assertNotIn("remember_1", ids)
        self.assertNotIn("remember_2", ids)
        self.assertTrue(all(tc.on_topic("cube store ship", h["summary"]) for h in near))


if __name__ == "__main__":
    unittest.main()
