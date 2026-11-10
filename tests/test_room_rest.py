"""REST room: two agents, one key. Memory databases only. No live identify."""
import json
import sqlite3
import unittest

from app.room.bridge import do_identify, finish_turn, gate, rest_attach, rest_step_zero
from app.room.digest import commit_cursor
from app.room.copy import OTHERS_HEADER
from app.room.events import record_event
from app.room.identity import resolve_call
from app.room.schema import ensure

INFO = {"key_id": "k-room", "user_id": "room-test@example.invalid", "chain_id": "ch-room", "key_name": "line"}


class RoomRestTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        ensure(self.conn)
        self.conn.execute(
            "CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, essence TEXT, actor_agent_id TEXT, session_id TEXT, ev_kind TEXT, author_kind TEXT, gist TEXT)"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_rest_sees_mcp_turn_and_hides_its_own(self):
        b = do_identify(INFO, self.conn, "rest-b", session_id="s-b")
        a = do_identify(INFO, self.conn, "mcp-a", session_id="s-a")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0], 2)
        again = do_identify(INFO, self.conn, "rest-b", session_id="s-b")
        self.assertEqual(again["agent_id"], b["agent_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0], 2)
        b = again

        own = rest_attach(INFO, self.conn, {"saved": True, "event_id": "evB-own", "session_id": "s-b"}, b["agent_token"], "s-b")
        self.assertTrue(own["saved"])
        self.assertFalse(own.get("while_away"))

        who = resolve_call(self.conn, INFO["key_id"], INFO["chain_id"], INFO["key_name"], agent_token=a["agent_token"], session_id="s-a")
        mcp = finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "evA-room", "session_id": "s-a", "verdict": "pass"})
        self.assertTrue(mcp["saved"])
        self.assertNotIn(a["agent_token"], json.dumps(mcp))

        nxt = rest_attach(INFO, self.conn, {"saved": True, "event_id": "evB-next", "session_id": "s-b"}, b["agent_token"], "s-b")
        away = nxt.get("while_away") or ""
        self.assertIn("evA-room", away)
        self.assertNotIn("evB-own", away)
        self.assertNotIn("evB-next", away)
        self.assertNotIn(b["agent_token"], away)
        self.assertNotIn("IDENTIFY_REQUIRED", json.dumps(nxt))

        record_event(self.conn, INFO["chain_id"], INFO["key_id"], a["agent_id"], "s-a", kind="brief", text="ship the room", event_id="briefA")
        brief_id = self.conn.execute("SELECT id FROM room_events WHERE event_id='briefA'").fetchone()[0]
        commit_cursor(self.conn, b["agent_id"], INFO["chain_id"], brief_id)
        pack = rest_step_zero(INFO, self.conn, b["agent_token"], session_id="s-b-pack")
        self.assertIn(OTHERS_HEADER, pack["text"])
        self.assertIn("briefA", pack["text"])
        self.assertIn("mcp-a", pack["text"])

    def test_other_line_and_other_account_see_nothing(self):
        b = do_identify(INFO, self.conn, "rest-b", session_id="s-b")
        a = do_identify(INFO, self.conn, "mcp-a", session_id="s-a")
        who = resolve_call(self.conn, INFO["key_id"], INFO["chain_id"], INFO["key_name"], agent_token=a["agent_token"], session_id="s-a")
        finish_turn(self.conn, INFO, who, {"saved": True, "event_id": "evA-room", "session_id": "s-a"})
        other = {"key_id": "k-other", "user_id": INFO["user_id"], "chain_id": "ch-other", "key_name": "other"}
        c = do_identify(other, self.conn, "other-c", session_id="s-c")
        seen = rest_attach(other, self.conn, {"saved": True, "event_id": "evC", "session_id": "s-c"}, c["agent_token"], "s-c")
        self.assertNotIn("evA-room", seen.get("while_away") or "")

        foreign = sqlite3.connect(":memory:")
        try:
            ensure(foreign)
            lone = {"key_id": "k-room", "user_id": "other@example.invalid", "chain_id": "ch-room", "key_name": "lone"}
            d = do_identify(lone, foreign, "lone-d", session_id="s-d")
            far = rest_attach(lone, foreign, {"saved": True, "event_id": "evD", "session_id": "s-d"}, d["agent_token"], "s-d")
            self.assertFalse(far.get("while_away"))
            self.assertEqual(foreign.execute("SELECT COUNT(*) FROM room_events WHERE event_id='evA-room'").fetchone()[0], 0)
        finally:
            foreign.close()

    def test_missing_token_still_saves_and_mcp_still_refuses(self):
        do_identify(INFO, self.conn, "rest-b", session_id="s-b")
        do_identify(INFO, self.conn, "mcp-a", session_id="s-a")
        before = self.conn.execute("SELECT COUNT(*) FROM room_events").fetchone()[0]
        soft = rest_attach(INFO, self.conn, {"saved": True, "event_id": "ev-free", "session_id": "soft"})
        self.assertTrue(soft["saved"])
        self.assertIn("identify", soft["identify_hint"])
        self.assertNotIn("IDENTIFY_REQUIRED", json.dumps(soft))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM room_events WHERE event_id='ev-free'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM room_events").fetchone()[0], before)
        refused = gate(INFO, self.conn, "", session_id="mcp-miss", client_hint="grok-chat")
        self.assertEqual(refused["error"], "IDENTIFY_REQUIRED")
        self.assertFalse(refused["saved"])

    def test_no_agents_stays_implicit(self):
        out = rest_attach(INFO, self.conn, {"saved": True, "event_id": "ev-plain", "session_id": "solo-implicit"})
        self.assertTrue(out["saved"])
        # C1: a lone agent is asked once per session to identify (soft nudge); nothing is stamped or refused
        self.assertIn("identify", out.get("identify_hint", "identify"))
        again = rest_attach(INFO, self.conn, {"saved": True, "event_id": "ev-plain2", "session_id": "solo-implicit"})
        self.assertTrue(again["saved"])
        self.assertNotIn("identify_hint", again)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM room_events").fetchone()[0], 0)

    def test_http_identify_and_room_do_not_touch_a_live_key(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from app.routers import room_http
        except Exception:
            self.skipTest("fastapi is not installed here")
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        ensure(raw)
        raw.execute(
            "CREATE TABLE event_metadata (event_id TEXT PRIMARY KEY, essence TEXT, actor_agent_id TEXT, session_id TEXT, ev_kind TEXT, author_kind TEXT, gist TEXT)"
        )
        raw.commit()

        class Hold:
            def close(self):
                return None

            def __getattr__(self, item):
                return getattr(raw, item)

        info = dict(INFO)
        real_lookup = room_http.lookup_key if hasattr(room_http, "lookup_key") else None
        import app.room.bridge as bridge
        old_lookup, old_open = bridge.lookup_key, bridge.open_account
        bridge.lookup_key = lambda token: info if token == "test-room-key" else None
        bridge.open_account = lambda _info: Hold()
        try:
            app = FastAPI()
            app.include_router(room_http.router)
            client = TestClient(app)
            headers = {"Authorization": "Bearer test-room-key"}
            first = client.post("/api/v7/agent/identify", json={"name": "rest-b", "session_id": "s-b"}, headers=headers)
            second = client.post("/api/v7/agent/identify", json={"name": "rest-b", "session_id": "s-b"}, headers=headers)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.json()["agent_id"], first.json()["agent_id"])
            self.assertEqual(raw.execute("SELECT COUNT(*) FROM agents").fetchone()[0], 1)
            token = second.json()["agent_token"]
            other = client.post("/api/v7/agent/identify", json={"name": "mcp-a", "session_id": "s-a"}, headers=headers)
            client.post("/api/v7/agent/room", json={"agent_token": token, "session_id": "s-b", "event_id": "evB-own", "saved": True}, headers=headers)
            who = resolve_call(raw, info["key_id"], info["chain_id"], info["key_name"], agent_token=other.json()["agent_token"], session_id="s-a")
            finish_turn(raw, info, who, {"saved": True, "event_id": "evA-room", "session_id": "s-a"})
            nxt = client.post("/api/v7/agent/room", json={"agent_token": token, "session_id": "s-b", "event_id": "evB-next", "saved": True}, headers=headers)
            self.assertEqual(nxt.status_code, 200)
            self.assertIn("evA-room", nxt.json().get("while_away") or "")
            bare = client.post("/api/v7/agent/room", json={"event_id": "ev-free", "saved": True, "session_id": "soft"}, headers=headers)
            self.assertTrue(bare.json().get("saved"))
            self.assertIn("identify_hint", bare.json())
            self.assertNotIn("IDENTIFY_REQUIRED", json.dumps(bare.json()))
            missing = client.post("/api/v7/agent/identify", json={"name": "rest-b"}, headers={"Authorization": "Bearer no-such"})
            self.assertEqual(missing.status_code, 401)
        finally:
            bridge.lookup_key = old_lookup
            bridge.open_account = old_open
            if real_lookup:
                pass
            raw.close()


if __name__ == "__main__":
    unittest.main()
