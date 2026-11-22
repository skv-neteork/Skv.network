"""Canonical public MCP tool list (39).

Imported by the server card and by mcp/mcp_skv.py. Lives under src/app so the
API container (which mounts only this tree) can describe the same tools as the
MCP server without reading mcp/mcp_skv.py.

SHORT is the tools/list sentence before the Suggest-when clause and the
constitution tag. META is the human title and the four annotation hints.
"""

VISIBLE = {
    "constitution_get", "turn", "step_zero", "constitution_status", "constitution_install", "memory_start", "memory_search",
    "cube_search", "cube_get", "cube_install", "cube_vote", "cube_create", "cube_confirm", "feedback_submit", "board_list", "board_act", "sandbox_run",
    "cube_consent", "court_case", "court_removal_request", "cube_link", "consult", "consult_accept", "vault_inject", "joint_project", "joint_search", "turn_stats", "memory_recall_later", "memory_recall_status",
    "identify", "file_claim", "file_check", "file_release",
    "drive_connect", "drive_sync", "drive_read", "drive_put", "drive_list",
    "memory_import_text",
}

# Appended to turn only when the constitution binding is loaded.
TURN_HEARTBEAT = " Constitution heartbeat: const_ack=true on constitution_manifest."

# tools/list copy. Start-order tools must contain "step_zero" and no Cyrillic.
SHORT = {
    "turn": "Call before every reply; end with the seal. compact=true, msg_ref, agent_token, recap.",
    "memory_search": "Search the event, not the question. Dates are MSK. date=YYYY-MM-DD is that day ±1. since/until=YYYY-MM-DD is that exact MSK day. Example: since=2026-11-21 until=2026-11-21.",
    "memory_start": "Start order: constitution_install, identify, step_zero, then turn.",
    "memory_recall_later": "If memory_search missed, poll memory_recall_status. Dates are MSK. date=YYYY-MM-DD is that day ±1. since/until is the exact MSK day. Example: since=2026-11-21 until=2026-11-21.",
    "memory_recall_status": "Poll recall job; evidence, not an answer.",
    "turn_stats": "Turn size and second_look stats.",
    "step_zero": "Read step_zero pages until done=true, then turn only.",
    "constitution_get": "Re-read constitution, paged.",
    "constitution_install": "Install only after the user says yes; then identify, then step_zero.",
    "constitution_status": "If installed: identify, step_zero once, then turn.",
    "cube_get": "Read one cube by id. Long skill_md is paged: page=1 through skill_pages. skill_md is never trimmed.",
    "sandbox_run": "Run python/pytest/node sandboxed (no net).",
    "cube_search": "Search shared cubes (latest versions).",
    "cube_create": "Cube at task end, or duty=cube_nothing.",
    "cube_confirm": "One confirmation per account per cube version: outcome ok, partial, or fail, plus evidence. A repeat from the same account keeps the first vote.",
    "cube_vote": "Vote +1/-1 on a used cube; -1 needs reason.",
    "cube_install": "Install a cube after the user's yes.",
    "court_case": "Court case; fix_id=0 lists pending.",
    "court_removal_request": "Ask court to remove a published cube.",
    "cube_consent": "Publish consent. action=status reads it; action=notice_shown records that the notice was shown. Publish only when status=allowed.",
    "cube_link": "Link two cubes (progress|next|from|against).",
    "feedback_submit": "Feedback or bug on SKV or a cube.",
    "board_list": "List board items; optional status/history.",
    "board_act": "Board add/start/done/claim/release. remove drops an item.",
    "identify": "Name this agent and return agent_token, then call step_zero. The same name is one actor. A later call rotates that token.",
    "file_claim": "Claim a path before editing (409 if held).",
    "file_release": "Release a file claim and record the change for the other agents.",
    "file_check": "Check a claimed file still matches base_hash. Does not write.",
    "drive_connect": "Start Google Drive connect. With no code, returns auth_url. Never returns the token.",
    "drive_sync": "Scan this memory line's Drive folder. Updates the local index. Does not trash Drive files.",
    "drive_read": "Read a Drive file on this line. Large files return one part and next.",
    "drive_put": "Store a file. Over 1 MB creates a new file in this line's Drive folder. It does not replace an existing file id.",
    "drive_list": "List Drive files on this memory line: name, size, description, status.",
    "consult": "Paid second opinion after the user says yes. Not a silent read.",
    "consult_accept": "Keep one consult answer in memory, or return a cube draft.",
    "joint_project": "Joint project memory for 2-5 people. Includes revoke and close.",
    "joint_search": "Search joint-project memory; cite [pj:id].",
    "vault_inject": "Send an HTTPS request with a vault secret substituted into the url or body. The caller chooses the URL and the method. The secret is never returned.",
    "memory_import_text": "Import pasted chat text into this account. Secrets route to the vault.",
}

# title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint
# Disagreements with the proposal are noted in the report:
# step_zero writes session rows, so it is not read-only.
# identify rotates the agent token, so a repeat is destructive.
# vault_inject can DELETE an arbitrary allowed HTTPS host, so it is open-world and destructive.
# drive_put creates a new Drive file and does not replace an existing id.
# file_check only compares a hash.
# cube_confirm keeps the first vote, so a repeat is idempotent.
# cube_consent can record notice_shown, so the tool is not read-only.
META = {
    "board_act": ("Update task board", False, True, False, False),
    "board_list": ("List task board", True, False, True, False),
    "constitution_get": ("Read constitution", True, False, True, False),
    "constitution_install": ("Install constitution", False, False, False, False),
    "constitution_status": ("Constitution status", True, False, True, False),
    "consult": ("Ask a second-opinion model", False, False, False, False),
    "consult_accept": ("Keep a consult answer", False, False, False, False),
    "court_case": ("Read a court case", True, False, True, False),
    "court_removal_request": ("Request cube removal", False, True, False, False),
    "cube_confirm": ("Confirm a cube action", False, False, True, False),
    "cube_consent": ("Cube publish consent", False, False, False, False),
    "cube_create": ("Create experience cube", False, False, False, False),
    "cube_get": ("Get a cube", True, False, True, False),
    "cube_install": ("Install a cube", False, False, False, False),
    "cube_link": ("Link two cubes", False, False, False, False),
    "cube_search": ("Search cubes", True, False, True, False),
    "cube_vote": ("Vote on a cube", False, False, False, False),
    "drive_connect": ("Connect a drive", False, False, False, False),
    "drive_list": ("List drive files", True, False, True, False),
    "drive_put": ("Write a drive file", False, False, False, False),
    "drive_read": ("Read a drive file", True, False, True, False),
    "drive_sync": ("Sync drive", False, False, False, False),
    "feedback_submit": ("Submit feedback", False, False, False, False),
    "file_check": ("Check a file", True, False, True, False),
    "file_claim": ("Claim a file", False, False, False, False),
    "file_release": ("Release a file claim", False, True, False, False),
    "identify": ("Identify this agent", False, True, False, False),
    "joint_project": ("Manage a joint project", False, True, False, False),
    "joint_search": ("Search joint project memory", True, False, True, False),
    "memory_import_text": ("Import text into memory", False, False, False, False),
    "memory_recall_later": ("Schedule a later recall", False, False, False, False),
    "memory_recall_status": ("Recall schedule status", True, False, True, False),
    "memory_search": ("Search memory", True, False, True, False),
    "memory_start": ("Start before constitution", True, False, True, False),
    "sandbox_run": ("Run code in the sandbox", False, True, False, False),
    "step_zero": ("Load step zero pages", False, False, False, False),
    "turn": ("Save turn and check draft", False, False, False, False),
    "turn_stats": ("Turn statistics", True, False, True, False),
    "vault_inject": ("Use a vault secret in a request", False, True, False, True),
}


def annotations(name):
    """Hint object for one public tool. Title is repeated here and on the tool."""
    title, read_only, destructive, idempotent, open_world = META[name]
    return {
        "title": title,
        "readOnlyHint": bool(read_only),
        "destructiveHint": bool(destructive),
        "idempotentHint": bool(idempotent),
        "openWorldHint": bool(open_world),
    }


def public_description(name, heartbeat=False, suggest="", tag=""):
    """Same sentence tools/list shows: short copy, optional heartbeat, suggest, tag."""
    text = SHORT[name]
    if name == "turn" and heartbeat and TURN_HEARTBEAT.strip() not in text:
        text += TURN_HEARTBEAT
    hint = (suggest or "").strip()
    if hint and hint not in text:
        text = (text.rstrip() + " " + hint).strip()
    mark = (tag or "").strip()
    if mark and mark not in text:
        text = (text.rstrip() + " " + mark).strip()
    return text


def overlay_tool(item, name, heartbeat=False, suggest="", tag=""):
    """Copy a card/tool object and set the shared title, description, and annotations."""
    out = dict(item or {})
    out["name"] = name
    out["title"] = META[name][0]
    out["description"] = public_description(name, heartbeat=heartbeat, suggest=suggest, tag=tag)
    out["annotations"] = annotations(name)
    if not isinstance(out.get("inputSchema"), dict):
        out["inputSchema"] = {"type": "object"}
    return out
