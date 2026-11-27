"""T85 chain fix. In-process fixtures. No live index, no production sidecars.

PYTHONPATH=src:mcp:. /root/skv-core/runtime/mcp_venv/bin/python -m unittest tests.test_t85_chain
"""
import ast
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import date
from unittest import mock

from app import board
from app import search_pack
from app import search_window as sw
from app import second_look_q
from app import turn_pack as tp
from app.components import recall_component as rc
from app.mcp_public_tools import SHORT


TODAY = date(2026, 11, 22)


def _fact(ev, fact, time, **extra):
    row = {"ev": ev, "time": time, "fact": fact}
    row.update(extra)
    return row


class F1Rank(unittest.TestCase):
    def test_injected_cosine_uses_rrf_order(self):
        rows = [
            {"id": "low", "date": "2026-11-14 01:00", "content": "alpha " * 40},
            {"id": "high", "date": "2026-11-14 02:00", "content": "beta " * 40},
        ]

        def cos(uid, ids, query):
            return {"low": 0.1, "high": 0.9}

        page = sw.order_rows(rows, "gift", 80, 10, 0, cosine_fn=cos, uid="u", always_rank=True)
        self.assertEqual(page["hits"][0]["id"], "high")
        self.assertGreater(page["hits"][0]["score"], page["hits"][1]["score"])


class F2MskDay(unittest.TestCase):
    def _rows(self, triples):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, kind TEXT, raw_dialogue TEXT)")
        for eid, ts, raw in triples:
            c.execute("INSERT INTO event_metadata VALUES (?,?,?,?)", (eid, ts, "", raw))
        c.commit()
        c.close()
        return path

    def test_exact_msk_day_includes_late_utc_and_excludes_the_neighbours(self):
        path = self._rows([
            ("gold14", "2026-11-13 22:50", "inside 14 Nov MSK"),
            ("early14", "2026-11-13 20:00", "still 13 Nov MSK"),
            ("next14", "2026-11-14 21:30", "already 15 Nov MSK"),
            ("late21", "2026-11-20 21:30", "21 Nov 00:30 MSK"),
            ("edge21", "2026-11-21 21:30", "22 Nov 00:30 MSK"),
            ("before21", "2026-11-20 20:00", "20 Nov 23:00 MSK"),
        ])
        try:
            b14 = sw.parse(since="2026-11-14", until="2026-11-14")
            ids14 = [r["id"] for r in sw.collect("u", b14, db=path)]
            self.assertEqual(ids14, ["gold14"])
            b21 = sw.parse(since="2026-11-21", until="2026-11-21")
            ids21 = [r["id"] for r in sw.collect("u", b21, db=path)]
            self.assertEqual(ids21, ["late21"])
            self.assertNotIn("edge21", ids21)
            self.assertNotIn("before21", ids21)
        finally:
            os.remove(path)

    def test_date_param_stays_plus_minus_one_calendar(self):
        b = sw.parse(date="2026-11-14")
        self.assertEqual(b["since"], "2026-11-13")
        self.assertEqual(b["until"], "2026-11-15")


class F3Echo(unittest.TestCase):
    def test_quote_moves_under_the_original(self):
        gold = {
            "event_id": "remember_gold",
            "summary": "каждый объект SKV имеет свой мини-мозг следит за собой и шлёт сигналы в общий центр",
            "metadata": {"time_str": "2026-10-24 21:57"},
            "score": 0.02,
        }
        echo = {
            "event_id": "remember_echo",
            "summary": "[цитирует мой старый ответ] каждый объект SKV имеет свой мини-мозг следит за собой и шлёт сигналы в общий центр",
            "metadata": {"time_str": "2026-11-22 13:12"},
            "score": 0.04,
        }
        out = search_pack.derank_quotes([echo, gold])
        self.assertEqual(out[0]["event_id"], "remember_gold")
        self.assertEqual(out[1]["echo_of"], "remember_gold")
        self.assertLess(out[1]["score"], gold["score"])

    def test_recall_evidence_selected_zero_is_the_original(self):
        ev = [
            {"ev": "remember_echo", "date": "2026-11-22 13:12", "selected": True,
             "text": "[цитирует мой старый ответ] каждый объект SKV имеет свой мини-мозг следит за собой и шлёт сигналы"},
            {"ev": "remember_gold", "date": "2026-10-24 21:57", "selected": True,
             "text": "каждый объект SKV имеет свой мини-мозг следит за собой и шлёт сигналы в общий центр"},
        ]
        out = search_pack.derank_quotes(ev, id_key="ev")
        selected = [x["ev"] for x in out if x.get("selected")]
        self.assertEqual(selected[0], "remember_gold")


class F4Centres(unittest.TestCase):
    def test_open_search_keeps_five_centres_inside_the_limit(self):
        import mcp_skv
        hits = []
        for i in range(6):
            hits.append({
                "event_id": "remember_%d" % i,
                "ev": "remember_%d" % i,
                "date": "2026-10-24 21:57",
                "score": 1 - i * 0.1,
                "content": "word " * 800,
                "summary": "word " * 200,
                "centre": {"text": "word " * 800},
                "neighbours": [{"text": "near " * 400}, {"text": "near " * 400}],
                "l1": "layer " * 80,
                "l2": "block " * 40,
            })
        raw = {"results": hits, "hits": hits, "n": 6, "order": "mini-lens"}
        text = mcp_skv._search_json(raw)
        self.assertLessEqual(len(text), mcp_skv.RESP_LIMIT)
        data = json.loads(text)
        self.assertGreaterEqual(data["n"], 5)
        self.assertEqual(len(data["results"]), data["n"])
        self.assertTrue(data.get("truncated"))


class F5Window(unittest.TestCase):
    def test_in_window_fact_survives_off_topic_and_self_is_dropped(self):
        facts = [
            _fact("remember_night", "unrelated porridge", "2026-11-20 22:00"),
            _fact("remember_after", "unrelated porridge", "2026-11-21 21:30"),
            _fact("remember_self", "board note", "2026-11-20 22:10", is_self=True),
            _fact("remember_old", "board decision stays", "2026-10-01"),
        ]
        rows = tp.select_facts(facts, message="вчера про доску", today=TODAY)
        ids = [r["ev"] for r in rows]
        self.assertIn("remember_night", ids)
        self.assertNotIn("remember_after", ids)
        self.assertNotIn("remember_self", ids)
        self.assertNotIn("remember_old", ids)

    def test_finish_attaches_loader_l1_and_events(self):
        def loader(user, window):
            return [
                {"ev": "l1:sess", "time": "2026-11-20 22:00", "fact": "[l1] night session", "layer": "l1"},
                {"ev": "l2:b", "time": "2026-11-20 22:00", "fact": "[l2] night block", "layer": "l2"},
                {"ev": "remember_e1", "time": "2026-11-20 22:05", "fact": "one event", "layer": "event"},
                {"ev": "remember_e2", "time": "2026-11-20 22:06", "fact": "two event", "layer": "event"},
                {"ev": "remember_me", "time": "2026-11-20 22:07", "fact": "my own", "is_self": True, "layer": "event"},
            ]

        resp = {"mode": "context", "facts": []}
        tp.finish(resp, {
            "db": "", "user": "u", "session": "s", "message": "вчера", "today": TODAY,
            "recent_ids": [], "seen_fact_ids": [], "commits": [], "window_loader": loader,
        })
        ids = [f["ev"] for f in resp["facts"]]
        self.assertIn("l1:sess", ids)
        self.assertIn("l2:b", ids)
        self.assertIn("remember_e1", ids)
        self.assertNotIn("remember_me", ids)
        layers = {row["layer"] for row in resp["window_map"]}
        self.assertIn("l1", layers)
        self.assertIn("l2", layers)
        self.assertIn("2026-11-21", resp["window_hint"])


class F6Cap(unittest.TestCase):
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix="-rc.db")
        os.close(self.fd)
        self.shelf = self.path + ".shelf"
        open(self.shelf, "a").close()
        self._env = {
            "SKV_RECALL_COMPONENT_DB": os.environ.get("SKV_RECALL_COMPONENT_DB"),
            "SKV_RECALL_COMPONENT": os.environ.get("SKV_RECALL_COMPONENT"),
            "SKV_RECALL_COMPONENT_EVERY": os.environ.get("SKV_RECALL_COMPONENT_EVERY"),
            "SKV_RECALL_DAY_CAP": os.environ.get("SKV_RECALL_DAY_CAP"),
            "SKV_RECALL_JOB_CAP": os.environ.get("SKV_RECALL_JOB_CAP"),
            "SKV_RECALL_MIN_GAP": os.environ.get("SKV_RECALL_MIN_GAP"),
        }
        os.environ["SKV_RECALL_COMPONENT_DB"] = self.path
        os.environ["SKV_RECALL_COMPONENT"] = "1"
        os.environ["SKV_RECALL_COMPONENT_EVERY"] = "5"
        os.environ["SKV_RECALL_DAY_CAP"] = "1"
        os.environ["SKV_RECALL_JOB_CAP"] = "0.2"
        os.environ["SKV_RECALL_MIN_GAP"] = "0"

    def tearDown(self):
        for key, val in self._env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        for p in (self.path, self.shelf):
            if os.path.exists(p):
                os.remove(p)

    def _state(self, n=5):
        return {"uid": "t85-user", "message": "vault store", "topic": "vault store", "turns": n, "last_sched": 0}

    def test_gap_blocks_a_second_job(self):
        os.environ["SKV_RECALL_MIN_GAP"] = "60"
        with mock.patch("app.memory_v2.db_path", return_value=self.shelf):
            first = rc.launch(self._state(), submit_fn=lambda *a, **k: "j1")
            second = rc.launch(self._state(6), submit_fn=lambda *a, **k: "j2")
        self.assertEqual(first, "j1")
        self.assertIsNone(second)
        c = sqlite3.connect(self.path)
        n = c.execute("SELECT count(*) FROM rc_job").fetchone()[0]
        c.close()
        self.assertEqual(n, 1)

    def test_parallel_reserves_stay_inside_the_day_cap(self):
        os.environ["SKV_RECALL_MIN_GAP"] = "0"
        errors = []

        def one(i):
            try:
                rc.launch(self._state(), submit_fn=lambda *a, **k: "j%d" % i)
            except Exception as exc:
                errors.append(type(exc).__name__)

        with mock.patch("app.memory_v2.db_path", return_value=self.shelf):
            threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        c = sqlite3.connect(self.path)
        total = c.execute("SELECT coalesce(sum(reserve),0) FROM rc_job").fetchone()[0]
        n = c.execute("SELECT count(*) FROM rc_job WHERE reserve>0").fetchone()[0]
        c.close()
        self.assertLessEqual(float(total), 1.0 + 1e-6)
        self.assertGreaterEqual(n, 1)
        self.assertLessEqual(n, 5)
        self.assertEqual(errors, [])

    def test_empty_ready_refunds_and_a_later_job_can_run(self):
        os.environ["SKV_RECALL_MIN_GAP"] = "0"
        with mock.patch("app.memory_v2.db_path", return_value=self.shelf):
            jid = rc.launch(self._state(), submit_fn=lambda *a, **k: "j-empty")
            lines = rc.collect("t85-user", "vault store", get_fn=lambda u, j: {
                "status": "done", "report": {"evidence": []},
            })
            again = rc.launch(self._state(10), submit_fn=lambda *a, **k: "j-next")
        self.assertEqual(jid, "j-empty")
        self.assertEqual(lines, [])
        self.assertEqual(again, "j-next")
        c = sqlite3.connect(self.path)
        spent = c.execute("SELECT coalesce(sum(reserve),0) FROM rc_job").fetchone()[0]
        c.close()
        self.assertLessEqual(float(spent), 0.2 + 1e-6)

    def test_five_turns_then_recalled(self):
        os.environ["SKV_RECALL_MIN_GAP"] = "60"
        calls = []

        def submit(*a, **k):
            calls.append(1)
            return "job-ready"

        def get_fn(uid, jid):
            return {"status": "done", "report": {"evidence": [{
                "selected": True, "ev": "remember_91",
                "text": "shipped the vault store after review",
                "date": "2026-11-01", "why": "match",
            }]}}

        with mock.patch("app.memory_v2.db_path", return_value=self.shelf), \
             mock.patch("app.recall_later.submit", submit), \
             mock.patch.object(rc, "_agent_searched", return_value=False), \
             mock.patch("app.recall_later.get", get_fn):
            out = {"ok": True}
            for _ in range(5):
                rc.on_turn(out, "t85-user", "vault store", launch_ok=True)
            self.assertEqual(len(calls), 1)
            rc.on_turn(out, "t85-user", "vault store", launch_ok=True)
        self.assertTrue(out.get("recalled"))
        self.assertIn("remember_91", out["recalled"][0])
        c = sqlite3.connect(self.path)
        n = c.execute("SELECT count(*) FROM rc_job").fetchone()[0]
        c.close()
        self.assertEqual(n, 1)


class F7Board(unittest.TestCase):
    def test_done_words_do_not_hint_and_commit_id_still_can(self):
        items = [{
            "item_id": "T83", "kind": "task", "status": "todo", "title": "48h ribbon",
            "body": "ribbon", "priority": 2,
        }]
        with mock.patch("app.board.items", return_value=items), mock.patch("app.board.stale", return_value=[]):
            out = board.relevant("t85", "T83 ribbon", "готово T83 ribbon done and fixed")
        self.assertIsNone(out.get("board_hint"))
        self.assertTrue(out.get("board"))
        hint = tp.looks_done_hint(
            [{"id": "T83", "title": "48h ribbon", "status": "todo", "created_at": 1000}],
            [{"hash": "abc1234", "subject": "unrelated work", "ts": 2000}],
        )
        self.assertEqual(hint, "")
        named = tp.looks_done_hint(
            [{"id": "T82", "title": "T73 v2 recall", "status": "todo", "created_at": 1000}],
            [{"hash": "c424c18", "subject": "T73 v2: search yourself first", "ts": 2000}],
        )
        self.assertIn("looks done, close?", named)

    def test_next_step_names_the_duty_and_skips_other_and_closed(self):
        cube = tp.next_step_for({"duties": ["CUBE DUTY publish the cube"], "facts": [1]})
        self.assertTrue(cube.startswith("close duty cube"))
        self.assertIn("cube_nothing", cube)
        other = tp.next_step_for({"duties": [{"id": "d0"}], "facts": [1]})
        self.assertNotIn("close duty other", other)
        after = tp.next_step_for(
            {"duties": ["CUBE DUTY publish", "L1: write l1_summary"], "facts": [1]},
            closed_duty={"cube": True},
        )
        self.assertTrue(after.startswith("close duty l1"))
        self.assertIn("l1_summary", after)
        voted = tp.next_step_for(
            {"duties": ["vote: cube_vote or vote_nothing"], "facts": [1]},
            closed_duty={"vote": True},
        )
        self.assertFalse(voted.startswith("close duty vote"))


class F8Schema(unittest.TestCase):
    def test_short_copy_and_recall_date_param(self):
        text = SHORT["memory_search"]
        self.assertIn("MSK", text)
        self.assertIn("YYYY-MM-DD", text)
        self.assertIn("2026-11-21", text)
        self.assertNotIn("yesterday", text.lower())
        later = SHORT["memory_recall_later"]
        self.assertIn("date=", later)
        self.assertIn("since", later)
        self.assertIn("until", later)
        self.assertNotIn("yesterday", later.lower())
        with open("/root/skv-core/mcp/mcp_skv.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Yesterday (MSK)", src)
        tree = ast.parse(src)
        args = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "memory_recall_later":
                args = [a.arg for a in node.args.args]
        self.assertIn("date", args)
        self.assertIn("since", args)
        self.assertIn("until", args)


class SecondLookPlan(unittest.TestCase):
    def test_plan_and_window_dates_do_not_ask_for_an_ev(self):
        w = tp.date_window("вчера")
        self.assertIsNotNone(w)
        draft = "Вчера я буду искать это через memory_search(since=%s, until=%s)." % (w["since"], w["until"])
        qs = second_look_q.questions(draft, "вчера", [])
        self.assertFalse(any(q["rule"] == "unlinked_past" for q in qs))
        self.assertFalse(any(q["rule"] == "unsourced_number" for q in qs))
        plain = "The window starts %s." % w["since"]
        qs2 = second_look_q.questions(plain, "вчера", [])
        self.assertFalse(any(q["rule"] == "unsourced_number" for q in qs2))
        real = second_look_q.questions("Yesterday you said the port is 8443.", "what was the port last time?", [])
        self.assertTrue(any(q["rule"] == "unlinked_past" for q in real))


if __name__ == "__main__":
    unittest.main()
