#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/atlas-builder-full-access.sh [--host atlas-builder] [--user ao] [shell|command|sudo|monitor] [payload]

Modes:
  shell    Open interactive shell (default)
  command  Execute one shell command on remote host
  sudo     Run as root (opens root shell if no payload)
  monitor  Run atlas-builder web monitor launcher
EOF
}

HOST="atlas-builder"
USER="ao"
ACTION="shell"
PAYLOAD=""

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
    shell|command|sudo|monitor)
      ACTION="$1"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      if [[ -n "$PAYLOAD" ]]; then
        PAYLOAD="${PAYLOAD% } $1"
      else
        PAYLOAD="$1"
      fi
      shift
      ;;
  esac
done

TARGET="${USER}@${HOST}"

case "$ACTION" in
  shell)
    exec ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new "$TARGET"
    ;;
  command)
    if [[ -z "$PAYLOAD" ]]; then
      echo "missing command payload" >&2
      usage
      exit 2
    fi
    exec ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new "$TARGET" "$PAYLOAD"
    ;;
  sudo)
    if [[ -z "$PAYLOAD" ]]; then
      exec ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new "$TARGET" 'sudo -s'
    else
      exec ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new "$TARGET" "sudo $PAYLOAD"
    fi
    ;;
  monitor)
    exec bash scripts/run-atlas-builder-monitor.sh --host "$HOST" --user "$USER"
    ;;
  *)
    usage
    exit 2
    ;;
esac
