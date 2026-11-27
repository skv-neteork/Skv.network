"""T87 seal journal and looks_done created_at. Temp log and db only.

PYTHONPATH=src:mcp:. /root/skv-core/runtime/mcp_venv/bin/python -m unittest tests.test_t87_seal_gap
"""
import json
import os
import tempfile
import unittest

from app import seal_gap as sg
from app import turn_pack as tp


class SealGap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SKV_SEAL_GAP_DB"] = os.path.join(self.tmp, "gap.db")
        os.environ["SKV_SEAL_LOG"] = os.path.join(self.tmp, "seals.log")
        sg._sync_key = None
        self.assertNotIn("/data/skv", sg.db_path())
        self.assertNotIn("/data/skv", sg.log_path())

    def test_missing_seal_opens_a_gap(self):
        note = sg.observe("t87-miss", "tok", [{"text": "plain answer", "ref": "t1u"}])
        self.assertEqual(note["results"][0]["status"], "missing")
        self.assertEqual(note["results"][0]["plan"], "backfill")
        self.assertEqual(note["unsealed_gaps"], 1)
        self.assertEqual(note["unsealed_gaps_total"], 1)
        self.assertEqual(note["duty"]["id"], "unsealed_gap")
        self.assertEqual(note["duty"]["kind"], "unsealed_gap")
        self.assertEqual(note["duty"]["severity"], "critical")
        self.assertIn(sg.PIN, note["duty"]["do"])
        self.assertIn(sg.CLOSE_DUTY, note["duty"]["do"])
        self.assertNotIn("missed_turns", note["duty"]["do"])
        self.assertNotIn("tok", note["scope"])

    def test_repeated_n_is_a_gap(self):
        user = "t87-rep"
        sg.record_issued(user, 5, "ab12", "first answer", event_id="remember_1", via="test")
        other = "second answer\n🔐 SKV | #5·ab12"
        cl = sg.classify(user, other)
        self.assertEqual(cl["status"], "repeated")
        note = sg.observe(user, "tok", [{"text": other, "ref": "t2u"}])
        self.assertEqual(note["unsealed_gaps"], 1)
        self.assertEqual(note["duty"]["id"], "unsealed_gap")
        self.assertIn("t2u", " ".join(note["duty"]["refs"]))

    def test_fabricated_seal_is_a_gap(self):
        text = "drawn\n🔐 SKV | #999·abcd"
        cl = sg.classify("t87-fab", text)
        self.assertEqual(cl["status"], "fabricated")
        self.assertIsNone(sg.parse_seal("no seal"))
        note = sg.observe("t87-fab", "tok", [{"text": text, "ref": "t9u"}])
        self.assertEqual(note["unsealed_gaps"], 1)
        self.assertEqual(note["results"][0]["status"], "fabricated")
        self.assertIn("t9u", " ".join(note["duty"]["refs"]))

    def test_two_unsealed_recap_items_one_duty(self):
        note = sg.observe("t87-two", "tok", [
            {"text": "alpha", "ref": "t10u"},
            {"text": "beta", "ref": "t11u"},
        ])
        self.assertEqual(note["unsealed_gaps"], 2)
        self.assertEqual(note["unsealed_gaps_total"], 2)
        self.assertEqual(note["duty"]["n"], 2)
        refs = " ".join(note["duty"]["refs"])
        self.assertIn("t10u", refs)
        self.assertIn("t11u", refs)

    def test_same_text_twice_in_one_call_counts_once(self):
        note = sg.observe("t87-dup", "tok", [
            {"text": "same body", "ref": "t8u"},
            {"text": "same body", "ref": "t8b"},
        ])
        self.assertEqual(note["unsealed_gaps"], 1)
        self.assertEqual(note["unsealed_gaps_total"], 1)

    def test_valid_journal_seal_is_not_a_gap(self):
        user = "t87-ok"
        text = "the answer"
        sg.record_issued(user, 10, "ab12", text, event_id="remember_10", via="test")
        sealed = text + "\n🔐 SKV | #10·ab12"
        cl = sg.classify(user, sealed)
        self.assertEqual(cl["status"], "ok")
        self.assertEqual(cl["plan"], "link")
        self.assertNotEqual(cl["plan"], "backfill")
        note = sg.observe(user, "tok", [{"text": sealed, "ref": "t1u"}])
        self.assertEqual(note["unsealed_gaps"], 0)
        self.assertEqual(note["unsealed_gaps_total"], 0)
        self.assertIsNone(note["duty"])
        self.assertEqual(note["results"][0]["status"], "ok")

    def test_later_recap_closes_without_increment(self):
        user = "t87-close"
        first = sg.observe(user, "tok", [{"text": "the sent answer", "ref": "t3u"}])
        self.assertEqual(first["unsealed_gaps"], 1)
        self.assertIsNotNone(first["duty"])
        second = sg.observe(user, "tok", [{"text": "the sent answer", "ref": "t3u"}])
        self.assertEqual(second["unsealed_gaps"], 0)
        self.assertEqual(second["unsealed_gaps_total"], 1)
        self.assertIsNone(second["duty"])
        sealed = sg.record_issued(user, 11, "cd34", "another answer", event_id="", via="test")
        opened = sg.observe(user, "tok", [{"text": "another answer", "ref": "t3b"}])
        self.assertEqual(opened["unsealed_gaps"], 1)
        again = "another answer\n🔐 SKV | #11·cd34"
        closed = sg.observe(user, "tok", [{"text": again, "ref": "t3b"}])
        self.assertEqual(closed["results"][0]["status"], "ok")
        self.assertEqual(closed["unsealed_gaps"], 0)
        self.assertIsNone(closed["duty"])
        self.assertIsNone(sealed)

    def test_unsealed_gap_nothing_closes_and_omits_duty(self):
        user = "t87-nothing"
        sg.observe(user, "tok", [{"text": "left open", "ref": "t4u"}])
        closed = sg.observe(user, "tok", [], duty="unsealed_gap_nothing")
        self.assertEqual(closed["unsealed_gaps"], 0)
        self.assertEqual(closed["unsealed_gaps_total"], 1)
        self.assertIsNone(closed["duty"])
        both = sg.observe(user, "tok", [{"text": "opened and closed", "ref": "t5u"}], duty=sg.CLOSE_DUTY)
        self.assertEqual(both["unsealed_gaps"], 1)
        self.assertEqual(both["unsealed_gaps_total"], 2)
        self.assertIsNone(both["duty"])

    def test_duty_reason_closes_the_named_ref(self):
        user = "t87-ref"
        sg.observe(user, "tok", [
            {"text": "keep", "ref": "t6u"},
            {"text": "drop", "ref": "t7u"},
        ])
        note = sg.observe(user, "tok", [], duty_reason="recap of t7u already sent")
        self.assertEqual(note["unsealed_gaps"], 0)
        self.assertEqual(note["unsealed_gaps_total"], 2)
        refs = " ".join(note["duty"]["refs"])
        self.assertIn("t6u", refs)
        self.assertNotIn("t7u", refs)

    def test_legacy_log_row_accepts_matching_code_only(self):
        user = "t87-legacy"
        with open(sg.log_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "t": 1, "user": user, "seal": 3, "code": "abcd",
                "event_id": "remember_9", "via": "old",
            }) + "\n")
        sg._sync_key = None
        ok = sg.classify(user, "old answer\n🔐 SKV | #3·abcd")
        self.assertEqual(ok["status"], "ok")
        self.assertEqual(ok["plan"], "link")
        bad = sg.classify(user, "old answer\n🔐 SKV | #3·ffff")
        self.assertEqual(bad["status"], "repeated")

    def test_totals_sum_agent_scopes_without_storing_the_token(self):
        sg.observe("t87-sum", "agent-a", [{"text": "one"}])
        sg.observe("t87-sum", "agent-b", [{"text": "two"}])
        self.assertEqual(sg.totals_for_user("t87-sum"), 2)
        sc = sg.scope("t87-sum", "secret-token-value")
        self.assertNotIn("secret-token-value", sc)
        self.assertTrue(sc.startswith("t87-sum#"))

    def test_shape_keeps_unsealed_and_missed_turns(self):
        duty = {
            "id": sg.DUTY_ID,
            "kind": sg.DUTY_ID,
            "severity": "critical",
            "pin": sg.PIN,
            "do": sg.PIN + ". Close: send a recap of that answer on a later turn, or duty=%s." % sg.CLOSE_DUTY,
        }
        missed = "missed_turns: send recap for t12u"
        out, counts, _sent, _sd = tp.shape_duties([duty, missed])
        blob = " ".join(tp._blob(d) for d in out)
        self.assertIn("unsealed_gap", blob)
        self.assertIn(sg.PIN, blob)
        self.assertIn("missed_turns", blob)
        self.assertIn("unsealed", counts)
        self.assertIn("missed", counts)
        self.assertEqual(tp._duty_kind(duty), "unsealed")


class LooksDoneCreatedAt(unittest.TestCase):
    def test_item_created_after_the_commit_does_not_hint(self):
        commit = [{"hash": "59594e9", "subject": "T85: score the date window", "ts": 1700000000}]
        after = [{"id": "T85", "title": "chain", "status": "todo", "created_at": 1700000001}]
        self.assertEqual(tp.looks_done_hint(after, commit), "")
        before = [{"id": "T85", "title": "chain", "status": "todo", "created_at": 1699990000}]
        hint = tp.looks_done_hint(before, commit)
        self.assertIn("looks done, close?", hint)
        self.assertIn("T85", hint)
        self.assertIn("59594e9", hint)
        missing = [{"id": "T85", "title": "chain", "status": "todo"}]
        self.assertEqual(tp.looks_done_hint(missing, commit), "")
        no_ts = [{"id": "T85", "title": "chain", "status": "todo", "created_at": 1}]
        self.assertEqual(tp.looks_done_hint(no_ts, [{"hash": "abc1234", "subject": "T85: later"}]), "")


if __name__ == "__main__":
    unittest.main()
