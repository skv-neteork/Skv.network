"""MCP smoke for joint tools (public MCP on 127.0.0.1:8765), test accounts only, prints no keys."""
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
K = json.load(open("/data/skv/.jp_test_keys.json"))
URL = "http://127.0.0.1:8765/"
async def call(key, name, args):
    async with streamablehttp_client(URL, headers={"Authorization": "Bearer " + key}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if name == "__list__":
                return [t.name for t in (await s.list_tools()).tools]
            res = await s.call_tool(name, args)
            return json.loads(res.content[0].text)
async def main():
    ok = []
    def chk(n, c, x=""):
        ok.append(c); print(("PASS " if c else "FAIL ") + n + ("" if c else " | " + str(x)[:300]))
    tools = await call(K["a"]["main"], "__list__", {})
    chk("tools listed", "joint_project" in tools and "joint_search" in tools and "consult" in tools, tools)
    d = await call(K["a"]["main"], "joint_project", {"action": "create", "title": "MCP smoke"}); pid = d.get("project_id"); pkA = d.get("project_key")
    chk("create via MCP", bool(pid and pkA), d)
    d = await call(K["a"]["main"], "joint_project", {"action": "invite", "project_id": pid, "email": K["b"]["user"]}); chk("invite", d.get("ok"), d)
    d = await call(K["b"]["main"], "joint_project", {"action": "invites"}); chk("invites", any(i["project_id"] == pid for i in d.get("invites", [])), d)
    d = await call(K["b"]["main"], "joint_project", {"action": "accept", "project_id": pid}); pkB = d.get("project_key"); chk("accept", bool(pkB), d)
    d = await call(pkA, "constitution_install", {"user_confirmed": True}); chk("test account A: constitution installed via project key", (d.get("install") or {}).get("installed"), str(d)[:300])
    d = await call(pkA, "turn", {"user_message": "What is the smoke project codename?", "draft": "MAGNOLIA-5 is the codename of the MCP smoke project."}); chk("turn by project key saved", d.get("saved"), str(d)[:600])
    d = await call(pkB, "joint_search", {"query": "MAGNOLIA-5 codename"}); chk("joint_search sees A note", "MAGNOLIA" in json.dumps(d.get("hits")), d)
    d = await call(K["b"]["main"], "joint_search", {"query": "MAGNOLIA"}); chk("main key refused", d.get("ok") is False, d)
    d = await call(K["a"]["main"], "joint_project", {"action": "info", "project_id": pid}); chk("info + audit", d.get("audit_chain_ok") and len(d.get("audit", [])) >= 4, d)
    d = await call(K["a"]["main"], "consult", {"task": "test", "consent": False}); chk("consult needs consent", d.get("status") == "need_consent", d)
    d = await call(K["a"]["main"], "joint_project", {"action": "close", "project_id": pid}); chk("close", d.get("ok"), d)
    print("MCP RESULT %d/%d" % (sum(ok), len(ok)), "memory_remember tool:", "memory_remember" in tools)
asyncio.run(main())


