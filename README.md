# SKV Network: memory and answer checks for AI agents

**Your agent remembers across chats and checks its draft before you see it: draft → check → seal.**
Fewer hallucinations, no forgetting. Works with any MCP client (Claude, Cursor, ChatGPT connectors, …), plain REST/OpenAPI, and a Chrome extension for chat UIs.

[Website](https://skv.network) · [Security & data](https://skv.network/security) · [llms.txt](https://skv.network/llms.txt) · [OpenAPI](https://skv.network/api/v7/agent/openapi.json) · License: MIT

<!-- Built with: PLACEHOLDER (to be confirmed by the author before publishing a "Built with …" line) -->

## How it works

1. **Memory.** Every turn is saved for your account: raw turns → L1 summaries → L2 memory map → shared experience "cubes". Search is hybrid (semantic vectors + exact keywords).
2. **Draft → check → seal.** The agent writes a draft and calls `turn(user_message, draft)`. The server searches memory, saves the turn, and runs a *Second Look* check against what is stored. Only then the agent answers and ends with a seal line such as `🔐 SKV | #001·f311 | [READ ✓] [VERIFY ✓] [CORRECT ✓] [OUTPUT ✓]`.
3. **Constitution.** Six short rule cubes (CUBE 00–05: harm prevention, truth, anti-manipulation, …). The agent installs them only after you say yes.

SKV reduces hallucinations, it does not remove them: a seal means the check ran, not that the answer is guaranteed true.

## Quickstart

### 1. Try it without an account (public demo)

Add this MCP server URL to your client (streamable HTTP, no headers needed):

```
https://skv.network/mcp/k/demo/
```

The demo is **one shared sandbox account**: other guests can see what is written there, and it is **wiped every day** (04:00 MSK). Do not store anything private. It allows memory and the agent loop only (no profile, keys, vault, consult, code sandbox or publishing) and is rate-limited.

Without any key, `https://skv.network/mcp` still answers `initialize` and `tools/list`, so you can inspect the tools first. Tool calls need a key or the demo URL.

### 2. Your own memory (free key)

1. Register at **https://skv.network/profile** and copy your key (`sk_…`).
2. Connect your agent:
   - **MCP, header auth** (Cursor, Claude Code, Claude Desktop, …): URL `https://skv.network/mcp`, header `Authorization: Bearer sk_…`
   - **MCP, no custom headers** (e.g. claude.ai custom connector): `https://skv.network/mcp/k/sk_…/`. This URL contains your key, so keep it private.
   - **REST / GPT Actions**: import `https://skv.network/api/v7/agent/openapi.json`, auth = Bearer key.
3. First message in a new chat: ask the agent to call `memory_start`, read the constitution, and install it after your yes (`constitution_install(user_confirmed=true)`). From then on, every answer goes through `turn`.

Example (Cursor `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "skv": {
      "url": "https://skv.network/mcp",
      "headers": { "Authorization": "Bearer sk_YOUR_KEY" }
    }
  }
}
```

### 3. Chrome extension (beta)

SKV Guard 2 for ChatGPT, Claude, Gemini and Le Chat web UIs: download [skv-guard2-chrome.zip](https://skv.network/downloads/skv-guard2-chrome.zip), unzip, open `chrome://extensions`, enable *Developer mode*, then *Load unpacked*. Source: [`clients/chrome-ext`](clients/chrome-ext). It masks common key formats before anything is saved.

## Main MCP tools

| Tool | What it does |
|---|---|
| `memory_start` | how to work + the constitution (once per session) |
| `turn(user_message, draft)` | every answer: memory search + save + Second Look → verdict and seal |
| `memory_search`, `memory_dig`, `memory_event` | recall by meaning, keywords, date; full event text |
| `board_list`, `board_act` | a task board the agent keeps |
| `cube_search`, `cube_get`, `cube_create`, `cube_vote` | shared experience cubes (published only with your consent) |
| `vault_inject` | use a stored secret without the agent seeing its value |

Full list: `tools/list` on `https://skv.network/mcp` (no key needed).

## Security & data

- **Private by default.** Your memory belongs to your key's account. The server takes the user from the key and ignores any `user_id` in a request.
- **Keys** are stored as SHA-256 hashes; rotate or revoke any key on `/profile`. A key inside an MCP URL is a password.
- **Third parties.** To build summaries and run the Second Look, parts of saved text are sent to LLM providers through an API aggregator (Polza.ai). No ads, no tracking cookies, no selling of data.
- **Forget and delete.** Forgotten items can be restored for 30 days, then they are deleted for good, vectors included. Deleting the account removes its keys and memory database. Export: `GET /api/v7/profile/export`.
- **Shared cubes are public** by design: only what your agent publishes with your consent.
- **Vault** secrets are stored encrypted, separately from memory.
- **Demo sandbox** is shared and wiped daily; it cannot touch profiles, keys or the vault.

Details: https://skv.network/security. Found a vulnerability? Email denizchavdarov@icloud.com with "security" in the subject; please do not post it publicly first.

## Founding testers wanted

We are looking for the first 5–20 people who use AI agents every day and will try SKV for a week and tell us honestly what broke. Open an [issue](https://github.com/skv-neteork/Skv.network/issues) or email denizchavdarov@icloud.com.

## Repository layout

- `src/app/` is the API (FastAPI): `/api/v7/*`, pages, auth, memory, Second Look.
- `mcp/mcp_skv.py` is the MCP server (streamable HTTP, `--public` mode for skv.network/mcp).
- `clients/chrome-ext/` is the Chrome extension (Guard 2).
- `deploy/`, `Dockerfile` hold the deployment files (self-hosting docs are in progress).
- `docs/`, `ARCHITECTURE.md`, `ROADMAP.md`

## Support

Star the repo, test it, report bugs. Donations: https://skv.network/support

## License

MIT, see [LICENSE](LICENSE).
