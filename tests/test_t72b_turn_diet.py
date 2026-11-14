"""T72b: turn_diet dedup resets (per account+session, cooldown window, state change); l1_overdue is throttled unless escalated."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, "/root/skv-core/mcp")
import turn_diet as TD  # noqa: E402


class GateTests(unittest.TestCase):
    def setUp(self):
        self.p = tempfile.mktemp(suffix=".db")
        self.c = TD._db(self.p)

    def tearDown(self):
        self.c.close()
        if os.path.exists(self.p):
            os.remove(self.p)

    def gate(self, turn, duties, scope="s1", user="u"):
        out, held = TD.gate_duties(self.c, user, turn, duties, False, scope)
        self.c.commit()
        return out, held

    def test_plain_duty_returns_after_reset_window(self):
        duty = {"foo": "bar", "text": "do the thing"}
        shown = [t for t in range(1, 120) if self.gate(t, [duty])[0]]
        self.assertEqual(shown[:3], [1, 6, 11])
        self.assertNotIn(16, shown)
        self.assertTrue(any(t >= 11 + int(TD.cfg("duty_reset_turns")) for t in shown), shown)   # it comes back
        self.assertLess(len(shown), 20)   # but no flood

    def test_scope_is_per_session(self):
        duty = {"foo": "bar"}
        for t in (1, 6, 11):
            self.assertTrue(self.gate(t, [duty], scope="A")[0])
        self.assertFalse(self.gate(12, [duty], scope="A")[0])
        self.assertTrue(self.gate(12, [duty], scope="B")[0])   # another session is not silenced

    def test_state_change_reshows(self):
        a = {"id": "x_due", "do": "5 turns waiting"}
        for t in (1, 6, 11):
            self.gate(t, [a])
        self.assertFalse(self.gate(12, [a])[0])
        b = {"id": "x_due", "do": "27 turns waiting"}
        self.assertTrue(self.gate(13, [b])[0])

    def test_l1_overdue_is_throttled(self):
        shown = 0
        for t in range(1, 151):
            d = {"id": "l1_overdue", "kind": "summary", "do": "L1 OVERDUE (%d turns uncovered): do it" % (20 + t // 40)}
            if self.gate(t, [d])[0]:
                shown += 1
        self.assertLess(shown, 70)
        self.assertGreater(shown, 30)   # still a steady reminder, not silence

    def test_escalated_l1_overdue_every_turn(self):
        shown = sum(1 for t in range(1, 21) if self.gate(t, [{"id": "l1_overdue", "do": "MANDATORY: l1 reminded 6 times without action, do it now. L1 OVERDUE (30 turns)"}])[0])
        self.assertEqual(shown, 20)

    def test_other_critical_every_turn(self):
        shown = sum(1 for t in range(1, 11) if self.gate(t, [{"id": "missed_turns", "kind": "missed_turns", "n": 1}])[0])
        self.assertEqual(shown, 10)

    def test_apply_moves_overdue_l1_out_of_summary_due(self):
        resp = {"verdict": "pass", "duties": [{"id": "l1_overdue", "do": "L1 OVERDUE (30 turns)"}],
                "summary_due": {"l1": "x", "l1_pending": 30, "l1_source_event_ids": "a,b", "l2": "L2 now"}}
        ctx = {"user": "u", "session": "s9", "eligible": True, "verbose": False, "draft": "", "checklist": [], "slq": False, "tools": set(), "params": set()}
        TD.apply(self.p, {"verdict": "pass"}, ctx)   # opens the session: the next call is a compact turn
        out, mode = TD.apply(self.p, resp, ctx)
        self.assertEqual(mode, "compact")
        self.assertEqual(out["summary_due"], {"l2": "L2 now"})


if __name__ == "__main__":
    unittest.main()
