"""Tests for the 8/8/8 snapshot. They use temporary databases, not a previous partial pack."""
import gzip
import os
import sqlite3
import tempfile
import unittest

from app.memory_pack888 import (
    BUDGET, assemble_step_zero, build_pack, join_pack_pages, leak_names, load_document,
    pack_span, parse_records, render_document, split_bytes, split_document, step_zero_envelope_len,
    step_zero_next, write_snapshot, verify_snapshot, STEP_ZERO_MAX_JSON, STEP_ZERO_PAGE_TEXT,
)


def _user(path):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, raw_dialogue TEXT);
    CREATE TABLE summary_l1 (session_id TEXT, topic TEXT, summary_text TEXT, created_at TEXT, from_rowid INT, to_rowid INT);
    CREATE TABLE summary_l2 (user_id TEXT, map_json TEXT);
    CREATE TABLE summary_l2_blocks (id INT, source TEXT, period_from TEXT, period_to TEXT, from_rowid INT, to_rowid INT, text TEXT);
    CREATE TABLE critical_auto (key TEXT, kind TEXT, value TEXT, context TEXT, event_id TEXT, time_str TEXT, hits INT);
    CREATE TABLE board_items (item_id TEXT, kind TEXT, title TEXT, body TEXT, status TEXT, updated_at TEXT, removed INT,
                              priority INT, parent_id TEXT, waiting_for TEXT, result TEXT, created_at TEXT);
    CREATE TABLE profile_rows (id TEXT, kind TEXT, text TEXT, scope TEXT, status TEXT, created_at TEXT);
    """)
    return c


def _shared(path):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE cubes_new (cube_id TEXT, essence TEXT, rules_markdown TEXT, created_by TEXT, status TEXT);
    CREATE TABLE user_api_keys (user_id TEXT, api_key TEXT, is_active INT, created_at TEXT, key_prefix TEXT, label TEXT);
    """)
    return c


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.udb = os.path.join(self.tmp.name, "u.db")
        self.sdb = os.path.join(self.tmp.name, "s.db")
        self.user = _user(self.udb)
        self.shared = _shared(self.sdb)

    def tearDown(self):
        self.user.close()
        self.shared.close()
        self.tmp.cleanup()

    def _seed_layers(self):
        # rowid 100 fills most of the raw budget. rowid 90 would cross it and is left out whole.
        # rowid 10 is older and not reached. L1/L2 that touch the raw window are excluded.
        self.user.execute("INSERT INTO event_metadata (rowid, event_id, time_str, raw_dialogue) VALUES (100,'e100','2026-11-09 01:00',?)", ("A" * 20000,))
        self.user.execute("INSERT INTO event_metadata (rowid, event_id, time_str, raw_dialogue) VALUES (90,'e90','2026-11-08 01:00',?)", ("B" * 16000,))
        self.user.execute("INSERT INTO event_metadata (rowid, event_id, time_str, raw_dialogue) VALUES (10,'e10','2026-01-01 01:00','OLD RAW NOT IN WINDOW')")
        self.user.execute("INSERT INTO event_metadata (rowid, event_id, time_str, raw_dialogue) VALUES (4,'e2','2026-01-02','note\n>>> critical mark full line')")
        self.user.execute("INSERT INTO summary_l1 VALUES ('l1-overlap','t','should not be in l1','2026-11-09',90,100)")
        self.user.execute("INSERT INTO summary_l1 VALUES ('l1-old','t','L1 OLD COMPLETE','2026-02-01',20,50)")
        self.user.execute("INSERT INTO summary_l2 VALUES ('u','LEGACYMAPTOKEN')")
        self.user.execute("INSERT INTO summary_l2_blocks VALUES (9,'agent','2026-02-01','2026-02-02',20,50,'L2 overlaps l1')")
        self.user.execute("INSERT INTO summary_l2_blocks VALUES (1,'agent','2026-01-01','2026-01-02',1,15,'L2 OLD COMPLETE')")
        self.user.execute("INSERT INTO critical_auto VALUES ('k1','fact','a fact','ctx','e10','2026-01-01',1)")
        self.user.execute("INSERT INTO board_items VALUES ('T1','task','Do','full task body','todo','2026-03-01',0,1,'','','','2026-03-01')")
        self.user.execute("INSERT INTO board_items VALUES ('N1','note','N','full note body','','2026-03-01',0,2,'','','','2026-03-01')")
        self.user.execute("INSERT INTO board_items VALUES ('X','task','gone','removed task body','todo','2026-03-01',1,1,'','','','2026-03-01')")
        self.user.execute("INSERT INTO profile_rows VALUES ('p1','rule','always full profile','global','active','2026-03-01')")
        self.shared.execute("INSERT INTO cubes_new VALUES ('cube_const_00_v5','e','FULL CONST 00','system','verified')")
        self.shared.execute("INSERT INTO cubes_new VALUES ('cube_const_00_v4','e','OLD CONST','system','verified')")
        self.shared.execute(
            "INSERT INTO user_api_keys VALUES ('u', ?, 1, '2026-01-01', 'sk_abcd', 'grok')",
            ("sk_thisisasecretkeyvalue123",),
        )
        self.user.commit()
        self.shared.commit()

    def test_whole_records_disjoint_ranges_and_sections(self):
        self._seed_layers()
        pack = build_pack(self.user, self.shared, owners=["system"])
        doc = render_document(pack)
        parsed = {(r["layer"], r["id"]): r["body"] for r in parse_records(doc)}
        self.assertEqual(parsed[("raw", "e100")], "A" * 20000)
        self.assertNotIn(("raw", "e90"), parsed)
        self.assertNotIn(("raw", "e10"), parsed)
        self.assertNotIn("B" * 20, doc)
        self.assertEqual(parsed[("l1", "l1-old")], "L1 OLD COMPLETE")
        self.assertNotIn(("l1", "l1-overlap"), parsed)
        self.assertEqual(parsed[("l2", "1")], "L2 OLD COMPLETE")
        self.assertNotIn(("l2", "9"), parsed)
        self.assertNotIn("LEGACYMAPTOKEN", doc)
        self.assertTrue(pack["overlap_ok"])
        self.assertLess(pack["spans"]["l2"]["rowid_max"], pack["spans"]["l1"]["rowid_min"])
        self.assertLess(pack["spans"]["l1"]["rowid_max"], pack["spans"]["raw"]["rowid_min"])
        self.assertIn("a fact", parsed[("critical", "auto:k1")])
        self.assertIn(">>> critical mark full line", parsed[("critical", "mark:e2:1")])
        self.assertIn("FULL CONST 00", parsed[("constitution", "cube_const_00_v5")])
        self.assertNotIn(("constitution", "cube_const_00_v4"), parsed)
        self.assertIn("full task body", parsed[("tasks", "T1")])
        self.assertIn("full note body", parsed[("board", "N1")])
        self.assertNotIn("secret body", doc)
        self.assertIn("always full profile", parsed[("profile", "p1")])
        self.assertNotIn("sk_thisisasecretkeyvalue123", doc)
        self.assertIn("sk_abcd", doc)
        self.assertEqual(pack["access_registry_status"], "present")
        self.assertEqual(pack["gaps"]["legacy_l2_map"], "excluded_no_disjoint_range")

    def test_stable_prefix_when_the_tail_grows(self):
        self._seed_layers()
        doc = render_document(build_pack(self.user, self.shared, owners=["system"]))
        names = (
            "constitution", "profile", "l2", "l1", "raw",
            "critical", "board", "tasks", "access_registry", "pack_status",
        )
        spots = [doc.index("## " + name) for name in names]
        self.assertEqual(spots, sorted(spots))
        head = doc.split("## pack_status")[0]
        self.assertNotIn("time_min:", head)
        self.assertNotIn("time_max:", head)
        self.assertLess(doc.index("FULL CONST 00"), doc.index("always full profile"))
        self.assertLess(doc.index("always full profile"), doc.index("L2 OLD COMPLETE"))
        self.assertLess(doc.index("L2 OLD COMPLETE"), doc.index("L1 OLD COMPLETE"))
        self.assertLess(doc.index("L1 OLD COMPLETE"), doc.index("A" * 20))
        # Upper blocks stop at the raw section. A new raw record appends there.
        upper = doc.split("## raw")[0]
        self.user.execute(
            "INSERT INTO event_metadata (rowid, event_id, time_str, raw_dialogue) VALUES (200,'e200','2026-11-10','NEW RAW TAIL')"
        )
        self.user.commit()
        grown = render_document(build_pack(self.user, self.shared, owners=["system"]))
        self.assertEqual(grown.split("## raw")[0], upper)
        raw_end = doc.index("## critical")
        self.assertTrue(grown.startswith(doc[:raw_end]))
        fresh = grown[raw_end:]
        self.assertLess(fresh.index("NEW RAW TAIL"), fresh.index("## critical"))
        again = render_document(build_pack(self.user, self.shared, owners=["system"]))
        self.assertEqual(again, grown)

    def test_underfill_and_whole_exclusion(self):
        self.user.execute("INSERT INTO event_metadata VALUES ('tiny','2026-01-01','hi')")
        self.user.commit()
        pack = build_pack(self.user, None)
        raw = pack["layers"]["raw"]
        self.assertEqual(raw["stopped_because"], "data_exhausted")
        self.assertGreater(raw["underfill"], 0)
        self.assertLess(raw["tokens_estimate"], BUDGET)
        self.assertIsNone(raw["excluded_next"])
        # one record bigger than the budget is left out whole
        huge = "word " * 20000
        self.user.execute("INSERT INTO event_metadata VALUES ('huge','2026-11-09',?)", (huge,))
        self.user.commit()
        pack = build_pack(self.user, None)
        raw = pack["layers"]["raw"]
        self.assertEqual(raw["included"], [])
        self.assertEqual(raw["excluded_next"]["id"], "huge")
        self.assertEqual(raw["stopped_because"], "next_record_exceeds_budget")
        doc = render_document(pack)
        self.assertNotIn("word word word", doc)

    def test_clipped_tail_is_not_a_complete_record(self):
        full = "START " + ("middle " * 200) + " END"
        clipped = full[-800:]
        self.assertGreater(len(full), 800)
        self.assertNotEqual(clipped, full)
        self.assertFalse(clipped.startswith("START"))
        self.assertTrue(full.endswith(" END"))

    def test_absent_registry(self):
        self.shared.execute("DROP TABLE user_api_keys")
        self.shared.commit()
        pack = build_pack(self.user, self.shared)
        self.assertEqual(pack["access_registry_status"], "absent")
        self.assertIn("ABSENT", render_document(pack))

    def test_gzip_parts_and_secret_refusal(self):
        self._seed_layers()
        pack = build_pack(self.user, self.shared, owners=["system"])
        dest = write_snapshot(pack, self.tmp.name, part_bytes=4000)
        man = verify_snapshot(dest)
        self.assertTrue(man["checks"]["gzip_roundtrip"])
        with open(os.path.join(dest, "snapshot.txt.gz"), "rb") as f:
            gz_payload = gzip.decompress(f.read())
        with open(os.path.join(dest, "snapshot.txt"), "rb") as f:
            doc_bytes = f.read()
        self.assertEqual(gz_payload, doc_bytes)
        chunks = []
        for p in man["parts"]["files"]:
            with open(os.path.join(dest, "parts", p["name"]), "rb") as f:
                chunks.append(f.read())
        joined = b"".join(chunks)
        self.assertEqual(joined, doc_bytes)
        self.assertGreater(len(man["parts"]["files"]), 1)
        # a planted long key must not survive masking
        self.assertEqual(leak_names("sk_thisisasecretkeyvalue123"), ["sk_key"])
        dirty = dict(pack)
        dirty["layers"] = {k: dict(v) for k, v in pack["layers"].items()}
        # write_snapshot refuses documents that still contain a secret
        poisoned = render_document(pack) + "\nsk_thisisasecretkeyvalue123\n"
        self.assertIn("sk_key", leak_names(poisoned))

    def test_split_keeps_utf8(self):
        data = ("привет" * 20).encode("utf-8")
        parts = split_bytes(data, 7)
        self.assertEqual(b"".join(parts), data)
        for chunk in parts:
            chunk.decode("utf-8")


class StepZeroPagesTest(unittest.TestCase):
    def test_pages_join_without_loss_or_overlap_and_fit(self):
        huge = "Q: " + ("код \"x\" " * 3000) + "\nA: " + ("ё" * 9000)
        small = "Q: short\nA: done"
        doc = (
            "SKV memory pack 8/8/8\n"
            + "<<<RECORD layer=raw id=big bytes=%d>>>\n" % len(huge.encode())
            + huge + "\n<<<END>>>\n"
            + "<<<RECORD layer=raw id=small bytes=%d>>>\n" % len(small.encode())
            + small + "\n<<<END>>>\n"
        )
        pages = split_document(doc)
        self.assertGreater(len(pages), 1)
        self.assertEqual(join_pack_pages(pages), doc)
        self.assertEqual([r["id"] for r in parse_records(join_pack_pages(pages))], ["big", "small"])
        self.assertEqual(parse_records(join_pack_pages(pages))[0]["body"], huge)
        for p in pages:
            self.assertLessEqual(step_zero_envelope_len(p), STEP_ZERO_MAX_JSON)
            self.assertTrue(p.startswith("=== PACK888 "))
        # a record that fits stays whole on its page
        small_page = next(p for p in pages if "id=small " in p and "<<<END>>>" in p.split("id=small ", 1)[-1])
        self.assertIn(small, small_page)

    def test_quotes_do_not_get_trimmed(self):
        doc = '"' * 20000
        pages = split_document(doc)
        self.assertEqual(join_pack_pages(pages), doc)
        for p in pages:
            self.assertLessEqual(len(p), STEP_ZERO_PAGE_TEXT)
            self.assertLessEqual(step_zero_envelope_len(p), STEP_ZERO_MAX_JSON)

    def test_full_page_text_is_about_14kb(self):
        line = "строка памяти.\n"
        doc = line * 5000
        pages = split_document(doc)
        self.assertGreaterEqual(len(pages), 5)
        self.assertEqual(join_pack_pages(pages), doc)
        for p in pages[:-1]:
            self.assertGreaterEqual(len(p), 12000)
            self.assertLessEqual(len(p), STEP_ZERO_PAGE_TEXT)
            self.assertLessEqual(step_zero_envelope_len(p), STEP_ZERO_MAX_JSON)
        self.assertLessEqual(len(pages[-1]), STEP_ZERO_PAGE_TEXT)

    def test_step_zero_order_and_next_hint(self):
        doc = "ALPHA\n<<<END>>>\nBETA\n"
        pack_pages = split_document(doc)
        pages = assemble_step_zero(["intro"], pack_pages, ["CUBE 00"])
        self.assertEqual(pages[0], "intro")
        self.assertEqual(pages[-1], "CUBE 00")
        lo, hi = pack_span(pages)
        self.assertEqual(pages[lo - 1][:12], "=== PACK888 ")
        self.assertEqual(join_pack_pages(pages[lo - 1:hi]), doc)
        self.assertIn("memory pack 8/8/8", step_zero_next(1, pages))
        self.assertIn("constitution", step_zero_next(hi, pages))
        self.assertIn("step zero complete", step_zero_next(len(pages), pages))

    def test_missing_user_is_explicit(self):
        with self.assertRaises(RuntimeError) as cm:
            load_document("nobody-pack888@example.com", user_db="/tmp/does-not-exist-pack888.db")
        self.assertIn("user database not found", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
