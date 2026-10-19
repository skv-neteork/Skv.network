# SKV vault, one-time reveal links, hashed API keys (2026-10-19)

## What it does
- **Vault.** Per-user secrets are encrypted with AES-256-GCM. The associated data is `user_id|name`, so a ciphertext cannot be moved to another user or name.
  - Data lives in `shared_master.db`, in three tables: `vault_secrets`, `vault_log` and `vault_reveals`.
  - The master key is a separate file: host `/root/skv_vault/master.key` (root, 600), mounted read-only at `/run/skv_vault`. Override the path with `SKV_VAULT_KEY_FILE`. The key is not in `/data/skv`, so `backup_now.sh` data backups do not contain it.
- **Memory keeps references only.** Memory stores `[vault:<name>]`, never the value. `/remember` (query, response, critical, l1_summary, l2_map, cube_rules, cube_evidence, topic) and every chat turn (`account_memory.queue_turn`) run `vault.scrub()`. Secret patterns are moved into the vault as `auto_<kind>_<fp8>`. Placeholders like `YOUR_KEY`, `$(...)` and `<...>` are left alone. `/remember` returns `vaulted: [names]`.
- **Owner-only endpoints.** These sit under `/api/v7`; the API key decides the user:
  - `GET /api/v7/vault`: names and metadata, never values;
  - `POST /api/v7/vault {name, value, kind, note}`: store or overwrite;
  - `POST /api/v7/vault/use {name, purpose}`: returns the value. It is logged with purpose and IP, and sent with `Cache-Control: no-store`;
  - `POST /api/v7/vault/reveal {name, ttl_s (default 300, max 3600), require_login}`: returns a one-time URL;
  - `GET /api/v7/vault/log`: the audit log (no values);
  - `DELETE /api/v7/vault/<name>`: deletes the secret and also kills its open reveal links.
- **Reveal links: `https://skv.network/s/<token>`.**
  - Only `sha256(token)` is stored.
  - `GET` shows a page with a Reveal button and does **not** consume the link, so chat link previews cannot burn it.
  - `POST` consumes it atomically, once. The value is shown for about 10 s (or until the tab is hidden), then wiped from the page.
  - Responses send `no-store`, `no-referrer` and `noindex`.
  - Optional `require_login`: the owner's email and password are checked; 5 failures burn the link.
- **Hashed API keys.** `user_api_keys.api_key` now stores `h1$` + sha256(key). `key_prefix` and `label` are kept for display.
  - Lookups accept the plaintext key, so all existing keys kept working through the migration (14 rows).
  - A new key is shown once: on register, login and `POST /profile/keys`.
  - Login issues a new key each time and keeps at most 5 active login keys.
  - `/profile` lists `sk_xxxx… #id`; revoke with `DELETE /api/v7/profile/keys/<display or #id>`.
- **Internal self-calls.** Guardian tools calling `/api/v7/memory`, `/dig` and `/event` use short-lived (5 min) HMAC tokens `skint_…` instead of reading a stored key. These tokens are refused on `/vault`, `/profile`, `/auth` and `/account`.
- **Rate limit.** The limit now counts the real client IP (`X-Real-IP` from nginx-proxy). Before, every public request shared the proxy container's 300/min bucket.

## Transient reveal (one-time payload, not stored in the vault)
- POST /api/v7/vault/reveal/transient with label, value, ttl_s (max 3600), require_login encrypts the value with a key derived from the token itself and stores only the ciphertext in vault_reveals.payload_nonce / payload_ct.
- Nothing is written to vault_secrets. After open or expiry the ciphertext is zeroed then set to NULL (secure_delete on); the maintenance thread also purges leftover rows.
- Used for offline hand-off of the vault master key (and similar one-shots). Do not put the master key into vault_secrets.

## Ops
- **Image.** `skv-network:v8.4` is v8.3 plus `cryptography==50.0.2` (`deploy/Dockerfile.v8.4`). The run script is `/root/skv_api.run.sh` (copy in `deploy/`) and adds `-v /root/skv_vault:/run/skv_vault:ro`.
- **Tests.**
  - `tests/test_vault.py`: 30 checks, with cleanup;
  - `tests/test_api_keys.py`: 11 checks;
  - `tests/test_memory_v2.py`: 32 checks.
- **Backups.** `/root/backups/vault_20261019_1440` holds code, `shared_master.db` with plaintext keys from before hashing (root-only), the owner DB, `run.sh`, env, the pg key dump and the CUBE 05 v6 JSON.
- **Back up the master key offline.** If it is lost, vault values cannot be decrypted. Nothing else is affected.

## Rollback
1. Code: `git revert` the vault commits. Container: `docker rm -f skv_api` and use the v8.3 `run.sh` from the backup dir.
2. Hashed keys cannot be un-hashed. To restore plaintext rows, copy `user_api_keys` back from `/root/backups/vault_20261019_1440/shared_master.db`. Old code only does plaintext lookups, so without this restore every key fails.
3. CUBE 05: `cube_archive_const_05_v6` and the JSON backup. Rename `cube_const_05_v7` back to `cube_const_05_v6` with the old text, and set the main.py and v7_router refs back to v6.

## Not covered yet
- The legacy Postgres `user_api_keys` (4 rows, plaintext, used only by `/api/v4/*` and `/api/execute/code` paths) is not hashed.
- Secrets already in old memory are masked on output but were not moved to the vault. A one-off scan can do it on request.
