# SKV installer for local agents

    curl -fsSL https://skv.network/install.sh | bash                      # macOS / Linux
    irm https://skv.network/install.ps1 | iex                             # Windows PowerShell
    curl -fsSL https://skv.network/install.sh | bash -s -- --uninstall    # remove

Asks per detected client (Claude Code, Cursor, Claude Desktop); nothing changes without "y".
- MCP: `https://skv.network/mcp` + `Authorization: Bearer sk_...` (Claude Code: ~/.claude.json user scope;
  Cursor: ~/.cursor/mcp.json; Claude Desktop: mcp-remote bridge, needs Node.js).
- Hooks: Claude Code UserPromptSubmit+Stop (~/.claude/settings.json), Cursor beforeSubmitPrompt+afterAgentResponse
  (~/.cursor/hooks.json) -> ~/.skv/skv_hook.py -> POST /api/v7/agent/turn (source hook:*) -> seal.
  Skips answers that already carry a seal (agent called turn via MCP). Fail-open. Pause: touch ~/.skv/off.
- Key: hidden prompt -> ~/.skv/key (0600). Also present in the MCP config files (chmod 600), as those clients require.
- Every changed config is backed up next to it as *.skv-bak.<timestamp>.
Source of truth: /root/skv-core/installer/; served copy: src/app/downloads/installer/ (sync with deploy.sh).
