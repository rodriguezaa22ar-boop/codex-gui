#!/usr/bin/env bash
set -euo pipefail

# Fast path into atlas-builder with minimal typing.
# No args => persistent root tmux attachment.
# Pass a mode (shell, command, sudo, tmux, monitor, tmux-root) to override.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${ATLAS_BUILDER_HOST:-atlas-builder}"
USER="${ATLAS_BUILDER_USER:-ao}"
SESSION="${ATLAS_BUILDER_SESSION:-atlas-builder}"

if [[ "$#" -eq 0 ]]; then
  set -- tmux-root
fi

exec "${SCRIPT_DIR}/atlas-builder-full-access.sh" --host "$HOST" --user "$USER" --session "$SESSION" "$@"
