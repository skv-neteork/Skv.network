#!/usr/bin/env bash
# SKV installer for local agents (Claude Code, Cursor, Claude Desktop).
#   curl -fsSL https://skv.network/install.sh | bash
#   curl -fsSL https://skv.network/install.sh | bash -s -- --uninstall
# Options: --clients claude-code,cursor,claude-desktop   (skip the questions)
#          --no-hooks   MCP only        --uninstall   remove everything SKV added
# Nothing is installed without your yes. Key is read hidden and kept in ~/.skv/key (0600), never in shell history.
set -euo pipefail
BASE="${SKV_BASE:-https://skv.network}"
SKV_HOME="${SKV_HOME:-$HOME/.skv}"
ACTION=install; CLIENTS=""; HOOKS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) ACTION=uninstall ;;
    --clients) CLIENTS="$2"; shift ;;
    --clients=*) CLIENTS="${1#*=}" ;;
    --no-hooks) HOOKS=0 ;;
    -h|--help) sed -n '2,8p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac; shift
done
command -v python3 >/dev/null || { echo "SKV installer needs python3." >&2; exit 1; }
TTY=/dev/tty
if ! { : <"$TTY"; } 2>/dev/null; then
  if [ ! -t 0 ] && [ -z "${BASH_SOURCE[0]:-}" ]; then
    echo "No terminal for questions. Run: bash <(curl -fsSL $BASE/install.sh)   (answers can then come from stdin)" >&2; exit 1
  fi
  TTY=/dev/stdin
fi
ask() { local a; printf "%s [y/N] " "$1" >&2; read -r a <"$TTY" || a=""; [[ "$a" =~ ^([yY]|[дД]) ]]; }
fetch() { # fetch <name> <dest>: from SKV_SRC_DIR (tests) or the site
  if [ -n "${SKV_SRC_DIR:-}" ]; then cp "$SKV_SRC_DIR/$1" "$2"; else curl -fsSL "$BASE/install/$1" -o "$2"; fi; }

mkdir -p "$SKV_HOME"; chmod 700 "$SKV_HOME"
fetch skv_config.py "$SKV_HOME/skv_config.py"

detect() {
  case "$1" in
    claude-code) command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ] || [ -f "$HOME/.claude.json" ] ;;
    cursor) command -v cursor >/dev/null 2>&1 || [ -d "$HOME/.cursor" ] ;;
    claude-desktop) [ -d "$HOME/Library/Application Support/Claude" ] || [ -d "$HOME/.config/Claude" ] ;;
  esac; }
label() { case "$1" in claude-code) echo "Claude Code (MCP + hooks)";; cursor) echo "Cursor (MCP + hooks)";; claude-desktop) echo "Claude Desktop (MCP only, needs Node.js; no hooks there)";; esac; }

if [ -z "$CLIENTS" ]; then
  for c in claude-code cursor claude-desktop; do
    if detect "$c"; then
      if [ "$ACTION" = install ]; then ask "Connect SKV to $(label $c)?" && CLIENTS="$CLIENTS,$c"
      else ask "Remove SKV from $(label $c)?" && CLIENTS="$CLIENTS,$c"; fi
    fi
  done
  CLIENTS="${CLIENTS#,}"
fi
[ -n "$CLIENTS" ] || { echo "Nothing selected. Nothing changed."; exit 0; }

if [ "$ACTION" = install ]; then
  if [ ! -s "$SKV_HOME/key" ] || ask "A key is already saved in $SKV_HOME/key. Replace it?"; then
    if [ -n "${SKV_KEY_FILE:-}" ]; then K="$(tr -d ' \r\n' <"$SKV_KEY_FILE")"
    else printf "Paste your SKV key (sk_... from %s/profile; hidden): " "$BASE" >&2; read -rs K <"$TTY"; echo >&2; fi
    case "$K" in sk_*) ;; *) echo "That does not look like an SKV key (sk_...). Nothing changed." >&2; exit 1;; esac
    ( umask 077; printf "%s" "$K" >"$SKV_HOME/key" ); chmod 600 "$SKV_HOME/key"; unset K
  fi
  if [ "$HOOKS" = 1 ]; then fetch skv_hook.py "$SKV_HOME/skv_hook.py"; chmod 700 "$SKV_HOME/skv_hook.py"; fi
fi

IFS=',' read -ra LIST <<<"$CLIENTS"
for c in "${LIST[@]}"; do
  echo "== $c"
  SKV_NO_HOOKS=$((1-HOOKS)) python3 "$SKV_HOME/skv_config.py" "$ACTION" "$c" "$SKV_HOME" "$BASE" || echo "  failed for $c (see message above)"
done

if [ "$ACTION" = install ]; then
  if [ "$HOOKS" = 1 ]; then
    echo "== test turn"; python3 "$SKV_HOME/skv_hook.py" test || echo "  test failed: check the key and network"
  fi
  echo "Done. Restart the selected apps. Pause saving any time: touch $SKV_HOME/off. Remove: curl -fsSL $BASE/install.sh | bash -s -- --uninstall"
else
  if ask "Also delete $SKV_HOME (your saved key and hook)?"; then rm -rf "$SKV_HOME"; echo "Deleted $SKV_HOME"; fi
  echo "Done. Backups of changed files are next to them (*.skv-bak.*)."
fi
