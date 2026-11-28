"""Replay the Gemini T96 gold set against turn_diet17. No network."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import turn_diet17 as d

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "t96_testset_gemini.jsonl")


def _load():
    rows = []
    with open(FIXTURE, encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            s = ln.strip()
            if not s:
                continue
            obj = json.loads(s)
            obj["_line"] = i
            rows.append(obj)
    return rows


def _got_turn(row):
    plan = d.apply_17c(
        {},
        row.get("user_message"),
        None,
        prev_answer=row.get("prev_answer"),
        minutes=row.get("minutes"),
    )
    mode = plan.get("mode") or ""
    reason = plan.get("skip_reason") or ""
    if mode == "directive" or reason == "directive":
        return "DIRECTIVE"
    if mode == "auto_skip" or reason == "empty_ack<15m":
        return "SKIP"
    return "SEARCH"


class GeminiTestset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _load()
        cls.turns = [r for r in cls.rows if r.get("type") == "turn"]
        cls.deltas = [r for r in cls.rows if r.get("type") == "delta"]

    def test_fixture_shape(self):
        self.assertEqual(len(self.turns), 60)
        self.assertEqual(len(self.deltas), 10)

    def test_all_turns_match(self):
        misses = []
        for r in self.turns:
            got = _got_turn(r)
            exp = r.get("expected")
            if got != exp:
                misses.append((r["_line"], r.get("user_message"), exp, got))
        self.assertEqual(misses, [], "turn mismatches: %s" % misses)

    def test_all_deltas_match(self):
        misses = []
        for r in self.deltas:
            gap = float(r.get("gap_hours") or 0)
            events = list(r.get("events") or [])
            client = r.get("client_seal")
            server = r.get("server_seal")
            if client is None:
                client = ""
            fires = bool(d.catchup_due(gap, client, server, len(events)))
            summary = d.format_delta(events, gap, since=r.get("since") or "") if fires else ""
            if fires != bool(r.get("expected_fires")) or summary != (r.get("expected_summary") or ""):
                misses.append({
                    "line": r["_line"],
                    "expected_fires": r.get("expected_fires"),
                    "got_fires": fires,
                    "expected_summary": r.get("expected_summary"),
                    "got_summary": summary,
                })
        self.assertEqual(misses, [], "delta mismatches: %s" % misses)


if __name__ == "__main__":
    unittest.main()
