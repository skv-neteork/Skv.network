"""T84 turn pack. PYTHONPATH=src python3 -m unittest tests.test_t84_turn_pack"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest import mock

from app import recall_later as rl
from app import turn_pack as tp
from app import turn_watch_rest as TW
from app.mcp_public_tools import SHORT


TODAY = date(2026, 11, 22)
CORE = "AUTHOR CUBE CORE (cube_3de96286fc73, v1):\n" + ("core textbook line. " * 200)


def _fact(ev, fact, time, layer=""):
    row = {"ev": ev, "time": time, "fact": fact}
    if layer:
        row["layer"] = layer
    return row


class Facts(unittest.TestCase):
    def test_dedupe_keeps_newest_ev(self):
        rows = tp.dedupe_facts([
            _fact("remember_1795346742474642566", "old wording", "2026-11-22 15:00"),
            _fact("remember_1795346742474642566", "new wording", "2026-11-22 15:01"),
            _fact("remember_other", "kept", "2026-11-01 10:00"),
        ])
        self.assertEqual([r["fact"] for r in rows], ["new wording", "kept"])

    def test_junk_criticals_dropped(self):
        rows = tp.select_facts([
            _fact("grokexp_acdfe644e3d5", "alice@example.com", "2026-10-01"),
            _fact("remember_1793548382301132209", "https://github.com/org/repo", "2026-10-02"),
            _fact("remember_surge", "see https://nssurge.example/conf", "2026-10-03"),
            _fact("remember_mask", "https://files.example/k?token=sk-****abcd", "2026-10-04"),
            _fact("remember_ok", "the board stays the source of task status", "2026-10-05"),
        ], message="where is the board status kept")
        ids = [r["ev"] for r in rows]
        self.assertNotIn("grokexp_acdfe644e3d5", ids)
        self.assertNotIn("remember_1793548382301132209", ids)
        self.assertNotIn("remember_surge", ids)
        self.assertNotIn("remember_mask", ids)
        self.assertIn("remember_ok", ids)

    def test_offtopic_critical_dropped(self):
        rows = tp.select_facts([
            _fact("remember_milk", "[critical] buy milk tomorrow morning", "2026-10-01", "critical"),
            _fact("remember_nx", "nginx keepalive is 75 seconds on the api", "2026-10-02"),
        ], message="what is the nginx keepalive")
        self.assertEqual([r["ev"] for r in rows], ["remember_nx"])

    def test_cutoff_default_and_compressed(self):
        facts = [
            _fact("remember_now", "nginx keepalive is 75 seconds", "2026-11-22 15:00"),
            _fact("remember_old", "nginx keepalive was raised last month", "2026-10-01"),
        ]
        recent = ["remember_now"]
        default = tp.select_facts(facts, message="nginx keepalive", recent_ids=recent)
        self.assertEqual([r["ev"] for r in default], ["remember_old"])
        back = tp.select_facts(facts, message="nginx keepalive", recent_ids=recent, compressed=True)
        self.assertIn("remember_now", [r["ev"] for r in back])
        stamped = tp.select_facts(
            facts, message="nginx keepalive", recent_ids=recent,
            compressed=True, compressed_at="2026-11-22 12:00",
        )
        self.assertEqual([r["ev"] for r in stamped], ["remember_old"])

    def test_novelty_skips_seen_unless_compressed(self):
        facts = [_fact("remember_old", "nginx keepalive was raised last month", "2026-10-01")]
        quiet = tp.select_facts(facts, message="nginx keepalive", seen_fact_ids=["remember_old"])
        self.assertEqual(quiet, [])
        again = tp.select_facts(
            facts, message="nginx keepalive", seen_fact_ids=["remember_old"], compressed=True,
        )
        self.assertEqual([r["ev"] for r in again], ["remember_old"])

    def test_yesterday_is_not_killed_by_the_word(self):
        facts = [
            _fact("remember_y", "shipped the desk map", "2026-11-21 09:00"),
            _fact("remember_old", "shipped the desk map", "2026-10-01"),
            _fact("remember_tail", "shipped the desk map", "2026-11-21 18:00"),
        ]
        rows = tp.select_facts(
            facts, message="yesterday", today=TODAY, recent_ids=["remember_tail"],
        )
        self.assertEqual([r["ev"] for r in rows], ["remember_y"])


class CriticalNest(unittest.TestCase):
    def test_critical_line_inside_l1_not_duplicated(self):
        records = {
            "l2": {"included": []},
            "l1": {"included": [{
                "id": "l1:1", "row_lo": 1, "row_hi": 9, "body": "stage covers remember_crit1",
            }]},
            "raw": {"included": []},
        }
        criticals = [{
            "id": "c1", "event_id": "remember_crit1", "title": "desk map ships with the turn",
            "hits": 2, "auto": True,
        }]
        records, placed = tp.nest_critical(records, criticals, {})
        lines = records["l1"]["included"][0].get("critical_lines") or []
        self.assertTrue(lines and lines[0].startswith("CRITICAL:"))
        self.assertIn("[ev:remember_crit1]", lines[0])
        self.assertIn("remember_crit1", placed)
        facts = tp.select_facts([
            _fact("remember_crit1", "[critical] desk map ships with the turn", "2026-10-01", "critical"),
            _fact("l1:1", "[l1] the desk map stage covers remember_crit1", "2026-10-01", "l1"),
        ], message="desk map")
        facts = [f for f in facts if str(f.get("ev")).split("::")[-1] not in placed or f.get("layer") != "critical"]
        self.assertFalse(any(f.get("layer") == "critical" for f in facts))
        self.assertTrue(any(f.get("layer") == "l1" for f in facts))


class Window(unittest.TestCase):
    def test_yesterday_and_week_and_explicit(self):
        y = tp.date_window("what happened yesterday", today=TODAY)
        self.assertEqual((y["since"], y["until"], y["rank"]), ("2026-11-21", "2026-11-21", False))
        w = tp.date_window("неделю назад", today=TODAY)
        self.assertEqual((w["since"], w["until"]), ("2026-11-12", "2026-11-18"))
        self.assertTrue(w["rank"])
        d = tp.date_window("решение 14.11.2026", today=TODAY)
        self.assertEqual((d["since"], d["until"], d["rank"]), ("2026-11-13", "2026-11-15", False))
        p = tp.date_window("позавчера", today=TODAY)
        self.assertEqual((p["since"], p["until"]), ("2026-11-20", "2026-11-20"))

    def test_hint_is_a_choice_on_the_turn(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            resp = {"facts": [_fact("remember_y", "[l1] shipped the desk", "2026-11-21", "l1")], "mode": "context"}
            tp.finish(resp, {"db": path, "user": "u", "session": "s", "message": "yesterday", "today": TODAY, "recent_ids": [], "seen_fact_ids": [], "commits": []})
            self.assertEqual(resp["window"]["since"], "2026-11-21")
            self.assertIn("memory_search since=2026-11-21 until=2026-11-21", resp["window_hint"])
            self.assertEqual(resp["window_map"][0]["layer"], "l1")
            self.assertTrue(resp["next_step"].startswith("search first") or resp["next_step"] == "answer")
        finally:
            os.remove(path)


class Descriptions(unittest.TestCase):
    def test_memory_search_and_recall_describe_the_window(self):
        text = SHORT["memory_search"]
        self.assertIn("YYYY-MM-DD", text)
        self.assertIn("since=", text)
        self.assertIn("2026-11-21", text)
        self.assertNotIn("yesterday", text.lower())  # the example is the dates, not the word in the query
        later = SHORT["memory_recall_later"]
        self.assertIn("since", later)
        self.assertIn("until", later)
        with open("/root/skv-core/mcp/mcp_skv.py", encoding="utf-8") as fh:
            guide = fh.read()
        self.assertIn("2026-11-21", guide)
        self.assertIn("Yesterday (MSK)", guide)


class Recall(unittest.TestCase):
    def test_submit_stores_since_until_exclude(self):
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
                        "t84-user", "where was the desk",
                        since="2026-11-21", until="2026-11-21", exclude_event="remember_self",
                    )
            c = sqlite3.connect(path)
            row = c.execute(
                "SELECT since, until, exclude_event FROM recall_later WHERE job_id=?", (jid,)
            ).fetchone()
            c.close()
            self.assertEqual(row, ("2026-11-21", "2026-11-21", "remember_self"))
        finally:
            os.remove(path)

    def test_pool_allow_drops_echo_outside_window(self):
        pool = rl._Pool()
        window = {"u::remember_in"}
        echo = {"u::remember_self"}

        def allow(e):
            if e in echo:
                return False
            return e in window

        pool.allow = allow
        pool.add(["u::remember_in", "u::remember_self", "u::remember_out"], 1.0, "q:q2s")
        self.assertEqual(pool.ranked(), ["u::remember_in"])

    def test_judge_keeps_direct_hit(self):
        # The stored event remember_1792879070250144752 is a 2026-10-24 note, not an
        # insect-legs sentence. This fixture pairs that id with an overlapping sentence
        # so a direct hit stays selected when the model says there is no event.
        q = "how many legs does an insect have"
        evidence = [
            {"ev": "remember_other", "text": "unrelated calendar note", "selected": False, "why": ""},
            {"ev": "remember_1792879070250144752", "text": "an insect has six legs on the thorax", "selected": False, "why": ""},
        ]
        evidence, missing = rl.judge_keep_direct(evidence, q, "missing: нет события")
        hit = evidence[1]
        self.assertTrue(hit["selected"])
        self.assertEqual(hit["why"], "direct match")
        self.assertEqual(missing, "")
        control = [{"ev": "remember_1792879070250144752", "text": "each object watches itself and sends signals to a shared center", "selected": False, "why": ""}]
        control, missing2 = rl.judge_keep_direct(control, q, "нет события")
        self.assertFalse(control[0]["selected"])
        self.assertIn("нет события", missing2)


class Duties(unittest.TestCase):
    def _ctx(self, path, **kw):
        base = {"db": path, "user": "u", "session": "s", "recent_ids": [], "seen_fact_ids": [], "commits": [], "today": TODAY}
        base.update(kw)
        return base

    def test_triggers_core_once_and_close_counter(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            vote = {"mode": "context", "facts": [_fact("remember_ok", "board status lives on the board", "2026-10-01")],
                    "duties": ["RULE vote: cube_vote or duty=vote_nothing"]}
            tp.finish(vote, self._ctx(path, message="board status", cube_applied=False))
            self.assertEqual(vote["duties"], [])
            l2 = {"mode": "context", "facts": [], "duties": ["L2 is due: send l2_summary"]}
            tp.finish(l2, self._ctx(path, message="hi", session="s2", l1_just_saved=True))
            self.assertEqual(l2["duties"], [])
            book = {"mode": "context", "facts": [], "duties": ["RULE profile: write the row"]}
            tp.finish(book, self._ctx(path, message="hi", session="s3"))
            self.assertEqual(book["duties"], [])
            first = {"verdict": "pass", "facts": [], "duties": ["CUBE DUTY: publish\n\n" + CORE]}
            tp.finish(first, self._ctx(path, message="ship the desk", session="cube"))
            self.assertIn("висит 1 хода", first["duties"][0])
            self.assertIn("cube_nothing", first["duties"][0])
            self.assertIn("AUTHOR CUBE CORE", first["duties"][0])
            second = {"verdict": "pass", "facts": [], "duties": ["CUBE DUTY: publish\n\n" + CORE]}
            tp.finish(second, self._ctx(path, message="ship the desk", session="cube"))
            self.assertNotIn("AUTHOR CUBE CORE", second["duties"][0])
            self.assertIn("cube cube_3de96286fc73", second["duties"][0])
            self.assertIn("висит 2 хода", second["duties"][0])
            self.assertTrue(first["next_step"].startswith("close duty"))
        finally:
            os.remove(path)

    def test_cube_nothing_not_refired_for_same_l1(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            tp.note_closed(path, "u", "remember_1229", "cube")
            resp = {"verdict": "pass", "facts": [], "duties": ["CUBE DUTY for remember_1229 publish the cube"]}
            tp.finish(resp, self._ctx(path, message="continue", trigger_id="remember_1229"))
            self.assertEqual(resp["duties"], [])
            other = {"verdict": "pass", "facts": [], "duties": ["CUBE DUTY for remember_9999 publish the cube"]}
            tp.finish(other, self._ctx(path, message="continue", session="s9", trigger_id="remember_9999"))
            self.assertTrue(other["duties"])
        finally:
            os.remove(path)

    def test_summary_due_not_duplicated_and_digest_hash(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            digest = "profile digest " + ("rule " * 40)
            raw = {
                "verdict": "pass",
                "facts": [],
                "summary_due": {"l1": "write the L1", "l1_pending": 3},
                "duties": [{"id": "l1_overdue", "do": "write the L1"}, {"id": "missed_turns", "do": "send recap"}],
                "profile_digest": digest,
                "search_language_rule": "search in English",
                "profile": [{"id": "p_x", "text": "short rule"}],
            }
            tp.finish(raw, self._ctx(path, message="status"))
            self.assertEqual(raw["summary_due"]["l1"], "write the L1")
            self.assertFalse(any(isinstance(d, dict) and d.get("id") == "l1_overdue" for d in raw["duties"]))
            self.assertTrue(any(isinstance(d, dict) and d.get("id") == "missed_turns" for d in raw["duties"]))
            self.assertIn("profile_digest", raw)
            again = {
                "verdict": "pass", "facts": [],
                "profile_digest": digest,
                "search_language_rule": "search in English",
                "profile": [{"id": "p_x", "text": "short rule"}],
                "duties": [],
            }
            tp.finish(again, self._ctx(path, message="status"))
            self.assertNotIn("profile_digest", again)
            self.assertNotIn("search_language_rule", again)
            self.assertNotIn("profile", again)
            self.assertNotIn("desk", again)
            self.assertNotIn("desk_delta", again)
        finally:
            os.remove(path)


class UsedAndBoardAndDesk(unittest.TestCase):
    def test_used_fact_ids_stored_when_present(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            resp = {"verdict": "pass", "event_id": "remember_turn", "facts": [], "mode": "context"}
            tp.finish(resp, {"db": path, "user": "u", "session": "s", "message": "hi", "recent_ids": [], "seen_fact_ids": [], "commits": [], "used_fact_ids": "remember_a, remember_b"})
            c = sqlite3.connect(path)
            ids = sorted(r[0] for r in c.execute("select fact_id from tp_used"))
            c.close()
            self.assertEqual(ids, ["remember_a", "remember_b"])
            bare = {"verdict": "pass", "facts": [], "mode": "context"}
            tp.finish(bare, {"db": path, "user": "u", "session": "s2", "message": "hi", "recent_ids": [], "seen_fact_ids": [], "commits": []})
            c = sqlite3.connect(path)
            n = c.execute("select count(*) from tp_used").fetchone()[0]
            c.close()
            self.assertEqual(n, 2)
        finally:
            os.remove(path)

    def test_looks_done_hint_does_not_close(self):
        hint = tp.looks_done_hint(
            [{"id": "T82", "title": "T73 v2 recall", "status": "todo"}],
            [{"hash": "c424c18", "subject": "T73 v2: search yourself first"}, {"hash": "c314553", "subject": "T73 v2: smoke account"}],
        )
        self.assertIn("looks done, close?", hint)
        self.assertIn("T82", hint)
        self.assertIn("c424c18", hint)
        self.assertIn("c314553", hint)
        self.assertEqual(tp.looks_done_hint([{"id": "T82", "title": "T73 v2", "status": "done"}], [{"hash": "c424c18", "subject": "T73 v2"}]), "")
        resp = {"mode": "context", "facts": [], "board": [{"id": "SmokeZ", "title": "quartz migration", "status": "todo"}], "board_hint": ""}
        # empty string is falsy, so a real match may fill it; this title does not match
        tp.finish(resp, {"db": "", "user": "u", "session": "s", "message": "quartz", "recent_ids": [], "seen_fact_ids": [], "commits": [{"hash": "abc1234", "subject": "unrelated"}]})
        self.assertFalse(resp.get("board_hint"))

    def test_desk_on_start_and_compression_then_delta_only(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            a = {"mode": "context", "facts": []}
            tp.finish(a, {"db": path, "user": "u", "session": "desk", "message": "hi", "recent_ids": [], "seen_fact_ids": [], "commits": []})
            self.assertGreaterEqual(len(a["desk"]), 9)
            joined = "\n".join(a["desk"])
            for needle in ("memory_search", "memory_recall_later", "board_act", "critical", "l1_summary", "cube_nothing", "profile", "vault", "drive_"):
                self.assertIn(needle, joined)
            b = {"mode": "context", "facts": []}
            tp.finish(b, {"db": path, "user": "u", "session": "desk", "message": "hi", "recent_ids": [], "seen_fact_ids": [], "commits": []})
            self.assertNotIn("desk", b)
            self.assertNotIn("desk_delta", b)
            c = {"mode": "context", "facts": []}
            tp.finish(c, {"db": path, "user": "u", "session": "desk", "message": "hi", "recent_ids": [], "seen_fact_ids": [], "commits": [], "compressed": True})
            self.assertIn("desk", c)
            self.assertTrue(c["next_step"])
        finally:
            os.remove(path)


class SystemSkip(unittest.TestCase):
    def test_system_recap_is_not_a_missed_turn(self):
        self.assertEqual(tp.system_skip_refs([{"ref": "t1759u", "skip": "system"}]), [1759])
        self.assertEqual(tp.system_skip_refs([{"ref": "t12u", "user": "q", "answer": "a"}]), [])
        tmp = tempfile.mkdtemp()
        old = TW.DB
        TW.DB = os.path.join(tmp, "w.db")
        try:
            k = "acct"
            TW.cover(k, [10])
            # previous saved ref is 10 only after a check that saves; seed it
            c = sqlite3.connect(TW.DB)
            c.execute("insert or replace into rtw_ref values(?,?,?)", (k, 10, 1))
            c.commit()
            c.close()
            TW.cover(k, tp.system_skip_refs([{"ref": "t1759u", "skip": "system"}]))
            missing = TW.check(k, (1760, 1760), True)
            self.assertNotIn(1759, missing)
            self.assertIn(1758, missing)
        finally:
            TW.DB = old


class Measure(unittest.TestCase):
    def test_ten_fixtures_shrink_and_ten_remembers(self):
        report = run_measure()
        self.assertLess(report["tokens_after"], report["tokens_before"])
        self.assertEqual(len(report["remember"]), 10)
        self.assertTrue(all(row["covered"] for row in report["remember"]))
        self.assertIn("2026-11-21", json.dumps(report["remember"]))
        open("/tmp/t84_measure.json", "w").write(json.dumps(report, ensure_ascii=False, indent=2))


def run_measure():
    """Frozen fixtures. Tokens are json-length//4. No live memory."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    samples = []

    def one(name, resp, ctx, prime=None):
        # Desk is once per session. Prime it (and, for the cube duty, the full CORE)
        # so the measured turn is the steady state: B+E+F, not nine copies of the map.
        if prime:
            tp.finish(prime[0], dict(prime[1], db=path))
        else:
            tp.finish(
                {"mode": "context", "facts": []},
                {"db": path, "user": "m", "session": ctx.get("session"), "message": "hi",
                 "recent_ids": [], "seen_fact_ids": [], "commits": [], "today": TODAY},
            )
        before = tp.tok(resp)
        packed = json.loads(json.dumps(resp))
        ctx = dict(ctx, db=path, user="m", commits=[], today=TODAY)
        ctx.setdefault("recent_ids", [])
        ctx.setdefault("seen_fact_ids", [])
        tp.finish(packed, ctx)
        samples.append({"name": name, "before": before, "after": tp.tok(packed), "next_step": packed.get("next_step"), "facts": len(packed.get("facts") or [])})

    cube_payload = {"verdict": "pass", "facts": [], "duties": ["CUBE DUTY\n\n" + CORE]}
    one("cube_duty", json.loads(json.dumps(cube_payload)), {"session": "c", "message": "ship the desk"},
        prime=(json.loads(json.dumps(cube_payload)), {"session": "c", "message": "ship the desk", "user": "m", "recent_ids": [], "seen_fact_ids": [], "commits": [], "today": TODAY}))
    one("l1_due", {
        "verdict": "pass", "facts": [],
        "summary_due": {"l1": "write the L1 now", "l1_pending": 20},
        "duties": [{"id": "summary_due", "do": "write the L1 now"}, {"id": "l1_overdue", "do": "write the L1 now"}],
    }, {"session": "l1", "message": "status of the task"})
    one("yesterday", {
        "mode": "context",
        "facts": [
            _fact("grokexp_acdfe644e3d5", "a@b.com", "2026-11-21"),
            _fact("remember_y", "[l1] shipped the window", "2026-11-21", "l1"),
        ],
    }, {"session": "y", "message": "yesterday"})
    one("followup_zero", {
        "mode": "context",
        "facts": [_fact("remember_old", "nginx keepalive was raised last month", "2026-10-01")],
    }, {"session": "f", "message": "nginx keepalive", "recent_ids": ["remember_old"]})
    one("decision", {
        "mode": "context",
        "facts": [
            _fact("remember_d", "[decision] keep the board as the task list", "2026-09-01", "decision"),
            _fact("remember_x", "unrelated recipe for soup", "2026-09-02"),
        ],
    }, {"session": "d", "message": "what was the board decision"})
    digest = "digest " + ("row " * 80)
    primed = {"verdict": "pass", "facts": [], "profile_digest": digest, "search_language_rule": "en", "profile": [{"id": "p", "text": "rule"}]}
    one("digest_again", json.loads(json.dumps(primed)), {"session": "g", "message": "next"}, prime=(json.loads(json.dumps(primed)), {"session": "g", "message": "next", "user": "m", "recent_ids": [], "seen_fact_ids": [], "commits": [], "today": TODAY}))
    one("vote_noise", {"mode": "context", "facts": [], "duties": ["RULE vote: cube_vote or duty=vote_nothing"]}, {"session": "v", "message": "hello", "cube_applied": False})
    one("l2_after_l1", {"mode": "context", "facts": [], "duties": ["L2 is due: send l2_summary"]}, {"session": "l2", "message": "saved", "l1_just_saved": True})
    one("textbook", {"mode": "context", "facts": [], "duties": ["RULE profile: write a lasting row"]}, {"session": "t", "message": "hello"})
    one("week_lookup", {
        "mode": "context",
        "facts": [_fact("remember_w", "[l2] deploy window", "2026-11-15", "l2"), _fact("remember_far", "[l2] old", "2026-01-01", "l2")],
    }, {"session": "w", "message": "a week ago"})

    remembers = []

    def remember(q, facts, recent=None):
        resp = {"mode": "context", "facts": facts}
        tp.finish(resp, {"db": path, "user": "m", "session": "r" + str(len(remembers)), "message": q, "today": TODAY, "recent_ids": recent or [], "seen_fact_ids": [], "commits": []})
        evs = [f.get("ev") for f in resp.get("facts") or []]
        # A follow-up whose only hit is inside the current session is covered by returning nothing.
        cutoff_ok = bool(recent) and not evs
        remembers.append({
            "question": q,
            "window": bool(resp.get("window")),
            "since": (resp.get("window") or {}).get("since"),
            "until": (resp.get("window") or {}).get("until"),
            "map": bool(resp.get("window_map")),
            "hint": bool(resp.get("window_hint")),
            "facts": evs,
            "next_step": resp.get("next_step"),
            "covered": bool(resp.get("window") or evs or resp.get("next_step") == "search first" or cutoff_ok),
        })

    remember("yesterday", [_fact("remember_y", "[l1] shipped", "2026-11-21", "l1")])
    remember("a week ago", [_fact("remember_w", "[l2] deploy", "2026-11-15", "l2")])
    remember("позавчера", [_fact("remember_p", "note about the desk", "2026-11-20")])
    remember("what did we decide on 14.11.2026", [_fact("remember_e", "decision on the date window", "2026-11-14")])
    remember("remember the board decision", [_fact("remember_d", "board decision stays on the board", "2026-09-01")])
    remember("remember the email", [_fact("grokexp_acdfe644e3d5", "alice@example.com", "2026-10-01"), _fact("remember_ok", "the contact lives in the vault", "2026-10-01")])
    remember("remember the github link", [_fact("remember_1793548382301132209", "https://github.com/org/repo", "2026-10-02")])
    remember("what did we decide yesterday about the board", [_fact("remember_b", "[l1] board decision yesterday", "2026-11-21", "l1")])
    remember("nginx keepalive follow up", [_fact("remember_old", "nginx keepalive was raised last month", "2026-10-01")], recent=["remember_old"])
    # deferred search keeps a direct hit on the next turn
    evidence = [{"ev": "remember_1792879070250144752", "text": "an insect has six legs on the thorax", "selected": False}]
    evidence, _miss = rl.judge_keep_direct(evidence, "how many legs does an insect have", "нет события")
    remembers.append({
        "question": "how many legs does an insect have",
        "window": False, "since": None, "until": None, "map": False, "hint": False,
        "facts": [],
        "recall_selected": [e["ev"] for e in evidence if e.get("selected")],
        "next_step": "search first",
        "covered": any(e.get("selected") for e in evidence),
    })
    try:
        os.remove(path)
    except Exception:
        pass
    return {
        "tokens_before": sum(s["before"] for s in samples),
        "tokens_after": sum(s["after"] for s in samples),
        "samples": samples,
        "remember": remembers,
    }


if __name__ == "__main__":
    unittest.main()
