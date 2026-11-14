#!/bin/bash
# Restart skv_api only when nothing is in flight:
#  1) no /remember/batch or /import* requests in the API log for QUIET seconds;
#  2) in-process background jobs (GET /_ops/inflight inside the container) report busy=false.
# Also waits (up to CONSULT_MAX_WAIT, then proceeds) while a consult is running.
# Waits up to MAX_WAIT, then gives up (exit 2). Stop is graceful (SIGTERM, 60 s for in-flight requests).
QUIET=${QUIET:-90}; MAX_WAIT=${MAX_WAIT:-1800}; waited=0
log_busy() { docker logs --since ${QUIET}s skv_api 2>&1 | grep -E '"(POST|GET) /(api/v7/(remember/batch|import|agent/import)|import/)' | grep -q . ; }
jobs_busy() {
  out=$(docker exec skv_api python -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8000/_ops/inflight",timeout=5).read().decode())' 2>/dev/null)
  [ -z "$out" ] && { echo "inflight endpoint unavailable (old process?), relying on logs" >&2; return 1; }
  echo "$out" | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if any(k != "consult" for k in (d.get("jobs") or {})) else 1)   # consults: see consult_busy (bounded wait)' 2>/dev/null && { echo "background jobs: $out" >&2; return 0; }
  return 1
}
# T73: a consult (DeepSeek/Qwen, up to ~5 min) runs in an API thread: a restart kills it. Wait while any account has a consult_pool row
# status='running' younger than 10 min (checked inside the container: same clock as created_at). After CONSULT_MAX_WAIT we proceed anyway.
CONSULT_MAX_WAIT=${CONSULT_MAX_WAIT:-600}
consult_busy() {
  docker exec -i skv_api python - <<'PY' 2>/dev/null
import glob, sqlite3, sys, time
now, n = time.time(), 0
for p in glob.glob("/data/skv/metadata_store/*"):   # account DBs have no .db suffix
    if p.endswith(("-wal", "-shm", "-journal")):
        continue
    try:
        c = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=3)
        if c.execute("select 1 from sqlite_master where name='consult_pool'").fetchone():
            for (ts,) in c.execute("select created_at from consult_pool where status='running'"):
                try:
                    if 0 <= now - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S")) < 600:
                        n += 1
                except Exception:
                    pass
        c.close()
    except Exception:
        pass
sys.exit(0 if n else 1)
PY
  local rc=$?
  [ $rc = 0 ] && echo "consult running" >&2
  return $rc
}
consult_wait() { [ $waited -lt $CONSULT_MAX_WAIT ] && consult_busy; }
while log_busy || jobs_busy || consult_wait; do
  [ $waited -ge $MAX_WAIT ] && { echo "still busy after ${MAX_WAIT}s, not restarting"; exit 2; }
  echo "imports/jobs in flight, waiting..."; sleep 30; waited=$((waited+30))
done
docker restart -t 60 skv_api >/dev/null
for i in $(seq 1 30); do sleep 2; [ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/)" = 200 ] && { sleep 5; bash /root/skv-core/ops/install_mcp_nginx.sh 2>&1 | grep -E "changed|reload" ; [ ${PIPESTATUS[0]} = 0 ] && echo "mcp nginx checked" || echo "WARN mcp nginx re-apply failed"; echo "restarted ok"; exit 0; }; done
echo "api not healthy after restart"; exit 1
