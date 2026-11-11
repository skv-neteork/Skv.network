"""Collision-safe account name mapping (2026-11-11: purge of "bench-locomo" deleted the db of "benchlocomo").
Run: PYTHONPATH=src python3 -m unittest tests.test_account_ids"""
import os, sqlite3, tempfile, unittest

from app import account_ids as AI
from app import account_purge as AP

A = "bench-locomo@bench.skv.invalid"      # primary name keeps the hyphen
B = "benchlocomo@bench.skv.invalid"       # equals A's old hyphen-less variant


class Names(unittest.TestCase):
    def test_primary_names_differ_but_legacy_variant_hit_the_other_account(self):
        self.assertNotEqual(AI.account_name(A), AI.account_name(B))
        self.assertIn(AI.account_name(B), AI.legacy_names(A))                 # the bug: this variant was purged
        self.assertEqual(AI.conflicting_accounts(A, [A, B]), [])
        self.assertIn(AI.account_name(B), AI.protected_names(A, [A, B]))

    def test_same_primary_name_is_a_conflict(self):
        x, y = "a.b@x.io", "ab@x.io"
        self.assertEqual(AI.account_name(x), AI.account_name(y))
        self.assertEqual(AI.conflicting_accounts(x, [x, y]), [y])
        self.assertEqual(AI.conflicting_accounts("plus+tag@x.io", ["plustag@x.io"]), ["plustag@x.io"])

    def test_collisions_report(self):
        g = AI.collisions([A, B, "a.b@x.io", "ab@x.io", "solo@x.io"])
        self.assertIn(sorted([A, B]), g); self.assertIn(["a.b@x.io", "ab@x.io"], g)
        self.assertFalse(any("solo@x.io" in x for x in g))

    def test_name_variants_skip_protected(self):
        v = AP.name_variants(A, protected={AI.account_name(B)})
        self.assertNotIn(AI.account_name(B), v); self.assertIn(AI.account_name(A), v)

    def test_all_mappers_agree(self):
        mods = []
        for m, f in (("app.account_memory", "account_db_name"), ("app.semantic", "account_name"), ("app.memory_v2", "account_name")):
            try:
                mods.append(getattr(__import__(m, fromlist=[f]), f))
            except Exception:
                pass
        for u in (A, B, "Mixed.Case+tag@Example.COM", "a_b-c@x.io"):
            for f in mods:
                self.assertEqual(f(u), AI.account_name(u))


class PurgeFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = (AP.BASE, AP.SHARED_DB, AP.HNSW_DIRS)
        AP.BASE = self.d; AP.SHARED_DB = os.path.join(self.d, "shared_master.db"); AP.HNSW_DIRS = ()
        sqlite3.connect(AP.SHARED_DB).close()

    def tearDown(self):
        AP.BASE, AP.SHARED_DB, AP.HNSW_DIRS = self.old

    def touch(self, email, suffix=".db"):
        p = os.path.join(self.d, AI.account_name(email) + suffix); open(p, "w").write("x"); return p

    def test_purge_of_hyphen_account_keeps_the_other_account(self):
        pa, pb = self.touch(A), self.touch(B)
        pb_chunk = os.path.join(self.d, AI.account_name(B) + "__l1.db"); open(pb_chunk, "w").write("x")
        rep = AP.purge(A, [], registered=[B])
        self.assertFalse(os.path.exists(pa))
        self.assertTrue(os.path.exists(pb)); self.assertTrue(os.path.exists(pb_chunk))
        self.assertEqual(rep.get("skipped_other_account_names"), 1)

    def test_purge_refused_when_primary_name_is_shared(self):
        p = self.touch("ab@x.io")
        with self.assertRaises(AP.NameCollision):
            AP.purge("a.b@x.io", [], registered=["ab@x.io"])
        self.assertTrue(os.path.exists(p))

    def test_plain_purge_still_removes_everything_of_the_account(self):
        p, w = self.touch("solo@x.io"), self.touch("solo@x.io", ".db-wal")
        rep = AP.purge("solo@x.io", [], registered=[B])
        self.assertFalse(os.path.exists(p)); self.assertFalse(os.path.exists(w)); self.assertGreaterEqual(rep["files"], 2)


class Lines(unittest.TestCase):
    def test_memory_lines_uses_the_canonical_name(self):
        try:
            from app import memory_lines as ML
        except Exception:
            self.skipTest("memory_lines needs the app environment")
        self.assertTrue(ML.db_file(A).endswith(AI.account_name(A) + ".db"))
        self.assertNotEqual(ML.db_file(A), ML.db_file(B))


if __name__ == "__main__":
    unittest.main()
