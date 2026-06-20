# Atlas Main Mission: Bootstrap Builder

Status: superseded by `ATLAS_MAIN_PRODUCT_PULSE.md` once Builder is already reachable and running.

Issued by `atlas-ubuntu` Commander / Integrator.

You are `atlas-main`, the Product / GTK UX Engineer, but this is an operator
handoff: start the headless `atlas-builder` Core Systems lane.

Do not start UI work yet. Your only task is to get Builder running Codex in a
persistent tmux session.

## Pull Latest Source

```bash
mkdir -p ~/Projects
cd ~/Projects

if [ ! -d codex-gui/.git ]; then
  git clone git@github.com:rodriguezaa22ar-boop/codex-gui.git codex-gui || \
    git clone https://github.com/rodriguezaa22ar-boop/codex-gui.git codex-gui
fi

cd ~/Projects/codex-gui
if GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new" \
  git ls-remote git@github.com:rodriguezaa22ar-boop/codex-gui.git main >/dev/null 2>&1; then
  git remote set-url origin git@github.com:rodriguezaa22ar-boop/codex-gui.git
else
  git remote set-url origin https://github.com/rodriguezaa22ar-boop/codex-gui.git
fi
git fetch origin main
git checkout main
git pull --ff-only origin main
```

## Start Builder

Run:

```bash
bash scripts/atlas-main-bootstrap-builder.sh
```

This script tries regular SSH first, then Tailscale SSH. If it reaches
`atlas-builder`, it will:

- pull latest `main` on Builder
- use GitHub SSH when available and fall back to HTTPS without forcing a broken
  SSH remote
- create/reset `lane/core-systems`
- write Builder's mission prompt
- start `tmux` session `codex-core-systems`
- launch Codex with the Core Systems mission

## If SSH Is Blocked

If the script cannot open a shell on Builder, enable this once on
`atlas-builder` from its local console:

```bash
sudo tailscale set --ssh=true --operator=$USER
```

Then rerun from `atlas-main`:

```bash
cd ~/Projects/codex-gui
bash scripts/atlas-main-bootstrap-builder.sh
```

## Handoff Back To Commander

Send this result:

```text
Role: Product / GTK UX Engineer
Device: atlas-main
Task: Bootstrap atlas-builder Core Systems lane

Result:
- started / blocked

Evidence:
- command run
- tmux session seen, or exact SSH/Tailscale error

Next:
- exact Commander action needed
```
