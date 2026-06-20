# Atlas Trust Infrastructure Team Dispatch

Date: 2026-06-20
Issued by `atlas-ubuntu` Commander / Integrator.
Control repo: `codex-gui`
Target repo: `~/Projects/atlas-trust-infrastructure`

## Commander Baseline

Atlas trust infrastructure has been reviewed in depth on the commander node.

Validated baseline on this machine:

- `./bin/dev-test`: `182 tests, 0 failures`
- `nix-shell --run './bin/dev-qa'`: `qa: ok`

Commander research artifact:

- `docs/missions/ATLAS_TRUST_INFRASTRUCTURE_COMMANDER_BRIEF.md`

## Mission Goal

Move `atlas-trust-infrastructure` closer to full claim-to-enforcement
alignment without weakening the metadata-only boundary.

Primary commander objective:

Every important Atlas public claim should map to one of:

1. an enforced check
2. a retained proof artifact
3. an explicitly bounded aspiration

## Team Split

### Lane 1: Core Systems / Proof Enforcement

Default device: `atlas-builder`
Branch: `lane/core-systems`

Scope:

- tighten validation coverage for existing public claims
- close drift between wrappers, docs, and top-level QA
- harden replay, verification, and fail-closed behavior
- do not do broad UX/doc marketing rewrites

Best first targets:

- top-level QA coverage alignment
- governance/export-boundary enforcement alignment
- targeted validator additions for claims already made in docs

Required validation:

```bash
cd ~/Projects/atlas-trust-infrastructure
./bin/dev-test
nix-shell --run './bin/dev-qa'
```

### Lane 2: Product / Reviewer Experience

Default device: `atlas-main`
Branch: `lane/product-pulse`

Scope:

- improve reviewer/operator legibility only
- simplify verify/replay/readiness understanding
- preserve the current bounded claim language
- do not imply runtime authority that does not exist

Best first targets:

- reviewer quickstart tightening
- command-reference/readme drift reduction
- clearer explainability around release/proof flows

Required validation:

```bash
cd ~/Projects/atlas-trust-infrastructure
./bin/dev-test
./bin/export-public-trust --check
```

### Lane 3: Release / Verification

Default device: `atlas-cockpit`
Branch: `lane/release-verify`

Scope:

- fresh-clone verification
- source-archive verification
- retained release trust replay
- SLSA / release manifest verification
- docs accuracy against actual commands

Best first targets:

- verify clean-clone path from scratch
- verify source-archive path stays read-only and bounded
- prove retained release-trust and production-explain paths

Required validation:

```bash
cd ~/Projects/atlas-trust-infrastructure
nix-shell --run './bin/dev-qa'
./bin/export-public-trust --check
```

## Lane Rules

- No one weakens the metadata-only boundary.
- No one adds runtime authority claims without implemented enforcement.
- No lane treats green tests as permission to overclaim.
- Changes should stay focused and lane-local.
- Handoffs must include exact commands run and exact remaining gap.

## First Commander Assignment

Start with `atlas-builder`.

Reason:

- the highest leverage first move is claim-to-validator alignment
- the repo is already green, so the first job is hardening rather than rescue
- builder is the correct lane for backend/proof-enforcement work

## Required Handoff Format

```text
Role:
Device:
Repo:
Branch:
Commit:

Changed:
- file: reason

Validation:
- command: result

Risks:
- risk or none

Next:
- exact commander action needed
```
