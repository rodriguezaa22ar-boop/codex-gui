#!/usr/bin/env bash
set -euo pipefail

SESSION="${SESSION:-codex-release-verify}"
REPO="${REPO:-$HOME/Projects/codex-gui}"
REMOTE_SSH="git@github.com:rodriguezaa22ar-boop/codex-gui.git"
REMOTE_HTTPS="https://github.com/rodriguezaa22ar-boop/codex-gui.git"
MISSION_DIR="$HOME/.config/codex-gui/missions"
PROMPT_FILE="$MISSION_DIR/atlas-cockpit-release-verify.prompt"
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
  export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
  export PROMPT_FILE
  if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found in PATH."
    echo "Install or expose codex, then rerun: bash $SCRIPT_PATH"
    exec bash
  fi
  exec codex -C "$REPO" "$(cat "$PROMPT_FILE")"
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required before starting the verifier lane." >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required before starting the verifier lane." >&2
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
git checkout -B lane/release-verify

cat > "$PROMPT_FILE" <<'PROMPT'
Use $best-upfront-codex.

You are atlas-cockpit, the Verifier / Release Engineer lane for Codex Control.

Read docs/TEAM_ROLES.md and docs/missions/ATLAS_COCKPIT_RELEASE_VERIFY.md first.
Stay in the verification/release boundary.

Mission:
Verify release-readiness from this machine without duplicating backend or
product implementation work.

Primary targets:
- unit and pytest verification
- install and launch verification
- docs accuracy for docs/INSTALL.md and docs/PUBLIC_RELEASE.md
- exact reproduction of any failing command

Rules:
- Prefer verification, reproduction, and small verifier-safe fixes only.
- Do not rewrite broad UI or backend areas from this lane.
- Do not commit machine-private output, raw tokens, credentials, or local config.

Validation required:
- python3 -m unittest discover -s tests
- python3 -m pytest -q

Deliverable:
Push a focused verifier branch only if a small safe fix is required. Otherwise
write a precise handoff with the commands run, results, failures, risks, and the
exact Commander next action.
PROMPT

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -c "$REPO" "bash '$SCRIPT_PATH' --run-codex"

cat <<EOF
Started atlas-cockpit Release Verify Codex lane.

Session:
  $SESSION

Attach:
  tmux attach -t $SESSION

Repo:
  $REPO

Prompt:
  $PROMPT_FILE
EOF
