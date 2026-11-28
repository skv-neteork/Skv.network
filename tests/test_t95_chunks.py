"""T95 step 0: 350/70 chunks, parent score, stale pending_vector label."""
import math
import os
import sqlite3
import tempfile
import unittest

import zlib

from app.search_v2 import (
    CHUNK_HI,
    CHUNK_LO,
    CHUNK_OVERLAP,
    PARENT_BONUS,
    PARENT_COS_FLOOR,
    _chunks,
    event_text,
    flip_active_where_indexed,
    parent_score,
)


def _words(n, word="alpha"):
    return " ".join([word] * n)


class ChunkCut(unittest.TestCase):
    def test_short_event_is_one_piece(self):
        text = "A short note about the port."
        self.assertEqual(_chunks(text), [text])

    def test_empty_is_empty(self):
        self.assertEqual(_chunks(""), [])
        self.assertEqual(_chunks("   \n"), [])

    def test_long_record_stays_in_the_window_and_overlaps(self):
        # A sentence end near the 350 target, then more text.
        head = _words(40, "lead") + ". "
        # pad so the period lands inside [300..360]
        while len(head) < 340:
            head = "lead " + head
        tail = _words(80, "tail") + "."
        text = head + tail
        self.assertGreater(len(text), CHUNK_HI)
        parts = _chunks(text)
        self.assertGreaterEqual(len(parts), 2)
        for part in parts[:-1]:
            self.assertGreaterEqual(len(part), CHUNK_LO)
            self.assertLessEqual(len(part), CHUNK_HI)
        self.assertLessEqual(len(parts[-1]), CHUNK_HI)
        # overlap: the next piece starts CHUNK_OVERLAP before the previous end
        end0 = len(parts[0])
        self.assertTrue(parts[1].startswith(text[end0 - CHUNK_OVERLAP:end0].lstrip()[:12]) or text[end0 - CHUNK_OVERLAP:end0][:8] in parts[1])

    def test_cut_prefers_a_sentence_end_inside_the_window(self):
        body = ("x" * 320) + ". " + ("y" * 200)
        parts = _chunks(body)
        self.assertTrue(parts[0].endswith("."))
        self.assertLessEqual(len(parts[0]), CHUNK_HI)
        self.assertGreaterEqual(len(parts[0]), CHUNK_LO)

    def test_token_counter_shrinks_a_dense_piece(self):
        text = "word " * 200
        parts = _chunks(text, count_tokens=lambda s: len(s), token_limit=128)
        self.assertTrue(parts)
        for part in parts:
            self.assertLessEqual(len(part), 128)


class ParentScore(unittest.TestCase):
    def test_one_slot_and_the_bonus_uses_chunks_only(self):
        chunks = [("ev1#0", 0.50), ("ev1#1", 0.80), ("ev1#2", 0.20), ("ev2#0", 0.70)]
        events = [("ev1", 0.90), ("ev3", 0.40)]
        scored = dict(parent_score(chunks, events))
        self.assertEqual(set(scored), {"ev1", "ev2", "ev3"})
        # ev1 max is the whole-event 0.90; two chunks clear the floor (0.50 and 0.80)
        n_hits = 2
        self.assertAlmostEqual(scored["ev1"], 0.90 + PARENT_BONUS * math.log(1 + n_hits))
        self.assertAlmostEqual(scored["ev2"], 0.70 + PARENT_BONUS * math.log(1 + 1))
        self.assertAlmostEqual(scored["ev3"], 0.40)
        self.assertGreaterEqual(PARENT_COS_FLOOR, 0.45)
        # best first
        order = [e for e, _s in parent_score(chunks, events)]
        self.assertEqual(order[0], "ev1")


class ArchivedBody(unittest.TestCase):
    def test_marker_uses_the_compressed_archive(self):
        body = "chat import body that search should index"
        blob = zlib.compress(body.encode("utf-8"))
        self.assertEqual(event_text("[archived] chat_1", "", blob), body)
        self.assertEqual(event_text("Q: live\nA: answer", "", blob), "Q: live\nA: answer")
        self.assertEqual(event_text("[archived] chat_1", "", None), "")


class StatusLabel(unittest.TestCase):
    def test_flip_only_where_a_vector_exists(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            c = sqlite3.connect(path)
            c.execute("CREATE TABLE event_metadata (event_id TEXT, status TEXT)")
            c.execute("CREATE TABLE pvec_mml12 (event_id TEXT)")
            c.executemany("INSERT INTO event_metadata VALUES (?,?)", [
                ("keep", "pending_vector"),
                ("also", None),
                ("miss", "pending_vector"),
                ("leave", "quarantine"),
            ])
            c.executemany("INSERT INTO pvec_mml12 VALUES (?)", [("keep",), ("also",), ("leave",)])
            n = flip_active_where_indexed(c, "pvec_mml12")
            c.commit()
            rows = dict(c.execute("SELECT event_id, coalesce(status,'') FROM event_metadata"))
            self.assertEqual(n, 2)
            self.assertEqual(rows["keep"], "active")
            self.assertEqual(rows["also"], "active")
            self.assertEqual(rows["miss"], "pending_vector")
            self.assertEqual(rows["leave"], "quarantine")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
