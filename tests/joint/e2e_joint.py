"""E2E for joint projects, run inside skv_api: python3 - < e2e_joint.py. Uses test accounts only; prints no keys."""
import json, httpx, time
K = json.load(open("/data/skv/.jp_test_keys.json"))
B = "http://127.0.0.1:8000/api/v7"
R = []
def call(key, m, p, body=None):
    r = httpx.request(m, B + p, headers={"Authorization": "Bearer " + key}, json=body, timeout=120)
    try: d = r.json()
    except Exception: d = {"raw": r.text[:300]}
    return r.status_code, d
def check(name, cond, extra=""):
    R.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra)[:300]) if not cond else ""))
tag = str(int(time.time()))[-5:]
A, Bk, C = K["a"], K["b"], K["c"]
s, d = call(A["main"], "POST", "/joint/projects", {"title": "ORCHID test " + tag})
check("create", s == 200 and d.get("project_key", "").startswith("sk_"), d); pid = d.get("project_id"); pkA = d.get("project_key")
call(A["main"], "POST", "/remember", {"query": "private note", "response": "A_PRIVATE_ZEBRA%s secret plan of A" % tag})
s, d = call(pkA, "POST", "/remember", {"query": "project fact", "response": "ORCHID%s deployment uses port 9443; token = sk_abcdef1234567890abcdef12" % tag})
check("pkA remember", s == 200, d)
s, d = call(Bk["main"], "POST", "/joint/projects/%s/invite" % pid, {"email": "x@y.z"}); check("non-owner cannot invite", s == 403, d)
s, d = call(A["main"], "POST", "/joint/projects/%s/invite" % pid, {"email": Bk["user"]}); check("invite B", s == 200, d)
s, d = call(C["main"], "POST", "/joint/projects/%s/accept" % pid); check("C cannot accept B's invite", s == 404, d)
s, d = call(Bk["main"], "GET", "/joint/invites"); check("B sees invite", any(i["project_id"] == pid for i in d.get("invites", [])), d)
s, d = call(Bk["main"], "POST", "/joint/projects/%s/accept" % pid); check("B accepts", s == 200 and d.get("project_key"), d); pkB = d.get("project_key")
s, d = call(Bk["main"], "POST", "/joint/projects/%s/accept" % pid); check("accept twice refused", s == 404, d)
call(Bk["main"], "POST", "/remember", {"query": "private", "response": "B_PRIVATE_LYNX%s only mine" % tag})
call(Bk["side"], "POST", "/remember", {"query": "side", "response": "B_SIDE_OTTER%s other agent of B" % tag})
s, d = call(pkB, "POST", "/remember", {"query": "plan", "response": "ORCHID%s test plan: B handles QA on Friday" % tag}); check("pkB remember", s == 200, d)
s, d = call(pkB, "POST", "/agent/turn", {"user_message": "ORCHID%s status?" % tag, "draft": "ORCHID%s: QA is on Friday, deploy port 9443." % tag})
check("pkB turn saved", s == 200 and d.get("saved"), {k: d.get(k) for k in ("verdict", "saved", "event_id")})
s, d = call(pkB, "POST", "/joint/search", {"query": "ORCHID%s port QA" % tag})
txt = json.dumps(d, ensure_ascii=False)
check("pkB search sees A project fact", s == 200 and "9443" in txt and any(not h["own"] for h in d.get("hits", [])), d)
check("pkB search sees own turn", sum(1 for h in d.get("hits", []) if h["own"]) >= 2, [h["text"][:60] for h in d.get("hits", [])])
check("no private lines in project search", all(x not in txt for x in ("ZEBRA", "LYNX", "OTTER")), txt[:300])
check("secret masked in project search", "sk_abcdef1234567890" not in txt and "vault:" not in txt and "[SECRET]" in txt, txt[:400])
check("citations are pj", all(h["pj"].startswith("[pj:") for h in d.get("hits", [])))
s, d = call(pkB, "POST", "/joint/search", {"query": "ZEBRA%s" % tag}); check("private word -> 0 hits", s == 200 and not d.get("hits"), d)
s, d = call(Bk["main"], "POST", "/joint/search", {"query": "ORCHID"}); check("B main key cannot project-search", s == 403, d)
s, d = call(Bk["side"], "POST", "/joint/search", {"query": "ORCHID"}); check("B side key cannot project-search", s == 403, d)
s, d = call(C["main"], "POST", "/joint/search", {"query": "ORCHID"}); check("outsider cannot search", s == 403, d)
s, d = call(C["main"], "GET", "/joint/projects/%s" % pid); check("outsider cannot read info", s == 404, d)
s, d = call(pkB, "POST", "/search", {"query": "ZEBRA%s" % tag, "lines": "all"}); check("pkB normal search lines=all: no A data", "ZEBRA" not in json.dumps(d), str(d)[:200])
s, d = call(pkA, "POST", "/search", {"query": "LYNX%s OTTER%s" % (tag, tag), "lines": "all"}); check("pkA normal search: no B data", "LYNX" not in json.dumps(d) and "OTTER" not in json.dumps(d), str(d)[:200])
s, d = call(Bk["main"], "GET", "/joint/projects/%s" % pid)
check("B (member, any key) sees audit with own read", s == 200 and any(a["action"] == "search" and A["user"] in a["detail"].get("read_from", []) for a in d.get("audit", [])), d)
check("audit chain ok", d.get("audit_chain_ok") is True, d.get("audit_chain_ok"))
s, d = call(Bk["main"], "POST", "/joint/projects/%s/revoke" % pid, {"email": A["user"]}); check("member cannot revoke", s == 403, d)
s, d = call(A["main"], "POST", "/joint/projects/%s/revoke" % pid, {"email": Bk["user"]}); check("owner revokes B", s == 200, d)
s, d = call(pkB, "POST", "/joint/search", {"query": "ORCHID%s" % tag}); check("revoked key: search refused at once", s == 403, d)
s, d = call(pkA, "POST", "/joint/search", {"query": "ORCHID%s QA Friday" % tag}); txt = json.dumps(d.get("hits"))
check("after revoke B contributions hidden", s == 200 and "Friday" not in txt and "9443" in txt, txt[:300])
s, d = call(pkB, "POST", "/remember", {"query": "after", "response": "ORCHID%s after revoke" % tag})
s, d = call(A["main"], "GET", "/joint/projects/%s" % pid)
nB = [m["shared_events"] for m in d.get("members", []) if m["user"] == Bk["user"]]
check("writes after revoke not recorded", nB and nB[0] >= 1 and "key_name" in d["members"][0], d.get("members"))
s, d = call(A["main"], "POST", "/joint/projects/%s/close" % pid); check("owner closes", s == 200, d)
s, d = call(pkA, "POST", "/joint/search", {"query": "ORCHID"}); check("closed: search refused", s == 403, d)
print("RESULT %d/%d passed" % (sum(1 for _, ok in R if ok), len(R)))
