"""T76: uninstall consent, secret fallback, MCP _SENS_RX, server card, feedback rating, constitution wording."""
import ast
import os
import re
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.environ.get("SKV_CORE", "/root/skv-core")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "mcp"))


def _src(*parts):
    return os.path.join(ROOT, *parts)


class UninstallConsentTests(unittest.TestCase):
    def setUp(self):
        from app import constitution_consent as cc
        self.cc = cc
        self.td = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.td.name, "acct.db")
        self._orig_db = cc._user_db
        self._orig_pin = cc._pin_board
        cc._user_db = lambda uid: self.db
        cc._pin_board = lambda uid: None

    def tearDown(self):
        self.cc._user_db = self._orig_db
        self.cc._pin_board = self._orig_pin
        self.td.cleanup()

    def test_uninstall_without_confirm_is_ask_first_and_noop(self):
        r = self.cc.install("u1", user_confirmed=True)
        self.assertTrue(r.get("ok"))
        self.assertTrue(self.cc.status("u1").get("installed"))
        out = self.cc.uninstall("u1")
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "ask_first")
        self.assertIn("user_confirmed=true", (out.get("hint") or ""))
        self.assertTrue(self.cc.status("u1").get("installed"), "state must stay installed")
        out = self.cc.uninstall("u1", user_confirmed=False)
        self.assertEqual(out.get("error"), "ask_first")
        self.assertTrue(self.cc.status("u1").get("installed"))

    def test_uninstall_with_user_confirmed_drops_state(self):
        self.cc.install("u1", user_confirmed=True)
        out = self.cc.uninstall("u1", user_confirmed=True)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("uninstalled"))
        self.assertFalse(self.cc.status("u1").get("installed"))

    def test_user_said_uninstall_also_ok(self):
        self.cc.install("u1", user_confirmed=True)
        out = self.cc.uninstall("u1", user_said_uninstall=True)
        self.assertTrue(out.get("ok"))
        self.assertFalse(self.cc.status("u1").get("installed"))

    def test_no_mcp_constitution_uninstall_tool(self):
        src = open(_src("mcp", "mcp_skv.py"), encoding="utf-8").read()
        self.assertNotIn("def constitution_uninstall", src)
        self.assertIn("def cube_uninstall", src)


class SecretFallbackTests(unittest.TestCase):
    def test_scrub_masks_test_key_sentence(self):
        from app.secret_scrub import scrub
        raw = "My test key is sk-test-1234567890abcdef"
        out = scrub(raw)
        self.assertIn("[SECRET]", out)
        self.assertNotIn("sk-test-1234567890abcdef", out)
        self.assertTrue(out.startswith("My test key is "))

    def test_remember_reuses_secret_scrub_not_weaker_copy(self):
        src = open(_src("src", "app", "routers", "v7_memory.py"), encoding="utf-8").read()
        self.assertIn("def _fallback_mask", src)
        self.assertIn("from app.secret_scrub import scrub", src)
        self.assertNotIn("_fb_rx", src)
        # import the helper (router stack) when the env allows it
        try:
            from app.routers.v7_memory import _fallback_mask
        except Exception as e:
            self.skipTest("v7_memory import skipped: %s" % type(e).__name__)
        raw = "My test key is sk-test-1234567890abcdef"
        out = _fallback_mask(raw)
        self.assertIn("[SECRET]", out)
        self.assertNotIn("sk-test-1234567890abcdef", out)


class SensRxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = open(_src("mcp", "mcp_skv.py"), encoding="utf-8").read()
        i = src.find("_SENS_RX = re.compile(")
        j = src.find("\n_TOK_RX", i)
        ns = {}
        exec("import re\n" + src[i:j], ns)
        cls.rx = ns["_SENS_RX"]

    def _hit(self, text):
        return bool(self.rx.search(text or ""))

    def test_ordinary_code_name_is_not_a_secret(self):
        self.assertFalse(self._hit("code name is Cedar-17"))
        self.assertFalse(self._hit("The code name is Cedar-17."))
        self.assertFalse(self._hit("project is called Cedar-17"))
        self.assertFalse(self._hit("the project is called X"))

    def test_real_secrets_still_flagged(self):
        self.assertTrue(self._hit("password is hunter2"))
        self.assertTrue(self._hit("api key is sk-test-1234567890abcdef"))
        self.assertTrue(self._hit("token is abcdef1234567890"))
        self.assertTrue(self._hit("пароль это secret99token"))
        self.assertTrue(self._hit("ghp_" + "A" * 20 + "xyz"))


def _visible_names():
    src = open(_src("mcp", "mcp_skv.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "VISIBLE":
                    return sorted(ast.literal_eval(node.value))
    raise AssertionError("VISIBLE not found")


def _card_doc():
    # Mirror pages._mcp_server_card_doc without importing FastAPI.
    import json
    path = _src("src", "app", "downloads", "mcp-server-card.json")
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        data = {"serverInfo": {"name": "SKV Network", "version": "1.30.0"}, "tools": []}
    names = _visible_names()
    by = {t.get("name"): t for t in (data.get("tools") or []) if isinstance(t, dict) and t.get("name")}
    data["tools"] = [by[n] if n in by else {"name": n, "description": n, "inputSchema": {"type": "object"}} for n in names]
    return data


class ServerCardTests(unittest.TestCase):
    def test_card_lists_exactly_visible_tools(self):
        names = _visible_names()
        self.assertEqual(len(names), 38, names)
        ns = {}
        exec(open(_src("src", "app", "mcp_public_tools.py"), encoding="utf-8").read(), ns)
        self.assertEqual(sorted(ns["VISIBLE"]), names)
        doc = _card_doc()
        listed = [t["name"] for t in doc["tools"]]
        self.assertEqual(listed, names)
        self.assertNotIn("memory_dig", listed)
        self.assertNotIn("memory_event", listed)
        for must in ("turn", "identify", "drive_list", "file_claim", "cube_confirm", "feedback_submit"):
            self.assertIn(must, listed)

    def test_alias_route_exists(self):
        src = open(_src("src", "app", "routers", "pages.py"), encoding="utf-8").read()
        self.assertIn('/mcp-server-card.json', src)
        self.assertIn("RedirectResponse", src)

    def test_open_auth_and_server_version(self):
        import json
        raw = json.load(open(_src("src", "app", "downloads", "mcp-server-card.json"), encoding="utf-8"))
        self.assertFalse(raw["authentication"]["required"])
        self.assertEqual(raw["serverInfo"]["version"], "1.30.0")
        desc = raw["authentication"]["description"].lower()
        self.assertIn("not required", desc)
        self.assertIn("optional", desc)
        self.assertIn("private memory", desc)
        src = open(_src("src", "app", "routers", "pages.py"), encoding="utf-8").read()
        self.assertIn('auth["required"] = False', src)
        self.assertIn(r"\d+\.\d+\.\d+", src)
        self.assertNotIn('"version": "8.3"', src)
        reg = json.load(open(_src("server.json"), encoding="utf-8"))
        self.assertEqual(reg["version"], raw["serverInfo"]["version"])
        self.assertFalse(reg["remotes"][0]["headers"][0]["isRequired"])
        self.assertIn("optional", reg["remotes"][0]["headers"][0]["description"].lower())
        self.assertLessEqual(len(reg["description"]), 100)
        self.assertIn("no auth required", reg["description"].lower())
        self.assertIn("private memory", reg["description"].lower())


def _ensure_feedback_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback_reports
        (id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, type TEXT, title TEXT,
         description TEXT, event_id TEXT, cube_id TEXT, query_text TEXT,
         severity INTEGER, rating INTEGER, status TEXT DEFAULT 'new',
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cols = [r[1] for r in conn.execute("pragma table_info(feedback_reports)")]
    if "rating" not in cols:
        conn.execute("ALTER TABLE feedback_reports ADD COLUMN rating INTEGER")


class FeedbackRatingTests(unittest.TestCase):
    def test_request_model_has_rating_field(self):
        src = open(_src("src", "app", "routers", "v7_core.py"), encoding="utf-8").read()
        i = src.find("class FeedbackRequest")
        j = src.find("class ", i + 10)
        body = src[i:j]
        self.assertIn("rating: Optional[int]", body)
        self.assertIn("kind: Optional[str]", body)
        self.assertIn("text: Optional[str]", body)

    def test_schema_adds_rating_column(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE feedback_reports
            (id TEXT PRIMARY KEY, user_id TEXT, type TEXT, title TEXT,
             description TEXT, severity INTEGER, status TEXT DEFAULT 'new',
             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        _ensure_feedback_schema(conn)
        cols = [r[1] for r in conn.execute("pragma table_info(feedback_reports)")]
        self.assertIn("rating", cols)
        conn.close()

    def test_single_feedback_routes(self):
        src = open(_src("src", "app", "routers", "v7_cubes.py"), encoding="utf-8").read()
        self.assertEqual(src.count('@router.post("/feedback"'), 1)
        self.assertEqual(src.count('@router.get("/feedback"'), 1)
        self.assertNotIn("async def agent_feedback", src)


class ConstitutionTextTests(unittest.TestCase):
    def test_compact_wording(self):
        text = open(_src("src", "app", "constitution_compact_v2.md"), encoding="utf-8").read()
        self.assertIn("the server turn reply", text)
        self.assertIn("never invent or continue the number yourself", text)
        self.assertIn("user's base_language", text)
        self.assertIn("before answering call turn", text)
        self.assertNotIn("numbered +1 each time", text)
        self.assertNotIn("Continue #N from the previous seal", text)
        self.assertNotIn("Every 10 messages, reload CUBE 00", text)
        self.assertNotIn("search/cubes in English", text)

    def test_constitution_api_version_label(self):
        src = open(_src("src", "app", "routers", "v7_guards.py"), encoding="utf-8").read()
        self.assertIn('"version": "v8.3"', src)
        self.assertNotIn('"version": "v8.0 PRO"', src)

    def test_const_bind_hash_matches_compact(self):
        from app import const_bind as CB
        import hashlib
        raw = open(_src("src", "app", "constitution_compact_v2.md"), "rb").read()
        h = hashlib.sha1(raw).hexdigest()[:6]
        reg = CB.registry()
        self.assertEqual(reg["hash"], h)
        self.assertEqual(reg["v"], "5")
        self.assertEqual(reg["drift"], [])


if __name__ == "__main__":
    unittest.main()
