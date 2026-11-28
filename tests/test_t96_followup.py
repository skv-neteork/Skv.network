"""T96 items 16 and 20. Gloss plan, active slice, note text. No network."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import turn_context as tc
from app import gloss_note, search_text, t89_rules, turn_pack


class Plan(unittest.TestCase):
    def test_status_is_a_slice_and_a_longer_status_is_not(self):
        self.assertTrue(tc.is_status("как идет ?)"))
        self.assertTrue(tc.is_status("what is the status now?"))
        self.assertFalse(tc.is_status("как идет сборка"))
        dash = tc.followup_plan("what is the status now?", "-", [])
        self.assertEqual(dash["mode"], "slice")
        self.assertEqual(dash["stat"], "dash_ok")
        self.assertFalse(dash["revise"])
        named = tc.followup_plan("T95", None, ["older line"])
        self.assertEqual(named["mode"], "plain")
        self.assertEqual(named["query"], "T95")
        self.assertFalse(named["revise"])

    def test_empty_ack_is_a_slice_without_revise(self):
        for msg in ("да", "next", "thanks", "дальше"):
            plan = tc.followup_plan(msg, None, ["previous real question about the archive"])
            self.assertEqual(plan["mode"], "slice", msg)
            self.assertFalse(plan["revise"], msg)
            self.assertFalse(plan["duty"], msg)

    def test_deictic_without_gloss_revises_and_a_good_gloss_is_the_only_query(self):
        missed = tc.followup_plan("а он сделал?", "", ["Build and the missed T95 rows"])
        self.assertEqual(missed["mode"], "slice")
        self.assertTrue(missed["revise"])
        self.assertTrue(missed["duty"])
        gloss = "Build сделал 40 пропущенных заданий T95"
        got = tc.followup_plan("а дальше?", gloss, ["older"])
        self.assertEqual(got["mode"], "deictic")
        self.assertEqual(got["query"], gloss)
        self.assertEqual(got["search_as"], [])
        self.assertEqual(got["context"], [])
        self.assertEqual(got["user_weight"], 0.0)
        bad = tc.followup_plan("а он сделал?", "-", [])
        self.assertEqual(bad["mode"], "skip")
        self.assertEqual(bad["stat"], "dash_rejected")
        self.assertTrue(bad["revise"])

    def test_long_dash_skips_without_revise_and_a_long_gloss_stays_beside_the_query(self):
        msg = "what did we decide about the cube store and the archive layout?"
        dash = tc.followup_plan(msg, "-", [])
        self.assertEqual(dash["mode"], "skip")
        self.assertFalse(dash["revise"])
        kept = tc.followup_plan(msg, "cube store decision", [])
        self.assertEqual(kept["mode"], "plain")
        self.assertEqual(kept["query"], msg)
        self.assertEqual(kept["search_as"], ["cube store decision"])
        self.assertFalse(kept["revise"])

    def test_vague_short_line_uses_the_previous_line_and_does_not_glue_it(self):
        recent = ["archive recall check for T04"]
        plan = tc.followup_plan("где файл?", None, recent)
        self.assertEqual(plan["mode"], "series")
        self.assertEqual(plan["query"], recent[0])
        self.assertNotIn("ну и", plan["query"])
        self.assertTrue(plan["duty"])
        specific = tc.followup_plan("ты как посоветуешь с архивом?", None, recent)
        self.assertEqual(specific["query"], "ты как посоветуешь с архивом?")
        self.assertNotEqual(specific["query"], recent[0])

    def test_command_without_gloss_stays_the_query(self):
        q, sa = tc.build_search("do everything", None, ["cube store plan"])
        self.assertEqual(q, "do everything")
        self.assertEqual(sa, [])
        plan = tc.followup_plan("делай", None, [])
        self.assertEqual(plan["mode"], "plain")
        self.assertFalse(plan["revise"])


class Slice(unittest.TestCase):
    def test_doing_item_and_the_latest_answer_come_back(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE board_items (item_id TEXT, title TEXT, body TEXT, status TEXT, updated_at TEXT, removed INTEGER)")
        conn.execute("INSERT INTO board_items VALUES ('t1','Pack the bench','rows left', 'doing','2026-11-28 12:00',0)")
        conn.execute("INSERT INTO board_items VALUES ('t2','Old','done work','done','2026-11-01',0)")
        conn.execute("CREATE TABLE board_history (id INTEGER PRIMARY KEY, item_id TEXT, action TEXT, text TEXT, ts TEXT)")
        conn.execute("INSERT INTO board_history (item_id, action, text, ts) VALUES ('t1','update','started the pack','2026-11-28 12:05')")
        conn.execute("CREATE TABLE summary_l1 (topic TEXT, summary_text TEXT, created_at TEXT)")
        conn.execute("INSERT INTO summary_l1 VALUES ('pack','L1 of the pack','2026-11-28')")
        conn.execute("CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, raw_dialogue TEXT)")
        conn.execute("INSERT INTO event_metadata VALUES ('u::remember_9','2026-11-28 11:00','Q: go\\nA: the pack is at forty')")
        hits = tc.active_slice(conn, "bench pack")
        self.assertTrue(hits)
        self.assertTrue(all(h.get("active_slice") for h in hits))
        self.assertEqual(hits[0]["event_id"], "board:t1")
        ids = [h["event_id"] for h in hits]
        self.assertIn("u::remember_9", ids)
        self.assertIn("l1:1", ids)
        self.assertEqual(tc.active_slice(sqlite3.connect(":memory:"), ""), [])

    def test_deictic_miss_without_a_doing_row_searches_the_previous_line(self):
        plan = tc.followup_plan("а он сделал?", None, ["Build saved the forty T95 rows"])
        self.assertEqual(plan["mode"], "slice")
        self.assertTrue(plan["revise"])
        events = [{"event_id": "u::remember_1", "active_slice": True}]
        self.assertFalse(tc.slice_keeps(plan, events))
        self.assertTrue(tc.slice_keeps(plan, [{"event_id": "board:t1"}]))
        status = tc.followup_plan("what is the status now?", "-", [])
        self.assertTrue(tc.slice_keeps(status, events))
        ack = tc.followup_plan("thanks", None, ["earlier line about the pack"])
        self.assertEqual(ack["mode"], "slice")
        self.assertFalse(ack["revise"])
        self.assertTrue(tc.slice_keeps(ack, events))

    def test_topic_filter_keeps_the_slice_and_drops_the_flag(self):
        facts = [{"ev": "board:t1", "fact": "doing: pack the bench", "active_slice": True, "time": "2026-11-28"}]
        kept = turn_pack.select_facts([dict(f) for f in facts], message="как идет ?)")
        self.assertEqual([f["ev"] for f in kept], ["board:t1"])
        self.assertNotIn("active_slice", kept[0])
        bare = turn_pack.select_facts(
            [{"ev": "board:t1", "fact": "doing: pack the bench", "time": "2026-11-28"}],
            message="как идет ?)",
        )
        self.assertEqual(bare, [])

    def test_slice_rows_use_the_longer_clip_inside_the_normal_budget(self):
        hits = [{"event_id": "u::remember_1", "summary": "A " + ("x" * 500), "active_slice": True, "score": 1}]
        facts = tc.compact_facts(hits, "", message="как идет?")
        self.assertTrue(facts[0].get("active_slice"))
        self.assertNotIn("pack2400", facts[0])
        piece = facts[0]["fact"].split(" [ev:")[0]
        self.assertEqual(len(piece.replace(" [cut]", "")), 400)


class Recency(unittest.TestCase):
    def test_shorter_half_life_is_stricter_and_age_zero_matches(self):
        self.assertLess(search_text.blend_score(1, 48, 1, half_life=36), search_text.blend_score(1, 48, 1, half_life=168))
        self.assertEqual(search_text.blend_score(1, 0, 1, 36), search_text.blend_score(1, 0, 1, 168))
        self.assertEqual(search_text.blend_score(1, 48, 1), search_text.blend_score(1, 48, 1, half_life=168))
        now = __import__("datetime").datetime(2026, 11, 28, 12, 0, tzinfo=__import__("datetime").timezone.utc)
        hits = [
            {"event_id": "old", "score": 1, "summary": "pack status", "time": "2026-11-20 12:00"},
            {"event_id": "new", "score": 1, "summary": "pack status", "time": "2026-11-28 10:00"},
        ]
        ranked = tc.rerank_recency(hits, "pack status", 36, now=now)
        self.assertEqual(ranked[0]["event_id"], "new")


class Note(unittest.TestCase):
    def test_headline_is_kept_and_raw_is_trimmed(self):
        old = "» kept retelling\nolder essence"
        self.assertEqual(gloss_note.essence_prepend(old, "new note here"), old)
        updated = gloss_note.essence_outcome(old, "checked the board result")
        self.assertTrue(updated.startswith("» kept retelling\n→ checked the board result"))
        self.assertIn("older essence", updated)
        self.assertEqual(gloss_note.vector_text("no note", "RAW TEXT " * 50), ("RAW TEXT " * 50)[:1000])
        note = "» " + " ".join("w%d" % i for i in range(20))
        text = gloss_note.vector_text(note, "RAW " * 30, limit=5, count=lambda s: len(s.split()) or 1)
        self.assertTrue(text.startswith("["))
        self.assertNotIn("RAW", text)
        fitted = gloss_note.vector_text("» short gloss\n→ short outcome", "RAW " * 40, limit=8, count=lambda s: len(s.split()) or 1)
        self.assertTrue(fitted.startswith("[short gloss -> short outcome]"))
        self.assertLessEqual(len(fitted.split()), 8)

    def test_stamp_does_not_embed_and_fts_uses_the_note(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        stats = path + ".stats"
        try:
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, essence TEXT, raw_dialogue TEXT)")
            conn.execute("INSERT INTO event_metadata VALUES ('u::remember_1','topic','Q: hi\\nA: there')")
            conn.execute("CREATE VIRTUAL TABLE events_fts_stem USING fts5(event_id UNINDEXED, body)")
            conn.commit()
            conn.close()
            got = gloss_note.stamp_outcome(path, "u::remember_1", "saved the outcome line", reembed=False)
            self.assertTrue(got.startswith("→ saved the outcome line") or "→ saved the outcome line" in got)
            conn = sqlite3.connect(path)
            essence, raw = conn.execute("SELECT essence, raw_dialogue FROM event_metadata").fetchone()
            self.assertIn("Q: hi", raw)
            self.assertIn("→ saved the outcome line", essence)
            self.assertTrue(gloss_note.refresh_fts(conn, "u::remember_1"))
            body = conn.execute("SELECT body FROM events_fts_stem").fetchone()[0]
            self.assertIn("saved", body.lower())
            conn.close()
            self.assertEqual(gloss_note.bump("unit-agent", "missed", path=stats), 1)
            self.assertEqual(gloss_note.count_of("unit-agent", "missed", path=stats), 1)
            self.assertNotIn("unit-agent", tc.agent_key("secret-token-value"))
        finally:
            os.remove(path)
            if os.path.exists(stats):
                os.remove(stats)

    def test_skeleton_is_optional(self):
        plain = t89_rules.summary_build(1, "", "", "plain material only\n")
        self.assertNotIn("skeleton", plain)
        self.assertNotEqual(plain["steps"][0], "use these headlines as the L1 skeleton")
        noted = t89_rules.summary_build(1, "", "", "» user asked current status of T92\nplain\n")
        self.assertEqual(noted["steps"][0], "use these headlines as the L1 skeleton")
        self.assertTrue(noted["skeleton"])
        self.assertNotIn("» user asked current status of T92", noted.get("key_ideas") or [])


if __name__ == "__main__":
    unittest.main()
