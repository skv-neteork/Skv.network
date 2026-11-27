"""Pure tests for turn fact context. No network and no app package import."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "app"))
import turn_context as tc


class BuildSearch(unittest.TestCase):
    def test_short_followup_keeps_topic_beside_the_query(self):
        recent = ["what did we decide about the cube store?"]
        q, sa = tc.build_search("do everything", None, recent)
        ctx = tc.context_queries("do everything", recent)
        self.assertEqual(q, "do everything")
        self.assertNotIn("cube", q.lower())
        self.assertEqual(sa, [])
        self.assertEqual(len(ctx), 1)
        self.assertIn("cube", ctx[0].lower())
        self.assertIn("store", ctx[0].lower())

    def test_agent_search_as_is_kept_and_capped(self):
        q, sa = tc.build_search(
            "do everything",
            "cube store is free | vault was added later | server moved | extra form",
            ["cube store plan"],
        )
        ctx = tc.context_queries("do everything", ["cube store plan"])
        self.assertEqual(sa, ["cube store is free", "vault was added later", "server moved"])
        self.assertEqual(q, "do everything")
        self.assertEqual(ctx, ["cube store plan"])

    def test_substantive_question_does_not_gain_search_as_or_context(self):
        msg = "what did we decide about the cube store?"
        recent = ["unrelated weekend plan for the picnic"]
        q, sa = tc.build_search(msg, "", recent)
        self.assertEqual(sa, [])
        self.assertEqual(q, msg)
        self.assertNotIn("picnic", q.lower())
        self.assertEqual(tc.context_queries(msg, recent), [])

    def test_six_word_followup_keeps_the_previous_file(self):
        q = "ты как посоветуешь с архивом?"
        recent = ["[background] T04/T05 done, archive recall check", "older note with no id"]
        built, sa = tc.build_search(q, None, recent)
        ctx = tc.context_queries(q, recent)
        self.assertEqual(built, q)
        self.assertEqual(sa, [])
        self.assertEqual(len(ctx), 2)
        self.assertIn("T04", ctx[0])

    def test_own_id_does_not_pull_the_previous_line(self):
        self.assertEqual(tc.context_queries("T87", ["see notes.txt and the older plan"]), [])

    def test_long_question_does_not_pull_context(self):
        msg = "Read /root/skv-tasks/build_task_b17.txt and do task B17. No push."
        self.assertEqual(tc.context_queries(msg, ["earlier build_task_b10.txt"]), [])

    def test_file_past_the_head_survives_the_clip(self):
        line = ("word " * 90) + "build_task_b18.txt at the end"
        ctx = tc.context_queries("ну что там?", [line])
        self.assertEqual(len(ctx), 1)
        self.assertIn("build_task_b18.txt", ctx[0])
        self.assertLessEqual(len(ctx[0]), 400)

    def test_named_file_in_context_leads_and_a_vague_line_does_not(self):
        import q2s
        primary = [("e_raw", 0.03279)] + [("e%d" % i, 0.030 - i * 0.001) for i in range(1, 8)]
        ctx = [("e_file", 1.0), ("e_file2", 0.5)]
        fused = q2s._attach_context(primary, ctx, 0.25, strong=True)
        ids = [e for e, _s in fused]
        self.assertEqual(ids[0], "e_file")
        self.assertLess(ids.index("e_file2"), 3)
        self.assertIn("e_raw", ids[:5])
        vague = q2s._attach_context(primary, [("e_ctx", 1.0)], 0.25, strong=False)
        self.assertEqual(vague[0][0], "e_raw")
        self.assertLess(dict(vague)["e_ctx"], dict(vague)["e_raw"])

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
        ids = [h["event_id"] for h in out]
        self.assertEqual(out[0]["layer"], "decision")
        self.assertIn("remember_9", ids)
        self.assertNotIn("remember_8", ids)
        echo = next(h for h in out if h["event_id"] == "remember_9")
        self.assertEqual(echo["layer"], "event")
        self.assertLess(out.index(echo), len(out))
        self.assertNotIn("2026-11-14", out[0]["summary"][:4])

    def test_three_durables_demote_the_best_echo(self):
        hits = [
            {"event_id": "prof:1", "score": 0.4, "summary": "[decision] cube store stays free", "source": "decision", "layer": "decision", "time": "2026-11-14"},
            {"event_id": "remember_4", "score": 0.4, "summary": "[critical] cube store", "source": "critical", "layer": "critical", "time": "2026-11-14"},
            {"event_id": "l1:s", "score": 0.4, "summary": "[l1] cube store plan", "source": "l1", "layer": "l1", "time": "2026-11-14"},
            {"event_id": "remember_9", "score": 0.99, "summary": "Q: hi A: hi", "source": "search", "time": "2026-11-20"},
        ]
        out = tc.rank(hits, "cube store", {"remember_9"}, False)
        self.assertTrue(all(h["layer"] != "echo" for h in out))
        self.assertIn("remember_9", [h["event_id"] for h in out])
        self.assertEqual(out[0]["layer"], "decision")
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


class Pack2400(unittest.TestCase):
    def test_flag_defaults_on_and_off_is_explicit(self):
        self.assertTrue(tc.pack_2400_enabled({}))
        self.assertTrue(tc.pack_2400_enabled({"q2s": True}))
        self.assertFalse(tc.pack_2400_enabled({"turn_pack_2400": False}))
        self.assertTrue(tc.pack_2400_enabled({"turn_pack_2400": True}))
        self.assertEqual(tc.turn_rank_limit(True, {}), 12)
        self.assertEqual(tc.turn_rank_limit(False, {}), 5)
        self.assertEqual(tc.turn_rank_limit(True, {"turn_pack_2400": False}), 5)

    def test_default_pack_keeps_the_lower_score_and_clips_at_400(self):
        hits = [
            {"event_id": "u::remember_1", "summary": "A" * 500, "score": 1, "time": "2026-11-01"},
            {"event_id": "u::remember_2", "summary": "gold T87 here", "score": 0.5, "time": "2026-11-02"},
            {"event_id": "remember_own", "summary": "skip me", "score": 0.9, "time": "2026-11-03"},
        ]
        facts = tc.compact_facts(hits, "remember_own", cfg={})
        text = "\n".join(f["fact"] for f in facts)
        self.assertEqual([f["ev"] for f in facts], ["remember_1", "remember_2"])
        self.assertIn("T87", text)
        self.assertIn("[ev:remember_2]", text)
        self.assertLessEqual(len("A" * 400), 400)
        self.assertIn("A" * 400, facts[0]["fact"])
        self.assertNotIn("A" * 401, facts[0]["fact"])
        self.assertIn("[cut]", facts[0]["fact"])
        self.assertTrue(facts[0].get("pack2400"))
        bodies = []
        for f in facts:
            body = f["fact"].split(" [ev:")[0]
            body = body.replace(" [cut]", "")
            bodies.append(body)
        self.assertLessEqual(len("\n".join(bodies)), 2400)

    def test_flag_off_restores_three_by_two_hundred(self):
        hits = [
            {"event_id": "u::remember_1", "summary": "A" * 500, "score": 1},
            {"event_id": "u::remember_2", "summary": "gold T87 here", "score": 0.5},
            {"event_id": "u::remember_3", "summary": "B" * 50, "score": 0.9},
            {"event_id": "u::remember_4", "summary": "C" * 50, "score": 0.8},
        ]
        facts = tc.compact_facts(hits, "", cfg={"turn_pack_2400": False})
        self.assertEqual(len(facts), 3)
        self.assertNotIn("T87", "\n".join(f["fact"] for f in facts))
        self.assertLessEqual(len(facts[0]["fact"].split(" [ev:")[0].replace(" [cut]", "")), 200)
        self.assertNotIn("pack2400", facts[0])


class PackSurvivesDiet(unittest.TestCase):
    def test_topic_diet_keeps_a_packed_fact_and_drops_a_plain_one(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from app.turn_pack import select_facts
        packed = [{"ev": "remember_1", "fact": "unrelated archive note " * 20, "time": "2026-11-01", "pack2400": True}]
        plain = [{"ev": "remember_1", "fact": "unrelated archive note " * 20, "time": "2026-11-01"}]
        kept = select_facts(packed, message="как сделать кубы?", recent_ids=[], seen_fact_ids=[])
        dropped = select_facts(plain, message="как сделать кубы?", recent_ids=[], seen_fact_ids=[])
        self.assertEqual(len(kept), 1)
        self.assertNotIn("pack2400", kept[0])
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
