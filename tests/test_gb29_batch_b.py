"""GB-29 batch B: durable layers compete on relevance plus a bonus, not a forced top score."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from app import turn_context as TC


class RankCompetes(unittest.TestCase):
    def test_off_topic_l1_does_not_beat_best_event(self):
        hits = [
            {"event_id": "u::remember_1", "summary": "порт прокси 17890 в конфиге", "score": 0.03},
            {"event_id": "l1:a", "summary": "[l1] сессия 27.11 вечер: память, бенч, деплой", "layer": "l1", "score": 0.9},
        ]
        out = TC.rank(hits, "какой порт у прокси", set(), False, limit=5)
        self.assertEqual(out[0]["event_id"], "u::remember_1")
        self.assertLess(out[1]["score"], out[0]["score"])

    def test_on_topic_decision_leads_and_stays_on_event_scale(self):
        hits = [
            {"event_id": "u::remember_1", "summary": "что-то про прокси", "score": 0.03},
            {"event_id": "d:1", "summary": "[decision] порт прокси 17890 закреплён", "layer": "decision", "score": 0.9},
        ]
        out = TC.rank(hits, "порт прокси 17890", set(), False, limit=5)
        self.assertEqual(out[0]["event_id"], "d:1")
        self.assertLessEqual(out[0]["score"], 0.03 + 1e-9)
        self.assertNotIn("_key", out[0])

    def test_raw_slots_still_reserved(self):
        hits = [{"event_id": "l1:%d" % i, "summary": "[l1] порт прокси %d" % i, "layer": "l1", "score": 0.9} for i in range(3)]
        hits.append({"event_id": "u::remember_9", "summary": "сырой ответ про порт прокси", "score": 0.01})
        ranked = TC.rank(hits, "порт прокси", set(), False, limit=12)
        facts = TC.compact_facts(ranked, "", cfg={}, message="какой порт прокси сейчас")
        self.assertIn("remember_9", [f["ev"] for f in facts])


if __name__ == "__main__":
    unittest.main()
