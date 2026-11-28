"""T96 items 17, 17b, 18. Response diet and the L1 turn check. No network."""
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, "/root/skv-core/src")

from app import duty_rules, search_v2, t89_rules as t89
from app import turn_context as tc
from app import turn_pack as tp


class Marks(unittest.TestCase):
    def test_full_line_not_one_character(self):
        text = ">>> 2 the cube shipped on Friday\n>>> Р строка целиком остаётся\nnote\n"
        marks = t89.critical_marks(text)
        self.assertEqual(marks[0], ">>> 2 the cube shipped on Friday")
        self.assertEqual(marks[1], ">>> Р строка целиком остаётся")
        self.assertNotEqual(marks[0], ">>> 2")

    def test_prefix_is_not_the_mark(self):
        material = ">>> 2 the cube shipped on Friday\n"
        draft = "stages done. >>> 2 is only the prefix. " + ("x" * 30)
        built = t89.summary_build(1, draft, "remember_1", material, covered_ids=["remember_1"])
        self.assertFalse(built["ok"])
        self.assertTrue(any(item == "mark: >>> 2 the cube shipped on Friday" for item in built["missing"]))

    def test_raw_mark_line_is_not_clipped_at_one_token(self):
        raw = "Saved.\n>>> 2 the cube shipped on Friday\nThe goal.\n"
        self.assertEqual(tp.mark_lines_from_raw(raw), ">>> 2 the cube shipped on Friday")


class SourceIds(unittest.TestCase):
    def test_string_is_not_split_into_characters(self):
        raw = "remember_1,remember_2 remember_3"
        self.assertEqual(tp._parse_ids(raw), ["remember_1", "remember_2", "remember_3"])
        self.assertEqual(tp.bare_ids(raw), ["remember_1", "remember_2", "remember_3"])
        self.assertEqual(tp.bare_ids("user::remember_9"), ["remember_9"])
        self.assertNotEqual(tp.bare_ids(raw)[0], "r")

    def test_param_ids_satisfy_the_check_without_being_in_the_draft(self):
        ids = ["remember_%d" % i for i in range(16)]
        draft = "stages done. decided the pack. outcome shipped. " + ("x" * 20)
        built = t89.summary_build(1, draft, ids, "", covered_ids=",".join(ids))
        self.assertFalse(any(item.startswith("id:") for item in built["missing"]), built["missing"])
        self.assertNotIn(",".join(ids), built["ready_call"])
        self.assertIn("see summary_build.source_event_ids", built["ready_call"])

    def test_finish_keeps_the_id_list_once(self):
        ids = ",".join("remember_%d" % i for i in range(16))
        draft = "stages done. the summary names the work. " + ("x" * 20)
        resp = {
            "mode": "answer",
            "verdict": "pass",
            "facts": [{"ev": "remember_1", "fact": "a fact"}],
            "summary_due": {"l1": "due", "l1_source_event_ids": ids},
        }
        tp.finish(resp, {
            "db": "", "user": "u", "session": "s", "message": "status",
            "l1_summary": draft, "source_event_ids": ids,
            "seen_fact_ids": [], "recent_ids": [],
        })
        built = resp["summary_build"]
        self.assertFalse(any(item.startswith("id:") for item in built["missing"]), built["missing"])
        self.assertEqual(built["source_event_ids"], "see summary_due.l1_source_event_ids")
        self.assertEqual(resp["summary_due"]["l1_source_event_ids"], ids)
        self.assertNotIn(ids, built["ready_call"])
        self.assertNotIn(ids, resp["next_step"])
        self.assertIn("see summary_due.l1_source_event_ids", resp["next_step"])


class SearchAs(unittest.TestCase):
    def test_dash_skips(self):
        self.assertTrue(tc.search_as_skip("-"))
        self.assertTrue(tc.search_as_skip(["-"]))
        self.assertFalse(tc.search_as_skip("статус сборки"))
        q, sa = tc.build_search("как идет ?)", "-", [])
        self.assertEqual(q, "")
        self.assertEqual(sa, [])

    def test_short_message_uses_search_as_as_the_query(self):
        # A status line is the active-state slice. search_as only names the task.
        q, sa = tc.build_search("Как идет ?)", "статус Build по T95", ["older line about a picnic"])
        self.assertEqual(q, "")
        self.assertEqual(sa, [])
        plan = tc.followup_plan("Как идет ?)", "статус Build по T95", ["older line about a picnic"])
        self.assertEqual(plan["mode"], "slice")
        self.assertEqual(plan["task_hint"], "статус Build по T95")
        self.assertFalse(plan["revise"])
        # A non-status short line still searches by the gloss, not by the raw words.
        q2, sa2 = tc.build_search("а про Google?", "нужен ли Google для остатков работ", ["older line about a picnic"])
        self.assertEqual(q2, "нужен ли Google для остатков работ")
        self.assertEqual(sa2, [])
        self.assertNotIn("picnic", q2.lower())
        # Deictic: the gloss is the whole query. The raw line is not added beside it.
        gloss = "Build сделал 40 пропущенных заданий T95"
        q3, sa3 = tc.build_search("а он сделал?", gloss, ["older line about a picnic"])
        self.assertEqual(q3, gloss)
        self.assertEqual(sa3, [])
        self.assertNotIn("picnic", q3.lower())
        deictic = tc.followup_plan("а он сделал?", gloss, ["older line about a picnic"])
        self.assertEqual(deictic["mode"], "deictic")
        self.assertEqual(deictic["user_weight"], 0.0)
        self.assertEqual(deictic["recency_h"], 36.0)
        self.assertEqual(deictic["context"], [])

    def test_long_message_keeps_search_as_beside_the_query(self):
        msg = "what did we decide about the cube store and the archive layout?"
        q, sa = tc.build_search(msg, "cube store decision", [])
        self.assertEqual(q, msg)
        self.assertEqual(sa, ["cube store decision"])


class Diet(unittest.TestCase):
    def test_normal_budget_reserves_a_raw_slot(self):
        hits = [
            {"event_id": "l1:a", "summary": "[l1] alpha topic notes", "layer": "l1", "score": 0.9},
            {"event_id": "l1:b", "summary": "[l1] beta topic notes", "layer": "l1", "score": 0.8},
            {"event_id": "l1:c", "summary": "[l1] gamma topic notes", "layer": "l1", "score": 0.7},
            {"event_id": "u::remember_9", "summary": "raw answer about the topic", "layer": "event", "score": 0.4},
        ]
        facts = tc.compact_facts(hits, "", message="what is the topic status now")
        evs = [f["ev"] for f in facts]
        self.assertIn("remember_9", evs)
        # GB-29 A3: up to 3 extra "reserve" rows may follow; select_facts caps them.
        self.assertLessEqual(len([f for f in facts if not f.get("reserve")]), 3)
        facts = [f for f in facts if not f.get("reserve")]
        # GB-29: a normal row is soft-marked (topic diet may demote it, not drop it).
        self.assertTrue(facts[0].get("pack_soft"))
        self.assertNotIn("summary", facts[0])
        body = "\n".join(f["fact"].split(" [ev:")[0].replace(" [cut]", "") for f in facts)
        self.assertLessEqual(len(body), 1500)
        long = tc.compact_facts(
            [{"event_id": "u::remember_9", "summary": "R" * 400, "layer": "event", "score": 0.4}],
            "", message="what is the topic status now")
        piece = long[0]["fact"].split(" [ev:")[0]
        self.assertTrue(piece.endswith(" [cut]"))
        self.assertEqual(len(piece.replace(" [cut]", "")), 160)

    def test_wide_triggers_keep_2400(self):
        hits = [
            {"event_id": "u::remember_%d" % i, "summary": "word %d %s" % (i, "x" * 300), "score": 1 - i * 0.01}
            for i in range(8)
        ]
        multi = tc.compact_facts(hits, "", message="when did it ship and where is the file?")
        dated = tc.compact_facts(hits, "", message="yesterday the cube store")
        doc = tc.compact_facts(hits, "", message="status", kind="doc")
        plain = tc.compact_facts(hits, "")
        for facts in (multi, dated, doc, plain):
            self.assertTrue(facts[0].get("pack2400"))
            self.assertGreater(len(facts), 3)

    def test_cosine_floor_is_before_fusion_not_a_fused_cut(self):
        kept = search_v2.cosine_keep([("a", 0.36), ("b", 0.34), ("c", 0.90)])
        self.assertEqual([e for e, _s in kept], ["a", "c"])
        fused = search_v2.wrrf(kept, [("b", 1.0)], 1.0, 0.5)
        self.assertIn("b", [e for e, _s in fused])

    def test_duty_line_is_short_and_repeats_on_a_cadence(self):
        full = duty_rules.rule_text("l1")
        short = duty_rules.diet_line(full)
        self.assertLess(len(short), len(full))
        self.assertTrue(short.startswith("RULE l1:"))
        self.assertIn("source_event_ids", short)
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            first = duty_rules.diet_block([full], "u", "s", path)
            second = duty_rules.diet_block([full], "u", "s", path)
            self.assertEqual(first, [short])
            self.assertTrue(second[0].startswith("duty_rules_unchanged"))
        finally:
            os.remove(path)


class ShortSearchTopic(unittest.TestCase):
    def test_short_line_keeps_the_searched_query_and_a_long_line_still_filters(self):
        query = "остатки работ SKV и нужен ли Google"
        short = "как идет ?)"
        facts = [
            {"ev": "remember_1", "fact": "остатки работ SKV и нужен ли Google ещё открыты", "time": "2026-11-01"},
            {"ev": "remember_2", "fact": "picnic on the hill", "time": "2026-11-01"},
        ]
        bare = tp.select_facts([dict(f) for f in facts], message=short)
        self.assertEqual(bare, [])
        kept = tp.select_facts([dict(f) for f in facts], message=short, topic_query=query)
        self.assertEqual([f["ev"] for f in kept], ["remember_1"])
        long_msg = "what remains of the SKV work and is Google still required"
        off = tp.select_facts(
            [{"ev": "remember_9", "fact": "picnic on the hill yesterday afternoon", "time": "2026-11-01"}],
            message=long_msg,
            topic_query=query,
        )
        self.assertEqual(off, [])
        today = date(2026, 11, 28)
        dated = tp.select_facts(
            [
                {"ev": "remember_3", "fact": "picnic on the hill", "time": "2026-11-27 12:00"},
                {"ev": "remember_1", "fact": "остатки работ SKV и нужен ли Google ещё открыты", "time": "2026-11-01"},
                {"ev": "remember_4", "fact": "unrelated porridge note", "time": "2026-11-01"},
            ],
            message="вчера",
            topic_query=query,
            today=today,
        )
        self.assertEqual([f["ev"] for f in dated], ["remember_3", "remember_1"])
        resp = tp.finish(
            {"mode": "context", "facts": [dict(f) for f in facts], "_topic_query": query},
            {"message": short, "user": "", "session": "t19", "db": "", "recent_ids": [], "seen_fact_ids": []},
        )
        self.assertNotIn("_topic_query", resp)
        self.assertEqual([f["ev"] for f in resp["facts"]], ["remember_1"])

    def test_normal_compact_facts_survive_topic_filter_without_word_overlap(self):
        msg = "ну мы сделали что агент пишет свое понимание слов человека?"
        hits = [{"event_id": "u::remember_1", "time": "2026-11-27 18:07", "score": 0.5,
                 "summary": "по хорошему это должно работать как скил энд хук", "source": "x"}]
        facts = tc.compact_facts(hits, "", message=msg, kind="turn")
        self.assertTrue(facts and facts[0].get("pack_soft"))
        out = tp.select_facts(facts, message=msg, recent_ids=[], seen_fact_ids=[], topic_query=msg)
        # No cosine or exact token here: the row stays in a free slot, at a lower score.
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ev"], "remember_1")

    def test_hit_that_overlaps_only_search_as_is_kept(self):
        msg = "ну мы сделали что агент пишет свое понимание слов человека?"
        gloss = "скил энд хук как навык"
        fact = {"ev": "remember_1", "fact": "по хорошему это должно работать как скил энд хук",
                "time": "2026-11-27 18:07"}
        self.assertFalse(tc.on_topic(msg, fact["fact"]))
        self.assertTrue(tc.on_topic(msg, fact["fact"], gloss))
        bare = tp.select_facts([dict(fact)], message=msg, topic_query=msg)
        self.assertEqual(bare, [])
        kept = tp.select_facts([dict(fact)], message=msg, topic_query=msg, search_as=gloss)
        self.assertEqual([f["ev"] for f in kept], ["remember_1"])
        resp = tp.finish(
            {"mode": "context", "facts": [dict(fact)]},
            {"message": msg, "user": "", "session": "t96sa", "db": "",
             "recent_ids": [], "seen_fact_ids": [], "search_as": gloss},
        )
        self.assertEqual([f["ev"] for f in resp["facts"]], ["remember_1"])


if __name__ == "__main__":
    unittest.main()
