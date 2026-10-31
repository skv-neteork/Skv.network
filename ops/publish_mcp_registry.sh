#!/bin/bash
# Re-publish server.json to the official MCP Registry (namespace network.skv, HTTP auth).
# Proof record: https://skv.network/.well-known/mcp-registry-auth (public key only).
# Private key lives on the server only: /data/skv/mcp_registry_ed25519.pem (never commit it).
# Bump "version" in server.json first; the registry rejects re-publishing the same version.
set -euo pipefail
cd "$(dirname "$0")/.."
K=/data/skv/mcp_registry_ed25519.pem
PK=$(openssl pkey -in "$K" -noout -text | grep -A3 "priv:" | tail -n +2 | tr -d " :\n")
mcp-publisher login http --domain skv.network --private-key "$PK" >/dev/null
mcp-publisher publish
rm -f ~/.mcp_publisher_token
