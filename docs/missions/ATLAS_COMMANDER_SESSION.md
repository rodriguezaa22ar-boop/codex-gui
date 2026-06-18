# Atlas Team Commander Session

Date: 2026-06-18
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

- Keep this session role-split enforced while the team pushes forward.
- Commander remains responsible for final integration and branch hygiene.
