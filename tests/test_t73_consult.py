"""T73: consult rows stuck as 'running' become status='error' (interrupted) when fetched; safe_restart.sh waits for running consults."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, "/root/skv-core/src")
from app import consult_pool as CP  # noqa: E402


class StuckConsultTests(unittest.TestCase):
    def setUp(self):
        self.p = tempfile.mktemp(suffix=".db")
        self._db = CP._db
        CP._db = self.mk
        c = self.mk("u")
        c.close()

    def tearDown(self):
        CP._db = self._db
        CP._LIVE.clear()
        if os.path.exists(self.p):
            os.remove(self.p)

    def mk(self, user_id):
        c = sqlite3.connect(self.p, timeout=10)
        c.execute("CREATE TABLE IF NOT EXISTS consult_pool (id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, tried TEXT, failed TEXT, claude TEXT, gpt TEXT, "
                  "status TEXT, chosen TEXT, as_kind TEXT, created_at TEXT, usage_json TEXT, saved_event TEXT, mode TEXT, reviews_json TEXT, synthesis TEXT, context TEXT)")
        return c

    def add(self, age_s, status="running"):
        c = self.mk("u")
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - age_s))
        cur = c.execute("INSERT INTO consult_pool (task, claude, gpt, status, created_at, mode) VALUES ('t','','',?,?,'deep')", (status, ts))
        c.commit(); cid = cur.lastrowid; c.close()
        return cid

    def status(self, cid):
        c = self.mk("u")
        try:
            return c.execute("SELECT status FROM consult_pool WHERE id=?", (cid,)).fetchone()[0]
        finally:
            c.close()

    def test_older_than_15_min_becomes_error_and_stays_error(self):
        cid = self.add(1000)
        CP._LIVE.add(cid)     # even a "live" id is closed after 15 min
        r = CP.result("u", cid)
        self.assertEqual(r["status"], "error")
        self.assertIn("interrupted (server restart)", r["reason"])
        self.assertEqual(self.status(cid), "error")
        r2 = CP.result("u", cid)
        self.assertEqual(r2["status"], "error")
        self.assertIn("interrupted", r2["reason"])

    def test_orphan_after_restart_is_closed_early_live_one_keeps_running(self):
        dead, live, fresh = self.add(300), self.add(300), self.add(20)
        CP._LIVE.add(live)
        self.assertEqual(CP.result("u", live)["status"], "running")
        self.assertEqual(CP.result("u", fresh)["status"], "running")      # too young to judge
        self.assertEqual(CP.result("u", dead)["status"], "error")         # no worker thread in this process
        self.assertEqual(self.status(live), "running")

    def test_accept_on_interrupted_gives_error_not_running(self):
        cid = self.add(2000)
        r = CP.accept("u", cid, "synthesis")
        self.assertEqual(r["status"], "error")
        self.assertIn("interrupted", r["reason"])
        self.assertEqual(self.status(cid), "error")

    def test_finished_rows_are_untouched(self):
        cid = self.add(5000, status="open")
        c = self.mk("u"); c.execute("UPDATE consult_pool SET claude='a', gpt='b', usage_json='{}', reviews_json='{}', synthesis='s' WHERE id=?", (cid,)); c.commit(); c.close()
        r = CP.result("u", cid)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(self.status(cid), "open")


class SafeRestartScriptTests(unittest.TestCase):
    def test_script_waits_for_consults_and_is_valid_bash(self):
        p = "/root/skv-core/ops/safe_restart.sh"
        self.assertEqual(subprocess.run(["bash", "-n", p]).returncode, 0)
        with open(p) as fh:
            s = fh.read()
        self.assertIn("consult_busy", s)
        self.assertIn("CONSULT_MAX_WAIT", s)
        self.assertIn("status='running'", s)
        self.assertIn("no .db suffix", s)   # account DBs are files without an extension
        self.assertIn("while log_busy || jobs_busy || consult_wait", s)

    def test_worker_is_tracked_in_inflight(self):
        with open("/root/skv-core/src/app/consult_pool.py") as fh:
            src = fh.read()
        self.assertIn('_inf.track("consult")', src)


if __name__ == "__main__":
    unittest.main()
