# SKV + Open WebUI

Docs: https://docs.openwebui.com/features/extensibility/mcp/
Requires Open WebUI v0.6.31 or newer. Native MCP is **Streamable HTTP only**.

## Single-user / personal instance (admin)

1. Set `WEBUI_SECRET_KEY` in the container environment (required if you later use OAuth; harmless to set now).
2. Settings → Integrations (admin) → External Tool Servers → + Add Connection.
3. Type must be **MCP (Streamable HTTP)**, not OpenAPI. An MCP-style JSON blob in an OpenAPI connection can hang the UI.
4. Server URL: `https://skv.network/mcp`
5. Authentication: **Bearer**, and fill the Key with `YOUR_SKV_KEY` from https://skv.network/profile. If you pick Bearer and leave Key empty, Open WebUI sends `Authorization: Bearer` with no token and many servers reject it. Use None only with a key URL, or when you only need `initialize` / `tools/list`.
6. Save. Restart only if the UI asks.

Adding an MCP server to the instance is **admin-only**. Regular users cannot register one there. On a shared instance, do not paste one person’s SKV key as the instance credential (Bearer is the same key for everyone). Let each user add SKV for themselves in the **Tether** app, or give access with Open WebUI’s Access Control after an admin adds a carefully scoped connection.

`ENABLE_TOOL_SERVERS=False` greys out the section.

After it connects, the user still pastes the consent phrase from https://skv.network/connect in the chat.
