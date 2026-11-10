"""Stop guard of the local-agent hook (installer/skv_hook.py): blocks the end of a reply with no SKV turn.
Run: python3 -m unittest tests.test_stop_guard  (no network: save() is stubbed)"""
import importlib.util, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEAL = "🔐 SKV | #12·ab12"


def load_hook(home):
    os.environ["SKV_HOME"] = home
    os.environ.pop("CURSOR_VERSION", None)
    os.environ.pop("SKV_STOP_GUARD", None)
    spec = importlib.util.spec_from_file_location("skv_hook_t", os.path.join(ROOT, "installer", "skv_hook.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.saved = []
    m.save = lambda um, ans, src, sid: m.saved.append((um, ans, src, sid)) or ""
    return m


def run(m, mode, ev):
    buf = io.StringIO()
    old, oldargv = sys.stdin, sys.argv
    sys.stdin = io.StringIO(json.dumps(ev))
    try:
        with redirect_stdout(buf):
            sys.argv = ["skv_hook.py", mode]
            m.main()
    finally:
        sys.stdin, sys.argv = old, oldargv
    out = buf.getvalue().strip()
    return json.loads(out) if out.startswith("{") else None


class StopGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = load_hook(self.tmp)

    def guard(self, on=True):
        p = os.path.join(self.tmp, "guard")
        if on:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def test_off_by_default_no_block(self):
        r = run(self.m, "claude-stop", {"session_id": "s1", "last_assistant_message": "hi"})
        self.assertIsNone(r)
        self.assertEqual(len(self.m.saved), 1)

    def test_claude_blocks_twice_then_fallback(self):
        self.guard()
        run(self.m, "claude-prompt", {"session_id": "s1", "prompt": "hello"})
        ev = {"session_id": "s1", "last_assistant_message": "answer without seal"}
        r1 = run(self.m, "claude-stop", ev)
        self.assertEqual(r1["decision"], "block")
        self.assertIn("same first step", r1["reason"])
        self.assertEqual(run(self.m, "claude-stop", ev)["decision"], "block")
        self.assertIsNone(run(self.m, "claude-stop", ev))            # third time: give up, fallback save
        self.assertEqual(len(self.m.saved), 1)
        run(self.m, "claude-prompt", {"session_id": "s1", "prompt": "next"})   # new user message resets the counter
        self.assertEqual(run(self.m, "claude-stop", ev)["decision"], "block")

    def test_sealed_answer_passes(self):
        self.guard()
        self.assertIsNone(run(self.m, "claude-stop", {"session_id": "s2", "last_assistant_message": "ok\n" + SEAL}))

    def test_grok_camelcase_and_session_end(self):
        self.guard()
        run(self.m, "claude-prompt", {"sessionId": "g1", "prompt": "hey"})
        r = run(self.m, "claude-stop", {"sessionId": "g1", "reason": "end_turn", "lastAssistantMessage": "no seal"})
        self.assertEqual(r["decision"], "block")
        self.assertIsNone(run(self.m, "claude-stop", {"sessionId": "g1", "reason": "shutdown", "lastAssistantMessage": "x"}))

    def test_transcript_turn_call_passes(self):
        self.guard()
        tp = os.path.join(self.tmp, "t.jsonl")
        rows = [{"type": "user", "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "mcp__skv__turn", "input": {}}]}}]
        open(tp, "w").write("\n".join(json.dumps(x) for x in rows))
        self.assertIsNone(run(self.m, "claude-stop", {"session_id": "s3", "transcript_path": tp, "last_assistant_message": "a"}))
        rows.append({"type": "user", "message": {"role": "user", "content": "second message"}})   # turn was for the older message
        open(tp, "w").write("\n".join(json.dumps(x) for x in rows))
        self.assertEqual(run(self.m, "claude-stop", {"session_id": "s3", "transcript_path": tp, "last_assistant_message": "a"})["decision"], "block")

    def test_off_file_pauses_guard(self):
        self.guard()
        open(os.path.join(self.tmp, "off"), "w").close()
        self.assertIsNone(run(self.m, "claude-stop", {"session_id": "s4", "last_assistant_message": "a"}))

    def test_cursor_followup_then_fallback(self):
        self.guard()
        run(self.m, "cursor-prompt", {"conversation_id": "c1", "prompt": "yo"})
        self.assertEqual(run(self.m, "cursor-response", {"conversation_id": "c1", "text": "plain answer"}), {})
        self.assertEqual(self.m.saved, [])                                   # saving waits for the stop event
        r = run(self.m, "cursor-stop", {"conversation_id": "c1", "status": "completed", "loop_count": 0})
        self.assertIn("followup_message", r)
        run(self.m, "cursor-response", {"conversation_id": "c1", "text": "still plain"})
        r = run(self.m, "cursor-stop", {"conversation_id": "c1", "status": "completed", "loop_count": 1})
        self.assertIn("followup_message", r)
        run(self.m, "cursor-response", {"conversation_id": "c1", "text": "still plain 2"})
        self.assertEqual(run(self.m, "cursor-stop", {"conversation_id": "c1", "status": "completed", "loop_count": 2}), {})
        self.assertEqual(len(self.m.saved), 1)

    def test_cursor_sealed_and_aborted(self):
        self.guard()
        run(self.m, "cursor-response", {"conversation_id": "c2", "text": "ok " + SEAL})
        self.assertEqual(run(self.m, "cursor-stop", {"conversation_id": "c2", "status": "completed"}), {})
        run(self.m, "cursor-response", {"conversation_id": "c3", "text": "partial"})
        self.assertEqual(run(self.m, "cursor-stop", {"conversation_id": "c3", "status": "aborted"}), {})
        self.assertEqual(run(self.m, "cursor-stop", {"status": "completed"}), {})   # no conversation_id (Grok Build): no-op

    def test_installer_registers_stop_and_grok(self):
        home = tempfile.mkdtemp()
        env = dict(os.environ, HOME=home, SKV_NO_HOOKS="0")
        import subprocess
        cfg = os.path.join(ROOT, "installer", "skv_config.py")
        os.makedirs(os.path.join(home, ".skv"))
        open(os.path.join(home, ".skv", "key"), "w").write("sk_test")
        for c in ("cursor", "grok-build"):
            r = subprocess.run([sys.executable, cfg, "install", c, os.path.join(home, ".skv"), "https://x.example"],
                               env=env, input="sk_test\n", capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        h = json.load(open(os.path.join(home, ".cursor", "hooks.json")))
        self.assertEqual(h["hooks"]["stop"][0]["loop_limit"], 2)
        self.assertIn("cursor-stop", h["hooks"]["stop"][0]["command"])
        g = json.load(open(os.path.join(home, ".grok", "hooks", "skv.json")))
        self.assertIn("claude-stop", g["hooks"]["Stop"][0]["hooks"][0]["command"])
        for c in ("cursor", "grok-build"):
            subprocess.run([sys.executable, cfg, "uninstall", c, os.path.join(home, ".skv"), "https://x.example"], env=env, capture_output=True)
        self.assertFalse(os.path.exists(os.path.join(home, ".grok", "hooks", "skv.json")))
        self.assertNotIn("stop", json.load(open(os.path.join(home, ".cursor", "hooks.json"))).get("hooks", {}))


if __name__ == "__main__":
    unittest.main()
