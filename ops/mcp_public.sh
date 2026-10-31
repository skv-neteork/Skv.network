#!/usr/bin/env bash
# Public MCP now runs under systemd (skv-mcp-public.service, env /etc/skv/mcp_public.env, Restart=always).
# This script is kept as a shim: (re)start via systemd.
set -euo pipefail
systemctl restart skv-mcp-public
sleep 2; systemctl --no-pager -l status skv-mcp-public | head -5
