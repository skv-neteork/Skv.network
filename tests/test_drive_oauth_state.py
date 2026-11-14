"""OAuth state: tied to the user who started connect, rejected when unknown or expired."""
import json
import os
import tempfile
import unittest
import urllib.parse
from unittest import mock

from app import drive_files as drive


class StateTests(unittest.TestCase):
    def test_memory_state_round_trip_unknown_and_expired(self):
        store = drive.MemState()
        token = drive.issue_state("user-a@example.invalid", "chain-1", "Line One", store, now=1_000)
        self.assertNotIn("user-a", token)
        got = store.take(token, 1_000 + drive.STATE_TTL_S)
        self.assertEqual(got["user_id"], "user-a@example.invalid")
        self.assertEqual(got["chain_id"], "chain-1")
        self.assertEqual(got["chain_name"], "Line One")
        self.assertIsNone(store.take(token, 1_000))
        again = drive.issue_state("user-a@example.invalid", "chain-1", "Line One", store, now=2_000)
        self.assertIsNone(store.take(again, 2_000 + drive.STATE_TTL_S + 1))
        self.assertIsNone(store.take("not-a-real-state", 2_000))
        self.assertIsNone(store.take("", 2_000))

    def test_sqlite_state_is_one_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = drive.SqliteState(os.path.join(tmp, "state.db"))
            token = drive.issue_state("user-b@example.invalid", "main", "main", store, now=5_000)
            first = store.take(token, 5_100)
            self.assertEqual(first["user_id"], "user-b@example.invalid")
            self.assertIsNone(store.take(token, 5_100))

    def test_start_connect_auth_url_carries_state_for_that_user(self):
        store = drive.MemState()
        with mock.patch.dict(os.environ, {
            "SKV_DRIVE_OAUTH_CLIENT_ID": "client-test.apps.googleusercontent.com",
            "SKV_DRIVE_OAUTH_CLIENT_SECRET": "secret-test",
            "SKV_DRIVE_OAUTH_REDIRECT": "https://skv.network/drive/callback",
        }, clear=False):
            body = drive.start_connect("user-c@example.invalid", "ch", "Chat", store, now=8_000)
        self.assertTrue(body["ok"])
        self.assertEqual(body["auth_url"], body["url"])
        parsed = urllib.parse.urlparse(body["auth_url"])
        q = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(q["client_id"], ["client-test.apps.googleusercontent.com"])
        self.assertEqual(q["redirect_uri"], ["https://skv.network/drive/callback"])
        self.assertEqual(q["access_type"], ["offline"])
        self.assertEqual(q["prompt"], ["consent"])
        self.assertEqual(q["response_type"], ["code"])
        state = q["state"][0]
        self.assertTrue(state)
        self.assertNotIn("secret-test", body["auth_url"])
        self.assertNotIn("client_secret", json.dumps(body))
        bound = store.take(state, 8_000)
        self.assertEqual(bound["user_id"], "user-c@example.invalid")
        self.assertEqual(bound["chain_id"], "ch")

    def test_callback_rejects_bad_state_and_accepts_a_stored_one(self):
        store = drive.MemState()
        token = drive.issue_state("user-d@example.invalid", "ch-d", "Desk", store, now=9_000)
        bad = drive.handle_callback("auth-code", "nope", store=store, now=9_100, complete=lambda *a: {"ok": True})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["status"], 400)
        self.assertIn("invalid or expired", bad["text"])
        self.assertIn("invalid or expired", bad["html"])
        self.assertNotIn("auth-code", bad["html"])
        seen = {}

        def complete(user_id, chain_id, chain_name, code):
            seen["args"] = (user_id, chain_id, chain_name, code)
            return {"ok": True, "refresh_token": "refresh-SHOULD-NOT-LEAK", "client_secret": "nope"}

        good = drive.handle_callback("auth-code", token, store=store, now=9_100, complete=complete)
        self.assertTrue(good["ok"])
        self.assertEqual(good["status"], 200)
        self.assertEqual(good["text"], "Google Drive connected. You can close this tab.")
        self.assertIn("Google Drive connected. You can close this tab.", good["html"])
        self.assertNotIn("refresh-SHOULD-NOT-LEAK", good["html"])
        self.assertNotIn("auth-code", good["html"])
        self.assertEqual(seen["args"], ("user-d@example.invalid", "ch-d", "Desk", "auth-code"))
        reused = drive.handle_callback("auth-code", token, store=store, now=9_100, complete=complete)
        self.assertFalse(reused["ok"])
        self.assertIn("invalid or expired", reused["text"])

    def test_callback_expired_state_does_not_exchange(self):
        store = drive.MemState()
        token = drive.issue_state("user-e@example.invalid", "main", "", store, now=1)
        called = []
        page = drive.handle_callback("code", token, store=store, now=1 + drive.STATE_TTL_S + 5,
                                     complete=lambda *a: called.append(a) or {"ok": True})
        self.assertFalse(page["ok"])
        self.assertEqual(called, [])
        self.assertIn("invalid or expired", page["html"])

    def test_exchange_posts_the_same_form_as_connect(self):
        seen = {}

        class FakeResp:
            def read(self):
                return json.dumps({"access_token": "at-ok", "refresh_token": "rt-ok"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=30):
            seen["url"] = req.full_url
            seen["body"] = urllib.parse.parse_qs(req.data.decode())
            seen["timeout"] = timeout
            return FakeResp()

        env = {
            "SKV_DRIVE_OAUTH_CLIENT_ID": "client-test.apps.googleusercontent.com",
            "SKV_DRIVE_OAUTH_CLIENT_SECRET": "secret-test",
            "SKV_DRIVE_OAUTH_REDIRECT": "https://skv.network/drive/callback",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("app.drive_files.urllib.request.urlopen", fake_urlopen):
                out = drive.exchange_code("one-time-code")
        self.assertTrue(out["ok"])
        self.assertEqual(seen["url"], "https://oauth2.googleapis.com/token")
        self.assertEqual(seen["timeout"], 30)
        self.assertEqual(seen["body"]["code"], ["one-time-code"])
        self.assertEqual(seen["body"]["client_id"], ["client-test.apps.googleusercontent.com"])
        self.assertEqual(seen["body"]["client_secret"], ["secret-test"])
        self.assertEqual(seen["body"]["redirect_uri"], ["https://skv.network/drive/callback"])
        self.assertEqual(seen["body"]["grant_type"], ["authorization_code"])
        self.assertNotIn("secret-test", json.dumps({k: v for k, v in out.items() if k != "token"}))


if __name__ == "__main__":
    unittest.main()
