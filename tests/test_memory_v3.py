"""SKV memory v3 tests (batch ingest, recall facts, relative dates, latency). Run on the server:
SKV_KEY=<test account key> python3 tests/test_memory_v3.py   (uses localhost:8000; writes only to that account, then forgets it)"""
import json, os, sys, time, urllib.request, statistics
BASE = os.environ.get("SKV_LOCAL", "http://127.0.0.1:8000"); KEY = os.environ.get("SKV_KEY") or sys.exit("set SKV_KEY")
RES = []
def api(path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, method=method or ("POST" if body is not None else "GET"),
                               headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=120) as resp: raw, code = resp.read().decode(), resp.status
    except urllib.error.HTTPError as e: raw, code = e.read().decode(), e.code
    try: d = json.loads(raw)
    except Exception: d = raw
    return code, d, (time.time() - t) * 1000
def check(n, c, info=""):
    RES.append((n, bool(c))); print(("PASS " if c else "FAIL ") + n + ("  " + str(info) if info else ""))
TAG = "V3T" + str(int(time.time()))[-6:]
items = [{"query": f"Alice{TAG}: I adopted a cat named Miso yesterday.", "response": "Bob: Lovely!", "ts": "2023-03-06T10:00:00"},
         {"query": f"Alice{TAG}: Last Saturday I ran a half marathon.", "response": "Bob: Wow", "ts": "2023-04-10T10:00:00"},
         {"query": f"Alice{TAG}: Two weeks ago I started pottery classes.", "response": "Bob: Cool", "ts": "2023-05-15T10:00:00"},
         {"query": f"Alice{TAG}: I also play the violin on weekends.", "response": "Bob: Nice", "ts": "2023-06-01T10:00:00"}]
c, d, ms = api("/api/v7/remember/batch", {"items": items, "source": "v3test"})
check("B1 batch saves all items", c == 200 and d.get("saved") == 4, d)
check("B2 batch embeds now", isinstance(d, dict) and d.get("vectors") == "now", d.get("vectors") if isinstance(d, dict) else d)
c, d2, _ = api("/api/v7/remember/batch", {"items": [{"query": "x", "ts": "not-a-date"}]})
check("B3 bad ts -> 422", c == 422, c)
c, d3, _ = api("/api/v7/remember/batch", {"items": [{"query": "x"}] * 501})
check("B4 >500 items -> 413", c == 413, c)
big = [{"query": f"filler{TAG} turn {i} about gardening and weather", "response": "ok", "ts": "2023-07-01T10:00:00"} for i in range(200)]
c, d4, ms4 = api("/api/v7/remember/batch", {"items": big, "source": "v3test"})
check("B5 200 items in one call < 20 s", c == 200 and ms4 < 20000, round(ms4))
c, m, _ = api("/api/v7/memory", {"query_text": f"What hobbies and activities does Alice{TAG} have?", "session_id": "v3t_" + TAG, "probe": True})
m2 = api("/api/v7/memory", {"query_text": f"What hobbies and activities does Alice{TAG} have?", "session_id": "v3t_" + TAG, "probe": True})[1]
blob = json.dumps([m2.get("hits"), m2.get("facts")])
check("R1 recall finds 3+ of 4 activities across episodes", sum(w in blob for w in ("Miso", "marathon", "pottery", "violin")) >= 3, [w for w in ("Miso", "marathon", "pottery", "violin") if w in blob])
check("R2 hits carry event dates (ts)", any((h.get("date") or "").startswith("2023-") for h in m2.get("hits") or []), [h.get("date") for h in m2.get("hits") or []][:4])
check("R3 relative dates resolved", "yesterday=2023-03-05" in blob or "last saturday=2023-04-08" in blob or "two weeks ago=~2023-05-01" in blob)
m3 = api("/api/v7/memory", {"query_text": f"What hobbies does Alice{TAG} have?", "session_id": "v3t_" + TAG, "probe": True, "recall": "basic"})[1]
check("R4 recall=basic has no facts", "facts" not in m3, list(m3)[:12])
mt = api("/api/v7/memory", {"query_text": f"What hobbies does Alice{TAG} have?", "session_id": "v3t_" + TAG, "probe": True, "format": "text"})[1]
check("R5 text format renders hits with dates", "[2023-" in (mt.get("prompt_text") or ""))
lat = []
for i in range(20):
    lat.append(api("/api/v7/memory", {"query_text": f"When did Alice{TAG} start pottery?", "session_id": "v3t_" + TAG, "probe": True})[2])
p50 = statistics.median(lat)
check("L1 /memory follow-up p50 < 300 ms (localhost)", p50 < 300, f"p50={p50:.0f} p90={sorted(lat)[17]:.0f}")
one = [api("/api/v7/remember", {"query": f"single{TAG} {i}", "response": "ok", "source": "v3test"})[2] for i in range(5)]
check("L2 single /remember p50 < 300 ms", statistics.median(one) < 300, f"{statistics.median(one):.0f} ms")
# cleanup through the forget flow
n = 0
for _ in range(5):
    c, p, _ = api("/api/v7/memory/forget/preview", {"mode": "shelf", "source": "v3test", "limit": 200})
    if c != 200 or not p.get("count"): break
    n += api("/api/v7/memory/forget/confirm", {"token": p["confirm"]["token"], "user_confirmed": True})[1].get("count", 0)
c, p, _ = api("/api/v7/memory/forget/preview", {"query": "single" + TAG, "mode": "text", "limit": 50})
if c == 200 and p.get("count"): n += api("/api/v7/memory/forget/confirm", {"token": p["confirm"]["token"], "user_confirmed": True})[1].get("count", 0)
print("cleanup forgotten", n)
ok = sum(1 for _, x in RES if x); print(f"{ok}/{len(RES)} passed"); sys.exit(0 if ok == len(RES) else 1)
