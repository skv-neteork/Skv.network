# T84 staged profile and constitution change

APPLY-ONLY-AFTER-DENIZ-OK.

This file is a proposal. It does not change the live constitution, the live profile, or `src/app/const_bind.py`.

## Current R05m

The live bind in `src/app/const_bind.py` is the short tag agents are labelled with. `cube_const_00_v6` `rules_markdown` is the protocol (DRAFT / VERIFY / SEAL). It has no R05m heading. The card tag is `[C v5.b7dd8f:H,R02,R05m]`.

Current tuple:

```
("R05m", "search memory before answering; empty hits is not a fact", "search memory first", r"MEMORY:")
```

## Current profile rule p_0c54dd61

kind=rule. Live text, not edited:

```
Каждый агент вызывает turn на каждое сообщение пользователя первым шагом вместе с первым ответом, даже коротким; печать в конце ответа — видимая проверка.
```

## Proposed replacement (both)

Apply this sentence to constitution R05m and replace profile rule `p_0c54dd61` with the same sentence, only after Deniz says ok:

```
Agent may send a short ack, then calls turn (new user message + previous answer), builds the answer from turn's result; if weak, deferred search catches up in 1-2 turns and the agent self-corrects.
```

Do not write this into the constitution cube or into `profile_rows` from this task.
