# SKV + Flowise (Custom MCP)

Docs: https://docs.flowiseai.com/tutorials/tools-and-mcp

Use **Custom MCP** with Streamable HTTP (not stdio / npx). Stdio is only for a local Flowise process.

## Steps

1. In Flowise, create a variable for the key (for example `skvApiKey`) and paste `YOUR_SKV_KEY` from https://skv.network/profile. Do not hard-code it in the canvas.
2. On an Agent node, add a Custom MCP tool. Config:

```json
{
  "url": "https://skv.network/mcp",
  "headers": {
    "Authorization": "Bearer {{$vars.skvApiKey}}"
  }
}
```

3. Refresh Available Actions and select at least `turn`, `memory_search`, and `step_zero` if you do not want all 39 tools.

If a hosted Flowise cannot store a per-user variable, use the key URL `https://skv.network/mcp/k/YOUR_SKV_KEY/` only on a private instance, never in a shared template.
