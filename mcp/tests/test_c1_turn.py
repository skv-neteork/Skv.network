"""C1/C3: per-agent turn watch, Russian missed_turns duty, identify reminder on turn. Run: runtime/mcp_venv/bin/python mcp/tests/test_c1_turn.py"""
import sys, os, json, tempfile
sys.path.insert(0, "/root/skv-core/mcp")
sys.path.insert(0, "/root/skv-core/src")
import mcp_skv as m
m.COMPACT_DB = tempfile.mkdtemp() + "/c.db"
m._caller_id = lambda: "key-A"
ok = {}

def who(actor):
    m._tr()["room_who"] = {"ok": True, "implicit": False, "actor_id": actor} if actor else None

who(None); ok["key_without_agent"] = m._tw_key() == "key-A"
who("grok-bot"); ok["key_per_agent"] = m._tw_key() == "key-A#grok-bot"
who("grok-chat"); ok["key_other_agent"] = m._tw_key() == "key-A#grok-chat"
m._tr()["room_who"] = {"ok": True, "implicit": True, "actor_id": "line"}; ok["implicit_not_split"] = m._tw_key() == "key-A"

# each agent has its own msg_ref sequence: grok-chat at t5 does not make grok-bot's t1337 a gap
who("grok-bot"); m._tw_turn(True, 1, (1336, 1336)); d1 = m._tw_turn(True, 2, (1337, 1337))
who("grok-chat"); d2 = m._tw_turn(True, 1, (5, 5))
ok["no_cross_agent_gap"] = not d1 and not d2
who("grok-bot"); d3 = m._tw_turn(True, 3, (1340, 1340))
ok["gap_duty"] = d3.get("id") == "missed_turns" and d3.get("n") == 2 and d3.get("source") == "msg_ref"
ok["gap_text_ru"] = d3.get("do", "").startswith("missed_turns: пропущены t1338u–t1339u (2), пришли recap=[{ref,user,answer}]")
# a recap covering the refs resolves the duty
m._tw_cover([1341, 1342]); d4 = m._tw_turn(True, 4, (1343, 1343))
ok["recap_resolves"] = not d4
ok["refs_format"] = m._fmt_refs_ru([3, 4, 5, 9]) == "t3u–t5u, t9u"
bad = [k for k, v in ok.items() if not v]
print("%d/%d passed" % (len(ok) - len(bad), len(ok)), "FAILED: " + ",".join(bad) if bad else "")
sys.exit(1 if bad else 0)
