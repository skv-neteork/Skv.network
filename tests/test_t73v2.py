"""T73 v2: tool duty, agent search_as, tool map, recall component, notebook guards."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SKV_TOOL_MAP_DB", tempfile.mktemp(suffix="-toolmap.db"))
os.environ.setdefault("SKV_RECALL_COMPONENT_DB", tempfile.mktemp(suffix="-recallc.db"))

from app import critical_auto as ca
from app import cubes_v2 as cv
from app import profile
from app import recall_later as rl
from app import tool_duty
from app import tool_map
from app import turn_context as tc
from app.components import recall_component as rc
from app.cube_dedup import public_author
from app.turn_watch_rest import parse_recap


class ToolDuty(unittest.TestCase):
    def test_past_question_with_weak_facts(self):
        line = tool_duty.duty_line("помнишь, мы обсуждали vault?", [{"fact": "picnic plan for sunday"}])
        self.assertTrue(line)
        self.assertIn("memory_recall_later", line)
        self.assertIn("memory_recall_status", line)

    def test_on_topic_facts_skip_the_duty(self):
        self.assertIsNone(tool_duty.duty_line(
            "did we ship the vault?",
            [{"fact": "shipped the vault yesterday after the review"}],
        ))

    def test_did_we_names_board_and_commit(self):
        line = tool_duty.duty_line("did we ship the vault?", [])
        self.assertIn("board", line)
        self.assertIn("git commit", line)

    def test_one_field(self):
        out = tool_duty.apply({"duties": ["other"]}, "yesterday we discussed the vault", [])
        self.assertTrue(out["tool_duty"].startswith("Search yourself before answering"))
        self.assertEqual(out["duties"][0], out["tool_duty"])
        again = tool_duty.apply(out, "yesterday we discussed the vault", [])
        self.assertEqual(again["duties"].count(out["tool_duty"]), 1)


class SearchAs(unittest.TestCase):
    def test_clean_keeps_n_and_uses_sanitize(self):
        fs = rl._sa_clean(["ship the vault on N", "[ok] extra form"], "other question here")
        self.assertTrue(any(" N" in f or f.endswith("N") for f in fs))
        self.assertTrue(any("ok extra" in f for f in fs))
        self.assertFalse(any("[" in f or "]" in f for f in fs))

    def test_keep_agent_forms_adds_only(self):
        kept, extra = rl.keep_agent_forms(["a one", "b two", "c three"], ["a one", "translated four"])
        self.assertEqual(kept, ["a one", "b two", "c three"])
        self.assertEqual(extra, ["translated four"])

    def test_submit_stores_sanitized_search_as(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        class _NoThread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

        try:
            with mock.patch("app.recall_later.threading.Thread", _NoThread):
                with mock.patch("app.recall_later._sh.connect", lambda uid: sqlite3.connect(path)):
                    jid = rl.submit(
                        "t73v2-user",
                        "did we ship the vault",
                        search_as=["ship the vault on N", "[ok] extra form"],
                        cost_cap=0.2,
                    )
            c = sqlite3.connect(path)
            row = c.execute(
                "SELECT search_as_json, cost_cap FROM recall_later WHERE job_id=?", (jid,)
            ).fetchone()
            c.close()
            stored = json.loads(row[0])
            self.assertTrue(any("N" in s for s in stored))
            self.assertFalse(any("[" in s for s in stored))
            self.assertEqual(row[1], 0.2)
        finally:
            os.remove(path)


class ToolMapOnce(unittest.TestCase):
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        os.environ["SKV_TOOL_MAP_DB"] = self.path
        self._text = tool_map.MAP_TEXT

    def tearDown(self):
        tool_map.MAP_TEXT = self._text
        os.environ.pop("SKV_TOOL_MAP_DB", None)
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_once_per_hash_then_again_when_text_changes(self):
        user = "map-user"
        first = {}
        tool_map.apply(first, user)
        self.assertEqual(first["tool_map"]["version"], tool_map.version())
        second = {}
        tool_map.apply(second, user)
        self.assertNotIn("tool_map", second)
        tool_map.MAP_TEXT = self._text + "\nextra row -> vault"
        third = {}
        tool_map.apply(third, user)
        self.assertIn("tool_map", third)
        self.assertNotEqual(third["tool_map"]["version"], first["tool_map"]["version"])


class RecallComponent(unittest.TestCase):
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        self.shelf = self.path + ".shelf"
        open(self.shelf, "a").close()
        os.environ["SKV_RECALL_COMPONENT_DB"] = self.path
        os.environ["SKV_RECALL_COMPONENT"] = "1"
        os.environ["SKV_RECALL_COMPONENT_EVERY"] = "5"
        os.environ.pop("SKV_RECALL_DAY_CAP", None)
        os.environ.pop("SKV_RECALL_JOB_CAP", None)

    def tearDown(self):
        os.environ.pop("SKV_RECALL_COMPONENT_DB", None)
        os.environ.pop("SKV_RECALL_COMPONENT", None)
        os.environ.pop("SKV_RECALL_DAY_CAP", None)
        os.environ.pop("SKV_RECALL_JOB_CAP", None)
        for p in (self.path, self.shelf):
            if os.path.exists(p):
                os.remove(p)

    def test_trigger_every_n_topic_and_l1(self):
        self.assertTrue(rc.should_trigger({"turns": 5, "last_sched": 0, "topic": "alpha", "last_topic": "alpha"}))
        self.assertFalse(rc.should_trigger({"turns": 4, "last_sched": 0, "topic": "alpha", "last_topic": "alpha"}))
        self.assertTrue(rc.should_trigger({"turns": 1, "last_sched": 0, "topic": "beta", "last_topic": "alpha"}))
        self.assertTrue(rc.should_trigger({"turns": 1, "last_sched": 1, "topic": "alpha", "last_topic": "alpha", "l1_new": True}))

    def test_kill_switch(self):
        os.environ["SKV_RECALL_COMPONENT"] = "0"
        self.assertFalse(rc.enabled())
        out = {"ok": True}
        self.assertIs(rc.on_turn(out, "nobody", "hello", launch_ok=True), out)
        self.assertNotIn("recalled", out)

    def test_cost_cap_increments_skips(self):
        os.environ["SKV_RECALL_DAY_CAP"] = "0.05"
        os.environ["SKV_RECALL_JOB_CAP"] = "0.2"
        with mock.patch("app.memory_v2.db_path", return_value=self.shelf):
            jid = rc.launch({
                "uid": "cap-user", "message": "vault store", "topic": "vault",
                "turns": 5, "last_sched": 0,
            }, submit_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("submit must not run")))
        self.assertIsNone(jid)
        c = sqlite3.connect(self.path)
        skips = c.execute("SELECT skips FROM rc_state").fetchone()[0]
        c.close()
        self.assertGreaterEqual(skips, 1)

    def test_failure_does_not_raise(self):
        def boom(*a, **k):
            raise RuntimeError("recall down")

        with mock.patch.object(rc, "collect", boom):
            out = rc.on_turn({"ok": True}, "cap-user", "hello", launch_ok=True)
        self.assertTrue(out["ok"])

    def test_judge_skips_seen_and_session(self):
        report = {"evidence": [{
            "selected": True, "ev": "acct::remember_91",
            "text": "shipped the vault store after review", "date": "2026-11-01", "why": "match",
        }]}
        got = rc.judge(report, [], set(), "vault store")
        self.assertEqual(len(got), 1)
        self.assertIn("[ev:remember_91]", got[0]["line"])
        self.assertEqual(rc.judge(report, [], {got[0]["ev"]}, "vault store"), [])
        self.assertEqual(rc.judge(report, ["remember_91"], set(), "vault store"), [])


class RankAndCritical(unittest.TestCase):
    def test_off_topic_critical_does_not_outrank(self):
        hits = [
            {"event_id": "c1", "score": 0.99, "summary": "[critical] host bill ticket", "layer": "critical", "time": "2026-11-01", "source": "critical"},
            {"event_id": "e1", "score": 0.4, "summary": "ship the vault store this week", "time": "2026-11-20", "source": "search"},
        ]
        out = tc.rank(hits, "vault store", set(), False)
        self.assertEqual(out[0]["event_id"], "e1")
        demoted = [h for h in out if h["event_id"] == "c1"][0]
        self.assertEqual(demoted["layer"], "event")
        self.assertLess(demoted["score"], out[0]["score"])

    def test_on_topic_durables_still_tie(self):
        hits = [
            {"event_id": "d1", "score": 0.4, "summary": "[decision] cube store stays free", "layer": "decision", "time": "2026-11-14", "source": "decision"},
            {"event_id": "c1", "score": 0.2, "summary": "[critical] cube store rating", "layer": "critical", "time": "2026-11-14", "source": "critical"},
        ]
        out = tc.rank(hits, "cube store", set(), False)
        self.assertEqual(out[0]["score"], out[1]["score"])
        self.assertEqual(out[0]["layer"], "decision")

    def test_extract_skips_placeholder_junk(self):
        junk = ca.extract("mail test@example.com see https://example.com/a and ticket +7 999 123 45 67 firstvds https://nssurge.com/x")
        kinds = {k for k, _, _ in junk}
        self.assertNotIn("email", kinds)
        self.assertNotIn("link", kinds)
        self.assertNotIn("phone", kinds)
        kept = ca.extract("write ada@skv.network about the vault")
        self.assertTrue(any(k == "email" for k, _, _ in kept))


class ProfileAndRecap(unittest.TestCase):
    def test_separable_only_for_length_and_l2(self):
        length = "profile[0]: text must be 1..300 chars (one rule per row)"
        l2 = "L2 rejected: profile_review required (send profile_review={ops:[...]} )"
        self.assertTrue(profile.separable([length]))
        self.assertTrue(profile.separable([l2]))
        self.assertTrue(profile.separable([length, l2]))
        self.assertFalse(profile.separable([length, "profile[1]: op must be one of add|supersede"]))
        self.assertFalse(profile.separable([]))

    def test_supersede_reason_names_the_floor(self):
        c = sqlite3.connect(":memory:")
        profile.ensure(c)
        c.execute(
            "INSERT INTO profile_rows (id, kind, text, scope, status, source_event_ids, author, confidence, priority, created_at, updated_at) "
            "VALUES ('p1','habit','keep notes short','global','active','[]','agent',0.9,2,'t','t')"
        )
        errs, _out = profile.validate(
            c, "u",
            [{"op": "supersede", "id": "p1", "text": "keep notes shorter", "reason": "no", "ev": "current"}],
            cur_eid="u::remember_1",
        )
        self.assertTrue(any("supersede needs reason (>=5 chars); the row is unchanged" in e for e in errs))

    def test_recap_object(self):
        items = parse_recap({"ref": "t9u", "user": "hi", "answer": "yo"})
        self.assertEqual(items, [("t9u", "hi", "yo")])
        import mcp_skv
        got = mcp_skv._parse_recap({"ref": "t8u", "user": "q", "answer": "a"})
        self.assertEqual(got[0], ("t8u", "q", "a"))


class PoolAndAuthor(unittest.TestCase):
    def test_live_pool_refuses_test_uid_only_on_the_live_file(self):
        live = "/data/skv/metadata_store/shared_master.db"
        self.assertTrue(cv.test_pool_account("a@example.invalid"))
        self.assertTrue(cv.test_pool_account("who@example.com"))
        self.assertTrue(cv.test_pool_account("test_bot"))
        self.assertFalse(cv.test_pool_account("ada@skv.network"))
        self.assertTrue(cv.refuse_live_pool("a@example.invalid", live))
        self.assertFalse(cv.refuse_live_pool("a@example.invalid", "/tmp/not-the-live-pool.db"))
        self.assertFalse(cv.refuse_live_pool("ada@skv.network", live))

    def test_window_name_is_not_a_public_agent(self):
        label = public_author("ada@skv.network", "b20-keepalive")
        self.assertNotIn("agent", label)
        named = public_author("ada@skv.network", "grok-build")
        self.assertEqual(named["agent"], "grok-build")


class DietKeepsFields(unittest.TestCase):
    def test_compact_keeps_tool_map_and_tool_duty(self):
        import turn_diet as td
        path = tempfile.mktemp(suffix=".db")
        duty = "Search yourself before answering: memory_recall_later(query, search_as=[statement])"
        resp = {
            "verdict": "pass", "seal": "s",
            "tool_map": {"version": "abc", "name": "skv-tool-map", "text": "when -> tool"},
            "tool_duty": duty,
            "duties": [duty],
        }
        ctx = {
            "user": "diet-user", "session": "s", "verbose": False, "eligible": True, "draft": "",
            "checklist": [], "slq": False, "prof_extra": {}, "facts": [], "cited": [],
            "tools": set(), "params": set(),
        }
        try:
            td.apply(path, dict(resp), ctx)
            out, mode = td.apply(path, dict(resp), ctx)
            self.assertEqual(mode, "compact")
            self.assertEqual(out["tool_map"]["version"], "abc")
            self.assertTrue(str(out.get("tool_duty") or "").startswith("Search yourself before answering"))
            self.assertTrue(any(str(d).startswith("Search yourself before answering") for d in (out.get("duties") or [])))
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
