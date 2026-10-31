#!/usr/bin/env bash
# SKV MCP over SSE on localhost. Tunnel: ssh -L 8765:127.0.0.1:8765 root@SERVER
set -euo pipefail
ROOT=/root/skv-core
export SKV_API_BASE="${SKV_API_BASE:-http://127.0.0.1:8000/api/v7}"
export FASTMCP_HOST="${SKV_MCP_HOST:-127.0.0.1}"
export FASTMCP_PORT="${SKV_MCP_PORT:-8765}"
export HOST="$FASTMCP_HOST"
export PORT="$FASTMCP_PORT"
if [[ -z "${SKV_API_KEY:-}" ]]; then
  echo "SKV_API_KEY required" >&2
  exit 2
fi
exec "$ROOT/runtime/mcp_venv/bin/python" -u "$ROOT/mcp/mcp_skv.py" --sse --host "$FASTMCP_HOST" --port "$FASTMCP_PORT"
