# Codex Control

Codex Control is a local GTK workstation for the Codex CLI on Linux.

It uses an embedded VTE terminal when available, with Konsole as a detached
fallback. Codex still runs as the real CLI/TUI, so keyboard handling, approvals,
streaming output, and shell behavior stay intact while the GUI adds project,
thread, config, profile, Git, and health workflows around it.

## Run

```bash
codex-gui
```

Startup now runs a launcher preflight by default. If checks return warning/blocker,
`codex-gui` will stop and print remediation steps.

```bash
codex-gui --self-check            # text report
codex-gui --self-check --json      # machine-readable report
codex-gui --self-check --project /path/to/project  # target project
codex-gui --force-start            # force launch despite warning-level checks
```

Or directly:

```bash
python3 codex_gui.py
```

## Atlas Builder Web Monitor

Launch the web monitor from this machine (SSH-capable commander node):

```bash
bash scripts/run-atlas-builder-monitor.sh \
  --host atlas-builder \
  --user ao \
  --bind 127.0.0.1 \
  --port 9760
```

Open in browser:

```text
http://127.0.0.1:9760
```

Defaults:

- host: `atlas-builder`
- user: `ao`
- port: `9760`
- poll interval: `4s`
- endpoint: `/api/metrics`

## Atlas Builder Full Access

Use the commander helper for direct shell, command, and privileged actions on atlas-builder:

```bash
bash scripts/atlas-builder-full-access.sh
```

Examples:

```bash
# interactive shell (legacy positional form)
bash scripts/atlas-builder-full-access.sh atlas-builder ao

# interactive shell (explicit host/user flags)
bash scripts/atlas-builder-full-access.sh --host atlas-builder --user ao shell

# run one remote command
bash scripts/atlas-builder-full-access.sh atlas-builder ao command "systemctl --user status"

# open root shell (password required on builder)
bash scripts/atlas-builder-full-access.sh atlas-builder ao sudo

# run one privileged command
bash scripts/atlas-builder-full-access.sh atlas-builder ao sudo "journalctl -u sshd -n 80"

# open monitor fast path
bash scripts/atlas-builder-full-access.sh atlas-builder ao monitor

# open persistent tmux session (keeps shell alive across reconnects)
bash scripts/atlas-builder-full-access.sh atlas-builder ao tmux

# open persistent root tmux session
bash scripts/atlas-builder-full-access.sh atlas-builder ao tmux-root
```

## Fastest Builder Access

One command for persistent root access:

```bash
bash scripts/atlas-builder-fast.sh
```

Preferred one-phrase launchers:

```bash
builder    # same as above
fab        # backward-compatible alias phrase
```

Optional quick overrides:

```bash
# open regular shell
bash scripts/atlas-builder-fast.sh shell

# run command mode
bash scripts/atlas-builder-fast.sh command "systemctl --user status"
```

## Builder Ops Commander

Use one entry point for day-to-day builder operations:

```bash
bash scripts/atlas-builder-ops.sh
bash scripts/atlas-builder-ops.sh status
bash scripts/atlas-builder-ops.sh shell
bash scripts/atlas-builder-ops.sh command "systemctl --user status"
bash scripts/atlas-builder-ops.sh root
bash scripts/atlas-builder-ops.sh monitor

# Reduce noisy startup output when running commands
bash scripts/atlas-builder-ops.sh --quiet status
```

One-phrase compatibility:

```bash
fab status      # or: builder status
fab shell       # or: builder shell
```

Set host/user defaults once per workstation:

```bash
export ATLAS_BUILDER_HOST=atlas-builder
export ATLAS_BUILDER_USER=ao
export ATLAS_BUILDER_SESSION=atlas-builder
```

## Headless Team Ops (Commander)

Run the full atlas team lifecycle from terminal using the same role model as the GUI:

```bash
python3 codex_team_ops.py --json discover
python3 codex_team_ops.py --json check
python3 codex_team_ops.py --json roles
python3 codex_team_ops.py --json prepare --check
python3 codex_team_ops.py --json sync
python3 codex_team_ops.py --json launch
python3 codex_team_ops.py --json collect
python3 codex_team_ops.py --json doctor
python3 codex_team_ops.py --json summary
```

The same command set is available as a short script:

```bash
bash scripts/codex-team-ops.sh discover
bash scripts/codex-team-ops.sh prepare --check
bash scripts/codex-team-ops.sh status
bash scripts/codex-team-ops.sh launch --sync

# installed script shortcut after pip install:
codex-team-ops discover
```

Role defaults in the default naming model:

- `atlas-ubuntu` (local): Commander / Integrator
- `atlas-builder`: Core Systems Engineer
- `atlas-main`: Product / GTK UX Engineer
- `atlas-cockpit`: Verifier / Release Engineer

Runbook references:

- [Multi-device orchestration](docs/MULTI_DEVICE_ORCHESTRATION.md)
- [Team roles](docs/TEAM_ROLES.md)

## Install

From a clone:

```bash
python3 -m pip install --user .
```

That installs the `codex-gui` launcher and keeps the app runnable from a
GitHub checkout without editing paths.

On offline or restricted workers, make sure Python build tooling is already
available before installing from the clone: `setuptools>=68` and `wheel` are
declared in `pyproject.toml` and are normally downloaded by pip on networked
hosts.

Detailed install and release notes:

- [Install guide](docs/INSTALL.md)
- [Public release checklist](docs/PUBLIC_RELEASE.md)
- [Codex team operating model](docs/TEAM_ROLES.md)
- [Multi-device orchestration runbook](docs/MULTI_DEVICE_ORCHESTRATION.md)
- [Atlas Builder core systems mission](docs/missions/ATLAS_BUILDER_CORE_SYSTEMS.md)
- [Atlas Main bootstrap Builder mission](docs/missions/ATLAS_MAIN_BOOTSTRAP_BUILDER.md)

## Included Workflows

- Embedded terminal Codex sessions
- One-click Max Power sessions backed by the `maximum-power` profile
- First-screen Operator Console with backend-synthesized readiness, next action,
  Codex health, project posture, Autopilot state, run ledger, agents, and receipt
  signals.
- Quality Gate that plans and runs the current project's validation checks,
  `codex doctor --summary --ascii`, and desktop-entry validation from the GUI,
  then saves a copyable report in `~/.config/codex-gui/quality-report.json`.
- Command Palette and action graph for searching and running major app
  capabilities from the Workbench or full Palette page. `Ctrl+K` opens the full
  action surface. Palette actions now write concise feedback to the full Palette
  page and the Workbench rail, show a redacted "would run" preview, and block
  known-incomplete actions until required prompt or selection state is present.
  They also keep durable last-result history per action with rerun, copy, and
  open-log controls.
- Context Packet that synthesizes the current prompt, project intelligence,
  launch preflight, Quality Gate, Mission Architect, Autopilot history, run
  ledger, and receipt posture into one Codex-ready brief. It can be refreshed,
  copied, saved to `~/.config/codex-gui/context-packet.md`, or applied as the
  active launch prompt. `Ctrl+J` opens the full packet page.
- Milestone Roadmap that ranks the next best upgrades from current project,
  quality, context, mission, run, Autopilot, and receipt state. It can apply the
  selected milestone as the active prompt, copy the roadmap, save it to
  `~/.config/codex-gui/milestone-roadmap.md`, or open a full Roadmap page.
  `Ctrl+Shift+M` opens the roadmap.
- Run Orchestrator that prepares a metadata-safe launch package from Context
  Packet, Milestone Roadmap, Launch Preflight, Quality Gate, command preview,
  run ledger, terminal availability, and receipt posture. It can prepare, run,
  copy, and save packages to `~/.config/codex-gui/launch-package.md`.
  `Ctrl+Shift+O` opens the full orchestration page.
- Device Mesh for connecting your other Codex machines over SSH. It can discover
  active Linux/macOS workers from `tailscale status --json`, merge MagicDNS
  devices into the local mesh without duplicating manual entries, preview the
  exact SSH launch and memory-sync commands, open remote Codex sessions in a
  terminal, and sync the explicit portable memory file with `rsync`.
- Codex Team mode on the Mesh page. It probes trusted Tailscale devices, assigns
  each ready machine a focus lane such as Coordinator, Backend Builder, UI
  Polish, or Verifier, writes a shared ledger plus per-lane prompt files, syncs
  the package to each remote device, launches terminal-backed Codex lanes, and
  collects lane handoffs/results back into the local run folder. The current
  workstation is treated as a local coordinator worker and runs direct local
  probe/launch commands instead of SSHing into itself. Team runs are reloadable
  after app restart and can generate a combined `summary.md` from collected lane
  artifacts. The handoff bus writes `out/handoff-bus.md` and
  `out/team-summary.md`, then redistributes that context to every current team
  device for the next pass. Failed bus deliveries are persisted in
  `out/handoff-bus-report.json`, and the GUI can retry only the failed devices.
- Premium visual-system overlay with named color tokens, consistent panel,
  row, button, chip, terminal, and rail styling, plus visual audit tests and a
  Quality Gate check that guard core selectors and palette diversity.
- Workstation layout persistence for the default maximized window, sidebar,
  control rail, Workbench split, and report/detail split panes.
- Palette previews are generated by [codex_palette.py](codex_palette.py), with
  prompt-safe command summaries, action surface/risk labels, and readiness
  requirements for selection-dependent actions. The same module stores
  metadata-only palette action history.
- Profile launchers and command preview
- Mission Architect that synthesizes the current project, prompt variants,
  launch preflight, agent lanes, validation commands, and receipt posture into
  one executable blueprint with Use Prompt, Plan Agents, Run Max, and copyable
  details.
- Codex Autopilot that turns the Mission Architect blueprint into a durable
  replay package with `autopilot.sh`, `blueprint.md`, `manifest.txt`, JSON event
  stream, and final answer under `~/.config/codex-gui/autopilot/`. The
  Autopilot page and Workbench panel can prepare, terminal-replay, tracked-run,
  stop, open, copy, and remove history records. Tracked runs persist PID, exit
  code, start/finish timestamps, log tail, and final answer while the metadata
  file stores hashes and paths rather than raw prompts or raw command bodies.
- Launch Preflight for advisory readiness checks before running Codex. It checks
  the selected project, CLI availability, auth state, terminal path, prompt
  shape, profile install state, Git gate, validation commands, and Atlas receipt
  readiness without disabling intentional high-power modes.
- Prompt Lab that enhances rough requests into selectable Codex-ready prompts
- AI Enhance option that asks Codex to draft model-generated prompt variants
  through a read-only ephemeral `codex exec` call, with local fallback
- Session Workspace for saved prompts, runnable workspace sessions, and
  thread-backed resume/fork launches from one panel
- Project Intelligence panel with stack detection, Git state, changed files,
  recent Codex threads, and one-click validation commands
- Agent Studio that plans Architect, Builder, Reviewer, UI Polish, and Verifier
  lanes, isolates them in Git worktrees when available, and can launch all lanes
  in terminal-backed Codex `exec` sessions
- Results Console that refreshes lane status, opens lane folders, shows diffs,
  copies summaries, applies tracked worktree diffs, and merges branch-backed lanes
- Persistent Agent Run history with load, delete, copy, and save-current actions
  for multi-agent plans and collected lane results
- Execution Monitor for tracked `codex exec --json` lane runs with live status,
  exit codes, log tails, final-message files, stop controls, and artifact folders
- Receipt Vault for metadata-only Atlas receipts around Codex launches. It can
  stamp the current command, auto-stamp direct Codex runs, verify receipts, and
  replay the retained receipt chain without embedding raw prompts, raw command
  bodies, terminal output, logs, or model output.
- Run Ledger for persistent metadata-only launch records. Embedded, external,
  headless, manual stamp, and monitored agent launches are recorded with status,
  surface, profile, command hash, prompt hash, and linked receipt hashes.
- External terminal launch
- One-shot headless `codex exec --json`
- Local thread browser with resume, fork, and archive
- Project scanner with Git branch and dirty-state summaries
- Git status, diff stat, log, worktree list, worktree create, and prune
- `~/.codex/config.toml` editor
- Profile preset installer
- `codex doctor --json` dashboard
- Codex update, login, and app-server daemon controls

## Notes

- The app stores preferences in `~/.config/codex-gui/config.json` and saved
  workspace sessions in `~/.config/codex-gui/sessions.json`.
  Window and split-pane layout is stored in the same config file.
- Agent Run history is stored in `~/.config/codex-gui/agent-runs.json`.
- Quality Gate reports are stored in `~/.config/codex-gui/quality-report.json`.
- Palette action history is stored in
  `~/.config/codex-gui/palette-history.json`, with a copyable markdown log at
  `~/.config/codex-gui/palette-history.md`.
- Device Mesh records are stored in `~/.config/codex-gui/devices.json`.
- Codex Team packages are stored under `~/.config/codex-gui/team/`. Prompt files
  and the shared ledger are explicit local files synced only to trusted devices
  you launch. Lane handoffs, final messages, status files, and generated
  summaries remain in the run folder. The handoff bus lives under each run's
  `out/` directory so every lane can read the same post-collection context.
  Bus sync failures are written to `out/handoff-bus-report.json` for later
  retry and review.
  Untrusted devices such as `atlas-security` are excluded by name.
- Portable Codex Control memory is stored in
  `~/.config/codex-gui/memory.md`. It is an explicit local file for trusted
  devices, not ChatGPT's private account memory store. To carry ChatGPT memory
  into Codex Control, copy intentional saved-memory/custom-instruction details
  or import selected lines from a ChatGPT data export. The GUI does not store
  SSH passwords, sudo codes, API keys, or tokens.
- Context Packet saves are stored in `~/.config/codex-gui/context-packet.md`.
- Milestone Roadmap saves are stored in
  `~/.config/codex-gui/milestone-roadmap.md`.
- Run Orchestrator package saves are stored in
  `~/.config/codex-gui/launch-package.md`.
- Execution Monitor artifacts are stored in `~/.config/codex-gui/executions/`.
- Autopilot package history is stored in
  `~/.config/codex-gui/autopilot-runs.json`; replay scripts and blueprints live
  in per-run folders under `~/.config/codex-gui/autopilot/`, with tracked
  execution logs written to each package's `autopilot.log`.
- Receipt Vault events and receipts are stored in
  `~/.config/codex-gui/receipts/`. Atlas is used only as a receipt engine when
  an `atlas-trust-infrastructure` checkout is available.
- Run Ledger records are stored in `~/.config/codex-gui/command-runs.json` and
  deliberately avoid raw prompts, raw command bodies, terminal output, logs, and
  model output.
- The profile presets live in `~/.codex/*.config.toml` and can be used from the
  terminal with `codex --profile <name>`.
- `codex-power` starts Codex with the `maximum-power` profile and live search.
- The Workbench opens in Max Power mode by default.
- The Operator Console is generated from local health, preflight, project,
  session, Autopilot, run-ledger, agent, and receipt state so the first screen is
  an operational command deck rather than static decoration.
- Context Packet is local and explicit. It redacts obvious token/password-style
  values and only becomes the Codex prompt when you choose `Use`.
- Milestone Roadmap is also local and explicit. It turns "next milestone" into a
  concrete Codex prompt only when you choose `Use Next`.
- Run Orchestrator keeps its saved launch package metadata-oriented. It stores
  prompt and command hashes plus a redacted command preview; actual execution
  still happens through the normal Codex terminal path.
- The visual system is layered over the original GTK CSS from
  [codex_visual.py](codex_visual.py), so the app can keep improving without
  turning every new panel into a one-off theme. The Quality Gate includes the
  same audit when the visual module is present.
- Prompt choices are generated locally first, so you can choose what is passed to
  Codex before running. They include the selected project snapshot when available.
- `AI Enhance` is optional and slower; it generates deeper prompt variants but
  never replaces the local fallback.
- Launch Preflight is advisory. It blocks only clearly broken launch paths such
  as a missing project, missing Codex CLI, or `codex exec` without a prompt.
- Mission Architect is local and reversible by default. It plans and prepares the
  launch path; actual Codex execution still uses the embedded or external
  terminal unless you explicitly run it.
- Autopilot is opt-in from the Mission Architect. It uses terminal execution so
  output, approvals, validation, and shell behavior remain inspectable.
- `gpt-5.5` is the best default profile. `gpt-5.3-codex-spark` is included as a
  fast ChatGPT Pro option.
