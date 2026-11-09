"""REST step_zero pages. Temporary databases only. No live identify."""
import os
import sqlite3
import tempfile
import unittest

import gzip
import json

from app.step_zero_rest import (
    REST_RESPONSE_GZIP, REST_RESPONSE_JSON, build_pages, select_rest_page,
)


def _user(path):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE event_metadata (event_id TEXT, time_str TEXT, raw_dialogue TEXT);
    CREATE TABLE summary_l1 (session_id TEXT, topic TEXT, summary_text TEXT, created_at TEXT, from_rowid INT, to_rowid INT);
    CREATE TABLE summary_l2 (user_id TEXT, map_json TEXT);
    CREATE TABLE summary_l2_blocks (id INT, source TEXT, period_from TEXT, period_to TEXT, from_rowid INT, to_rowid INT, text TEXT);
    CREATE TABLE critical_auto (key TEXT, kind TEXT, value TEXT, context TEXT, event_id TEXT, time_str TEXT, hits INT);
    CREATE TABLE board_items (item_id TEXT, kind TEXT, title TEXT, body TEXT, status TEXT, updated_at TEXT, removed INT,
                              priority INT, parent_id TEXT, waiting_for TEXT, result TEXT, created_at TEXT);
    CREATE TABLE profile_rows (id TEXT, kind TEXT, text TEXT, scope TEXT, status TEXT, created_at TEXT);
    """)
    c.execute("INSERT INTO event_metadata VALUES ('e1','2026-11-09','hello pack')")
    c.commit()
    c.close()


def _shared(path):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE cubes_new (cube_id TEXT, essence TEXT, rules_markdown TEXT, created_by TEXT, status TEXT);
    CREATE TABLE user_api_keys (user_id TEXT, api_key TEXT, is_active INT, created_at TEXT, key_prefix TEXT, label TEXT);
    """)
    c.execute("INSERT INTO cubes_new VALUES ('cube_const_00_v1','essence','FULL CONST 00','system','verified')")
    c.commit()
    c.close()


class StepZeroRestTests(unittest.TestCase):
    def test_pages_include_pack_and_constitution(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        udb = os.path.join(tmp.name, "u.db")
        sdb = os.path.join(tmp.name, "s.db")
        _user(udb)
        _shared(sdb)
        out = build_pages("packb7@example.invalid", udb, sdb)
        self.assertTrue(out["ok"])
        self.assertFalse(out["error"])
        text = "\n".join(out["pages"])
        self.assertIn("PACK888", text)
        self.assertIn("FULL CONST 00", text)
        self.assertIn("CUBE 00", text)
        self.assertTrue(all(isinstance(p, str) and p.strip() for p in out["pages"]))

    def test_missing_database_is_an_explicit_error(self):
        out = build_pages("missing-b7@example.invalid", "/tmp/skv-b7-no-such-user.db", "/tmp/skv-b7-no-such-shared.db")
        self.assertFalse(out["ok"])
        self.assertEqual(out["pages"], [])
        self.assertTrue(out["error"])
        self.assertNotIn("\n", out["error"][:1])

    def test_rest_page_is_one_slice_under_the_cap(self):
        page_a = "=== PACK888 001/002 ===\n" + ("q" * 30000)
        page_b = "=== CUBE 00 ===\nFULL CONST 00\n" + ("w" * 20000)
        built = {"ok": True, "pages": [page_a, page_b], "error": ""}
        room = {"text": "=== OTHER AGENTS ===\nbrief", "while_away": "ходы других: +1", "others_block": "=== OTHER AGENTS ===", "step_zero": True, "kind": "full"}
        first = select_rest_page(built, None, room)
        self.assertTrue(first["ok"])
        self.assertEqual(first["page"], 1)
        self.assertGreater(first["total_pages"], 1)
        self.assertNotIn("pages", first)
        self.assertIn("OTHER AGENTS", first.get("room_text") or "")
        self.assertIn("while_away", first)
        self.assertLessEqual(len(json.dumps(first, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), REST_RESPONSE_JSON)
        joined = []
        for n in range(1, first["total_pages"] + 1):
            got = select_rest_page(built, n, room)
            self.assertTrue(got["ok"])
            self.assertLessEqual(len(json.dumps(got, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), REST_RESPONSE_JSON)
            if n != 1:
                self.assertNotIn("room_text", got)
                self.assertNotIn("while_away", got)
            joined.append(got["text"])
        self.assertEqual("".join(joined), page_a + page_b)
        self.assertIn("FULL CONST 00", "".join(joined))
        missing = select_rest_page({"ok": False, "pages": [], "error": "user database not found"}, 1, room)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["pages"], [])
        self.assertEqual(missing["text"], "")
        self.assertIn("not found", missing["pack_error"])

    def test_gzip_pages_join_and_plain_fallback_stays_small(self):
        lines = []
        for i in range(4500):
            token = "%08x" % (i * 2654435761 & 0xFFFFFFFF)
            lines.append(
                "запись %04d %s Пользователь помнит факт %d про проект. уточнение %d"
                % (i, token, i, i % 17)
            )
        whole = "\n".join(lines)
        built = {"ok": True, "pages": [whole], "error": ""}
        room = {
            "text": "=== OTHER AGENTS ===\nbrief",
            "while_away": "ходы других: +1",
            "others_block": "=== OTHER AGENTS ===",
            "step_zero": True,
            "kind": "full",
        }
        gzip_first = select_rest_page(built, 1, room, "gzip")
        plain_first = select_rest_page(built, 1, room, "plain")
        self.assertTrue(gzip_first["ok"])
        self.assertTrue(plain_first["ok"])
        self.assertGreaterEqual(gzip_first["total_pages"], 4)
        self.assertLessEqual(gzip_first["total_pages"], 6)
        self.assertGreater(plain_first["total_pages"], gzip_first["total_pages"])
        self.assertIn("while_away", gzip_first)
        joined = []
        for n in range(1, gzip_first["total_pages"] + 1):
            got = select_rest_page(built, n, room, "gzip")
            self.assertTrue(got["ok"])
            raw = json.dumps(got, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.assertLessEqual(len(gzip.compress(raw, compresslevel=9, mtime=0)), REST_RESPONSE_GZIP)
            if n != 1:
                self.assertNotIn("while_away", got)
                self.assertNotIn("room_text", got)
            joined.append(got["text"])
        self.assertEqual("".join(joined), whole)
        plain_joined = []
        for n in range(1, plain_first["total_pages"] + 1):
            got = select_rest_page(built, n, room, "plain")
            self.assertLessEqual(
                len(json.dumps(got, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
                REST_RESPONSE_JSON,
            )
            plain_joined.append(got["text"])
        self.assertEqual("".join(plain_joined), whole)

    def test_http_attaches_pages_and_room_events(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from app.routers import room_http
            import app.step_zero_rest as step_zero_rest
            import app.room.bridge as bridge
            from app.room.events import record_event
            from app.room.schema import ensure
        except Exception:
            self.skipTest("fastapi is not installed here")
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        ensure(raw)
        info = {"key_id": "k-b7", "user_id": "b7@example.invalid", "chain_id": "ch-b7", "key_name": "line"}
        identified = bridge.do_identify(info, raw, "restb", "assistant", "", "s-b8")
        record_event(raw, "ch-b7", "k-b7", "mcp-a", "s-a", kind="brief", text="ship the pack", event_id="evA-room")

        class Hold:
            def close(self):
                return None

            def __getattr__(self, item):
                return getattr(raw, item)

        old_lookup, old_open, old_build = bridge.lookup_key, bridge.open_account, step_zero_rest.build_pages
        seen = {}

        def fake_build(user_id, user_db="", shared_db=""):
            seen["user"] = user_id
            return {"ok": True, "pages": [
                "=== PACK888 001/001 ===\n" + ("h" * 20000),
                "=== CUBE 00 ===\nFULL CONST 00\n",
            ], "error": ""}

        bridge.lookup_key = lambda token: info if token == "test-room-key" else None
        bridge.open_account = lambda _info: Hold()
        step_zero_rest.build_pages = fake_build
        try:
            app = FastAPI()
            app.include_router(room_http.router)
            client = TestClient(app)
            headers = {"Authorization": "Bearer test-room-key", "Accept-Encoding": "identity"}
            got = client.post(
                "/api/v7/agent/step_zero",
                json={"session_id": "s-rest", "agent_token": identified["agent_token"]},
                headers=headers,
            )
            self.assertEqual(got.status_code, 200)
            body = got.json()
            self.assertEqual(seen.get("user"), "b7@example.invalid")
            self.assertEqual(body["page"], 1)
            self.assertGreater(body["total_pages"], 1)
            self.assertNotIn("pages", body)
            self.assertIn("PACK888", body["text"])
            self.assertNotIn("FULL CONST 00", body["text"])
            self.assertTrue(body.get("room_text") or body.get("while_away") or body.get("others_block"))
            self.assertLessEqual(len(got.content), REST_RESPONSE_JSON)
            parts = [body["text"]]
            for n in range(2, body["total_pages"] + 1):
                nxt = client.post(
                    "/api/v7/agent/step_zero",
                    json={"session_id": "s-rest", "agent_token": identified["agent_token"], "page": n},
                    headers=headers,
                )
                self.assertEqual(nxt.status_code, 200)
                self.assertLessEqual(len(nxt.content), REST_RESPONSE_JSON)
                page_n = nxt.json()
                self.assertNotIn("room_text", page_n)
                self.assertNotIn("while_away", page_n)
                parts.append(page_n["text"])
            joined = "".join(parts)
            self.assertIn("FULL CONST 00", joined)
            self.assertIn("PACK888", joined)
            self.assertEqual(joined.count("h"), 20000)
            self.assertNotIn("pack_error", body)
            step_zero_rest.build_pages = lambda *a, **k: {"ok": False, "pages": [], "error": "user database not found"}
            bad = client.post("/api/v7/agent/step_zero", json={}, headers=headers)
            self.assertEqual(bad.status_code, 200)
            self.assertEqual(bad.json().get("pages"), [])
            self.assertEqual(bad.json().get("text"), "")
            self.assertIn("not found", bad.json().get("pack_error") or "")
            events = client.post("/api/v7/agent/room_events", json={}, headers=headers)
            self.assertEqual(events.status_code, 200)
            self.assertEqual(events.json()["room_events"][0]["ev"], "evA-room")
            self.assertEqual(client.post("/api/v7/agent/step_zero", json={}, headers={"Authorization": "Bearer no-such"}).status_code, 401)
            gzip_headers = dict(headers)
            gzip_headers["Accept-Encoding"] = "gzip"
            varied = "\n".join(
                "запись %04d про память агента и комнату, номер %d" % (i, i % 13)
                for i in range(2000)
            )
            step_zero_rest.build_pages = lambda *a, **k: {"ok": True, "pages": [varied], "error": ""}
            gz = client.post("/api/v7/agent/step_zero", json={"agent_token": identified["agent_token"]}, headers=gzip_headers)
            plain = client.post("/api/v7/agent/step_zero", json={"agent_token": identified["agent_token"]}, headers=headers)
            self.assertEqual(gz.status_code, 200)
            self.assertLess(gz.json()["total_pages"], plain.json()["total_pages"])
            self.assertEqual(gz.json()["page"], 1)
        finally:
            bridge.lookup_key = old_lookup
            bridge.open_account = old_open
            step_zero_rest.build_pages = old_build
            raw.close()


if __name__ == "__main__":
    unittest.main()
