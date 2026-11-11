#!/usr/bin/env python3
import re
import os
"""SKV smoke test. Test/fresh accounts only. Usage: smoke.py  (env: SKV_TEST_KEY, SKV_REST, SKV_MCP)"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error, ssl, gzip
KEY = os.environ.get("SKV_TEST_KEY") or open("/root/.skvext_test_key").read().strip()  # skvext test (key file, rotated 25.10) account
REST = os.environ.get("SKV_REST", "http://127.0.0.1:8000/api/v7")
MCP = os.environ.get("SKV_MCP", "http://127.0.0.1:8765/k/%s/")
CTX = ssl._create_unverified_context()
R = []
def rec(name, ok, info=""):
    R.append((name, bool(ok), str(info)[:110])); print(("PASS " if ok else "FAIL ") + name + "  " + str(info)[:110], flush=True)

def http(url, body=None, headers=None, method=None):
    h = {"Content-Type": "application/json"}; h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, h, method=method or ("POST" if data else "GET"))
    try:
        r = urllib.request.urlopen(req, timeout=40, context=CTX); d = r.read()
        if r.headers.get("content-encoding") == "gzip": d = gzip.decompress(d)
        return r.status, d.decode(errors="replace"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), e.headers

def rest_turn(key, **kw):
    s, b, _ = http(REST + "/agent/turn", kw, {"X-API-Key": key})
    try: return s, json.loads(b)
    except Exception: return s, {"raw": b[:300]}

class Mcp:
    def __init__(self, key):
        self.url = MCP % key; self.h = {"Accept": "application/json, text/event-stream"}; self.i = 0
        s, b, hd = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}, raw=True)
        self.status = s
        if s == 200:
            if hd.get("mcp-session-id"): self.h["mcp-session-id"] = hd.get("mcp-session-id")  # absent in stateless mode
            http(self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, self.h)
    def rpc(self, method, params, raw=False):
        self.i += 1
        s, b, hd = http(self.url, {"jsonrpc": "2.0", "id": self.i, "method": method, "params": params}, self.h)
        if raw: return s, b, hd
        if "data:" in b and not b.lstrip().startswith("{"):
            b = "\n".join(l[5:].strip() for l in b.splitlines() if l.startswith("data:"))
        return json.loads(b)
    def call(self, name, args):
        j = self.rpc("tools/call", {"name": name, "arguments": args})
        t = "".join(c.get("text", "") for c in j.get("result", {}).get("content", []))
        try: return json.loads(t)
        except Exception:
            if os.environ.get("SMOKE_DEBUG"): print("RAW", name, json.dumps(j)[:400])
            return {"_text": t}

def seal_no(d):
    m = re.search(r"#(\d+)·([0-9a-f]+)", json.dumps(d, ensure_ascii=False)); return int(m.group(1)) if m else None

FRESH_KEY_FILE = "/root/skv-smoke/fresh_account.json"
def _dex(code):
    return subprocess.run(["docker", "exec", "skv_api", "python3", "-c", code], capture_output=True, text=True, timeout=60)

def consent_allow(key):
    """Smoke accounts: grandfathered consent row (notice shown long ago) so cube_create checks are not blocked by the notice window."""
    _dex("import sys,sqlite3;sys.path.insert(0,'/app');from app import api_keys as ak, cube_consent as cc;c=sqlite3.connect(cc.SHARED_DB,timeout=30);cc._c().close();u=ak.user_for(%r,conn=c);"
         "u=(u.get('email') if isinstance(u,dict) else u) or '';u=str(u).lower();assert 'test' in u or 'smoke' in u or 'skvext' in u, u;"
         "c.execute(\"INSERT INTO cube_consent (user_id,opted_out,notice_shown_at,source,updated_at) VALUES (?,0,'legacy-smoke','smoke',datetime('now')) ON CONFLICT(user_id) DO UPDATE SET opted_out=0,notice_shown_at='legacy-smoke',notice_ts=NULL\",(u,));c.commit()" % key)


def fresh_account():
    """One fixed smoke account, reset each run (its account DB is moved aside -> no install flag, no memory)."""
    os.makedirs(os.path.dirname(FRESH_KEY_FILE), exist_ok=True)
    if not os.path.exists(FRESH_KEY_FILE):
        code = ("import sys,sqlite3;sys.path.insert(0,'/app');from app import api_keys as ak;"
                "c=sqlite3.connect('/data/skv/metadata_store/shared_master.db',timeout=30);u='skvtest_smoke_fixed@test.skv.invalid';"
                "c.execute(\"INSERT OR IGNORE INTO users (email,password_hash,confirmed,created_at) VALUES (?,?,1,datetime('now'))\",(u,'!test'));"
                "k=ak.issue(u,'smoke',conn=c);c.commit();print(u);print(k)")
        u, k = _dex(code).stdout.split()[:2]
        json.dump({"email": u, "key": k}, open(FRESH_KEY_FILE, "w")); os.chmod(FRESH_KEY_FILE, 0o600)
    d = json.load(open(FRESH_KEY_FILE))
    assert d["email"].startswith("skvtest_smoke_fixed@"), "refusing to reset a non-smoke account"
    r = _dex("import sys,os;sys.path.insert(0,'/app');from app.memory_v2 import db_path;p=db_path(%r);"
             "[os.remove(p+x) for x in ('','-wal','-shm') if os.path.exists(p+x)];print('reset',p)" % d["email"])
    consent_allow(d["key"])
    return d["email"], d["key"]

def vault_has(user, value):
    r = _dex("import sys;sys.path.insert(0,'/app');from app import vault as v;c=v._db();"
             "print(c.execute('select count(*) from vault_secrets where user_id=? and fingerprint=?',(%r,v._fp(%r))).fetchone()[0])" % (user, value))
    try: return int(r.stdout.strip().split()[-1])
    except Exception: return -1

def skills_checks(tag):
    """Identify step 3 (skills and hooks as cubes) and the harvest state, on the fixed smoke account."""
    u, k = fresh_account()
    h = {"Authorization": "Bearer " + k}
    s1, b1, _ = http(REST + "/agent/identify", {"name": "smoke-sh-" + tag[-6:], "session_id": "sh-" + tag[-6:]}, h)
    try: d1 = json.loads(b1)
    except Exception: d1 = {}
    rec("SH1 identify reply carries step 3 (publish skills/hooks as cubes)", s1 == 200 and "cube_3de96286fc73" in str(d1.get("skills_step")) and "skills_none" in str(d1.get("skills_step")) and d1.get("skills_step") in str(d1.get("room_text")), str({k: v for k, v in d1.items() if k not in ("agent_token", "room_text")})[:100])
    s2, b2, _ = http(REST + "/agent/identify", {"name": "smoke-sh-" + tag[-6:], "session_id": "sh-" + tag[-6:]}, h)
    try: d2 = json.loads(b2)
    except Exception: d2 = {"raw": b2[:80]}
    rec("SH2 step 3 is shown once per agent", s2 == 200 and "skills_step" not in d2 and bool(d2.get("agent_token")), str({k: v for k, v in d2.items() if k not in ("agent_token", "room_text")})[:100])
    s3, b3, _ = http(REST + "/agent/room", {"agent_token": d2.get("agent_token", ""), "session_id": "sh-" + tag[-6:], "event_id": "", "saved": True, "duty": "skills_none"}, h)
    rec("SH3 room accepts duty=skills_none", s3 == 200 and "cube_harvest" not in b3 and "skills_harvest" not in b3, b3[:100])


def profile_checks(tag):
    """Profile layer (flag on for the skvext test account + the smoke account) and the MCP turn watch."""
    J = lambda d: json.dumps(d, ensure_ascii=False)
    rule = "smoke %s: never use emoji in answers to this user" % tag
    s, a = rest_turn(KEY, user_message="smoke %s profile add" % tag, draft="ok", session_id=tag,
                     profile=[{"op": "add", "kind": "prohibition", "text": rule, "scope": "topic:smoke%s" % tag, "ev": ["this"]}])
    ap = [x for x in (a.get("profile_applied") or []) if x.get("op") == "add"]
    pid = ap[0]["id"] if ap else ""
    rec("P1 profile add via REST turn", s == 200 and a.get("seal") and pid.startswith("prof:p_"), pid or J(a)[:100])
    n0 = seal_no(a)
    s, b = rest_turn(KEY, user_message="smoke %s profile secret" % tag, draft="ok", session_id=tag,
                     profile=[{"op": "add", "kind": "rule", "text": "use key sk_abcdef0123456789abcdef", "scope": "global", "ev": ["this"]}])
    s2, c = rest_turn(KEY, user_message="smoke %s after reject" % tag, draft="ok", session_id=tag)
    rec("P2 secret in profile -> revise, no seal burned", b.get("verdict") == "revise" and not b.get("seal") and seal_no(c) == (n0 or -9) + 1, "%s→%s" % (n0, seal_no(c)))
    s, d = rest_turn(KEY, user_message="smoke %s bad ev" % tag, draft="ok", session_id=tag,
                     profile=[{"op": "add", "kind": "rule", "text": "smoke rule with fake ev", "scope": "global", "ev": ["remember_1000000000000000001"]}])
    rec("P3 unknown ev id -> revise", d.get("verdict") == "revise", J(d.get("profile_errors"))[:100])
    s, e = rest_turn(KEY, user_message="smoke%s emoji answer style" % tag, draft="ok", session_id=tag + "r")
    rec("P4 turn returns relevant profile row", rule in J(e.get("profile") or e.get("profile_new") or []), J(e.get("profile"))[:100])
    s, e2 = rest_turn(KEY, user_message="можно использовать эмодзи в ответах?", draft="ok", session_id=tag + "ru")
    rec("P4b RU message -> EN profile row (semantic)", "emoji" in J(e2.get("profile") or e2.get("profile_new") or []), J(e2.get("profile"))[:100])
    st, bb, _ = http(REST + "/profile/block", None, {"X-API-Key": KEY})
    rec("P5 /profile/block shows the row", pid and pid in bb, bb[:100])
    s, f = rest_turn(KEY, user_message="smoke %s supersede" % tag, draft="ok", session_id=tag,
                     profile=[{"op": "supersede", "id": pid[5:], "text": rule + " (also no stickers)", "reason": "smoke refine"}])
    st, hb, _ = http(REST + "/memory/source", {"query": "prof:history"}, {"X-API-Key": KEY})
    new = [x["id"] for x in (f.get("profile_applied") or []) if x.get("op") == "supersede"]
    rec("P6 supersede keeps history", new and "supersede" in hb, (new or ["-"])[0] + " " + hb[:60])
    s, g = rest_turn(KEY, user_message="smoke %s retract" % tag, draft="ok", session_id=tag,
                     profile=[{"op": "retract", "id": new[0][5:] if new else "x", "reason": "smoke cleanup"}])
    rec("P7 retract", any(x.get("op") == "retract" for x in (g.get("profile_applied") or [])), J(g.get("profile_applied"))[:100])
    s, h = rest_turn(KEY, user_message="smoke %s: никогда не присылай мне длинные таблицы" % tag, draft="ok", session_id=tag)
    cand = [x for x in (h.get("profile_duties") or []) if x.get("kind") == "profile_candidate"]
    rec("P8 user rule without profile -> profile_candidate duty", cand, J(h.get("profile_duties"))[:100])
    if cand:
        rest_turn(KEY, user_message="smoke %s dismiss" % tag, draft="ok", session_id=tag,
                  profile=[{"op": "dismiss", "duty_id": cand[0]["id"], "reason": "smoke test, not a real rule"}])
    # L2 review gate on the smoke account (DB reset each run; flag kept in shared_master)
    email, fk = fresh_account()
    w = []
    for i in range(3):
        s, r = rest_turn(fk, user_message="smoke %s l2 %d" % (tag, i), draft="ok", session_id=tag, l2_summary="smoke L2 headline %d" % i)
        w.append(bool(r.get("seal")) and bool(r.get("profile_warnings")))
    rec("P9 L2 without profile_review: 3 warnings", all(w), w)
    s, r4 = rest_turn(fk, user_message="smoke %s l2 3" % tag, draft="ok", session_id=tag, l2_summary="smoke L2 headline 3")
    s, r5 = rest_turn(fk, user_message="smoke %s l2 4" % tag, draft="ok", session_id=tag, l2_summary="smoke L2 headline 4",
                      profile_review={"no_changes": True, "reason": "smoke period changed nothing about the user"})
    rec("P10 4th L2 rejected; with review passes", r4.get("verdict") == "revise" and not r4.get("seal") and r5.get("seal"), "%s/%s" % (r4.get("verdict"), bool(r5.get("seal"))))
    time.sleep(5)   # stay under the 300 req/min key limit
    m = Mcp(KEY)   # installed test account (the smoke account is uninstalled after its reset)
    t = m.call("turn", {"user_message": "smoke %s mcp profile" % tag, "draft": "ok", "session_id": tag,
                        "profile": J([{"op": "add", "kind": "preference", "text": "smoke %s: answers in short bullet lists" % tag, "scope": "global", "ev": ["this"]}])})
    dg = m.call("memory_dig", {"focus_id": "prof:list"})
    pid11 = [x["id"] for x in (t.get("profile_applied") or []) if x.get("op") == "add"]
    rec("P11 MCP turn profile + memory_dig prof:list", t.get("seal") and pid11 and pid11[0] in J(dg), J(t.get("profile_errors") or pid11)[:100])
    if pid11:
        m.call("turn", {"user_message": "smoke %s mcp cleanup" % tag, "draft": "ok", "session_id": tag,
                        "profile": J([{"op": "retract", "id": pid11[0][5:], "reason": "smoke cleanup"}])})
    # turn watch: age this caller's state, then a tool call must carry turn_reminder and turn must return missed_turns
    import sqlite3
    db = "/data/skv/metadata_store/compact_state_mcp.db"
    c = sqlite3.connect(db, timeout=10)
    k = c.execute("select k from tw order by last_call desc limit 1").fetchone()[0]
    c.execute("update tw set last_turn=?, last_call=?, bursts=3 where k=?", (time.time() - 1800, time.time() - 600, k)); c.commit(); c.close()
    sr = m.call("memory_search", {"query": "smoke"})
    rec("TW1 stale turn -> turn_reminder on other tools", "turn_reminder" in J(sr) and "turn" in J(sr.get("turn_reminder", sr)), J(sr.get("turn_reminder"))[:100])
    t2 = m.call("turn", {"user_message": "smoke %s after gap" % tag, "draft": "ok", "session_id": tag})
    rec("TW2 turn after gap -> missed_turns duty", "missed_turns" in J(t2.get("duties") or t2), J([x for x in (t2.get("duties") or []) if "missed" in J(x)])[:100])
    sr2 = m.call("memory_search", {"query": "smoke"})
    rec("TW3 fresh turn -> no reminder", "turn_reminder" not in J(sr2) and t2.get("seal"), J(sr2.get("turn_reminder") or t2.get("error") or "")[:100])
    # msg_ref: exact gap from client message ordinals (restore this caller's tw_ref row afterwards)
    c = sqlite3.connect(db, timeout=10)
    c.execute("create table if not exists tw_ref(k text primary key, last_ref int, t real)")
    old = c.execute("select k, last_ref, t from tw_ref where k=?", (k,)).fetchone(); c.close()
    base = 9000000 + int(time.time()) % 900000
    m.call("turn", {"user_message": "smoke %s ref a" % tag, "draft": "ok", "session_id": tag, "msg_ref": "t%du" % base})
    t4 = m.call("turn", {"user_message": "smoke %s ref b" % tag, "draft": "ok", "session_id": tag, "msg_ref": "t%du" % (base + 4)})
    mt4 = [x for x in (t4.get("duties") or []) if isinstance(x, dict) and x.get("id") == "missed_turns"]
    rec("TW4 msg_ref jump -> missed_turns n=3 source=msg_ref", mt4 and mt4[0].get("n") == 3 and mt4[0].get("source") == "msg_ref", J(mt4 or t4.get("duties"))[:100])
    t5 = m.call("turn", {"user_message": "smoke %s ref c" % tag, "draft": "ok", "session_id": tag, "msg_ref": "t%du" % (base + 5)})
    rec("TW5 consecutive msg_ref -> no missed_turns", "missed_turns" not in J(t5.get("duties") or []) and t5.get("seal"), J(t5.get("duties"))[:100])
    c = sqlite3.connect(db, timeout=10); c.execute("delete from tw_ref where k=?", (k,))
    if old: c.execute("insert into tw_ref values(?,?,?)", old)
    c.commit(); c.close()
    # draft-specific Second Look: rule questions quote the draft, silence when nothing fires, kept/changed stats
    time.sleep(3)
    # The tag keeps the quoted sentence unique so a previous run's second-look dedupe does not drop it.
    s, q1 = rest_turn(KEY, user_message="smoke %s which port does the api use?" % tag, session_id=tag + "sl",
                      draft="Great question! You told me last time that the api listens on port 8443 (%s)." % tag)
    qs = q1.get("second_look_questions") or []
    rec("SL1 rule questions first, quoting the draft", qs and list(q1)[0] == "second_look_questions" and 2 <= len(qs) <= 4 and "last time" in qs[0] and "8443" in J(qs),
        J(qs)[:110])
    s, q2 = rest_turn(KEY, user_message="smoke %s which port again?" % tag, session_id=tag + "sl", second_look="kept|changed: dropped the unsourced port",
                      draft="Great question! Earlier you said it is 8443.")
    st = q2.get("second_look_stats") or {}
    rec("SL2 second_look answers counted (kept/changed, revision_rate)", st.get("changed", 0) >= 1 and st.get("kept", 0) >= 1 and st.get("revision_rate") is not None, J(st)[:100])
    s, q3 = rest_turn(KEY, user_message="smoke %s say ok" % tag, session_id=tag + "sl", draft="ok")
    rec("SL3 clean draft -> no second_look_questions", s == 200 and q3.get("seal") and "second_look_questions" not in q3, J(q3.get("second_look_questions"))[:100])
    s, q5 = rest_turn(KEY, user_message="smoke %s ext status?" % tag, session_id=tag + "sl5",
                      draft="Guard2 ext 0.1.3 Le Chat adapter works live: new chat 79fb1679, reply Ten, seal #1157, v2 build, see [ev:remember_1790000000000000001].")
    rec("SL5 versions/ids/#seals -> no number question", s == 200 and "unsourced" not in J(q5.get("second_look_questions")) and "0.1" not in J(q5.get("second_look_questions")), J(q5.get("second_look_questions"))[:100])
    s, q6 = rest_turn(KEY, user_message="smoke %s is 8443 the port?" % tag, session_id=tag + "sl6", draft="Yes, the api uses 8443; load is %d.7%%." % (int(time.time()) % 89 + 10))
    qq6 = J(q6.get("second_look_questions"))
    rec("SL6 number from user_message skipped, full token quoted", "\\\"8443\\\"" not in qq6 and "8443\\\" come" not in qq6 and ".7%" in qq6, qq6[:110])
    t6 = m.call("turn", {"user_message": "smoke %s mcp port?" % tag, "session_id": tag, "draft": "As we decided yesterday, the limit is 300 requests."})
    rec("SL4 MCP turn returns second_look_questions first", list(t6)[:1] == ["second_look_questions"] and "yesterday" in J(t6.get("second_look_questions")) and "reminder" not in t6,
        J(t6.get("second_look_questions"))[:100])
    # test account is pinned to Europe/Moscow (MCP caches tz 10 min). TZ: display in the account zone with label + age; storage stays UTC
    http(REST + "/account/timezone", {"tz": "Europe/Moscow"}, {"X-API-Key": KEY})
    time.sleep(1)
    tzr = J(Mcp(KEY).call("memory_search", {"query": "smoke"}))
    rec("TZ1 memory_search times in account zone + age", "MSK (" in tzr and re.search(r"MSK \((just now|\d+\w+ ago)\)", tzr) and not re.search(r"\d{2}:\d{2}(?::\d{2})? UTC", tzr), re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \w+ \([^)]*\)", tzr)[:1])
    bt, bb2, _ = http(REST + "/account/timezone", {"tz": "Mars/Base"}, {"X-API-Key": KEY})
    rec("TZ2 unknown zone rejected", bt == 422, bt)

def supersede_checks(m, tag):
    """Cubes are never edited in place: a fix is a new version with supersedes=<old>."""
    tok = "zq" + tag[-6:] + "vers"
    base = dict(topic="smoke versioning %s retry flaky upload" % tok, kind="lifehack", evidence="smoke run %s" % tag,
                essence="Retry a flaky %s upload three times with backoff before reporting failure." % tok,
                rules="1. Retry the upload up to three times.\n2. Wait 1s, 2s, 4s between tries.\n3. Report the last error if all fail.")
    a = m.call("cube_create", base); A = a.get("cube_id", "")
    rec("SV1 cube_create new cube", a.get("status") == "ok" and A.startswith("cube_"), json.dumps(a)[:120])
    try:
        e = m.call("cube_create", dict(base, cube_id=A, essence=base["essence"] + " Edited."))
        rec("SV2 in-place edit refused (409, hint supersedes)", "never edited in place" in json.dumps(e) and "supersedes" in json.dumps(e), json.dumps(e)[:140])
        b = m.call("cube_create", dict(base, supersedes=A, essence="Retry a flaky %s upload three times with exponential backoff, then report the last error." % tok,
                                       rules=base["rules"] + "\n4. Log each attempt with its delay."))
        B = b.get("cube_id", "")
        rec("SV3 new version with supersedes", b.get("status") == "ok" and B and B != A and b.get("supersedes") == A, json.dumps(b)[:140])
        r = _dex("import sqlite3,json;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
                 "a=c.execute('select status,links_json from cubes_new where cube_id=?',(%r,)).fetchone();"
                 "b=c.execute('select parent_id from cubes_new where cube_id=?',(%r,)).fetchone();"
                 "print(json.dumps([a[0],json.loads(a[1] or '{}').get('superseded_by'),b[0]]))" % (A, B))
        try: st = json.loads((r.stdout or "").strip().splitlines()[-1])
        except Exception: st = [r.stderr[-120:]]
        rec("SV4 old marked superseded_by new, new.parent_id=old", st == ["superseded", B, A], json.dumps(st)[:120])
        sr = json.dumps(m.call("cube_search", {"query": "flaky %s upload retry" % tok}))
        rec("SV5 search shows newest only", B in sr and A not in sr.split("hidden_superseded_versions")[0], sr[:140] if B not in sr else "")
        e2 = m.call("cube_create", dict(base, supersedes=A, essence="Third try %s" % tok))
        rec("SV6 superseding a superseded cube refused", "already superseded" in json.dumps(e2) and B in json.dumps(e2), json.dumps(e2)[:140])
        r = _dex("import sys;sys.path.insert(0,'/app');from app import chain_skills as cs;"
                 "print(cs.newest_version(%r)==%r, 'ZZTAIL' not in cs.core_only('core line'+chr(10)+'## PART 2 REFERENCE'+chr(10)+'ZZTAIL'))" % (A, B))
        r8 = _dex("import sys;sys.path.insert(0,'/app');from app import profile as p;"
                  "print(bool(p._NOPUB.search(\"Don't publish my cubes\")), bool(p._NOPUB.search('не публикуй кубы')), bool(p._NOPUB.search('Publish cubes in English')))")
        rec("SV8 'don't publish' opt-out detected (EN/RU), normal text not", (r8.stdout or "").strip() == "True True False", (r8.stdout or r8.stderr)[-120:])
        rec("SV7 installs follow newest; CORE-only skill delivery", (r.stdout or "").strip() == "True True", (r.stdout or r.stderr)[-120:])
        # foreign cube: a new version is a pending candidate until the court (or 3 distinct +1) approves
        try:
            k2 = json.load(open(FRESH_KEY_FILE))["key"]
        except Exception:
            fresh_account(); k2 = json.load(open(FRESH_KEY_FILE))["key"]
        m2 = Mcp(k2)
        f = m2.call("cube_create", dict(base, supersedes=B, essence="Retry a flaky %s upload with jittered exponential backoff, then report the last error." % tok,
                                        rules=base["rules"] + "\n4. Add random jitter to each delay."))
        D = f.get("cube_id", "")
        r = _dex("import sqlite3,json;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
                 "a=c.execute('select status,links_json from cubes_new where cube_id=?',(%r,)).fetchone();d=c.execute('select status,parent_id from cubes_new where cube_id=?',(%r,)).fetchone();"
                 "print(json.dumps([a[0],json.loads(a[1] or '{}').get('proposed_versions'),d[0],d[1]]))" % (B, D))
        try: st = json.loads((r.stdout or "").strip().splitlines()[-1])
        except Exception: st = [r.stderr[-120:]]
        rec("SV9 other author's version -> pending candidate, old stays", f.get("status_version") == "pending" and st == [st[0], [D], "pending_version", B] and st[0] != "superseded", json.dumps([f.get("status_version"), st])[:140])
        sr = m.call("cube_search", {"query": "flaky %s upload retry" % tok}); sj = json.dumps(sr)
        hit = [x for x in sr.get("results", []) if x.get("cube_id") == B]
        rec("SV10 search shows old + proposed_newer_version link", hit and hit[0].get("proposed_newer_version") == D and D not in sj.split("proposed_newer_version")[0], sj[:140])
        r = _dex("import sys,sqlite3;sys.path.insert(0,'/app');from app import cube_suggest as cs;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
                 "fid=c.execute(\"select id from cube_fixes where cube_id=? and reason like ? and status='pending'\",(%r,'version:%s%%')).fetchone()[0];"
                 "cs.apply_fix(c,fid,True,'j1:approve; j2:approve');c.commit();"
                 "print(c.execute('select status from cubes_new where cube_id=?',(%r,)).fetchone()[0],c.execute('select status from cubes_new where cube_id=?',(%r,)).fetchone()[0])" % (B, D, B, D))
        rec("SV11 court approval promotes it (old superseded)", (r.stdout or "").strip() == "superseded community", (r.stdout or r.stderr)[-140:])
        st_, b_, _ = http(REST + "/court/removal_request", {"cube_id": D, "ground": "dislike", "reason": "smoke wrong ground"}, {"X-API-Key": KEY})
        rec("RM0 /court/removal_request route exists, bad ground refused", st_ in (400, 401, 403, 422), "%s %s" % (st_, b_[:100]))
        r = _dex("import sys,sqlite3,json;sys.path.insert(0,'/app');from app import cube_suggest as cs;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
                 "a=cs.request_removal(c,%r,'smoke','dislike','i just do not like it');b=cs.request_removal(c,%r,'smoke','personal_data','smoke %s: rules contain a leaked phone number');"
                 "b2=cs.request_removal(c,%r,'smoke','personal_data','smoke %s duplicate request here');q=c.execute('select reason from court_queue where cube_id=?',(%r,)).fetchone();"
                 "cs.apply_fix(c,b['fix_id'],True,'j1:approve; j2:approve');c.commit();"
                 "print(json.dumps([a['ok'],b['ok'],b.get('kind'),b2['fix_id']==b['fix_id'],bool(q and 'removal:personal_data' in q[0]),c.execute('select status from cubes_new where cube_id=?',(%r,)).fetchone()[0]]))" % (D, D, tok, D, tok, D, D))
        try: rm = json.loads((r.stdout or "").strip().splitlines()[-1])
        except Exception: rm = [r.stderr[-160:]]
        rec("RM1 removal needs a valid ground (no author retract)", rm[:1] == [False], json.dumps(rm)[:140])
        rec("RM2 valid removal_request -> pending court item, idempotent", rm[1:5] == [True, "removal_request", True, True], json.dumps(rm)[:140])
        rec("RM3 court approval removes it (archived, kept in archive)", rm[5:6] == ["archived"], json.dumps(rm)[:140])
    finally:
        _dex("import sqlite3;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
             "c.execute(\"DELETE FROM cube_fixes WHERE cube_id IN (select cube_id from cubes_new where subject_action_object LIKE ?)\",('%%%s%%',));"
             "c.execute(\"DELETE FROM court_queue WHERE cube_id IN (select cube_id from cubes_new where subject_action_object LIKE ?)\",('%%%s%%',));"
             "c.execute(\"DELETE FROM cubes_new WHERE subject_action_object LIKE ?\",('%%%s%%',));c.commit()" % (tok, tok, tok))

def search_checks(m, tag):
    """memory_search: multi-word RU (any-term + stems), date window / exclude_imports, board source; CO5 profile retract."""
    tok = "zq" + tag[-6:] + "srch"
    fa = json.load(open(FRESH_KEY_FILE)); k2, u2 = fa["key"], fa["email"].lower()
    m2 = Mcp(k2)
    try:
        rest_turn(k2, user_message="Смоук %s: деплой сломался, исправил перезапуском воркера вместо отката" % tok, draft="Записал.", session_id="smoke-search")
        time.sleep(2)
        a = m2.call("memory_search", {"query": "почему сломался деплой и как исправили %s" % tok, "lines": "all"})
        rec("MS1 multi-word RU question -> found (any-term + stems)", tok in json.dumps(a, ensure_ascii=False), json.dumps(a, ensure_ascii=False)[:160])
        b = m2.call("memory_search", {"query": "деплой исправил %s" % tok, "lines": "all", "since": "1d"})
        c = m2.call("memory_search", {"query": "деплой исправил %s" % tok, "lines": "all", "until": "2001-01-01"})
        # The empty MCP payload repeats the query in its message, so judge the hit list only.
        b_hits = json.dumps(b.get("results") if isinstance(b, dict) else b, ensure_ascii=False)
        c_hits = json.dumps(c.get("results") if isinstance(c, dict) else c, ensure_ascii=False)
        rec("MS2 since=1d finds it, until=2001 excludes it", tok in b_hits and tok not in c_hits, "since=%s until=%s" % (tok in b_hits, tok in c_hits))
        n = m2.call("board_act", {"action": "add", "kind": "note", "title": "cube candidate: %s warm cache" % tok, "text": "smoke note"})
        iid = (n.get("item") or {}).get("id") or n.get("id") or n.get("item_id") or ""
        d = m2.call("memory_search", {"query": "cube candidate:", "source": "board", "lines": "all"})
        rec("MS3 source=board finds 'cube candidate:' note", tok in json.dumps(d, ensure_ascii=False), json.dumps(d, ensure_ascii=False)[:160])
        if iid: m2.call("board_act", {"action": "remove", "item_id": iid})
        rest_turn(k2, user_message="Не публикуй мои кубы", draft="Понял.", session_id="smoke-search",
                  profile=json.dumps([{"op": "add", "kind": "prohibition", "text": "Do not publish my cubes anywhere (%s)" % tok, "scope": "global", "ev": ["this"]}]))
        rest_turn(k2, user_message="можно снова публиковать мои кубы", draft="Ок.", session_id="smoke-search")
        r = _dex("import sys;sys.path.insert(0,'/app');from app import profile as p, cube_consent as cc;c=p._db(%r);"
                 "print(c.execute(\"select count(*) from profile_log where op='retract'\").fetchone()[0], not p.publish_opted_out(%r), cc.info(%r)['status'])" % (u2, u2, u2))
        o = (r.stdout or "").split()
        rec("CO5 later 'можно снова публиковать' retracts profile prohibition (log) -> allowed", len(o) == 3 and int(o[0]) > 0 and o[1] == "True" and o[2] in ("allowed", "notice_required"), (r.stdout or r.stderr)[-140:])
        # HK1/HK2: own version that swaps hooks of a cube installed by another account -> court only; text-only -> immediate
        hb = dict(topic="smoke hooks %s retry backoff order" % tok, kind="skill", carrier="skill", evidence="smoke run %s" % tag,
                  essence="Retry the %s call with backoff before reporting failure." % tok,
                  rules="1. Retry twice with backoff.\n2. Then report the error.",
                  skill_md="---\nname: retry-%s\ndescription: retry with backoff\n---\n# Steps\n1. Retry." % tok,
                  hooks=json.dumps([{"when": "on_error", "do": "retry once"}]))
        A = m.call("cube_create", hb).get("cube_id", "")
        ins = m2.call("cube_install", {"cube_id": A, "user_confirmed": True, "user_quote": "да, установи"})
        g = m.call("cube_create", dict(hb, supersedes=A, essence=hb["essence"] + " Log each attempt.",
                                       hooks=json.dumps([{"when": "on_error", "do": "retry once and send logs"}])))
        live = _dex("import sys;sys.path.insert(0,'/app');from app import chain_skills as c;print(c.newest_version(%r))" % A)
        rec("HK1 own hooks change on a cube installed by others -> pending court_only; installs keep old hooks",
            g.get("status_version") == "pending" and g.get("court_only") is True and (live.stdout or "").strip() == A, json.dumps([g.get("status_version"), g.get("court_only"), (live.stdout or "").strip() == A, str(ins)[:60]]))
        g2 = m.call("cube_create", dict(hb, supersedes=A, essence=hb["essence"] + " Then alert.", hooks=json.dumps([{"when": "on_error", "do": "retry once then alert"}])))
        rec("DV1 second pending version of the same cube + same topic -> duplicate_pending", "duplicate_pending" in json.dumps(g2), json.dumps(g2)[:140])
        mp = [m.call("cube_create", dict(topic="smoke merge %s part %s queue drain" % (tok, x), kind="lifehack", evidence="smoke run %s" % tag,
                      essence="Drain the %s %s queue before restart to keep jobs." % (tok, x), rules="1. Stop intake.\n2. Drain the queue.\n3. Restart.")).get("cube_id", "") for x in ("ka", "kb")]
        mm = m.call("cube_create", dict(topic="smoke merge %s merged queue drain" % tok, kind="lifehack", evidence="smoke run %s" % tag,
                    essence="Drain every %s queue before restart; intake stopped first." % tok, rules="1. Stop intake.\n2. Drain all queues.\n3. Restart.")).get("cube_id", "")
        lk = m.call("cube_link", {"src": mm, "dst": mp[0], "kind": "from"})
        gone = mp[0] not in json.dumps(m.call("cube_search", {"query": "smoke merge %s part ka queue drain" % tok}))
        rec("MG1 cube_link(from) own part -> superseded, leaves search", lk.get("merge") == "merged" and gone, json.dumps([lk, gone])[:140])
        b1 = m.call("board_act", {"action": "add", "kind": "note", "title": "smoke key %s" % tok, "key": "ev_smoke_" + tok})
        b2 = m.call("board_act", {"action": "add", "kind": "note", "title": "smoke key %s again" % tok, "key": "ev_smoke_" + tok})
        rec("BK1 board_act key -> second add idempotent", b2.get("idempotent") is True and b2.get("id") == b1.get("id"), json.dumps([b1.get("id"), b2.get("id"), b2.get("idempotent")]))
        m.call("board_act", {"action": "remove", "item_id": b1.get("id", "")})
        t = m.call("cube_create", dict(hb, supersedes=A, essence="When %s keeps timing out, give up after two attempts and tell the user plainly what failed." % tok, topic=hb["topic"]))
        cs = m.call("court_case", {})
        k = [x for x in (cs.get("fixes") or []) if x.get("new_cube_id") == g.get("cube_id")]
        k = k[0] if k else {}
        k1 = m.call("court_case", {"fix_id": k.get("id") or 0}) if k else {}
        rec("CC1 court case has old + new in full and separate hooks/skill_md diffs",
            bool(k) and k1.get("old", {}).get("hooks") is not None and k1.get("new", {}).get("hooks") and k1.get("hooks_changed") is True
            and "hooks" in k1.get("diff", {}) and "skill_md" in k1.get("diff", {}) and k1["diff"]["hooks"].get("unified", "").count("+") > 0
            and k1["old"].get("essence") and k1["new"].get("essence"),
            json.dumps([k.get("id"), k1.get("hooks_changed"), k1.get("skill_md_changed"), sorted((k1.get("diff") or {}).keys())])[:140])
        r = _dex("import sys,sqlite3;sys.path.insert(0,'/app');from app import cube_suggest as cs;c=sqlite3.connect(':memory:');cs.ensure_fix(c);"
                 "[c.execute(\"INSERT INTO cube_fixes (cube_id,user_id,reason,ts) VALUES ('x','rl@t','fix',datetime('now'))\") for _ in range(cs.COURT_MAX_PENDING)];"
                 "print(cs.court_rate(c,'rl@t') is not None, cs.court_rate(c,'other@t') is None)")
        rec("RL1 per-account court filing limit (open cases)", (r.stdout or "").strip() == "True True", (r.stdout or r.stderr)[-140:])
        r = _dex(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke_court.py")).read())
        rec("CJ1 human court: author can't judge, reason required, 2 distinct accounts approve, reasons stored, complaints appended, fresh voter unverified",
            (r.stdout or "").strip().startswith("{"), (r.stdout or r.stderr)[-200:])
        rec("HK2 own text-only version -> immediate", t.get("cube_id") and not t.get("status_version") and "superseded_by" in (t.get("note") or ""), json.dumps(t)[:140])
        d = m.call("cube_create", dict(hb, supersedes=t.get("cube_id") or A, essence=hb["essence"] + " Log each attempt.", topic=hb["topic"]))
        rec("DP1 duplicate check ignores pending versions (same text as pending HK1 -> not 'already')", d.get("status") != "already", json.dumps(d)[:140])
        m2.call("cube_uninstall", {"cube_id": A})
    except Exception as e:
        rec("MS search checks crashed", False, repr(e)[:160])


def consent_checks(m, tag):
    """v4 server items: PII field report, intent opt-out (RU/EN), fail closed, notice_shown, court-only skill/hook changes, MCP removal tool."""
    tok = "zq" + tag[-6:] + "cons"
    fa = json.load(open(FRESH_KEY_FILE)); k2, u2 = fa["key"], fa["email"].lower()
    m2 = Mcp(k2)
    base = dict(topic="smoke consent %s cache warmup order" % tok, kind="lifehack", evidence="smoke run %s" % tag,
                essence="Warm the %s cache before the first request to avoid a cold start timeout." % tok,
                rules="1. Call the warmup endpoint once after deploy.\n2. Wait until it returns 200.\n3. Then route traffic.")
    reset = ("import sqlite3;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
             "c.execute('CREATE TABLE IF NOT EXISTS cube_consent (user_id TEXT PRIMARY KEY, opted_out INTEGER DEFAULT 0, notice_shown_at TEXT, source TEXT, updated_at TEXT)');"
             "c.execute('DELETE FROM cube_consent WHERE user_id=?',(%r,));c.commit()" % u2)
    try:
        _dex(reset)
        p = m.call("cube_create", dict(base, rules=base["rules"] + "\n4. Mail ops.lead@example.org if it fails."))
        pj = json.dumps(p)
        rec("CP1 PII in shared cube -> rejected with field+reason", "personal data or secret" in pj and '"field": "rules"' in pj and '"reason": "email"' in pj, pj[:160])
        p2 = m.call("cube_create", dict(base, essence=base["essence"] + " Key sk_abcdefghijklmnopqrstuvwx."))
        rec("CP2 secret -> rejected naming essence", '"field": "essence"' in json.dumps(p2) and "secret:" in json.dumps(p2), json.dumps(p2)[:160])
        st, d = rest_turn(k2, user_message="Пожалуйста, не публикуй мои кубы никуда", draft="Понял.", session_id="smoke-consent")
        c1 = m2.call("cube_consent", {"action": "status"})
        rec("CO1 RU intent 'не публикуй' (server-side, via turn) -> opted_out", c1.get("status") == "opted_out", json.dumps(c1)[:140])
        f = m2.call("cube_create", base); f2 = m2.call("cube_create", dict(base, cube_publish=False))
        rec("CO2 opted out -> shared AND private cube_create refused (403)", "opted out" in json.dumps(f) and "opted out" in json.dumps(f2), (json.dumps(f) + json.dumps(f2))[:160])
        rest_turn(k2, user_message="ok, you may publish again", draft="Ok.", session_id="smoke-consent")
        c2 = m2.call("cube_consent", {"action": "status"})
        rest_turn(k2, user_message="please stop sharing my stuff", draft="Ok.", session_id="smoke-consent")
        c3 = m2.call("cube_consent", {"action": "status"})
        rest_turn(k2, user_message="можно снова публиковать", draft="Ок.", session_id="smoke-consent")
        rec("CO3 EN 'stop sharing' -> opted_out; 'may publish again'/'можно снова публиковать' -> allowed", c2.get("status") in ("allowed","notice_required") and c3.get("status") == "opted_out" and m2.call("cube_consent", {}).get("status") in ("allowed","notice_required"), json.dumps([c2.get("status"), c3.get("status")]))
        rest_turn(k2, user_message="Rule for the cube: the user can say 'don't publish' and the agent stops. Design decision: no retract of published cubes. Make v7, no publishing.", draft="Ok.", session_id="smoke-consent")
        c5 = m2.call("cube_consent", {"action": "status"})
        rest_turn(k2, user_message="не публикуй мои кубы", draft="Ок.", session_id="smoke-consent")
        c6 = m2.call("cube_consent", {"action": "status"})
        rest_turn(k2, user_message="Я за публикацию, можно снова публиковать", draft="Ок.", session_id="smoke-consent")
        c7 = m2.call("cube_consent", {"action": "status"})
        rec("CO6 rule/meta talk ('don't publish' quoted, no retract, no publishing for a draft) -> NOT opted out", c5.get("status") in ("allowed", "notice_required"), str(c5.get("status")))
        rec("CO7 direct 'не публикуй мои кубы' -> opted_out; later opt-in retracts", c6.get("status") == "opted_out" and c7.get("status") in ("allowed", "notice_required"), json.dumps([c6.get("status"), c7.get("status")]))
        r = _dex("import sys;sys.path.insert(0,'/app');from app import cube_consent as cc;print(cc.profile_nopub(\"Agent gives a one-time notice (user can say 'don't publish')\"), cc.profile_nopub('User asked: do not publish my cubes'))")
        rec("CO8 profile notice/quote row is not an opt-out; direct row is", (r.stdout or "").strip() == "False True", (r.stdout or r.stderr)[-120:])
        r = _dex("import sys;sys.path.insert(0,'/app');from app import cube_consent as cc, profile as p;p.publish_opted_out=lambda u: None;print(cc.info(%r)['status'])" % u2)
        rec("CO4 unknown permission -> status unknown (create fails closed)", (r.stdout or "").strip() == "unknown", (r.stdout or r.stderr)[-120:])
        n0 = m2.call("cube_consent", {"action": "status"}); n1 = m2.call("cube_consent", {"action": "notice_shown"}); n2 = m2.call("cube_consent", {"action": "status"})
        rec("NS1 notice_shown stored server-side, notice text only until shown", (not n0.get("notice_shown")) and n0.get("notice") and n1.get("notice_shown") and n2.get("notice_shown") and not n2.get("notice"), json.dumps([n0.get("notice_shown"), n2.get("notice_shown")]))
        rec("NS2 status notice_required before notice, notice_pending right after", n0.get("status") == "notice_required" and n2.get("status") == "notice_pending", json.dumps([n0.get("status"), n2.get("status")]))
        _dex(reset); m2.call("cube_consent", {"action": "notice_shown", "msg_ref": "t500u"})
        q1 = m2.call("cube_consent", {"action": "status", "msg_ref": "t500u"}); q2 = m2.call("cube_create", dict(base, msg_ref="t500u"))
        rec("NP1 same-turn: status notice_pending, cube_create -> 409 notice_pending", q1.get("status") == "notice_pending" and "notice_pending" in json.dumps(q2) and not q2.get("cube_id"), json.dumps([q1.get("status"), json.dumps(q2)[:90]]))
        rest_turn(k2, user_message="[t500u] ok", draft="Ok.", session_id="smoke-consent")
        q3 = m2.call("cube_consent", {"action": "status"})
        rest_turn(k2, user_message="[t501u] next question", draft="Ok.", session_id="smoke-consent")
        q4 = m2.call("cube_consent", {"action": "status"}); q5 = m2.call("cube_consent", {"action": "status", "msg_ref": "t501u"})
        rec("NP2 notice turn itself still pending; after the user's next message -> allowed", q3.get("status") == "notice_pending" and q4.get("status") == "allowed" and q5.get("status") == "allowed", json.dumps([q3.get("status"), q4.get("status"), q5.get("status")]))
        _dex(reset); m2.call("cube_consent", {"action": "notice_shown"}); rest_turn(k2, user_message="smoke same turn no ref", draft="Ok.", session_id="smoke-consent")
        q6 = m2.call("cube_consent", {}); rest_turn(k2, user_message="smoke later message no ref", draft="Ok.", session_id="smoke-consent"); q7 = m2.call("cube_consent", {})
        rec("NP3 no msg_ref: pending until a second distinct user message", q6.get("status") == "notice_pending" and q7.get("status") == "allowed", json.dumps([q6.get("status"), q7.get("status")]))
        consent_allow(k2)
        a = m.call("cube_create", dict(base, skill_md="---\nname: warming-caches\ndescription: warm caches\n---\n# Steps\n1. Warm up.", carrier="skill"))
        A = a.get("cube_id", "")
        g = m2.call("cube_create", dict(base, supersedes=A, essence="Warm the %s cache and verify a 200 before routing traffic." % tok,
                                        skill_md="---\nname: warming-caches\ndescription: warm caches\n---\n# Steps\n1. Warm up.\n2. Also run the extra hook.", carrier="skill"))
        G = g.get("cube_id", "")
        r = _dex("import sqlite3,json;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
                 "[c.execute(\"INSERT OR REPLACE INTO cube_outcomes (cube_id,user_id,outcome,ts) VALUES (?,?,'helped',datetime('now'))\",(%r,u)) for u in ('smk_a_%s','smk_b_%s')];c.commit()" % (G, tok, tok))
        v = m.call("cube_vote", {"cube_id": G, "vote": 1, "reason": "smoke used it"})
        r = _dex("import sqlite3;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');print(c.execute('select status from cubes_new where cube_id=?',(%r,)).fetchone()[0], c.execute('select status from cubes_new where cube_id=?',(%r,)).fetchone()[0])" % (A, G))
        rec("CT1 foreign skill_md change -> court_only, votes cannot promote", g.get("court_only") is True and (r.stdout or "").strip() == "community pending_version", json.dumps([g.get("court_only"), (r.stdout or r.stderr)[-80:]]))
        x1 = m2.call("court_removal_request", {"cube_id": A, "ground": "dislike", "reason": "not a valid ground at all"})
        x2 = m2.call("court_removal_request", {"cube_id": A, "ground": "personal_data", "reason": "smoke %s: names a private person" % tok})
        rec("MR1 MCP court_removal_request: bad ground refused, valid -> pending court item", "valid ground" in json.dumps(x1) and x2.get("kind") == "removal_request" and x2.get("status") == "pending", json.dumps([x1, x2])[:160])
    finally:
        _dex(reset); consent_allow(k2)
        _dex("import sqlite3;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db');"
             "c.execute(\"DELETE FROM cube_outcomes WHERE user_id LIKE ?\",('smk_%%%s',));"
             "c.execute(\"DELETE FROM cube_fixes WHERE cube_id IN (select cube_id from cubes_new where subject_action_object LIKE ?)\",('%%%s%%',));"
             "c.execute(\"DELETE FROM court_queue WHERE cube_id IN (select cube_id from cubes_new where subject_action_object LIKE ?)\",('%%%s%%',));"
             "c.execute(\"DELETE FROM cubes_new WHERE subject_action_object LIKE ?\",('%%%s%%',));c.commit()" % (tok, tok, tok, tok))


def main():
    tag = "smoke%d" % int(time.time())
    consent_allow(KEY)
    # 1 bad key
    s, _ = rest_turn("sk_bad000000000000000000", user_message="x", draft="y")
    rec("bad key REST 401", s == 401, s)
    try:
        m = Mcp("sk_bad000000000000000000"); st = m.status
        if st == 200:
            r = m.call("turn", {"user_message": "x", "draft": "y"}); st = 401 if re.search(r"401|invalid|unknown key|api key", json.dumps(r), re.I) else 200
    except Exception as e: st = "err %s" % e
    rec("bad key MCP 401", st == 401, st)
    # 2 REST turn twice, monotonic seal
    s1, a = rest_turn(KEY, user_message="smoke %s rest A" % tag, draft="Smoke answer A.", session_id=tag)
    s2, b = rest_turn(KEY, user_message="smoke %s rest B" % tag, draft="Smoke answer B.", session_id=tag)
    n1, n2 = seal_no(a), seal_no(b)
    rec("REST turn save+seal monotonic", s1 == 200 and a.get("event_id") and n1 and n2 and n2 > n1, "%s %s ev=%s" % (n1, n2, a.get("event_id")))
    # 3 public MCP turn
    m = Mcp(KEY)
    c = m.call("turn", {"user_message": "smoke %s mcp C" % tag, "draft": "Smoke answer C.", "session_id": tag})
    n3 = seal_no(c)
    rec("MCP turn save+seal monotonic (shared counter)", c.get("event_id") and n3 and n2 and n3 > n2, "%s ev=%s" % (n3, c.get("event_id")))
    # 4 compact twice
    c1 = m.call("turn", {"user_message": "smoke %s compact 1" % tag, "answer": "Compact one.", "compact": True, "session_id": tag + "c"})
    c2 = m.call("turn", {"user_message": "smoke %s compact 2" % tag, "answer": "Compact two.", "compact": True, "session_id": tag + "c"})
    l1, l2 = len(json.dumps(c1, ensure_ascii=False)), len(json.dumps(c2, ensure_ascii=False))
    rec("compact turn x2 (2nd smaller, sealed)", seal_no(c1) and seal_no(c2) and seal_no(c2) > seal_no(c1) and l2 < l1, "%d->%d bytes" % (l1, l2))
    # 5 placeholder ok / fake revise
    p = m.call("turn", {"user_message": "smoke %s placeholder" % tag, "draft": "Cite facts as [ev:id] in answers.", "session_id": tag})
    rec("placeholder [ev:id] -> pass", p.get("verdict") == "pass", p.get("verdict"))
    f = m.call("turn", {"user_message": "smoke %s fake" % tag, "draft": "As noted [ev:remember_999999999999999999].", "session_id": tag})
    rec("fake ev -> revise", f.get("verdict") == "revise", f.get("verdict"))
    # 6 sensitive -> vault, no plaintext
    secret = "smk_SECRET_%s" % os.urandom(4).hex()
    sv = m.call("turn", {"user_message": "smoke %s my token is %s" % (tag, secret), "draft": "Saved your token [SECRET].", "sensitive": secret, "session_id": tag})
    time.sleep(1)
    srch = m.call("memory_search", {"query": secret})
    blob = json.dumps(sv, ensure_ascii=False) + json.dumps(srch, ensure_ascii=False)
    rec("sensitive: no plaintext in reply/search", secret not in blob and seal_no(sv) is not None, "sealed=%s" % (seal_no(sv) is not None))
    acct = (sv.get("event_id") or "").split("::")[0]
    nv = vault_has(acct, secret)
    rec("sensitive -> really stored in vault", nv >= 1, "vault rows=%d" % nv)
    # 7 fresh account: no save before install
    try:
        email, fk = fresh_account()
        fm = Mcp(fk)
        ft = fm.call("turn", {"user_message": "hello", "draft": "hi"})
        ms = fm.call("memory_start", {})
        rec("fresh acct: no save/seal before install", not ft.get("event_id") and seal_no(ft) is None and ms.get("installed") is False, "%s %s" % (email, ft.get("verdict") or str(ft)[:60]))
        bs, bb, _ = http(REST + "/session/bootstrap", {"recent_messages": [{"role": "assistant", "content": "hello there, this is a smoke message"}]}, {"X-API-Key": fk})
        rec("fresh acct: session_bootstrap ok (no event_metadata error)", bs == 200 and "no such table" not in bb, "%s %s" % (bs, bb[:80] if bs != 200 or "no such table" in bb else ""))
    except Exception as e:
        rec("fresh acct: no save/seal before install", False, e)
    # 8 step_zero pages reach done=true. The pack grows; 40 pages is no longer enough.
    done, pg, err = False, 1, ""
    while pg <= 80:
        z = m.call("step_zero", {"page": pg})
        if z.get("_text") is not None and not z.get("pages"): err = z["_text"][:80]
        if z.get("done") is True: done = True; break
        pg += 1
    rec("step_zero pages -> done=true", done, "pages=%d %s" % (pg, err))
    # 9 Russian query returns facts
    m.call("turn", {"user_message": "Решение: в компактном режиме печать печати одной строкой, %s" % tag, "draft": "Записал решение про компактный режим и печать.", "session_id": tag})
    r = m.call("turn", {"user_message": "что мы решили про компактный режим и печать?", "draft": "Проверка поиска.", "session_id": tag})
    facts = r.get("facts") or r.get("memory") or r.get("hits") or []
    rec("RU query -> facts in turn", len(facts) > 0, "n=%d" % len(facts))
    # Live community cube. cube_688c0ebbb3be and cube_9ff3f12ce0ba are superseded.
    _harvest = "cube_3de96286fc73"
    cs1 = m.call("cube_search", {"query": "how to create a cube"})
    rec("CS1 'how to create a cube' -> current harvest cube", _harvest in json.dumps(cs1), json.dumps([x.get("cube_id") for x in cs1.get("results") or []])[:120])
    _sec = "zq9smk" + tag.replace("_", "")[-6:]
    rest_turn(KEY, user_message="my test password is %s, reply OK" % _sec, session_id=tag + "sc1", draft="OK")
    m.call("turn", {"user_message": "my api key is %sx, reply OK" % _sec, "draft": "OK", "session_id": tag + "sc1"})
    import subprocess, glob
    _leak = subprocess.run("docker logs --since 2m skv_api 2>&1 | grep -c %s; grep -rlaF %s /data/skv/metadata_store | head -3" % (_sec, _sec), shell=True, capture_output=True, text=True).stdout.split()
    # HV: periodic cube_harvest reminder (app/cube_harvest.py), skvext test account
    import sqlite3 as _sq
    _hu = "denizchavdarov+skvext@gmail.com"; _hdb = "/data/skv/metadata_store/cube_harvest.db"
    _c = _sq.connect(_hdb); _c.execute("create table if not exists h(user text primary key, last_t real, last_rowid int, shown_t real, n_done int default 0)")
    _c.execute("insert or replace into h(user,last_t,last_rowid,shown_t,n_done) values(?,?,0,0,0)", (_hu, time.time() - 4 * 86400)); _c.commit(); _c.close()
    _sz = m.call("step_zero", {"page": 1})
    rec("HV1a step_zero page1 shows cube_harvest when due", (_sz.get("cube_harvest") or {}).get("cube_id") == _harvest, str(_sz.get("cube_harvest"))[:100])
    _ht = m.call("turn", {"user_message": "hv check, reply OK", "draft": "OK", "session_id": tag + "hv"})
    rec("HV1b turn duties carry cube_harvest", "cube_harvest" in json.dumps(_ht) and _harvest in json.dumps(_ht), json.dumps(_ht.get("duties"))[:100])
    m.call("turn", {"user_message": "harvest done", "draft": "OK", "session_id": tag + "hv", "duty": "cube_harvest", "duty_reason": "nothing: smoke test"})
    _c = _sq.connect(_hdb); _lt = _c.execute("select last_t from h where user=?", (_hu,)).fetchone()[0]; _c.close()
    rec("HV2 duty=cube_harvest resets the timer", time.time() - _lt < 300, "%.0fs ago" % (time.time() - _lt))
    _cs2 = m.call("cube_search", {"query": "cube harvesting"})
    rec("CS2 'cube harvesting' -> current harvest cube", _harvest in json.dumps(_cs2), json.dumps([x.get("cube_id") for x in _cs2.get("results") or []])[:120])
    rec("SC1 secret not in access log / state DBs", _leak[:1] == ["0"] and len(_leak) == 1, " ".join(_leak)[:120])
    # cube_install consent from the user's quoted reply, no prior turn (fresh MCP session per key state reset not needed: quote is fresh)
    cs = m.call("cube_search", {"query": "memory"})
    cl = cs.get("cubes") or cs.get("results") or cs.get("items") or []
    cq = next((x.get("cube_id") for x in cl if x.get("carrier") == "skill" and not x.get("own")), None) or next((x.get("cube_id") for x in cl if x.get("cube_id")), None)
    if cq:
        r0 = m.call("cube_install", {"cube_id": cq, "user_confirmed": True, "user_quote": "нет, не надо"})
        rec("CI1 cube_install quote 'нет' -> refused", r0.get("installed") is False and "consent" in str(r0.get("error")), str(r0.get("error"))[:80])
        r1 = m.call("cube_install", {"cube_id": cq, "user_confirmed": True, "user_quote": "да"})
        rec("CI2 cube_install quote 'да' w/o prior turn -> consent accepted (server decides the cube)", "no user consent" not in json.dumps(r1, ensure_ascii=False) and "ask_first" not in json.dumps(r1), json.dumps(r1, ensure_ascii=False)[:100])
        m.call("cube_uninstall", {"cube_id": cq})
    else:
        rec("CI1/2 cube for consent test", False, "no cube from cube_search")
    # 10 board v2
    w = "zebrafoo%s" % os.urandom(2).hex()
    def ba(**kw): return m.call("board_act", kw)
    t = ba(action="add", title="Smoke %s quartz migration" % w, text="smoke board item", priority=1)
    tid = t.get("id")
    rec("board add -> todo + priority", (t.get("item") or {}).get("status") == "todo" and (t.get("item") or {}).get("priority") == 1, tid)
    st = ba(action="add_subtask", parent_id=tid, title="Smoke %s sub" % w)
    sid = st.get("id")
    rec("board add_subtask -> parent_id", (st.get("item") or {}).get("parent_id") == tid, sid)
    rec("board start -> doing", (ba(action="start", item_id=tid).get("item") or {}).get("status") == "doing", tid)
    rec("board block needs waiting_for", "waiting_for" in json.dumps(ba(action="block", item_id=sid)), "422 ok")
    bk = ba(action="block", item_id=sid, waiting_for="user")
    rec("board block waiting_for=user", (bk.get("item") or {}).get("status") == "blocked", (bk.get("item") or {}).get("waiting_for"))
    z = m.call("step_zero", {"page": 1}).get("text", "")
    rec("step_zero p1: doing item + waiting", tid in z and ("- %s [doing]" % tid) in z and sid in z and ("- %s [blocked]" % sid) in z and "(waiting: user)" in z, "")
    tr = m.call("turn", {"user_message": "how is the %s quartz migration going?" % w, "answer": "Готово: quartz migration %s исправил и проверил." % w, "compact": True, "session_id": tag + "b"})
    ids = [x.get("id") for x in (tr.get("board") or [])]
    rec("turn -> relevant board items (<=3)", tid in ids and len(ids) <= 3, ids)
    rec("turn -> 'looks done?' hint", tid in str(tr.get("board_hint") or ""), str(tr.get("board_hint"))[:60])
    rec("board done without result -> refused", "result" in json.dumps(ba(action="done", item_id=tid)) and not ba(action="done", item_id=tid).get("item"), "")
    dn = ba(action="done", item_id=tid, result="smoke: migration verified")
    ev = tr.get("event_id") or ""
    rec("board done stores result + turn event", (dn.get("item") or {}).get("status") == "done" and dn.get("result_event") and dn.get("result_event").split("::")[-1] == ev.split("::")[-1], str(dn.get("result_event"))[-24:])
    rec("board park / reopen", (ba(action="park", item_id=sid).get("item") or {}).get("status") == "parked" and (ba(action="reopen", item_id=sid).get("item") or {}).get("status") == "todo", sid)
    old = ba(action="progress", item_id=sid)
    rec("board old action names still work", (old.get("item") or {}).get("status") == "doing", "progress->doing")
    # stale reminder: backdate the doing subtask 30h (title carries the unique tag w)
    _dex("import glob,sqlite3\nfor f in glob.glob('/data/skv/metadata_store/*.db'):\n  try:\n    c=sqlite3.connect(f); c.execute(\"UPDATE board_items SET updated_at=datetime('now','-30 hours') WHERE title LIKE ?\", ('%%%s sub%%',)); c.commit(); c.close()\n  except Exception: pass" % w)
    sz = m.call("step_zero", {"page": 1}).get("text", "")
    trs = m.call("turn", {"user_message": "что нового по %s?" % w, "compact": True, "session_id": tag + "s"})
    stl = trs.get("board_stale") or []
    rec("BS1 turn -> board_stale (doing idle >24h) + hint", any(x.get("id") == sid for x in stl) and len(stl) <= 3 and "park" in str(trs.get("board_stale_hint")), json.dumps(stl, ensure_ascii=False)[:100])
    rec("BS2 step_zero p1 lists the backdated doing item", sid in sz and ("- %s [doing]" % sid) in sz, "")
    for x in (sid, tid): ba(action="remove", item_id=x)
    # MCP restart must not break an existing client (stateless HTTP)
    subprocess.run(["systemctl", "restart", "skv-mcp-public"]); time.sleep(4)
    ra = m.call("board_list", {})
    rec("ST1 same MCP client works after MCP restart", isinstance(ra, dict) and not ra.get("error") and "session" not in json.dumps(ra).lower()[:200], json.dumps(ra)[:80])
    rest_t = rest_turn(KEY, user_message="smoke %s rest board" % w, draft="ok", session_id=tag)[1]
    rec("REST turn has no board leak after remove", tid not in json.dumps(rest_t.get("board") or []), "")
    # archive steps 1+2: archived raw text readable via /event and found by memory search + recall_later seeds
    tok = "zorblaxq" + "".join(chr(97 + int(ch)) for ch in str(int(time.time()))[-5:])
    _pre = ("import sys,sqlite3;sys.path.insert(0,'/app');from app import api_keys as ak;from app.memory_v2 import db_path;"
            "u=ak.user_for(%r);c=sqlite3.connect(db_path(u),timeout=30);eid=u+'::smokearch_%s';" % (KEY, tok))
    # real archive pass (t625): old event with FTS rows + vectors -> compressed archive, rows/vectors gone, text readable
    _setup = _pre.replace(";", "\n") + """
import json, numpy as np
from app import archive_store as A, semantic as S, search_v2 as V
raw = 'user: my old archived parrot is called %s and lives in Tver'
c.execute('INSERT INTO event_metadata (event_id,time_str,essence,raw_dialogue) VALUES (?,?,?,?)', (eid, '12:00, 01.06.2026', 'smoke archived', raw))
c.execute('INSERT INTO events_fts (event_id, raw_dialogue) VALUES (?,?)', (eid, raw))
V.sync(c); c.execute('INSERT INTO events_fts_stem (event_id, body) VALUES (?,?)', (eid, V.stem_text(raw)))
A._tables(c); S._ensure_table(c, 'pvec_mml12'); c.execute("INSERT OR REPLACE INTO pvec_mml12 (event_id, created_at) VALUES (?, datetime('now'))", (eid,)); c.commit()
nm = S.account_name(u); v = np.random.rand(1, S.MODELS['mml12']['dim']).astype('float32')
S.STORE.add('mml12', nm, [eid], v); S.STORE.add('mml12', nm + '__chunks', [eid + '#0'], v)
def cnt():
    r = {t: c.execute('SELECT count(*) FROM %%s WHERE event_id=?' %% t, (eid,)).fetchone()[0] for t in ('events_fts', 'events_fts_stem', 'pvec_mml12')}
    r['hnsw'] = int(eid in S.STORE._load('mml12', nm)['pos']); r['chunks'] = int(eid + '#0' in S.STORE._load('mml12', nm + '__chunks')['pos']); return r
before = cnt(); res = A.run_db(db_path(u), only_ids=[eid]); after = cnt()
z = c.execute('SELECT raw_dialogue IS NULL, length(body_z) > 0 FROM event_archive WHERE event_id=?', (eid,)).fetchone()
print(json.dumps({'eid': eid, 'before': before, 'after': after, 'z': list(z or []), 'purged': res.get('purged')}))
""" % tok
    r = _dex(_setup)
    try:
        _ar = json.loads((r.stdout or "").strip().split("\n")[-1])
    except Exception:
        _ar = {"eid": "", "err": (r.stderr or r.stdout or "")[-200:]}
    rec("AR0 archive pass: FTS/vector rows+hnsw gone, text zlib", all(_ar.get("before", {}).values()) and _ar.get("before") and not any(_ar.get("after", {1: 1}).values()) and _ar.get("z") == [1, 1], json.dumps(_ar)[:160])
    r.stdout = _ar.get("eid", "")
    aeid = (r.stdout or "").strip().split("\n")[-1]
    try:
        ev = m.call("memory_event", {"event_id": aeid})
        rec("AR1 memory_event archived -> full text + tag", tok in json.dumps(ev) and '"archived": true' in json.dumps(ev), json.dumps(ev)[:100] if tok not in json.dumps(ev) else "")
        srh = m.call("memory_search", {"query": "parrot " + tok, "lines": "all"})  # synthetic event has no memory line
        rec("AR2 memory_search finds archived text", tok in json.dumps(srh) and "archiv" in json.dumps(srh), json.dumps(srh)[:120] if tok not in json.dumps(srh) else "")
        rl = _dex(_pre + "from app import recall_later as rl;print(any(q.startswith('archive:') and %r in str(x) for q,x in rl._seed_searches(u,'parrot %s')))" % (tok, tok))
        rec("AR3 recall_later seeds use archive", (rl.stdout or "").strip().endswith("True"), (rl.stderr or rl.stdout)[-120:])
    finally:
        _dex(_pre + "c.execute('DELETE FROM event_metadata WHERE event_id=?',(eid,));c.execute('DELETE FROM event_archive WHERE event_id=?',(eid,));c.commit()")
    try: supersede_checks(m, tag)
    except Exception as e: rec("supersede checks ran", False, repr(e))
    try: search_checks(m, tag)
    except Exception as e: rec('MS search_checks', False, repr(e)[:120])
    try: consent_checks(m, tag)
    except Exception as e: rec("consent checks ran", False, repr(e))
    try: profile_checks(tag)
    except Exception as e: rec("profile checks ran", False, repr(e))
    try: skills_checks(tag)
    except Exception as e: rec("skills checks ran", False, repr(e))
    # CL: close this run's test-account court cases (no judge calls): withdraw pending fixes, drop their queue rows
    _cl = _dex("import sqlite3;c=sqlite3.connect('/data/skv/metadata_store/shared_master.db',timeout=30);"
               "w=\"status='pending' AND (lower(user_id)='denizchavdarov+skvext@gmail.com' OR lower(user_id) LIKE '%.invalid')\";"
               "ids=[r[0] for r in c.execute('SELECT DISTINCT cube_id FROM cube_fixes WHERE '+w)];"
               "n=c.execute(\"UPDATE cube_fixes SET status='withdrawn',verdict='smoke cleanup',decided_at=datetime('now') WHERE \"+w).rowcount;"
               "q=sum(c.execute(\"DELETE FROM court_queue WHERE cube_id=? AND NOT EXISTS (SELECT 1 FROM cube_fixes WHERE cube_id=? AND status='pending')\",(i,i)).rowcount for i in ids);"
               "c.commit();print(n,q,c.execute('SELECT COUNT(*) FROM cube_fixes WHERE '+w).fetchone()[0])")
    _clo = (_cl.stdout or "").split()
    rec("CL1 test-account court cases closed (no paid calls)", len(_clo) == 3 and _clo[2] == "0", (_cl.stdout or _cl.stderr or "")[-120:])
    print("\n%-48s %s" % ("CHECK", "RESULT")); print("-" * 60)
    for n, ok, i in R: print("%-48s %s  %s" % (n, "PASS" if ok else "FAIL", i))
    print("-" * 60); print("%d/%d PASS" % (sum(o for _, o, _ in R), len(R)))
    sys.exit(0 if all(o for _, o, _ in R) else 1)
if __name__ == "__main__": main()
