# SKV + n8n (MCP Client Tool)

Docs: https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp

Use the **MCP Client Tool** node attached to an **AI Agent**. This is n8n as an MCP client (consuming SKV), not the “MCP Server Trigger” node (exposing n8n as a server).

## Settings (node version 1.2 or newer)

- Endpoint: `https://skv.network/mcp`
- Server Transport: **HTTP Streamable** (`httpStreamable`)
- Authentication: Bearer. Put `YOUR_SKV_KEY` (from https://skv.network/profile) in an n8n credential, not in the workflow JSON.
- Tools to Include: start with Selected: `turn`, `memory_search`, `step_zero` (SKV currently lists 39 tools).

If the client has no header field, use `https://skv.network/mcp/k/YOUR_SKV_KEY/` and Authentication: None. Do not commit the key-in-URL form to a shared workflow.

## Docs caveat

The official docs page may still label the URL field “SSE Endpoint”. In n8n source, node v1.2+ uses `endpointUrl` plus `serverTransport: "httpStreamable"`, and that is the right choice for SKV. Prefer a current n8n build and set HTTP Streamable explicitly. Plain SSE is not the SKV transport.

If SKV later appears in n8n’s own MCP registry, you can connect it from that panel. Until then, this node is the path the docs describe for servers that are not in the registry.
