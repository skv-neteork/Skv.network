# SKV memory v2 (agent view, windows, lens)

Commits: f8bdeea (A), 9916730 (B), 4ff9a1b (C), step D (docs/tests). Backup before changes: `/root/backups/memv2_20261019_1336/` (code tgz, sqlite backups of all 48 account DBs, embed_config.json, default memory_config).

## Flags: `/data/skv/memory_config.json` (re-read on change, no restart)
| key | default | meaning |
|---|---|---|
| enabled | true | master switch for view=agent and the new endpoints. `false` = pure legacy |
| default_view | legacy | what `/memory` returns when `view` is not sent |
| mask_secrets | true | mask sk_ keys, Bearer, api_key=/password=/token=, private keys in /memory, /event, /memory/dig, lens |
| legacy_rowid_order | true | legacy map orders Raw/Critical by rowid (true chronology) instead of event_id |
| l2_legacy_overwrite | true | remember l2_map still overwrites summary_l2 (old readers); the old text is snapshotted into summary_l2_blocks first |
| bg_llm | false | old Llama L1/L2 background job (was crashing; calls polza.ai). Off until the owner decides |
| maintenance / maintenance_interval_s | true / 900 | migration + L1 ranges + auto L2 blocks for all accounts |
| lens_v2 | true | view=agent uses the new lens |
| session_idle_s | 1800 | a session counts as new after 30 min silence |
| budgets / caps | see below | token budgets and hard server caps |

Budgets (tokens): map 800, raw 3000, l1 2000, l2 1500, critical 400, constitution 1200, hits 1000, lens 1500, followup 3000. Caps: 2000/8000/6000/5000/1200/3500/3000/5000/8000.
Resolution: request `budget_<name>` > per-user `POST /api/v7/memory/settings {"budgets":{...}}` > defaults; always clamped to caps.

## API
- `POST /api/v7/memory` new optional fields: `view` (legacy|agent|debug), `session_id`, `start`, `probe`, `interact`, `format` (json|text|both), `focus_event_id`, `lens_offset`, `radius`, `budget_*`.
  - legacy (default): same keys as before; `probe=true` = no step bump, no duty_error.
  - agent: no debug arrays, no duplicates. Step bumps only with `interact=true` (send it on the first memory call of each user turn).
  - First request of a session (new session_id, `start=true`, or idle > 30 min): `memory_map` {who, projects, topics}, `windows` {raw, l1, l2, bounds, tokens}, `critical`, `constitution_compact` (+ url). Follow-ups: `hits` + `lens` only, ≤ followup budget.
  - windows: raw = newest turns by rowid, verbatim (>>> lines go to critical), 10..30 msgs, ≤600 tok each; l1 = summaries with to_rowid < raw start (gap entries where no L1 exists); l2 = blocks with to_rowid < L1 start. No overlap by construction.
  - lens: `terms`, `clusters` (1 full: center, before, after, l1, l2, critical; 2..5 brief with `expand.focus_event_id`), `clusters_total`, `total_hits`, `more_cursor` (send as `lens_offset`). `hits[0]` = center of cluster 1.
- `GET /api/v7/memory/start?session_id=&query=&format=text|json` — first-request pack for GET-only agents.
- `GET /api/v7/agent/memory?...&view=agent` — weak-agent passthrough (text by default).
- `POST /api/v7/memory/lens {query_text | focus_event_id, radius, offset, budget_lens, kind, source, project}` — light follow-up, no step bump.
- `GET|POST /api/v7/memory/profile` — who / projects / prefs (merge, never delete).
- `GET /api/v7/memory/l2/blocks` — L2 series (sources: legacy_summary_l2, auto, agent).
- `GET|POST /api/v7/memory/settings` — per-user budgets.

## Data (additive only)
`summary_l1` + from_rowid, to_rowid, lang; new `summary_l2_blocks`, `user_profile`, `memory_sessions`, `memory_settings`. The legacy `summary_l2` row is untouched and copied into blocks (`legacy_summary_l2`). Nothing is deleted.

## Rollback
1. Soft: `{"enabled": false}` in /data/skv/memory_config.json → legacy only (masking stays unless `mask_secrets: false`).
2. Per feature: `lens_v2: false`, `maintenance: false`, `legacy_rowid_order: false`, `l2_legacy_overwrite: true`.
3. Code: `git revert <D> 4ff9a1b 9916730 f8bdeea` in /root/skv-core, then `docker restart skv_api`. New tables/columns are ignored by the old code.
4. Data: restore any DB from `/root/backups/memv2_20261019_1336/metadata_store/` (stop skv_api first).

## Tests
`SKV_KEY=sk_... python3 tests/test_memory_v2.py all measure` on the server (localhost:8000): 31 checks (A legacy compat, probes, masking, budgets; B map/windows/no overlap/L2 preserved; C lens clusters/focus/paging/≤3k).
Quality harness (box): `/workspace/skv_eval/harness.py` (legacy) and `SKV_VIEW=agent` (agent view).
