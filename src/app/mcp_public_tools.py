"""Canonical public MCP tool names (38). Imported by the server card and mcp_skv.

Lives under src/app so the API container (which mounts only this tree) can list
the same tools as the MCP server without reading mcp/mcp_skv.py.
"""
VISIBLE = {
    "constitution_get", "turn", "step_zero", "constitution_status", "constitution_install", "memory_start", "memory_search",
    "cube_search", "cube_get", "cube_install", "cube_vote", "cube_create", "cube_confirm", "feedback_submit", "board_list", "board_act", "sandbox_run",
    "cube_consent", "court_case", "court_removal_request", "cube_link", "consult", "consult_accept", "vault_inject", "joint_project", "joint_search", "turn_stats", "memory_recall_later", "memory_recall_status",
    "identify", "file_claim", "file_check", "file_release",
    "drive_connect", "drive_sync", "drive_read", "drive_put", "drive_list",
}
