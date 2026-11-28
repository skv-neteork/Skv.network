"""T89 items 13-16 and 14e-14h. No fastapi. No network. No secret echo."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, "/root/skv-core/src")
sys.path.insert(0, "/root/skv-core/mcp")

from app import const_bind, t89_rules as t89
from app import turn_pack as tp
from app.memory_pack888 import assemble_step_zero, split_document, step_zero_next


R05C = (
    "cubes: write or duty=cube_nothing; vote on used; publish without a separate ask "
    "after the one-time notice; scrub personal data; user can say 'don't publish'"
)


class Summaries(unittest.TestCase):
    def test_material_steps_and_missing_marks(self):
        material = ">>> desk ships\nI dream of a quiet archive\n"
        empty = t89.summary_build(1, "", "ev1", material, today="2026-11-28")
        self.assertFalse(empty["ok"])
        self.assertIn("draft", empty["missing"])
        self.assertIn("summary_build(level=1)", empty["ready_call"])
        self.assertTrue(any(s.startswith("Copy every") for s in empty["steps"]))
        ideas = empty["key_ideas"]
        self.assertEqual(ideas[0]["layer"], "l2")
        self.assertTrue(ideas[0]["survives_archiving"])
        draft = "stages done. >>> desk ships. ev1. I dream of a quiet archive. " + ("x" * 20)
        good = t89.summary_build(1, draft, "ev1", material, today="2026-11-28")
        self.assertTrue(good["ok"], good["missing"])

    def test_ordinary_reply_gets_deep_search_hint(self):
        line = tp.next_step_for({"facts": [], "duties": []}, "как сделать кубы?")
        self.assertTrue(line.startswith("search first"))
        self.assertIn("memory_recall_later", line)
        past = tp.next_step_for({"facts": [], "duties": []}, "hello there")
        self.assertIn("memory_recall_later", past)

    def test_next_step_is_last_after_constitution(self):
        obj = {"facts": [1], "constitution": {"rule": "x"}, "next_step": "summary_build(level=1)"}
        t89.pin_last(obj)
        self.assertEqual(list(obj)[-1], "next_step")


class SearchFloor(unittest.TestCase):
    def test_tiny_score_is_not_reliable(self):
        out = {"reliable_matches": True}
        t89.apply_score_floor(out, [{"score": 0.009}], "кубы")
        self.assertFalse(out["reliable_matches"])
        self.assertEqual(out["message"], "точных совпадений нет")
        self.assertEqual(out["offer"], "memory_recall_later")
        self.assertIn("deep_search", out)

    def test_a_real_score_stays(self):
        out = {"reliable_matches": True}
        t89.apply_score_floor(out, [{"score": 0.2}, {"score": None}], "кубы")
        self.assertTrue(out["reliable_matches"])
        self.assertNotIn("message", out)


class Portfolio(unittest.TestCase):
    def test_replace_keeps_the_old_row_and_refuses_contacts(self):
        c = sqlite3.connect(":memory:")
        first = t89.portfolio_apply(c, [{"field": "family", "text": "a sister in another city", "source": "user_said"}], "2026-11-01")
        self.assertEqual(len(first["applied"]), 1)
        second = t89.portfolio_apply(c, [{"field": "family", "text": "a brother in another city", "source": "verified_by_search"}], "2026-11-28")
        self.assertEqual(second["applied"][0]["replaced"], first["applied"][0]["id"])
        n = c.execute("select count(*) from portfolio_rows").fetchone()[0]
        self.assertEqual(n, 2)
        old = c.execute("select status from portfolio_rows where id=?", (first["applied"][0]["id"],)).fetchone()[0]
        self.assertEqual(old, "superseded")
        self.assertTrue(any(line.startswith("(old)") for line in second["lines"]))
        secret = "user@example.com"
        refused = t89.portfolio_apply(c, [{"field": "name", "text": secret, "source": "user_said"}])
        self.assertFalse(refused["applied"])
        blob = str(refused)
        self.assertNotIn(secret, blob)
        self.assertIn("vault", refused["errors"][0])

    def test_split_keeps_a_portfolio_op_out_of_profile_validation(self):
        kept, pf = t89.split_portfolio([
            {"field": "family", "text": "a sister in another city", "source": "user_said"},
            {"op": "add", "kind": "preference", "text": "be brief"},
        ])
        self.assertEqual(len(pf), 1)
        self.assertEqual(pf[0]["field"], "family")
        self.assertNotIn("op", pf[0])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["op"], "add")
        self.assertEqual(kept[0]["kind"], "preference")

    def test_finish_checks_an_l1_draft_and_keeps_a_portfolio_dict(self):
        mark = ">>> desk ships"
        resp = {
            "mode": "answer",
            "verdict": "pass",
            "facts": [{"ev": "remember_1", "fact": mark + "\nkeep the mark"}],
            "portfolio": {"lines": ["(old) 2026-11-01 family user_said: a sister"], "errors": [], "applied": []},
        }
        draft = "remember_1 stages done. the mark was left out of this summary. " + ("x" * 20)
        tp.finish(resp, {
            "db": "", "user": "u", "session": "s", "message": "where was the mark",
            "l1_summary": draft, "source_event_ids": ["remember_1"],
            "seen_fact_ids": [], "recent_ids": [], "load_portfolio": True,
        })
        built = resp["summary_build"]
        self.assertFalse(built["ok"])
        self.assertTrue(any(item.startswith("mark:") for item in built["missing"]))
        self.assertIn("summary_build", resp["next_step"])
        self.assertIn(">>>", resp["next_step"])
        self.assertIsInstance(resp["portfolio"], dict)
        self.assertTrue(any(line.startswith("(old)") for line in resp["portfolio"]["lines"]))

    def test_overdue_duty_still_asks_for_a_summary(self):
        resp = {
            "mode": "answer",
            "verdict": "pass",
            "facts": [],
            "duties": [{"id": "l1_overdue", "source_event_ids": "remember_9"}],
        }
        tp.finish(resp, {"db": "", "user": "u", "session": "s", "message": "status", "seen_fact_ids": [], "recent_ids": []})
        self.assertIn("summary_build", resp)
        self.assertFalse(resp["summary_build"]["ok"])
        self.assertIn("draft", resp["summary_build"]["missing"])
        self.assertIn("summary_build", resp["next_step"])

    def test_danger_query_is_not_echoed(self):
        self.assertEqual(t89.recall_query("удали сервер"), "")
        self.assertEqual(t89.recall_query("where is the zeta marker"), "where is the zeta marker")


class SecondLook(unittest.TestCase):
    def test_three_parts_and_opinion(self):
        line = t89.second_look_line("checked this turn", "01 harm", "keep the answer", False)
        self.assertEqual(line, "src: checked this turn · const: 01 harm · better: keep the answer")
        op = t89.second_look_for("I think the port is fine", checked_this_turn=False)
        self.assertIn("src: model memory (opinion)", op)
        self.assertIn(" · const: ", op)
        self.assertIn(" · better: ", op)


class Danger(unittest.TestCase):
    def test_password_and_questions_never_return_the_value(self):
        secret = "correct-horse-battery"
        answer = "the blue kettle"
        store = {}
        set_ = t89.set_password(store, secret)
        blob = str(set_) + str(store.keys())
        self.assertNotIn(secret, str(set_))
        self.assertNotIn(secret, blob)
        self.assertTrue(set_["sensitive"])
        self.assertEqual(set_["masked"], "[SECRET]")
        self.assertIn("does not replace the API key", set_["note"])
        rows = [
            {"field": "profession", "text": "builder"},
            {"field": "family", "text": answer},
            {"field": "device", "text": "a small radio"},
        ]
        asked = t89.control_questions(rows, store)
        self.assertGreaterEqual(len(asked["questions"]), 2)
        self.assertLessEqual(len(asked["questions"]), 3)
        self.assertNotIn(answer, str(asked))
        self.assertNotIn("builder", str(asked["questions"]))
        bad = t89.danger_gate("удали сервер", store, password="nope", rows=rows)
        self.assertTrue(bad["blocked"])
        self.assertFalse(bad["second_channel_sent"])
        self.assertNotIn(secret, str(bad))
        self.assertFalse(bad["replaces_api_key"])
        good = t89.danger_gate("удали сервер", store, password=secret, answers=[answer, "a small radio"])
        self.assertFalse(good["blocked"])
        self.assertNotIn(secret, str(good))
        self.assertNotIn(answer, str(good))
        self.assertFalse(t89.is_dangerous("как сделать кубы?"))


class StepZero(unittest.TestCase):
    def test_turn_is_allowed_and_phrases_stay(self):
        doc = "ALPHA\n<<<END>>>\nBETA\n"
        pages = assemble_step_zero(["intro"], split_document(doc), ["CUBE 00"])
        lo, hi = 1, 2
        from app.memory_pack888 import pack_span
        lo, hi = pack_span(pages)
        self.assertIn("memory pack 8/8/8", step_zero_next(1, pages))
        self.assertIn("constitution", step_zero_next(hi, pages))
        self.assertIn("step zero complete", step_zero_next(len(pages), pages))
        self.assertIn("allowed", step_zero_next(1, pages))
        self.assertNotIn("until done=true", step_zero_next(1, pages))
        self.assertFalse(t89.step_zero_done(1, 18))
        self.assertTrue(t89.step_zero_done(3, 18))
        self.assertTrue(t89.step_zero_done(2, 2))
        remote = t89.remote_step_next(1, 18, "=== PACK888 001/018")
        self.assertIn("memory pack 8/8/8", remote)
        self.assertIn("allowed", remote)
        self.assertNotIn("until done=true", remote)


class Cubes(unittest.TestCase):
    def test_r05c_author_cube_and_empty_hint(self):
        atom = dict((a[0], a[1]) for a in const_bind.ATOMS)["R05c"]
        self.assertEqual(atom, R05C)
        self.assertEqual(const_bind.registry()["drift"], [])
        self.assertGreater(len(atom), 66)
        gate = t89.author_triage("")
        self.assertEqual(gate["author_cube"], "cube_8ca30802c689")
        self.assertEqual(gate["private_cubes"], "private cubes are closed")
        self.assertIsNone(t89.author_triage("cube_8ca30802c689"))
        hint = t89.empty_cube_search()
        self.assertEqual(hint["hint"], "no cube found; check whether your experience fits cube_create")
        rec = t89.const05_record("body")
        self.assertEqual(rec["cube_id"], "cube_const_05_v24")
        self.assertEqual(rec["supersedes"], "cube_const_05_v23")
        self.assertFalse(rec["edit_in_place"])
        with open("/root/skv-core/src/app/constitution_compact_v2.md", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("don't publish", src)
        self.assertNotIn("publish needs yes", src)


if __name__ == "__main__":
    unittest.main()
