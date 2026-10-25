# SKV-CUBE
One shelf. Two jobs (same cube object).
1. Answer cube (`carrier=answer`, default): changes what the agent says. Kinds: moment / fact / culture / lifehack / warning / code.
2. Skill cube (`carrier=skill`): installable skill + hooks the agent plugs in (Instagram, realtor persona, later robotics with `carrier=robotics`).

Moment lines: obvious / miss / instead / check.
Culture is the cover. Moments link to it. Search returns culture, then moments.
If it does not change the answer and is not a real skill package, write nothing.

## Skill cubes (same create path)
Fields on the same experience cube:
- `skill_md` — SKILL.md-style instructions the agent runs (markdown; thin pass = no scripts).
- `hooks` — when to fire: JSON list of strings or `{when, do}` objects.
- `carrier` — `answer` | `skill` | `robotics`. Auto `skill` if skill_md/hooks set.

Create:
- MCP `cube_create(topic, essence, rules, skill_md=..., hooks=..., carrier="skill", cube_publish=true)`
- HTTP `POST /api/v7/experience/create` with the same fields
- or (legacy, unlisted) `memory_remember` with `cube_*` fields

Shared by default (`cube_publish=true`): English, no secrets (Guard checks skill_md + hooks too). Default SHARED (owner: cubes are always shared); cube_publish=false only for explicit private.
Give `essence` yourself, never the user's question.

## Install (skill carrier)
- **Connect = consent:** const hooks (`cube_skill_const_*`) + meta create-cubes (`cube_688c0ebbb3be`) auto-attach on bootstrap.
- **All other skill cubes:** offer first ("I have experience cubes for X — attach?"). `cube_install(..., user_confirmed=true)` only after yes, or `user_said_install=true` if user already said install/attach.
- Never silent install for non-default cubes. `cube_uninstall` to detach. Bootstrap `attached_skills` = installed on this chain.

### Suggested cubes (in search)
- `turn` (context mode), `memory_search`, `cube_search` may return `suggested_cubes.items` (only on strong topic match; no repeats per session).
- Plain cube → use it in the answer if it fits. Skill cube (`has_skill`) → offer install; `cube_install` only after user yes.
- `rate_this` → after use, `cube_vote` +1/-1. Wrong or outdated → `cube_vote` with `reason` + `fix_rules`/`fix_essence`/`fix_skill_md`/`fix_hooks`: judges decide; old version is kept.
