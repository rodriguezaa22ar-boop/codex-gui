#!/usr/bin/env python3
"""Milestone roadmap synthesis for Codex Control."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SnapshotLike(Protocol):
    name: str
    root: str
    is_git: bool
    stack: tuple[str, ...]
    commands: tuple[object, ...]
    recommendation: str


class PreflightLike(Protocol):
    status: str
    score: int


class QualityLike(Protocol):
    status: str
    score: int

    def summary(self) -> str: ...


class ContextLike(Protocol):
    status: str
    score: int

    def summary(self) -> str: ...


class MissionLike(Protocol):
    headline: str
    status: str
    score: int
    validation: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class RoadmapMilestone:
    id: str
    title: str
    outcome: str
    impact: int
    effort: int
    confidence: int
    status: str
    signals: tuple[str, ...]
    validation: tuple[str, ...]
    prompt: str

    @property
    def priority(self) -> int:
        return max(0, min(100, self.impact * 8 + self.confidence * 5 - self.effort * 3))

    def summary(self) -> str:
        return f"{self.title} | priority {self.priority} | impact {self.impact}/10 | effort {self.effort}/10"

    def detail_text(self) -> str:
        lines = [
            f"## {self.title}",
            f"Status: {self.status}",
            f"Priority: {self.priority}",
            f"Impact: {self.impact}/10",
            f"Effort: {self.effort}/10",
            f"Confidence: {self.confidence}/10",
            "",
            "Outcome:",
            self.outcome,
            "",
            "Signals:",
        ]
        lines.extend(f"- {signal}" for signal in self.signals)
        lines.extend(["", "Validation:"])
        lines.extend(f"- {check}" for check in self.validation)
        lines.extend(["", "Launch prompt:", self.prompt.strip()])
        return "\n".join(lines).strip()


@dataclass(frozen=True)
class Roadmap:
    generated: int
    project: str
    title: str
    status: str
    score: int
    milestones: tuple[RoadmapMilestone, ...]

    def next_milestone(self) -> RoadmapMilestone | None:
        for milestone in self.milestones:
            if milestone.status == "next":
                return milestone
        return self.milestones[0] if self.milestones else None

    def summary(self) -> str:
        next_item = self.next_milestone()
        next_text = next_item.title if next_item is not None else "none"
        return f"{self.score}/100 | next: {next_text} | {len(self.milestones)} milestones"

    def detail_text(self) -> str:
        lines = [
            "# Codex Control Milestone Roadmap",
            "",
            f"Title: {self.title}",
            f"Project: {self.project}",
            f"Status: {self.status}",
            f"Score: {self.score}",
            f"Generated: {self.generated}",
            "",
        ]
        for milestone in self.milestones:
            lines.append(milestone.detail_text())
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def next_prompt(self) -> str:
        milestone = self.next_milestone()
        if milestone is None:
            return "Use $best-upfront-codex. Inspect the project, choose the highest-value next milestone, implement it end to end, and validate it."
        return "\n".join([
            "Use $best-upfront-codex.",
            "",
            f"Milestone: {milestone.title}",
            "",
            "Outcome:",
            milestone.outcome,
            "",
            "Why this is next:",
            *[f"- {signal}" for signal in milestone.signals],
            "",
            "Implementation request:",
            milestone.prompt.strip(),
            "",
            "Validation:",
            *[f"- {check}" for check in milestone.validation],
        ]).strip()


def _clean(text: object, fallback: str = "") -> str:
    value = " ".join(str(text or "").replace("\x00", "").split())
    return value or fallback


def _project_name(project: str, snapshot: SnapshotLike | None) -> str:
    if snapshot is not None and _clean(snapshot.name):
        return snapshot.name
    return Path(project).expanduser().name or project


def _validation(snapshot: SnapshotLike | None, mission: MissionLike | None) -> tuple[str, ...]:
    commands: list[str] = []
    if mission is not None:
        commands.extend(str(item) for item in mission.validation[:4] if _clean(item))
    if snapshot is not None:
        for command in snapshot.commands[:4]:
            value = getattr(command, "command", command)
            if _clean(value) and str(value) not in commands:
                commands.append(str(value))
    if "python3 -m unittest discover -s tests" not in commands:
        commands.append("python3 -m unittest discover -s tests")
    commands.append("python3 -m py_compile codex_gui.py codex_actions.py codex_context.py codex_roadmap.py")
    return tuple(dict.fromkeys(commands))[:6]


def _signals(
    *,
    snapshot: SnapshotLike | None,
    preflight: PreflightLike | None,
    quality: QualityLike | None,
    context: ContextLike | None,
    mission: MissionLike | None,
    autopilot_records: list[object],
    command_runs: list[object],
    receipts: list[object],
) -> dict[str, tuple[str, ...]]:
    project = []
    if snapshot is None:
        project.append("Project intelligence is not loaded yet.")
    else:
        project.append(f"Stack: {_clean(', '.join(snapshot.stack), 'unknown')}.")
        project.append("Git worktree isolation is available." if snapshot.is_git else "No Git repository; keep parallel work opt-in.")
        if snapshot.commands:
            project.append(f"{len(snapshot.commands)} validation command(s) detected.")
    health = []
    if preflight is not None:
        health.append(f"Preflight is {preflight.status} at score {preflight.score}.")
    if quality is not None:
        health.append(f"Quality Gate is {quality.status} at score {quality.score}.")
    if context is not None:
        health.append(f"Context Packet is {context.status} at score {context.score}.")
    if mission is not None:
        health.append(f"Mission Architect: {_clean(mission.headline)}.")
    activity = [
        f"{len(command_runs)} command run(s) recorded.",
        f"{len(autopilot_records)} Autopilot package(s) prepared.",
        f"{len(receipts)} receipt record(s) available.",
    ]
    return {
        "project": tuple(project),
        "health": tuple(health),
        "activity": tuple(activity),
    }


def _milestone(
    *,
    milestone_id: str,
    title: str,
    outcome: str,
    impact: int,
    effort: int,
    confidence: int,
    signals: tuple[str, ...],
    validation: tuple[str, ...],
    prompt: str,
) -> RoadmapMilestone:
    return RoadmapMilestone(
        id=milestone_id,
        title=title,
        outcome=outcome,
        impact=max(1, min(10, impact)),
        effort=max(1, min(10, effort)),
        confidence=max(1, min(10, confidence)),
        status="candidate",
        signals=signals,
        validation=validation,
        prompt=prompt,
    )


def build_roadmap(
    *,
    project: str,
    prompt: str,
    snapshot: SnapshotLike | None = None,
    preflight: PreflightLike | None = None,
    quality: QualityLike | None = None,
    context: ContextLike | None = None,
    mission: MissionLike | None = None,
    autopilot_records: list[object] | None = None,
    command_runs: list[object] | None = None,
    receipts: list[object] | None = None,
) -> Roadmap:
    autopilot_records = autopilot_records or []
    command_runs = command_runs or []
    receipts = receipts or []
    name = _project_name(project, snapshot)
    validation = _validation(snapshot, mission)
    signal_groups = _signals(
        snapshot=snapshot,
        preflight=preflight,
        quality=quality,
        context=context,
        mission=mission,
        autopilot_records=autopilot_records,
        command_runs=command_runs,
        receipts=receipts,
    )
    prompt_line = _clean(prompt, "Continue improving Codex Control toward the best practical version.")

    quality_bonus = 1 if quality is not None and quality.status == "passed" else 0
    context_bonus = 1 if context is not None and context.score >= 85 else 0
    gtk_bonus = 1 if snapshot is not None and "GTK" in snapshot.stack else 0
    run_gap_bonus = 1 if not command_runs else 0
    receipt_gap_bonus = 1 if not receipts else 0
    agent_gap_bonus = 1 if not autopilot_records else 0

    candidates = [
        _milestone(
            milestone_id="run-orchestrator",
            title="Run Orchestration Console",
            outcome="Unify Context Packet, preflight, command preview, live run status, run ledger, and receipts into a single launch-control workflow.",
            impact=10,
            effort=6,
            confidence=8 + quality_bonus,
            signals=signal_groups["health"] + signal_groups["activity"] + ("The app now has enough context to make each launch reproducible.",),
            validation=validation,
            prompt=(
                "Build a Run Orchestration Console for Codex Control. It should create a launch package from the current Context Packet, show preflight and command preview, start the selected run path, track status, and connect the result to the run ledger and receipt posture without storing raw secrets."
            ),
        ),
        _milestone(
            milestone_id="visual-system",
            title="Premium Visual System Pass",
            outcome="Turn the current dense workstation into a more polished product surface with stronger spacing, hierarchy, reusable tokens, and screenshot-verified first-screen ergonomics.",
            impact=8 + gtk_bonus,
            effort=5,
            confidence=8,
            signals=signal_groups["project"] + ("GTK UI is the user's primary surface.", "Screenshots are already part of the validation loop."),
            validation=validation + ("Launch the GUI and capture Workbench plus focused page screenshots.",),
            prompt=(
                "Upgrade the Codex Control visual system end to end. Consolidate CSS tokens, improve hierarchy and density, keep the terminal-first workflow, verify the Workbench and key pages with screenshots, and preserve all existing behavior."
            ),
        ),
        _milestone(
            milestone_id="agent-command-center",
            title="Agent Command Center",
            outcome="Make Architect, Builder, Reviewer, UI Polish, and Verifier lanes easier to compare, launch, monitor, and merge from one operational page.",
            impact=8 + agent_gap_bonus,
            effort=7,
            confidence=7,
            signals=signal_groups["project"] + ("Agent lanes already exist, but orchestration and comparison can become more direct.",),
            validation=validation,
            prompt=(
                "Create an Agent Command Center that makes planned lanes, launch controls, monitor state, diffs, and apply/merge decisions easier to operate from one page while keeping risky writes opt-in."
            ),
        ),
        _milestone(
            milestone_id="trust-receipts",
            title="Trust and Receipt Layer",
            outcome="Make local run provenance easier to understand by surfacing receipt chain health, Atlas availability, verification status, and metadata-only privacy guarantees.",
            impact=7 + receipt_gap_bonus,
            effort=5,
            confidence=8,
            signals=signal_groups["activity"] + ("The user wants Atlas for receipts, not to build the GUI.",),
            validation=validation,
            prompt=(
                "Improve the Receipt Vault into a trust layer: show Atlas availability, receipt chain health, verification state, privacy notes, and one-click copy/open flows without embedding raw prompt or command bodies."
            ),
        ),
        _milestone(
            milestone_id="release-hardening",
            title="Release Hardening and Recovery",
            outcome="Strengthen local install reliability with launcher diagnostics, crash/log surfacing, config backup, app-server clarity, and first-run repair actions.",
            impact=7,
            effort=6,
            confidence=8 + quality_bonus,
            signals=signal_groups["health"] + ("The app is now broad enough that recovery and diagnostics matter.",),
            validation=validation + ("codex doctor --summary --ascii", "desktop-file-validate ~/.local/share/applications/codex-gui.desktop"),
            prompt=(
                "Harden Codex Control for daily use. Add launcher diagnostics, log/crash visibility, config backup/restore or repair actions, clearer app-server status, and verification that desktop launch remains intact."
            ),
        ),
        _milestone(
            milestone_id="prompt-memory",
            title="Prompt Memory and Brief Library",
            outcome="Persist high-value prompt variants, context packets, and roadmap decisions into a browsable local library that can be reused without manual copying.",
            impact=7 + context_bonus,
            effort=5,
            confidence=8,
            signals=signal_groups["health"] + ("Context Packet and Prompt Lab now produce useful reusable artifacts.",),
            validation=validation,
            prompt=(
                "Add a local Prompt Memory and Brief Library that stores selected prompt variants, context packets, roadmap prompts, and saved briefs with search, use, copy, and delete flows."
            ),
        ),
    ]

    if quality is not None and quality.status != "passed":
        candidates.insert(0, _milestone(
            milestone_id="quality-repair",
            title="Quality Repair Sprint",
            outcome="Fix the failing checks before adding new surface area.",
            impact=10,
            effort=3,
            confidence=9,
            signals=(f"Quality Gate is {quality.status}: {quality.summary()}",),
            validation=validation,
            prompt="Fix the current Quality Gate failures with the smallest high-confidence changes, then rerun the full validation suite.",
        ))

    ordered = sorted(candidates, key=lambda item: (-item.priority, item.effort, item.title))
    marked: list[RoadmapMilestone] = []
    for index, candidate in enumerate(ordered):
        status = "next" if index == 0 else ("ready" if index < 4 else "later")
        marked.append(RoadmapMilestone(
            id=candidate.id,
            title=candidate.title,
            outcome=candidate.outcome,
            impact=candidate.impact,
            effort=candidate.effort,
            confidence=candidate.confidence,
            status=status,
            signals=candidate.signals,
            validation=candidate.validation,
            prompt=candidate.prompt,
        ))

    score = max(0, min(100, 70 + quality_bonus * 8 + context_bonus * 8 + min(len(marked), 6) * 2))
    status = "ready" if marked else "empty"
    return Roadmap(
        generated=int(time.time()),
        project=str(Path(project).expanduser()),
        title=f"{name} best-version roadmap",
        status=status,
        score=score,
        milestones=tuple(marked),
    )
