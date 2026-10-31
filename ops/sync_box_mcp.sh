#!/usr/bin/env bash
# Keep box copy /home/box/skv-mcp/mcp_skv.py == server /root/skv-core/mcp/mcp_skv.py (server = source of truth).
# Run ON THE BOX: ./sync_box_mcp.sh [--check]   (needs /workspace/ssh.py + SKV_SSH_PASS)
# --check: only compare md5, exit 1 on mismatch. Default: pull server copy if different (old box copy kept as .prev).
set -euo pipefail
BOX=/home/box/skv-mcp/mcp_skv.py; SRV=/root/skv-core/mcp/mcp_skv.py
S=$(echo "md5sum $SRV | cut -d' ' -f1" | python3 /workspace/ssh.py | head -1)
B=$(md5sum "$BOX" | cut -d' ' -f1)
echo "server=$S box=$B"
[[ "$S" == "$B" ]] && { echo "IN SYNC"; exit 0; }
[[ "${1:-}" == "--check" ]] && { echo "MISMATCH"; exit 1; }
cp "$BOX" "$BOX.prev"
echo "base64 -w0 $SRV" | python3 /workspace/ssh.py | head -1 | base64 -d > "$BOX.new"
[[ "$(md5sum "$BOX.new" | cut -d' ' -f1)" == "$S" ]] || { echo "download corrupt"; rm -f "$BOX.new"; exit 2; }
mv "$BOX.new" "$BOX"; echo "SYNCED -> restart the stdio connector (RestartMcpServers) to load it"
