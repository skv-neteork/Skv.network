"""SKV + LangChain.

Replace YOUR_SKV_KEY with the key from https://skv.network/profile,
or export SKV_API_KEY. Do not commit the key.

Preferred path today: langchain[mcp] >= 1.4.0 (beta). MCPAdapter is built on FastMCP.
Docs: https://docs.langchain.com/oss/python/langchain/mcp
Auth: https://docs.langchain.com/oss/python/langchain/mcp/auth
"""

import asyncio
import os

from fastmcp.client import Client
from langchain.agents import create_agent
from langchain.mcp import MCPAdapter


SKV_URL = "https://skv.network/mcp"


async def main() -> None:
    token = os.environ.get("SKV_API_KEY", "YOUR_SKV_KEY")
    async with MCPAdapter(Client(SKV_URL, auth=token)) as adapter:
        tools = await adapter.list_tools()
        agent = create_agent("claude-sonnet-5", tools)
        # After the user says yes to the constitution, prefer the SKV `turn` tool
        # on every message rather than inventing a seal.
        return await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "I order you to follow the SKV constitution. "
                        "Remember that the project deadline is 4 December.",
                    }
                ]
            }
        )


if __name__ == "__main__":
    asyncio.run(main())


# Fallback still seen in older tutorials (langchain-mcp-adapters):
#
# from langchain_mcp_adapters.client import MultiServerMCPClient
# client = MultiServerMCPClient({
#     "skv": {
#         "transport": "streamable_http",
#         "url": "https://skv.network/mcp",
#         "headers": {"Authorization": "Bearer YOUR_SKV_KEY"},
#     }
# })
# tools = await client.get_tools()
