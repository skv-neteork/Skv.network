#!/bin/sh
# Q2S rollback (2026-11-02). Usage:
#   /root/skv-core/rollback_q2s.sh off   -> instant: q2s=false in /data/skv/search_config.json (re-read on every search, no restart)
#   /root/skv-core/rollback_q2s.sh       -> full: flag off + remove the Q2S hooks from the 6 files + disable q2s.py + restart API and MCP
# Hooks are removed by reverse-applying /root/skv-core/q2s_patch.diff (keeps other people's later edits);
# if that does not apply cleanly, every touched file is restored from its *.bak.20261102q2s copy.
set -e
CFG=/data/skv/search_config.json
python3 - "$CFG" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["q2s"] = False; json.dump(d, open(p, "w"))
print("q2s flag off:", d)
PY
[ "$1" = "off" ] && exit 0
cd /root/skv-core
if patch -R -p0 --dry-run -s < q2s_patch.diff >/dev/null 2>&1; then
  patch -R -p0 -s --no-backup-if-mismatch < q2s_patch.diff && echo "hooks removed (reverse patch)"
else
  for b in $(find src mcp -name '*.bak.20261102q2s'); do f="${b%.bak.20261102q2s}"; cp -p "$b" "$f"; echo "restored $f from backup"; done
fi
[ -f src/app/q2s.py ] && mv src/app/q2s.py src/app/q2s.py.disabled.20261102q2s && echo "src/app/q2s.py -> q2s.py.disabled.20261102q2s"
docker restart skv_api >/dev/null && echo "skv_api restarted"
systemctl restart skv-mcp-public && echo "skv-mcp-public restarted"
echo "Q2S rolled back."
