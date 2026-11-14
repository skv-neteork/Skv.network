"""B11 date window. Unit cases use a temp sqlite and an injected cosine.
The gate case reads benchlme3 (skip if that db is absent) and the real index.

Run inside the API container (host venv has no numpy):
  docker cp tests/test_b11_window.py skv_api:/tmp/test_b11_window.py
  docker exec -w /tmp -e PYTHONPATH=/app skv_api python -m unittest test_b11_window
"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from app import memory_lines as ML
from app import search_pack as SP
from app import search_text as ST
from app import search_window as SW


def _db(rows):
    """rows: (event_id, time_str, content, kind)."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "t.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, raw_dialogue TEXT, kind TEXT)")
    for eid, ts, raw, kind in rows:
        c.execute("INSERT INTO event_metadata VALUES (?,?,?,?)", (eid, ts, raw, kind))
    c.commit()
    c.close()
    return path


def _zero(uid, eids, query):
    return {e: 0.0 for e in eids}


class Parse(unittest.TestCase):
    def test_date_is_day_before_and_after(self):
        b = SW.parse(date="2023-03-04")
        self.assertTrue(b["window_set"])
        self.assertEqual(b["since"], "2023-03-03")
        self.assertEqual(b["until"], "2023-03-05")
        self.assertEqual(b["since_kind"], "date")

    def test_date_with_since_is_400(self):
        with self.assertRaises(SW.WindowError) as cm:
            SW.parse(date="2023-03-04", since="2023-03-01")
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "conflict")

    def test_since_after_until_is_400_no_swap(self):
        with self.assertRaises(SW.WindowError) as cm:
            SW.parse(since="2023-03-05", until="2023-03-03")
        self.assertEqual(cm.exception.code, "since_after_until")
        self.assertEqual(cm.exception.status, 400)

    def test_impossible_day_is_400(self):
        with self.assertRaises(SW.WindowError) as cm:
            SW.parse(date="2023-02-31")
        self.assertEqual(cm.exception.code, "bad_date")
        with self.assertRaises(SW.WindowError):
            SW.parse(since="2023-02-31")

    def test_unknown_and_question_mark_are_no_window(self):
        for t in ("unknown", "?", "UNKNOWN"):
            b = SW.parse(time=t)
            self.assertFalse(b["window_set"])
            self.assertEqual(b["note"], "no window set")
            self.assertEqual(b["covered_window"], "all time (window unknown)")

    def test_unknown_plus_a_real_bound_is_400(self):
        with self.assertRaises(SW.WindowError) as cm:
            SW.parse(time="unknown", since="2023-03-01")
        self.assertEqual(cm.exception.code, "conflict")

    def test_question_mark_on_one_side_is_open(self):
        b = SW.parse(since="?", until="2023-03-05")
        self.assertTrue(b["window_set"])
        self.assertIsNone(b["since"])
        self.assertEqual(b["until"], "2023-03-05")

    def test_since_only_is_open(self):
        b = SW.parse(since="2023-03-03")
        self.assertTrue(b["window_set"])
        self.assertEqual(b["since"], "2023-03-03")
        self.assertIsNone(b["until"])

    def test_bad_time_word_is_400(self):
        with self.assertRaises(SW.WindowError) as cm:
            SW.parse(time="yesterday")
        self.assertEqual(cm.exception.status, 400)
        self.assertIn("example", cm.exception.body())

    def test_bad_paging(self):
        for limit, offset in ((0, 0), (101, 0), (20, -1), ("nope", 0)):
            with self.assertRaises(SW.WindowError) as cm:
                SW.paging(limit, offset)
            self.assertEqual(cm.exception.code, "bad_paging")
        self.assertEqual(SW.paging(None, None), (20, 0))
        self.assertEqual(SW.paging(100, 3), (100, 3))

    def test_duration_is_utc_stamp_not_shifted(self):
        kind, val = SW._bound_one("1d", datetime(2026, 11, 14, 15, 30), "since")
        self.assertEqual(kind, "stamp")
        self.assertEqual(val, "2026-11-13 15:30")

    def test_cap_constant(self):
        self.assertEqual(SW.WINDOW_CAP, 20000)


class Rank(unittest.TestCase):
    def _rows(self):
        return [
            ("u::early", "2023-03-03 09:00", "zzzz noise", ""),
            ("u::aunt", "2023-03-04 16:45", "crystal chandelier from my aunt", ""),
            ("u::late", "2023-03-05 11:00", "unrelated walk", ""),
            ("u::out", "2023-03-06 11:00", "crystal chandelier from my aunt", ""),
            ("u::before", "2023-03-02 11:00", "crystal chandelier from my aunt", ""),
        ]

    def test_window_drops_outside_and_ranks_inside(self):
        path = _db(self._rows())
        called = {"n": 0}

        def cos(uid, eids, query):
            called["n"] += 1
            called["ids"] = list(eids)
            return {"u::aunt": 0.9, "u::early": 0.1, "u::late": 0.0}

        # long filler so the full texts do not fit a tiny budget
        c = sqlite3.connect(path)
        c.execute("UPDATE event_metadata SET raw_dialogue = raw_dialogue || ?", (" word" * 800,))
        c.commit()
        c.close()
        pack = SW.run("u@x", "chandelier aunt", since="2023-03-03", until="2023-03-05",
                      budget=3000, limit=10, db=path, cosine_fn=cos)
        self.assertEqual(pack["total_in_window"], 3)
        self.assertTrue(pack["scored"])
        self.assertEqual(called["n"], 1)
        self.assertNotIn("u::out", called["ids"])
        self.assertEqual(pack["hits"][0]["id"], "u::aunt")
        for h in pack["hits"]:
            self.assertGreaterEqual(h["date"][:10], "2023-03-03")
            self.assertLessEqual(h["date"][:10], "2023-03-05")
        self.assertIn("2023-02-28", pack["hint"])
        self.assertIn("2023-03-08", pack["hint"])

    def test_no_query_is_chronological_and_does_not_embed(self):
        path = _db(self._rows())
        pack = SW.run("u@x", "", since="2023-03-03", until="2023-03-05",
                      budget=10 ** 9, limit=20, db=path, cosine_fn=lambda *a: (_ for _ in ()).throw(AssertionError("embed")))
        self.assertFalse(pack["scored"])
        self.assertEqual([h["id"] for h in pack["hits"]], ["u::early", "u::aunt", "u::late"])
        self.assertIsNone(pack["hits"][0]["score"])
        self.assertFalse(pack["has_more"])

    def test_fit_is_chronological_even_with_a_query(self):
        path = _db(self._rows()[:3])
        pack = SW.run("u@x", "chandelier", since="2023-03-03", until="2023-03-05",
                      budget=3000, limit=20, db=path,
                      cosine_fn=lambda *a: (_ for _ in ()).throw(AssertionError("embed")))
        self.assertFalse(pack["scored"])
        self.assertEqual(pack["hits"][0]["id"], "u::early")
        self.assertEqual(pack["n"], 3)
        self.assertFalse(pack["has_more"])

    def test_fit_but_over_limit_pages_in_order(self):
        path = _db(self._rows()[:3])
        pack = SW.run("u@x", "", since="2023-03-03", until="2023-03-05",
                      budget=3000, limit=2, db=path, cosine_fn=_zero)
        self.assertFalse(pack["scored"])
        self.assertEqual(pack["n"], 2)
        self.assertTrue(pack["has_more"])
        self.assertEqual(pack["next_offset"], 2)
        nxt = SW.run("u@x", "", since="2023-03-03", until="2023-03-05",
                     budget=3000, limit=2, offset=2, db=path, cosine_fn=_zero)
        self.assertEqual([h["id"] for h in nxt["hits"]], ["u::late"])
        self.assertFalse(nxt["has_more"])
        self.assertIsNone(nxt["next_offset"])

    def test_offset_past_the_end_is_an_empty_page(self):
        path = _db(self._rows()[:3])
        pack = SW.run("u@x", "", since="2023-03-03", until="2023-03-05",
                      budget=3000, limit=20, offset=50, db=path, cosine_fn=_zero)
        self.assertEqual(pack["hits"], [])
        self.assertEqual(pack["total_in_window"], 3)
        self.assertFalse(pack["has_more"])

    def test_always_rank_even_when_the_budget_is_huge(self):
        path = _db(self._rows()[:3])

        def cos(uid, eids, query):
            return {"u::late": 1.0, "u::aunt": 0.2, "u::early": 0.0}

        pack = SW.run("u@x", "walk", since="2023-03-03", until="2023-03-05",
                      budget=10 ** 9, limit=5, db=path, cosine_fn=cos, always_rank=True)
        self.assertTrue(pack["scored"])
        self.assertEqual(pack["hits"][0]["id"], "u::late")

    def test_one_oversized_hit_still_returns_a_page(self):
        path = _db([("u::big", "2023-03-04 10:00", "aunt " * 5000, "")])
        pack = SW.run("u@x", "aunt", date="2023-03-04", budget=200, limit=5, db=path, cosine_fn=_zero)
        self.assertEqual(pack["n"], 1)
        self.assertTrue(pack["hits"][0]["truncated"])
        self.assertTrue(pack["hits"][0]["content"])

    def test_overlap_is_nfkc_lower_no_stem(self):
        self.assertEqual(SW.overlap("File", "the ﬁle is here"), 1.0)
        self.assertEqual(SW.overlap("aunt", "my Aunt"), 1.0)
        self.assertAlmostEqual(SW.overlap("received an item", "the item arrived"), 1.0 / 3.0)
        # no stemming: "receiving" does not count as "received"
        self.assertEqual(SW.overlap("received", "receiving a gift"), 0.0)

    def test_missing_vector_keeps_the_event(self):
        path = _db([("u::a", "2023-03-04 10:00", "alpha beta extra", "")])
        pack = SW.run("u@x", "alpha beta", date="2023-03-04", budget=200, limit=5,
                      db=path, cosine_fn=lambda uid, eids, q: {}, always_rank=True)
        self.assertEqual(pack["n"], 1)
        self.assertAlmostEqual(pack["hits"][0]["score"], round(0.15 * 1.0, 5))

    def test_over_cap_is_422_and_names_the_cap(self):
        path = _db([
            ("u::a", "2023-03-04 10:00", "a", ""),
            ("u::b", "2023-03-04 11:00", "b", ""),
            ("u::c", "2023-03-04 12:00", "c", ""),
        ])
        old = SW.WINDOW_CAP
        SW.WINDOW_CAP = 2
        try:
            with self.assertRaises(SW.WindowError) as cm:
                SW.run("u@x", "q", date="2023-03-04", db=path, cosine_fn=_zero)
        finally:
            SW.WINDOW_CAP = old
        self.assertEqual(cm.exception.status, 422)
        self.assertEqual(cm.exception.code, "window_too_large")
        self.assertIn("2", cm.exception.detail)
        self.assertEqual(SW.WINDOW_CAP, 20000)

    def test_imports_and_line_filter(self):
        path = _db([
            ("u::own", "2023-03-04 10:00", "own", ""),
            ("u::other", "2023-03-04 11:00", "other", ""),
            ("u::imp", "2023-03-04 12:00", "imported", "import"),
        ])
        tok = ML.LINE_CTX.set({"mode": "allow", "ids": ["u::own", "u::imp"]})
        try:
            pack = SW.run("u@x", "", date="2023-03-04", budget=3000, limit=20,
                          db=path, cosine_fn=_zero, exclude_imports=True)
        finally:
            ML.LINE_CTX.reset(tok)
        self.assertEqual([h["id"] for h in pack["hits"]], ["u::own"])

    def test_duration_and_stamp_bounds(self):
        path = _db([
            ("u::old", "2026-11-13 15:29", "old", ""),
            ("u::edge", "2026-11-13 15:30", "edge", ""),
            ("u::new", "2026-11-14 01:00", "new", ""),
        ])
        pack = SW.run("u@x", "", since="1d", now=datetime(2026, 11, 14, 15, 30),
                      budget=3000, limit=20, db=path, cosine_fn=_zero)
        self.assertEqual([h["id"] for h in pack["hits"]], ["u::edge", "u::new"])
        pack = SW.run("u@x", "", since="2023-03-04 16:00", until="2023-03-04 18:00",
                      budget=3000, limit=20, db=_db([
                          ("u::no", "2023-03-04 15:00", "no", ""),
                          ("u::yes", "2023-03-04 16:45", "yes", ""),
                          ("u::end", "2023-03-04 18:00", "end", ""),
                      ]), cosine_fn=_zero)
        self.assertEqual([h["id"] for h in pack["hits"]], ["u::yes", "u::end"])


class SearchPath(unittest.TestCase):
    def test_focus_is_400_with_one_example(self):
        with self.assertRaises(SW.WindowError) as cm:
            SP.search("u@x", "gift", focus_event_id="u::remember_1")
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "focus_removed")
        self.assertIn("since=", cm.exception.example)

    def test_empty_query_without_a_window_is_400(self):
        with self.assertRaises(SW.WindowError) as cm:
            SP.search("u@x", "")
        self.assertEqual(cm.exception.code, "query_required")

    def test_relative_phrase_does_not_filter(self):
        calls = {}

        def wide(uid, query, top_k=50, since=None, until=None, exclude_imports=False, source=None):
            calls["since"] = since
            calls["until"] = until
            calls["query"] = query
            return [("u::a", 0.4)]

        def div(wide_hits, query, window, gap=3):
            return list(wide_hits)

        def pkg(uid, sliced, query, budget=None, window=None):
            return {"hits": [{"event_id": "u::a", "centre": {"text": "met yesterday"}}],
                    "hint": "base", "truncated": False, "n": 1}

        old = (SP.retrieve_wide, SP.diversify, SP.package, SP.resolve_time)
        SP.retrieve_wide, SP.diversify, SP.package = wide, div, pkg

        def boom(*a, **k):
            raise AssertionError("resolve_time must not run on the search path")

        SP.resolve_time = boom
        try:
            pack = SP.search("u@x", "what happened yesterday", time="unknown")
        finally:
            SP.retrieve_wide, SP.diversify, SP.package, SP.resolve_time = old
        self.assertIsNone(calls["since"])
        self.assertIsNone(calls["until"])
        self.assertEqual(calls["query"], "what happened yesterday")
        self.assertFalse(pack["window_set"])
        self.assertEqual(pack["note"], "no window set")
        self.assertEqual(pack["covered_window"], "all time (window unknown)")
        self.assertIn("No window set", pack["hint"])
        self.assertIn("date=", pack["hint"])

    def test_search_window_does_not_use_top_k_as_limit(self):
        seen = {}

        def fake(uid, query, **kw):
            seen.update(kw)
            seen["query"] = query
            return {"hits": [], "window_set": True, "total_in_window": 0}

        import app.search_window as sw
        old = sw.run
        sw.run = fake
        try:
            SP.search("u@x", "gift", since="2023-03-03", until="2023-03-05", top_k=8)
        finally:
            sw.run = old
        self.assertIsNone(seen.get("limit"))
        self.assertEqual(seen.get("since"), "2023-03-03")

    def test_filtered_search_delegates_to_the_window(self):
        seen = {}

        def fake(uid, query, **kw):
            seen.update(kw)
            seen["query"] = query
            return {"hits": [{"id": "u::a", "date": "2023-03-04 16:45", "content": "aunt chandelier", "score": 0.42}]}

        old = SW.run
        SW.run = fake
        try:
            out = ST.filtered_search("u@x", "gift", top_k=5, since="2023-03-03", until="2023-03-05")
        finally:
            SW.run = old
        self.assertTrue(seen.get("always_rank"))
        self.assertEqual(seen.get("limit"), 5)
        self.assertEqual(seen.get("budget"), 10 ** 9)
        self.assertEqual(out[0]["event_id"], "u::a")
        self.assertEqual(out[0]["metadata"]["time_str"], "2023-03-04 16:45")
        self.assertEqual(out[0]["score"], 0.42)


class Gate(unittest.TestCase):
    """The live numbers. Line lme-71017277 is chain ch_25eb8fb4d6c4471c on benchlme3."""

    CHAIN = "ch_25eb8fb4d6c4471c"
    AUNT = "remember_1794386516586827764"
    SHARED = "/data/skv/metadata_store/shared_master.db"

    def test_gift_window_line_and_all(self):
        if not os.path.exists(self.SHARED):
            self.skipTest("shared db absent")
        c = sqlite3.connect("file:%s?mode=ro" % self.SHARED, uri=True)
        row = c.execute("SELECT user_id FROM event_lines WHERE chain_id=? LIMIT 1", (self.CHAIN,)).fetchone()
        if not row:
            c.close()
            self.skipTest("bench line absent")
        uid = row[0]
        ids = [r[0] for r in c.execute("SELECT event_id FROM event_lines WHERE chain_id=?", (self.CHAIN,))]
        c.close()
        from app.memory_v2 import db_path
        if not os.path.exists(db_path(uid)):
            self.skipTest("account db absent")
        tok = ML.LINE_CTX.set({"mode": "allow", "ids": ids})
        try:
            pack = SW.run(uid, "received an item as a gift", since="2023-03-03", until="2023-03-05",
                          limit=20, budget=3000)
            via = SP.search(uid, "received an item as a gift", since="2023-03-03", until="2023-03-05", limit=20)
        finally:
            ML.LINE_CTX.reset(tok)
        self.assertEqual(pack["total_in_window"], 75)
        self.assertEqual(via["total_in_window"], 75)
        self.assertTrue(pack["window_set"])
        self.assertTrue(pack["scored"])
        self.assertEqual(pack["covered_window"], {"since": "2023-03-03", "until": "2023-03-05"})
        hits = pack["hits"]
        self.assertGreaterEqual(len(hits), 10)
        for h in hits:
            self.assertGreaterEqual(h["date"][:10], "2023-03-03")
            self.assertLessEqual(h["date"][:10], "2023-03-05")
            self.assertTrue(h["id"])
        top = hits[:10]
        aunt = [h for h in top if self.AUNT in (h["id"] or "")]
        self.assertTrue(aunt, [h["id"].rsplit("::", 1)[-1] for h in top])
        blob = (aunt[0]["content"] or "").lower()
        self.assertTrue("chandelier" in blob or "aunt" in blob)
        rank = next(i for i, h in enumerate(hits) if self.AUNT in (h["id"] or ""))
        all_pack = SW.run(uid, "received an item as a gift", since="2023-03-03", until="2023-03-05",
                          limit=5, budget=3000)
        self.assertEqual(all_pack["total_in_window"], 101)
        for h in all_pack["hits"]:
            self.assertGreaterEqual(h["date"][:10], "2023-03-03")
            self.assertLessEqual(h["date"][:10], "2023-03-05")
        doc = {
            "line_total": pack["total_in_window"],
            "all_total": all_pack["total_in_window"],
            "aunt_rank": rank + 1,
            "aunt_in_top10": True,
            "page_n": len(hits),
            "scored": pack["scored"],
            "cap": SW.WINDOW_CAP,
            "aunt_score": aunt[0]["score"],
            "content_has_chandelier": "chandelier" in blob,
            "content_has_aunt": "aunt" in blob,
        }
        json.dump(doc, open("/tmp/b11_gate.json", "w"))
        print("GATE", json.dumps(doc))


if __name__ == "__main__":
    unittest.main()
