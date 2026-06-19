# Atlas Team Commander Session

Date: 2026-06-19
Project: codex-gui

## Active Commander

- `atlas-ubuntu`: **Commander / Integrator** (I am this commander)

## Team Roles

- `atlas-builder`: **Core Systems Engineer**
  - Responsible for reliability, mesh orchestration, setup automation, SSH/Tailscale behavior,
    worker lifecycle, packaging, and defensive diagnostics.

- `atlas-main`: **Product / GTK UX Engineer**
  - Responsible for operator-facing workflow: Mesh, Command Palette, agent/team surfaces,
    and quality/clarity of the GUI experience.

- **Verifier / Release lane**
  - Any clean machine with git access is assigned this lane when available.
  - Responsible for fresh-clone install checks, release-readiness checks, and regression validation.

## Working Protocol

1. Source of truth is `origin/main`.
2. No free-edit on `main`; use lane branches.
3. Mandatory lane branches:
   - `lane/core-systems`
   - `lane/product-ux`
   - `lane/release-verify`
4. Each lane ships one focused patch, runs local validation, and pushes a handoff with
   changed files + risks + exact next action.
5. Commander pulls, reviews, validates (`python3 -m unittest discover -s tests` + required checks),
   merges only reviewed and passing patches, and pushes.

## Immediate Operational Rule

- `atlas-builder` and `atlas-main` can execute in parallel only inside their role boundaries.
- If a blocker appears, create a short handoff artifact and report it immediately before continuing.

## Default Sync Commands

```bash
git fetch --all --prune
git checkout main
git pull --ff-only origin main
```

## Lane Baselines

- Core Systems / Backend baseline:
  - `python3 -m unittest discover -s tests`
  - `python3 -m py_compile codex_devices.py codex_gui.py codex_actions.py codex_team.py codex_setup.py codex_quality.py`

- Verification baseline:
  - Same as above, plus install docs check in `docs/INSTALL.md` and public release checklist.

## Priority Right Now

- Keep fleet state coherent across `atlas-ubuntu`, `atlas-builder`,
  `atlas-main`, and `atlas-cockpit`.
- Preserve `atlas-main` local product-lane work instead of overwriting it.
- Keep `atlas-builder` on backend/core systems only.
- Keep `atlas-cockpit` on verification/release only.
- Commander remains responsible for final integration and branch hygiene.

## Fleet Baseline Right Now

- `atlas-ubuntu`: `d731ecf`
- `atlas-builder`: `d731ecf`
- `atlas-cockpit`: `d731ecf`
- `atlas-main`: `fdd206a` plus local uncommitted `codex_gui.py` work

Important:

- `atlas-cockpit` GitHub SSH auth has been repaired and direct `git pull` now works.
- `atlas-main` is the active product lane. Do not auto-reset or force-pull it.

## Active Work Split

- `atlas-builder`
  - branch: `lane/core-systems`
  - target: backend readiness and orchestration hardening

- `atlas-main`
  - branch: `lane/product-pulse`
  - target: finish launch-console readiness pulse and related source tests

- `atlas-cockpit`
  - branch: `lane/release-verify`
  - target: fresh verification, docs accuracy, install/launch proof
