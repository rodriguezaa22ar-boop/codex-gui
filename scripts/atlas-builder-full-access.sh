#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/atlas-builder-full-access.sh [--host atlas-builder] [--user ao] [--session atlas-builder] [shell|command|sudo|tmux|tmux-root|monitor] [payload]

Modes:
  shell      Open interactive shell (default)
  command    Execute one shell command on remote host
  sudo       Run as root (opens root shell if no payload)
  tmux       Attach to a persistent tmux session on builder
  tmux-root  Attach to tmux with automatic root shell
  monitor    Open atlas-builder web monitor launcher

Examples:
  # legacy positional form
  scripts/atlas-builder-full-access.sh atlas-builder ao

  # explicit form
  scripts/atlas-builder-full-access.sh --host atlas-builder --user ao shell

  # one remote command
  scripts/atlas-builder-full-access.sh atlas-builder ao command "systemctl --user status"

  # persistent root shell that survives reconnects
  scripts/atlas-builder-full-access.sh --host atlas-builder --user ao tmux-root
EOF
}

HOST="atlas-builder"
USER="ao"
ACTION="shell"
TMUX_SESSION="atlas-builder"
PAYLOAD=()

HOST_SET=0
USER_SET=0

ssh_common=(
  -o BatchMode=yes
  -o ConnectTimeout=12
  -o StrictHostKeyChecking=accept-new
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:-}"
      shift 2
      ;;
    --user)
      USER="${2:-}"
      shift 2
      ;;
    --session)
      TMUX_SESSION="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    shell|command|sudo|tmux|tmux-root|monitor)
      ACTION="$1"
      shift
      break
      ;;
    *)
      if [[ "$HOST_SET" -eq 0 ]]; then
        HOST="$1"
        HOST_SET=1
        shift
        continue
      fi
      if [[ "$USER_SET" -eq 0 ]]; then
        USER="$1"
        USER_SET=1
        shift
        continue
      fi
      PAYLOAD+=("$1")
      shift
      ;;
  esac
done

while [[ $# -gt 0 ]]; do
  PAYLOAD+=("$1")
  shift
done

if [[ "${#PAYLOAD[@]}" -eq 0 ]]; then
  if [[ "$ACTION" == "command" ]]; then
    echo "missing command payload" >&2
    usage
    exit 2
  fi
fi

TARGET="${USER}@${HOST}"

case "$ACTION" in
  shell)
    exec ssh "${ssh_common[@]}" "$TARGET"
    ;;
  command)
    exec ssh "${ssh_common[@]}" "$TARGET" "${PAYLOAD[@]}"
    ;;
  sudo)
    if [[ ${#PAYLOAD[@]} -eq 0 ]]; then
      exec ssh "${ssh_common[@]}" "$TARGET" 'sudo -s'
    else
      exec ssh "${ssh_common[@]}" "$TARGET" sudo "${PAYLOAD[@]}"
    fi
    ;;
  tmux)
    exec ssh "${ssh_common[@]}" "$TARGET" \
      "command -v tmux >/dev/null 2>&1 || { echo 'tmux is required for this mode' >&2; exit 1; }; \
      exec tmux new-session -A -s \"${TMUX_SESSION}\""
    ;;
  tmux-root)
    exec ssh "${ssh_common[@]}" "$TARGET" \
      "command -v tmux >/dev/null 2>&1 || { echo 'tmux is required for this mode' >&2; exit 1; }; \
      exec tmux new-session -A -s \"${TMUX_SESSION}\" 'sudo -s'"
    ;;
  monitor)
    exec bash scripts/run-atlas-builder-monitor.sh --host "$HOST" --user "$USER"
    ;;
  *)
    usage
    exit 2
    ;;
esac
