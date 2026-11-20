"""T79: summary_due L2 (nl1) counts L1s since the last agent-written L2 only.

Extractive source='auto' (and server_fallback/llm) blocks must not hide an overdue agent L2.
The SQL here must match v7_memory.py summary_due (_l2to / _nl1).
Run: PYTHONPATH=src python3 -m unittest tests.test_t79_l2_due
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from app import duty_rules as DR  # noqa: E402


def l2to_nl1(conn, agent_only=True):
    # keep in sync with src/app/routers/v7_memory.py (summary_due)
    if agent_only:
        l2to = conn.execute("SELECT MAX(to_rowid) FROM summary_l2_blocks WHERE source IN ('agent')").fetchone()[0] or 0
    else:
        l2to = conn.execute("SELECT MAX(to_rowid) FROM summary_l2_blocks").fetchone()[0] or 0
    nl1 = conn.execute("SELECT COUNT(*) FROM summary_l1 WHERE to_rowid > ?", (l2to,)).fetchone()[0] or 0
    return int(l2to or 0), int(nl1 or 0)


class T79L2DueTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("CREATE TABLE summary_l1 (session_id TEXT, to_rowid INTEGER)")
        self.conn.execute("CREATE TABLE summary_l2_blocks (source TEXT, to_rowid INTEGER)")
        # 15 L1s at to_rowid 10,20,...,150
        self.conn.executemany("INSERT INTO summary_l1 VALUES (?,?)", [("s%d" % i, i * 10) for i in range(1, 16)])
        # agent L2 covers only the first 5 L1s
        self.conn.execute("INSERT INTO summary_l2_blocks VALUES ('agent', 50)")
        # extractive auto block covers everything — this used to zero nl1
        self.conn.execute("INSERT INTO summary_l2_blocks VALUES ('auto', 150)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_auto_block_does_not_zero_nl1(self):
        l2to, nl1 = l2to_nl1(self.conn, agent_only=True)
        self.assertEqual(l2to, 50)
        self.assertEqual(nl1, 10)  # to_rowid 60..150
        _, nl_all = l2to_nl1(self.conn, agent_only=False)
        self.assertEqual(nl_all, 0)
        _done, _dis, _ev, app = DR.signals({}, {"nl1": nl1})
        self.assertTrue(app["l2"])
        _done, _dis, _ev, app_old = DR.signals({}, {"nl1": nl_all})
        self.assertFalse(app_old["l2"])

    def test_fresh_agent_l2_is_not_due(self):
        self.conn.execute("INSERT INTO summary_l2_blocks VALUES ('agent', 150)")
        self.conn.commit()
        _, nl1 = l2to_nl1(self.conn, True)
        self.assertEqual(nl1, 0)
        self.assertFalse(DR.signals({}, {"nl1": nl1})[3]["l2"])

    def test_server_fallback_does_not_cover_agent_duty(self):
        self.conn.execute("INSERT INTO summary_l2_blocks VALUES ('server_fallback', 150)")
        self.conn.execute("INSERT INTO summary_l2_blocks VALUES ('llm', 150)")
        self.conn.commit()
        _, nl1 = l2to_nl1(self.conn, True)
        self.assertEqual(nl1, 10)
        self.assertTrue(DR.signals({}, {"nl1": nl1})[3]["l2"])


if __name__ == "__main__":
    unittest.main()
