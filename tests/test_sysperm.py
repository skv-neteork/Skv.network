import os, sys, asyncio, tempfile, types
sys.path.insert(0, "/app")
os.environ["SKV_SYSPERM_DB"] = tempfile.mktemp(suffix=".db"); os.environ["SKV_SHELL_OWNERS"] = "owner@x.io"
from app.routers import sysperm_router as s
from fastapi import HTTPException
ok = n = 0
def t(name, c):
    global ok, n; n += 1; ok += bool(c); print(("PASS " if c else "FAIL ") + name)
R = lambda u: types.SimpleNamespace(query_params={"user_id": u})
run = asyncio.run
def err(coro):
    try: run(coro); return None
    except HTTPException as e: return e.status_code
t("non-owner cannot grant", err(s.grant(s.GrantReq(scope="/etc/nginx", ttl_minutes=10), R("eve@x.io"))) == 403)
t("scope / refused", err(s.grant(s.GrantReq(scope="/", ttl_minutes=10), R("owner@x.io"))) == 422)
t("ttl capped", err(s.grant(s.GrantReq(scope="/etc/nginx", ttl_minutes=999), R("owner@x.io"))) == 422)
t("no grant -> refused", run(s.check(s.CheckReq(path="/etc/nginx/nginx.conf", action="write"), R("owner@x.io")))["allowed"] is False)
g = run(s.grant(s.GrantReq(scope="/etc/nginx", ttl_minutes=10, actions=["read", "write"], agent="bot1"), R("owner@x.io")))
t("grant ok", g["grant_id"].startswith("sg_"))
t("in scope + agent -> allowed", run(s.check(s.CheckReq(path="/etc/nginx/sites/a.conf", action="write", agent="bot1"), R("owner@x.io")))["allowed"])
t("other agent refused", not run(s.check(s.CheckReq(path="/etc/nginx/a", action="write", agent="bot2"), R("owner@x.io")))["allowed"])
t("traversal refused", not run(s.check(s.CheckReq(path="/etc/nginx/../shadow", action="read", agent="bot1"), R("owner@x.io")))["allowed"])
t("prefix sibling refused", not run(s.check(s.CheckReq(path="/etc/nginx2/x", action="read", agent="bot1"), R("owner@x.io")))["allowed"])
t("action outside grant refused", not run(s.check(s.CheckReq(path="/etc/nginx/a", action="delete", agent="bot1"), R("owner@x.io")))["allowed"])
t("other user never allowed", not run(s.check(s.CheckReq(path="/etc/nginx/a", action="read", agent="bot1"), R("eve@x.io")))["allowed"])
t("log within grant", run(s.log(s.LogReq(grant_id=g["grant_id"], path="/etc/nginx/a", action="write", agent="bot1"), R("owner@x.io")))["within_grant"])
run(s.revoke(s.RevokeReq(grant_id=g["grant_id"]), R("owner@x.io")))
t("revoked -> refused", not run(s.check(s.CheckReq(path="/etc/nginx/a", action="read", agent="bot1"), R("owner@x.io")))["allowed"])
t("log after revoke flagged", not run(s.log(s.LogReq(grant_id=g["grant_id"], path="/etc/nginx/a", action="write"), R("owner@x.io")))["within_grant"])
c = s._conn(); c.execute("INSERT INTO sys_grants VALUES ('sg_old','owner@x.io','/tmp','[\"read\"]','','', '2026-01-01','2026-01-01T00:00:00+00:00',NULL)"); c.commit(); c.close()
t("expired -> refused", not run(s.check(s.CheckReq(path="/tmp/a", action="read"), R("owner@x.io")))["allowed"])
a = run(s.audit(R("owner@x.io")))["items"]
t("audit logs every check, refusal, action, revoke", {"grant", "check", "action", "revoke", "action_without_grant"} <= {x["event"] for x in a} and any(x["result"] == "refused" for x in a))
t("audit owner only", err(s.audit(R("eve@x.io"))) == 403)
print(f"{ok}/{n} passed")
