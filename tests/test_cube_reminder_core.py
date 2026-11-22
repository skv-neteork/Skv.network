"""Author-cube CORE on cube reminders, once per episode, and the cube-duty reset."""
import os
import sqlite3
import tempfile
import time
import unittest

os.environ.setdefault("SKV_CUBE_REMINDER_CORE", "1")
os.environ.setdefault("SKV_CUBE_REMINDER_CORE_DB", os.path.join(tempfile.mkdtemp(prefix="crc-"), "crc.db"))

from app import cube_reminder_core as crc  # noqa: E402
from app import duty_rules as DR  # noqa: E402
from app.chain_skills import SKILL_MD_CAP  # noqa: E402
from app.cube_harvest import CUBE_ID  # noqa: E402


RULE = "RULE experience cube: publish or duty=cube_nothing + reason."
PART2 = "PART2BODY must stay out of the reminder"


def _chain(path, live_md, mid_md="MIDCORE should not be attached"):
    c = sqlite3.connect(path)
    c.execute("create table cubes_new(cube_id text, status text, links_json text, skill_md text, created_by text, created_at text)")
    mid, live = "cube_mid11111111", "cube_live222222"
    c.execute("insert into cubes_new values(?,?,?,?,?,?)",
              (CUBE_ID, "superseded", '{"superseded_by":"%s"}' % mid, "ROOTCORE", "a@x", "2020-01-01 00:00:00"))
    c.execute("insert into cubes_new values(?,?,?,?,?,?)",
              (mid, "superseded", '{"superseded_by":"%s"}' % live, mid_md, "a@x", "2020-01-02 00:00:00"))
    c.execute("insert into cubes_new values(?,?,?,?,?,?)",
              (live, "community", "{}", live_md, "a@x", "2020-01-03 00:00:00"))
    c.commit()
    c.close()
    return live


class CoreAttachTests(unittest.TestCase):
    def setUp(self):
        self.shared = tempfile.mktemp(suffix=".db")
        self.cache = tempfile.mktemp(suffix=".db")
        self.live = _chain(self.shared, "LIVE CORE line\n\n# PART 2 — REFERENCE\n" + PART2)
        os.environ["SKV_CUBE_REMINDER_CORE"] = "1"

    def tearDown(self):
        for p in (self.shared, self.cache):
            if os.path.exists(p):
                os.remove(p)
        os.environ["SKV_CUBE_REMINDER_CORE"] = "1"

    def dec(self, text, user="agent-a"):
        return crc.decorate(text, user, shared_db=self.shared, db=self.cache)

    def test_four_reminders_carry_live_core_not_the_mid_cube(self):
        mand = DR.mandatory_text("cube", 4)
        nudge = "• CUBE NUDGE: 25 turns since your last cube/cube_nothing. cube_get(cube_id=\"cube_x\")."
        duty = "• CUBE DUTY: the task ended. Write a cube only if it changes the answer."
        for i, text in enumerate((RULE, mand, nudge, duty)):
            out = self.dec(text, "u%d" % i)
            self.assertIn("LIVE CORE line", out)
            self.assertIn(self.live, out)
            self.assertIn("v3", out)
            self.assertNotIn("cube_mid11111111", out)
            self.assertNotIn("MIDCORE", out)
            self.assertNotIn(PART2, out)
            self.assertNotIn("# PART 2", out)
            core = out.split("AUTHOR CUBE CORE (", 1)[1].split("\n", 1)[1]
            self.assertLessEqual(len(core), SKILL_MD_CAP)
            self.assertTrue(text.split("\n", 1)[0] in out)

    def test_core_is_capped_at_skill_md_cap(self):
        os.remove(self.shared)
        huge = ("A" * 8000) + "\n\n# PART 2 — REFERENCE\n" + PART2
        self.live = _chain(self.shared, huge)
        out = self.dec(RULE, "cap-user")
        core = out.split("AUTHOR CUBE CORE (", 1)[1].split("\n", 1)[1]
        self.assertLessEqual(len(core), SKILL_MD_CAP)
        self.assertEqual(len(core), SKILL_MD_CAP)
        self.assertNotIn(PART2, out)

    def test_same_episode_does_not_repeat_core_new_episode_and_new_id_do(self):
        first = self.dec(RULE)
        second = self.dec(DR.mandatory_text("cube", 5))
        self.assertIn("AUTHOR CUBE CORE (", first)
        self.assertNotIn("AUTHOR CUBE CORE (", second)
        self.assertEqual(second, DR.mandatory_text("cube", 5))
        crc.note_complied("agent-a", db=self.cache)
        again = self.dec("• CUBE DUTY: the task ended.")
        self.assertIn("LIVE CORE line", again)
        c = sqlite3.connect(self.shared)
        c.execute("update cubes_new set status='superseded', links_json=? where cube_id=?",
                  ('{"superseded_by":"cube_new333333"}', self.live))
        c.execute("insert into cubes_new values(?,?,?,?,?,?)",
                  ("cube_new333333", "community", "{}", "NEWCORE\n\n# PART 2 — REFERENCE\n" + PART2, "a@x", "2020-01-04 00:00:00"))
        c.commit(); c.close()
        nxt = self.dec(RULE)
        self.assertIn("cube_new333333", nxt)
        self.assertIn("NEWCORE", nxt)
        self.assertNotIn(PART2, nxt)
        self.assertNotIn("AUTHOR CUBE CORE (", self.dec(RULE))

    def test_flag_off_keeps_the_reminder_without_core(self):
        os.environ["SKV_CUBE_REMINDER_CORE"] = "0"
        try:
            out = self.dec(RULE)
        finally:
            os.environ["SKV_CUBE_REMINDER_CORE"] = "1"
        self.assertEqual(out, RULE)
        self.assertNotIn("AUTHOR CUBE CORE (", out)

    def test_lookup_failure_returns_the_reminder(self):
        out = crc.decorate(RULE, "agent-a", shared_db="/no/such/cube-reminder-core.db", db=self.cache)
        self.assertEqual(out, RULE)

    def test_empty_core_says_so_in_one_line(self):
        os.remove(self.shared)
        _chain(self.shared, "")
        out = self.dec(RULE, "empty-user")
        self.assertTrue(out.startswith(RULE))
        extra = out[len(RULE):].strip()
        self.assertIn("missing", extra)
        self.assertEqual(len(extra.splitlines()), 1)
        self.assertNotIn("LIVE CORE", out)

    def test_shrink_and_clip_keep_the_block(self):
        long = RULE + "\n\nAUTHOR CUBE CORE (cube_live222222, v3):\n" + ("M" * 1000)
        self.assertEqual(crc.shrink_text(long, 300), long)
        self.assertEqual(crc.clip_duty(long), long)
        self.assertEqual(len(crc.shrink_text("x" * 500, 300)), 300 + len("…(trimmed)"))
        self.assertFalse(crc.carries_core("RULE vote: rate it"))
        self.assertTrue(crc.carries_core({"rules": [long]}))


class DutyResetTests(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.nosh = "/nonexistent_shared.db"

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)

    def _pin(self, scope="s1"):
        last = []
        for _ in range(8):
            last = DR.on_turn("u@x", scope, db=self.db, shared_db=self.nosh, events={"cube"}, applicable={"cube": True}).get("rules") or []
        self.assertTrue(any(x.startswith("MANDATORY: cube ") for x in last), last)
        return last

    def test_publish_resets_mandatory_on_every_scope(self):
        self._pin("s1")
        self._pin("s2")
        self.assertTrue(DR.note_cube_published("u@x", db=self.db))
        nxt = DR.on_turn("u@x", "s1", db=self.db, shared_db=self.nosh, events={"cube"}, applicable={"cube": True}).get("rules") or []
        self.assertFalse(any(x.startswith("MANDATORY: cube ") for x in nxt))
        self.assertFalse(any(x.startswith("RULE experience cube") for x in nxt))
        shown = False
        for _ in range(6):
            nxt = DR.on_turn("u@x", "s1", db=self.db, shared_db=self.nosh, events={"cube"}, applicable={"cube": True}).get("rules") or []
            self.assertFalse(any(x.startswith("MANDATORY: cube ") for x in nxt))
            if any(x.startswith("RULE experience cube") for x in nxt):
                shown = True
                break
        self.assertTrue(shown)
        st = {r["scope"]: r for r in DR.stats("u@x", db=self.db) if r["duty"] == "cube"}
        self.assertEqual(st["s1"]["ignored"], 0)
        self.assertEqual(st["s1"]["pinned"], 0)
        self.assertEqual(st["s2"]["ignored"], 0)
        self.assertEqual(st["s2"]["pinned"], 0)

    def test_pinned_but_not_pending_still_sees_a_new_cube(self):
        self._pin("s1")
        now = time.time()
        c = sqlite3.connect(self.db)
        c.execute("update dr_duty set pending=0, pinned=1, ignored=6, last_shown_t=? where user=? and scope=? and duty='cube'",
                  (now - 100, "u@x", "s1"))
        c.commit(); c.close()
        sh = tempfile.mktemp(suffix=".db")
        sc = sqlite3.connect(sh)
        sc.execute("create table cubes_new(cube_id text, created_by text, created_at text)")
        sc.execute("insert into cubes_new values(?,?,?)", ("c1", "u@x", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))))
        sc.commit(); sc.close()
        try:
            rules = DR.on_turn("u@x", "s1", db=self.db, shared_db=sh).get("rules") or []
        finally:
            os.remove(sh)
        self.assertFalse(any(x.startswith("MANDATORY: cube ") for x in rules))
        st = {r["duty"]: r for r in DR.stats("u@x", "s1", db=self.db)}
        self.assertEqual(st["cube"]["ignored"], 0)
        self.assertEqual(st["cube"]["pinned"], 0)

    def test_cube_nothing_needs_a_reason(self):
        self._pin("s1")
        done, *_ = DR.signals({"duty": "cube_nothing", "duty_reason": ""}, {})
        self.assertNotIn("cube", done)
        rules = DR.on_turn("u@x", "s1", db=self.db, shared_db=self.nosh, done=done, events={"cube"}, applicable={"cube": True}).get("rules") or []
        self.assertTrue(any(x.startswith("MANDATORY: cube ") for x in rules))
        done, *_ = DR.signals({"duty": "cube_nothing", "duty_reason": "nothing worth sharing"}, {})
        self.assertIn("cube", done)
        # harvest aliases still close without that reason rule
        done_h, *_ = DR.signals({"duty": "skills_none"}, {})
        self.assertIn("cube", done_h)
        rules = DR.on_turn("u@x", "s1", db=self.db, shared_db=self.nosh, done=done, events={"cube"}, applicable={"cube": True}).get("rules") or []
        self.assertFalse(any(x.startswith("MANDATORY: cube ") for x in rules))
        nxt = DR.on_turn("u@x", "s1", db=self.db, shared_db=self.nosh, events={"cube"}, applicable={"cube": True}).get("rules") or []
        self.assertFalse(any(x.startswith("MANDATORY: cube ") for x in nxt))
        self.assertFalse(any(x.startswith("RULE experience cube") for x in nxt))
        shown = False
        for _ in range(6):
            nxt = DR.on_turn("u@x", "s1", db=self.db, shared_db=self.nosh, events={"cube"}, applicable={"cube": True}).get("rules") or []
            self.assertFalse(any(x.startswith("MANDATORY: cube ") for x in nxt))
            if any(x.startswith("RULE experience cube") for x in nxt):
                shown = True
                break
        self.assertTrue(shown)


class DeliveryTests(unittest.TestCase):
    def test_nudge_and_duty_hint_go_through_decorate(self):
        import app.cubes_v2 as cv
        orig_r, orig_l = crc.resolve_live, crc.load_core
        crc.resolve_live = lambda shared_db=None: ("cube_live222222", 3)
        crc.load_core = lambda cube_id, shared_db=None: "NUDGECORE"
        os.environ["SKV_CUBE_NUDGE_TURNS"] = "1"
        os.environ["SKV_CUBE_REMINDER_CORE"] = "1"
        try:
            c = sqlite3.connect(":memory:")
            c.execute("create table cubes_new(cube_id text)")
            cv.ensure(c)
            notes = cv.on_remember(c, "nudge-user", 1, turn=True)
            self.assertTrue(any("CUBE NUDGE" in n and "NUDGECORE" in n for n in notes))
            notes2 = cv.on_remember(c, "nudge-user", 2, turn=True)
            self.assertTrue(any("CUBE NUDGE" in n for n in notes2))
            self.assertFalse(any("NUDGECORE" in n for n in notes2))
            cv.on_remember(c, "duty-user", 3, task_done=True)
            held = cv.duty_hints(c, "duty-user")
            self.assertFalse(any(h.startswith("• CUBE DUTY:") for h in held))
            hints = cv.duty_hints(c, "duty-user")
            self.assertTrue(any(h.startswith("• CUBE DUTY:") and "NUDGECORE" in h for h in hints))
            again = cv.duty_hints(c, "duty-user")
            self.assertTrue(any(h.startswith("• CUBE DUTY:") for h in again))
            self.assertFalse(any("NUDGECORE" in h for h in again))
        finally:
            crc.resolve_live = orig_r
            crc.load_core = orig_l
            os.environ.pop("SKV_CUBE_NUDGE_TURNS", None)

    def test_compact_diet_keeps_the_core_block(self):
        import turn_diet as td
        path = tempfile.mktemp(suffix=".db")
        token = "MANUALTOKEN"
        duty = "• CUBE NUDGE: 25 turns.\n\nAUTHOR CUBE CORE (cube_z, v2):\n" + token + ("M" * 800)
        ctx = {"user": "diet-user", "session": "s", "verbose": False, "eligible": True, "draft": "",
               "checklist": [], "slq": True, "prof_extra": {}, "facts": [], "cited": [], "tools": set(), "params": set()}
        try:
            td.apply(path, {"verdict": "pass", "duties": [duty], "seal": "s"}, ctx)
            resp, mode = td.apply(path, {"verdict": "pass", "duties": [duty], "seal": "s"}, ctx)
            self.assertEqual(mode, "compact")
            blob = str(resp.get("duties"))
            self.assertIn("AUTHOR CUBE CORE (", blob)
            self.assertIn(token, blob)
            self.assertTrue(td._has_author_core(duty))
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_mcp_shrink_and_dumps_keep_core(self):
        import mcp_skv
        duty = {"id": "duty_rules", "severity": "critical", "rules": [
            "RULE experience cube: go\n\nAUTHOR CUBE CORE (cube_z, v2):\n" + ("C" * 4000)
        ]}
        shrunk = mcp_skv._shrink(duty, 300)
        self.assertIn("C" * 4000, shrunk["rules"][0])
        blob = {"duties": [shrunk], "facts": ["F" * 20000], "seal": "s", "verdict": "pass"}
        raw = mcp_skv._dumps(blob)
        self.assertIn("AUTHOR CUBE CORE (", raw)
        self.assertIn("C" * 4000, raw)
        self.assertNotIn("…(trimmed; use detail/page params)", raw)


class LiveChainTests(unittest.TestCase):
    def test_walker_does_not_stop_on_a_superseded_root(self):
        shared = "/data/skv/metadata_store/shared_master.db"
        self.assertTrue(os.path.isfile(shared))
        cid, hops = crc.resolve_live()
        c = sqlite3.connect("file:%s?mode=ro" % shared, uri=True)
        try:
            st = c.execute("select coalesce(status,'') from cubes_new where cube_id=?", (cid,)).fetchone()
            self.assertIsNotNone(st)
            self.assertNotEqual(st[0], "superseded")
            self.assertGreater(hops, 1)
            for old in (CUBE_ID, "cube_3de96286fc73"):
                row = c.execute("select coalesce(status,'') from cubes_new where cube_id=?", (old,)).fetchone()
                if row and row[0] == "superseded":
                    self.assertNotEqual(cid, old)
            body = crc.load_core(cid)
        finally:
            c.close()
        self.assertGreater(len(body), 100)
        self.assertLessEqual(len(body), SKILL_MD_CAP)
        self.assertNotIn("# PART 2", body)
        text = crc.decorate(RULE, "live-chain-user")
        self.assertIn(cid, text)
        self.assertNotIn("# PART 2", text)


if __name__ == "__main__":
    unittest.main()
