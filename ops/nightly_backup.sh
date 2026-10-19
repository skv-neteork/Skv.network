#!/bin/bash
# SKV nightly encrypted backup. Cron 03:30 MSK. Output: /root/skv_offsite/skv_YYYYmmdd_HHMM.tar.gz.gpg (keeps 3 locally)
# Vault master key (/root/skv_vault/master.key) is deliberately EXCLUDED.
set -euo pipefail
umask 077
OUT=/root/skv_offsite; PASS=/root/skv_backup_secret/passphrase
TS=$(date +%Y%m%d_%H%M); W=$(mktemp -d /root/.skvbk.XXXX); trap 'rm -rf "$W"' EXIT
mkdir -p "$OUT" "$W/sqlite" "$W/config"
python3 - "$W/sqlite" <<'PY'
import sqlite3,glob,os,sys,json
d=sys.argv[1]; m={}
for f in sorted(glob.glob('/data/skv/metadata_store/*.db')):
    s=sqlite3.connect(f'file:{f}?mode=ro',uri=True); t=sqlite3.connect(os.path.join(d,os.path.basename(f)))
    s.backup(t); t.close(); s.close(); m[os.path.basename(f)]=os.path.getsize(os.path.join(d,os.path.basename(f)))
json.dump(m,open(os.path.join(d,'MANIFEST.json'),'w'),indent=1)
PY
docker exec skv_postgres pg_dump -U skv_user -Fc skv_db > "$W/postgres_skv_db.dump"
cd /root/skv-core
find . -path ./.venv -prune -o -path ./archive -prune -o -path ./data -prune -o \( -name ".env*" -o -name "*.yml" -o -name "*.yaml" -o -name "Dockerfile" -o -name "requirements.txt" \) -type f -print | tar -cf "$W/config/skv-core-config.tar" -T -
git -C /root/skv-core rev-parse HEAD > "$W/config/git_head.txt"
crontab -l > "$W/config/crontab.txt"
[ -d /data/skv/hnsw ] && tar -cf "$W/hnsw.tar" -C /data/skv hnsw || true
echo "vault ciphertext is inside sqlite/shared_master.db; master.key NOT included" > "$W/README.txt"
tar -czf - -C "$W" . | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$PASS" --symmetric --cipher-algo AES256 -o "$OUT/skv_$TS.tar.gz.gpg"
sha256sum "$OUT/skv_$TS.tar.gz.gpg" | awk '{print $1}' > "$OUT/skv_$TS.sha256"
ls -1t "$OUT"/skv_*.gpg | tail -n +4 | while read f; do rm -f "$f" "${f%.tar.gz.gpg}.sha256"; done
echo "$TS ok $(du -h "$OUT/skv_$TS.tar.gz.gpg" | cut -f1)" >> /var/log/skv_backup.log
