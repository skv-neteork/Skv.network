#!/bin/bash
# Restart skv_api only when no import/batch traffic is in flight.
# Waits until the API log shows no /remember/batch, /import/* or /remember calls for QUIET seconds (max MAX_WAIT), then stops gracefully.
QUIET=${QUIET:-90}; MAX_WAIT=${MAX_WAIT:-1800}; waited=0
busy() { docker logs --since ${QUIET}s skv_api 2>&1 | grep -E '"(POST|GET) /api/v7/(remember/batch|import/|agent/import|import)' | grep -q . ; }
while busy; do
  [ $waited -ge $MAX_WAIT ] && { echo "still busy after ${MAX_WAIT}s, not restarting"; exit 2; }
  echo "imports in flight, waiting..."; sleep 30; waited=$((waited+30))
done
docker restart -t 60 skv_api >/dev/null   # SIGTERM: uvicorn finishes in-flight requests up to 60s
for i in $(seq 1 30); do sleep 2; [ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/)" = 200 ] && { echo "restarted ok"; exit 0; }; done
echo "api not healthy after restart"; exit 1
