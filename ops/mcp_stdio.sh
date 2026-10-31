#!/usr/bin/env bash
# SKV MCP over stdio (Cursor / Claude Desktop on the server).
set -euo pipefail
ROOT=/root/skv-core
export SKV_API_BASE="${SKV_API_BASE:-http://127.0.0.1:8000/api/v7}"
export SKV_SITE="${SKV_SITE:-http://127.0.0.1:8000}"
if [[ -z "${SKV_API_KEY:-}" ]]; then
  echo "SKV_API_KEY required" >&2
  exit 2
fi
exec "$ROOT/runtime/mcp_venv/bin/python" -u "$ROOT/mcp/mcp_skv.py" --stdio
