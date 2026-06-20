#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${CODEX_GUI_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_ROOT="${CODEX_GUI_PROJECT_ROOT:-$REPO_ROOT}"
NO_PERSIST=0
JSON_OUTPUT=0

print_usage() {
  cat <<'USAGE'
Usage:
  scripts/atlas-mesh-blockers.sh [--project-root /path] [--no-persist] [--json]

Run a checked fleet probe and print the remaining blockers with next actions.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root|-p)
      shift
      PROJECT_ROOT="${1:?missing --project-root value}"
      ;;
    --no-persist)
      NO_PERSIST=1
      ;;
    --json)
      JSON_OUTPUT=1
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      print_usage
      exit 2
      ;;
  esac
  shift
done

cd "$REPO_ROOT"

if [[ ! -f "$REPO_ROOT/codex_team_ops.py" ]]; then
  echo "codex_team_ops.py not found at $REPO_ROOT" >&2
  exit 2
fi

JSON_PATH="$(mktemp)"
trap 'rm -f "$JSON_PATH"' EXIT

if (( NO_PERSIST )); then
  python3 codex_team_ops.py --json check --no-persist > "$JSON_PATH"
else
  python3 codex_team_ops.py --json check > "$JSON_PATH"
fi

python3 - "$JSON_PATH" "$PROJECT_ROOT" "$JSON_OUTPUT" <<'PY'
import json
import pathlib
import sys

json_path = pathlib.Path(sys.argv[1])
project_root = sys.argv[2]
json_output = bool(int(sys.argv[3]))
payload = json.loads(json_path.read_text(encoding="utf-8"))
rows = payload.get("rows", [])

if not rows:
  print("No saved fleet devices found. Run: python3 codex_team_ops.py --json discover")
  raise SystemExit(0)

blockers = [row for row in rows if row.get("status") in {"blocked", "review", "offline"}]
ready = [row for row in rows if row.get("status") == "ready"]
ready_count = len(ready)
blocker_count = len(blockers)

if blocker_count == 0:
  if json_output:
    print(json.dumps({
        "project_root": project_root,
        "ready": ready_count,
        "blockers": 0,
        "rows": [],
        "summary": "ready",
    }, sort_keys=True))
  else:
    print(f"Fleet ready: {ready_count} ready device(s) in {project_root}.")
    print("Next action: prepare --check")
  raise SystemExit(0)

def priority(row: dict) -> tuple[int, str]:
  return (row.get("action_priority", 999), row.get("device_name", ""))

if json_output:
  print(json.dumps({
      "project_root": project_root,
      "ready": ready_count,
      "blockers": blocker_count,
      "total": len(rows),
      "rows": sorted(blockers, key=priority),
      "summary": "blocked",
  }, sort_keys=True))
  raise SystemExit(0)

for row in sorted(blockers, key=priority):
  status = row.get("status", "unknown")
  device = row.get("device_name", "<unknown>")
  host = row.get("host", "<unknown>")
  summary = row.get("summary", "No summary available")
  category = row.get("blocker_category", "unknown")
  print(f"{status.upper():>8} | {device} ({host}) | {category} | {summary}")
  for action in row.get("next_actions", []):
    print(f"         -> {action}")

print(f"\nReady: {ready_count} | Blockers: {blocker_count} | Total: {len(rows)}")
print(f"Project: {project_root}")
print("Tip: Open the approval links above, then run: python3 codex_team_ops.py --json check")
PY
