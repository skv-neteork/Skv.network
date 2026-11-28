"""GB-29 batch A: soft topic filter, clip window, seen TTL, topic trigger, diet metrics, size not a date."""
import os
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from app import turn_pack as TP
from app import turn_context as TC
from app import turn_diet17 as D17


class SizeIsNotDate(unittest.TestCase):
    def test_gb_ram(self):
        today = date(2026, 11, 28)
        self.assertIsNone(TP.date_window("Свободно ~1.12 ГБ RAM, хватит?", today=today))
        self.assertIsNone(TP.date_window("1.12 GB free", today=today))
        self.assertIsNone(TP.date_window("занято 1.12 МБ", today=today))
        self.assertIsNone(TP.date_window("рост 1.12 %", today=today))
        self.assertIsNone(TP.date_window("версия v1.12 вышла", today=today))
        self.assertIsNone(TP.date_window("порог 0.35 и 1.12.3", today=today))

    def test_real_dates_still_open(self):
        today = date(2026, 11, 28)
        w = TP.date_window("что было 14.11?", today=today)
        self.assertEqual(w["since"], "2026-11-13")
        w = TP.date_window("встреча 01.12 в 10:00", today=today)
        self.assertEqual(w["since"], "2026-11-30")


class SoftFilter(unittest.TestCase):
    def _row(self, ev, text, cos=None, rare=False, score=0.02):
        r = {"ev": ev, "fact": text, "score": score, "pack_soft": True}
        if cos is not None:
            r["cos"] = cos
        if rare:
            r["rare"] = True
        return r

    def test_cos_or_rare_keeps_without_words(self):
        rows = [
            self._row("e1", "прокси через socks5 на домашнем сервере", cos=0.62),
            self._row("e2", "proxychains4 config line", rare=True),
            self._row("e3", "погода в Амстердаме сегодня", cos=0.2),
            self._row("e4", "рецепт борща", cos=None),
        ]
        out = TP.select_facts(rows, message="как настроить туннель для гемини", recent_ids=[], seen_fact_ids=[])
        evs = [f["ev"] for f in out]
        self.assertEqual(evs[:2], ["e1", "e2"])
        # off-topic rows only fill free slots, at a lower score
        self.assertEqual(len(out), 3)
        self.assertTrue(out[2].get("off_topic"))
        self.assertAlmostEqual(out[2]["score"], 0.02 * TP.SOFT_FACTOR, places=6)
        for f in out:
            self.assertNotIn("cos", f)
            self.assertNotIn("pack_soft", f)

    def test_off_topic_dropped_when_slots_full(self):
        rows = [self._row("e%d" % i, "туннель гемини вариант %d" % i, cos=0.7) for i in range(3)]
        rows.append(self._row("x", "рецепт борща", cos=0.1))
        out = TP.select_facts(rows, message="туннель гемини", recent_ids=[], seen_fact_ids=[])
        self.assertEqual([f["ev"] for f in out], ["e0", "e1", "e2"])

    def test_weak_hint_sees_low_score(self):
        rows = [self._row("x", "рецепт борща", cos=0.1, score=0.3)]
        out = TP.select_facts(rows, message="туннель гемини настройка", recent_ids=[], seen_fact_ids=[])
        self.assertTrue(D17.facts_are_weak(out))


class ClipWindow(unittest.TestCase):
    def test_window_on_match(self):
        text = "Вопрос про погоду и прочее. " * 8 + "ответ: порт прокси 17890 в proxychains4. " + "хвост " * 30
        piece, start = TC.clip_window(text, "порт прокси 17890", 160)
        self.assertGreater(start, 0)
        self.assertIn("17890", piece)
        self.assertLessEqual(len(piece), 160)

    def test_head_kept_when_head_matches(self):
        text = "порт прокси 17890 задан. " + "прочее " * 60
        piece, start = TC.clip_window(text, "порт прокси", 160)
        self.assertEqual(start, 0)

    def test_compact_marks_soft_and_windows(self):
        text = "Вопрос про погоду. " * 12 + "порт прокси 17890 в конфиге. " + "хвост " * 40
        rows = TC.compact_facts([{"event_id": "u::remember_1", "summary": text, "score": 0.02, "cos": 0.5}],
                                "", cfg={}, message="какой порт прокси", terms="порт прокси 17890")
        self.assertTrue(rows[0]["pack_soft"])
        self.assertIn("17890", rows[0]["fact"])
        self.assertTrue(rows[0]["fact"].startswith("… "))
        self.assertEqual(rows[0]["cos"], 0.5)


class SeenTTL(unittest.TestCase):
    def test_expire_and_restamp(self):
        seq = TP.seen_update([], ["a", "b"], 1)
        self.assertEqual(TP.seen_active(seq, 2), ["a", "b"])
        seq = TP.seen_update(seq, ["b"], 10)
        self.assertEqual(set(TP.seen_active(seq, 1 + TP._SEEN_TTL)), {"b"})
        self.assertEqual(TP.seen_active(seq, 10 + TP._SEEN_TTL), [])

    def test_legacy_list(self):
        turn, pairs = TP.seen_state(["x%d" % i for i in range(100)])
        self.assertEqual(turn, 0)
        self.assertEqual(len(pairs), TP._SEEN_CAP)
        self.assertEqual(TP.seen_active(pairs, TP._SEEN_TTL), [])

    def test_session_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "tp.db")
            st, _ = TP._load_sess(db, "u", "s")
            st["seen_seq"] = TP.seen_update([], ["a"], 3)
            st["turn"] = 3
            TP._save_sess(db, "u", "s", st)
            st2, existed = TP._load_sess(db, "u", "s")
            self.assertTrue(existed)
            self.assertEqual(st2["turn"], 3)
            self.assertEqual(st2["seen"], ["a"])


class TopicTrigger(unittest.TestCase):
    def test_short_reply_is_not_new_topic(self):
        trig, sim = D17.topic_trigger("ок, давай дальше", "продолжение фикса памяти", ["совсем другое"])
        self.assertEqual(trig, "")

    def test_inflected_words_overlap(self):
        recent = ["Q: почини фильтр фактов в упаковке A: фильтр фактов поправлен, упаковка проверена"]
        trig, sim = D17.topic_trigger("а что с фильтром фактов при упаковке компактного ответа сейчас",
                                      "фильтры фактов упаковки", recent)
        self.assertEqual(trig, "")
        self.assertGreater(sim, 0.12)

    def test_phrase_still_triggers(self):
        trig, _ = D17.topic_trigger("другая тема: купить билеты", "", ["что угодно"])
        self.assertEqual(trig, "phrase")


class ContextMetrics(unittest.TestCase):
    def test_log_context_row(self):
        import sqlite3
        import turn_diet as TD
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "cs.db")
            self.assertTrue(TD.log_context(db, "u", "mcp", {"mode": "context", "facts": [{"ev": "a"}]}, "context_seal"))
            c = sqlite3.connect(db)
            row = c.execute("select mode, facts from diet_metrics").fetchone()
            c.close()
            self.assertEqual(row, ("context_seal", 1))


if __name__ == "__main__":
    unittest.main()
