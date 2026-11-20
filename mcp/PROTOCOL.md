> **CURRENT LOOP:** public `tools/list` is 39 names (`src/app/mcp_public_tools.py`, same set in `mcp/mcp_skv.py`). Start order, once per new key: `constitution_install(user_confirmed=true)` only after a yes, then `identify(name)`, then `step_zero(page=1..N)` until `done=true`, then `turn(user_message, draft)` on every user message. The seal is issued only by `turn`. Same key: do not call `step_zero` again. A rotated key does this order once. `memory_bootstrap`, `memory_consult`, `second_look`, `memory_dig` and `memory_event` are not in the public 39. `memory_import_text` is public: pasted chat text. A conversations export is uploaded on Profile.

# SKV Agent Protocol for MCP / Протокол агента SKV

RU + EN. Mirrors live CUBE 05-MCP (`cube_const_05_mcp_v20`) and the compact constitution v5.  
MCP tools call real V7 endpoints only. MCP is the primary connector. Guard 1 sends short missed-step reminders. The Guard 2 download still follows the older HTTP order (bootstrap, consult, second look). That order is not the public MCP loop.

---

## RU — коротко (для человека)

1. **Новый ключ, один раз:** если конституция не стоит, агент спрашивает один раз и вызывает `constitution_install(user_confirmed=true)` только после «да». Затем `identify(name)`, затем `step_zero` до `done=true`.
2. **Каждое сообщение:** черновик, затем `turn(user_message, draft)` до ответа. Печать берётся только из `turn`.
3. **Память:** поиск внутри `turn`. Если фактов мало, `memory_search` на языке памяти. Пустой поиск — не повод выдумывать.
4. **Конституция:** компакт v5. Манифест приходит на первом ходе сессии, при новой версии, при `context_reset` и каждый 10-й ход. Ответ: `const_ack=true`. CUBE 00 заново по счётчику сообщений не читают.
5. **Конец задачи:** куб (`cube_create`) **или** `duty=cube_nothing`; оценка кубов (`cube_vote`) **или** `duty=vote_nothing`. Молчание = ошибка.
6. Ключ `sk_` из профиля — своя линия памяти. Один URL MCP + ключ = «одна кнопка».

---

## EN — agent order (mandatory)

### New key (once)
1. If the constitution is not installed, ask once. On yes: `constitution_install(user_confirmed=true)`. The reply is short and has no step_zero pages. On no: answer without SKV.
2. `identify(name)`. The reply includes `agent_token` once. Pass it on later calls.
3. `step_zero(page=1, agent_token)`, then further pages until `done=true`. PACK888 pages are the memory pack (constitution, profile, L2, L1, raw, open items, access counter) plus full CUBE 00–04 and CUBE 05, once. Critical marks are headings inside L2 and L1. Each page stays under 15 KB. Do not stop before `done=true`.
4. Do not repeat `step_zero` for the same key. A rotated key does this order once. Do not ask for consent again.

### Every user message
| # | Duty | Tool |
|---|------|------|
| A | Draft privately. Check it against CUBE 01–04. | local |
| B | Before the user sees the answer: search, save, Second Look, seal | `turn(user_message, draft)`. Answers that went out without `turn`: next call `turn(..., recap='tNu: ask => answer')` |
| C | Facts inside `turn` are not enough, or the user asks to recall | `memory_search` in the account `base_language`, then `memory_recall_later` / `memory_recall_status` |
| D | Copy the seal from `turn`. Do not invent one. | seal line only |
| E | Manifest in the reply (`constitution_manifest`) | next `turn(..., const_ack=true)` or `ack="const"` |
| F | Task end: cube **or** `duty=cube_nothing`; vote **or** `duty=vote_nothing` | `cube_create` / `cube_vote` / `turn(duty=...)` |

`turn` returns facts, cubes and a self-check. The server does not judge the meaning of the draft. `verdict=revise` only when an `[ev:id]` in the draft is not in memory.

### Constitution heartbeat
The compact summary is v5: `src/app/constitution_compact_v2.md`. Live cube rows are `cube_const_00_v6`, CUBE 01–04 at v4, CUBE 05 `cube_const_05_v22`, MCP how-to `cube_const_05_mcp_v20`.

`src/app/const_bind.py` puts `constitution` (version, hash, one rule, stale) on every turn reply. The full manifest is sent on the first turn of a session, on a new version, on `context_reset=true`, and every 10th turn (`MANIFEST_EVERY = 10`). After four ignored manifests it is sent every turn until `const_ack=true`. Do not re-read CUBE 00 on a fixed message count. One rule per other turn.

L1 is written at the start and at the end of a big task, or when a topic closes (`l1_summary` plus `source_event_ids`). L2 is about 5% of L1, when `summary_due.l2` appears. The server writes a fallback only if the agent skips it, about 15 turns after `summary_due`.

### Vectors
Live text search embeds with `mml12`: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-d, index `/data/skv/hnsw_mml12` (`semantic.py`, active tag in `/data/skv/embed_config.json`). The English bge 768-d index at `/data/skv/hnsw` is frozen. `account_memory.DIM = 768` is that frozen index. A raw `query_vector` with no `query_text` is still rejected unless its length is 768. That check is the old guard, not the live embedding size.

### Court
A vote is +1 or -1. A −1 needs a reason. Own cubes cannot be voted. Three negative outcomes from distinct clients (the same user or the same IP counts as one; the author is excluded) set status `disputed` and insert `court_queue`. The cube stays visible. A downvote does not set `deprecated`. Three distinct helped confirmations set status `verified`.

`ops/evolver.py` drains the queue at 03:00 MSK. One judge (`deepseek/deepseek-chat`). A second (`llama-3.3-70b-instruct`) only if the first verdict is `remove`. A third (`qwen3.6-plus`) only if that second reply does not parse. The cube is archived, never hard-deleted, only when two distinct judges both say `remove`. Otherwise a `fix` or a single `remove` becomes an effective `fix` (rules may be rewritten, status `community`). A proposed fix or version (`fix:` / `version:`) is one judge unless the first says `remove` or says `fix` on a risky change (removal, hooks, skill_md, or `[court_only]`); the old text stays until every asked judge says `fix`. Abstain retries the next night and is dropped after three nights for a human judge. Constitutional cubes are skipped. Caps: 40 cases a run, 5 per author, 200 calls a day, 400k tokens a day. Hourly `:15 --watch` is alerts only.

Other queue sources: zero ratings after 12 impressions; a `cube_link` kind `against` (queues only, does not itself set status); a merge of someone else's cube; a removal request.

### Constitution as hooks (SKV-CONST-HOOKS)
- Base constitution skills (shared, auto-attached): `cube_skill_const_second_look`, `cube_skill_const_memory`, `cube_skill_const_close`, `cube_skill_const_cube_install`, `cube_688c0ebbb3be` (meta cube-author: how to create cubes).
- Long CUBE 00–05 text stays available via `constitution_get`, but agents should execute **hooks**.
- Private skill cubes (Deniz first cut): `cube_skill_const_second_look` (`before_reply`), `cube_skill_const_memory` (`session_start`/`before_reply`), `cube_skill_const_close` (`after_reply`/`task_end`/`secret_in_text`), `cube_skill_const_cube_install` (ask-then-install).
- Index: `skills_get SKV-CONST-HOOKS.md`. CUBE 01–04 checked inside Second Look hooks.
- **Connect = consent:** on Step 0 / bootstrap the server auto-attaches constitution hook cubes (`cube_skill_const_*`) and the meta create-cubes skill (`cube_688c0ebbb3be`). Connecting the agent to SKV is the consent for those — no ask.
- **Ask then install (everything else):** when the task matches other skill cubes → offer ("I have experience cubes for X — attach?"). Install only after explicit yes (`cube_install` + `user_confirmed=true`) OR user already said install/attach this cube (`user_said_install=true`). **Never silent install** for non-default cubes. Uninstall: `cube_uninstall`.
- Bootstrap / Step 0 returns `attached_skills` (skill_md + hooks) for cubes installed on this chain (incl. auto-attached defaults).
- Guard 1 stays short reminders; Guard 2 checklist unchanged.

### Cubes (SKV-CUBE)
- One shelf. `carrier=answer` (default) shapes the reply; `carrier=skill` is an installable skill+hooks package the agent plugs in; later `carrier=robotics`.
- Kinds (content shape): `moment` (obvious/miss/instead/check) · `fact` · `culture` · `lifehack` · `warning` · `code`
- Skill fields on the same cube: `skill_md` (SKILL.md body), `hooks` (JSON `[{when,do}]` or when-strings). Auto `carrier=skill` if set.
- Create: `cube_create(..., skill_md=..., hooks=..., carrier="skill")` (HTTP: `POST /api/v7/experience/create` with the same fields).
- Shared (`cube_publish=true`), English, no secrets (Guard checks skill_md/hooks too). `cube_publish=false` is refused and stores no private cube. Shared answer-cubes are **data**; skill-cubes are installable **after user yes** (ask-then-install).
- Search: `cube_search` → GET `/api/cubes/search`. Read: `cube_get` (returns skill_md/hooks/carrier; private experience_cubes too). Link: `cube_link`.
- Install: `cube_install` → POST `/cube/install` (per-chain `chain_skills`). Uninstall: `cube_uninstall`. List: GET `/experience/installed`.
- Feedback on SKV/cubes: `feedback_submit` → POST `/feedback`.

### Language
- Raw `query`/`response`: user language  
- Memory search queries: the account `base_language` (names and rare terms as-is). Cube search and cube text: English.  

### Auth / chains
- `Authorization: Bearer sk_...` from https://skv.network/profile  
- Named key = one chain; write only to own chain  

### What Guards do (aligned to this PROTOCOL)
- **MCP** = primary: `https://skv.network/mcp` + Bearer `sk_` from `/profile`.
- **Guard 1** (server): short missed-step reminders. It does **not** block answers. Its reminder text still names the older HTTP steps.
- **Guard 2** (download): local process. The file still prefers `/session/bootstrap` and DRAFT → SECOND LOOK → FINAL. That is the download, not the public MCP start order. Draft insurance still runs when MCP is connected.
- Shared short constants: `app/skv_protocol.py`. Full text = this file.

---

## One-button connect

**Remote (any user, Cursor/Claude):**  
`url`: `https://skv.network/mcp` + `headers.Authorization: Bearer sk_...` from `/profile`  
(Streamable HTTP. SSE alternative: `https://skv.network/mcp/sse`.)

**On server / SSH:** `ops/mcp_stdio.sh` + `SKV_API_KEY=sk_...`.

See **README.md** for full JSON snippets.

Tools without a matching V7 route were **not** invented.


---

## This week’s memory work (mirror — keep constitution meaning)

### Legacy HTTP bootstrap (not the public MCP start)
`memory_bootstrap` is not in the public 39. The MCP start is `identify` then `step_zero`. The HTTP route POST `/session/bootstrap` still returns:
- Continuity: **raw tail** + **L1** + **L2** + **critical** + **memory_map**
- Plus **constitution**, **board**, reminders
- Pass last **2–3** chat messages → server detects **lag** (chat ahead of memory)
- Returns `chain_id` label for this named key. Write only to own chain.

### Named keys = chains
- Profile `sk_…` name = one memory **chain** (`chain_id`)
- Rename / rotate / revoke via profile or MCP `keys_*` tools → V7 `/profile/keys…`
- Rotate keeps same name+chain with new secret; rename keeps secret+chain; revoke disables
- Cross-chain search: **labeled read-only** when available (`whose-memory` / chain label). Until then bootstrap notes it as stub — do not invent other-chain facts.

### Honest search + delayed recall
- Empty / weak hits → **say no match**; do **not** invent
- Offer: `memory_dig` (after ~3 misses) and/or `memory_recall_later` (cheap on-server agent, ~5–30 steps, **sourced** report with event ids/dates)
- Poll `memory_recall_status`; report only what sources support

### L1 / L2 quality (write discipline)
- **Raw** every turn (`turn` saves it; answers sent without turn: `turn recap=` in the next call)
- **L1** at the start and at the end of a big task, or when a topic closes — about **5–8%** of that raw text, with `source_event_ids`. Not "every 10–15 turns" as the agent's duty.
- **L2** headlines ≈ **5% of L1** when `summary_due.l2` appears (topic titles, not essays)
- The server writes a fallback summary only if the agent skips it, about 15 turns after `summary_due`
- Critical = rare lasting facts (`memory_critical`)

### Topic-window import + routing
`memory_import_text` → POST `/api/v7/import/text` (topic-aware windows, not fixed-60):
- Windows: topic change + caps (`max_msgs`/`min_msgs`/`max_chars`)
- Cheap L1/L2 only (8B-class); refuse frontier models for import
- Quality: term-overlap verify, reject refusals/garbage
- **Routing:** secrets → vault `[vault:…]`; critical marks → Critical layer; heavy URL/base64/large → `import_drive_queue` + stub `[drive:pending:name]`
- **Drive drain (T_GDRIVE):** agent MCP `drive_queue_list` → `drive_queue_payload` → upload via Google Drive MCP into folder **SKV Import** → `drive_queue_complete` (replaces stub with `[drive:url]`). Optional server OAuth: `drive_queue_process` if `/root/skv_drive/token.json` present. Nightly backup stays local; Drive copies are agent-mediated.
- Separate import chain `import:<source>`; tag shelves `kind=import`
- Optional rebuild: server `/import/rebuild` (ops; dry_run first)

### Vector fill
`vectors_process` → POST `/api/v7/vectors/process` — (re)fill embeddings for search. Ops/maintenance; not every turn. Live fills are 384-d `mml12`. The 768-d bge index is frozen.

### Memory map
First consult / bootstrap returns **memory_map** (topic windows overview). Use it at session start; refresh via consult `start=true` when lost.

### Forget (SKV-SAVE)
`memory_forget_preview` → user yes → `memory_forget_confirm` (token). Restore within ~30d: `memory_forget_restore`.


### Suggested cubes (in search)
- `memory_consult`, `memory_search`, `cube_search` may return `suggested_cubes.items` (only on strong topic match; no repeats per session).
- Memory search stays in the memory language. Cube search translates a non-English query into English on the server (`cube_query`) and searches the English catalog. Names and ids stay verbatim.
- Plain cube → use it in the answer if it fits. Skill cube (`has_skill`) → offer install; `cube_install` only after user yes.
- `rate_this` → after use, `cube_vote` +1/-1. A −1 needs a reason. Three negatives from distinct clients set status `disputed` and queue the cube. They do not set `deprecated`. A fix proposal (`fix_rules` / `fix_essence` / `fix_skill_md` / `fix_hooks`) keeps the old text until every judge who was asked says `fix`.

## Connecting without custom headers (key in URL)
Some clients (e.g. free Claude.ai custom connectors) cannot send headers. Use the key in the URL path:
`https://skv.network/mcp/k/<YOUR_SK_KEY>/` (Streamable HTTP, same tools, auth "none" in the client).
Header auth (`Authorization: Bearer sk_...` on `https://skv.network/mcp/`) is unchanged and preferred.
The URL contains your key: treat it as a secret. Revoking the key in /profile makes the URL return 401.

## Memory lines (one key = one line)
Each agent key (sk_ from /profile) writes and reads its own memory line. 3 parallel agents with 3 keys = 3 lines.
- Default (bootstrap, /memory/start, /memory, /memory/dig): only this key's line.
- Explicit cross-line search: `lines="all"` (MCP `memory_consult(..., lines="all")`, API body `"lines":"all"`). Use it only when the user asks or the own line misses; label what came from other lines.
- Memory saved before lines existed belongs to the account's `main` key line.

Filtered endpoints: /memory, /memory/start, /memory/dig, /session/bootstrap, /search, /memory/lens, /memory/recall_later, /event/{id} (foreign event -> 404). MCP tools memory_search, memory_consult, memory_dig accept lines="all". Works the same for header auth and the /mcp/k/<key>/ URL route.

Summaries are split per line too: during a default read the server builds raw, L1, L2, critical facts and search only from the caller line (read-only DB view). An L1/L2 summary is shown to a line only if it was written by that line key or its range holds only that line events; legacy summaries stay with the main line. The background L1 builder never mixes lines in one chunk. lines=all merges all lines. The code-pattern output filter stays as an extra guard.
