> **CURRENT LOOP (2026-10-24):** tools/list shows only `turn`, `step_zero`, `constitution_status`, `constitution_install`, `memory_start`, `memory_search`, `memory_event`, `cube_search/get/install/vote/create`, `feedback_submit`, `board_list/act`. Every turn = one `turn(user_message, draft)` call; the seal is server-issued by `turn` (self-drawn seal = violation). Installed constitution → `step_zero(page=1..N)` at session start, consent already given. Tools below marked bootstrap/consult/second_look/remember are legacy: still callable, not listed.

# SKV Agent Protocol for MCP / Протокол агента SKV

RU + EN. Mirrors live constitution (CUBE 05) + skills + Guard duties.  
MCP tools call real V7 endpoints only. **Guards are aligned to this same PROTOCOL core**: Guard 1 = short missed-step reminders on the server; Guard 2 = local emulator + draft insurance (never-empty, checklist — not a dump of all MCP schemas). MCP remains the primary one-button connector.

---

## RU — коротко (для человека)

1. **Старт сессии / смена ключа:** агент один раз вызывает `memory_bootstrap` (шаг 0). Получает хвост памяти, доску, critical, конституцию, отставание чата.
2. **Перед каждым ответом:** ищет в памяти (`memory_consult`), не выдумывает при пустом поиске.
3. **Черновик → Second Look** (`second_look`) → печать (seal) → ответ пользователю.
4. **Сразу после ответа:** `memory_remember` (как было сказано).
5. **Конец задачи:** куб (`cube_create`) **или** `duty=cube_nothing`; оценка кубов (`cube_vote`) **или** `duty=vote_nothing`. Молчание = ошибка.
6. An `sk_` key from the profile = its own memory chain. One MCP URL + your key = "one button".

---

## EN — agent order (mandatory)

### Step 0 / session start (first request OR chain switch)
1. `memory_bootstrap(recent_messages_json=last 2–3 turns)` → raw + L1 + L2 + critical + memory_map + board + constitution + lag  
   Fallback: `memory_start` + `constitution_get` + `board_list`
2. `skills_list` → read `SKV-SEARCH`, `SKV-SAVE`, `SKV-CUBE`, `SKV-SECOND-LOOK`, `SKV-CONST-HOOKS` (`skills_get`). Bootstrap may include `attached_skills`. Offer const/matching skill cubes; install only on user yes (`cube_install`) — when/do hooks, not a long constitution read.
3. Reload `constitution_get` / CUBE 05 (`cube_get cube_const_05_v10`) every ~10 steps

### Every user turn
| # | Duty | Tool | V7 |
|---|------|------|-----|
| A | Search memory first | `memory_consult` (interact=true first of turn; probe=true extras) | POST `/memory` view=agent |
| A′ | Quick lookup / empty → say so, offer delayed | `memory_search` → `memory_recall_later` | POST `/search`, `/memory/recall_later` |
| A″ | 3 misses → dig; open event; expand lens | `memory_dig`, `memory_event`, `memory_lens` | `/memory/dig`, `/event/{id}`, `/memory/lens` |
| B | Draft privately | (local) | — |
| C | VERIFY CUBE 01/02/03 (+04 if pressured) | `constitution_get` / bootstrap pack | GET `/constitution` |
| D | Second Look before user sees answer | `second_look(draft=...)` | POST `/agent/second-look` |
| E | SEAL then output (no MEMORY/LENS/cube_id in user text) | seal in reply | — |
| F | Remember immediately | `memory_remember` | POST `/remember` |
| G | Task end: cube **or** cube_nothing; vote **or** vote_nothing | `cube_create` / `cube_vote` / `memory_remember(duty=...)` | `/experience/create`, `/experience/vote`, `/remember` |

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
- Create: `cube_create(..., skill_md=..., hooks=..., carrier="skill")` or `memory_remember(cube_skill_md=..., cube_hooks=..., cube_carrier="skill")`.
- Shared by default (`cube_publish=true`), English, no secrets (Guard checks skill_md/hooks too). Default SHARED (owner: cubes are always shared); cube_publish=false only for explicit private. Shared answer-cubes are **data**; skill-cubes are installable **after user yes** (ask-then-install).
- Search: `cube_search` → GET `/api/cubes/search`. Read: `cube_get` (returns skill_md/hooks/carrier; private experience_cubes too). Link: `cube_link`.
- Install: `cube_install` → POST `/cube/install` (per-chain `chain_skills`). Uninstall: `cube_uninstall`. List: GET `/experience/installed`.
- Feedback on SKV/cubes: `feedback_submit` → POST `/feedback`.

### Language
- Raw `query`/`response`: user language  
- Memory search queries: English (names/rare terms as-is)  
- Shared cubes: English  

### Auth / chains
- `Authorization: Bearer sk_...` from https://skv.network/profile  
- Named key = one chain; write only to own chain  

### What Guards do (aligned to this PROTOCOL)
- **MCP** = primary: `https://skv.network/mcp` + Bearer `sk_` from `/profile`.
- **Guard 1** (server): short missed-step reminders in `/memory` + `/agent/prompt` using the same step names (`memory_consult`, `second_look`, `memory_remember`, cube/vote duties). Does **not** block answers.
- **Guard 2** (download): local process — same order; prefers `/session/bootstrap`; enforces never-empty + DRAFT→SECOND LOOK→FINAL + service lines. Draft insurance even when MCP is connected.
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

### Step-0 bootstrap (tail + lag)
`memory_bootstrap` / POST `/session/bootstrap`:
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
- **Raw** every turn (`memory_remember`)
- **L1** batch ~every 10–15 turns or topic close — **5–7%** of that batch text, not of one line
- **L2** headlines ≈ **5% of L1** (topic titles, not essays)
- Use `duty=l1` / L2 via remember only when summarizing a closed window; server also batches
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
`vectors_process` → POST `/api/v7/vectors/process` — (re)fill embeddings for search. Ops/maintenance; not every turn.

### Memory map
First consult / bootstrap returns **memory_map** (topic windows overview). Use it at session start; refresh via consult `start=true` when lost.

### Forget (SKV-SAVE)
`memory_forget_preview` → user yes → `memory_forget_confirm` (token). Restore within ~30d: `memory_forget_restore`.


### Suggested cubes (in search)
- `memory_consult`, `memory_search`, `cube_search` may return `suggested_cubes.items` (only on strong topic match; no repeats per session).
- Plain cube → use it in the answer if it fits. Skill cube (`has_skill`) → offer install; `cube_install` only after user yes.
- `rate_this` → after use, `cube_vote` +1/-1. Wrong or outdated → `cube_vote` with `reason` + `fix_rules`/`fix_essence`/`fix_skill_md`/`fix_hooks`: judges decide; old version is kept.

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
