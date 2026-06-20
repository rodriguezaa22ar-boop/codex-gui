#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
PROJECT_DIR="${PROJECT_DIR:-$REPO}"
SHELL_BIN="${SHELL_BIN:-/bin/bash}"

echo "Reinstalling codex-gui entrypoint from $PROJECT_DIR"
cd "$PROJECT_DIR"
python3 -m pip install --user --upgrade --force-reinstall .
bash scripts/install-codex-gui-desktop-entry.sh

echo "Done. Use:"
echo "  codex-gui --self-check"
echo "  codex-gui --self-check --project $PROJECT_DIR"
