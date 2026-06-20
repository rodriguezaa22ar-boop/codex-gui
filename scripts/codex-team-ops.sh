#!/usr/bin/env bash
set -euo pipefail

# One-phrase entry for headless Codex team orchestration on the commander host.
# Example:
#   scripts/codex-team-ops.sh discover
#   scripts/codex-team-ops.sh prepare --check
#   scripts/codex-team-ops.sh status --run-id team-xyz

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${CODEX_GUI_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

if [[ ! -f "$REPO_ROOT/codex_team_ops.py" ]]; then
  echo "codex_team_ops.py not found at $REPO_ROOT" >&2
  exit 2
fi

cd "$REPO_ROOT"

# Keep command shape identical to direct module usage.
python3 "$REPO_ROOT/codex_team_ops.py" "$@"
