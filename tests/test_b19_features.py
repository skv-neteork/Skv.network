"""B19: import upload, public memory_import_text, feature status, shared try prompts."""
import ast
import base64
import io
import json
import os
import sqlite3
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
import sys
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app.feature_offer import FEATURES, OFFER, SUGGEST, TRY
from app.features_status import account_features

try:
    from app.routers.import_dialogs import payload_from_upload, to_pairs
except Exception:
    payload_from_upload = to_pairs = None


def _visible_mcp():
    src = open(os.path.join(ROOT, "mcp", "mcp_skv.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "VISIBLE":
                    found = ast.literal_eval(node.value)
    if found is None:
        raise AssertionError("VISIBLE missing")
    return set(found)


@unittest.skipUnless(to_pairs, "import_dialogs needs fastapi")
class ImportPairsTests(unittest.TestCase):
    def test_claude_content_list(self):
        payload = {"chat_messages": [
            {"sender": "human", "content": [{"type": "text", "text": "We decided oat milk only."}]},
            {"sender": "assistant", "content": [{"type": "text", "text": "Noted. Oat milk, nothing else."}]},
        ]}
        pairs = to_pairs(payload)
        self.assertEqual(len(pairs), 2)
        self.assertIn("oat milk only", pairs[0]["content"])
        self.assertEqual(pairs[1]["role"], "assistant")

    def test_chatgpt_mapping_unchanged(self):
        payload = [{"mapping": {
            "1": {"message": {"author": {"role": "user"}, "content": {"parts": ["Hello from chatgpt"]}}},
            "2": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["Hello back"]}}},
        }}]
        pairs = to_pairs(payload)
        self.assertEqual([p["role"] for p in pairs], ["user", "assistant"])
        self.assertIn("Hello from chatgpt", pairs[0]["content"])

    def test_zip_conversations_json_not_double_wrapped(self):
        conv = [{"mapping": {
            "1": {"message": {"author": {"role": "user"}, "content": {"parts": ["zip user"]}}},
            "2": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["zip assistant"]}}},
        }}]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("conversations.json", json.dumps(conv))
        raw = buf.getvalue()
        payload, hint = payload_from_upload({
            "content_b64": base64.b64encode(raw).decode(),
            "filename": "export.zip",
        })
        self.assertIsInstance(payload, list)
        self.assertEqual(hint, "chatgpt")
        pairs = to_pairs(payload)
        self.assertEqual(pairs[0]["content"], "zip user")

    def test_rejects_huge_base64(self):
        with self.assertRaises(ValueError):
            payload_from_upload({"content_b64": "A" * 40_000_001, "filename": "x.zip"})


class FeatureStatusTests(unittest.TestCase):
    def _dbs(self):
        import tempfile
        d = tempfile.mkdtemp()
        user = os.path.join(d, "user.db")
        shared = os.path.join(d, "shared.db")
        seal = os.path.join(d, "seal.db")
        cfg = os.path.join(d, "cfg.json")
        return user, shared, seal, cfg

    def test_empty_account_is_not_green(self):
        user, shared, seal, cfg = self._dbs()
        sqlite3.connect(user).close()
        sqlite3.connect(shared).close()
        sqlite3.connect(seal).close()
        json.dump({"recall_later_enabled": False}, open(cfg, "w"))
        out = account_features("ada@example.com", user_db=user, shared_db=shared, seal_db=seal, config_path=cfg)
        by = {c["id"]: c for c in out["features"]}
        self.assertEqual(by["memory"]["status"], "Not set")
        self.assertEqual(by["import"]["status"], "Not set")
        self.assertEqual(by["lines"]["status"], "Not set")
        self.assertEqual(by["recall"]["status"], "Off")
        self.assertEqual(by["seal"]["status"], "Not set")
        self.assertEqual(by["constitution"]["status"], "Off")
        self.assertEqual(by["vault"]["status"], "Not set")
        self.assertEqual(by["cubes"]["status"], "Not set")
        self.assertEqual(by["chrome"]["status"], "Beta")
        self.assertEqual(by["demo"]["status"], "N/A")
        self.assertNotIn("nonce", json.dumps(out))

    def test_known_states_flip_on(self):
        user, shared, seal, cfg = self._dbs()
        u = sqlite3.connect(user)
        u.execute("CREATE TABLE event_metadata (event_id TEXT, kind TEXT)")
        u.execute("INSERT INTO event_metadata VALUES ('e1','import')")
        u.execute("CREATE TABLE constitution_state (id INTEGER, installed_at TEXT, installed_by TEXT)")
        u.execute("INSERT INTO constitution_state VALUES (1, '2026-01-01', 'ada@example.com')")
        u.execute("CREATE TABLE agents (id TEXT, key_id TEXT, name TEXT)")
        u.execute("INSERT INTO agents VALUES ('a','k','one'), ('b','k','two')")
        u.execute("CREATE TABLE chain_skills (chain_id TEXT, cube_id TEXT)")
        u.execute("INSERT INTO chain_skills VALUES ('c','cube1')")
        u.commit(); u.close()
        s = sqlite3.connect(shared)
        s.execute("CREATE TABLE user_api_keys (user_id TEXT, is_active INT, kind TEXT, label TEXT, name TEXT)")
        s.execute("INSERT INTO user_api_keys VALUES ('ada@example.com', 1, 'agent', '', 'main')")
        s.execute("CREATE TABLE vault_secrets (user_id TEXT, name TEXT)")
        s.execute("INSERT INTO vault_secrets VALUES ('ada@example.com', 'demo_name')")
        s.execute("CREATE TABLE cubes_new (cube_id TEXT, created_by TEXT)")
        s.commit(); s.close()
        c = sqlite3.connect(seal)
        c.execute("CREATE TABLE ctr (user TEXT, n INT)")
        c.execute("INSERT INTO ctr VALUES ('ada@example.com', 3)")
        c.commit(); c.close()
        json.dump({"recall_later_enabled": True}, open(cfg, "w"))
        out = account_features("ada@example.com", user_db=user, shared_db=shared, seal_db=seal, config_path=cfg)
        by = {row["id"]: row for row in out["features"]}
        for fid in ("memory", "import", "lines", "recall", "seal", "constitution", "vault", "cubes"):
            self.assertEqual(by[fid]["status"], "On", fid)
        self.assertEqual(by["vault"]["detail"], "1 name")
        self.assertNotIn("demo_name", json.dumps(by["vault"]))
        self.assertNotIn("nonce", json.dumps(out))

    def test_prompts_match_the_features_page_and_profile(self):
        page = open(os.path.join(SRC, "app", "features.html"), encoding="utf-8").read()
        profile = open(os.path.join(SRC, "app", "profile.html"), encoding="utf-8").read()
        connect = open(os.path.join(SRC, "app", "connect.html"), encoding="utf-8").read()
        for key, text in TRY.items():
            self.assertIn(text, page, key)
        self.assertIn('id="import-chat"', profile)
        self.assertIn('id="importFile"', profile)
        self.assertIn('id="my-features"', profile)
        self.assertIn("/downloads/skv-guard2-chrome.zip", profile)
        self.assertIn("/downloads/skv-guard2-chrome.zip", connect)
        self.assertIn("Load unpacked", connect)
        self.assertNotIn("Chrome Web Store listing.", page.split("Honest limits")[0][-1:])  # page may mention it in the honest section
        self.assertIn("not a Chrome Web Store listing", page)
        self.assertIn("memory_import_text", page)
        self.assertNotIn("paste, not a file-upload button", page)
        for _fid, name, anchor, _b, _t, _a in FEATURES:
            self.assertIn('id="%s"' % anchor, page)
            self.assertIn(name, page)

    def test_offer_mentions_the_import_tool(self):
        self.assertIn("memory_import_text", OFFER)
        self.assertNotIn("no import tool", OFFER)
        self.assertIn("memory_import_text", SUGGEST)
        self.assertNotIn("38-tool", SUGGEST["vault_inject"])
        names = _visible_mcp()
        ns = {}
        exec(open(os.path.join(SRC, "app", "mcp_public_tools.py"), encoding="utf-8").read(), ns)
        self.assertEqual(set(ns["VISIBLE"]), names)
        self.assertIn("memory_import_text", names)
        self.assertEqual(len(names), 39)


if __name__ == "__main__":
    unittest.main()
