"""New-user digest: reboot must not re-announce old accounts; one mail per day."""
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime
from importlib.machinery import SourceFileLoader

EV = SourceFileLoader("ev_digest", "/root/skv-core/ops/evolver.py").load_module()


def _users_db(path, rows):
    c = sqlite3.connect(path)
    c.execute("create table users (email text, confirmed int, created_at text)")
    c.executemany("insert into users values (?,?,?)", rows)
    c.commit()
    c.close()


class DigestRestartTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="skv-digest-")
        self.db = os.path.join(self.td, "users.db")
        self.state = os.path.join(self.td, "state")
        os.makedirs(self.state)
        _users_db(self.db, [
            ("old@example.invalid", 1, "2026-07-04 13:26:03"),
            ("also-old@example.invalid", 1, "2026-07-04 14:41:47"),
        ])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_empty_cursor_seeds_and_does_not_list_old_users(self):
        out = EV.new_users(db=self.db, state_dir=self.state)
        self.assertEqual(out, [])
        log = os.path.join(self.state, "skv_digest.txt")
        self.assertTrue(not os.path.exists(log) or open(log).read().strip() == "")
        with open(os.path.join(self.state, "skv_users.seen")) as f:
            seen = f.read().strip()
        self.assertEqual(seen, "2026-07-04 14:41:47")

    def test_reboot_empty_tmp_does_not_reannounce(self):
        EV.new_users(db=self.db, state_dir=self.state)
        c = sqlite3.connect(self.db)
        c.execute("insert into users values (?,?,?)", ("fresh@example.invalid", 1, "2026-11-13 10:00:00"))
        c.commit()
        c.close()
        first = EV.new_users(db=self.db, state_dir=self.state)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0][0], "fresh@example.invalid")
        # reboot: /tmp gone, durable cursor stays
        again = EV.new_users(db=self.db, state_dir=self.state)
        self.assertEqual(again, [])
        with open(os.path.join(self.state, "skv_digest.txt")) as f:
            log = f.read()
        self.assertEqual(log.count("new user"), 1)
        self.assertNotIn("old@example.invalid", log)
        self.assertNotIn("also-old@example.invalid", log)

    def test_1970_cursor_is_treated_as_unset(self):
        with open(os.path.join(self.state, "skv_users.seen"), "w") as f:
            f.write("1970-01-01\n")
        out = EV.new_users(db=self.db, state_dir=self.state)
        self.assertEqual(out, [])
        log = os.path.join(self.state, "skv_digest.txt")
        self.assertTrue(not os.path.exists(log) or "new user" not in open(log).read())

    def test_digest_once_per_day(self):
        mailed = []
        def fake_mail(subject, body):
            mailed.append(subject)
            return True
        kw = dict(mail_fn=fake_mail, state_dir=self.state, court_fn=lambda: "Court: 0",
                  health_fn=lambda: [], backup_fn=lambda: "ok")
        self.assertTrue(EV.send_digest(now=datetime(2026, 11, 13, 9, 15), **kw))
        self.assertFalse(EV.send_digest(now=datetime(2026, 11, 13, 10, 15), **kw))
        self.assertEqual(mailed, ["SKV day"])
        self.assertTrue(EV.send_digest(now=datetime(2026, 11, 14, 9, 15), **kw))
        self.assertEqual(len(mailed), 2)

    def test_digest_before_nine_is_held(self):
        mailed = []
        ok = EV.send_digest(now=datetime(2026, 11, 13, 3, 0), mail_fn=lambda s, b: mailed.append(s) or True,
                            state_dir=self.state, court_fn=lambda: "", health_fn=lambda: [], backup_fn=lambda: "ok")
        self.assertFalse(ok)
        self.assertEqual(mailed, [])

    def test_lock_serializes_two_senders(self):
        mailed = []
        def fake_mail(subject, body):
            time.sleep(0.05)
            mailed.append(1)
            return True
        kw = dict(mail_fn=fake_mail, state_dir=self.state, court_fn=lambda: "",
                  health_fn=lambda: [], backup_fn=lambda: "ok", now=datetime(2026, 11, 13, 9, 15))
        t1 = threading.Thread(target=lambda: EV.send_digest(**kw))
        t2 = threading.Thread(target=lambda: EV.send_digest(**kw))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(mailed), 1)


if __name__ == "__main__":
    unittest.main()
