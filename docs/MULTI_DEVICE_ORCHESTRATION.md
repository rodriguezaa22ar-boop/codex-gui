# Multi-Device Orchestration (codex-gui)

This is the source-of-truth runbook for running the team workflow across:

- `atlas-ubuntu` (commander/integrator)
- `atlas-builder` (headless NixOS core systems worker)
- `atlas-main` (Fedora HP laptop UI/product lane)
- `atlas-cockpit` (Fedora Kinoite verification/release lane, when SSH is reachable)

Keep each Codex lane in a clean, scoped state and pull/push through Git.

## 1) Device Roles and Mapping

Use explicit host names in Tailnet discovery:

```bash
# Tailnet discovery in Mesh page
Discover Tailnet -> Check Fleet
```

Expected role mapping after probe:

- `atlas-ubuntu` → Coordinator / Integrator  
- `atlas-builder` → Core Systems Engineer  
- `atlas-main` → Product / GTK UX Engineer  
- `atlas-cockpit` → Verifier / Release Engineer  

If any device does not map as expected, update its DNSName/hostname in Tailscale and re-run discovery.

## 2) Preflight before any team action

1. On each worker: confirm project is on latest `main` and no unrelated local edits.
2. From commander, run:

```bash
cd ~/Projects/codex-gui
python3 -m py_compile codex_devices.py codex_gui.py codex_team.py
python3 -m unittest tests.test_devices
```

3. Run `Discover Tailnet` then `Check Fleet`.
4. Confirm ready set is what you expect in Mesh.

Do not start a team run while a lane is blocked.

## 2b) Commander headless flow (for non-GUI sessions)

Use this when `builder`/`main`/`cockpit` sessions are already running and you need
a terminal-native control flow:

```bash
cd ~/Projects/codex-gui
python3 codex_team_ops.py --json discover
python3 codex_team_ops.py --json check
python3 codex_team_ops.py --json prepare --check
python3 codex_team_ops.py --json sync
python3 codex_team_ops.py --json launch --sync
python3 codex_team_ops.py --json collect
python3 codex_team_ops.py --json doctor
python3 codex_team_ops.py --json summary
```

`doctor` includes sanitized readiness rows for each saved device; it does not
emit raw SSH or probe output.
Use `python3 codex_team_ops.py --json check --no-persist` in read-only verifier
lanes when probing is useful but `devices.json` must not be updated.

You can also use the launcher script:

```bash
bash scripts/codex-team-ops.sh status
```

`discover` and `prepare` both read and update `~/.config/codex-gui/devices.json`. Keep
`~/.config/codex-gui/team/` clean across attempts to make failure recovery visible.

## 3) Run workflow (4-device team)

On the Mesh page:

1. **Prepare Team** (builds lane prompts and role manifests)
2. **Sync Bus** (push handoff state)
3. **Launch Team** (starts one lane per ready device)
4. **Collect Team** (pulls out final lane artifacts)

If one device is down (e.g., SSH refused), continue with remaining ready devices and resolve later.

## 4) Push protocol (“ready and clear”)

Use this exact process so every device can sync safely.

### Worker lane (recommended)

```bash
git fetch origin main
git checkout main
git pull --ff-only origin main
git checkout -b lane/<role-name>
# make one scoped change
python3 -m py_compile codex_devices.py codex_gui.py codex_team.py
python3 -m unittest tests.test_devices
git add -A
git commit -m "<role>: short scoped change summary"
git push -u origin HEAD
```

### Commander integrate

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff <worker-branch>
python3 -m unittest tests.test_devices
python3 -m py_compile codex_devices.py codex_gui.py codex_team.py
python3 -m unittest discover -s tests
git push origin main
```

Use full suite + local smoke checks before final push.

## 5) Current repository note

This repo currently includes:

- Dynamic Codex launcher resolution for heterogeneous nodes (`~/.npm-global`, `~/.local`, `/usr/local/bin`, `/usr/bin`, PATH)
- Updated mesh probe/launch scripts that no longer assume a fixed `~/.local/bin/codex` binary.
