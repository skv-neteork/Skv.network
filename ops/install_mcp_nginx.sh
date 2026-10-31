#!/usr/bin/env bash
# Install the /mcp/ route + restart hold as nginx-proxy vhost.d/skv.network (included by the template, survives regeneration).
# Reloads nginx ONLY when the rendered vhost or the regenerated default.conf actually changed (FORCE=1 to always reload).
set -euo pipefail
GW=$(docker network inspect skv-core_default --format '{{(index .IPAM.Config 0).Gateway}}')
NEW=$(sed "s/__GW__/${GW}/g" /root/skv-core/ops/nginx_vhost_skv.network.tmpl)
OLD=$(docker exec nginx-proxy sh -c 'cat /etc/nginx/vhost.d/skv.network 2>/dev/null' || true)
CHG=0
if [ "$NEW" != "$OLD" ]; then
  docker exec nginx-proxy mkdir -p /etc/nginx/vhost.d
  printf '%s\n' "$NEW" | docker exec -i nginx-proxy sh -c 'cat > /etc/nginx/vhost.d/skv.network'; CHG=1; echo "vhost changed"
fi
# default.conf is owned by nginx-proxy's own docker-gen (it regenerates on container events).
# Regenerate it here only if it lost the vhost.d include (a one-shot docker-gen differs slightly, e.g. resolver line,
# so regenerating every time would flip-flop the config and force a reload on every restart).
if ! docker exec nginx-proxy grep -q "include /etc/nginx/vhost.d/skv.network" /etc/nginx/conf.d/default.conf; then
  docker exec nginx-proxy sh -c 'cp /etc/nginx/conf.d/default.conf /tmp/default.conf.prev; docker-gen /app/nginx.tmpl /etc/nginx/conf.d/default.conf' >/dev/null 2>&1 || true
  CHG=1; echo "default.conf regenerated (vhost include was missing)"
fi
if [ "$CHG" = 1 ] || [ "${FORCE:-0}" = 1 ]; then
  if ! docker exec nginx-proxy nginx -t 2>&1; then
    echo "nginx -t FAILED, restoring previous config"
    printf '%s\n' "$OLD" | docker exec -i nginx-proxy sh -c 'cat > /etc/nginx/vhost.d/skv.network'
    docker exec nginx-proxy sh -c 'test -f /tmp/default.conf.prev && cp /tmp/default.conf.prev /etc/nginx/conf.d/default.conf' || true
    exit 1
  fi
  docker exec nginx-proxy nginx -s reload; sleep 1; echo "nginx reloaded"
else
  echo "nginx config unchanged: no reload"
fi
KC=$(curl -s -m 15 -o /dev/null -w %{http_code} --resolve skv.network:443:127.0.0.1 https://skv.network/mcp/k/sk_routecheck000000/ || true)
echo "MCP nginx OK -> ${GW}:8765 via vhost.d (bad-key check: ${KC}, expect 401)"
