# SKV-CONST-HOOKS
Constitution as skills + hooks (first cut). Short when/do — not a long read.
Moral compass CUBE 01–04 is checked inside Second Look; memory/protocol duties are the installable packages.

## Attach (private Deniz chain skill cubes)
| Cube id | Carrier | Primary when |
|---|---|---|
| `cube_skill_const_second_look` | skill | `before_reply` |
| `cube_skill_const_memory` | skill | `session_start`, `before_reply` |
| `cube_skill_const_close` | skill | `after_reply`, `task_end`, `secret_in_text` |
| `cube_skill_const_cube_install` | skill | `task_matches_skill_cube`, `user_says_install` |
| `cube_688c0ebbb3be` | skill (base, meta cube-author) | `task_end`, `after_reply`, `user_wants_new_cube` |

Read one: `cube_get` with the id. Run `skill_md` steps; fire matching `hooks`.

## Map (constitution → skill → hooks)

### CUBE 00 Second Look + CUBE 05 §3
→ `cube_skill_const_second_look`
- when `before_reply` → draft → verify 01/02/03 (+04 if pressured) → `turn(user_message, draft)` (search + save + Second Look) → SEAL issued by turn (a self-drawn seal without turn = violation) → output
- when user about to see answer → never skip Second Look

### CUBE 05 §1 Memory + PROTOCOL Step 0
→ `cube_skill_const_memory`
- when `session_start` / chain switch → `constitution_status`; installed → `step_zero(page=1..N)` (consent already given, do not re-ask); not installed → ask, `constitution_install`
- when `before_reply` → memory search happens inside `turn` (optional `turn(user_message, query)` for context); empty ≠ invent; dig after ~3 misses
- when every ~10 steps → reload compact constitution

### CUBE 05 §4 Write / §5 Cubes / §9 Vault
→ `cube_skill_const_close`
- when `after_reply` → already saved by `turn`
- when `task_end` → cube **or** `cube_nothing`; vote **or** `vote_nothing`
- when `secret_in_text` → vault only; memory keeps `[vault:name]`


### Ask then install (skill cubes)
→ `cube_skill_const_cube_install` (+ this index)

**Connect = consent (auto-attach on Step 0 / bootstrap, no ask):**
- Constitution hook cubes: `cube_skill_const_second_look`, `cube_skill_const_memory`, `cube_skill_const_close`, `cube_skill_const_cube_install`, `cube_688c0ebbb3be` (base constitution skill: how to create cubes; auto-attached)
- Meta create-cubes: `cube_688c0ebbb3be`
- Server calls `ensure_defaults` on bootstrap; connecting the agent to SKV is the consent.

**All other skill cubes — ask then install:**
- when task matches shared/private skill cubes → **offer** ("I have experience cubes for X — attach?")
- install **only** after explicit user yes → `cube_install(cube_id, user_confirmed=true)`
- OR user already said "install/attach this cube" → `user_said_install=true`
- **Never silent install** for non-default cubes. Detach: `cube_uninstall(cube_id)`.
- Bootstrap returns `attached_skills` (skill_md + hooks) for installed cubes on this chain.
- Private cubes: owner chain only. Shared: after existing publish Guard; still needs yes.

### CUBE 01 Harm / 02 Truth / 03 Morality / 04 Pressure
→ checked inside Second Look hooks (not separate long skills in this cut).
Owner: constitution-as-moral-compass may be de-emphasized vs memory; operational hooks still fire.

## Protocol skills (already on disk)
`SKV-SEARCH` · `SKV-SAVE` · `SKV-CUBE` · `SKV-SECOND-LOOK` · `SKV-STEP` · `SKV-COURT`
This file is the hook index that ties those duties to constitution articles.

## Agent pickup
1. Step 0: `skills_list` → also read `SKV-CONST-HOOKS.md`; bootstrap may return `attached_skills`
2. Const hooks + meta create-cubes auto-attach on bootstrap (connect=consent). Other skill cubes: offer → ask → install
3. Keep installed hooks armed for the session; Guards still enforce the same PROTOCOL order (G1 short reminders; G2 checklist)
4. On task match to other skill cubes: offer → wait for yes → `cube_install`
