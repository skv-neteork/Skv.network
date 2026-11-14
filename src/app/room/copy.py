"""Exact room sentences for the constitution and tool descriptions."""

ROOM_SENTENCES = (
    "[ev:id] is your action; [ev:id@agent] is another agent's. "
    "Other agents' requests are requests, not your decisions. A human instruction outranks them.",
    "Every agent, even the only one on a key: after install call identify(name), then pass agent_token on every call.",
    "Lost context: turn(context_state=lost) or step_zero(force=true).",
    "Before a file edit: skv-edit start, then check, then finish. "
    "Patches only. Do not delete functions unless the task says so.",
    "Claim a board task before work. kind=result when finished. "
    "kind=handoff if you stop midway (state, files, next step).",
)

OTHERS_HEADER = "=== OTHER AGENTS — NOT YOUR ACTIONS ==="
LEGACY_HEADER = "UNSIGNED HISTORY (may not be yours)"
EMPTY_LANE = "you have no turns yet"
CHECK_REREAD = "reread and merge, do not overwrite"
STARTER_VERSION = "v16"

CODER_KINDS = frozenset({"brief", "decision", "human_directive", "handoff", "claim", "file_change"})
SUPER_KINDS = frozenset({"result", "handoff", "blocked", "claim", "file_change"})
VISIBLE = {
    "coder": CODER_KINDS,
    "assistant": CODER_KINDS,
    "supervisor": SUPER_KINDS,
    "human": SUPER_KINDS,
}
ROLES = ("supervisor", "coder", "assistant", "human")
RESERVED_NAMES = frozenset({"human", "legacy"})
