> **CURRENT LOOP:** public `tools/list` is 39 names (`src/app/mcp_public_tools.py`). Start order, once per new key: `constitution_install(user_confirmed=true)` only after a yes, then `identify(name)`, then `step_zero(page=1..N)` until `done=true`, then `turn(user_message, draft)` on every user message. The seal is issued only by `turn`. The compact constitution is v5; the server sends its manifest every 10th turn (also on the first turn of a session, a new version, and `context_reset`). Acknowledge with `const_ack=true`. Full order: **PROTOCOL.md**. `memory_bootstrap`, `memory_consult`, `second_look`, `memory_dig` and `memory_event` are not in the public 39.

# SKV MCP — full agent protocol

Tools → real V7 HTTP. Protocol = CUBE 05 + skills + Guard duties (see **PROTOCOL.md**).  
MCP = primary one-button (39 public tools). **Guards**: Guard 1 = short missed-step reminders; Guard 2 = local checklist and draft insurance. The Guard 2 download still follows the older HTTP order (bootstrap, consult, second look). The required MCP order is below.

## One button (any user)

1. Open https://skv.network/profile → copy your key `sk_...`
2. In Cursor / Claude MCP settings paste (**Streamable HTTP** — preferred):

```json
{
  "mcpServers": {
    "skv-memory": {
      "url": "https://skv.network/mcp",
      "headers": {
        "Authorization": "Bearer sk_YOUR_KEY_FROM_PROFILE"
      }
    }
  }
}
```

That is it. Your key = your memory chain. No SSH.

**SSE** (optional, clients that still want SSE):

```json
{
  "mcpServers": {
    "skv-memory": {
      "url": "https://skv.network/mcp/sse",
      "headers": {
        "Authorization": "Bearer sk_YOUR_KEY_FROM_PROFILE"
      }
    }
  }
}
```

| URL | Transport |
|-----|-----------|
| `https://skv.network/mcp` | Streamable HTTP (Cursor / Claude remote) |
| `https://skv.network/mcp/sse` | SSE |
| `https://skv.network/mcp/health` | Liveness (no auth) |

If the public URL is temporarily down, use stdio on the server (or SSH tunnel):

```json
{
  "mcpServers": {
    "skv-memory": {
      "command": "/root/skv-core/ops/mcp_stdio.sh",
      "env": { "SKV_API_KEY": "sk_YOUR_KEY_FROM_PROFILE" }
    }
  }
}
```

Tunnel: `ssh -L 8765:127.0.0.1:8765 root@SERVER` then `http://127.0.0.1:8765/` (streamable) or `/sse` + same Bearer header.

## Agent must follow PROTOCOL.md

Order: **constitution_install (only after yes) → identify → step_zero until done → turn on every message.** Details, the v5 manifest, and the court are in **PROTOCOL.md**.

## Tools (V7 mapping)

The public MCP list is the 39 names in the banner. `memory_import_text` is one of them. A row here that is not in that list is an older HTTP route. It is not the required loop.

| Tool | Endpoint |
|------|----------|
| memory_bootstrap | POST `/api/v7/session/bootstrap` |
| memory_start | GET `/api/v7/memory/start` |
| memory_consult | POST `/api/v7/memory` |
| memory_search | POST `/api/v7/search` |
| memory_dig | POST `/api/v7/memory/dig` |
| memory_lens | POST `/api/v7/memory/lens` |
| memory_event | GET `/api/v7/event/{id}` |
| turn | POST `/api/v7/remember` (saves the turn; `recap=` saves answers sent without turn) |
| memory_critical | POST `/api/v7/remember` (critical) |
| memory_recall_later / _status | `/api/v7/memory/recall_later` |
| second_look | POST `/api/v7/agent/second-look` |
| constitution_get | GET `/api/v7/constitution` |
| skills_list / skills_get | GET `/api/v7/skills` |
| cube_get | GET `/api/v7/cube/{id}` |
| cube_search | GET `/api/cubes/search` |
| cube_create | POST `/api/v7/experience/create` |
| cube_vote | POST `/api/v7/experience/vote` |
| cube_link | POST `/api/v7/cube/link` |
| feedback_submit | POST `/api/v7/feedback` |
| board_list / board_act | `/api/v7/board` |
| memory_forget_preview/confirm/restore | `/api/v7/memory/forget/*` |
| memory_import_text | `/api/v7/import/text` |
| vectors_process | `/api/v7/vectors/process` |
| keys_list/create/rename/rotate/revoke | `/api/v7/profile/keys*` |

## Run locally on server

```bash
SKV_API_KEY=sk_... /root/skv-core/ops/mcp_stdio.sh
# public multi-tenant streamable-http + SSE (Bearer per client):
/root/skv-core/ops/mcp_public.sh   # 0.0.0.0:8765 --public
```

## Auth

Profile key `sk_...` or internal `skint_...`. Never commit keys. Rotate in /profile if leaked.

## Guards (non-MCP + insurance)

- **MCP** remains the primary connector (`/mcp` + Bearer `sk_`).
- **Guard 1** (server): short PROTOCOL missed-step reminders in `/api/v7/memory` and `/agent/prompt`. Does not block answers.
- **Guard 2** download: `GET /api/v7/agent/guardian.py` or Profile → Download Guard 2. Same step order; prefers `/session/bootstrap`; enforces never-empty duties + DRAFT→SECOND LOOK→FINAL.
- Shared short constants: `src/app/skv_protocol.py`.

