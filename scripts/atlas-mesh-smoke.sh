#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${CODEX_GUI_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_ROOT="${CODEX_GUI_PROJECT_ROOT:-$REPO_ROOT}"
RECEIPT_DIR="${CODEX_GUI_SMOKE_ROOT:-$HOME/.config/codex-gui/smoke-reports}"
TIMESTAMP="${CODEX_GUI_SMOKE_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="$RECEIPT_DIR/$TIMESTAMP"

mkdir -p "$RUN_DIR"
cd "$REPO_ROOT"

OUTPUTS=()

run_capture() {
    local label="$1"
    shift
    local status=0

    {
        printf '{\n'
        printf '  "label": "%s",\n' "$label"
        printf '  "command": "%s",\n' "$*"
        printf '  "project_root": "%s",\n' "$PROJECT_ROOT"
        printf '  "ts_unix": %s,\n' "$(date +%s)"
        printf '  "exit_code": '
    } > "$RUN_DIR/${label}.json"

    if "$@" > "$RUN_DIR/${label}.stdout" 2> "$RUN_DIR/${label}.stderr"; then
        status=0
    else
        status=$?
    fi

    {
        printf '%s,\n' "$status"
        printf '  "stdout_path": "%s",\n' "$RUN_DIR/${label}.stdout"
        printf '  "stderr_path": "%s"\n' "$RUN_DIR/${label}.stderr"
        printf '}\n'
    } >> "$RUN_DIR/${label}.json"

    if [[ -s "$RUN_DIR/${label}.stderr" ]]; then
        printf '[mesh-smoke] %s exit=%s stderr=%s\n' "$label" "$status" "$(cat "$RUN_DIR/${label}.stderr" | tr '\n' '; ')"
    else
        printf '[mesh-smoke] %s exit=%s\n' "$label" "$status"
    fi

    OUTPUTS+=("$label")
    return 0
}

echo "Mesh smoke run: $TIMESTAMP"
echo "Repository: $REPO_ROOT"
echo "Output: $RUN_DIR"

echo "[mesh-smoke] running local validators"
run_capture "local-pyc" python3 -m py_compile codex_devices.py codex_gui.py codex_team.py
run_capture "local-tests" python3 -m unittest discover -s tests

run_capture "discover" python3 codex_team_ops.py --json discover
run_capture "check" python3 codex_team_ops.py --json check
run_capture "roles" python3 codex_team_ops.py --json roles
run_capture "doctor" python3 codex_team_ops.py --json doctor --check
# This command intentionally may fail when no ready trusted devices exist.
run_capture "prepare-check" python3 codex_team_ops.py --json prepare --project-root "$PROJECT_ROOT" --check || true

if [[ -f ~/.local/bin/codex-gui ]]; then
  run_capture "codex-gui-self-check" codex-gui --self-check --project "$PROJECT_ROOT" --json
fi

if command -v codex >/dev/null 2>&1; then
  run_capture "codex-doctor" codex doctor --summary --ascii
fi

{
    printf 'Smoke run captured at %s\n' "$RUN_DIR"
    printf 'manifest: %s\n' "$RUN_DIR/manifest.json"
} > "$RUN_DIR/manifest.txt"

{
    printf '{\n'
    printf '  "timestamp": "%s",\n' "$TIMESTAMP"
    printf '  "repo": "%s",\n' "$REPO_ROOT"
    printf '  "project_root": "%s",\n' "$PROJECT_ROOT"
    printf '  "outputs": ['

    for i in "${!OUTPUTS[@]}"; do
        if [[ "$i" -gt 0 ]]; then
            printf ', '
        fi
        printf '"%s"' "${OUTPUTS[$i]}"
    done

    printf ']\n}\n'
} > "$RUN_DIR/manifest.json"

echo "Mesh smoke run complete: $RUN_DIR"
