"""Client without a local database gets step_zero over REST. No live key."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, "/root/skv-core/mcp")
os.environ.pop("SKV_API_KEY", None)
import mcp_skv as m

_ORIG_REQ = m._req
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
                return self._one_page(body)
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

    def _one_page(self, body):
        payload = self.payload or {}
        if payload.get("ok") is False or payload.get("pack_error") or (
            not payload.get("pages") and payload.get("error")
        ):
            return json.loads(json.dumps(payload))
        pages = payload.get("pages") or []
        try:
            page = int((body or {}).get("page") or 1)
        except (TypeError, ValueError):
            page = 1
        if page < 1 or page > len(pages) or not str(pages[page - 1]).strip():
            return {
                "ok": False,
                "pages": [],
                "text": "",
                "page": page,
                "total_pages": len(pages),
                "pack_error": payload.get("pack_error") or payload.get("error") or "empty pages",
            }
        out = {"ok": True, "page": page, "total_pages": len(pages), "text": pages[page - 1], "error": ""}
        if page == 1:
            if payload.get("text"):
                out["room_text"] = payload["text"]
            for key in ("while_away", "others_block", "identify_hint", "kind"):
                if payload.get(key):
                    out[key] = payload[key]
        return out

    def test_step_zero_pages_and_room_block(self):
        out = json.loads(m.step_zero(page=1, agent_token="tok-b", session_id="s-b"))
        self.assertTrue(out.get("text"))
        self.assertIn("PACK888", out["text"])
        self.assertIn("OTHER AGENTS", out["text"])
        self.assertGreater(out["text"].index("OTHER AGENTS"), out["text"].index("PACK888"))
        self.assertEqual(out["pages"], 2)
        self.assertFalse(out["done"])
        nxt = json.loads(m.step_zero(page=2, agent_token="tok-b", session_id="s-b"))
        self.assertIn("FULL CONST 00", nxt["text"])
        self.assertIn("CUBE 00", nxt["text"])
        self.assertTrue(nxt["done"])
        self.assertNotIn("OTHER AGENTS", nxt["text"])
        posted = [c for c in self.calls if c[1] == "/agent/step_zero"]
        self.assertEqual([c[2]["page"] for c in posted], [1, 2])
        self.assertEqual(posted[0][2]["agent_token"], "tok-b")
        self.assertEqual(posted[1][2]["agent_token"], "tok-b")
        self.assertNotIn("pages", posted[0][2])

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

    def test_constitution_install_is_a_short_pointer(self):
        m._CV.clear()
        out = json.loads(m.constitution_install(user_confirmed=True))
        self.assertTrue(out["install"]["installed"])
        self.assertNotIn("step_zero", out)
        self.assertIn("identify", out["next_action"])
        self.assertIn("step_zero", out["next_action"])
        self.assertLess(len(json.dumps(out)), 2500)
        self.assertFalse(any(c[1] == "/agent/step_zero" for c in self.calls))

    def test_constitution_install_does_not_fetch_a_missing_pack(self):
        self.payload = {"ok": False, "pages": [], "error": "user database not found"}
        out = json.loads(m.constitution_install(user_confirmed=True))
        self.assertTrue(out["install"]["installed"])
        self.assertNotIn("step_zero", out)
        self.assertFalse(any(c[1] == "/agent/step_zero" for c in self.calls))

    def test_memory_search_agents_all_uses_rest(self):
        out = json.loads(m.memory_search("hello pack", agents="all", agent_token="tok-b"))
        self.assertEqual(out["room_events"][0]["ev"], "evA-room")
        self.assertTrue(any(c[1] == "/agent/room_events" for c in self.calls))
        self.assertNotIn("room_events_error", out)

    def test_remote_page_is_not_cut_to_three_thousand_chars(self):
        whole = "П" * 12000
        self.payload = {"ok": True, "pages": [whole, "second page"], "text": ""}
        m._TRACK.pop("remote-test-key", None)
        out = json.loads(m.step_zero(page=1))
        self.assertEqual(out["text"], whole)
        self.assertNotIn("trimmed", out["text"])
        installed = json.loads(m.constitution_install(user_confirmed=True))
        self.assertNotIn("step_zero", installed)
        self.assertTrue(installed["install"]["installed"])
        self.assertNotIn(whole[:20], json.dumps(installed))

    def test_step_zero_read_is_identity_and_retried(self):
        import httpx

        class Resp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"ok": True, "page": 2, "total_pages": 2, "text": "hi"}

        class Client:
            is_closed = False

            def __init__(self):
                self.n = 0
                self.timeouts = []
                self.headers = []

            def request(self, method, url, headers=None, json=None, params=None, timeout=None):
                self.n += 1
                self.timeouts.append(timeout)
                self.headers.append(dict(headers or {}))
                if self.n < 3:
                    raise httpx.ReadTimeout("slow")
                return Resp()

        client = Client()
        fake = m._req
        old = m._HTTP_CLIENTS.get("*")
        m._HTTP_CLIENTS["*"] = client
        m._req = _ORIG_REQ
        try:
            out = m._req("POST", "/agent/step_zero", {"page": 2})
        finally:
            m._req = fake
            if old is None:
                m._HTTP_CLIENTS.pop("*", None)
            else:
                m._HTTP_CLIENTS["*"] = old
        self.assertEqual(out.get("text"), "hi")
        self.assertEqual(client.n, 3)
        self.assertEqual(client.headers[0].get("Accept-Encoding"), "identity")
        self.assertGreaterEqual(float(client.timeouts[0].read), 60)

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
