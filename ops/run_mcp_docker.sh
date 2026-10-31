#!/usr/bin/env bash
# Multi-tenant SKV MCP container (self-contained pip). Network: skv-core_default.
set -euo pipefail
NAME=skv_mcp
ROOT=/root/skv-core
REQ="$ROOT/mcp/requirements.txt"
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --restart unless-stopped \
  --network skv-core_default \
  -e SKV_API_BASE=http://skv_api:8000/api/v7 \
  -e SKV_SITE=http://skv_api:8000 \
  -v "$ROOT/mcp:/mcp:ro" \
  -w /mcp \
  python:3.12-slim \
  bash -lc 'pip install -q -r /mcp/requirements.txt httpx "mcp[cli]" uvicorn starlette && python -u /mcp/mcp_skv.py --sse --host 0.0.0.0 --port 8765'
echo "started $NAME (pip on first boot may take ~30s)"
