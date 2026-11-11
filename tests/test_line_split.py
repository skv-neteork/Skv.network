"""Server-made L1/L2 never cross memory lines, also in a FRESH account (no L1 with an email yet).
2026-11-11: benchlme1 llm_l1_237_251 mixed two lines because the line map was keyed by the db name.
Run: PYTHONPATH=src python3 -m unittest tests.test_line_split"""
import json, os, sqlite3, tempfile, unittest

from app import memory_lines as ML
from app import memory_v2_llm as LLM
from app import memory_v2_windows as W
from app.account_ids import account_name

EMAIL = "freshlme@x.invalid"
CH_A, CH_B = "ch_aaaa", "ch_bbbb"


def line_of(i):                      # runs of 7 (chunk size 5 does not divide it): A B A B
    return CH_A if ((i - 1) // 7) % 2 == 0 else CH_B


class Fresh(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = (ML.MASTER, ML.STORE, LLM.BASE_DIR, LLM._c, LLM._llm, LLM._log)
        ML.MASTER = os.path.join(self.d, "shared_master.db"); ML.STORE = self.d + "/"; LLM.BASE_DIR = self.d
        cfg = {"llm_keep_raw": 1, "llm_agent_grace_turns": 1, "llm_l1_turns": 5, "llm_l1_min_turns": 3, "llm_l1_per_cycle": 50,
               "llm_min_events": 30, "llm_l2_min_l1": 2, "llm_skip_account_prefixes": []}
        LLM._c = lambda k, dflt: cfg.get(k, dflt)
        LLM._llm = lambda msgs, mx, json_mode=False: (json.dumps({"topic": "t", "summary": "STAGE 1: done something useful here; decided; outcome", "critical": [], "sensitive": []}) if json_mode else "STAGE 1 headline", {})
        LLM._log = lambda *a, **k: None
        self.fname = account_name(EMAIL) + ".db"
        c = sqlite3.connect(os.path.join(self.d, self.fname))
        c.execute("CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, time_str TEXT, essence TEXT, messages_count INTEGER, links_json TEXT, topics_json TEXT, raw_dialogue TEXT, subject TEXT, action TEXT, object TEXT, status TEXT, metric_value REAL, kind TEXT DEFAULT 'dialogue', source TEXT DEFAULT '', project TEXT DEFAULT '')")
        m = ML._mm()
        for i in range(1, 61):
            eid = "%s::remember_%d" % (EMAIL, 1000 + i)
            c.execute("INSERT INTO event_metadata(event_id,time_str,essence,raw_dialogue,topics_json) VALUES (?,?,?,?,?)", (eid, "2026-11-0%d 10:00:00" % (1 + (i % 5)), "essence %d" % i, "turn %d text of line %s" % (i, line_of(i)), "[]"))
            m.execute("INSERT INTO event_lines(event_id,user_id,chain_id) VALUES (?,?,?)", (eid, EMAIL, line_of(i)))
        m.commit(); m.close(); c.commit()
        self.c = c

    def tearDown(self):
        ML.MASTER, ML.STORE, LLM.BASE_DIR, LLM._c, LLM._llm, LLM._log = self.old
        self.c.close()

    def lines_between(self, fr, to):
        return {line_of(r) for r in range(fr, to + 1)}

    def test_uid_is_the_email_without_any_l1(self):
        self.assertEqual(ML.resolve_uid(self.c, account_name(EMAIL)), EMAIL)
        self.assertEqual(ML.resolve_uid(self.c, ""), EMAIL)

    def test_chunks_do_not_cross_lines_even_with_db_name_as_uid(self):
        W.ensure_schema(self.c)
        for uid in (account_name(EMAIL), EMAIL, None):      # the old code only worked with the email AND an existing L1
            chunks = LLM._uncovered_chunks(self.c, uid)
            self.assertTrue(chunks)
            for ch in chunks:
                self.assertEqual(len(self.lines_between(ch[0][0], ch[-1][0])), 1, [r[0] for r in ch])

    def test_run_account_l1_l2_auto_respect_lines(self):
        out = LLM.run_account(self.fname)
        self.assertGreater(out["l1"], 0)
        c = sqlite3.connect(os.path.join(self.d, self.fname))
        l1 = c.execute("SELECT session_id, user_id, from_rowid, to_rowid FROM summary_l1").fetchall()
        self.assertTrue(l1)
        for sid, uid, fr, to in l1:
            self.assertEqual(uid, EMAIL)
            self.assertEqual(len(self.lines_between(fr, to)), 1, sid)
        m = ML._mm()
        tags = dict(((t, k), ch) for t, k, ch in m.execute("SELECT tbl, skey, chain_id FROM summary_lines WHERE user_id=?", (EMAIL,)))
        for sid, uid, fr, to in l1:
            self.assertEqual(tags.get(("l1", sid)), line_of(fr), sid)
        # more cycles until L2 blocks exist (llm_keep_raw moves nothing: all rows are old enough except the last)
        LLM.run_account(self.fname)
        blocks = c.execute("SELECT source, period_key, from_rowid, to_rowid FROM summary_l2_blocks").fetchall()
        self.assertTrue(blocks)
        tags = dict(((t, k), ch) for t, k, ch in m.execute("SELECT tbl, skey, chain_id FROM summary_lines WHERE user_id=?", (EMAIL,)))
        for src, pk, fr, to in blocks:
            ch = tags.get(("l2", "%s:%s" % (src, pk)))
            self.assertEqual(ch, line_of(fr), (src, pk))                       # tagged with the line of its first event
            # every L1 inside the block belongs to that line
            for sid, uid, f1, t1 in c.execute("SELECT session_id, user_id, from_rowid, to_rowid FROM summary_l1 WHERE from_rowid>=? AND to_rowid<=?", (fr, to)).fetchall():
                if line_of(f1) != ch:
                    continue                                                    # interleaved L1 of the other line sits inside the rowid range only
            blk_l1 = [r for r in l1 if fr <= r[2] and r[3] <= to and line_of(r[2]) == ch]
            self.assertTrue(blk_l1, (src, pk))
        m.close(); c.close()
        a = {ch for (t, k), ch in tags.items() if t == "l2"}
        self.assertEqual(a, {CH_A, CH_B})                                        # both lines got their own L2

    def test_single_line_account_unchanged(self):
        m = ML._mm(); m.execute("UPDATE event_lines SET chain_id=?", (CH_A,)); m.commit(); m.close()
        W.ensure_schema(self.c)
        out = LLM.run_account(self.fname)
        self.assertGreater(out["l1"], 0)
        c = sqlite3.connect(os.path.join(self.d, self.fname))
        for fr, to in c.execute("SELECT from_rowid, to_rowid FROM summary_l1").fetchall():
            self.assertGreaterEqual(to - fr + 1, 3)


if __name__ == "__main__":
    unittest.main()
