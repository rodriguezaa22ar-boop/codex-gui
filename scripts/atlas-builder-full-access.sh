#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/atlas-builder-full-access.sh [--host atlas-builder] [--user ao] [--session atlas-builder] [--quiet] [shell|command|sudo|tmux|tmux-root|monitor] [payload]

Modes:
  shell      Open interactive shell (default)
  command    Execute one shell command on remote host
  sudo       Run as root (opens root shell if no payload)
  tmux       Attach to a persistent tmux session on builder
  tmux-root  Attach to tmux with automatic root shell
  monitor    Open atlas-builder web monitor launcher
  --quiet    Filter noisy shell-init output lines (declare -x) in remote command output

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
QUIET=0

require_interactive() {
  if ! [ -t 0 ] || ! [ -t 1 ]; then
    echo "builder interactive mode requires a terminal (TTY)." >&2
    echo "Run from a real terminal:" >&2
    echo "  builder tmux-root" >&2
    echo "Or use command mode for non-interactive runs:" >&2
    echo "  builder command \"<command>\"" >&2
    exit 2
  fi
}

ssh_common=(
  -o BatchMode=yes
  -o ConnectTimeout=12
  -o StrictHostKeyChecking=accept-new
)

run_ssh_command() {
  if [[ "$QUIET" -eq 1 ]]; then
    ssh "${ssh_common[@]}" "$TARGET" "$@" | sed -u '/^declare -x /d'
  else
    ssh "${ssh_common[@]}" "$TARGET" "$@"
  fi
}

run_ssh_interactive() {
  if [[ "$QUIET" -eq 1 ]]; then
    ssh -t "${ssh_common[@]}" "$TARGET" "$@" | sed -u '/^declare -x /d'
  else
    ssh -t "${ssh_common[@]}" "$TARGET" "$@"
  fi
}

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
    --quiet)
      QUIET=1
      shift
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
    require_interactive
    exec ssh "${ssh_common[@]}" "$TARGET"
    ;;
  command)
    run_ssh_command "${PAYLOAD[@]}"
    ;;
  sudo)
    if [[ ${#PAYLOAD[@]} -eq 0 ]]; then
      exec ssh "${ssh_common[@]}" "$TARGET" 'sudo -s'
    else
      if [[ "$QUIET" -eq 1 ]]; then
        run_ssh_command sudo "${PAYLOAD[@]}"
      else
        exec ssh "${ssh_common[@]}" "$TARGET" sudo "${PAYLOAD[@]}"
      fi
    fi
    ;;
  tmux)
    require_interactive
    run_ssh_interactive \
      "command -v tmux >/dev/null 2>&1 || { echo 'tmux is required for this mode' >&2; exit 1; }; \
      exec tmux new-session -A -s \"${TMUX_SESSION}\""
    ;;
  tmux-root)
    require_interactive
    run_ssh_interactive \
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
