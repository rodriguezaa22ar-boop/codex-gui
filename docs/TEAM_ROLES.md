# Codex Team Roles

Codex Control assigns stable lanes to trusted devices so the team does not
duplicate work.

## Current Device Plan

- This device: Coordinator. Integrates handoffs, keeps scope tight, and decides
  merge order.
- `atlas-builder`: Backend Builder. Owns core implementation, mesh
  orchestration, setup readiness, persistence, packaging, and tests.
- `atlas-ubuntu`: Verifier. Owns compile, unit tests, Quality Gate, Codex
  doctor, package validation, pull checks, and regression notes.
- `atlas-cockpit`: UI Polish. Owns GTK layout, hierarchy, text fit,
  interaction states, and screenshot readiness.

## Boundaries

- Backend Builder should avoid broad visual redesign unless exposing backend
  state requires UI plumbing.
- UI Polish should avoid backend behavior changes unless they are small and
  local to the UI control.
- Verifier should prefer exact failing commands and logs over broad fixes.
- Coordinator should integrate and resolve conflicts rather than owning a large
  feature lane.

The role registry lives in `codex_team.py`; Mesh team package generation records
the resolved role ID in each assignment manifest.

## Atlas Builder Setup

`atlas-builder` should keep a clean checkout at:

```bash
~/Projects/codex-gui
```

Because it is NixOS, use the repo shell before running Python checks:

```bash
cd ~/Projects/codex-gui
nix-shell --run "python3 -m unittest discover -s tests"
```
