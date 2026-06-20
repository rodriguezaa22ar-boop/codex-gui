#!/usr/bin/env bash
set -euo pipefail

# High-signal control surface for atlas-builder in one entry point.
# Usage: builder|fab [status|shell|command|root|tmux|tmux-root|monitor|monitor-daemon|help] [...]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${ATLAS_BUILDER_HOST:-atlas-builder}"
USER="${ATLAS_BUILDER_USER:-ao}"
SESSION="${ATLAS_BUILDER_SESSION:-atlas-builder}"

if [[ "${1:-}" == "fab" || "${1:-}" == "builder" ]]; then
  shift
fi

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=1
  shift
fi

ACTION="${1:-status}"
shift || true

STATUS_CMD="$(
cat <<'EOF'
set -o pipefail

printf "host=%s\n" "$(hostname)"
printf "user=%s\n" "$(whoami)"
printf "uptime=%s\n" "$(uptime -p 2>/dev/null || uptime)"

if command -v free >/dev/null 2>&1; then
printf "memory=%s\n" "$(free -m | awk 'NR==2 {printf "%sMiB used / %sMiB total", $3, $2}')"
fi

if [ -r /proc/loadavg ]; then
  read -r load1 load5 load15 _ </proc/loadavg
  printf "cpu_load=%s,%s,%s\n" "$load1" "$load5" "$load15"
fi

if command -v df >/dev/null 2>&1; then
  printf "root_disk=%s\n" "$(df -m / | awk 'NR==2 {printf "%sM/%sM", $3, $2}')"
fi

if command -v systemctl >/dev/null 2>&1; then
  failed_units="$(systemctl --no-legend --failed --type=service | wc -l | tr -d ' ')"
  printf "failed_services=%s\n" "$failed_units"
fi

if [ -d /sys/class/power_supply/BAT0 ]; then
  read -r bat_level < /sys/class/power_supply/BAT0/capacity 2>/dev/null || true
  read -r bat_status < /sys/class/power_supply/BAT0/status 2>/dev/null || true
  printf "battery=%s%% (%s)\n" "${bat_level:-unknown}" "${bat_status:-unknown}"
fi

printf "temperature_samples=%s\n" \
  "$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{print int($1/1000)}' | tr '\n' ',' | sed 's/,$//' || true)"
EOF
)"

usage() {
  cat <<'EOF'
Usage:
  scripts/atlas-builder-ops.sh [--quiet] [status|shell|command|root|tmux|tmux-root|monitor|monitor-daemon|help] [payload]

Aliases:
  fab
  builder

Modes:
  status      Show essential remote health (default)
  shell       Open interactive shell
  command     Run one remote command
  root        Open root shell via sudo
  tmux        Attach to builder tmux session
  tmux-root   Attach to builder tmux with sudo shell
  monitor     Open local web monitor proxy command
  monitor-daemon
             Manage persistent local monitor service. Subcommands:
             install | start | stop | status | logs | disable | remove.
             Example: scripts/atlas-builder-ops.sh monitor-daemon install
  help        Show this help
EOF
}

RUN_PREFIX=()
if [[ "$QUIET" -eq 1 ]]; then
  RUN_PREFIX+=(--quiet)
fi

run_full() {
  bash "${SCRIPT_DIR}/atlas-builder-full-access.sh" "${RUN_PREFIX[@]}" --host "$HOST" --user "$USER" --session "$SESSION" "$@"
}

case "$ACTION" in
  status)
    run_full command "$STATUS_CMD"
    ;;
  shell)
    run_full shell
    ;;
  command)
    if [[ "$#" -eq 0 ]]; then
      usage >&2
      exit 2
    fi
    run_full command "$*"
    ;;
  root)
    run_full sudo
    ;;
  tmux)
    run_full tmux
    ;;
  tmux-root)
    run_full tmux-root
    ;;
  monitor)
    bash "${SCRIPT_DIR}/run-atlas-builder-monitor.sh" --host "$HOST" --user "$USER"
    ;;
  monitor-daemon)
    bash "${SCRIPT_DIR}/atlas-builder-monitor-service.sh" --host "$HOST" --user "$USER" "$@"
    ;;
  help|-h|--help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
