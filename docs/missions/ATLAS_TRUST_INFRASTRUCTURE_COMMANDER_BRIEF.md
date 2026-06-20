# Atlas Trust Infrastructure Commander Brief

Date: 2026-06-20
Project: codex-gui
Target repo: `~/Projects/atlas-trust-infrastructure`

## Commander Status

The Atlas trust repository has been reviewed in depth and validated on this
device after installing the missing local tooling.

Current local validation state:

- `./bin/dev-test`: `182 tests, 0 failures`
- `nix-shell --run './bin/dev-qa'`: `qa: ok`

Environment work completed on this machine:

- installed `bats`
- installed `nix-shell`
- added user `ao` to `nix-users`
- initialized `nixpkgs` channel so `shell.nix` resolves and runs

## What The Repo Actually Is

`atlas-trust-infrastructure` is the public trust and reviewer surface for
Atlas, not the private implementation/runtime source.

Boundary:

- private repo: `atlas-lab-toolkit`
- public repo: `atlas-trust-infrastructure`

The public repo contains:

- trust model and bounded claims
- schemas and examples
- governance contracts
- retained release and reviewer evidence
- validation tooling
- public-safe shell-native proof surfaces

It does not claim to be the full runtime authority for external systems.

## Real Architecture

The repo is still rooted in the older shell-native lab architecture rather than
an abstract docs-only model.

Real substrate:

- file-backed source of truth
- env records for durable metadata
- JSONL/NDJSON append-only records
- Markdown and JSON packets for retained proof
- shell entrypoints and validators instead of a database/server primary runtime

Primary domain split:

- `labctl`: layout, sessions, release build, deploy activation
- `wiremap`: recon, capture, saved-run analysis, intel publication
- `vector`: ranked action lanes and bounded backend runs
- `intelctl`: direct shared-intel inspection
- `atlas`: proof/control front-end over those domains

Shared intel spine:

- `state/intel/observations.jsonl`
- `state/intel/entities.jsonl`
- `state/intel/outcomes.jsonl`
- `state/intel/relationships.jsonl`

## Atlas Gravity Wells

The implementation weight sits in `tools/atlas/lib/`.

Largest modules:

- `flows.sh`
- `release.sh`
- `findings.sh`
- `web.sh`
- `production.sh`

That means the current Atlas center of gravity is:

- business-flow evidence
- release trust and replay
- findings lifecycle
- bounded web assessment
- production/readiness contracts

## Implemented Versus Contract-Only

Implemented and validated:

- receipt create/verify/replay
- generic external event import
- approval request/verify/approve/expire event path
- evidence-envelope validation
- operation trust chain
- release packet / verify / replay
- release artifact manifest / verify
- SLSA reference verification
- business-flow packet / verify / assurance / trust-chain
- reviewer package generation
- full shell test and QA gates

Governance contracts with validation but still intentionally bounded:

- capability manifest
- adapter registry
- policy plane
- approval plane
- evidence plane
- governance integration map
- governance decision vocabulary

These are real contracts and validators, but they are not yet a live
orchestration/runtime authority layer.

## Hard Numbers

- capabilities declared: `16`
- adapters declared: `9`
- retained docs under `docs/retention/`: `329` files
- examples: `22` files
- root `schemas/`: `8` files
- `tests/atlas.bats`: `15706` lines

Capability IDs:

- `atlas.status.read`
- `atlas.production.verify`
- `atlas.release.verify`
- `atlas.release.packet`
- `atlas.receipt.create`
- `atlas.receipt.verify`
- `atlas.receipt.replay`
- `atlas.receipt.import_generic_event`
- `atlas.public_export.check`
- `atlas.reviewer.package`
- `atlas.evidence.sufficiency.review`
- `atlas.policy.evaluate`
- `atlas.approval.request`
- `atlas.host.check`
- `atlas.adapter.import`
- `atlas.agent.tool.exec`

Adapter IDs:

- `generic.external_event.import`
- `github.actions.import`
- `github.release.verify`
- `scanner.finding.import`
- `ticket.issue.import`
- `ticket.transition.propose`
- `ai_agent.action.import`
- `cloud.change.propose`
- `business_flow.event.import`

## Pressure Points

The repo is credible, but its weakest seam is still claim-to-enforcement
alignment.

Most important pressure points:

1. Keep every important claim mapped to:
   - an enforced check
   - a retained proof artifact
   - or an explicitly bounded aspiration
2. Reduce drift between docs, wrappers, and top-level QA.
3. Preserve the metadata-only boundary as features expand.
4. Prevent governance docs from implying live runtime authority before it
   exists.
5. Keep release trust, reviewer proof, and business-flow evidence coherent as a
   single system rather than separate stories.

## Immediate Commander Takeaways

- Atlas trust infrastructure is not vapor. It has real shell implementation and
  real validation gates.
- The best leverage from `codex-gui` is orchestration, verification, and
  claim-enforcement alignment, not more high-level prose.
- The repo is ready for disciplined team work because the current baseline is
  green on this machine.

## Recommended Team Lanes

If Commander reactivates the multi-lane team against Atlas later, use this
split:

- Core Systems / Proof Enforcement
  - tighten claim-to-validator coverage
  - close QA/governance drift
  - harden replay/verification invariants

- Product / Reviewer Experience
  - improve reviewer-facing legibility
  - simplify verify/replay/operator flows without weakening boundaries

- Release / Verification
  - fresh clone checks
  - source archive checks
  - retained release trust replay
  - SLSA and manifest verification

## Commander Rule

Do not treat Atlas as “done because tests are green.”

Green tests mean:

- the current public contracts are internally coherent on this machine
- the shell-native proof surface is operational

They do not mean:

- live governance enforcement exists
- external certification exists
- enterprise readiness is proven
- claims are fully saturated by enforcement
