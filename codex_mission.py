#!/usr/bin/env python3
"""Mission blueprint synthesis for Codex Control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codex_preflight import PreflightReport
from codex_prompting import PromptVariant


class SnapshotLike(Protocol):
    name: str
    is_git: bool
    dirty: int
    untracked: int
    stack: tuple[str, ...]
    commands: tuple[object, ...]
    recommendation: str


class AgentPlanLike(Protocol):
    is_git: bool
    lanes: tuple[object, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class MissionPhase:
    title: str
    detail: str
    status: str = "planned"


@dataclass(frozen=True)
class MissionBlueprint:
    headline: str
    objective: str
    status: str
    score: int
    recommended_prompt_id: str
    recommended_prompt_title: str
    recommended_action: str
    recommended_profile: str
    recommended_web: str
    phases: tuple[MissionPhase, ...]
    agents: tuple[str, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]

    def summary(self) -> str:
        return f"{self.headline} | {len(self.agents)} lanes | {len(self.validation)} checks"

    def detail_text(self) -> str:
        lines = [
            "# Mission Blueprint",
            "",
            f"Headline: {self.headline}",
            f"Status: {self.status}",
            f"Score: {self.score}",
            f"Objective: {self.objective}",
            "",
            "Recommended prompt:",
            f"{self.recommended_prompt_title} ({self.recommended_prompt_id})",
            f"Action: {self.recommended_action}",
            f"Profile: {self.recommended_profile}",
            f"Web: {self.recommended_web}",
            "",
            "Phases:",
        ]
        lines.extend(f"- {phase.title}: {phase.detail}" for phase in self.phases)
        if self.agents:
            lines.extend(["", "Agent lanes:"])
            lines.extend(f"- {agent}" for agent in self.agents)
        if self.validation:
            lines.extend(["", "Validation:"])
            lines.extend(f"- {command}" for command in self.validation)
        if self.risks:
            lines.extend(["", "Watch:"])
            lines.extend(f"- {risk}" for risk in self.risks)
        return "\n".join(lines)


def _compact(text: str, fallback: str) -> str:
    cleaned = " ".join(text.strip().split())
    return cleaned or fallback


def _select_variant(variants: list[PromptVariant], preflight: PreflightReport | None) -> PromptVariant:
    if preflight is not None and preflight.blocks:
        for variant in variants:
            if variant.id == "deep-review":
                return variant
    for preferred in ["product-polish", "best-upfront", "architect"]:
        for variant in variants:
            if variant.id == preferred:
                return variant
    return variants[0]


def _validation_commands(snapshot: SnapshotLike | None) -> tuple[str, ...]:
    if snapshot is None:
        return ()
    commands: list[str] = []
    for command in snapshot.commands[:5]:
        value = getattr(command, "command", "")
        if value:
            commands.append(str(value))
    return tuple(commands)


def _agent_labels(agent_plan: AgentPlanLike | None) -> tuple[str, ...]:
    if agent_plan is None:
        return ()
    labels: list[str] = []
    for lane in agent_plan.lanes[:6]:
        title = str(getattr(lane, "title", "Agent"))
        objective = str(getattr(lane, "objective", "")).strip()
        labels.append(f"{title}: {objective}" if objective else title)
    return tuple(labels)


def _risk_list(
    *,
    snapshot: SnapshotLike | None,
    preflight: PreflightReport | None,
    agent_plan: AgentPlanLike | None,
) -> tuple[str, ...]:
    risks: list[str] = []
    if preflight is not None:
        risks.extend(f"{check.title}: {check.detail}" for check in preflight.checks if check.status in {"block", "warn"})
    if snapshot is None:
        risks.append("Project intelligence is still scanning.")
    else:
        if snapshot.dirty or snapshot.untracked:
            risks.append(f"Existing work present: {snapshot.dirty} tracked and {snapshot.untracked} untracked changes.")
        if not snapshot.commands:
            risks.append("No validation command detected.")
        if not snapshot.is_git:
            risks.append("No Git repository detected; parallel write lanes share the same directory.")
    if agent_plan is not None and not agent_plan.is_git:
        risks.append("Agent worktree isolation is unavailable until this project is a Git repository.")
    return tuple(dict.fromkeys(risks))[:8]


def build_mission_blueprint(
    *,
    prompt: str,
    variants: list[PromptVariant],
    snapshot: SnapshotLike | None,
    preflight: PreflightReport | None,
    agent_plan: AgentPlanLike | None,
) -> MissionBlueprint:
    if not variants:
        variants = [PromptVariant(
            id="best-upfront",
            title="Best Upfront",
            summary="Maximum-quality default.",
            prompt=_compact(prompt, "Improve this project to the highest practical quality."),
        )]
    selected = _select_variant(variants, preflight)
    objective = _compact(prompt, "Improve this project to the highest practical quality.")
    project_name = snapshot.name if snapshot is not None else "selected project"
    preflight_status = preflight.status if preflight is not None else "scanning"
    preflight_score = preflight.score if preflight is not None else 70
    validations = _validation_commands(snapshot)
    agents = _agent_labels(agent_plan)
    risks = _risk_list(snapshot=snapshot, preflight=preflight, agent_plan=agent_plan)

    if preflight_status == "blocked":
        headline = "Clear launch blockers first"
    elif "GTK" in (snapshot.stack if snapshot is not None else ()):
        headline = f"Ship polished GTK workstation work in {project_name}"
    elif snapshot is not None and snapshot.commands:
        headline = f"Build and validate {project_name}"
    else:
        headline = f"Architect {project_name} before launch"

    phases = [
        MissionPhase("Orient", "Inspect the project snapshot, changed files, recent threads, and validation commands.", "ready"),
        MissionPhase("Shape Prompt", f"Use the {selected.title} prompt path, then pass only the selected prompt to Codex.", "ready"),
        MissionPhase("Execute", f"Run {selected.action} with {selected.profile}; keep terminal-native behavior for approvals and streaming output.", "ready" if preflight_status != "blocked" else "blocked"),
        MissionPhase("Parallelize", f"Use {len(agents) or 5} specialized lanes for architecture, build, review, UI polish, and verification.", "planned"),
        MissionPhase("Verify", "Run detected checks, inspect rendered UI when applicable, and record metadata-only receipts and run ledger entries.", "planned"),
    ]
    if preflight_status == "blocked":
        phases.insert(0, MissionPhase("Fix Preflight", "Resolve blocking project, Codex CLI, prompt, or Git-gate issues before launching.", "blocked"))

    score = max(0, min(100, preflight_score + min(len(validations), 3) * 2 + min(len(agents), 5)))
    return MissionBlueprint(
        headline=headline,
        objective=objective,
        status=preflight_status,
        score=score,
        recommended_prompt_id=selected.id,
        recommended_prompt_title=selected.title,
        recommended_action=selected.action,
        recommended_profile=selected.profile,
        recommended_web=selected.web,
        phases=tuple(phases),
        agents=agents,
        validation=validations,
        risks=risks,
    )
