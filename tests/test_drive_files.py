"""Drive folder: 1 MB gate, line visibility, sync, and no token in the record."""
import json
import logging
import sqlite3
import unittest

from app import board
from app import drive_files as drive
from app.routers.import_dialogs import route_import_text


TOKEN = "refresh-LIVE-TOKEN-SHOULD-NOT-LEAK-99"
MARKER = b"PAYLOAD-MARKER-END"


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.other = sqlite3.connect(":memory:")
        self.store = drive.MemTokens()
        self.disk = drive.MemoryDrive()
        self.board = {}
        self.logs = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.logs.append(record.getMessage())
        logging.getLogger("skv.drive").addHandler(self.handler)
        self.logs.clear()

    def tearDown(self):
        logging.getLogger("skv.drive").removeHandler(self.handler)
        self.conn.close()
        self.other.close()

    def _board(self, user, item_id, title, body):
        self.board[item_id] = {"title": title, "body": body, "user": user}

    def _connect(self, chain="ch_line_a", name="alpha"):
        return drive.connect_token(
            "a@example.invalid", chain, name, TOKEN, self.store, self.disk,
            conn=self.conn, embedder=lambda text: drive._hash_vec(text), board_fn=self._board,
            tag_line=False, now=1_000_000,
        )

    def _line_folder(self):
        root = [node["id"] for node in self.disk.nodes.values() if node["name"] == "SKV" and node["parent"] is None][0]
        return [node["id"] for node in self.disk.nodes.values() if node["parent"] == root][0]

    def test_scope_sees_the_skv_folder_and_refuses_a_whole_disk_list(self):
        url = drive.auth_url("client", "https://skv.example/cb", "state1")
        self.assertIn("https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive", url)
        self.assertNotIn("drive.file", url)
        self.assertIn("name='SKV'", drive.root_skv_query())
        self.assertIn("'root' in parents", drive.root_skv_query())
        with self.assertRaises(ValueError):
            drive.child_query("")

    def test_heavy_file_goes_to_drive_and_small_file_stays_in_memory(self):
        self._connect()
        small = drive.place(
            "a@example.invalid", "ch_line_a", "alpha", b"short note", "note.txt", "a short note",
            mime="text/plain", client=self.disk, conn=self.conn, embedder=lambda text: drive._hash_vec(text),
            board_fn=self._board, now=1_000_100,
        )
        self.assertEqual(small["where"], "memory")
        self.assertNotIn(b"short note".decode(), drive.dump_text(self.conn))
        heavy = b"a" * (drive.HEAVY_BYTES + 1) + MARKER
        saved = drive.place(
            "a@example.invalid", "ch_line_a", "alpha", heavy, "budget.bin", "quarterly zebra budget",
            mime="application/octet-stream", client=self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, now=1_000_200,
        )
        self.assertEqual(saved["where"], "drive")
        self.assertTrue(saved["web_link"].startswith("https://drive.google.com/"))
        blob = drive.dump_text(self.conn) + json.dumps(saved)
        self.assertNotIn(MARKER.decode(), blob)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(TOKEN, "\n".join(self.logs))
        self.assertIn("[vault:drive_oauth]", blob)
        row = self.conn.execute("SELECT vector_json, memory_text FROM drive_files").fetchone()
        self.assertGreater(len(json.loads(row[0])), 0)
        self.assertIn("quarterly zebra budget", row[1])
        found = drive.search("a@example.invalid", "ch_line_a", "quarterly zebra budget", conn=self.conn)
        self.assertEqual(found[0]["name"], "budget.bin")

    def test_manual_change_and_delete_and_daily_sync(self):
        self._connect()
        folder = self._line_folder()
        meta = self.disk.put(folder, "manual.txt", b"alpha recipe for plum jam", "text/plain")
        first = drive.sync(
            "a@example.invalid", "ch_line_a", "alpha", self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, force=True, now=2_000_000,
        )
        self.assertEqual(first["live"], 1)
        found = drive.search("a@example.invalid", "ch_line_a", "plum jam", conn=self.conn)
        self.assertEqual(found[0]["drive_file_id"], meta["id"])
        self.disk.replace(meta["id"], b"alpha recipe now uses quince", "2026-11-10T00:00:00Z")
        drive.sync(
            "a@example.invalid", "ch_line_a", "alpha", self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, force=True, now=2_000_100,
        )
        updated = drive.search("a@example.invalid", "ch_line_a", "quince", conn=self.conn)
        self.assertEqual(updated[0]["drive_file_id"], meta["id"])
        self.assertNotIn("plum", updated[0]["description"])
        skipped = drive.sync(
            "a@example.invalid", "ch_line_a", "alpha", self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, force=False, now=2_000_200,
        )
        self.assertTrue(skipped.get("skipped"))
        self.disk.remove(meta["id"])
        drive.sync(
            "a@example.invalid", "ch_line_a", "alpha", self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, force=True, now=2_000_000 + drive.DAY_S + 5,
        )
        row = self.conn.execute("SELECT status FROM drive_files WHERE drive_file_id=?", (meta["id"],)).fetchone()
        self.assertEqual(row[0], "dead")
        self.assertEqual(drive.search("a@example.invalid", "ch_line_a", "quince", conn=self.conn), [])
        listing = drive.list_files("a@example.invalid", "ch_line_a", conn=self.conn)
        self.assertEqual(listing["title"], "Мой Drive")
        self.assertEqual(listing["files"][0]["status"], "dead")

    def test_same_line_sees_the_file_other_line_and_account_do_not(self):
        self._connect()
        drive.place(
            "a@example.invalid", "ch_line_a", "alpha", b"b" * (drive.HEAVY_BYTES + 2), "shared.bin",
            "shared line lantern map", mime="application/octet-stream", client=self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, now=3_000_000,
        )
        again = drive.search("a@example.invalid", "ch_line_a", "lantern map", conn=self.conn)
        self.assertEqual(len(again), 1)
        self.assertEqual(drive.search("a@example.invalid", "ch_line_b", "lantern map", conn=self.conn), [])
        drive.ensure(self.other)
        self.assertEqual(drive.search("b@example.invalid", "ch_line_a", "lantern map", conn=self.other), [])

    def test_read_pdf_and_text_range(self):
        self._connect()
        folder = self._line_folder()
        pdf = self.disk.put(folder, "note.pdf", b"BT (zebra habitat report) Tj ET", "application/pdf")
        text = self.disk.put(folder, "letters.txt", b"abcdefghijklmnopqrstuvwxyz", "text/plain")
        drive.sync(
            "a@example.invalid", "ch_line_a", "alpha", self.disk, conn=self.conn,
            embedder=lambda text: drive._hash_vec(text), board_fn=self._board, force=True, now=4_000_000,
        )
        got = drive.read_file("a@example.invalid", "ch_line_a", pdf["id"], client=self.disk, conn=self.conn)
        self.assertIn("zebra habitat", got["text"])
        part = drive.read_file("a@example.invalid", "ch_line_a", text["id"], start=0, limit=4, client=self.disk, conn=self.conn)
        nxt = drive.read_file("a@example.invalid", "ch_line_a", text["id"], start=part["next"], limit=4, client=self.disk, conn=self.conn)
        self.assertEqual(part["text"], "abcd")
        self.assertEqual(nxt["text"], "efgh")
        self.assertEqual(drive.read_file("a@example.invalid", "ch_line_b", text["id"], client=self.disk, conn=self.conn)["error"], "not_found")

    def test_no_drive_keeps_small_files_and_refuses_heavy_ones(self):
        refused = drive.place(
            "a@example.invalid", "ch_line_a", "alpha", b"c" * (drive.HEAVY_BYTES + 3), "big.bin", "big",
            conn=self.conn, board_fn=self._board,
        )
        self.assertEqual(refused["error"], "connect_drive")
        self.assertIn("подключи Drive", refused["hint"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM drive_files").fetchone()[0], 0)
        text = ("note " * 200_001)
        cleaned, stats = route_import_text("nobody-drive@example.invalid", text, db=None)
        self.assertIn("подключи Drive", cleaned)
        self.assertEqual(stats.get("drive_hint"), "подключи Drive")
        small, small_stats = route_import_text("nobody-drive@example.invalid", "hello", db=None)
        self.assertNotIn("подключи Drive", small or "")
        self.assertNotIn("drive_hint", small_stats)

    def test_board_folder_is_per_line(self):
        self._connect()
        body = self.board[next(iter(self.board))]["body"]
        self.assertTrue(body.startswith("chain:ch_line_a\n"))
        self.assertIn("Мой Drive", self.board[next(iter(self.board))]["title"])
        rows = [
            {"item_id": "drv_abc", "body": "chain:ch_line_a\nfile"},
            {"item_id": "T50", "title": "task", "body": "work"},
        ]
        self.assertEqual([item["item_id"] for item in board.for_line(rows, "ch_line_a")], ["drv_abc", "T50"])
        self.assertEqual([item["item_id"] for item in board.for_line(rows, "ch_line_b")], ["T50"])
        self.assertEqual([item["item_id"] for item in board.for_line(rows, "")], ["T50"])


if __name__ == "__main__":
    unittest.main()
