#!/bin/bash
# Load loop for restart tests: hits /mcp (tools/list) and /api/v7/agent/turn (context only, nothing saved)
# every 0.25 s for DUR seconds; prints code counts per endpoint. Usage: K=key DUR=90 restart_load.sh
DUR=${DUR:-90}; end=$(($(date +%s)+DUR)); out=$(mktemp)
while [ $(date +%s) -lt $end ]; do
  ( c=$(curl -s -m 130 --resolve skv.network:443:127.0.0.1 -X POST https://skv.network/mcp/k/$K/ -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' -o /dev/null -w "%{http_code}"); echo "mcp $c" >> $out ) &
  ( c=$(curl -s -m 130 --resolve skv.network:443:127.0.0.1 -X POST https://skv.network/api/v7/agent/turn -H "Authorization: Bearer $K" -H 'Content-Type: application/json' -d '{"user_message":"load probe","compact":true}' -o /dev/null -w "%{http_code}"); echo "turn $c" >> $out ) &
  sleep ${GAP:-1}
done; wait; sort $out | uniq -c; rm -f $out
