#!/usr/bin/env bash
# B20: nginx must close idle upstream connections before uvicorn does.
# uvicorn timeout_keep_alive is 75s (app/keepalive_align.py, deploy/skv_api.run.sh).
# upstream keepalive_timeout is 60s and the pool is 32. Idempotent.
# Reloads nginx only when this run changes the live config.
set -euo pipefail
FLAG=/tmp/b20_nginx_changed
python3 - <<'PY'
import subprocess, sys
MARK = "B20 upstream keepalive"
OLD = """        {{- if eq $keepalive "auto" }}
    keepalive {{ mul $servers 2 }};
        {{- else }}
    keepalive {{ $keepalive }};
        {{- end }}
    {{- end }}
"""
NEW = """        {{- if eq $keepalive "auto" }}
    keepalive {{ mul $servers 32 }};
        {{- else }}
    keepalive {{ $keepalive }};
        {{- end }}
    # B20 upstream keepalive: nginx closes idle conns before uvicorn (75s)
    keepalive_timeout 60s;
    keepalive_requests 1000;
    {{- end }}
"""

def run(args, data=None):
    return subprocess.run(args, input=data, text=True, capture_output=True)

changed = False
tmpl = run(["docker", "exec", "nginx-proxy", "cat", "/app/nginx.tmpl"])
if tmpl.returncode != 0:
    sys.stderr.write(tmpl.stderr)
    sys.exit(1)
body = tmpl.stdout
if MARK not in body:
    if OLD not in body:
        sys.stderr.write("nginx.tmpl upstream keepalive block not found\n")
        sys.exit(1)
    body = body.replace(OLD, NEW, 1)
    put = run(["docker", "exec", "-i", "nginx-proxy", "sh", "-c", "cat > /app/nginx.tmpl"], body)
    if put.returncode != 0:
        sys.stderr.write(put.stderr)
        sys.exit(1)
    changed = True
    print("template patched")
else:
    print("template already patched")

conf_path = "/etc/nginx/conf.d/default.conf"
conf = open(conf_path).read()
if MARK not in conf:
    needle = "    keepalive 2;\n"
    if needle not in conf:
        sys.stderr.write("default.conf has no keepalive 2 upstream line\n")
        sys.exit(1)
    insert = (
        "    keepalive 32;\n"
        "    # B20 upstream keepalive: nginx closes idle conns before uvicorn (75s)\n"
        "    keepalive_timeout 60s;\n"
        "    keepalive_requests 1000;\n"
    )
    open(conf_path, "w").write(conf.replace(needle, insert, 1))
    changed = True
    print("default.conf patched")
else:
    print("default.conf already patched")
open("/tmp/b20_nginx_changed", "w").write("1" if changed else "0")
PY
if [ "$(cat "$FLAG")" = "1" ]; then
  if ! docker exec nginx-proxy nginx -t; then
    echo "nginx -t FAILED" >&2
    exit 1
  fi
  docker exec nginx-proxy nginx -s reload
  echo "nginx reloaded"
else
  echo "nginx upstream keepalive already aligned"
fi
docker exec nginx-proxy sh -c 'nginx -T 2>/dev/null | awk "/upstream skv.network \\{/,/^}/"'
