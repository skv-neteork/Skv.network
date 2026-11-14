"""T73: account purge also removes const_bind state (cb_scope, cb_metrics) of the deleted account and keeps others."""
import os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from app import account_purge as AP  # noqa: E402
from app import const_bind as CB  # noqa: E402

U = "purge.me@example.com"
OTHER = "keep.me@example.com"


class PurgeConstBind(unittest.TestCase):
    def test_const_bind_rows_removed(self):
        d = tempfile.mkdtemp()
        AP.BASE = d
        AP.SHARED_DB = os.path.join(d, "shared_master.db")
        AP.OAUTH_STATE_DB = os.path.join(d, "oauth.db")
        sc = sqlite3.connect(AP.SHARED_DB)
        sc.execute("create table users (email text, password_hash text)")
        sc.executemany("insert into users values (?, '')", [(U,), (OTHER,)])
        sc.commit(); sc.close()
        db = os.path.join(d, "const_bind.db")
        for u in (U, OTHER):
            CB.on_turn(u, "s1", msg_key="m1", db=db)
            CB.gate(u, "cube_create", "", db=db)
        rep = AP.purge(U, [], [U, OTHER])
        self.assertFalse(rep.get("errors"), rep)
        c = sqlite3.connect(db)
        for t in ("cb_scope", "cb_metrics"):
            self.assertEqual({r[0] for r in c.execute("select user from %s" % t)}, {OTHER}, t)


if __name__ == "__main__":
    unittest.main()
