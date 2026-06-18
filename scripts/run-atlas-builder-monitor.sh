#!/usr/bin/env bash
set -euo pipefail

cd /home/ao/Projects/codex-gui

exec python3 atlas_builder_monitor.py "$@"
