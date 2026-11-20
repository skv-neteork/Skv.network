#!/bin/bash
# B15: copy the newest nightly encrypted backup onto Google Drive.
# Cron 04:00 MSK, 30 minutes after ops/nightly_backup.sh (03:30 MSK).
# Remote "gdrive" is /root/.config/rclone/rclone.conf (mode 600), placed by Grok Bot.
# This script never prints that file or its tokens.
# Seven weekday slots in gdrive:"SKV backups":
#   skv_<mon|tue|wed|thu|fri|sat|sun>.tar.gz.gpg
#   skv_<day>.sha256   (sha256 line names the original dated archive)
# rclone copyto overwrites the same slot. Size is checked with rclone lsjson.
# On failure, ops/deadman.py --drive sends one alert mail per incident.
set -euo pipefail
umask 077

LOG="${SKV_OFFSITE_DRIVE_LOG:-/var/log/skv_offsite_drive.log}"
CONF="${RCLONE_CONFIG:-/root/.config/rclone/rclone.conf}"
SRC="${SKV_OFFSITE_DIR:-/root/skv_offsite}"
REMOTE="${SKV_DRIVE_REMOTE:-gdrive:SKV backups}"
DEADMAN="${SKV_DEADMAN:-/root/skv-core/ops/deadman.py}"
DATE="${SKV_OFFSITE_DATE:-$(date +%Y-%m-%d)}"

if [ -n "${RCLONE_BIN:-}" ]; then
  RCLONE="$RCLONE_BIN"
elif [ -x /usr/bin/rclone ]; then
  RCLONE=/usr/bin/rclone
else
  RCLONE=rclone
fi

if [ -n "${SKV_OFFSITE_DRIVE_DETAIL:-}" ]; then
  DETAIL="$SKV_OFFSITE_DRIVE_DETAIL"
elif [ "$LOG" = "/var/log/skv_offsite_drive.log" ]; then
  DETAIL=/var/log/skv_offsite_drive.rclone.log
else
  DETAIL="${LOG}.rclone"
fi

if [ -n "${SKV_DEADMAN_LOG:-}" ]; then
  ALERT_LOG="$SKV_DEADMAN_LOG"
elif [ "$LOG" = "/var/log/skv_offsite_drive.log" ]; then
  ALERT_LOG=/var/log/skv_deadman.log
else
  ALERT_LOG="${LOG}.alert"
fi

if [ -n "${SKV_OFFSITE_SLOT:-}" ]; then
  DAY="$SKV_OFFSITE_SLOT"
else
  case "$(date +%u)" in
    1) DAY=mon;;
    2) DAY=tue;;
    3) DAY=wed;;
    4) DAY=thu;;
    5) DAY=fri;;
    6) DAY=sat;;
    7) DAY=sun;;
    *) DAY=mon;;
  esac
fi

mkdir -p "$(dirname "$LOG")" "$(dirname "$DETAIL")" "$(dirname "$ALERT_LOG")"
touch "$LOG" "$DETAIL" "$ALERT_LOG"
chmod 600 "$LOG" "$DETAIL" "$ALERT_LOG" 2>/dev/null || true

alert() {
  python3 "$DEADMAN" --drive >>"$ALERT_LOG" 2>&1 || true
}

note_fail() {
  local reason="$1"
  if [ "$reason" = "no rclone conf" ]; then
    echo "fail: no rclone conf" >>"$LOG"
  else
    echo "fail $DATE $DAY ${FILE_BASE:-none} ${FILE_SIZE:-0} $reason" >>"$LOG"
  fi
  alert
  exit 1
}

case "$DAY" in
  mon|tue|wed|thu|fri|sat|sun) ;;
  *) note_fail "bad slot";;
esac

if [ ! -f "$CONF" ]; then
  note_fail "no rclone conf"
fi

FILE=""
if [ -d "$SRC" ]; then
  # head closes the pipe early; do not let SIGPIPE fail the script
  FILE=$(find "$SRC" -maxdepth 1 -type f -name '*.tar.gz.gpg' -printf '%T@\t%p\n' | sort -nr | head -n 1 | cut -f2- || true)
fi
if [ -z "${FILE}" ] || [ ! -f "${FILE}" ]; then
  note_fail "no backup file"
fi

FILE_BASE=$(basename "$FILE")
FILE_SIZE=$(stat -c%s "$FILE")
SHA=$(sha256sum "$FILE" | awk 'NR==1{print $1}')
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# two spaces, same as sha256sum; the name is the original dated archive, not the slot
printf '%s  %s\n' "$SHA" "$FILE_BASE" > "$TMP/skv_${DAY}.sha256"

export RCLONE_CONFIG="$CONF"
if ! "$RCLONE" mkdir "$REMOTE" >>"$DETAIL" 2>&1; then
  note_fail "mkdir failed"
fi
if ! "$RCLONE" copyto "$FILE" "$REMOTE/skv_${DAY}.tar.gz.gpg" >>"$DETAIL" 2>&1; then
  note_fail "upload failed"
fi
if ! "$RCLONE" copyto "$TMP/skv_${DAY}.sha256" "$REMOTE/skv_${DAY}.sha256" >>"$DETAIL" 2>&1; then
  note_fail "sha256 upload failed"
fi

JSON=$("$RCLONE" lsjson "$REMOTE" --files-only 2>>"$DETAIL") || note_fail "lsjson failed"
REMOTE_SIZE=$(printf '%s' "$JSON" | python3 -c '
import json, sys
name = sys.argv[1]
raw = sys.stdin.read().strip() or "[]"
data = json.loads(raw)
if isinstance(data, dict):
    data = [data]
for item in data:
    if item.get("Name") == name or item.get("Path") == name:
        print(item.get("Size", ""))
        break
else:
    print("")
' "skv_${DAY}.tar.gz.gpg") || note_fail "lsjson parse failed"
if [ -z "$REMOTE_SIZE" ]; then
  note_fail "missing remote file"
fi
if [ "$REMOTE_SIZE" != "$FILE_SIZE" ]; then
  note_fail "size mismatch remote=${REMOTE_SIZE}"
fi
echo "ok $DATE $DAY $FILE_BASE $FILE_SIZE" >>"$LOG"
alert
exit 0
