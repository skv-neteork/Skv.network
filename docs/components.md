# SKV components

A component is a small brain with a fixed interface. The turn calls it and
does not wait on a model. Another area (board, profile, memory) can register
the same way later.

## Interface

- `name` — short id
- `version` — string
- `enabled()` — kill switch. False means the turn skips the component.
- `trigger(state) -> bool` — whether this turn should start work
- `run(state)` — start the work. It must return without waiting on a model.
- `outputs(user)` — items ready for a later turn

`state` carries the account, the last session messages, a seen-set, and
whether a new L1 just landed. `outputs` items are `{date, ev, text, why}`
with `text` capped.

Register with `app.components.registry.register`. Importing
`app.components` registers the built-in recall component.

## recall (version 2)

Safety net for when the agent did not search. It queues one `recall_later`
job (planner, search, substrate). It does not keep its own search path.

- Flag: `SKV_RECALL_COMPONENT=0` turns it off. Default on.
- Trigger: every `SKV_RECALL_COMPONENT_EVERY` turns (default 5), a topic
  change, or a new L1. Skipped when this turn already carries a tool duty
  or the agent queued `memory_recall_later` itself.
- Caps: `SKV_RECALL_JOB_CAP` per job and `SKV_RECALL_DAY_CAP` per account
  per day. Over the cap, the turn is unchanged and a skip counter increments.
- The next turn delivers at most two lines in `recalled`, including compact.
  An event already delivered, or one from the current session window, is dropped.
- A failure is logged and does not fail the turn.

The keyword sidecar (`spontaneous_recall`) runs only when this component is off.

The tool map is not a shared-pool cube. `step_zero` has no account id on the page picker, so the map is attached on the turn, once per text hash. A later hash is delivered again. The same turn carries at most one tool duty when a past-work question is not already answered by the fast facts.

## Retrospective (not built)

A later component could fire when a task ends, read that session, and emit
one lesson line the agent may turn into a cube. It is not implemented here.
The agent still writes the lesson, or sends `duty=cube_nothing` with a reason.
