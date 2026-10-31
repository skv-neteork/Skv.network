# Session bootstrap (шаг 0) — draft

Endpoint: `POST /api/v7/session/bootstrap`

Feature flag: `/data/skv/memory_config.json` → `bootstrap.enabled` (default **false**).

## Purpose
On connect / first call with an API key, the agent may send its last 2–3 chat messages.
SKV compares them to the memory tail for that key's chain and returns a continuity package
(raw + L1 + L2 + critical + board + constitution + reminders + lag).

Does **not** replace `POST /api/v7/memory` (step=0) or `GET /api/v7/memory/start`.
Guard 1 and Guard 2 are unchanged.

## Request
```json
{
  "recent_messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "session_id": "optional"
}
```
Auth: `Authorization: Bearer sk_...` (user_id taken from the key).

## Response (enabled)
- `continuity.raw` / `.l1` / `.l2` / `.critical` / `.memory_map`
- `board`, `constitution`, `reminders`
- `lag`: `in_sync` | `chat_behind` | `unknown`
- `lag_detail.missing` when behind
- `chain`: `{id, name, kind, write: own_chain_only}`
- `guards.unchanged: true`

## Reused
- `build_memory_map` (legacy full map)
- `memory_v2.constitution_compact`, clip/est_tokens
- `board.render` / `board.items`
- `api_keys.chain_for_token`

## Stub / later
- Per-chain memory DB isolation (today: per-account DB; chain_id is a label)
- Cross-chain search with chain label (read-only)
- Auto-call from MCP on connect

## Enable
Set `bootstrap.enabled` to `true` in memory_config.json, then `ops/safe_restart.sh`
(or wait for process reload that re-reads config — bootstrap reads config each call via memory_v2.config cache on mtime).
