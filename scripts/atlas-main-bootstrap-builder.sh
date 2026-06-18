#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-atlas-builder}"
REMOTE_USER="${REMOTE_USER:-ao}"
REMOTE_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
REPO_REMOTE="git@github.com:rodriguezaa22ar-boop/codex-gui.git"
REPO_HTTPS="https://github.com/rodriguezaa22ar-boop/codex-gui.git"

remote_payload() {
  cat <<'REMOTE'
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
export GIT_TERMINAL_PROMPT=0
REMOTE_SSH="git@github.com:rodriguezaa22ar-boop/codex-gui.git"
REMOTE_HTTPS="https://github.com/rodriguezaa22ar-boop/codex-gui.git"

repo_remote_url() {
  if git ls-remote "$REMOTE_SSH" HEAD >/dev/null 2>&1; then
    printf '%s\n' "$REMOTE_SSH"
  else
    printf '%s\n' "$REMOTE_HTTPS"
  fi
}

mkdir -p "$HOME/Projects"
cd "$HOME/Projects"

if ! command -v git >/dev/null 2>&1; then
  if command -v nix-shell >/dev/null 2>&1; then
    exec nix-shell -p git tmux --run 'bash -s' <<'NIXREMOTE'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export GIT_TERMINAL_PROMPT=0
REMOTE_SSH="git@github.com:rodriguezaa22ar-boop/codex-gui.git"
REMOTE_HTTPS="https://github.com/rodriguezaa22ar-boop/codex-gui.git"

repo_remote_url() {
  if git ls-remote "$REMOTE_SSH" HEAD >/dev/null 2>&1; then
    printf '%s\n' "$REMOTE_SSH"
  else
    printf '%s\n' "$REMOTE_HTTPS"
  fi
}

mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
if [ ! -d codex-gui/.git ]; then
  git clone "$(repo_remote_url)" codex-gui
fi
cd codex-gui
git remote set-url origin "$(repo_remote_url)" || true
git fetch origin main
git checkout main
git pull --ff-only origin main
bash scripts/atlas-builder-start-core-systems.sh
tmux ls
NIXREMOTE
  fi
  echo "git is not available and nix-shell is not available on atlas-builder." >&2
  exit 127
fi

if [ ! -d codex-gui/.git ]; then
  git clone "$(repo_remote_url)" codex-gui
fi

cd codex-gui
git remote set-url origin "$(repo_remote_url)" || true
git fetch origin main
git checkout main
git pull --ff-only origin main

bash scripts/atlas-builder-start-core-systems.sh
tmux ls
REMOTE
}

try_regular_ssh() {
  ssh \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=8 \
    "$REMOTE_TARGET" \
    'bash -s' < <(remote_payload)
}

try_tailscale_ssh() {
  tailscale ssh "$REMOTE_TARGET" 'bash -s' < <(remote_payload)
}

echo "Atlas Main bootstrap: starting atlas-builder Core Systems lane"
echo "Target: $REMOTE_TARGET"
echo

if try_regular_ssh; then
  echo
  echo "atlas-builder started through regular SSH."
  exit 0
fi

echo
echo "Regular SSH did not work; trying Tailscale SSH..."
echo

if try_tailscale_ssh; then
  echo
  echo "atlas-builder started through Tailscale SSH."
  exit 0
fi

cat >&2 <<'EOF'

Could not open a shell on atlas-builder.

Likely fixes on atlas-builder:

1. Enable Tailscale SSH:

   sudo tailscale set --ssh=true --operator=$USER

2. Or add atlas-main/atlas-ubuntu's SSH public key to the Builder user's
   ~/.ssh/authorized_keys.

3. Then rerun from atlas-main:

   cd ~/Projects/codex-gui
   bash scripts/atlas-main-bootstrap-builder.sh

EOF
exit 1
