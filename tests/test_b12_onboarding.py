"""B12: short step_zero pages, one start order, no fake-looking examples."""
import json
import os
import sys
import unittest

sys.path.insert(0, "/root/skv-core/src")
sys.path.insert(0, "/root/skv-core/mcp")

from app.memory_pack888 import (  # noqa: E402
    STEP_ZERO_MAX_JSON,
    STEP_ZERO_PAGE_TEXT,
    separate_pack_marks,
    split_document,
    step_zero_envelope_len,
)
from app.room.bridge import SOFT_IDENTIFY_HINT, STEP_ZERO_NEXT  # noqa: E402
from app.room.copy import ROOM_SENTENCES  # noqa: E402


def _cyrillic(text):
    return any("\u0400" <= ch <= "\u04ff" for ch in text or "")


class B12OnboardingTests(unittest.TestCase):
    def test_pack_mark_gets_its_own_line(self):
        self.assertEqual(separate_pack_marks("tail=== PACK888 001"), "tail\n=== PACK888 001")
        self.assertTrue(separate_pack_marks("=== PACK888 001").startswith("=== PACK888 "))
        self.assertFalse(separate_pack_marks("=== PACK888 001").startswith("\n"))

    def test_page_cap_stays_under_the_stall(self):
        self.assertLessEqual(STEP_ZERO_PAGE_TEXT, 11000)
        self.assertLessEqual(STEP_ZERO_MAX_JSON, 12000)
        pages = split_document("memory line\n" * 4000)
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertLessEqual(len(page), STEP_ZERO_PAGE_TEXT)
            self.assertLessEqual(step_zero_envelope_len(page), STEP_ZERO_MAX_JSON)

    def test_teaching_copy_is_english_and_the_example_is_labeled(self):
        import mcp_skv as m

        cube = m.CUBE05_MCP
        self.assertIn("FAKE EXAMPLE", cube)
        self.assertIn("#EXAMPLE", cube)
        self.assertIn("ev:EXAMPLE", cube)
        self.assertIn("BLUE-HERON-12", cube)
        self.assertNotIn("7c2e", cube)
        self.assertNotIn("#014", cube)
        self.assertNotIn("remember_1790000000000000001", cube)
        self.assertNotIn("\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0439", cube)
        for blob in (m.START_ORDER, m.SHORT_DESC["identify"], m.SHORT_DESC["constitution_install"],
                     m.SHORT_DESC["step_zero"], m.SHORT_DESC["memory_start"], SOFT_IDENTIFY_HINT, STEP_ZERO_NEXT,
                     " ".join(ROOM_SENTENCES)):
            self.assertFalse(_cyrillic(blob), blob[:80])
            self.assertIn("step_zero", blob)
        self.assertIn(m.START_ORDER, m.INSTRUCTIONS)
        self.assertNotIn("продолжай", m.INSTRUCTIONS)
        self.assertIn("constitution_install", m.START_ORDER)
        self.assertIn("identify", m.START_ORDER)
        self.assertIn("turn", m.START_ORDER)

    def test_constitution_is_not_appended_twice(self):
        import mcp_skv as m

        pack = ["## constitution\n=== CUBE 00 ===\nhello cube\n"]
        extra = m._constitution_once(pack)
        joined = "\n".join(extra)
        self.assertNotIn("=== CUBE 00 ===", joined)
        self.assertEqual(joined.count("=== CUBE 05-MCP"), 1)
        self.assertEqual(joined.count("How to work through the SKV MCP tools"), 1)
        self.assertIn("FAKE EXAMPLE", joined)

    def test_install_reply_does_not_embed_a_page(self):
        import mcp_skv as m

        calls = []

        def fake_req(method, path, body=None, params=None, base=None):
            calls.append(path)
            if path == "/constitution/install":
                return {"ok": True, "installed": True}
            if path == "/constitution":
                return {"version": "v-test", "cubes": []}
            raise AssertionError(path)

        old = m._req
        m._req = fake_req
        m._CV.clear()
        try:
            out = json.loads(m.constitution_install(user_confirmed=True))
        finally:
            m._req = old
        self.assertTrue(out["install"]["installed"])
        self.assertNotIn("step_zero", out)
        self.assertNotIn("/agent/step_zero", calls)
        self.assertLess(len(json.dumps(out)), 2500)

    def test_gated_call_is_a_pointer(self):
        import mcp_skv as m

        out = json.loads(m._tg_apply(json.dumps({"results": [1]}), True))
        self.assertTrue(out["next_action"].startswith("call step_zero"))
        self.assertNotIn("step_zero", out)
        self.assertEqual(out["results"], [1])
        later = json.loads(m._tg_apply(json.dumps({"results": [1]}), False))
        self.assertIn("TURN_REQUIRED", later)
        self.assertNotIn("text", later)

    def test_mcp_locations_do_not_gzip(self):
        with open("/root/skv-core/ops/nginx_vhost_skv.network.tmpl", encoding="utf-8") as fh:
            tmpl = fh.read()
        mcp = tmpl.split("gzip stays on for the API", 1)[0]
        self.assertGreaterEqual(mcp.count("gzip off;"), 2)
        self.assertIn("gzip on;", tmpl)


if __name__ == "__main__":
    unittest.main()
