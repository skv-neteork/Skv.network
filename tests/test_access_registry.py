"""Access registry: one non-secret table, isolated by owner and memory line.

Temporary databases only. Nothing here opens /data/skv.
"""
import os
import sqlite3
import tempfile
import unittest

from app import access_registry as ar
from app import board
from app import memory_v2
from app import session_bootstrap as sb
from app import shelves


SECRET = "sk_notarealkey1234567890"
LOC = "[vault:mail_box]"
LOC2 = "[conn:office_link]"


def _add(conn, owner, chain, service="mail", purpose="read the office mailbox", locator=LOC, **kw):
    return ar.add(conn, owner, chain, service=service, purpose=purpose, locator=locator, **kw)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_owner_and_line_isolation(self):
        a = _add(self.conn, "owner-a", "line-1", service="mail")
        b = _add(self.conn, "owner-a", "line-2", service="git", purpose="push release tags", locator=LOC2)
        c = _add(self.conn, "owner-b", "line-1", service="mail")
        self.assertEqual([r["access_id"] for r in ar.list_line(self.conn, "owner-a", "line-1")], [a["access_id"]])
        self.assertEqual([r["access_id"] for r in ar.list_line(self.conn, "owner-a", "line-2")], [b["access_id"]])
        self.assertEqual([r["access_id"] for r in ar.list_line(self.conn, "owner-b", "line-1")], [c["access_id"]])
        self.assertEqual(ar.list_line(self.conn, "owner-a", ""), [])
        self.assertEqual(ar.list_line(self.conn, "", "line-1"), [])
        with self.assertRaises(KeyError):
            ar.get(self.conn, "owner-b", "line-1", a["access_id"])
        with self.assertRaises(KeyError):
            ar.check(self.conn, "owner-a", "line-2", a["access_id"], "ok", "seen it work")

    def test_rejects_secrets_and_personal_data(self):
        samples = [
            SECRET,
            "person@example.com",
            "+1 202 555 0199",
            "5551234567",
            "https://example.com/path",
            "https://example.com/?access_token=abc",
            "SHA256:ab:cd:ef:12:34:56:78:90:ab",
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexamplekeymaterial",
        ]
        for bad in samples:
            with self.assertRaises(ValueError):
                _add(self.conn, "owner-a", "line-1", purpose=bad)
            with self.assertRaises(ValueError):
                _add(self.conn, "owner-a", "line-1", service="calendar", purpose="see the agenda", locator=LOC, basis=bad)
        with self.assertRaises(ValueError):
            _add(self.conn, "owner-a", "line-1", locator="https://example.com")
        with self.assertRaises(ValueError):
            _add(self.conn, "owner-a", "line-1", locator="[vault:BadName]")
        # A calendar date is not a phone number.
        row = _add(self.conn, "owner-a", "line-1", purpose="backup dated 2026-11-09")
        self.assertIn("2026-11-09", row["purpose"])
        stored = "\n".join(str(x) for rec in self.conn.execute("SELECT * FROM access_registry") for x in rec)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM access_registry").fetchone()[0], 1)
        self.assertNotIn(SECRET, stored)
        self.assertNotIn("example.com", stored)
        self.assertNotIn("5551234567", stored)

    def test_status_dates_and_upsert(self):
        row = _add(self.conn, "owner-a", "line-1", scope="inbox", basis="named by the operator")
        self.assertEqual(row["status"], "unchecked")
        self.assertIsNone(row["checked_at"])
        self.assertIsNone(row["confirmed_at"])
        self.assertEqual(row["owner_id"], "owner-a")
        self.assertEqual(row["chain_id"], "line-1")
        self.assertIn("not permission", row["permission"])
        again = ar.add(
            self.conn, "owner-a", "line-1", service="mail", purpose="read the office mailbox",
            locator=LOC, scope="inbox", owner="owner-b", memory_line="stolen",
        )
        self.assertEqual(again["access_id"], row["access_id"])
        self.assertEqual(again["owner_id"], "owner-a")
        ok = ar.check(self.conn, "owner-a", "line-1", row["access_id"], "ok", "opened the mailbox")
        self.assertEqual(ok["status"], "ok")
        self.assertTrue(ok["checked_at"])
        self.assertEqual(ok["confirmed_at"], ok["checked_at"])
        self.conn.execute(
            "UPDATE access_registry SET checked_at='2000-01-01 00:00:00' WHERE access_id=?",
            (row["access_id"],),
        )
        self.conn.commit()
        failed = ar.check(self.conn, "owner-a", "line-1", row["access_id"], "failed", "login was refused")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["confirmed_at"], ok["confirmed_at"])
        self.assertNotEqual(failed["checked_at"], "2000-01-01 00:00:00")
        with self.assertRaises(ValueError):
            ar.check(self.conn, "owner-a", "line-1", row["access_id"], "unchecked", "nope")
        with self.assertRaises(ValueError):
            ar.check(self.conn, "owner-a", "line-1", row["access_id"], "ok", "no")
        with self.assertRaises(ValueError):
            ar.add(self.conn, "", "line-1", service="mail", purpose="read the office mailbox", locator=LOC)

    def test_agent_cannot_delete(self):
        row = _add(self.conn, "owner-a", "line-1")
        with self.assertRaises(PermissionError):
            ar.agent_delete(self.conn, row["access_id"])
        self.assertEqual(ar.get(self.conn, "owner-a", "line-1", row["access_id"])["access_id"], row["access_id"])
        with open(ar.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("DELETE FROM", src)
        self.assertEqual(ar.task_ref(row["access_id"]), "access:" + row["access_id"])
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("profile_rows", tables)
        self.assertNotIn("source_links", tables)
        self.assertNotIn("board_items", tables)

    def test_limit_text_drops_whole_rows(self):
        rows = []
        for n in range(4):
            rows.append(_add(
                self.conn, "owner-a", "line-1", service="svc%d" % n,
                purpose="purpose %d for the office tool" % n, locator="[vault:box%d]" % n,
            ))
        fitted = ar.limit_text(rows, [], 80)
        self.assertTrue(fitted["omitted"])
        text = fitted["text"]
        for row in rows:
            line = "- " + row["access_id"] + " "
            if row["access_id"] in fitted["omitted"]:
                self.assertNotIn(line, text)
                self.assertIn(row["access_id"], text)
            else:
                self.assertIn(line, text)
                self.assertIn(row["locator"], text)
                self.assertIn(row["purpose"], text)
        self.assertNotIn(text[:40] + "…", text)


class BoardSurvivalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_shelf = shelves.BASE_DIR
        self.old_mem = memory_v2.BASE_DIR
        shelves.BASE_DIR = self.tmp.name
        memory_v2.BASE_DIR = self.tmp.name
        self.uid = "zzaccessregtest"
        self.live = "/data/skv/metadata_store/" + self.uid + ".db"
        self.assertFalse(os.path.exists(self.live))

    def tearDown(self):
        shelves.BASE_DIR = self.old_shelf
        memory_v2.BASE_DIR = self.old_mem
        self.tmp.cleanup()
        self.assertFalse(os.path.exists(self.live))

    def _seed(self):
        conn = shelves.connect(self.uid)
        try:
            return _add(conn, self.uid, "line-1")
        finally:
            conn.close()

    def test_tasks_do_not_remove_the_registry(self):
        row = self._seed()
        added = board.act(self.uid, "", "add", "see access:" + row["access_id"], "task", "recovery")
        item_id = added["id"]
        board.act(self.uid, item_id, "done", result="recovery finished")
        board.act(self.uid, item_id, "remove")
        conn = shelves.connect(self.uid)
        try:
            conn.execute("DELETE FROM board_items")
            conn.commit()
            left = ar.list_line(conn, self.uid, "line-1")
        finally:
            conn.close()
        self.assertEqual([r["access_id"] for r in left], [row["access_id"]])

    def test_render_keeps_access_after_task_clip(self):
        row = self._seed()
        board.act(self.uid, "", "add", "word " * 400, "task", "long task")
        text = board.render(self.uid, tokens=10, chain_id="line-1")
        self.assertIn("(clipped", text)
        self.assertIn(row["access_id"], text)
        self.assertIn(LOC, text)
        self.assertIn(row["purpose"], text)
        other = board.render(self.uid, tokens=10, chain_id="line-2")
        self.assertIn("ABSENT", other)
        self.assertNotIn(row["access_id"], other)
        quiet = board.render(self.uid, tokens=10)
        self.assertNotIn(row["access_id"], quiet)

    def test_bootstrap_variants_keep_every_row(self):
        conn = shelves.connect(self.uid)
        try:
            rows = []
            for n in range(40):
                rows.append(_add(
                    conn, self.uid, "line-1", service="svc%02d" % n,
                    purpose="purpose %02d for the office tool" % n, locator="[vault:box%02d]" % n,
                ))
            _add(conn, "someone-else", "line-1", service="hidden", purpose="not this owner", locator="[vault:hidden]")
            _add(conn, self.uid, "line-9", service="other", purpose="other memory line", locator="[conn:other_line]")
        finally:
            conn.close()
        ids = [r["access_id"] for r in rows]
        old_page = sb.PART_PAGE_CHARS
        sb.PART_PAGE_CHARS = 700
        try:
            part_ids = []
            page = 1
            while True:
                part = sb.build_part(self.uid, "accesses", page, "line-1")
                self.assertTrue(part["ok"])
                part_ids.extend(part["accesses"]["page_ids"])
                for rec in part["accesses"]["records"]:
                    self.assertEqual(part["text"].count("- " + rec["access_id"] + " "), 1)
                    self.assertIn(rec["locator"], part["text"])
                if part["done"]:
                    break
                page += 1
                self.assertLess(page, 30)
            self.assertEqual(sorted(part_ids), sorted(ids))
            self.assertGreater(page, 1)
            board_part = sb.build_part(self.uid, "board", 1, "line-1")
        finally:
            sb.PART_PAGE_CHARS = old_page
        missing = sb.build_part(self.uid, "accesses", 1, "")
        self.assertIn("ABSENT", missing["text"])
        self.assertEqual(missing["accesses"]["records"], [])
        self.assertEqual(sorted(board_part["accesses"]["ids"]), sorted(ids))
        compact = sb.build_compact(self.uid, chain_id="line-1")
        self.assertEqual(
            sorted(r["access_id"] for r in compact["accesses"]["records"]),
            sorted(ids),
        )
        self.assertNotIn("hidden", compact["accesses"]["text"])
        empty_line = sb.build_compact(self.uid, chain_id="line-2")
        self.assertEqual(empty_line["accesses"]["absent"], "empty")
        self.assertIn("ABSENT", empty_line["accesses"]["text"])
        old_cfg = sb._cfg
        sb._cfg = lambda: {
            "enabled": True,
            "budgets": {"raw": 1000, "l1": 1000, "l2": 500, "critical": 200, "constitution": 200, "board": 200, "missing": 200},
            "tail_events": 5,
            "lag_compare_chars": 40,
        }
        try:
            pkg = sb.build_package(self.uid, chain_id="line-1")
        finally:
            sb._cfg = old_cfg
        self.assertTrue(pkg.get("ok"))
        self.assertEqual(sorted(r["access_id"] for r in pkg["accesses"]["records"]), sorted(ids))
        self.assertIn(ids[0], pkg["board"]["text"])

    def test_fit_omits_whole_records(self):
        conn = shelves.connect(self.uid)
        try:
            rows = [
                _add(conn, self.uid, "line-1", service="svc%02d" % n,
                     purpose=("purpose %02d " % n) + ("office " * 20), locator="[vault:box%02d]" % n)
                for n in range(25)
            ]
        finally:
            conn.close()
        pkg = {
            "continuity": {"raw": "R" * 20000, "l1": "L" * 8000, "critical": "C" * 2000},
            "board": {"text": "B" * 4000},
            "accesses": {
                "records": rows,
                "omitted": [],
                "count": len(rows),
                "text": ar.render_records(rows),
            },
        }
        out = sb.fit(pkg, 4500)
        acc = out["accesses"]
        shown = {r["access_id"] for r in acc["records"]}
        omitted = set(acc["omitted"])
        self.assertEqual(shown | omitted, {r["access_id"] for r in rows})
        self.assertFalse(shown & omitted)
        self.assertTrue(omitted)
        for rec in acc["records"]:
            self.assertIn("- " + rec["access_id"] + " ", acc["text"])
            self.assertIn(rec["purpose"], acc["text"])
        for access_id in omitted:
            self.assertNotIn("- " + access_id + " ", acc["text"])
            self.assertIn(access_id, acc["text"])
        self.assertNotIn("[cut]", acc["text"])


class PackSectionTests(unittest.TestCase):
    def test_service_accesses_section_is_separate(self):
        from app.memory_pack888 import build_pack, parse_records, render_document
        tmp = tempfile.TemporaryDirectory()
        try:
            udb = os.path.join(tmp.name, "u.db")
            sdb = os.path.join(tmp.name, "s.db")
            user = sqlite3.connect(udb)
            shared = sqlite3.connect(sdb)
            user.executescript("""
                CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, raw_dialogue TEXT);
                CREATE TABLE summary_l1 (session_id TEXT, topic TEXT, summary_text TEXT, created_at TEXT, from_rowid INT, to_rowid INT);
                CREATE TABLE summary_l2 (user_id TEXT, map_json TEXT);
                CREATE TABLE summary_l2_blocks (id INT, source TEXT, period_from TEXT, period_to TEXT, from_rowid INT, to_rowid INT, text TEXT);
                CREATE TABLE critical_auto (key TEXT, kind TEXT, value TEXT, context TEXT, event_id TEXT, time_str TEXT, hits INT);
                CREATE TABLE board_items (item_id TEXT, kind TEXT, title TEXT, body TEXT, status TEXT, updated_at TEXT, removed INT,
                                          priority INT, parent_id TEXT, waiting_for TEXT, result TEXT, created_at TEXT);
                CREATE TABLE profile_rows (id TEXT, kind TEXT, text TEXT, scope TEXT, status TEXT, created_at TEXT);
            """)
            shared.executescript("""
                CREATE TABLE cubes_new (cube_id TEXT, essence TEXT, rules_markdown TEXT, created_by TEXT, status TEXT);
                CREATE TABLE user_api_keys (user_id TEXT, api_key TEXT, is_active INT, created_at TEXT, key_prefix TEXT, label TEXT);
            """)
            user.execute("INSERT INTO event_metadata (rowid, event_id, time_str, raw_dialogue) VALUES (1,'e1','2026-11-09','hello')")
            shared.execute(
                "INSERT INTO user_api_keys VALUES ('owner-a', ?, 1, '2026-01-01', 'sk_abcd', 'grok')",
                (SECRET,),
            )
            user.commit()
            shared.commit()
            reg = sqlite3.connect(":memory:")
            row = _add(reg, "owner-a", "line-1")
            pack = build_pack(user, shared, owners=["system"])
            pack["service_accesses"] = ar.pack_records(reg, "owner-a", "line-1")
            doc = render_document(pack)
            parsed = {(r["layer"], r["id"]): r["body"] for r in parse_records(doc)}
            self.assertIn(("service_access", row["access_id"]), parsed)
            self.assertIn(LOC, parsed[("service_access", row["access_id"])])
            self.assertIn("## service_accesses", doc)
            self.assertIn("## access_registry", doc)
            self.assertNotIn(SECRET, doc)
            pack.pop("service_accesses")
            quiet = render_document(pack)
            self.assertNotIn("## service_accesses", quiet)
            self.assertIn("ABSENT", ar.pack_records(reg, "", "")[0]["body"])
            user.close()
            shared.close()
            reg.close()
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
