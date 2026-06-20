#!/usr/bin/env bash
set -euo pipefail

# Manage a persistent Atlas Builder monitor process as a user systemd service.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SERVICE_NAME="atlas-builder-monitor.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/${SERVICE_NAME}"

HOST="${ATLAS_BUILDER_HOST:-atlas-builder}"
USER="${ATLAS_BUILDER_USER:-ao}"
BIND="${ATLAS_BUILDER_MONITOR_BIND:-127.0.0.1}"
PORT="${ATLAS_BUILDER_MONITOR_PORT:-9760}"
INTERVAL="${ATLAS_BUILDER_MONITOR_INTERVAL:-4.0}"
PYTHON_BIN="${ATLAS_BUILDER_MONITOR_PYTHON:-$(command -v python3)}"
LOG_FILE="/tmp/atlas-builder-monitor.log"

usage() {
  cat <<'EOF'
Usage:
  scripts/atlas-builder-monitor-service.sh [--host atlas-builder] [--user ao]
    [--bind 127.0.0.1] [--port 9760] [--interval 4.0]
    [install|start|stop|status|logs|disable|remove]

Modes:
  install   Render service unit and enable/start it
  start     Start service (writes unit if missing)
  stop      Stop service
  status    Show service status (default)
  logs      Follow service logs
  disable   Disable service (keeps unit file)
  remove    Stop/disable and delete unit file

Examples:
  scripts/atlas-builder-monitor-service.sh install
  scripts/atlas-builder-monitor-service.sh status --host atlas-builder --user ao
EOF
}

ACTION="status"
POSITIONAL=()

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:-}"
      shift 2
      ;;
    --user)
      USER="${2:-}"
      shift 2
      ;;
    --bind)
      BIND="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    --interval)
      INTERVAL="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ "${#POSITIONAL[@]}" -gt 0 ]]; then
  ACTION="${POSITIONAL[0]}"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required for monitor service management" >&2
  exit 1
fi

ensure_unit_dir() {
  mkdir -p "$UNIT_DIR"
}

write_unit() {
  ensure_unit_dir
  cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Atlas Builder Monitor
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/atlas_builder_monitor.py \
  --host ${HOST} \
  --user ${USER} \
  --bind ${BIND} \
  --port ${PORT} \
  --interval ${INTERVAL}
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=default.target
EOF
}

systemctl_user() {
  systemctl --user "$@"
}

status_print_hint() {
  local service_url="http://${BIND}:${PORT}"
  local state
  if systemctl_user is-active --quiet "$SERVICE_NAME"; then
    state="active"
  elif systemctl_user is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    state="enabled-inactive"
  else
    state="inactive"
  fi
  echo "Monitor service: ${SERVICE_NAME}"
  echo "State: ${state}"
  echo "URL: ${service_url}"
  if [[ "$BIND" == "127.0.0.1" || "$BIND" == "localhost" ]]; then
    echo "Remote access tip (from this machine): open ${service_url}"
  else
    echo "Public bind: ${BIND}"
  fi
  echo "To keep across reboot on systemd-enabled distros:"
  echo "  systemctl --user enable ${SERVICE_NAME}"
}

ensure_linger() {
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$USER" >/dev/null 2>&1 || true
  fi
}

case "$ACTION" in
  install)
    write_unit
    ensure_linger
    systemctl_user daemon-reload
    systemctl_user enable --now "$SERVICE_NAME"
    status_print_hint
    ;;
  start)
    if [[ ! -f "$UNIT_PATH" ]]; then
      write_unit
      systemctl_user daemon-reload
    fi
    ensure_linger
    systemctl_user start "$SERVICE_NAME"
    status_print_hint
    ;;
  stop)
    systemctl_user stop "$SERVICE_NAME"
    ;;
  status)
    if ! systemctl_user status "$SERVICE_NAME" --no-pager -l; then
      status_print_hint
      exit 0
    fi
    ;;
  logs)
    exec systemctl_user -f --no-pager --unit "$SERVICE_NAME"
    ;;
  disable)
    systemctl_user disable "$SERVICE_NAME" || true
    ;;
  remove)
    systemctl_user stop "$SERVICE_NAME" || true
    systemctl_user disable "$SERVICE_NAME" || true
    rm -f "$UNIT_PATH"
    systemctl_user daemon-reload
    echo "Removed $UNIT_PATH"
    ;;
  *)
    echo "unknown mode: $ACTION" >&2
    usage >&2
    exit 2
    ;;
esac
