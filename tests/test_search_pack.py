"""B10 search pack: line filter before top-k, mini-lens shape, RU routing, dates.
Run: PYTHONPATH=src python3 -m unittest tests.test_search_pack
Container: docker exec -i -w /app -e PYTHONPATH=/app skv_api python -m unittest tests.test_search_pack
"""
import os, sqlite3, tempfile, unittest
from datetime import datetime

from app import q2s as Q
from app import search_line as LN
from app import search_pack as SP
from app import search_text as ST
from app import memory_lines as ML


class Qtype(unittest.TestCase):
    def test_en_and_ru_map_to_same_routes(self):
        self.assertEqual(Q.qtype("Who is Caroline?"), "who")
        self.assertEqual(Q.qtype("Кто такая Caroline?"), "who")
        self.assertEqual(Q.qtype("When did they meet?"), "when")
        self.assertEqual(Q.qtype("Когда они встретились?"), "when")
        self.assertEqual(Q.qtype("What do Melanie's kids like?"), "what")
        self.assertEqual(Q.qtype("Что нравится детям Мелани?"), "what")
        self.assertEqual(Q.qtype("How many dogs?"), "how_many")
        self.assertEqual(Q.qtype("Сколько собак?"), "how_many")
        self.assertEqual(Q.qtype("Where do they live?"), "where")
        self.assertEqual(Q.qtype("Где они живут?"), "where")
        self.assertEqual(Q.qtype("Why did she leave?"), "why")
        self.assertEqual(Q.qtype("Почему она ушла?"), "why")
        self.assertEqual(Q.qtype("Melanie's kids loved the dinosaur exhibit"), None)

    def test_ru_q2s_forms_are_statements(self):
        f = Q.forms("Что нравится детям Мелани?")
        self.assertTrue(f)
        self.assertTrue(any("Мелани" in x or "Melanie" in x for x in f) or any("нравит" in x.lower() for x in f), f)
        self.assertFalse(any(x.endswith("?") for x in f), f)
        self.assertEqual(Q.plan("Что нравится детям Мелани?")[0], "rules")


class Dates(unittest.TestCase):
    def test_yesterday_is_hard(self):
        now = datetime(2026, 11, 14, 12, 0, 0)
        w = SP.resolve_time("who joined yesterday", now=now)
        self.assertTrue(w["hard"])
        self.assertEqual(w["since"][:10], "2026-11-13")
        self.assertFalse(w["soft"])

    def test_last_week_ru_is_hard(self):
        now = datetime(2026, 11, 14, 12, 0, 0)
        w = SP.resolve_time("что было на прошлой неделе", now=now)
        self.assertTrue(w["hard"])
        self.assertEqual(w["phrase"], "last_week")

    def test_recently_is_soft(self):
        w = SP.resolve_time("что недавно обсуждали", now=datetime(2026, 11, 14))
        self.assertTrue(w["soft"])
        self.assertFalse(w["hard"])

    def test_iso_date_is_hard(self):
        w = SP.resolve_time("events on 2026-07-04")
        self.assertTrue(w["hard"])
        self.assertEqual(w["since"][:10], "2026-07-04")

    def test_n_hits_clamped(self):
        self.assertEqual(SP.n_hits(1500), 3)
        self.assertEqual(SP.n_hits(3000), 5)
        self.assertEqual(SP.n_hits(10000), 10)
        self.assertEqual(SP.n_hits(100), 3)


class LineFilter(unittest.TestCase):
    def test_take_keeps_only_visible_before_cut(self):
        tok = ML.LINE_CTX.set({"mode": "allow", "ids": ["u::own1", "u::own2", "u::own3"], "db": "/tmp/x"})
        try:
            pairs = [("u::other%d" % i, 1.0 - i * 0.01) for i in range(40)] + [("u::own1", 0.2), ("u::own2", 0.1)]
            got = LN.take(pairs, 5)
            self.assertEqual([e for e, _ in got], ["u::own1", "u::own2"])
            self.assertLessEqual(len(got), 5)
        finally:
            ML.LINE_CTX.reset(tok)

    def test_deny_drops_foreign(self):
        tok = ML.LINE_CTX.set({"mode": "deny", "ids": ["u::foreign"], "db": "/tmp/x"})
        try:
            pairs = [("u::foreign", 0.9), ("u::keep", 0.8), ("u::keep2", 0.7)]
            got = LN.take(pairs, 2)
            self.assertEqual([e for e, _ in got], ["u::keep", "u::keep2"])
        finally:
            ML.LINE_CTX.reset(tok)

    def test_no_ctx_is_passthrough(self):
        pairs = [("u::a", 1), ("u::b", 0.5)]
        self.assertEqual(LN.take(pairs, 1), [("u::a", 1)])


class PackShape(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.uid = "packtest@x.invalid"
        from app.account_ids import account_name
        self.db = os.path.join(self.d, account_name(self.uid) + ".db")
        self.old = (SP.db_path,)
        SP.db_path = lambda uid: self.db
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, raw_dialogue TEXT)")
        c.execute("CREATE TABLE summary_l1 (session_id TEXT, topic TEXT, summary_text TEXT, from_rowid INTEGER, to_rowid INTEGER)")
        c.execute("CREATE TABLE summary_l2_blocks (id INTEGER PRIMARY KEY, source TEXT, period_key TEXT, text TEXT, from_rowid INTEGER, to_rowid INTEGER)")
        rows = []
        for i in range(1, 8):
            eid = "%s::remember_%d" % (self.uid, i)
            rows.append((eid, "2026-11-10 12:0%d:00" % i, "Q: turn %d about the dinosaur exhibit\nA: kids loved it %d" % (i, i)))
            c.execute("INSERT INTO event_metadata(event_id,time_str,raw_dialogue) VALUES (?,?,?)", rows[-1])
        c.execute("INSERT INTO summary_l1 VALUES ('s1','museum','L1 kids loved dinosaurs',1,7)")
        c.execute("INSERT INTO summary_l2_blocks VALUES (1,'agent','2026-11','L2 autumn museum trip',1,7)")
        c.commit(); c.close()
        self.c = sqlite3.connect(self.db)

    def tearDown(self):
        SP.db_path = self.old[0]
        self.c.close()

    def test_package_has_centre_neighbours_l1(self):
        hits = [{"event_id": "%s::remember_4" % self.uid, "score": 0.9, "source": "hybrid"}]
        pack = SP.package(self.uid, hits, "dinosaur", budget=3000)
        self.assertEqual(pack["n"], 1)
        h = pack["hits"][0]
        self.assertIn("dinosaur", h["centre"]["text"])
        self.assertTrue(h["neighbours"])
        self.assertIn("kids", h["l1"])
        self.assertEqual(h["l1_id"], "l1:s1")
        self.assertFalse(pack["truncated"])

    def test_expand_focus(self):
        pack = SP.expand(self.uid, "remember_4", radius=2)
        self.assertEqual(pack["n"], 1)
        self.assertGreaterEqual(len(pack["hits"][0]["neighbours"]), 2)

    def test_centre_truncated_flag(self):
        long = "word " * 2000
        c = sqlite3.connect(self.db)
        c.execute("UPDATE event_metadata SET raw_dialogue=? WHERE event_id=?", (long, "%s::remember_4" % self.uid))
        c.commit(); c.close()
        pack = SP.package(self.uid, [{"event_id": "%s::remember_4" % self.uid, "score": 1}], "x", budget=3000)
        self.assertTrue(pack["hits"][0]["centre"]["truncated"])
        self.assertTrue(pack["hits"][0]["truncated"])
        self.assertIn("memory_search(focus_event_id", pack["hint"])


if __name__ == "__main__":
    unittest.main()
