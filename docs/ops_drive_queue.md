# Import → Google Drive queue (T_GDRIVE)

Heavy import payloads enqueue into `import_drive_queue` (pending) with staging under `/data/skv/drive_staging/` and memory stub `[drive:pending:name]`.

## Agent / MCP (preferred)

1. `drive_queue_list` (or `GET /api/v7/import/drive/queue?user_id=…`)
2. `drive_queue_payload(id)` → base64
3. Upload via Google Drive MCP into folder **SKV Import** (`create_file` with `parentId` of that folder)
4. `drive_queue_complete(id, drive_url, drive_file_id)` → stub → `[drive:url]`

## Server OAuth (optional)

Place `token.json` + `client_secret.json` under `/root/skv_drive/`, then:
`POST /api/v7/import/drive/process` `{user_id, limit}` or MCP `drive_queue_process`.

## Restart

Only `ops/safe_restart.sh` after code deploy. Nightly backup remains local; Drive copies are agent-mediated.
