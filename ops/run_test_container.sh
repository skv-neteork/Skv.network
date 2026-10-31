#!/bin/sh
# Run a TEST container with hard memory limits so it can never exhaust server RAM.
# Usage: ops/run_test_container.sh <name> [extra docker run args...] <image> [cmd...]
# Production (skv_api, nginx-proxy, skv_postgres) must NOT be launched via this script.
name="$1"; shift
case "$name" in skv_api|nginx-proxy|skv_postgres) echo "refusing: production name" >&2; exit 1;; esac
exec docker run -d --name "$name" --memory=1g --memory-swap=1g --restart=no --oom-score-adj=500 "$@"
