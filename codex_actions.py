#!/usr/bin/env python3
"""Searchable action catalog for Codex Control."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    id: str
    title: str
    group: str
    detail: str
    keywords: tuple[str, ...] = ()
    priority: int = 50

    def haystack(self) -> str:
        return " ".join([self.id, self.title, self.group, self.detail, *self.keywords]).lower()


ACTION_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec("run.max", "Run Max", "Codex", "Launch the current prompt in the embedded terminal.", ("start", "interactive", "terminal"), 100),
    ActionSpec("run.review", "Run Review", "Codex", "Run Codex review against the active project.", ("review", "git", "changes"), 84),
    ActionSpec("run.exec", "Exec JSON", "Codex", "Run one-shot codex exec --json for bounded tasks.", ("headless", "json", "automation"), 78),
    ActionSpec("run.external", "Detach Terminal", "Codex", "Launch the current Codex command in an external terminal.", ("konsole", "terminal", "detached"), 72),
    ActionSpec("command.copy", "Copy Command", "Codex", "Copy the exact command that will be launched.", ("clipboard", "shell"), 68),
    ActionSpec("orchestrate.prepare", "Prepare Launch Package", "Orchestrate", "Build a launch package from context, roadmap, preflight, quality, command, ledger, and receipt posture.", ("package", "launch", "run"), 93),
    ActionSpec("orchestrate.run", "Run Launch Package", "Orchestrate", "Run the prepared package through the selected terminal-backed Codex path.", ("package", "launch", "terminal"), 89),
    ActionSpec("orchestrate.copy", "Copy Launch Package", "Orchestrate", "Copy the metadata-safe launch package markdown.", ("clipboard", "package"), 68),
    ActionSpec("orchestrate.save", "Save Launch Package", "Orchestrate", "Write the metadata-safe launch package to the local Codex Control config directory.", ("file", "markdown", "package"), 62),
    ActionSpec("prompt.enhance", "Enhance Prompt", "Prompt", "Generate local prompt variants for the current request.", ("rewrite", "variants", "prompt lab"), 95),
    ActionSpec("prompt.ai", "AI Enhance Prompt", "Prompt", "Ask Codex for deeper prompt variants with local fallback.", ("model", "variants", "prompt lab"), 82),
    ActionSpec("prompt.use", "Use Prompt Choice", "Prompt", "Apply the selected Prompt Lab variant.", ("select", "choice"), 74),
    ActionSpec("prompt.focus", "Focus Prompt", "Prompt", "Move focus to the prompt editor.", ("input", "compose"), 70),
    ActionSpec("context.refresh", "Refresh Context Packet", "Context", "Rebuild the Codex-ready launch packet from project state, checks, mission, runs, and receipts.", ("brief", "packet", "launch"), 90),
    ActionSpec("context.use", "Use Context Packet", "Context", "Apply the synthesized launch packet as the active prompt.", ("prompt", "brief", "best upfront"), 88),
    ActionSpec("context.copy", "Copy Context Packet", "Context", "Copy the current launch packet markdown.", ("clipboard", "brief", "packet"), 70),
    ActionSpec("context.save", "Save Context Packet", "Context", "Write the current launch packet to the local Codex Control config directory.", ("file", "brief", "markdown"), 62),
    ActionSpec("roadmap.plan", "Plan Roadmap", "Roadmap", "Rank the next best milestones from current app and project state.", ("milestone", "next", "strategy"), 91),
    ActionSpec("roadmap.use", "Use Next Milestone", "Roadmap", "Apply the selected roadmap milestone prompt to the composer.", ("prompt", "milestone", "next"), 86),
    ActionSpec("roadmap.copy", "Copy Roadmap", "Roadmap", "Copy the current milestone roadmap markdown.", ("clipboard", "milestone"), 66),
    ActionSpec("roadmap.save", "Save Roadmap", "Roadmap", "Write the current milestone roadmap to the local Codex Control config directory.", ("file", "markdown", "milestone"), 60),
    ActionSpec("mission.architect", "Architect Mission", "Mission", "Rebuild the mission blueprint from project, prompt, agents, and checks.", ("blueprint", "plan"), 96),
    ActionSpec("mission.use_prompt", "Use Mission Prompt", "Mission", "Apply the Mission Architect recommended prompt path.", ("recommended", "prompt"), 78),
    ActionSpec("agents.plan", "Plan Agents", "Agents", "Plan Architect, Builder, Reviewer, UI Polish, and Verifier lanes.", ("multi-agent", "lanes", "worktree"), 94),
    ActionSpec("agents.prepare", "Prepare Agent Worktrees", "Agents", "Prepare isolated worktrees for planned lanes when Git is available.", ("worktree", "parallel"), 70),
    ActionSpec("agents.run_lane", "Run Selected Agent", "Agents", "Launch the selected agent lane in a terminal-backed Codex session.", ("lane", "terminal"), 66),
    ActionSpec("agents.track_lane", "Track Selected Agent", "Agents", "Run the selected lane through the execution monitor.", ("monitor", "json", "lane"), 76),
    ActionSpec("agents.results", "Refresh Agent Results", "Agents", "Collect lane diffs and summaries into the Results Console.", ("diff", "summary"), 74),
    ActionSpec("autopilot.prepare", "Prepare Autopilot", "Autopilot", "Create a durable replay package from the current mission.", ("package", "script"), 92),
    ActionSpec("autopilot.track", "Track Autopilot", "Autopilot", "Run the selected Autopilot package with live status and artifacts.", ("monitor", "run"), 88),
    ActionSpec("autopilot.terminal", "Replay Autopilot In Terminal", "Autopilot", "Replay the selected package in the embedded terminal.", ("terminal", "script"), 70),
    ActionSpec("autopilot.stop", "Stop Autopilot", "Autopilot", "Stop the tracked Autopilot process for this app session.", ("cancel", "process"), 58),
    ActionSpec("mesh.discover", "Discover Tailnet", "Mesh", "Import this Tailscale tailnet into the local Device Mesh without duplicating existing device records.", ("tailscale", "tailnet", "magicdns", "devices", "ssh"), 96),
    ActionSpec("mesh.check", "Check Fleet", "Mesh", "Probe every trusted Codex device over SSH for CLI, project, Git, and memory readiness.", ("tailscale", "ssh", "devices", "health"), 94),
    ActionSpec("mesh.latest", "Load Latest Team", "Mesh", "Reload the most recent saved Codex Team run from local team storage.", ("agents", "team", "history", "reload"), 93),
    ActionSpec("mesh.prepare_team", "Prepare Codex Team", "Mesh", "Create a shared ledger and role-specific prompt package for ready trusted devices.", ("agents", "team", "lanes", "prompts"), 92),
    ActionSpec("mesh.launch_team", "Launch Codex Team", "Mesh", "Sync the team package and open one terminal-backed Codex lane per ready device.", ("agents", "team", "remote", "terminal"), 90),
    ActionSpec("mesh.collect_team", "Collect Team Results", "Mesh", "Pull remote lane handoffs and final output files back into the local team run folder.", ("agents", "handoff", "rsync", "results"), 86),
    ActionSpec("mesh.sync_bus", "Sync Handoff Bus", "Mesh", "Generate the shared handoff bus and redistribute it to every current Codex Team device.", ("agents", "team", "handoff", "redistribute"), 85),
    ActionSpec("mesh.sync_chat", "Broadcast Team Stream", "Mesh", "Broadcast the current team stream to every current Codex Team device.", ("agents", "team", "chat", "broadcast"), 83),
    ActionSpec("mesh.refresh_chat", "Refresh Team Stream", "Mesh", "Refresh the shared team-chat stream from the current team run folder.", ("agents", "team", "chat", "stream"), 84),
    ActionSpec("mesh.copy_chat", "Copy Team Stream", "Mesh", "Copy the latest team-chat stream for quick handoff and archive visibility.", ("agents", "team", "chat", "stream", "copy"), 72),
    ActionSpec("mesh.export_bundle", "Export Team Evidence Bundle", "Mesh", "Create a local team evidence bundle with selected receipts and team artifacts.", ("agents", "team", "evidence", "bundle", "handoff", "proof"), 88),
    ActionSpec("mesh.distribute_bundle", "Distribute Team Evidence Bundle", "Mesh", "Create and sync a team evidence bundle with every ready team device.", ("agents", "team", "evidence", "bundle", "distribute"), 87),
    ActionSpec("mesh.copy_bundle_report", "Copy Team Bundle Report", "Mesh", "Copy the latest team evidence bundle distribution report JSON.", ("agents", "team", "evidence", "bundle", "report", "copy"), 78),
    ActionSpec("mesh.verify_bundle", "Verify Team Evidence Bundle", "Mesh", "Verify local and remote bundle hashes for the latest team bundle distribution.", ("agents", "team", "evidence", "bundle", "verify"), 84),
    ActionSpec("mesh.preview_repair_bundle", "Preview Bundle Repair", "Mesh", "Preview bundle repair targets from the latest distribution report.", ("agents", "team", "evidence", "bundle", "repair", "preview"), 80),
    ActionSpec("mesh.retry_bundle", "Retry Bundle Distribution", "Mesh", "Retry evidence bundle sync for failed or stale targets.", ("agents", "team", "evidence", "bundle", "repair", "retry"), 82),
    ActionSpec("mesh.repair_bus", "Repair Bus Sync", "Mesh", "Repair stale and failed handoff bus transfers from the previous sync pass.", ("agents", "team", "handoff", "repair"), 83),
    ActionSpec("mesh.preview_repair_bus", "Preview Bus Repair", "Mesh", "Preview the stale or failed handoff bus targets that a repair pass will retry.", ("agents", "team", "handoff", "repair", "preview"), 80),
    ActionSpec("mesh.retry_bus", "Retry Bus Sync", "Mesh", "Retry handoff bus sync for devices that failed on the last pass.", ("agents", "team", "handoff", "retry"), 82),
    ActionSpec("mesh.verify_bus", "Verify Bus Integrity", "Mesh", "Check local handoff bus artifact checksums against the latest report and mark stale targets.", ("agents", "team", "handoff", "integrity", "checksum"), 73),
    ActionSpec("mesh.copy_bus_report", "Copy Bus Report", "Mesh", "Copy the latest handoff bus report JSON for the active Codex Team run.", ("agents", "team", "handoff", "bus", "report"), 70),
    ActionSpec("mesh.copy_role_bootstrap", "Copy Role Bootstrap", "Mesh", "Copy role bootstraps and startup presets for the active Codex Team run.", ("agents", "team", "bootstrap", "roles", "handoff"), 68),
    ActionSpec("mesh.summary", "Copy Team Summary", "Mesh", "Generate and copy the current Codex Team summary from collected lane artifacts.", ("agents", "team", "summary", "handoff"), 84),
    ActionSpec("mesh.review_summary", "Review Team Summary", "Mesh", "Mark the current Codex Team summary as reviewed so a completed or deliberately closed run stops blocking the next team.", ("agents", "team", "summary", "review", "close"), 85),
    ActionSpec("mesh.open", "Open Team Folder", "Mesh", "Open the current Codex Team run folder.", ("agents", "team", "files", "folder"), 70),
    ActionSpec("launcher.diagnostics", "Launcher Diagnostics", "Launcher", "Run launcher integrity checks for the `codex-gui` entrypoint and show actionable repair guidance.", ("launcher", "codex-gui", "entrypoint", "diagnostics", "repair"), 72),
    ActionSpec("launcher.repair", "Repair Launcher", "Launcher", "Reinstall codex-control in editable mode to regenerate the `codex-gui` entrypoint and metadata.", ("launcher", "pip", "repair", "entrypoint"), 58),
    ActionSpec("quality.run", "Run Quality Gate", "Quality", "Run project checks, Codex doctor, and desktop validation.", ("tests", "compile", "doctor", "validate"), 98),
    ActionSpec("quality.copy", "Copy Quality Report", "Quality", "Copy the latest Quality Gate report or current plan.", ("clipboard", "report"), 66),
    ActionSpec("preflight.open", "Open Preflight", "Quality", "Show launch readiness checks for the current Codex command.", ("checks", "readiness", "risk"), 76),
    ActionSpec("receipts.stamp", "Stamp Receipt", "Receipts", "Write a metadata-only receipt event for the current command.", ("atlas", "receipt", "hash"), 68),
    ActionSpec("receipts.verify", "Verify Receipt", "Receipts", "Verify the selected Atlas receipt.", ("atlas", "proof"), 62),
    ActionSpec("receipts.replay", "Replay Receipt Chain", "Receipts", "Replay retained receipt hashes for the selected receipt chain.", ("atlas", "chain"), 58),
    ActionSpec("receipts.bundle", "Export Review Bundle", "Receipts", "Bundle current launch context, receipts, and run ledger into a review package.", ("atlas", "proof", "bundle", "evidence"), 60),
    ActionSpec("session.new", "New Session", "Session", "Create a saved workspace session from the current prompt and project.", ("workspace", "save"), 64),
    ActionSpec("session.save", "Save Session", "Session", "Persist the current workspace session.", ("workspace", "prompt"), 68),
    ActionSpec("session.run", "Run Session", "Session", "Run the selected saved workspace session.", ("workspace", "launch"), 62),
    ActionSpec("project.refresh", "Refresh Project Intelligence", "Project", "Rescan stack, Git state, validation commands, and recent Codex threads.", ("scan", "stack", "git"), 82),
    ActionSpec("project.focus", "Focus Project", "Project", "Move focus to the active project entry.", ("path", "directory"), 56),
    ActionSpec("project.terminal", "Open Project Terminal", "Project", "Open a shell in the active project directory.", ("shell", "terminal"), 60),
    ActionSpec("git.status", "Git Status", "Git", "Show short branch and working tree status.", ("changes", "repo"), 62),
    ActionSpec("git.diff", "Git Diff Stat", "Git", "Show the active project's diff summary.", ("changes", "summary"), 58),
    ActionSpec("git.log", "Git Log", "Git", "Show recent decorated commits.", ("history", "commits"), 52),
    ActionSpec("profiles.install", "Install Profiles", "Config", "Install local Codex profile presets if missing.", ("config", "profiles"), 64),
    ActionSpec("doctor.run", "Run Doctor", "Config", "Run codex doctor and display the JSON health report.", ("health", "diagnostics"), 76),
    ActionSpec("codex.login", "Login Codex", "Config", "Open the Codex login flow in the embedded terminal.", ("auth", "account"), 50),
    ActionSpec("codex.update", "Update Codex", "Config", "Run the Codex update command.", ("upgrade", "install"), 48),
    ActionSpec("page.workbench", "Show Workbench", "Navigate", "Return to the main command deck.", ("home", "launch"), 70),
    ActionSpec("page.palette", "Show Palette", "Navigate", "Open the full command palette.", ("actions", "search"), 90),
    ActionSpec("page.context", "Show Context", "Navigate", "Open the full launch Context Packet page.", ("brief", "packet", "prompt"), 64),
    ActionSpec("page.roadmap", "Show Roadmap", "Navigate", "Open the milestone Roadmap page.", ("milestone", "next", "strategy"), 64),
    ActionSpec("page.orchestrate", "Show Orchestrate", "Navigate", "Open the Run Orchestration page.", ("package", "launch", "run"), 66),
    ActionSpec("page.quality", "Show Quality", "Navigate", "Open the Quality Gate page.", ("checks", "tests"), 62),
    ActionSpec("page.mission", "Show Mission", "Navigate", "Open the Mission Architect page.", ("blueprint", "plan"), 56),
    ActionSpec("page.autopilot", "Show Autopilot", "Navigate", "Open Autopilot history and controls.", ("runs", "package"), 56),
    ActionSpec("page.mesh", "Show Mesh", "Navigate", "Open multi-device Codex mesh and portable memory.", ("devices", "ssh", "sync", "memory"), 62),
    ActionSpec("page.monitor", "Show Monitor", "Navigate", "Open tracked execution monitor.", ("agents", "process"), 54),
    ActionSpec("page.receipts", "Show Receipts", "Navigate", "Open Receipt Vault.", ("atlas", "proof"), 50),
    ActionSpec("page.git", "Show Git", "Navigate", "Open Git controls.", ("repo", "diff"), 46),
    ActionSpec("app.refresh", "Refresh All", "App", "Refresh health, project, receipts, runs, Autopilot, and command previews.", ("reload", "sync"), 86),
)


def action_by_id(action_id: str, actions: tuple[ActionSpec, ...] = ACTION_SPECS) -> ActionSpec | None:
    return next((action for action in actions if action.id == action_id), None)


def _score_action(action: ActionSpec, terms: list[str], query: str) -> int:
    if not terms:
        return action.priority
    haystack = action.haystack()
    title = action.title.lower()
    score = action.priority
    if query == action.id.lower() or query == title:
        score += 400
    if title.startswith(query) or action.id.lower().startswith(query):
        score += 220
    for term in terms:
        if term in action.id.lower():
            score += 85
        if title.startswith(term):
            score += 70
        elif term in title:
            score += 50
        if term == action.group.lower():
            score += 45
        if any(term in keyword for keyword in action.keywords):
            score += 35
        if term not in haystack:
            score -= 180
    return score


def rank_actions(
    query: str,
    actions: tuple[ActionSpec, ...] = ACTION_SPECS,
    limit: int | None = None,
) -> tuple[ActionSpec, ...]:
    clean = " ".join(query.lower().split())
    terms = clean.split()
    scored = [
        (_score_action(action, terms, clean), action)
        for action in actions
    ]
    filtered = [(score, action) for score, action in scored if score > action.priority - 150 or not terms]
    ranked = tuple(action for _score, action in sorted(filtered, key=lambda item: (-item[0], item[1].group, item[1].title)))
    return ranked[:limit] if limit is not None else ranked


def action_groups(actions: tuple[ActionSpec, ...] = ACTION_SPECS) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for action in actions:
        counts[action.group] = counts.get(action.group, 0) + 1
    return tuple(sorted(counts.items(), key=lambda item: item[0].lower()))
