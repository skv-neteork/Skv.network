"""REST /agent/turn: optional msg_ref + recap (turn-watch twin of MCP). Run: PYTHONPATH=src python3 -m unittest tests.test_rest_turn_watch"""
import os, tempfile, unittest

from app import rest_turn as RT
from app import turn_watch_rest as TW


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        TW.DB = os.path.join(self.tmp, "w.db")
        self.calls, self.remembered = [], []
        self.inner_saved = True

        def fake_req(key, method, path, body=None, params=None, base=None):
            if path == "/constitution/status":
                return {"installed_by": "u1"}
            if path == "/remember":
                self.remembered.append(body)
                return {"ok": True, "event_id": "u1::remember_%d" % (len(self.remembered) + 100)}
            return {}

        def fake_inner(*a, **kw):
            self.calls.append(a)
            if not a[2] and not a[3]:   # no draft: context mode
                return {"mode": "context", "facts": []}
            return {"verdict": "pass", "saved": self.inner_saved, "event_id": "x", "duties": [{"id": "d0"}]}
        RT._req = fake_req
        RT._turn_inner = fake_inner

    def t(self, um, ref="", recap=None, draft="a", token=""):
        return RT.turn("sk_x", um, draft, msg_ref=ref, recap=recap, agent_token=token)


class Watch(Base):
    def test_no_msg_ref_is_untouched(self):
        r = self.t("hi")
        self.assertEqual(r["duties"], [{"id": "d0"}])
        self.assertNotIn("recap_saved", r)
        r = self.t("hi [t5u] tagged in the text only")           # tags in the text are not parsed on REST
        self.assertEqual(r["duties"], [{"id": "d0"}])

    def test_gap_gives_missed_turns_then_recap_covers(self):
        self.assertEqual(self.t("m1", "t10u")["duties"], [{"id": "d0"}])
        r = self.t("m5", "t14u")                                  # t11u..t13u went out without turn
        d = r["duties"][0]
        self.assertEqual(d["id"], "missed_turns"); self.assertEqual(d["n"], 3)
        self.assertIn("t11u–t13u", d["do"]); self.assertEqual(d["refs"], "t11u..t13u")
        self.assertEqual(r["duties"][1], {"id": "d0"})
        # same gap, now with a recap for two of the three: only one is still missing
        TW_prev = TW.last_ref(TW.scope("u1"))
        self.assertEqual(TW_prev, 14)

    def test_recap_in_same_call_resolves_gap(self):
        self.t("m1", "t10u")
        rc = [{"ref": "t11u", "user": "q11", "answer": "a11"}, {"ref": "t12u", "user": "q12", "answer": "a12"}, {"ref": "t13u", "user": "q13", "answer": "a13"}]
        r = self.t("m14", "t14u", recap=rc)
        self.assertEqual(r["duties"], [{"id": "d0"}])             # gap resolved by the recap
        self.assertEqual(r["recap_saved"], 3)
        self.assertEqual([b["topic"] for b in self.remembered], ["recap"] * 3)
        self.assertTrue(self.remembered[0]["query"].startswith("[recap t11u]"))

    def test_partial_recap_leaves_rest_missing(self):
        self.t("m1", "t10u")
        r = self.t("m14", "t14u", recap="t11u: q => a\nt13u: q => a")
        d = r["duties"][0]
        self.assertEqual((d["id"], d["n"], d["refs"]), ("missed_turns", 1, "t12u"))
        self.assertEqual(r["recap_saved"], 2)

    def test_context_call_reports_gap_but_does_not_advance(self):
        self.t("m1", "t10u")
        r = RT.turn("sk_x", "m4", "", msg_ref="t13u")             # context mode (no draft)
        self.assertEqual(r["mode"], "context"); self.assertEqual(r["duties"][0]["n"], 2)
        self.assertEqual(TW.last_ref(TW.scope("u1")), 10)

    def test_revise_does_not_advance_and_retry_is_not_a_gap(self):
        self.t("m1", "t10u")
        self.inner_saved = False
        self.t("m2", "t11u")
        self.assertEqual(TW.last_ref(TW.scope("u1")), 10)
        self.inner_saved = True
        r = self.t("m2", "t11u")
        self.assertEqual(r["duties"], [{"id": "d0"}])
        r = self.t("m2", "t11u")                                   # identical retry: no gap
        self.assertEqual(r["duties"], [{"id": "d0"}])

    def test_agents_have_separate_sequences(self):
        self.t("a", "t10u", token="tokA")
        r = self.t("b", "t50u", token="tokB")                      # first message of another agent: no gap
        self.assertEqual(r["duties"], [{"id": "d0"}])
        r = self.t("a2", "t14u", token="tokA")
        self.assertEqual(r["duties"][0]["n"], 3)

    def test_recap_dedupe_and_bad_recap(self):
        self.t("m1", "t10u")
        r = self.t("m2", "t11u", recap=[{"ref": "t9u", "user": "old", "answer": "x"}])
        self.assertEqual(r.get("recap_already_saved"), ["t9u"]); self.assertEqual(r["recap_saved"], 0)
        r = self.t("m3", "t12u", recap="   ")
        self.assertNotIn("recap_error", r)                          # blank recap = not sent
        r = self.t("m4", "t13u", recap=[{"ref": "t12u"}])
        self.assertIn("recap_error", r)

    def test_span_forms(self):
        self.assertEqual(TW.span("t648u"), (648, 648)); self.assertEqual(TW.span("649"), (649, 649))
        self.assertEqual(TW.span("t754u-t755u"), (754, 755)); self.assertEqual(TW.span("junk"), (0, 0))


if __name__ == "__main__":
    unittest.main()
