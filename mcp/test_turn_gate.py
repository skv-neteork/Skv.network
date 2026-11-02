"""Unit tests for the SKV MCP turn gate. Run: runtime/mcp_venv/bin/python mcp/test_turn_gate.py [path/to/mcp_skv.py]"""
import importlib.util, json, os, sys, tempfile, time
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "mcp_skv.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, "/root/skv-core/mcp")
spec = importlib.util.spec_from_file_location("mcp_skv_t", path); M = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]; spec.loader.exec_module(M)
M.COMPACT_DB = tempfile.mktemp(suffix=".db")
M._step_zero_pages = lambda: ["PAGE-ONE", "PAGE-TWO"]
M._tw_touch = lambda name: ""
M._post = lambda name, r: r
def memory_search(query=""): return json.dumps({"results": [1, 2], "q": query})
def board_list(): return "plain text board"
def turn(user_message="", draft=""): return json.dumps({"seal": "x"})
def step_zero(page=1):
    M._sz_seen_mark(); return json.dumps({"text": "sz"})   # real step_zero marks the key seen
def turn_stats(): return json.dumps({"n": 1})
S, B, T, Z, ST = (M._tw_wrap(f) for f in (memory_search, board_list, turn, step_zero, turn_stats))
ok = 0
def check(c, msg):
    global ok
    assert c, msg; ok += 1; print("ok", msg)
M._key_var.set("sk_test_gate_A")
o = json.loads(S("a")); check(list(o)[0] == "TURN_REQUIRED" and o["step_zero"]["text"] == "PAGE-ONE" and o["results"] == [1, 2], "first-ever call: notice first + step_zero package + result kept")
o = json.loads(S("b")); check("TURN_REQUIRED" in o and "step_zero" not in o, "second call: notice, no repeat step_zero")
r = B(); check(r.startswith("TURN_REQUIRED: ") and r.endswith("plain text board"), "plain-text result gets prefix")
check("TURN_REQUIRED" not in ST(), "meta tool exempt")
check("TURN_REQUIRED" not in T("hi"), "turn itself not gated")
o = json.loads(S("c")); check("TURN_REQUIRED" not in o, "after turn: notice cleared")
import sqlite3; c = sqlite3.connect(M.COMPACT_DB); c.execute("update turn_gate set last_turn=?", (time.time() - (M._TG_MIN + 1) * 60,)); c.commit(); c.close()
check("TURN_REQUIRED" in json.loads(S("d")), "stale turn (> SKV_TURN_GATE_MIN): notice again")
M._key_var.set("sk_test_gate_B"); Z()
o = json.loads(S("e")); check("TURN_REQUIRED" in o and "step_zero" not in o, "key that called step_zero: notice but no auto step_zero")
M._key_var.set("sk_test_gate_A"); M._TG_ON = False
check("TURN_REQUIRED" not in json.loads(S("f")), "SKV_TURN_GATE=0: off")
os.unlink(M.COMPACT_DB); print("ALL", ok, "passed")
