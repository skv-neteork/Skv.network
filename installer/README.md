# SKV installer for local agents

    curl -fsSL https://skv.network/install.sh | bash                      # macOS / Linux
    irm https://skv.network/install.ps1 | iex                             # Windows PowerShell
    curl -fsSL https://skv.network/install.sh | bash -s -- --uninstall    # remove

Asks per detected client (Claude Code, Cursor, Claude Desktop, Grok Build); nothing changes without "y".
- MCP: `https://skv.network/mcp` + `Authorization: Bearer sk_...` (Claude Code: ~/.claude.json user scope;
  Cursor: ~/.cursor/mcp.json; Claude Desktop: mcp-remote bridge, needs Node.js).
- Hooks: Claude Code UserPromptSubmit+Stop (~/.claude/settings.json), Cursor beforeSubmitPrompt+afterAgentResponse
  (~/.cursor/hooks.json) -> ~/.skv/skv_hook.py -> POST /api/v7/agent/turn (source hook:*) -> seal.
  Skips answers that already carry a seal (agent called turn via MCP). Fail-open. Pause: touch ~/.skv/off.
- Key: hidden prompt -> ~/.skv/key (0600). Also present in the MCP config files (chmod 600), as those clients require.
- Every changed config is backed up next to it as *.skv-bak.<timestamp>.
- Stop guard (ON by default when hooks are installed; flag file ~/.skv/guard; opt out: `--no-stop-guard` / `-NoStopGuard`, or rm ~/.skv/guard; `--stop-guard` / `-StopGuard` are accepted and equal the default; with `--no-hooks` there is no guard):
  the Stop hook blocks the end of a reply when no SKV turn was called for the current user message (no seal in the answer
  and no `turn` tool call after the last user message). Claude Code and Grok Build: `{"decision":"block","reason":...}`;
  Cursor: the `stop` event (registered with loop_limit 2) answers `{"followup_message":...}`. At most 2 blocks per user
  message, then the hook saves the turn itself (the old fallback). Fail-open on any error; paused by ~/.skv/off.
  Grok Build (`--clients grok-build`, hooks only -> ~/.grok/hooks/skv.json) also reads ~/.claude/settings.json and
  ~/.cursor/hooks.json; identical commands are deduplicated and camelCase fields are handled.
  Existing installs: re-run the installer (it refreshes ~/.skv/skv_hook.py and the Cursor `stop` entry).
Source of truth: /root/skv-core/installer/; served copy: src/app/downloads/installer/ (sync with deploy.sh).
