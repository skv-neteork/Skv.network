"""SKV memory v2 tests. Run on the server: python3 tests_v2.py [A|B|C|all]. Uses localhost:8000."""
import json, sys, time, urllib.request, urllib.parse, statistics, os
BASE = os.environ.get("SKV_LOCAL", "http://127.0.0.1:8000")
KEY = os.environ.get("SKV_KEY", "")
if not KEY:
    raise SystemExit("set SKV_KEY")
SECRET = KEY
RES = []
def api(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    r = urllib.request.Request(BASE + path, data=data, method=method, headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read().decode(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(); code = e.code
    ms = (time.time() - t) * 1000
    try: d = json.loads(raw)
    except Exception: d = raw
    return code, d, ms, len(raw)
def check(name, cond, info=""):
    RES.append({"test": name, "ok": bool(cond), "info": info}); print(("PASS " if cond else "FAIL ") + name + ("  " + str(info) if info else ""))
def step_now():
    return api("GET", "/api/v7/memory/settings")  # no-op
def mem(**kw):
    return api("POST", "/api/v7/memory", kw)
def tok(d): 
    s = json.dumps(d, ensure_ascii=False); a = sum(1 for ch in s if ord(ch) < 128); return int(a/4 + (len(s)-a)/2.5)
LEGACY_KEYS = {"server_time","prompt_text","memory","fragments","previous","agent_hint","span","lens","links","shared_cubes","open_tasks","due","constitution","reminders","duty_error","has_cubes","step","memory_map","vector_top10","fts_top10","intersection","best_vector","best_fts","best_intersection"}
DEBUG = {"vector_top10","fts_top10","intersection","best_vector","best_fts","best_intersection","memory"}
def stepA():
    c, d0, ms, n = mem(query_text="SKV architecture memory layers", probe=True)
    check("A0 default view is agent", isinstance(d0, dict) and d0.get("view") == "agent", d0.get("view") if isinstance(d0, dict) else d0)
    c, d, ms, n = mem(query_text="SKV architecture memory layers", probe=True, view="legacy")
    check("A1 legacy keys unchanged", c == 200 and set(d.keys()) == LEGACY_KEYS, sorted(set(d.keys()) ^ LEGACY_KEYS) if isinstance(d, dict) else d)
    s0 = d.get("step")
    c, d2, ms, n = mem(query_text="SKV architecture memory layers", probe=True, view="legacy")
    check("A2 legacy probe=true does not bump step", d2.get("step") == s0, (s0, d2.get("step")))
    check("A3 probe has no duty_error", not d2.get("duty_error"), d2.get("duty_error"))
    c, a, ms, n = mem(query_text="SKV architecture memory layers", view="agent", session_id="t_" + str(time.time()))
    check("A4 agent view no debug fields", c == 200 and not (DEBUG & set(a.keys())), sorted(DEBUG & set(a.keys())))
    check("A5 agent view no step bump without interact", a.get("step") == s0, (s0, a.get("step")))
    check("A6 first call of new session has memory_map + constitution_compact", bool(a.get("memory_map")) and bool(a.get("constitution_compact")) and a["session"]["first"])
    sid = a["session"]["id"]
    c, a2, ms, n = mem(query_text="forget archive purge", view="agent", session_id=sid)
    check("A7 follow-up in same session has no map/constitution", not a2.get("memory_map") and not a2.get("constitution_compact") and not a2["session"]["first"])
    check("A8 hits present with match_type", bool(a2.get("hits")) and all("match_type" in h for h in a2["hits"]), [h.get("match_type") for h in a2.get("hits", [])])
    c, a3, ms, n = mem(query_text="API key", view="agent", session_id="t_sec_" + str(time.time()), budget_hits=999999)
    check("A9 budget clamped to cap", a3["budget"]["limits"]["hits"] == 3000, a3["budget"]["limits"]["hits"])
    blobs = [json.dumps(x, ensure_ascii=False) for x in (d, d2, a, a2, a3)]
    c, lg, ms, n = mem(query_text="API_KEY получен от пользователя", probe=True, view="legacy")
    blobs.append(json.dumps(lg, ensure_ascii=False))
    c, dg, ms, n = api("POST", "/api/v7/memory/dig", {"query": "API_KEY получен"})
    blobs.append(json.dumps(dg, ensure_ascii=False))
    for f in dg.get("found", [])[:3]:
        if f.get("open"):
            c, ev, ms, n = api("GET", urllib.parse.quote(f["open"], safe="/:"))
            blobs.append(json.dumps(ev, ensure_ascii=False))
    leak = [i for i, b in enumerate(blobs) if SECRET and SECRET in b]
    check("A10 API key never appears in memory/dig/event output", not leak and any("[masked]" in b for b in blobs), leak)
    c, t, ms, n = api("GET", "/api/v7/memory/start?session_id=t_start_" + str(int(time.time())))
    check("A11 GET /memory/start returns text pack", c == 200 and "SKV MEMORY" in t.get("prompt_text", ""), c)
    c, st, ms, n = api("GET", "/api/v7/memory/settings")
    check("A12 settings shows defaults+caps", c == 200 and st["defaults"]["raw"] == 3000 and st["caps"]["raw"] == 8000)
    c, g, ms, n = api("GET", "/api/v7/agent/memory?query=" + urllib.parse.quote("T-particles") + "&view=agent&probe=true")
    check("A13 GET /agent/memory view=agent -> text", c == 200 and "prompt_text" in g, c)
def stepB():
    sid = "t_b_" + str(time.time())
    c, a, ms, n = mem(view="agent", session_id=sid, start=True)
    mm = a.get("memory_map"); w = a.get("windows") or {}
    check("B1 map is structured (who/projects/topics)", isinstance(mm, dict) and "topics" in mm and "who" in mm, type(mm).__name__)
    check("B2 three windows present", bool(w.get("raw")) and "l1" in w and "l2" in w, {k: len(v) for k, v in w.items() if isinstance(v, list)})
    raw_rows = [r["rowid"] for r in w.get("raw", [])]
    check("B3 raw newest-first by rowid", raw_rows == sorted(raw_rows, reverse=True) and len(raw_rows) >= 10, raw_rows[:5])
    b1 = min(raw_rows) if raw_rows else 0
    l1_to = [r.get("to_rowid") for r in w.get("l1", []) if r.get("to_rowid") is not None]
    check("B4 L1 window strictly older than raw (no overlap)", all(t < b1 for t in l1_to), (b1, l1_to[:5]))
    b2 = min([r.get("from_rowid") for r in w.get("l1", []) if r.get("from_rowid") is not None] or [b1])
    l2_to = [r.get("to_rowid") for r in w.get("l2", []) if r.get("to_rowid") is not None]
    check("B5 L2 window strictly older than L1", all(t < b2 for t in l2_to), (b2, l2_to[:5]))
    used = a["budget"]["used_tokens"]; lim = a["budget"]["limits"]
    check("B6 window budgets respected (+10%)", w["tokens"]["raw"] <= lim["raw"] * 1.1 and w["tokens"]["l1"] <= lim["l1"] * 1.1 and w["tokens"]["l2"] <= lim["l2"] * 1.1 and used.get("memory_map", 0) <= lim["map"] * 1.15, w["tokens"])
    check("B7 first pack total <= 11k tokens", a["budget"]["total_tokens"] <= 11000, a["budget"]["total_tokens"])
    c, a2, ms, n = mem(view="agent", session_id=sid, start=True, budget_raw=500, budget_l1=300, budget_l2=200)
    check("B8 budget params shrink windows", a2["windows"]["tokens"]["raw"] <= 560, a2["windows"]["tokens"])
    c, p, ms, n = api("GET", "/api/v7/memory/profile")
    check("B9 profile endpoint", c == 200 and "who" in p, c)
    c, l2, ms, n = api("GET", "/api/v7/memory/l2/blocks")
    check("B10 legacy L2 record preserved as a block", c == 200 and any(b.get("source") == "legacy_summary_l2" for b in l2.get("blocks", [])), [b.get("source") for b in l2.get("blocks", [])][:6])
def stepC():
    sid = "t_c_" + str(time.time())
    mem(view="agent", session_id=sid, start=True)
    c, a, ms, n = mem(query_text="Т-частицы", view="agent", session_id=sid)
    L = a.get("lens", {})
    check("C1 multi-hit query -> several clusters", len(L.get("clusters", [])) >= 3 and L.get("total_hits", 0) > 50, (len(L.get("clusters", [])), L.get("total_hits"), L.get("clusters_total")))
    c1 = (L.get("clusters") or [{}])[0]
    check("C2 cluster 1 full with context (before/after or l1)", bool(c1.get("center", {}).get("text")) and (c1.get("before") or c1.get("after") or c1.get("l1")))
    check("C3 hits[0] == lens center", a.get("hits") and a["hits"][0]["event_id"] == c1.get("center", {}).get("event_id"))
    c, b, ms, n = mem(query_text="AURORA codeword", view="agent", session_id=sid)
    check("C4 lens sees non-grokexp events (remember_)", any("remember_" in x.get("center", {}).get("event_id", "") for x in b.get("lens", {}).get("clusters", [])))
    c, e, ms, n = mem(query_text="What did we decide about SKV architecture and memory layers?", view="agent", session_id=sid)
    words = e.get("lens", {}).get("terms", [])
    check("C5 stop words removed (what/did/about)", not ({"what", "did", "about", "we"} & set(words)), words)
    fid = c1.get("center", {}).get("event_id")
    c, f, ms, n = api("POST", "/api/v7/memory/lens", {"focus_event_id": fid, "radius": 3})
    check("C6 focus_event_id expands one cluster", c == 200 and f.get("clusters") and f["clusters"][0]["center"]["event_id"] == fid and len(f["clusters"][0].get("before", [])) >= 1, c)
    check("C7 follow-up payload <= 3k tokens", a["budget"]["total_tokens"] <= 3000, a["budget"]["total_tokens"])
    if L.get("more_cursor") is not None:
        c, m, ms, n = mem(query_text="Т-частицы", view="agent", session_id=sid, lens_offset=L["more_cursor"])
        ids1 = {x["center"]["event_id"] for x in L["clusters"]}; ids2 = {x["center"]["event_id"] for x in m.get("lens", {}).get("clusters", [])}
        check("C8 lens_offset pages to new clusters", ids2 and not (ids1 & ids2))
def measure():
    out = {}
    sid = "t_m_" + str(time.time())
    cases = [("legacy_followup", dict(query_text="SKV architecture memory layers", probe=True, view="legacy")),
             ("agent_first", dict(view="agent", session_id=sid, start=True, query_text="SKV architecture memory layers")),
             ("agent_followup", dict(view="agent", session_id=sid, query_text="forget archive purge")),
             ("agent_multihit", dict(view="agent", session_id=sid, query_text="Т-частицы"))]
    for name, body in cases:
        lat = []
        for i in range(7 if "first" not in name else 3):
            if name == "agent_first": body = dict(body, session_id=sid + str(i))
            c, d, ms, n = mem(**body); lat.append(ms)
        sec = {k: (len(json.dumps(v, ensure_ascii=False))) for k, v in d.items()} if isinstance(d, dict) else {}
        out[name] = {"chars": n, "tokens": tok(d), "p50_ms": round(statistics.median(lat)), "max_ms": round(max(lat)), "sections_chars": sec,
                     "window_tokens": (d.get("windows") or {}).get("tokens") if isinstance(d, dict) else None}
        print(name, out[name]["chars"], out[name]["tokens"], out[name]["p50_ms"], out[name]["window_tokens"])
    json.dump(out, open("/tmp/memv2_measure.json", "w"), ensure_ascii=False, indent=1)
if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "A"
    if which in ("A", "all", "B", "C"): stepA()
    if which in ("B", "all", "C"): stepB()
    if which in ("C", "all"): stepC()
    if "measure" in sys.argv: measure()
    print(json.dumps({"passed": sum(r["ok"] for r in RES), "total": len(RES)}))
    json.dump(RES, open(f"/tmp/memv2_tests_{which}.json", "w"), ensure_ascii=False, indent=1)
