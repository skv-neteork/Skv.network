"""Auto step_zero on the first turn of a new key (2026-11-02). Run: runtime/mcp_venv/bin/python mcp/tests/test_sz_auto.py"""
import sys, os, json, tempfile
sys.path.insert(0, "/root/skv-core/mcp")
import mcp_skv as m
m.COMPACT_DB = tempfile.mkdtemp() + "/c.db"
key = {"v": "sk_test_A"}
m._active_key = lambda: key["v"]
m._step_zero_pages = lambda: ["PAGE1 tail L1 L2 critical profile board " + "x" * 7000, "CONST2"]
base = json.dumps({"verdict": "pass", "saved": True, "seal": "S", "facts": [{"fact": "y" * 4000}], "duties": ["z" * 3000]})
ok = {}
r = json.loads(m._sz_auto_attach(base)); ok["first_has_sz"] = "step_zero" in r and r["step_zero"]["note"].startswith("auto: new key") and r["step_zero"]["text"].startswith("PAGE1") and r["step_zero"]["pages"] == 2
ok["first_sz_whole"] = len(r["step_zero"]["text"]) > 7000 and r["seal"] == "S" and list(r)[0] == "step_zero"
ok["first_within_limit"] = len(m._sz_auto_attach.__globals__["json"].dumps(r, ensure_ascii=False, separators=(",", ":"))) <= m._SZ_AUTO_LIMIT
ok["second_unchanged"] = m._sz_auto_attach(base) == base
key["v"] = "sk_test_B"; ok["new_key_again"] = "step_zero" in json.loads(m._sz_auto_attach(base))
key["v"] = "sk_test_C"; m._sz_seen_mark(); ok["after_step_zero_no_auto"] = m._sz_auto_attach(base) == base
key["v"] = "sk_test_D"; nb = json.dumps({"installed": False, "seal": None}); ok["not_installed_skip"] = m._sz_auto_attach(nb) == nb and m._sz_auto_due()
rc = json.dumps({"mode": "recap"}); ok["recap_skip"] = m._sz_auto_attach(rc) == rc
ok["not_json_passthrough"] = m._sz_auto_attach("plain") == "plain"
import inspect; ok["turn_signature"] = list(inspect.signature(m.turn).parameters) == list(inspect.signature(m._turn_core).parameters) and "ONE CALL PER TURN" in (m.turn.__doc__ or "")
c = m._sz_seen_db(); ok["no_raw_key_stored"] = not any("sk_test" in str(x) for x in c.execute("select * from sz_key_seen").fetchall()); c.close()
bad = [k for k, v in ok.items() if not v]
print("%d/%d passed" % (len(ok) - len(bad), len(ok)), "FAILED: " + ",".join(bad) if bad else "")
sys.exit(1 if bad else 0)
