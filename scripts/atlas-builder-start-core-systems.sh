#!/usr/bin/env bash
set -euo pipefail

SESSION="${SESSION:-codex-core-systems}"
REPO="${REPO:-$HOME/Projects/codex-gui}"
REMOTE_SSH="git@github.com:rodriguezaa22ar-boop/codex-gui.git"
REMOTE_HTTPS="https://github.com/rodriguezaa22ar-boop/codex-gui.git"
MISSION_DIR="$HOME/.config/codex-gui/missions"
PROMPT_FILE="$MISSION_DIR/atlas-builder-core-systems.prompt"
SCRIPT_PATH="$(readlink -f "$0")"
export GIT_TERMINAL_PROMPT=0

configure_origin() {
  if GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new" \
    git ls-remote "$REMOTE_SSH" main >/dev/null 2>&1; then
    git remote set-url origin "$REMOTE_SSH"
  else
    git remote set-url origin "$REMOTE_HTTPS"
  fi
}

if [[ "${1:-}" == "--run-codex" ]]; then
  cd "$REPO"
  export PATH="$HOME/.local/bin:$PATH"
  export PROMPT_FILE
  if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found in PATH."
    echo "Install or expose codex, then rerun: bash $SCRIPT_PATH"
    exec bash
  fi
  exec codex -C "$REPO" "$(cat "$PROMPT_FILE")"
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required before starting the Codex lane." >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  if command -v nix-shell >/dev/null 2>&1; then
    exec nix-shell -p tmux git --run "bash '$SCRIPT_PATH'"
  fi
  echo "tmux is required. On NixOS, run: nix-shell -p tmux git" >&2
  exit 1
fi

mkdir -p "$HOME/Projects" "$MISSION_DIR"

if [[ ! -d "$REPO/.git" ]]; then
  git clone "$REMOTE_SSH" "$REPO" || git clone "$REMOTE_HTTPS" "$REPO"
fi

cd "$REPO"
configure_origin
git fetch origin main
git checkout main
git pull --ff-only origin main
git checkout -B lane/core-systems

cat > "$PROMPT_FILE" <<'PROMPT'
Use $best-upfront-codex.

You are atlas-builder, the Core Systems Engineer lane for Codex Control.

Read docs/TEAM_ROLES.md and docs/missions/ATLAS_BUILDER_CORE_SYSTEMS.md first.
Stay inside the Core Systems boundary.

Mission:
Implement a backend-first mesh readiness report path that the GUI and future CLI
can reuse. It should inspect saved mesh devices, classify readiness using
existing codex_devices helpers, and produce actionable next steps per worker
without exposing secrets or requiring a broad UI rewrite.

Preferred shape:
- Add small backend helpers rather than large GUI rewrites.
- Reuse codex_devices.py, codex_team.py, and existing test style.
- Include blocker categories for local ready, SSH auth denied, Tailscale SSH
  approval required, offline/timeout, missing project, missing Codex, and stale
  checkout when detectable.
- Add unit tests for report generation and classification.
- Keep remote command paths deterministic and metadata-safe.
- Do not commit local ~/.config/codex-gui/devices.json, raw logs, tokens, sudo
  codes, credentials, or machine-private output.

Validation required:
- python3 -m unittest discover -s tests
- python3 -m py_compile codex_devices.py codex_gui.py codex_actions.py codex_team.py codex_setup.py codex_quality.py

If this NixOS node needs the dev shell, run checks through nix-shell.

Deliverable:
Commit a focused change on branch lane/core-systems and push it if GitHub auth
is available. If push is blocked, write a handoff with exact changed files,
commands run, risks, and the smallest next action for the Commander.
PROMPT

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -c "$REPO" "bash '$SCRIPT_PATH' --run-codex"

cat <<EOF
Started atlas-builder Core Systems Codex lane.

Session:
  $SESSION

Attach:
  tmux attach -t $SESSION

Repo:
  $REPO

Prompt:
  $PROMPT_FILE
EOF
