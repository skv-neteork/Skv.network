import os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from app import account_purge as AP  # noqa: E402

U = "purge.me@example.com"
OTHER = "keep.me@example.com"


class PurgeSideTables(unittest.TestCase):
    def test_diet_duty_oauth_rows_removed(self):
        d = tempfile.mkdtemp()
        AP.BASE = d
        AP.SHARED_DB = os.path.join(d, "shared_master.db")
        AP.OAUTH_STATE_DB = os.path.join(d, "oauth.db")
        sc = sqlite3.connect(AP.SHARED_DB)
        sc.execute("create table users (email text, password_hash text)")
        sc.executemany("insert into users values (?, '')", [(U,), (OTHER,)])
        sc.commit(); sc.close()
        spec = {"compact_state_mcp.db": ["diet_sess", "diet_user"], "compact_state_rest.db": ["sl_last"],
                "duty_rules.db": ["dr_scope", "dr_duty"]}
        for db, tabs in spec.items():
            c = sqlite3.connect(os.path.join(d, db))
            for t in tabs:
                c.execute(f"create table {t} (user text, x text)")
                c.executemany(f"insert into {t} values (?, 'v')", [(U,), (OTHER,)])
            c.commit(); c.close()
        o = sqlite3.connect(AP.OAUTH_STATE_DB)
        o.execute("create table oauth_state (token text, user_id text)")
        o.executemany("insert into oauth_state values ('t', ?)", [(U,), (OTHER,)])
        o.commit(); o.close()
        rep = AP.purge(U, [], [U, OTHER])
        self.assertFalse(rep.get("errors"), rep)
        for db, tabs in spec.items():
            c = sqlite3.connect(os.path.join(d, db))
            for t in tabs:
                self.assertEqual(c.execute(f"select user from {t}").fetchall(), [(OTHER,)], t)
        o = sqlite3.connect(AP.OAUTH_STATE_DB)
        self.assertEqual(o.execute("select user_id from oauth_state").fetchall(), [(OTHER,)])


if __name__ == "__main__":
    unittest.main()
