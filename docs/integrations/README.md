# Use SKV from agent frameworks

Checked against official framework docs on 21 November 2026.

SKV is a hosted MCP server. These tools already speak remote Streamable HTTP, so you do not need a local install or an npx process.

- Endpoint: `https://skv.network/mcp`
- Auth: optional. `initialize` and `tools/list` work without a key. Private memory tool calls need a free key from https://skv.network/profile, sent as `Authorization: Bearer YOUR_SKV_KEY`, or use `https://skv.network/mcp/k/YOUR_SKV_KEY/` if the client has no header field.
- After the connection works, paste the consent phrase from https://skv.network/connect in the chat. The agent may install the constitution only after you say yes, then call `identify`, read `step_zero` until it is done, and call `turn` on every message.
- Do not commit API keys. Replace `YOUR_SKV_KEY` with your key, or use the host’s secret store.
- SKV currently exposes 39 tools. If the host has a tool cap, keep at least `turn`, `memory_search`, and `step_zero`.
- Public demo (shared, wiped daily, nothing private): `https://skv.network/mcp/k/demo/`

Copy-paste files in this folder:

- LangChain — [langchain.py](langchain.py)
- CrewAI — [crewai.py](crewai.py)
- n8n — [n8n.md](n8n.md)
- Flowise — [flowise.md](flowise.md)
- LibreChat — [librechat.yaml](librechat.yaml)
- Open WebUI — [openwebui.md](openwebui.md)

The same snippets are on https://skv.network/integrations.
