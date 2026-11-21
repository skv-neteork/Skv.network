"""Hook event bus, signal-log pointers, and exposure/application/outcome weights."""
import os
import sqlite3
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from app import cube_weights, hook_bus, signal_log
from app.cube_dedup import confirm, rank_score
from app.cube_suggest import trigger_match
from app.cubes_v2 import NEGATIVE_TO_COURT, ensure as cv2_ensure, negative_clients, record_outcome


ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIVE_EVENTS = (
    "session_start", "before_reply", "after_reply", "task_end",
    "secret_in_text", "task_matches_skill_cube", "user_says_install",
    "user_wants_new_cube",
)
PLANNED = (
    "on_rework", "on_error", "on_task_start", "on_create", "on_install",
    "user_wants_cube_review", "cubes_used", "before_publish_big",
)


def _mem():
    return sqlite3.connect(":memory:")


def _cube(conn, cube_id="cube_z", author="author-account", rank=1.0):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cubes_new (
            cube_id TEXT PRIMARY KEY, created_by TEXT, cube_version TEXT,
            rank_v0 REAL, status TEXT, trust TEXT, confirms INTEGER,
            rating REAL, upvotes INT, downvotes INT, votes_json TEXT)"""
    )
    conn.execute(
        "INSERT INTO cubes_new (cube_id, created_by, cube_version, rank_v0, status, votes_json) VALUES (?,?,?,?,?,?)",
        (cube_id, author, "1", rank, "community", "[]"),
    )


class BusTests(unittest.TestCase):
    def test_live_name_fires_do_text_without_a_model_call(self):
        hooks = [{"when": "session_start", "do": "read the constitution"}]
        with patch("urllib.request.urlopen") as urlopen:
            hits = hook_bus.fire("session_start", hooks, "cube_a")
            urlopen.assert_not_called()
        self.assertEqual(hits[0]["do"], "read the constitution")
        self.assertEqual(hits[0]["event"], "session_start")
        self.assertNotIn("httpx", Path(ROOT, "src/app/hook_bus.py").read_text(encoding="utf-8"))

    def test_each_planned_event_fires_from_a_fixture(self):
        for name in PLANNED:
            hooks = [{"when": name, "do": "do-" + name}]
            hits = hook_bus.fire(name, hooks, "cube_p")
            self.assertEqual([h["do"] for h in hits], ["do-" + name], name)

    def test_on_rework_only_after_a_material_write(self):
        hooks = [{"when": "on_rework", "do": "review the write"}]
        self.assertEqual(
            hook_bus.fire_rework(hooks, write=True, read=False, after_checkpoint=True, first_create=False, same_burst_retry=False)[0]["do"],
            "review the write",
        )
        self.assertEqual(
            hook_bus.fire_rework(hooks, write=True, read=False, after_checkpoint=False, first_create=True, same_burst_retry=False)[0]["do"],
            "review the write",
        )
        self.assertEqual(hook_bus.fire_rework(hooks, write=True, read=True, after_checkpoint=True, first_create=False, same_burst_retry=False), [])
        self.assertEqual(hook_bus.fire_rework(hooks, write=True, read=False, after_checkpoint=True, first_create=False, same_burst_retry=True), [])
        self.assertEqual(hook_bus.fire_rework(hooks, write=False, read=False, after_checkpoint=True, first_create=True, same_burst_retry=False), [])
        self.assertEqual(hook_bus.fire_rework(hooks, write=True, read=False, after_checkpoint=False, first_create=False, same_burst_retry=False), [])

    def test_task_start_and_install_are_not_session_start(self):
        hooks = [
            {"when": "session_start", "do": "connect"},
            {"when": "on_task_start", "do": "task"},
            {"when": "on_install", "do": "install"},
        ]
        self.assertEqual([h["do"] for h in hook_bus.fire("on_task_start", hooks)], ["task"])
        self.assertEqual([h["do"] for h in hook_bus.fire("on_install", hooks)], ["install"])
        self.assertEqual([h["do"] for h in hook_bus.fire("session_start", hooks)], ["connect"])

    def test_token_when_still_matches_and_a_phrase_does_not(self):
        hooks = [{"when": "session_start or chain_switch", "do": "memory"}]
        self.assertEqual(hook_bus.fire("session_start", hooks)[0]["do"], "memory")
        self.assertEqual(hook_bus.fire("on_install", hooks), [])
        phrase = [{"when": "user about to see the answer", "do": "look"}]
        self.assertEqual(hook_bus.fire("before_reply", phrase), [])

    def test_short_event_name_is_dispatched_by_the_bus_not_the_suggest_path(self):
        row = {"cube_id": "cube_s", "whens": [{"when": "on_install", "do": "offer the skill"}]}
        self.assertEqual(trigger_match([row], "please on_install this"), [])
        hits = hook_bus.fire("on_install", [{"when": "on_install", "do": "offer the skill"}], "cube_s")
        self.assertEqual(hits[0]["do"], "offer the skill")

    def test_cubes_used_session_field_does_not_update_rank(self):
        conn = _mem()
        _cube(conn)
        before = conn.execute("SELECT rank_v0 FROM cubes_new").fetchone()[0]
        field = hook_bus.session_field_cubes_used(["cube_z"])
        self.assertEqual(field["fired"], [])
        self.assertFalse(field["rank_updated"])
        self.assertEqual(conn.execute("SELECT rank_v0 FROM cubes_new").fetchone()[0], before)
        src = Path(ROOT, "src/app/routers/personal_memory.py").read_text(encoding="utf-8")
        self.assertIn("cubes_used: list = []", src)
        fired = hook_bus.fire("cubes_used", [{"when": "cubes_used", "do": "note the apply"}])
        self.assertEqual(fired[0]["do"], "note the apply")
        self.assertEqual(conn.execute("SELECT rank_v0 FROM cubes_new").fetchone()[0], before)

    def test_before_publish_big_is_a_gate(self):
        hits = hook_bus.fire("before_publish_big", [{"when": "before_publish_big", "do": "ask for a paid review"}])
        self.assertTrue(hits[0]["gate"])
        self.assertFalse(hits[0]["published"])

    def test_installed_pack_returns_capped_cues(self):
        pack = [{"cube_id": "cube_a", "hooks": [{"when": "after_reply", "do": "x" * 400}]}]
        cues = hook_bus.cues_from_pack(pack, ["after_reply"])
        self.assertEqual(len(cues), 1)
        self.assertLessEqual(len(cues[0]["do"]), 160)

    def test_live_names_are_unchanged(self):
        self.assertEqual(hook_bus.LIVE, LIVE_EVENTS)


class SignalTests(unittest.TestCase):
    def test_append_writes_a_pointer_and_makes_no_http_call(self):
        body = Path(ROOT, "src/app/signal_log.py").read_text(encoding="utf-8")
        self.assertNotIn("httpx", body)
        self.assertNotIn("consultation", body)
        self.assertNotIn("urlopen", body)
        conn = _mem()
        with patch("urllib.request.urlopen") as urlopen:
            row = signal_log.append_pointer(conn, "capture", ref="ptr-1", cube_id="cube_z", extra={"event": "after_reply"})
            urlopen.assert_not_called()
        self.assertFalse(row["model_called"])
        kind, ref, cube_id, extra = conn.execute("SELECT kind, ref, cube_id, extra_json FROM signal_log").fetchone()
        self.assertEqual((kind, ref, cube_id), ("capture", "ptr-1", "cube_z"))
        self.assertIn("after_reply", extra)
        self.assertNotIn("summary", extra)


class WeightTests(unittest.TestCase):
    def test_three_traces_join_decay_lowers_rank_and_a_use_does_not_vote(self):
        conn = _mem()
        _cube(conn, rank=0.0)
        conn.execute("CREATE TABLE cube_confirmations (cube_id TEXT, version TEXT, account_id TEXT)")
        conn.execute("CREATE TABLE cube_outcomes (cube_id TEXT, user_id TEXT, outcome TEXT)")
        t0 = 1_800_000_000.0
        exposure = cube_weights.record(conn, "cube_z", "exposure", account_id="reader", ref="shown", ts=t0)
        application = cube_weights.record(conn, "cube_z", "application", account_id="reader", ref="applied", ts=t0)
        outcome = cube_weights.record(conn, "cube_z", "outcome", account_id="reader", value=1.0, ref="ok", ts=t0)
        self.assertTrue(exposure["ok"] and application["ok"] and outcome["ok"])
        self.assertFalse(exposure["voted"] or exposure["confirmed"])
        self.assertEqual(cube_weights.count_kind(conn, "cube_z", "exposure"), 1)
        self.assertEqual(cube_weights.count_kind(conn, "cube_z", "application"), 1)
        self.assertEqual(cube_weights.count_kind(conn, "cube_z", "outcome"), 1)
        fresh = conn.execute("SELECT rank_v0 FROM cubes_new WHERE cube_id='cube_z'").fetchone()[0]
        self.assertGreater(fresh, 1.0)
        conn.execute("UPDATE cube_weight_trace SET ts=?", (t0 - 180 * 86400,))
        aged = cube_weights.recompute(conn, "cube_z", now=t0)
        self.assertLess(aged, fresh)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cubes_new").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cube_confirmations").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cube_outcomes").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT votes_json FROM cubes_new").fetchone()[0], "[]")


class ExistingPathTests(unittest.TestCase):
    def test_confirm_excludes_the_author_and_is_one_per_account(self):
        conn = _mem()
        _cube(conn, author="author-account")
        author = confirm(conn, "cube_z", "author-account", "ok", "ran the steps")
        self.assertFalse(author["counted"])
        self.assertEqual(author["reason"], "author")
        first = confirm(conn, "cube_z", "reader-account", "ok", "ran the steps")
        self.assertEqual(first["vote"], "recorded")
        again = confirm(conn, "cube_z", "reader-account", "ok", "ran the steps again")
        self.assertIn("already confirmed", again.get("note") or "")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cubes_new").fetchone()[0], 1)

    def test_decay_lowers_rank_and_does_not_delete(self):
        recent = datetime(2026, 1, 1)
        old = recent - timedelta(days=180)
        self.assertLess(rank_score(1, 1, 1, old, now=recent), rank_score(1, 1, 1, recent, now=recent))
        conn = _mem()
        _cube(conn)
        confirm(conn, "cube_z", "reader-account", "ok", "ran the steps")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cubes_new").fetchone()[0], 1)

    def test_negative_vote_needs_a_reason_and_three_clients_queue_without_delete(self):
        conn = _mem()
        with self.assertRaises(ValueError):
            record_outcome(conn, "cube_z", "c1", False, "")
        _cube(conn, author="author-account")
        cv2_ensure(conn)
        for i, uid in enumerate(("c1", "c2", "c3")):
            record_outcome(conn, "cube_z", uid, False, "wrong step", ip="203.0.113.%d" % (i + 1))
        n, _reasons = negative_clients(conn, "cube_z")
        self.assertGreaterEqual(n, NEGATIVE_TO_COURT)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM court_queue WHERE cube_id='cube_z'").fetchone())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cubes_new WHERE cube_id='cube_z'").fetchone()[0], 1)
        router = Path(ROOT, "src/app/routers/v7_cubes.py").read_text(encoding="utf-8")
        self.assertIn('status = "disputed"', router)


class FollowTests(unittest.TestCase):
    def test_roots_follow_to_the_same_live_author_cube(self):
        path = "/data/skv/metadata_store/shared_master.db"
        if not os.path.exists(path):
            self.skipTest("shared db missing")
        from app.chain_skills import newest_version
        from app.cube_harvest import latest_cube_id
        author = latest_cube_id("cube_3de96286fc73")
        meta = newest_version("cube_688c0ebbb3be")
        self.assertEqual(author, meta)
        self.assertNotEqual(author, "cube_3de96286fc73")
        self.assertNotEqual(meta, "cube_688c0ebbb3be")
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
        try:
            status = conn.execute("SELECT coalesce(status,'') FROM cubes_new WHERE cube_id=?", (author,)).fetchone()
            self.assertIsNotNone(status)
            self.assertNotEqual(status[0], "superseded")
            known = "cube_8ca30802c689"
            if author != known:
                seen = set()
                cid = known
                reached = False
                for _ in range(20):
                    if cid in seen:
                        break
                    seen.add(cid)
                    if cid == author:
                        reached = True
                        break
                    row = conn.execute("SELECT coalesce(status,''), links_json FROM cubes_new WHERE cube_id=?", (cid,)).fetchone()
                    if not row or row[0] != "superseded":
                        break
                    import json
                    cid = (json.loads(row[1] or "{}") or {}).get("superseded_by") or ""
                self.assertTrue(reached)
            else:
                self.assertEqual(author, known)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
