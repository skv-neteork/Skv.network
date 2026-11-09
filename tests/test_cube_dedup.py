"""B2 dedup, confirmations, rank, scrub, hook trigger, RATE duty."""
import json
import math
import os
import sqlite3
import unittest

os.environ.setdefault("SKV_CUBE_TRANSLATE", "0")

from app import cube_dedup as dd
from app import cubes_v2 as cv2
from app.cube_suggest import trigger_match


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE cubes_new (
        cube_id TEXT PRIMARY KEY, essence TEXT, subject_action_object TEXT, rules_markdown TEXT,
        evidence TEXT, status TEXT, created_by TEXT, kind TEXT, skill_md TEXT, hooks TEXT,
        carrier TEXT, parent_id TEXT, links_json TEXT, vector TEXT, created_at TEXT)""")
    dd.ensure(c)
    return c


def _skill(topic, steps, hooks, problem="the upload fails on a flaky link"):
    skill = "# Steps\n" + "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(steps))
    hook_rows = [{"when": h, "do": "retry the call"} for h in hooks]
    parts = dd.parts_from(topic=topic, problem=problem, hooks=hook_rows, steps=steps, skill_md=skill, rules=skill)
    return parts, skill, json.dumps(hook_rows)


def _put(c, cube_id, topic, steps, hooks, vector=None, author="author@example.invalid", kind="skill"):
    parts, skill, hooks_json = _skill(topic, steps, hooks)
    c.execute("""INSERT INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, skill_md, hooks, carrier)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (cube_id, parts["problem"], topic, skill, "", "community", author, kind, skill, hooks_json, "skill"))
    dd.stamp(c, cube_id, parts, vector=vector)
    row = dd.load_candidates(c, kind)[0] if False else None
    cand = [x for x in dd.load_candidates(c, kind) if x["cube_id"] == cube_id][0]
    if vector:
        cand["vector"] = vector
    return cand


def _draft_from(cand, **kw):
    parts = dd.parts_from(topic=kw.get("topic", cand.get("norm_text", "").split("\n")[0]), problem=kw.get("problem", "the upload fails on a flaky link"),
                          hooks=kw.get("hooks", cand["hook_rows"]), steps=kw.get("steps", cand["steps"]))
    # rebuild parts explicitly
    parts = {
        "topic": dd._clean_piece(kw.get("topic", "retry a flaky upload")),
        "problem": dd._clean_piece(kw.get("problem", "the upload fails on a flaky link")),
        "hooks": [dd._clean_piece(h["when"] if isinstance(h, dict) else h) for h in kw.get("hooks", cand["hook_rows"])],
        "hook_rows": kw.get("hooks", cand["hook_rows"]),
        "steps": [dd._clean_piece(s) for s in kw.get("steps", cand["steps"])],
        "result": "",
        "requirements": kw.get("requirements", cand.get("requirements") or []),
    }
    return {"kind": kw.get("kind", "skill"), "parts": parts, "steps_sha": dd.steps_sha(parts),
            "norm_text": dd.norm_text(parts), "vector": kw.get("vector", cand.get("vector"))}


class DedupTests(unittest.TestCase):
    def test_exact_copy_is_duplicate_without_insert(self):
        c = _db()
        hooks = [{"when": "the upload returns a timeout", "do": "retry the call"}]
        steps = ["call the upload endpoint", "wait and retry twice"]
        cand = _put(c, "cube_canon", "retry a flaky upload", steps, ["the upload returns a timeout"])
        draft = _draft_from(cand, topic="retry a flaky upload", steps=steps, hooks=hooks)
        plan = dd.classify(draft, [cand])
        self.assertEqual(plan["result"], "duplicate")
        self.assertEqual(plan["canonical_cube_id"], "cube_canon")
        self.assertIn("next", plan)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM cubes_new").fetchone()[0], 1)

    def test_same_steps_on_another_subject_is_new(self):
        c = _db()
        hooks = [{"when": "the upload returns a timeout", "do": "retry the call"}]
        steps = ["call the upload endpoint", "wait and retry twice"]
        cand = _put(c, "cube_canon", "retry a flaky upload", steps, ["the upload returns a timeout"])
        draft = _draft_from(cand, topic="drain a worker queue before restart", steps=steps, hooks=hooks, vector=None)
        draft["vector"] = None
        plan = dd.classify(draft, [cand])
        self.assertEqual(plan["result"], "new")

    def test_paraphrase_over_093_is_duplicate(self):
        c = _db()
        hooks = [{"when": "the upload returns a timeout", "do": "retry the call"}]
        vec = [1.0, 0.0]
        other = [0.96, math.sqrt(1 - 0.96 ** 2)]
        cand = _put(c, "cube_canon", "retry a flaky upload", ["call the upload endpoint", "wait and retry twice"],
                    ["the upload returns a timeout"], vector=vec)
        draft = _draft_from(cand, topic="retry a flaky upload",
                            steps=["invoke the upload endpoint", "pause then try two more times"],
                            hooks=hooks, vector=other)
        plan = dd.classify(draft, [cand])
        self.assertGreaterEqual(plan["similarity"], 0.93)
        self.assertEqual(plan["result"], "duplicate")

    def test_added_step_is_pending_version(self):
        c = _db()
        hooks = [{"when": "the upload returns a timeout", "do": "retry the call"}]
        vec = [1.0, 0.0]
        cand = _put(c, "cube_canon", "retry a flaky upload", ["call the upload endpoint", "wait and retry twice"],
                    ["the upload returns a timeout"], vector=vec)
        draft = _draft_from(cand, steps=["call the upload endpoint", "wait and retry twice", "mail the on-call channel"],
                            hooks=hooks, vector=vec)
        plan = dd.classify(draft, [cand])
        self.assertEqual(plan["result"], "near_duplicate")
        self.assertIn("mail the on-call channel", plan["diff"]["added_steps"])
        out = dd.propose_version(c, "cube_canon", {"topic": "retry a flaky upload", "rules": "1. call\n2. wait\n3. mail",
                                                   "diff": plan["diff"]}, "near_duplicate", "other@example.invalid")
        c.commit()
        self.assertEqual(c.execute("SELECT status FROM cubes_new WHERE cube_id='cube_canon'").fetchone()[0], "community")
        self.assertEqual(c.execute("SELECT status FROM cubes_new WHERE cube_id=?", (out["cube_id"],)).fetchone()[0], "pending_version")
        self.assertTrue(c.execute("SELECT 1 FROM court_queue WHERE cube_id='cube_canon'").fetchone())

    def test_opposite_hook_is_conflict(self):
        vec = [1.0, 0.0]
        hooks_old = [{"when": "the upload returns a timeout", "do": "retry the call"}]
        hooks_new = [{"when": "the upload returns a timeout", "do": "do not retry the call"}]
        cand = {"cube_id": "cube_canon", "kind": "skill", "status": "community", "steps_sha": "x",
                "norm_text": "retry", "hooks": ["the upload returns a timeout"], "hook_rows": hooks_old,
                "steps": ["call the upload endpoint", "wait and retry twice"], "requirements": [], "vector": vec}
        parts = dd.parts_from(topic="retry a flaky upload", problem="the upload fails", hooks=hooks_new,
                              steps=["call the upload endpoint", "wait and retry twice"])
        draft = {"kind": "skill", "parts": parts, "steps_sha": dd.steps_sha(parts), "norm_text": dd.norm_text(parts), "vector": vec}
        plan = dd.classify(draft, [cand])
        self.assertEqual(plan["result"], "conflict")
        self.assertTrue(plan["court"])

    def test_confirm_twice_is_one_vote_and_author_does_not_count(self):
        c = _db()
        _put(c, "cube_canon", "retry a flaky upload", ["call the upload endpoint", "wait and retry twice"],
             ["the upload returns a timeout"], author="author@example.invalid")
        author = dd.confirm(c, "cube_canon", "author@example.invalid", "ok", "i wrote this skill and it worked")
        self.assertFalse(author["counted"])
        self.assertEqual(author["reason"], "author")
        first = dd.confirm(c, "cube_canon", "reader@example.invalid", "ok", "ran it on a staging upload", agent_id="grok-a")
        second = dd.confirm(c, "cube_canon", "reader@example.invalid", "fail", "same account other agent", agent_id="grok-b")
        self.assertTrue(first["counted"])
        self.assertEqual(second["vote"], "one")
        self.assertEqual(second["votes"], 1)
        rank = dd.recompute_rank(c, "cube_canon")
        rows = dd.confirmation_rows(c, "cube_canon", "1", "author@example.invalid")
        self.assertEqual(len(rows), 1)
        self.assertGreater(rank, 0)
        bare = dd.rank_score(1, dd.q_of([], lambda a: 1), 0, None)
        self.assertGreater(rank, bare)

    def test_young_account_weights_half(self):
        self.assertAlmostEqual(dd.q_of([("young@example.invalid", "ok", "2026-11-09 00:00:00")], lambda a: 0.5),
                               (0.5 + 1) / (0.5 + 2))

    def test_secret_in_skill_is_refused(self):
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        out = dd.scrub_skill({"skill_md": "1. Send " + token})
        self.assertFalse(out["ok"])
        self.assertTrue(any(r.startswith("secret:") for r in out["reasons"]))

    def test_path_becomes_placeholder(self):
        out = dd.scrub_skill({"skill_md": "1. Read /root/skv-core/src/app/board.py then continue"})
        self.assertTrue(out["ok"])
        self.assertIn("[path]", out["fields"]["skill_md"])
        self.assertTrue(out["changed"])
        self.assertNotIn("/root/", out["fields"]["skill_md"])

    def test_trigger_phrase_selects_cube(self):
        rows = [{"id": "cube_trig", "topic": "nightly backup", "essence": "keep the archive", "kind": "fact",
                 "carrier": "answer", "status": "community", "rating": 1, "votes": 2, "has_skill": False,
                 "whens": [{"when": "deploy the nightly backup", "do": "check the archive"}]}]
        hits = trigger_match(rows, "Please deploy the nightly backup before midnight")
        self.assertEqual([h["id"] for h in hits], ["cube_trig"])
        self.assertEqual(trigger_match(rows, "hello there"), [])

    def test_author_label_has_no_email(self):
        label = dd.public_author("person@example.invalid", "grok-build")
        blob = json.dumps(label)
        self.assertNotIn("person@", blob)
        self.assertNotIn("example.invalid", blob)
        self.assertTrue(label["account"].startswith("acct_"))
        self.assertEqual(label["agent"], "grok-build")

    def test_calibrate_waits_for_labeled_pairs(self):
        out = dd.calibrate([{"label": "duplicate"}] * 3)
        self.assertFalse(out["calibrated"])
        self.assertIn("100", out["reason"])

    def test_rate_nudge_once_own_cube_silent_and_three_ignores(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE cubes_new (cube_id TEXT PRIMARY KEY, created_by TEXT, essence TEXT, status TEXT)")
        cv2.ensure(c)
        c.execute("INSERT INTO cubes_new (cube_id, created_by, essence, status) VALUES ('cube_own','reader@example.invalid','own','community')")
        for i in range(3):
            c.execute("INSERT INTO cubes_new (cube_id, created_by, essence, status) VALUES (?,?,?,?)",
                      ("cube_o%d" % i, "other@example.invalid", "other", "community"))
        cv2.mark_used(c, "reader@example.invalid", "cube_own", 1)
        self.assertNotIn("cube_own", cv2._state(c, "reader@example.invalid")["rate_pending"])
        for i in range(3):
            cv2.mark_used(c, "reader@example.invalid", "cube_o%d" % i, 1)
        notes = cv2.on_remember(c, "reader@example.invalid", 2, turn=True)
        self.assertFalse(any("missed_turns" in n for n in notes))
        hints = cv2.duty_hints(c, "reader@example.invalid")
        self.assertTrue(any(h.startswith("• RATE:") for h in hints))
        self.assertNotIn("cube_own", " ".join(hints))
        again = cv2.duty_hints(c, "reader@example.invalid")
        self.assertFalse(any(h.startswith("• RATE:") for h in again))
        self.assertTrue(cv2.rate_seal_failed(c, "reader@example.invalid", "", ""))
        self.assertFalse(cv2.rate_seal_failed(c, "reader@example.invalid", "vote_nothing", "not this task"))
        cv2.on_remember(c, "reader@example.invalid", 3, turn=True)
        missed = cv2.rate_missed_duty(c, "reader@example.invalid")
        self.assertEqual(missed["kind"], "missed_turns")
        self.assertGreaterEqual(missed["n"], 3)


if __name__ == "__main__":
    unittest.main()
