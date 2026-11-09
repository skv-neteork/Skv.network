"""Client without a local database gets step_zero over REST. No live key."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, "/root/skv-core/mcp")
os.environ.pop("SKV_API_KEY", None)
import mcp_skv as m

m.COMPACT_DB = tempfile.mkdtemp() + "/c.db"
m._active_key = lambda: "remote-test-key"
m._ROOM_LOCAL = False


PAGES = [
    "HOW TO WORK\n=== PACK888 001/001 concatenate ===\nhello pack\n",
    "=== SKV CONSTITUTION: CUBE 00-04 ===\n=== CUBE 00 (cube_const_00_v1) ===\nFULL CONST 00\n",
]


class RemoteClientTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        m._ROOM_LOCAL = False
        m._TRACK.pop("remote-test-key", None)
        m._step_zero_pages = self._local_pack_must_not_run
        self.payload = {
            "ok": True,
            "pages": list(PAGES),
            "text": "=== OTHER AGENTS ===\nbrief from mcp-a",
            "kind": "full",
            "while_away": "ходы других: +1",
            "others_block": "=== OTHER AGENTS ===",
        }

        def fake_req(method, path, body=None, params=None, base=None):
            self.calls.append((method, path, body))
            if path == "/constitution/status":
                return {"installed": True, "installed_by": "remote-test@example.invalid"}
            if path == "/agent/step_zero":
                return json.loads(json.dumps(self.payload))
            if path == "/constitution":
                return {"version": "v-test", "cubes": []}
            if path == "/constitution/install":
                return {"ok": True, "installed": True}
            if path == "/agent/room_events":
                return {"ok": True, "room_events": [{"ev": "evA-room", "actor": "mcp-a", "kind": "brief", "gist": "ship"}]}
            if path == "/search":
                return {"results": []}
            if path == "/file_check":
                return {"ok": True, "path": (body or {}).get("path"), "message": ""}
            return {}

        m._req = fake_req

    def _local_pack_must_not_run(self):
        raise AssertionError("local pack was used")

    def test_step_zero_pages_and_room_block(self):
        out = json.loads(m.step_zero(page=1, agent_token="tok-b", session_id="s-b"))
        self.assertTrue(out.get("text"))
        self.assertIn("PACK888", out["text"])
        self.assertIn("OTHER AGENTS", out["text"])
        self.assertEqual(out["pages"], 2)
        self.assertFalse(out["done"])
        nxt = json.loads(m.step_zero(page=2, agent_token="tok-b", session_id="s-b"))
        self.assertIn("FULL CONST 00", nxt["text"])
        self.assertIn("CUBE 00", nxt["text"])
        self.assertTrue(nxt["done"])
        self.assertNotIn("OTHER AGENTS", nxt["text"])
        posted = [c for c in self.calls if c[1] == "/agent/step_zero"]
        self.assertTrue(posted)
        self.assertEqual(posted[0][2]["agent_token"], "tok-b")

    def test_step_zero_without_token_still_returns_pages(self):
        self.payload = {"ok": True, "pages": list(PAGES), "text": "", "identify_hint": "call identify"}
        m._TRACK.pop("remote-test-key", None)
        out = json.loads(m.step_zero(page=1, session_id="s-plain"))
        self.assertIn("PACK888", out["text"])
        self.assertNotIn("OTHER AGENTS", out["text"])
        self.assertEqual(out.get("identify_hint"), "call identify")
        self.assertGreater(out["pages"], 0)

    def test_empty_pages_are_an_error(self):
        self.payload = {"ok": False, "pages": [""], "pack_error": "user database not found"}
        m._TRACK.pop("remote-test-key", None)
        out = json.loads(m.step_zero(page=1))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "step_zero pack unavailable")
        self.assertIn("not found", out["warning"])
        self.assertEqual(out["text"], "")
        self.assertFalse(out["done"])

    def test_constitution_install_uses_rest_pages(self):
        m._CV.clear()
        out = json.loads(m.constitution_install(user_confirmed=True))
        self.assertTrue(out["install"]["installed"])
        self.assertIn("PACK888", out["step_zero"]["text"])
        self.assertGreater(out["step_zero"]["pages"], 1)
        self.assertTrue(any(c[1] == "/agent/step_zero" for c in self.calls))

    def test_constitution_install_reports_a_missing_pack(self):
        self.payload = {"ok": False, "pages": [], "error": "user database not found"}
        out = json.loads(m.constitution_install(user_confirmed=True))
        self.assertFalse(out["step_zero"]["ok"])
        self.assertIn("not found", out["step_zero"]["warning"])

    def test_memory_search_agents_all_uses_rest(self):
        out = json.loads(m.memory_search("hello pack", agents="all", agent_token="tok-b"))
        self.assertEqual(out["room_events"][0]["ev"], "evA-room")
        self.assertTrue(any(c[1] == "/agent/room_events" for c in self.calls))
        self.assertNotIn("room_events_error", out)

    def test_file_check_is_a_visible_rest_tool(self):
        self.assertIn("file_check", m.VISIBLE)
        out = json.loads(m.file_check("src/app/x.py", current_hash="abc", agent_token="tok-b"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], "src/app/x.py")
        hit = [c for c in self.calls if c[1] == "/file_check"]
        self.assertEqual(hit[0][2]["current_hash"], "abc")
        self.assertEqual(hit[0][2]["agent_token"], "tok-b")


if __name__ == "__main__":
    unittest.main()
