# Atlas Main Mission: Product Pulse Lane

Issued by `atlas-ubuntu` Commander / Integrator.

You are `atlas-main`, the Product / GTK UX Engineer for Codex Control.

Your current lane is already in progress locally. Preserve that work and finish
it on a product branch. Do not reset the checkout to chase a remote pull if it
would discard local edits.

## Current Situation

- Baseline on this node: `fdd206a`
- Local modified file: `codex_gui.py`
- The current slice is a Mesh launch-console readiness pulse:
  - fleet pulse summary label
  - readiness chips
  - source-test coverage in `tests/test_gui_source.py`

## Required branch

```bash
cd ~/Projects/codex-gui
git status --short
git checkout -B lane/product-pulse
```

## Mission

Finish the launch-console pulse UX cleanly.

Stay inside the product/UI boundary:

- Mesh launch console only
- No broad backend rewrites
- Reuse existing chip, label, and operator-console patterns
- Keep dense operational UI, not decorative UI
- Keep text tight enough for GTK rows/chips/tooltips

Target outcome:

- clear fleet pulse summary
- ready / blocked / review / offline counts
- readable tooltip detail
- source tests that lock the feature surface

## Validation

Run:

```bash
python3 -m unittest tests.test_gui_source -q
python3 -m pytest -q
```

If the slice is safe and passing:

```bash
git add codex_gui.py tests/test_gui_source.py
git commit -m "Add mesh launch readiness pulse"
git push -u origin lane/product-pulse
```

## Handoff format

```text
Role: Product / GTK UX Engineer
Device: atlas-main
Branch: lane/product-pulse
Commit:

Changed:
- file: reason

Validation:
- command: result

Risks:
- risk or none

Next:
- exact Commander action needed
```
