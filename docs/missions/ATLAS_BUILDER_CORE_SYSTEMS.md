# Atlas Builder Mission: Core Systems Lane

Issued by `atlas-ubuntu` Commander / Integrator.

You are `atlas-builder`, the Core Systems Engineer for Codex Control. Your job
is to make the machinery reliable: mesh orchestration, Tailscale/SSH readiness,
local/remote worker behavior, config, persistence, command safety, packaging,
setup automation, and tests.

Do not work on broad visual redesign. Do not commit secrets, local device
config, raw prompts, terminal logs, or credentials.

## Pull Latest Source

Headless NixOS quick start:

```bash
cd ~/Projects/codex-gui
bash scripts/atlas-builder-start-core-systems.sh
tmux attach -t codex-core-systems
```

If Ubuntu Commander needs to drive this node over SSH later, enable Tailscale
SSH on the Builder node once:

```bash
sudo tailscale set --ssh=true --operator=$USER
```

The script above opens a persistent `tmux` session and launches Codex with this
mission. The manual setup below is the expanded version.

```bash
mkdir -p ~/Projects
cd ~/Projects

if [ ! -d codex-gui/.git ]; then
  git clone git@github.com:rodriguezaa22ar-boop/codex-gui.git codex-gui
fi

cd ~/Projects/codex-gui
git remote set-url origin git@github.com:rodriguezaa22ar-boop/codex-gui.git
git fetch origin main
git checkout main
git pull --ff-only origin main
git checkout -B lane/core-systems
```

Read the operating model:

```bash
sed -n '1,260p' docs/TEAM_ROLES.md
```

## Baseline Check

Ubuntu/Debian style:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile codex_devices.py codex_gui.py codex_actions.py codex_team.py codex_setup.py codex_quality.py
```

NixOS style:

```bash
nix-shell --run "python3 -m unittest discover -s tests"
nix-shell --run "python3 -m py_compile codex_devices.py codex_gui.py codex_actions.py codex_team.py codex_setup.py codex_quality.py"
```

If baseline fails, stop and report the exact command and failure before making
broad changes.

## Codex Command

Run this from `~/Projects/codex-gui`:

```bash
codex -C ~/Projects/codex-gui 'Use $best-upfront-codex.

You are atlas-builder, the Core Systems Engineer lane for Codex Control.

Read docs/TEAM_ROLES.md first. Stay within the Core Systems boundary.

Mission:
Implement a backend-first mesh readiness report path that the GUI and future CLI can reuse. It should inspect saved mesh devices, classify readiness using existing codex_devices helpers, and produce actionable next steps per worker without exposing secrets or requiring UI changes.

Preferred shape:
- Add small backend helpers rather than large GUI rewrites.
- Reuse codex_devices.py, codex_team.py, and existing test style.
- Include blocker categories for local ready, SSH auth denied, Tailscale SSH approval required, offline/timeout, missing project, missing Codex, and stale checkout when detectable.
- Add unit tests for the report generation and classification.
- Keep remote command paths deterministic and metadata-safe.
- Do not commit local ~/.config/codex-gui/devices.json, raw logs, tokens, sudo codes, or machine-private output.

Validation required:
- python3 -m unittest discover -s tests
- python3 -m py_compile codex_devices.py codex_gui.py codex_actions.py codex_team.py codex_setup.py codex_quality.py

Deliverable:
Commit a focused change on branch lane/core-systems and push it. In your final handoff, include changed files, commands run, risks, and the exact next action you want the Commander to take.'
```

## Commit And Push

After the change and validation pass:

```bash
git status --short
git diff --stat
git add <changed-files>
git commit -m "Add mesh readiness reporting"
git push -u origin lane/core-systems
```

If no implementation change is safe, do not force a commit. Write a handoff that
explains the blocker and the smallest next step.

## Handoff Format

Send this back to Commander:

```text
Role: Core Systems Engineer
Device: atlas-builder
Branch: lane/core-systems
Commit:

Changed:
- file: reason

Validation:
- command: result

Risks:
- risk or none

Next:
- exact recommended next action
```

Best return path:

```bash
git push -u origin lane/core-systems
```

Optional Taildrop copy:

```bash
cat > /tmp/atlas-builder-handoff.txt <<'EOF'
Role: Core Systems Engineer
Device: atlas-builder
Branch: lane/core-systems
Commit:

Changed:
- 

Validation:
- 

Risks:
- 

Next:
- 
EOF

tailscale file cp /tmp/atlas-builder-handoff.txt atlas-ubuntu:
```
