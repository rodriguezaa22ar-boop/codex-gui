# Atlas Trust Infrastructure Unblock Checklist

Date: 2026-06-20
Project: codex-gui

## Current External Blockers

### 1. Remote Lane Access

All three remote nodes currently require renewed Tailscale SSH approval:

- `atlas-builder`
- `atlas-main`
- `atlas-cockpit`

Commander follow-up cannot continue until those approvals are granted.

### 2. Pull Request Creation

The branch is already pushed:

- branch: `commander/atlas-trust-dispatch`
- commit: `d59dab7`

Two PR creation paths were attempted and blocked:

- `gh pr create`: blocked because local GitHub CLI is not authenticated
- GitHub connector PR create: blocked with `403 Resource not accessible by integration`

## Fastest Recovery Path

Open this URL in a browser:

```text
https://github.com/rodriguezaa22ar-boop/codex-gui/pull/new/commander/atlas-trust-dispatch
```

Use this PR title:

```text
Add Atlas trust infrastructure commander dispatch
```

Use this PR body:

```md
## Summary
Add commander-side Atlas trust infrastructure mission artifacts and lane status tracking.

## Included
- Atlas repo commander brief
- team dispatch doc
- lane status snapshot including current Tailscale SSH approval blocker

## Notes
- Atlas validation baseline was confirmed locally on the commander node before dispatch.
- Remote lane follow-up is currently blocked by Tailscale SSH re-approval on atlas-builder, atlas-main, and atlas-cockpit.
```

## Optional Local CLI Recovery

If local GitHub CLI auth is restored later:

```bash
gh auth login
cd ~/Projects/codex-gui-atlas-dispatch
gh pr create \
  --repo rodriguezaa22ar-boop/codex-gui \
  --base main \
  --head commander/atlas-trust-dispatch \
  --draft \
  --title "Add Atlas trust infrastructure commander dispatch" \
  --body-file docs/missions/ATLAS_TRUST_INFRASTRUCTURE_PR_BODY_2026-06-20.md
```

## Remote Lane Recovery

Once Tailscale SSH approval is restored:

1. re-check `atlas-builder`, `atlas-main`, and `atlas-cockpit`
2. confirm each node still has its dispatch file under `/tmp/`
3. collect branch and commit state from `~/Projects/atlas-trust-infrastructure`
4. pull first lane handoff back into commander flow
