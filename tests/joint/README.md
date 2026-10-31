# Joint projects, consult and Guard 2 API checks (2026-10-31)
Run on the server. They read test-account keys from `/data/skv/.jp_test_keys.json` (not in git) and print no keys.
- `e2e_joint.py`: REST end to end for /api/v7/joint/* (run inside skv_api: `docker exec -i skv_api python3 - < e2e_joint.py`).
- `mcp_joint.py`: MCP tools joint_project / joint_search / consult against the public MCP on 127.0.0.1:8765 (mcp venv).
- `ext_api_check.py`: the v7 endpoints the Chrome extension uses (inside skv_api).
