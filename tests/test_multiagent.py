"""Shared room. Temporary databases only. Nothing here opens /data/skv."""
import sqlite3
import unittest
from datetime import timedelta

from app.room import (
    add_task,
    assert_done,
    build_while_away,
    check_citations,
    claim_task,
    cursor_of,
    deliver,
    expire_tasks,
    facts_for,
    file_check,
    file_claim,
    file_release,
    hash_of,
    identify,
    list_events,
    owners_map,
    record_event,
    renew_leases,
    resolve_call,
    review_diff,
    step_zero_package,
)
from app.room.claims import ClaimConflict
from app.room.clock import as_dt, iso
from app.room.copy import CHECK_REREAD, EMPTY_LANE, LEGACY_HEADER, OTHERS_HEADER
from app.room.files import FileConflict
from app.room.schema import ensure

T0 = as_dt("2026-11-09 08:00:00")


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        ensure(self.c)
        self.c.execute(
            "CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, essence TEXT, actor_agent_id TEXT, session_id TEXT, ev_kind TEXT, author_kind TEXT, gist TEXT)"
        )
        self.c.commit()

    def tearDown(self):
        self.c.close()

    def _id(self, name, session, now=None, key="k", chain="ch"):
        return identify(self.c, key, chain, name, session_id=session, now=now or T0)

    def test_01_actor_from_token_ignores_client(self):
        a = self._id("grok-build", "s-a")
        b = self._id("grok-bot", "s-b")
        ev = record_event(
            self.c, "ch", "k", a["agent_id"], "s-a", kind="brief", text="ship the room",
            event_id="e1", client_actor=b["agent_id"], now=T0,
        )
        self.assertEqual(ev["actor_agent_id"], "grok-build")
        blob = str(ev)
        self.assertNotIn(a["agent_token"], blob)
        self.assertNotIn(b["agent_token"], blob)
        who = resolve_call(self.c, "k", "ch", "Грок", agent_token=a["agent_token"], session_id="s-a", client_actor="grok-bot", now=T0)
        self.assertEqual(who["actor_id"], "grok-build")
        self.assertNotEqual(who["actor_id"], "grok-bot")
        owners = owners_map(self.c, "ch")
        self.assertEqual(check_citations("[ev:e1] [ev:e1@grok-build]", owners), [])
        self.assertEqual(check_citations("[ev:e1@grok-bot]", owners), ["e1@grok-bot"])

    def test_02_morning_then_evening(self):
        a = self._id("grok-build", "morning", T0)
        record_event(self.c, "ch", "k", a["agent_id"], "morning", kind="brief", text="started the board", event_id="am1", now=T0)
        evening = T0 + timedelta(hours=10)
        b = self._id("grok-bot", "evening", evening)
        pack = step_zero_package(self.c, b["agent_id"], "k", "ch", "assistant", "evening", now=evening)
        self.assertEqual(pack["kind"], "full")
        self.assertIn(EMPTY_LANE, pack["text"])
        self.assertIn(OTHERS_HEADER, pack["text"])
        self.assertIn("[ev:am1@grok-build]", pack["text"])
        other = pack["text"].split(OTHERS_HEADER, 1)[1]
        self.assertNotRegex(other, r"(?i)(?:^|\s)я(?:\s|$)")
        self.assertTrue(pack["while_away"])
        self.assertIn("am1", pack["while_away"])

    def test_03_identify_required_then_unidentified(self):
        a = self._id("grok-build", "hold")
        self._id("grok-bot", "other")
        before = len(list_events(self.c, "ch"))
        cur0 = cursor_of(self.c, a["agent_id"], "ch")
        r1 = resolve_call(self.c, "k", "ch", "Грок", session_id="new", client_hint="grok-chat", now=T0)
        self.assertEqual(r1["error"], "IDENTIFY_REQUIRED")
        self.assertEqual(r1["hint"], "grok-chat")
        self.assertFalse(r1["saved"])
        self.assertEqual(len(list_events(self.c, "ch")), before)
        self.assertEqual(cursor_of(self.c, a["agent_id"], "ch"), cur0)
        r2 = resolve_call(self.c, "k", "ch", "Грок", session_id="new", now=T0)
        self.assertTrue(r2["actor_id"].startswith("unidentified@new"))
        ev = record_event(self.c, "ch", "k", r2["actor_id"], "new", kind="turn", text="still here", event_id="u1", now=T0)
        self.assertEqual(ev["actor_agent_id"], "unidentified@new")
        mine = facts_for(self.c, a["agent_id"], "k", "ch", "assistant")
        self.assertFalse(any(f["ev"] == "u1" and f["is_self"] for f in mine["facts"]))
        self.assertNotIn("u1", " ".join(mine["own_lines"]))
        lane = facts_for(self.c, r2["actor_id"], "k", "ch", "assistant")
        self.assertTrue(any(f["ev"] == "u1" and f["is_self"] for f in lane["facts"]))

    def test_04_name_in_use_and_idle_return(self):
        a = self._id("grok-build", "win-1", T0)
        held = hash_of(self.c, "k", a["agent_id"])
        busy = identify(self.c, "k", "ch", "grok-build", session_id="win-2", now=T0 + timedelta(minutes=5))
        self.assertEqual(busy["error"], "NAME_IN_USE")
        self.assertIn("-2", busy["suggestion"])
        self.assertEqual(hash_of(self.c, "k", a["agent_id"]), held)
        again = identify(self.c, "k", "ch", "grok-build", session_id="win-3", now=T0 + timedelta(minutes=31))
        self.assertEqual(again["agent_id"], a["agent_id"])
        self.assertNotEqual(hash_of(self.c, "k", a["agent_id"]), held)
        same = identify(self.c, "k", "ch", "grok-build", session_id="win-3", now=T0 + timedelta(minutes=32))
        self.assertEqual(same["agent_id"], a["agent_id"])

    def test_05_one_full_pack_lost_and_force(self):
        a = self._id("grok-build", "s1", T0)
        p1 = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s1", now=T0)
        p2 = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s1", now=T0 + timedelta(seconds=30))
        self.assertEqual(p1["kind"], "full")
        self.assertIsNone(p2["kind"])
        p3 = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", now=T0 + timedelta(minutes=1))
        p4 = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", now=T0 + timedelta(minutes=1, seconds=10))
        self.assertEqual(p3["kind"], "full")
        self.assertIsNone(p4["kind"])
        lost = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", context_state="lost", now=T0 + timedelta(minutes=2))
        spam = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", context_state="lost", now=T0 + timedelta(minutes=2, seconds=5))
        self.assertEqual(lost["kind"], "full")
        self.assertIsNone(spam["kind"])
        forced = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", force=True, now=T0 + timedelta(minutes=3))
        self.assertIsNone(forced["kind"])
        later = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", force=True, now=T0 + timedelta(minutes=14))
        self.assertEqual(later["kind"], "full")
        idle = step_zero_package(self.c, a["agent_id"], "k", "ch", session_id="s2", now=T0 + timedelta(hours=13))
        self.assertEqual(idle["kind"], "delta")

    def test_06_digest_limits_and_cursor(self):
        me = self._id("grok-build", "me", T0)
        other = self._id("grok-bot", "them", T0)
        empty = build_while_away(self.c, me["agent_id"], "k", "ch", "coder", T0)
        self.assertIsNone(empty["text"])
        for i in range(7):
            record_event(self.c, "ch", "k", other["agent_id"], "them", kind="file_change", path="src/app/only.py",
                         old_hash="a%d" % i, new_hash="b%d" % i, event_id="f%d" % i, now=T0)
        one = build_while_away(self.c, me["agent_id"], "k", "ch", "coder", T0)
        self.assertEqual(len(one["lines"]), 1)
        self.assertIn("×7", one["text"])
        self.assertIn("src/app/only.py", one["text"])
        deliver(self.c, lambda b: b["text"], me["agent_id"], "k", "ch", "coder", T0)
        for i in range(6):
            file_claim(self.c, "ch", "src/hot%d.py" % i, me["agent_id"], "h%d" % i, key_id="k", now=T0)
            record_event(self.c, "ch", "k", other["agent_id"], "them", kind="file_change", path="src/hot%d.py" % i,
                         old_hash="o", new_hash="n", event_id="c%d" % i, now=T0)
        for i in range(34):
            record_event(self.c, "ch", "k", other["agent_id"], "them", kind="claim", task_id="T%02d" % i,
                         event_id="q%d" % i, now=T0)
        built = build_while_away(self.c, me["agent_id"], "k", "ch", "coder", T0)
        self.assertLessEqual(len(built["lines"]), 5)
        self.assertLessEqual(len(built["text"]), 700)
        self.assertGreaterEqual(built["text"].count("⚠ КОНФЛИКТ"), 2)
        self.assertRegex(built["text"], r"\+\d+ ещё с ev:\S+ — memory_search\(since=\S+, lines=all\)")
        shown_conflicts = [ln for ln in built["lines"] if ln.startswith("⚠")]
        self.assertGreaterEqual(len(shown_conflicts), 2)
        first = deliver(self.c, lambda b: (_ for _ in ()).throw(RuntimeError("serialize")), me["agent_id"], "k", "ch", "coder", T0)
        self.assertFalse(first["committed"])
        frozen = cursor_of(self.c, me["agent_id"], "ch")
        self.assertEqual(first["cursor"], frozen)
        again = build_while_away(self.c, me["agent_id"], "k", "ch", "coder", T0)
        self.assertGreaterEqual(again["text"].count("⚠ КОНФЛИКТ"), 2)
        deliver(self.c, lambda b: b["text"], me["agent_id"], "k", "ch", "coder", T0)
        nxt = build_while_away(self.c, me["agent_id"], "k", "ch", "coder", T0)
        self.assertIn("⚠ КОНФЛИКТ", nxt["text"] or "")
        view = facts_for(self.c, me["agent_id"], "k", "ch", "coder", digest_ids=set(built["event_ids"]))
        for ev in built["event_ids"]:
            self.assertFalse(any(f["ev"] == ev for f in view["facts"]))

    def test_07_task_claim_lease(self):
        me = self._id("grok-build", "me", T0)
        other = self._id("grok-bot", "them", T0)
        add_task(self.c, "T1", "room", now=T0)
        add_task(self.c, "T2", "other", status="doing", now=T0)
        claim_task(self.c, "T1", me["agent_id"], expected_rev=0, chain_id="ch", key_id="k", now=T0)
        with self.assertRaises(ClaimConflict) as cm:
            claim_task(self.c, "T1", other["agent_id"], expected_rev=1, chain_id="ch", key_id="k", now=T0)
        self.assertEqual(cm.exception.owner, me["agent_id"])
        with self.assertRaises(ValueError):
            assert_done(self.c, "T2", other["agent_id"], now=T0)
        claim_task(self.c, "T2", other["agent_id"], expected_rev=0, chain_id="ch", key_id="k", now=T0)
        expire_tasks(self.c, "ch", "k", now=T0 + timedelta(minutes=31))
        row = self.c.execute("SELECT status, claimed_by FROM board_items WHERE item_id='T2'").fetchone()
        self.assertEqual(row[0], "todo")
        self.assertEqual(row[1], "")
        claim_task(self.c, "T1", me["agent_id"], chain_id="ch", key_id="k", now=T0 + timedelta(minutes=40))
        claim_task(self.c, "T2", other["agent_id"], chain_id="ch", key_id="k", now=T0 + timedelta(minutes=40))
        mine_before = self.c.execute("SELECT lease_until FROM board_items WHERE item_id='T2'").fetchone()[0]
        renew_leases(self.c, me["agent_id"], "ch", now=T0 + timedelta(minutes=50))
        mine_after = self.c.execute("SELECT lease_until FROM board_items WHERE item_id='T1'").fetchone()[0]
        other_after = self.c.execute("SELECT lease_until FROM board_items WHERE item_id='T2'").fetchone()[0]
        self.assertNotEqual(mine_after, "")
        self.assertEqual(other_after, mine_before)
        self.assertGreater(mine_after, other_after)

    def test_08_file_claim_check_release(self):
        me = self._id("grok-build", "me", T0)
        other = self._id("grok-bot", "them", T0)
        file_claim(self.c, "ch", "src/app/board.py", me["agent_id"], "abc", key_id="k", now=T0)
        with self.assertRaises(FileConflict) as cm:
            file_claim(self.c, "ch", "src/app/board.py", other["agent_id"], "abc", key_id="k", now=T0)
        self.assertEqual(cm.exception.owner, me["agent_id"])
        bad = file_check(self.c, "ch", "src/app/board.py", "zzz", now=T0)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["message"], CHECK_REREAD)
        rel = file_release(self.c, "ch", "src/app/board.py", me["agent_id"], "def", key_id="k", now=T0, minus=1, plus=2, old_hash="abc")
        seen = build_while_away(self.c, other["agent_id"], "k", "ch", "assistant", T0)
        self.assertIn(rel["event_id"], seen["text"])
        self.assertIn("FILE_CHANGE", seen["text"])

    def test_09_pre_commit(self):
        diff_fn = "\n".join([
            "diff --git a/src/app/demo.py b/src/app/demo.py",
            "--- a/src/app/demo.py",
            "+++ b/src/app/demo.py",
            "@@ -1,4 +1,3 @@",
            " class Box:",
            "-    def keep(self):",
            "-        return 1",
            "-    def drop(self):",
            "-        return 2",
            "+    def keep(self):",
            "+        return 1",
        ])
        blocked = review_diff(diff_fn, "tidy")
        self.assertFalse(blocked["ok"])
        self.assertTrue(any("drop" in e for e in blocked["errors"]))
        allowed = review_diff(diff_fn, "tidy\nALLOW-DELETE: the task removes drop")
        self.assertTrue(allowed["ok"])
        big = ["diff --git a/src/app/wide.py b/src/app/wide.py", "--- a/src/app/wide.py", "+++ b/src/app/wide.py", "@@ -1,400 +1,20 @@"]
        big += ["-x%d = %d" % (i, i) for i in range(321)]
        big += ["+y = 1"]
        wide = review_diff("\n".join(big), "rewrite", old_sizes={"src/app/wide.py": 400})
        self.assertFalse(wide["ok"])
        self.assertTrue(any("80%" in e or "30%" in e for e in wide["errors"]))
        waived = review_diff("\n".join(big), "ALLOW-DELETE: split the module", old_sizes={"src/app/wide.py": 400})
        self.assertTrue(waived["ok"])
        claimed = review_diff(diff_fn, "ALLOW-DELETE: still not mine", ["src/app/demo.py"])
        self.assertFalse(claimed["ok"])
        self.assertTrue(any("another agent" in e for e in claimed["errors"]))

    def test_10_legacy_and_single_agent_key(self):
        self.c.execute("INSERT INTO event_metadata (event_id, essence, actor_agent_id) VALUES ('old1', 'unsigned note', NULL)")
        record_event(self.c, "ch", "k", "", "old", kind="turn", text="way back", event_id="leg1", now=T0)
        who = resolve_call(self.c, "k-one", "ch", "Грок", session_id="solo", now=T0)
        self.assertTrue(who["ok"])
        self.assertTrue(who["implicit"])
        self.assertEqual(who["actor_id"], "Грок")
        self.assertNotIn("error", who)
        view = facts_for(self.c, "Грок", "k-one", "ch", "assistant")
        self.assertTrue(view["legacy_block"].startswith(LEGACY_HEADER))
        self.assertIn("[ev:leg1]", view["legacy_block"])
        self.assertFalse(any(f["ev"] == "leg1" and f["is_self"] for f in view["facts"]))
        self.assertNotIn("leg1", " ".join(view["own_lines"]))

    def test_11_full_pack_prints_each_event_once(self):
        a = self._id("grok-build", "morning", T0)
        record_event(self.c, "ch", "k", a["agent_id"], "morning", kind="brief", text="начал доску", event_id="am1", now=T0)
        record_event(
            self.c, "ch", "k", a["agent_id"], "morning", kind="file_change",
            path="src/app/board.py", old_hash="aaa1111", new_hash="bbb2222",
            minus=2, plus=5, event_id="am2", now=T0,
        )
        evening = T0 + timedelta(hours=10)
        b = self._id("grok-bot", "evening", evening)
        pack = step_zero_package(
            self.c, b["agent_id"], "k", "ch", "assistant", "evening", now=evening, display_name="grok-bot",
        )
        text = pack["text"]
        self.assertEqual(pack["kind"], "full")
        self.assertEqual(text.count("[ev:am1@grok-build]"), 1)
        self.assertEqual(text.count("[ev:am2@grok-build]"), 1)
        self.assertEqual(text.count("FILE_CHANGE src/app/board.py"), 1)
        self.assertNotIn("ещё с ev:", text)
        cites = set()
        for tok in text.split("[ev:")[1:]:
            cites.add(tok.split("]", 1)[0].split("@", 1)[0])
        for line in text.splitlines():
            if "ещё с ev:" not in line:
                continue
            pointed = line.split("ещё с ev:", 1)[1].split(" ", 1)[0].strip("—").strip()
            self.assertNotIn(pointed, cites)

    def test_12_pack_overflow_skips_events_already_printed(self):
        other = self._id("grok-build", "morning", T0)
        record_event(self.c, "ch", "k", other["agent_id"], "morning", kind="brief", text="план", event_id="b1", now=T0)
        record_event(self.c, "ch", "k", other["agent_id"], "morning", kind="turn", text="сырой ход", event_id="t1", now=T0)
        for i in range(6):
            record_event(
                self.c, "ch", "k", other["agent_id"], "morning", kind="claim",
                task_id="T%02d" % i, event_id="q%d" % i, now=T0,
            )
        evening = T0 + timedelta(hours=10)
        me = self._id("grok-bot", "evening", evening)
        pack = step_zero_package(
            self.c, me["agent_id"], "k", "ch", "assistant", "evening", now=evening, display_name="grok-bot",
        )
        text = pack["text"]
        self.assertEqual(text.count("[ev:b1@grok-build]"), 1)
        self.assertEqual(text.count("[ev:q0@grok-build]"), 1)
        self.assertEqual(text.count("[ev:q4@grok-build]"), 1)
        self.assertNotIn("[ev:t1@", text)
        overflow = [ln for ln in text.splitlines() if "ещё с ev:" in ln]
        self.assertEqual(len(overflow), 1)
        self.assertIn("ещё с ev:t1", overflow[0])
        self.assertNotIn("ещё с ev:b1", overflow[0])
        self.assertNotIn("ещё с ev:q4", overflow[0])


if __name__ == "__main__":
    unittest.main()
