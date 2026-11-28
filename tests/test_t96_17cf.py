"""T96 items 17c-17f. Rules only. No network."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import turn_diet17 as d


class Empty(unittest.TestCase):
    def test_acks_are_empty_and_commands_are_not(self):
        for msg in ("ок", "ok", "ага", "да", "спс", "спасибо", "понял", "ясно", "принято", "да ага"):
            self.assertTrue(d.is_strict_empty(msg), msg)
        self.assertTrue(d.is_emoji_only("👍"))
        self.assertTrue(d.is_strict_empty("🙂"))
        for msg in ("делай", "стоп", "стой", "катим", "отмена", "жди", "проверь",
                    "не надо", "не трогай", "T96", "8080", "a.py", "ок!", "да?"):
            self.assertFalse(d.is_strict_empty(msg), msg)
            self.assertTrue(d.is_always_meaningful(msg) or "?" in msg or "!" in msg, msg)

    def test_skip_needs_all_three_and_a_gloss_wins(self):
        plan = {"mode": "slice", "query": "", "revise": False}
        skipped = d.apply_17c(plan, "спасибо", None, "Готово.", 2)
        self.assertEqual(skipped["mode"], "auto_skip")
        self.assertEqual(skipped["skip_reason"], "empty_ack<15m")
        self.assertTrue(skipped["search_skipped"])
        asked = d.apply_17c(plan, "ок", None, "Выкатываем?", 2)
        self.assertEqual(asked["mode"], "anchor")
        self.assertIn("Выкатываем?", asked["query"])
        self.assertTrue(asked["query"].endswith("ок"))
        self.assertLessEqual(len(asked["query"].split("Выкатываем?")[0]), 200)
        stale = d.apply_17c(plan, "ок", None, "Готово.", 40)
        self.assertEqual(stale["mode"], "plain")
        unknown = d.apply_17c(plan, "ок", None, "Готово.", None)
        self.assertEqual(unknown["mode"], "slice")
        gloss = d.apply_17c(plan, "ок", "сборка T95", "Выкатываем?", 1)
        self.assertEqual(gloss["mode"], "slice")
        dash = d.apply_17c({"mode": "skip"}, "ок", "-", "Готово.", 1)
        self.assertEqual(dash["mode"], "skip")

    def test_meaningful_is_not_a_skip_even_on_the_slice(self):
        plan = {"mode": "slice", "query": ""}
        got = d.apply_17c(plan, "не надо", None, "Готово.", 1)
        self.assertEqual(got["mode"], "directive")
        self.assertTrue(got["search_skipped"])
        self.assertEqual(got["skip_reason"], "directive")
        self.assertEqual(got["query"], "")
        asked = d.apply_17c(plan, "делай", None, "Какой вариант?", 1)
        self.assertEqual(asked["mode"], "anchor")
        self.assertIn("делай", asked["query"])
        stop = d.apply_17c(plan, "стоп", None, "Выкатываем?", 1)
        self.assertEqual(stop["mode"], "directive")
        long = d.apply_17c(plan, "deploy the api to production now", None, "Готово.", 1)
        self.assertNotEqual(long["mode"], "directive")

    def test_answer_asks_on_the_tail_only(self):
        self.assertTrue(d.answer_asks("Собрал.\nВыкатываем?"))
        self.assertTrue(d.answer_asks("подтверди"))
        self.assertTrue(d.answer_asks("ok? [y/n]"))
        self.assertFalse(d.answer_asks("Готово. Печать ниже.\n🔐 SKV | #012"))
        long = ("x" * 400) + " вопрос в середине? " + ("y" * 80)
        self.assertFalse(d.answer_asks(long))


class OwnFresh(unittest.TestCase):
    def test_only_this_actor_and_this_session(self):
        events = []
        for i in range(25):
            events.append({"id": "own-%d" % i, "actor": "grok-bot", "session": "s", "seq": i})
        events.append({"id": "other-1", "actor": "grok-build", "session": "s", "seq": 100})
        events.append({"id": "other-sess", "actor": "grok-bot", "session": "old", "seq": 100})
        drop = d.own_fresh_ids(events, "grok-bot", "s", 20)
        self.assertEqual(len([x for x in drop if x.startswith("own-")]), 20)
        self.assertNotIn("own-0", drop)
        self.assertIn("own-24", drop)
        self.assertNotIn("other-1", drop)
        self.assertNotIn("other-sess", drop)
        facts = [
            {"ev": "own-24", "fact": "mine"},
            {"ev": "other-1", "fact": "theirs"},
            {"ev": "own-0", "fact": "old"},
        ]
        kept = d.drop_own_fresh(facts, drop)
        self.assertEqual([f["ev"] for f in kept], ["other-1", "own-0"])
        scored = [
            {"ev": "own-24", "fact": "mine", "score": 1.0},
            {"ev": "other-1", "fact": "theirs", "score": 1.0},
            {"ev": "own-0", "fact": "old", "score": 1.0},
            {"ev": "own-24", "fact": "see T96 in the pack", "score": 1.0},
        ]
        pen = d.penalize_own_fresh(scored[:3], drop, "what changed")
        self.assertAlmostEqual(pen[0]["score"], 0.35)
        self.assertEqual(pen[1]["score"], 1.0)
        self.assertEqual(pen[2]["score"], 1.0)
        lifted = d.penalize_own_fresh([scored[3]], drop, "open T96")
        self.assertEqual(lifted[0]["score"], 1.0)
        self.assertNotIn("fresh_penalty", lifted[0])

    def test_filter_is_off_for_the_four_exceptions(self):
        self.assertFalse(d.fresh_filter_enabled(context_compacted=True))
        self.assertFalse(d.fresh_filter_enabled(catchup=True))
        self.assertFalse(d.fresh_filter_enabled(new_session=True))
        self.assertFalse(d.fresh_filter_enabled(stateless=True))
        self.assertTrue(d.fresh_filter_enabled())

    def test_sqlite_load_is_strict(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE event_metadata (event_id TEXT, actor_agent_id TEXT, session_id TEXT)"
        )
        for i in range(5):
            conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("e%d" % i, "bot", "s"))
        conn.execute("INSERT INTO event_metadata VALUES (?,?,?)", ("build-1", "build", "s"))
        ids = d.load_own_fresh(conn, "bot", "s", 20)
        self.assertIn("e4", ids)
        self.assertNotIn("build-1", ids)


class Mini(unittest.TestCase):
    def test_mini_step_zero_lists_turns_board_l1_and_critical(self):
        turns = [{"actor": "grok-bot", "ev": "remember_1", "text": "saved the pack"}]
        got = d.mini_step_zero(turns, "doing T84", "fresh l1", ["seal failed"])
        self.assertIn("BOARD doing: doing T84", got["text"])
        self.assertIn("[ev:remember_1]", got["text"])
        self.assertIn("L1: fresh l1", got["text"])
        self.assertIn("CRITICAL: seal failed", got["text"])
        self.assertLessEqual(len(turns), 30)


class Catchup(unittest.TestCase):
    def test_gap_without_news_is_silent_and_news_is_typed(self):
        self.assertFalse(d.catchup_due(5, "", 10, 0))
        self.assertTrue(d.catchup_due(5, "", 10, 2))
        self.assertFalse(d.catchup_due(1, "", 10, 4))
        self.assertTrue(d.catchup_due(1, "3", 10, 1))
        self.assertTrue(d.seal_older("🔐 SKV | #004", "12"))
        self.assertFalse(d.seal_older("12", "12"))
        items = [
            {"kind": "BOARD", "actor": "grok-build", "text": "T84 todo->done", "ev": "board:t84", "ts": "2026-11-28 18:00:00"},
            {"kind": "AGENT", "actor": "grok-build", "text": "indexed the rows", "ev": "remember_9", "ts": "2026-11-28 17:00:00"},
            {"kind": "CRITICAL", "actor": "", "text": "do not restart", "ev": "critical_1", "ts": "2026-11-28 16:00:00"},
        ]
        text = d.format_delta(items, 5)
        self.assertTrue(text.startswith("[DELTA +5h] "))
        self.assertLess(text.find("BOARD:"), text.find("AGENT"))
        self.assertIn("[ev:remember_9]", text)
        self.assertLessEqual(len(text.encode()), 400)
        many = [{"kind": "AGENT", "actor": "grok-build", "text": "e%d %s" % (i, "z" * 40), "ev": "remember_%d" % i} for i in range(15)]
        over = d.format_delta(many, 30, since="2026-11-28 08:00:00")
        self.assertIn("+15 events, memory_search(since=2026-11-28)", over)
        self.assertNotIn("top-2", over)
        self.assertFalse(d.has_cyrillic(over))
        self.assertLessEqual(len(over.encode()), 1000)

    def test_loader_skips_this_actor_and_old_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE room_events (id INTEGER PRIMARY KEY, event_id TEXT, actor_agent_id TEXT, "
            "ev_kind TEXT, gist TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO room_events (event_id, actor_agent_id, ev_kind, gist, created_at) "
            "VALUES ('ev1','grok-build','turn','wrote the pack','2026-11-28 12:00:00')"
        )
        conn.execute(
            "INSERT INTO room_events (event_id, actor_agent_id, ev_kind, gist, created_at) "
            "VALUES ('ev2','grok-bot','turn','mine','2026-11-28 12:05:00')"
        )
        conn.execute("CREATE TABLE board_items (item_id TEXT, title TEXT, status TEXT, updated_at TEXT, removed INTEGER)")
        conn.execute("INSERT INTO board_items VALUES ('T84','pack','doing','2026-11-28 12:10:00',0)")
        items = d.load_delta_items(conn, "grok-bot", "2026-11-28 11:00:00")
        evs = {i["ev"] for i in items}
        self.assertIn("ev1", evs)
        self.assertNotIn("ev2", evs)
        self.assertTrue(any(i["kind"] == "BOARD" for i in items))
        who = {"actor_id": "grok-bot", "prev_seen_at": "2026-11-28 08:00:00"}
        text = d.catchup_text(conn, who, "", now=__import__("datetime").datetime(2026, 11, 28, 14, 0, 0))
        self.assertTrue(text.startswith("[DELTA "))
        quiet = d.catchup_text(conn, who, "", now=__import__("datetime").datetime(2026, 11, 28, 9, 0, 0))
        self.assertEqual(quiet, "")


class Quota(unittest.TestCase):
    def test_token_tiers_spare_and_cyrillic_room(self):
        self.assertAlmostEqual(d.estimate_tokens("a" * 400), 100.0, places=3)
        self.assertAlmostEqual(d.estimate_tokens("я" * 180), 100.0, delta=0.2)
        resp = {
            "constitution": {"rule": "rule"},
            "duties": ["short duty"],
            "board": [{"title": "pack", "status": "doing"}],
            "facts": [{"fact": "f" * 400, "score": 0.1} for _ in range(6)],
            "while_away": "delta",
        }
        sizes = d.apply_quotas(resp, message="where is the archive now")
        self.assertEqual(sizes["tier"], "base")
        self.assertLessEqual(sizes["total"], 600.05)
        self.assertGreater(sizes["facts"], 200)
        cyr = {"facts": [{"fact": "я" * 900, "score": 0.1}], "duties": [], "board": [], "while_away": ""}
        d.apply_quotas(cyr, message="where is the archive now")
        self.assertEqual(len(cyr["facts"]), 1)
        self.assertGreater(len(cyr["facts"][0]["fact"].encode()), 1500)
        strong = {"facts": [{"fact": "T96 " + "x" * 2000, "score": 0.8}], "duties": [], "board": [], "while_away": ""}
        s2 = d.apply_quotas(strong, message="where is the archive now")
        self.assertEqual(s2["tier"], "strong")
        self.assertLessEqual(s2["total"], 1200.05)
        topic = {"facts": [{"fact": "z" * 8000, "score": 0.2}], "duties": [], "board": [], "while_away": ""}
        t2 = d.apply_quotas(topic, message="new topic: the archive layout")
        self.assertEqual(t2["tier"], "new_topic")
        self.assertLessEqual(t2["total"], 6000.05)
        self.assertGreater(d.estimate_tokens(topic["facts"][0]["fact"]), 1500)
        self.assertFalse(d.has_cyrillic(d.GUARD_LINE))
        hint = d.attach_facts_hint({"facts": []}, "budget talk")
        self.assertIn("memory_search", hint["facts_note"])
        self.assertIn("memory_recall_later", hint["facts_note"])
        self.assertIn("deep_search_call", hint)
        self.assertFalse(d.has_cyrillic(hint["facts_note"]))
        self.assertTrue(d.weak_recall_due(True, True, None, False, False))
        self.assertFalse(d.weak_recall_due(True, True, 30, False, False))
        self.assertFalse(d.weak_recall_due(True, True, None, True, False))
        self.assertFalse(d.weak_recall_due(True, True, 900, False, True))

    def test_reask_counter_logs_a_tag(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            self.assertEqual(d.note_reask("я не про это, смотри", path=path), 1)
            self.assertEqual(d.note_reask("ты забыл печать", path=path), 2)
            self.assertEqual(d.note_reask("посмотри выше", path=path), 3)
            self.assertEqual(d.note_reask("обычный вопрос", path=path), 0)
            with open(path) as fh:
                self.assertEqual(fh.read().strip(), "3")
        finally:
            os.remove(path)


class Dates(unittest.TestCase):
    def test_bare_decimals_are_not_a_date_window(self):
        import turn_pack as tp
        from datetime import date
        today = date(2026, 11, 28)
        for msg in (
            "с 5 КБ до 1,5 КБ",
            "в 10 раз больше",
            "до 1.5 КБ",
            "3.5 раза больше",
            "5 KB to 1.5 KB",
        ):
            self.assertIsNone(tp.date_window(msg, today=today), msg)
        explicit = tp.date_window("решение 14.11.2026", today=today)
        self.assertEqual(explicit["label"], "date")
        self.assertEqual(explicit["since"], "2026-11-13")
        short = tp.date_window("L1 за вечер 19.10", today=today)
        self.assertEqual(short["since"], "2026-10-18")
        self.assertEqual(short["until"], "2026-10-20")


if __name__ == "__main__":
    unittest.main()
