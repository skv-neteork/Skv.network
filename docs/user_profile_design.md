# SKV User Profile layer: design (Phase 1 approved; Phase 2 implemented 2026-10-24)
Status: draft for Deniz's review, 2026-10-24. Author: agent. Code is not changed.

## 0. Goal and "why bother"
The profile holds lasting facts about the user and how to work with them: preferences, working rules, decisions, prohibitions and identity. Every agent (MCP, REST, Guards) gets them through step_zero and turn.
- Board = tasks (what to do). Critical facts = any important fact (what is true). Profile = how to work with this user (how to act).
- Why an agent uses it: turn returns the rules relevant to the current message that the agent would otherwise break. self_check checks the answer against those rules. Profile upkeep is a forced duty (section 5), not a goodwill duty.

## 1. Data model
Stored in the account's sqlite DB (/data/skv/metadata_store/<acct>.db). New module src/app/profile.py, with ensure() written in the same style as critical_auto/source_links.

```sql
CREATE TABLE user_profile (
  id TEXT PRIMARY KEY,            -- 'p_' + 8 hex, stable
  kind TEXT NOT NULL CHECK(kind IN ('preference','rule','decision','prohibition','identity')),
  text TEXT NOT NULL,             -- <=300 chars, imperative/declarative, one rule per row
  scope TEXT NOT NULL DEFAULT 'global', -- 'global' | 'project:<name>' | 'agent:<name>' | 'topic:<tag>'
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','superseded','retracted')),
  supersedes_id TEXT REFERENCES user_profile(id),
  superseded_by TEXT,             -- denormalized for fast history walk
  source_event_ids TEXT NOT NULL, -- JSON array of ev ids, or '["unlinked"]' (explicit)
  author TEXT NOT NULL CHECK(author IN ('agent','server_fallback','import','user')),
  agent_name TEXT,                -- which agent/client wrote it
  confidence REAL NOT NULL DEFAULT 0.9, -- agent 0.7-1.0; server_fallback <=0.6
  priority INTEGER NOT NULL DEFAULT 2,  -- 1 high (prohibitions default), 3 low
  keywords TEXT,                  -- for relevance ranking (agent supplied or extracted)
  reason TEXT,                    -- for supersede/retract
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX up_status ON user_profile(status, scope);
CREATE TABLE user_profile_log (   -- append-only history
  seq INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT, op TEXT, -- add|supersede|retract|confirm|fallback_add
  before_json TEXT, after_json TEXT, turn_event_id TEXT, author TEXT, at TEXT);
CREATE TABLE profile_duties (     -- open candidates / reviews
  id TEXT PRIMARY KEY, kind TEXT, -- 'profile_candidate' | 'profile_review'
  event_id TEXT, signal TEXT, opened_turn INTEGER, status TEXT, -- open|resolved|expired|fallback
  resolution TEXT, resolved_at TEXT);
```
Rules:
- Rows are never deleted. "Delete" = retract, "correct" = supersede (a new row is created and the old one gets status superseded). The full history lives in user_profile_log.
- source_event_ids are also written to source_links (obj_id='prof:<id>', kind='profile'), so dig and the link index work without special code.
- Version hash: profile_version = sha1(sorted active ids+updated_at)[:8]. It is the same mechanism as cubes_version.

## 2. Relation to critical facts
- Critical facts stay for what is true about the world or the project: URLs, accounts, numbers, statuses. Rules about behaviour go to the profile.
- One-time migration (dry-run report first, nothing deleted):
  - critical rows whose text matches rule/preference patterns are proposed to the agent as profile candidates;
  - if accepted, the critical row gets `moved_to=prof:<id>` (a new column) and is no longer returned in recall;
  - the source row is kept.
- Dedup on write: if the new text is ≥0.85 similar (normalized token Jaccard, or embedding if available) to an active profile row, the server answers `dup_of=<id>` and asks for supersede or confirm instead of add.
- critical_auto (server regex) never writes to the profile.

## 3. Write path (agent primary)
New turn field (MCP+REST, same core function):
```json
"profile": [
 {"op":"add","kind":"rule","text":"Сначала довести существующее до работоспособности, потом новые фичи","scope":"global","ev":["ev_ab12"],"priority":1},
 {"op":"supersede","id":"p_1a2b3c4d","text":"...","ev":["ev_cd34"],"reason":"Deniz changed decision"},
 {"op":"retract","id":"p_5e6f","ev":["ev_ef56"],"reason":"user said no longer valid"},
 {"op":"confirm","id":"p_77aa","ev":["ev_99"]},
 {"op":"dismiss","duty_id":"pd_x","reason":"one-off request, not lasting"}
]
```
Server checks (reject → `revise` with a precise error and no partial write; all ops are applied in one transaction):
1. Every ev exists and belongs to the account. The existing v7 ownership check and short ids are reused. `"unlinked"` is allowed only for author=import, or with an explicit `unlinked_reason`.
2. kind and op are valid; text is ≤300 chars and non-empty.
3. The sensitivity gate: the existing pii_filter plus the [SECRET] and token patterns run on the text. On a hit → revise: "secrets go to Vault; reference vault:<id> instead". The profile may hold `vault:<id>` refs only.
4. supersede/retract target exists and is active. Superseding a superseded row → error with pointer to current head.
5. Dedup (section 2).
6. Rate limit: ≤10 ops/turn.
The turn response returns `profile_applied:[{op,id}]` and the new `profile_version`.

## 4. Conflicts and supersede
- One head per chain. The newest agent op wins; history is kept in the log and the supersedes chain.
- Two active rows that contradict each other (same scope, flagged by the agent or by the server's negation heuristic "всегда X" vs "никогда X"): the server returns duty `profile_conflict` listing both ids. The agent must supersede one or narrow the scopes.
- server_fallback never supersedes agent rows. It can only add rows, at confidence ≤0.6, shown as "(unconfirmed)". An agent confirm turns such a row into author=agent.
- Scope: a narrower scope beats global when both are relevant (project rule beats global default).
- A user statement in the current turn always overrides the profile. The agent then must supersede the row (candidate duty fires).

## 5. Forcing mechanism (duties)
### 5.1 profile_review, tied to L2
When `summary_due` includes l2, the turn that sends `l2_summary` MUST also send `profile_review`:
```json
"profile_review": {"ops":[...same as profile...]}      // or
"profile_review": {"no_changes": true, "reason":"L2 window had only bugfix chatter, no new user rules"}
```
- The server gives the agent the list of active profile rows touched in the window (relevant ids) plus the window's open candidates, so the review is cheap.
- Missing → `revise`: "L2 rejected: profile_review required". The L2 is not stored. no_changes needs a reason ≥20 chars. If there are still open candidates from that window, no_changes is rejected until they are resolved or dismissed.
### 5.2 profile_candidate, light hook
- Signal detector on the user message, RU+EN, cheap regex/lexicon, no LLM:
  - RU: всегда, никогда, не надо, не делай, хочу чтобы, предпочитаю, запомни, правило, впредь, с этого момента, больше не, лучше так, давай всегда;
  - EN: always, never, don't, prefer, from now on, remember that, rule;
  - plus approvals of policy ("даю добро … но …").
- On a hit, turn returns `duties:[{id:'pd_..', kind:'profile_candidate', event_id, signal:'<matched phrase+40 chars>'}]`.
- The agent must resolve it within the next 2 turns, with profile op add/supersede or dismiss+reason. If it doesn't, the reminder escalates, and on turn 3 the answer gets `[PROFILE ✗]` in the seal checklist (seal still issued, but marked).
- The signal lexicon is a cube (editable via the court), not hardcoded.
### 5.3 Server fallback, last resort
- It runs only if a candidate expired (agent ignored it for N=5 turns, configurable `profile_fallback_grace_turns`) or the agent skipped profile_review for 2 L2 windows in a row.
- It uses the same LLM as the summarizer, a strict JSON prompt and the conservative rule "only explicit user-stated lasting rules, quote the user". It writes author=server_fallback, confidence ≤0.6, linked to the ev.
- The next turn returns `profile_unconfirmed:[ids]` as a duty to confirm or retract.
- It is logged to /var/log/skv_selfcheck.log.

## 6. Read path
### step_zero, page 1 (always)
`PROFILE v<hash> (N active)`. The block holds the top rows by priority, prohibitions first, then rules, decisions, preferences and identity. Budget ≤1.5 KB / ≤12 rows. Each row is one line: `[prof:p_1a2b] RULE: text (scope)`. The rest is listed via `memory_dig(focus_id=prof:list)`.
### turn (every turn)
- Relevant rows only, ≤5 rows / ≤800 B, ranked by:
  1. prohibitions with scope match (always);
  2. keyword/embedding similarity to user_message+answer;
  3. rows referenced by open duties;
  4. priority.
- Compact mode: like cubes. The full relevant set is sent only when its hash changed for the session; otherwise `profile_version` plus only rows newly relevant this turn. compact_state gets a `prof_h` column.
- self_check gains the item "Answer does not violate the PROFILE rows shown (list ids); if it does, say why or supersede". Server side, a cheap check flags obvious prohibition hits (e.g. a prohibition keyword present in the answer) as `profile_warning`. It is advisory, not blocking.
### memory_dig
- `focus_id=prof:<id>` → row + history chain + source events with radius.
- `prof:list` → all active rows; `prof:history` → the log.
- memory_search includes profile rows (as type profile) when the query matches.

## 7. Sensitive data
The profile never holds secrets, contacts or credentials. The gate in 3.3 enforces this, and the same gate also runs on the server_fallback output. Identity holds non-sensitive items only (name, language, timezone). Anything else is stored as a `vault:<id>` ref.

## 8. Constitution and cube text changes
- CUBE 05 MCP + CUBE 05 REST (v12→v13):
  - the `profile` and `profile_review` fields with examples;
  - duty kinds profile_candidate/conflict/unconfirmed;
  - the rule "behaviour rule → profile, world fact → critical";
  - "correct = supersede, delete = retract, never re-add".
- CUBE 00/hooks:
  - L2 hook: "with l2_summary always send profile_review";
  - turn hook: "resolve open profile duties first".
- Guards (no MCP): the startup prompt gets the PROFILE block from step_zero. Guard 2 adds the profile_review requirement in its L2 instruction. REST turn accepts the same fields.
- Tool descriptions: turn gets the profile fields listed explicitly (lesson from board_act). memory_dig adds the prof: prefix.
- New cube: "profile signals lexicon" (shared, court-editable).

## 9. Migration of the existing ~100 assistant-memory facts
1. Parent agent exports its memory list to a file (text + date if known).
2. The agent reviews each item: keep/drop, kind, scope. It searches SKV (memory_search) for the originating event to link. If none is found → `unlinked` + unlinked_reason.
3. Import in batches of 10 via turn `profile` ops with author=import. Dry-run first gives the report: kept/dropped/linked/unlinked counts.
4. Deniz skims the resulting `prof:list` once.
5. Critical-fact migration (section 2) runs after, with dedup against imported rows.
After that, every new entry in the assistant's own memory is mirrored with the same op in the same turn (duty in CUBE 05).

## 10. Smoke tests (added to the existing 25-check autotest)
1. add with own ev → active; with a foreign or non-existent ev → revise.
2. supersede → old superseded, chain ok; retract → hidden from reads, present in dig history.
3. Secret / [SECRET] / token in text → revise, nothing stored.
4. Dedup → dup_of returned.
5. step_zero page 1 has the PROFILE block ≤1.5 KB on an account with 50 rows.
6. turn relevance: a prohibition appears for a matching message; compact second turn → version only.
7. Signal message → profile_candidate duty; dismiss resolves it; ignoring it 5 turns → server_fallback row conf ≤0.6.
8. l2_summary without profile_review → revise and L2 not stored; with no_changes+reason → ok.
9. memory_dig prof:<id> returns sources.
10. Fresh account before constitution install → profile ops rejected (consistent with turn gating).
11. MCP and REST parity: the same ops give the same result (single core function).

## 11. Implementation shape (no hacks)
- One module `src/app/profile.py` (schema, ops, validation, ranking, render, fallback). rest_turn.py, mcp/mcp_skv.py and step_zero_lite.py call it, with no logic duplicated in the wrappers. The box connector syncs via the existing sync script.
- Config keys go in the existing settings: profile_turn_rows=5, profile_turn_bytes=800, profile_sz_bytes=1500, profile_fallback_grace_turns=5, candidate_resolve_turns=2.
- Feature flag `profile_enabled` per account.

## 12. Rollout and rollback
1. Schema + module + tests, flag off. Run the autotest.
2. Enable on the test account (+skvext), then run the external-chat check through the public MCP.
3. Enable on the main account and run the migration (section 9).
4. Enable the L2 enforcement last, after a few L2 windows in warn-only mode ("would have rejected").
5. Cube v13 is published after step 4.
Rollback:
- Turn the flag off. Reads disappear and the fields are ignored. Tables stay, nothing is deleted.
- The cube can revert to v12. A DB backup is taken before the migration.

## 13. Open questions for Deniz
1. L2 enforcement: hard reject (revise) from day one, or a week of warn-only first?
2. Profile scope across agents: one profile for all AIs on the account (proposed), or allow per-agent overrides (scope agent:<name>)?
3. Should the user see/edit the profile on the site (profile.html page, author=user), now or later?

## 14. Decisions (Deniz, 2026-10-24) and implementation notes
Decisions on section 13:
1. profile_review: warn-only for the first **3 L2 submissions** of an account (not one week), then a hard reject (turn returns verdict=revise, no seal is burned).
2. One profile per account; no `agent:` scope.
3. No website UI for now (read via memory_dig `prof:` and the export endpoint).

Implementation deviations from sections 1–12:
- **Table names.** Account DBs already have a legacy `user_profile` table (memory_v2 windows), so the layer uses `profile_rows`, `profile_log`, `profile_duties`, `profile_state` (same columns as section 1). `profile_state` keeps per-account counters: turns since last profile op, L2 reviews seen/skipped, `l2_warned`.
- **Flag.** `profile_enabled` lives in `shared_master.db` table `profile_flags(user_id, enabled, updated_at)`, not in the account DB, because the smoke account DB is wiped every run. Not exposed over HTTP; set with `docker exec skv_api python -c "from app import profile; profile.set_flag(uid, True)"`. Rollback = set False (rows stay, ignored).
- **Code.** `src/app/profile.py` (validate / precheck / apply / duties / relevant / block / dig / export / import_ops). Hooks: `/remember` (precheck → revise, apply after save), `rest_turn.turn` and MCP `turn` (precheck *before* the seal is reserved, so a rejected turn burns no seal; `[PROFILE ✗]` mark appended to the seal when profile text is rejected softly), `step_zero_lite` + `/session/bootstrap` + MCP `step_zero` p1 (`profile` block ≤1.5 KB), `/memory/source` + memory_dig `prof:list|prof:history|prof:<id>`.
- **Endpoints:** `POST /api/v7/profile/precheck`, `GET /api/v7/profile/relevant`, `GET /api/v7/profile/block`, `GET /api/v7/profile/export`.
- **Cube text.** CUBE 05 MCP `cube_const_05_mcp_v13` and REST `cube_const_05_v13` add section "PROFILE". Guardian2 and `skv_protocol.AGENT_PROMPT` gained PROFILE / PROFILE_REVIEW service lines.
- **Migration.** Not run. `ops/profile_migrate.py` produces a dry-run JSON proposal from critical facts; `--apply` needs `--i-confirm` and Deniz's go.

### 14.1 Turn watch (MCP only, reminder-style)
- The MCP server keeps a tiny per-key state (`tw` table in the MCP compact DB): last turn time, last tool call, number of "answer bursts" (tool-call groups separated by >90 s, env `SKV_TURN_BURST_GAP_S`).
- Every SKV MCP tool response (except turn / constitution_* / step_zero / bootstrap / start) gets a short `turn_reminder` when the last turn is stale: >1 burst without a turn, or >10 min (env `SKV_TURN_STALE_MIN`). Text: "call turn; no seal without it".
- On `turn`, if bursts were missed since the previous turn, the response gets duty `missed_turns` asking for 1-line recaps of the missed answers (in the next turn's l1_summary / remember). No blocking.
- MCP instructions start with one line: "EVERY ANSWER: draft privately, then call turn … No turn = no seal."
- REST cannot see tool calls between turns, so REST has no turn watch.
