# SKV server: how it is built (plain words)

SKV is one web service (the "API") that AI agents call over the internet. It runs in a Docker container `skv_api`
on the server. The code lives in `/root/skv-core/src/app` and is mounted into the container, so a code change
takes effect after a safe restart (`/root/skv-core/ops/safe_restart.sh`, which waits until no import or save is running).

## What it stores
- **Personal memory**: one small database file per user in `/data/skv/metadata_store/<user>.db`.
  Every saved turn (question + answer) is a row. On top of the raw turns there are short summaries:
  L1 (a few sentences per stretch of conversation), L2 (a map of topics) and "Critical" lines that are never shortened.
- **Shared data**: `/data/skv/metadata_store/shared_master.db` holds users and API keys (keys are stored only as hashes),
  experience cubes, votes, the court queue, help requests, projects, the system-file permission log.
- **Search indexes**: vector indexes for meaning-based search (`/data/skv/hnsw_mml12`) plus word search inside each db.
- **Vault**: secrets are encrypted separately; memory keeps only a `[vault:name]` reference.

## Main parts of the code
| Part | File(s) | What it does |
|---|---|---|
| Entry point | `main.py` | Starts the web app and plugs in all routers |
| Key check | `v7_auth.py`, `api_keys.py` | Every `/api/v7/...` call needs a valid key; the user is taken from the key |
| v7 API (assembler) | `routers/v7_router.py` | Glues the v7 parts below into one set of addresses, same as before the split |
| Shared core | `routers/v7_core.py` | Common settings, the in-memory buffer, request formats, helper functions |
| Memory | `routers/v7_memory.py` | `/memory` (recall), `/remember` (save), events, shelves, search, forget, calendar |
| Cubes | `routers/v7_cubes.py` + `cubes_v2.py` | Experience cubes, votes, court, help requests and solutions, projects, feedback |
| Guards | `routers/v7_guards.py`, `routers/guardian_middleware.py` | Constitution text, Second Look, download of Guard 2, agent prompt |
| Agent helpers | `routers/v7_agent.py` | Website chat, agent run/step/pack/start, owner shell |
| Import | `routers/v7_import.py`, `routers/v7_batch.py` | Importing whole chats |
| Accounts | `routers/v7_account.py` | Profile, keys, login |
| Vault | `routers/vault_router.py`, `vault.py` | Secrets |
| System files | `routers/sysperm_router.py` | Owner's time-limited permission for agents to touch system files, with an audit log |
| Memory engine | `memory_v2.py`, `memory_v2_windows.py`, `semantic.py` | Builds the memory pack an agent receives (windows, map, hits) |
| Web pages | `routers/pages.py`, `*.html` | skv.network pages (home, chat, profile...) |

## The two guards
- **Guard 1 (server)** only reminds: it marks a missed step (turn not saved, no seal, cube duty open) in the next memory reply.
  It never blocks an answer and uses no AI.
- **Guard 2 (client)** is a small program the user downloads (`/api/v7/agent/guardian.py`). It runs next to the user's own
  model and does the real control: the agent must write DRAFT, then SECOND LOOK (check every claim against memory, mark
  what is not verified, check safety), then FINAL. Guard 2 asks for one redo if a step is missing, if FINAL barely changed,
  or if specific facts have no source. Then it saves the turn and shows the person only FINAL. It lowers mistakes; it is not a 100% guarantee.

## Night jobs (cron)
- 03:00 MSK `ops/evolver.py`: cubes nobody rated go to court; the court (two AI judges must agree to remove) decides; daily digest e-mail.
- Every hour at :15 `ops/evolver.py --watch`: new users and alarms, no AI calls.

## Safety rules in the code
- Keys are hashed; there is no "any token works" developer mode.
- Agents may touch system files only with the owner's time-limited grant (`/api/v7/sysperm/...`), and every action is logged.
- Shared cubes pass a filter (English, no secrets or personal data) before others can see them.

## Tests
`/root/skv-core/tests/` - each `test_*.py` checks one area. They run against a temporary copy of the data, never the live database.
