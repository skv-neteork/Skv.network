"""C1: actor and is_self in facts, [ev:id@agent], identify without role, soft identify, step_zero reminder, while_away lines."""
import json
import re
import sqlite3
import unittest

from app.room.bridge import (
    SOFT_IDENTIFY_HINT, STEP_ZERO_NEXT, _annotate_facts, do_identify, finish_turn, gate, mark_pack_seen,
    pack_seen, rest_attach, rest_step_zero, soft_nudge_due, turn_gist,
)
from app.room.digest import build_while_away
from app.room.identity import identify, resolve_call
from app.room.schema import ensure

INFO = {"key_id": "k1", "user_id": "u@example.invalid", "chain_id": "ch1", "key_name": "line"}
T0 = "2026-11-10 21:05:00"   # UTC, 00:05 MSK next day


def _conn():
    c = sqlite3.connect(":memory:")
    ensure(c)
    c.execute("CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, essence TEXT, actor_agent_id TEXT, session_id TEXT, ev_kind TEXT, author_kind TEXT, gist TEXT)")
    c.commit()
    return c


def _who(c, tok, sess):
    return resolve_call(c, INFO["key_id"], INFO["chain_id"], INFO["key_name"], agent_token=tok, session_id=sess)


class C1Tests(unittest.TestCase):
    def setUp(self):
        self.c = _conn()
        self.a = do_identify(INFO, self.c, "grok-bot", session_id="sa")
        self.b = do_identify(INFO, self.c, "grok-chat", session_id="sb")

    def tearDown(self):
        self.c.close()

    def test_two_tokens_each_sees_own_is_self_and_other_actor(self):
        wa, wb = _who(self.c, self.a["agent_token"], "sa"), _who(self.c, self.b["agent_token"], "sb")
        finish_turn(self.c, INFO, wa, {"saved": True, "event_id": "u@example.invalid::remember_111111111", "session_id": "sa"}, gist="Сделал облегчение step_zero.")
        finish_turn(self.c, INFO, wb, {"saved": True, "event_id": "u@example.invalid::remember_222222222", "session_id": "sb"}, gist="Проверил identify.")
        facts = [
            {"ev": "remember_111111111", "time": "t", "fact": "Сделал облегчение [ev:remember_111111111]"},
            {"ev": "remember_222222222", "time": "t", "fact": "Проверил identify [ev:remember_222222222]"},
            {"ev": "remember_old", "time": "t", "fact": "legacy [ev:remember_old]"},
        ]
        fa = [dict(f) for f in facts]
        _annotate_facts(self.c, INFO["chain_id"], "grok-bot", fa, set())
        self.assertEqual((fa[0]["actor"], fa[0]["is_self"]), ("grok-bot", True))
        self.assertEqual((fa[1]["actor"], fa[1]["is_self"]), ("grok-chat", False))
        self.assertIn("[ev:remember_222222222@grok-chat]", fa[1]["fact"])
        self.assertIn("[ev:remember_111111111]", fa[0]["fact"])
        self.assertNotIn("@", fa[0]["fact"])
        self.assertEqual((fa[2]["actor"], fa[2]["is_self"]), (None, False))
        fb = [dict(f) for f in facts]
        _annotate_facts(self.c, INFO["chain_id"], "grok-chat", fb, set())
        self.assertEqual((fb[1]["actor"], fb[1]["is_self"]), ("grok-chat", True))
        self.assertEqual((fb[0]["actor"], fb[0]["is_self"]), ("grok-bot", False))

    def test_recap_saved_turns_are_stamped(self):
        wa = _who(self.c, self.a["agent_token"], "sa")
        out = finish_turn(self.c, INFO, wa, {"recap_saved": 2, "recap_event_ids": ["remember_31", "remember_32"],
                                             "recap_seals": [{"ref": "t1u", "event_id": "remember_31"}, {"ref": "t2u", "event_id": "remember_32"}],
                                             "session_id": "sa"}, gists={"remember_31": "первый", "remember_32": "второй"})
        rows = self.c.execute("SELECT event_id, actor_agent_id, gist FROM room_events ORDER BY id").fetchall()
        self.assertEqual([r[1] for r in rows], ["grok-bot", "grok-bot"])
        self.assertEqual([r[2] for r in rows], ["первый", "второй"])
        self.assertTrue(rows[0][0].startswith("u@example.invalid::"))
        self.assertEqual(out["actor"], "grok-bot")

    def test_identify_accepts_role_and_client_hint(self):
        got = identify(self.c, "k1", "ch1", "claude-code", role="executor", client_hint="Claude Code 2.0", session_id="sc")
        self.assertEqual(got["role"], "assistant")
        hint = self.c.execute("SELECT client_hint FROM agents WHERE name='claude-code'").fetchone()[0]
        self.assertIn("role=executor", hint)
        self.assertIn("Claude Code", hint)
        ok = identify(self.c, "k1", "ch1", "supervisor-x", role="Supervisor", session_id="sd")
        self.assertEqual(ok["role"], "supervisor")
        via = do_identify(INFO, self.c, "gpt-web", role="whatever", client_hint="browser", session_id="se")
        self.assertTrue(via["agent_token"])

    def test_identify_says_to_call_step_zero_and_turn_reminds_until_it_is_called(self):
        self.assertTrue(self.a["step_zero"])
        self.assertEqual(self.a["next"], STEP_ZERO_NEXT)
        self.assertIn("step_zero(agent_token)", self.a["room_text"])
        wa = _who(self.c, self.a["agent_token"], "sa")
        r1 = finish_turn(self.c, INFO, wa, {"saved": True, "event_id": "e1", "session_id": "sa"})
        self.assertIn("step_zero", r1["step_zero_reminder"])
        rest_step_zero(INFO, self.c, self.a["agent_token"], session_id="sa")
        self.assertTrue(pack_seen(self.c, "k1", "grok-bot"))
        r2 = finish_turn(self.c, INFO, wa, {"saved": True, "event_id": "e2", "session_id": "sa"})
        self.assertNotIn("step_zero_reminder", r2)
        again = do_identify(INFO, self.c, "grok-bot", session_id="sa")   # same session: nothing due again
        self.assertNotIn("step_zero(agent_token) и прочитай", again["next"])

    def test_turn_without_token_is_saved_with_a_reminder(self):
        soft = gate(INFO, self.c, "", "new-session", soft=True)
        self.assertTrue(soft["ok"] and soft["soft_identify"] and soft["implicit"])
        hard = gate(INFO, self.c, "", "new-session2")
        self.assertEqual(hard["error"], "IDENTIFY_REQUIRED")
        res = rest_attach(INFO, self.c, {"saved": True, "event_id": "x1", "session_id": "r"}, "", "r")
        self.assertTrue(res["saved"])
        self.assertTrue(res["identify_hint"])

    def test_single_agent_key_without_identify_gets_a_soft_nudge(self):
        c = _conn()
        try:
            info = {"key_id": "k-solo", "user_id": "solo@example.invalid", "chain_id": "ch-solo", "key_name": "solo"}
            r1 = rest_attach(info, c, {"saved": True, "event_id": "s1", "session_id": "only"}, "", "only")
            self.assertEqual(r1["identify_hint"], SOFT_IDENTIFY_HINT)
            r2 = rest_attach(info, c, {"saved": True, "event_id": "s2", "session_id": "only"}, "", "only")
            self.assertNotIn("identify_hint", r2)
            self.assertTrue(soft_nudge_due("k-x", "s") and not soft_nudge_due("k-x", "s"))
        finally:
            c.close()

    def test_while_away_one_line_per_foreign_turn(self):
        wa, wb = _who(self.c, self.a["agent_token"], "sa"), _who(self.c, self.b["agent_token"], "sb")
        for i, g in enumerate(["Сделал облегчение step_zero. Тесты 111/111.", "Починил identify: role принимается."]):
            finish_turn(self.c, INFO, wb, {"saved": True, "event_id": "u@example.invalid::remember_90%d" % i, "session_id": "sb"}, gist=g)
        built = build_while_away(self.c, "grok-bot", "k1", "ch1", "assistant")
        lines = built["text"].splitlines()
        self.assertEqual(len(lines), 2)
        for ln in lines:
            self.assertRegex(ln, r"^grok-chat \d\d:\d\d MSK: .+ \[ev:remember_90\d@grok-chat\]$")
            self.assertLessEqual(len(ln), 140)
        self.assertNotIn("::", built["text"])
        self.assertNotIn("ходы других", built["text"])

    def test_while_away_caps_at_five_lines_then_more(self):
        wb = _who(self.c, self.b["agent_token"], "sb")
        for i in range(9):
            finish_turn(self.c, INFO, wb, {"saved": True, "event_id": "u@example.invalid::remember_80%d" % i, "session_id": "sb"}, gist="ход %d" % i)
        built = build_while_away(self.c, "grok-bot", "k1", "ch1", "assistant")
        lines = built["text"].splitlines()
        self.assertLessEqual(len(lines), 5)
        self.assertRegex(lines[-1], r"^\+\d+ ещё")

    def test_gist_never_carries_a_secret(self):
        self.assertEqual(turn_gist("my key is sk_live_ABCDEF1234567890"), "")
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123", turn_gist("Токен ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 готов."))
        self.assertEqual(turn_gist("Первая фраза. Вторая фраза."), "Первая фраза.")
        self.assertLessEqual(len(turn_gist("а" * 300)), 80)


if __name__ == "__main__":
    unittest.main()
