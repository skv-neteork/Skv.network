#!/bin/bash
# Restart skv_api only when nothing is in flight:
#  1) no /remember/batch or /import* requests in the API log for QUIET seconds;
#  2) in-process background jobs (GET /_ops/inflight inside the container) report busy=false.
# Waits up to MAX_WAIT, then gives up (exit 2). Stop is graceful (SIGTERM, 60 s for in-flight requests).
QUIET=${QUIET:-90}; MAX_WAIT=${MAX_WAIT:-1800}; waited=0
log_busy() { docker logs --since ${QUIET}s skv_api 2>&1 | grep -E '"(POST|GET) /api/v7/(remember/batch|import|agent/import)' | grep -q . ; }
jobs_busy() {
  out=$(docker exec skv_api python -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8000/_ops/inflight",timeout=5).read().decode())' 2>/dev/null)
  [ -z "$out" ] && { echo "inflight endpoint unavailable (old process?), relying on logs" >&2; return 1; }
  echo "$out" | grep -q '"busy":true' && { echo "background jobs: $out" >&2; return 0; }
  return 1
}
while log_busy || jobs_busy; do
  [ $waited -ge $MAX_WAIT ] && { echo "still busy after ${MAX_WAIT}s, not restarting"; exit 2; }
  echo "imports/jobs in flight, waiting..."; sleep 30; waited=$((waited+30))
done
docker restart -t 60 skv_api >/dev/null
for i in $(seq 1 30); do sleep 2; [ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/)" = 200 ] && { echo "restarted ok"; exit 0; }; done
echo "api not healthy after restart"; exit 1
