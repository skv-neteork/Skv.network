#!/usr/bin/env bash
# SKV smoke test (test/fresh accounts only). Run after every change: /root/skv-core/ops/smoke.sh
exec python3 "$(dirname "$0")/smoke.py" "$@"
