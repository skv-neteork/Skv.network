# Import pipeline (v2) — topic windows, cheap L1/L2, routing

## What was wrong (09.10 grokexp)
- Fixed windows ~60–70 messages mixed topics.
- Too much text → model refusals saved as L1 ("Текст слишком длинный…").
- Some L1s did not match window content (term mismatch).
- Message index offset was OK; splitting was not.

## New behaviour (rollback switches in `memory_config.json` → `import`)
| Key | Default | Meaning |
|-----|---------|---------|
| `legacy_fixed_windows` | false | true = old cut-by-60 |
| `max_msgs` / `min_msgs` / `max_chars` | 12 / 4 / 6000 | topic-aware window caps |
| `topic_change_threshold` | 0.10 | flush on topic bag overlap drop |
| `verify_term_overlap` / `min_term_overlap` | true / 0.32 | reject mismatched L1 |
| `reject_refusals` | true | drop refusal/garbage L1 |
| `separate_chain` | true | L1 under `import:<source>` |
| `tag_shelves` | true | kind=import on events |
| `l1_model` / `l2_model` | `meta-llama/llama-3.1-8b-instruct` | **cheap only** |
| `route_critical` | true | L1/`>>>` → critical_candidates + critical_auto |
| `route_secrets` | true | vault scrub → `[vault:name]`, never plain memory |
| `route_heavy_to_drive` | true | heavy URL/base64/large → Drive queue + `[drive:pending:…]` stub |
| `heavy_char_threshold` | 12000 | whole-turn size trigger |
| `drive_folder` | SKV Import | target Drive folder (agent MCP or server OAuth) |

### Cheap model hard rule
L1 and L2 call Polza through `_polza()`. Default is Llama 3.1 8B. If someone sets a frontier model name, import **refuses** it and falls back to 8B. Strong models stay for interactive chat only.

### Routing (Deniz)
1. **Secrets** → `vault.scrub` / `vault.put` (AES-GCM under `/run/skv_vault`). Memory keeps only `[vault:…]`.
2. **Critical** → `critical_candidates` (pending review) + `critical_auto` kind=`import_mark` (live Critical layer). Password-like lines skipped.
3. **Heavy files** → row in `import_drive_queue` (status=`pending`) + stub `[drive:pending:name]` in text; bytes staged under `/data/skv/drive_staging/`. **Drain (T_GDRIVE):** `GET /import/drive/queue|payload`, upload to Drive folder **SKV Import** (MCP `user-Google-drive--skv` or server OAuth `/root/skv_drive/`), then `POST /import/drive/complete` → stub becomes `[drive:url]`, `drive_url` set, staging deleted. MCP tools: `drive_queue_*`. `POST /import/drive/process` if OAuth present.

Log table: `import_routing_log` (route = vault|drive|critical).

## Side-by-side rebuild (does not wipe raw events)
```
POST /import/rebuild
{"user_id":"…","source":"grokexp","prefix":"v2","dry_run":true}
```
- `dry_run=true` → window plan only (events/windows/preview).
- `dry_run=false` → background rebuild into topic `import:grokexp:v2`, session ids `import:grokexp:v2:l1_N`. Old `grok` L1s untouched.

Rollback: set `import.legacy_fixed_windows=true` and re-run, or ignore the `:v2` chain.

## Ops
- Code: `src/app/routers/import_dialogs.py` (bind-mounted into `skv_api`).
- Restart only via `ops/safe_restart.sh`.
- Backup of pre-fix tree: `/root/backups/import_fix_20261023_212435/`.
