#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/atlas-sync.sh [--branch <name>] [--repo <path>] [--node <host>] [--user <user>] [--local|--remote|--all] [--dry-run] [--help]

Modes:
  --local      Sync only this machine.
  --remote     Sync only remote nodes.
  --all        Sync local machine and remote nodes (default).

Options:
  --branch     Git branch to pull from origin (default: current local branch, fallback main)
  --repo       Local repo path (default: repository root)
  --node       Add explicit remote node (repeatable; default: atlas-main, atlas-builder, atlas-cockpit)
  --user       SSH user for remote nodes without @userhost notation (default: ao)
  --dry-run    Print actions without applying remote changes
  --help       Show this help.

Examples:
  scripts/atlas-sync.sh
  scripts/atlas-sync.sh --branch lane/core-systems
  scripts/atlas-sync.sh --local --branch main
  scripts/atlas-sync.sh --remote --node atlas-main --node atlas-builder --node atlas-cockpit --user ao
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DEFAULT="$ROOT_DIR"
REPO="$REPO_DEFAULT"
BRANCH=""
MODE="all"
REMOTE_USER="${ATLAS_SYNC_USER:-ao}"
DRY_RUN=false
NODES=()
TARGET_NODES=(atlas-main atlas-builder atlas-cockpit)

normalize_node() {
  local node="$1"
  case "$node" in
    main)
      echo "atlas-main"
      return
      ;;
    cockpit)
      echo "atlas-cockpit"
      return
      ;;
    builder)
      echo "atlas-builder"
      return
      ;;
    *)
      echo "$node"
      ;;
  esac
}

require_repo() {
  if [[ ! -d "$REPO/.git" ]]; then
    echo "Not a git repository: $REPO" >&2
    exit 1
  fi
}

remote_branch_exists() {
  local repo="$1"
  local branch="$2"
  git -C "$repo" ls-remote --exit-code --heads origin "refs/heads/$branch" >/dev/null 2>&1
}

local_branch_exists() {
  local repo="$1"
  local branch="$2"
  git -C "$repo" show-ref --verify --quiet "refs/heads/$branch"
}

sync_repo() {
  local repo="$1"
  local requested_branch="$2"

  if [[ -z "$requested_branch" ]]; then
    requested_branch="$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || echo main)"
  fi

  local branch="$requested_branch"
  echo "Syncing local repo at $repo (${branch})"

  git -C "$repo" fetch --prune origin

  if ! remote_branch_exists "$repo" "$branch"; then
    if [[ "$branch" != "main" ]]; then
      echo "Warning: branch '$branch' missing on origin; falling back to main" >&2
    fi
    branch="main"
  fi

  if ! remote_branch_exists "$repo" "$branch"; then
    echo "Error: origin branch '$branch' not found for $repo" >&2
    return 1
  fi

  local current
  current="$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || true)"

  if [[ "$current" == "$branch" ]]; then
    git -C "$repo" pull --ff-only "origin" "$branch"
  elif [[ -n "$current" ]] && local_branch_exists "$repo" "$branch"; then
    git -C "$repo" checkout "$branch"
    git -C "$repo" pull --ff-only "origin" "$branch"
  else
    git -C "$repo" checkout -b "$branch" "origin/$branch"
  fi

  echo "Updated local: $(git -C "$repo" rev-parse --abbrev-ref HEAD) => $(git -C "$repo" rev-parse --short HEAD)"
}

run_remote_sync() {
  local node="$1"
  local target
  local normalized

  normalized="$(normalize_node "$node")"
  target="$normalized"

  if [[ "$target" != *"@"* ]]; then
    target="$REMOTE_USER@$target"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] Skipping remote execution for $target"
    return 0
  fi

  echo "Syncing remote node: $target"

  local -a ssh_opts=(
    -o BatchMode=yes
    -o ConnectTimeout=12
    -o StrictHostKeyChecking=accept-new
  )

  ssh "${ssh_opts[@]}" "$target" bash -s -- "$REPO" "$BRANCH" <<'REMOTE_SCRIPT'
set -euo pipefail

repo="${1:-$HOME/Projects/codex-gui}"
branch="${2:-}"

if [[ -z "$branch" ]]; then
  branch="$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || echo main)"
fi

if [[ ! -d "$repo/.git" ]]; then
  echo "Not a git repository on remote: $repo" >&2
  exit 1
fi

workspace_clean() {
  [[ -z "$(git -C "$repo" status --porcelain=1)" ]]
}

echo "Remote sync: $repo (${branch})"

git -C "$repo" fetch --prune origin

if ! git -C "$repo" ls-remote --exit-code --heads origin "refs/heads/$branch" >/dev/null 2>&1; then
  if [[ "$branch" != "main" ]]; then
    echo "Warning: branch '$branch' missing on origin on remote; falling back to main" >&2
  fi
  branch="main"
fi

if ! git -C "$repo" ls-remote --exit-code --heads origin "refs/heads/$branch" >/dev/null 2>&1; then
  echo "Error: origin branch '$branch' not found on remote." >&2
  exit 1
fi

current="$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || true)"

if ! workspace_clean; then
  if [[ "$current" == "$branch" ]]; then
    echo "Remote branch '$branch' has local changes on $repo; skipping fast-forward pull to avoid overwrite." >&2
    exit 0
  fi

  echo "Remote branch has local changes on $repo; skipping checkout of '$branch' to avoid overwrite." >&2
  exit 0
fi

if [[ "$current" == "$branch" ]]; then
  git -C "$repo" pull --ff-only origin "$branch"
elif [[ -n "$current" ]] && git -C "$repo" show-ref --verify --quiet "refs/heads/$branch"; then
  git -C "$repo" checkout "$branch" && git -C "$repo" pull --ff-only origin "$branch"
else
  git -C "$repo" checkout -b "$branch" "origin/$branch"
fi

echo "Updated remote: $(git -C "$repo" rev-parse --abbrev-ref HEAD) => $(git -C "$repo" rev-parse --short HEAD)"
REMOTE_SCRIPT
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --user)
      REMOTE_USER="${2:-}"
      shift 2
      ;;
    --node)
      NODES+=("${2:-}")
      shift 2
      ;;
    --local)
      MODE="local"
      shift
      ;;
    --remote)
      MODE="remote"
      shift
      ;;
    --all)
      MODE="all"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! -d "$REPO" ]]; then
  echo "Repo path not found: $REPO" >&2
  exit 1
fi

if [[ -z "${NODES[*]}" ]]; then
  NODES=("${TARGET_NODES[@]}")
fi

require_repo

if [[ "$MODE" == "local" || "$MODE" == "all" ]]; then
  sync_repo "$REPO" "$BRANCH"
fi

if [[ "$MODE" == "remote" || "$MODE" == "all" ]]; then
  for node in "${NODES[@]}"; do
    if run_remote_sync "$node"; then
      true
    else
      echo "Remote sync failed: $node" >&2
    fi
  done
fi
