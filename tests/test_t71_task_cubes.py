"""T71: task L1 start -> draft task cube (or suggestion). End keeps that cube and asks for a real experience cube."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, "/root/skv-core/src")
from app import task_cubes as TC  # noqa: E402

START = "started task: migrate the billing cron from systemd timers to a queue worker and keep the retries"


def mkdb():
    p = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(p)
    c.execute("""CREATE TABLE cubes_new (cube_id TEXT PRIMARY KEY, essence TEXT NOT NULL, subject_action_object TEXT NOT NULL, rules_markdown TEXT NOT NULL,
                 evidence TEXT NOT NULL, source_session TEXT, status TEXT DEFAULT 'community', created_by TEXT, kind TEXT DEFAULT 'moment', source TEXT DEFAULT 'agent',
                 is_constitutional BOOLEAN DEFAULT 0, updated_at TIMESTAMP)""")
    c.execute("CREATE TABLE cube_links (src TEXT, dst TEXT, kind TEXT, created_by TEXT, created_at TEXT, PRIMARY KEY (src, dst, kind))")
    TC.ensure(c)
    return p, c


def en(x):
    return x


class TaskCubeTests(unittest.TestCase):
    def setUp(self):
        self.p, self.c = mkdb()

    def tearDown(self):
        self.c.close(); os.remove(self.p)

    def proc(self, l1, uid="a@x.invalid", **kw):
        r = TC.process(self.c, uid, "s1", l1, translate=en, **kw)
        self.c.commit()
        return r

    def test_start_creates_open_task_cube(self):
        r = self.proc(START)
        self.assertTrue(r["task_cube"].startswith("cube_"))
        row = self.c.execute("select kind,status,created_by,rules_markdown from cubes_new where cube_id=?", (r["task_cube"],)).fetchone()
        self.assertEqual(row[:3], ("task", "open", "a@x.invalid"))
        self.assertIn("billing cron", row[3])
        self.assertEqual(self.c.execute("select state from task_cubes").fetchone()[0], "open")
        self.assertEqual(self.proc(START)["task_cube"], r["task_cube"])   # same task twice: no second cube

    def test_start_with_matching_experience_suggests_and_creates_nothing(self):
        self.c.execute("insert into cubes_new (cube_id,essence,subject_action_object,rules_markdown,evidence,status,created_by,kind) values "
                       "('cube_exp1','migrate billing cron systemd timers to queue worker','billing cron migration','Use a queue worker with retries','e','community','b@x.invalid','lifehack')")
        r = self.proc(START)
        self.assertEqual(r["match"]["id"], "cube_exp1")
        self.assertNotIn("task_cube", r)
        self.assertEqual(self.c.execute("select count(*) from cubes_new where kind='task'").fetchone()[0], 0)
        note = TC.turn_note(self.c, "a@x.invalid", "", r)
        self.assertIn("cube_exp1", note); self.assertLess(len(note), 290)

    def test_end_keeps_the_task_cube_and_asks_for_a_real_one(self):
        cid = self.proc(START)["task_cube"]
        r = self.proc("finished, solution: moved to a queue worker with exponential retries and a dead-letter queue")
        self.assertTrue(r.get("remind_cube"))
        self.assertNotIn("experience", r)
        self.assertEqual(r.get("task_cube"), cid)
        row = self.c.execute("select kind,status from cubes_new where cube_id=?", (cid,)).fetchone()
        self.assertEqual(row, ("task", "open"))
        self.assertEqual(self.c.execute("select state, experience_id from task_cubes").fetchone(), ("closed", None))
        note = TC.turn_note(self.c, "a@x.invalid", "", r)
        self.assertIn("cube_nothing", note)
        self.assertNotIn("is now an experience cube", note)
        self.assertEqual(self.proc("finished, solution: again something else here"), {})

    def test_end_after_match_does_not_write_a_moment(self):
        self.c.execute("insert into cubes_new (cube_id,essence,subject_action_object,rules_markdown,evidence,status,created_by,kind) values "
                       "('cube_exp1','migrate billing cron systemd timers to queue worker','billing cron migration','Use a queue worker with retries','e','community','b@x.invalid','lifehack')")
        self.proc(START)
        r = self.proc("finished, solution: used a queue worker, retries via backoff and a scheduler lock")
        self.assertTrue(r.get("remind_cube"))
        self.assertNotIn("experience", r)
        self.assertEqual(self.c.execute("select count(*) from cubes_new where kind='moment'").fetchone()[0], 0)
        self.assertEqual(self.c.execute("select count(*) from cube_links").fetchone()[0], 0)
        self.assertEqual(self.c.execute("select cube_id from cubes_new").fetchone()[0], "cube_exp1")

    def test_scrub_removes_email_keys_code_ip_path(self):
        dirty = ("started task: fix the mailer for deniz@example.com using key " + "sk_" + "live_abcdefghijklmnopqrstuvwx" + " on 10.1.2.3 ```python\n"
                 "import smtplib\nsmtp = smtplib.SMTP('h')\n``` under /home/deniz/app/mail.py and retry the send queue")
        r = self.proc(dirty)
        cid = r.get("task_cube")
        self.assertTrue(cid, r)
        blob = " ".join(map(str, self.c.execute("select essence,subject_action_object,rules_markdown,evidence from cubes_new where cube_id=?", (cid,)).fetchone()))
        for bad in ("deniz@example.com", "sk_live_abcdefgh", "10.1.2.3", "import smtplib", "/home/deniz", "SMTP("):
            self.assertNotIn(bad, blob)
        self.assertIn("[code]", blob)
        fake = "api_" + "key=" + "".join(["ABCDEF12", "34567890", "ABCDEF12", "34567890"])
        t = TC.scrub_text("password is hunter22 " + fake + " call +1 415 555 0100", ["hunter22"])
        self.assertNotIn("hunter22", t); self.assertNotIn("ABCDEF1234567890", t); self.assertNotIn("415 555", t)
        kept = TC.scrub_text("bind 127.0.0.1 and localhost while closing B20 T81 and T_BUILD_NOTE")
        self.assertIn("127.0.0.1", kept)
        self.assertIn("localhost", kept)
        self.assertNotIn("B20", kept)
        self.assertNotIn("T81", kept)
        self.assertNotIn("T_BUILD_NOTE", kept)

    def test_not_english_is_translated_or_skipped(self):
        r = TC.process(self.c, "a@x.invalid", "s1", "начал задачу: перенести cron биллинга на очередь", translate=lambda t: "migrate the billing cron to a queue")
        self.assertTrue(r.get("task_cube"), r)
        r2 = TC.process(self.c, "b@x.invalid", "s1", "начал задачу: перенести задачу биллинга на очередь воркеров", translate=lambda t: "")
        self.assertIn("not English", r2["skipped"])
        self.assertEqual(self.c.execute("select count(*) from cubes_new where created_by='b@x.invalid'").fetchone()[0], 0)

    def test_detect_phrases_flag_and_order(self):
        d = TC.detect("закончил, решение: поставил очередь. начал задачу: новый отчёт по продажам")
        self.assertIn("поставил очередь", d["end"]); self.assertIn("новый отчёт", d["start"]); self.assertNotIn("новый отчёт", d["end"])
        self.assertEqual(TC.detect("some plain l1 text here", "start")["start"], "some plain l1 text here")
        self.assertEqual(TC.detect("plain solution text", "end")["end"], "plain solution text")
        self.assertEqual(TC.detect("just a normal L1 summary of work done"), {"start": None, "end": None})

    def test_answer_link_notifies_author_once(self):
        cid = self.proc(START)["task_cube"]
        self.c.execute("insert into cubes_new (cube_id,essence,subject_action_object,rules_markdown,evidence,status,created_by,kind) values ('cube_ans','x y z','t','r','e','community','b@x.invalid','lifehack')")
        self.assertFalse(TC.notify_answer(self.c, "cube_ans", cid, "a@x.invalid"))   # own answer: no note
        self.assertTrue(TC.notify_answer(self.c, "cube_ans", cid, "b@x.invalid"))
        self.c.commit()
        note = TC.turn_note(self.c, "a@x.invalid", "unrelated message", {})
        self.assertIn("cube_ans", note); self.assertIn("cube_vote", note)
        self.assertEqual(TC.turn_note(self.c, "a@x.invalid", "unrelated message", {}), "")   # seen
        # still works after the task tracking row closes (the task cube stays)
        self.proc("finished, solution: queue worker with retries and locking")
        TC.notify_answer(self.c, "cube_ans", cid, "b@x.invalid")
        self.assertIn("cube_ans", TC.turn_note(self.c, "a@x.invalid", "", {}))

    def test_open_task_shown_to_similar_agent_once(self):
        cid = self.proc(START)["task_cube"]
        q = "how do I migrate billing cron from systemd timers to a queue worker"
        t1 = TC.open_tasks_for(self.c, "b@x.invalid", q)
        self.assertEqual([x["id"] for x in t1], [cid])
        self.assertEqual(TC.open_tasks_for(self.c, "b@x.invalid", q), [])           # once
        self.assertEqual(TC.open_tasks_for(self.c, "a@x.invalid", q), [])           # not to the author
        self.assertEqual(TC.open_tasks_for(self.c, "c@x.invalid", "bake a chocolate cake recipe"), [])

    def test_disabled(self):
        os.environ["SKV_TASK_CUBES"] = "0"
        try:
            self.assertFalse(TC.enabled())
        finally:
            os.environ.pop("SKV_TASK_CUBES")


if __name__ == "__main__":
    unittest.main()
