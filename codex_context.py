#!/usr/bin/env python3
"""Codex-ready context packet synthesis for Codex Control."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CommandLike(Protocol):
    label: str
    command: str


class SnapshotLike(Protocol):
    root: str
    name: str
    is_git: bool
    branch: str
    dirty: int
    untracked: int
    changed_files: tuple[str, ...]
    recent_commits: tuple[str, ...]
    stack: tuple[str, ...]
    commands: tuple[CommandLike, ...]
    top_files: tuple[str, ...]
    recommendation: str
    notes: tuple[str, ...]


class PreflightLike(Protocol):
    status: str
    score: int
    checks: tuple[object, ...]

    def summary(self) -> str: ...


class QualityLike(Protocol):
    generated: int
    project: str
    status: str
    score: int
    checks: tuple[object, ...]

    def summary(self) -> str: ...


class MissionLike(Protocol):
    headline: str
    objective: str
    status: str
    score: int
    recommended_prompt_title: str
    recommended_action: str
    recommended_profile: str
    agents: tuple[str, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class ContextSection:
    title: str
    detail: str
    status: str = "ready"

    def markdown(self) -> str:
        return f"## {self.title}\nStatus: {self.status}\n\n{self.detail.strip()}".strip()


@dataclass(frozen=True)
class ContextPacket:
    generated: int
    project: str
    title: str
    status: str
    score: int
    prompt: str
    sections: tuple[ContextSection, ...]

    def summary(self) -> str:
        return f"{self.title} | score {self.score} | {len(self.sections)} sections"

    def markdown(self) -> str:
        lines = [
            "# Codex Launch Context Packet",
            "",
            f"Title: {self.title}",
            f"Project: {self.project}",
            f"Status: {self.status}",
            f"Score: {self.score}",
            f"Generated: {self.generated}",
            "",
        ]
        lines.extend(section.markdown() + "\n" for section in self.sections)
        return "\n".join(lines).strip() + "\n"

    def launch_prompt(self) -> str:
        objective = _redact(self.prompt).strip() or "Improve this project to the highest practical quality."
        return "\n".join([
            "Use $best-upfront-codex.",
            "",
            "Primary objective:",
            objective,
            "",
            "Use this context packet as the working brief. Inspect the repo before editing, keep changes scoped, preserve user work, implement end to end, and run the listed validation checks when relevant.",
            "",
            self.markdown().strip(),
        ]).strip()


SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|sudo|authorization)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer)\s+([a-z0-9._~+/=-]{12,})"),
)


def _redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=[redacted]", redacted)
    return redacted


def _clean(text: object, fallback: str = "") -> str:
    value = _redact(str(text or "")).replace("\x00", "")
    return " ".join(value.split()) or fallback


def _clip(text: object, limit: int = 260, fallback: str = "") -> str:
    value = _clean(text, fallback)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


def _bullets(items: list[str] | tuple[str, ...], empty: str = "none") -> str:
    cleaned = [_clip(item, 220) for item in items if _clean(item)]
    if not cleaned:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in cleaned)


def _command_text(command: object) -> str:
    if hasattr(command, "command_text"):
        try:
            return str(command.command_text())
        except TypeError:
            pass
    return str(getattr(command, "command", command))


def _check_line(check: object) -> str:
    title = _clean(getattr(check, "title", getattr(check, "label", "Check")), "Check")
    status = _clean(getattr(check, "status", "ready"), "ready")
    detail = _clip(getattr(check, "detail", getattr(check, "output_tail", "")), 160)
    if detail:
        return f"{title}: {status} - {detail}"
    return f"{title}: {status}"


def _recent_record_line(record: object) -> str:
    title = _clean(getattr(record, "title", getattr(record, "id", "")), "record")
    status = _clean(getattr(record, "status", "ready"), "ready")
    note = _clip(getattr(record, "note", ""), 120)
    return f"{title}: {status}" + (f" - {note}" if note else "")


def _project_name(project: str, snapshot: SnapshotLike | None) -> str:
    if snapshot is not None and _clean(snapshot.name):
        return snapshot.name
    return Path(project).expanduser().name or project


def _packet_score(
    *,
    snapshot: SnapshotLike | None,
    preflight: PreflightLike | None,
    quality: QualityLike | None,
    mission: MissionLike | None,
) -> int:
    score = 58
    if snapshot is not None:
        score += 10
        if snapshot.commands:
            score += 6
        if snapshot.stack:
            score += 4
    if preflight is not None:
        score += int(preflight.score * 0.12)
        if preflight.status == "blocked":
            score -= 18
        elif preflight.status == "ready":
            score += 5
    if quality is not None:
        score += 12 if quality.status == "passed" else -10
        score += min(8, max(0, quality.score // 12))
    if mission is not None:
        score += int(mission.score * 0.08)
        if mission.agents:
            score += 3
    return max(0, min(100, score))


def _snapshot_section(snapshot: SnapshotLike | None) -> ContextSection:
    if snapshot is None:
        return ContextSection(
            "Project Intelligence",
            "Project scan is still pending. Start by inspecting files, stack markers, and validation commands before editing.",
            "scanning",
        )
    git_line = "not a Git repository"
    if snapshot.is_git:
        git_line = f"{snapshot.branch or 'detached'} | {snapshot.dirty} tracked, {snapshot.untracked} untracked changes"
    detail = "\n".join([
        f"Root: {_clean(snapshot.root)}",
        f"Stack: {_clean(', '.join(snapshot.stack), 'unknown')}",
        f"Git: {git_line}",
        f"Recommendation: {_clean(snapshot.recommendation, 'Inspect first')}",
        "",
        "Validation commands:",
        _bullets(tuple(_command_text(command) for command in snapshot.commands[:6]), "none detected"),
        "",
        "Changed files:",
        _bullets(snapshot.changed_files[:8], "clean or not available"),
        "",
        "Top files:",
        _bullets(snapshot.top_files[:10], "none"),
    ])
    return ContextSection("Project Intelligence", detail, "ready")


def _preflight_section(preflight: PreflightLike | None) -> ContextSection:
    if preflight is None:
        return ContextSection("Launch Readiness", "No preflight report is available yet.", "scanning")
    priority = {"block": 0, "warn": 1, "note": 2, "ok": 3}
    checks = sorted(preflight.checks, key=lambda check: priority.get(str(getattr(check, "status", "ok")), 4))[:8]
    detail = "\n".join([
        f"Summary: {_clean(preflight.summary())}",
        f"Score: {preflight.score}",
        "",
        "Checks:",
        _bullets(tuple(_check_line(check) for check in checks), "none"),
    ])
    return ContextSection("Launch Readiness", detail, preflight.status)


def _quality_section(quality: QualityLike | None) -> ContextSection:
    if quality is None:
        return ContextSection(
            "Quality Gate",
            "No completed quality report is available. Use detected project validation commands and Codex doctor before finalizing.",
            "ready",
        )
    checks = tuple(_check_line(check) for check in quality.checks[:8])
    detail = "\n".join([
        f"Summary: {_clean(quality.summary())}",
        f"Project: {_clean(quality.project)}",
        f"Generated: {quality.generated}",
        "",
        "Checks:",
        _bullets(checks, "none"),
    ])
    return ContextSection("Quality Gate", detail, quality.status)


def _mission_section(mission: MissionLike | None) -> ContextSection:
    if mission is None:
        return ContextSection(
            "Mission Architect",
            "No mission blueprint is available yet. Shape the work into objective, implementation lanes, validation, and UI polish before launch.",
            "scanning",
        )
    detail = "\n".join([
        f"Headline: {_clean(mission.headline)}",
        f"Objective: {_clip(mission.objective, 500)}",
        f"Recommended: {_clean(mission.recommended_prompt_title)} | {_clean(mission.recommended_action)} | {_clean(mission.recommended_profile)}",
        "",
        "Agent lanes:",
        _bullets(mission.agents[:6], "none planned"),
        "",
        "Validation:",
        _bullets(mission.validation[:6], "none planned"),
        "",
        "Watch:",
        _bullets(mission.risks[:6], "no major risks listed"),
    ])
    return ContextSection("Mission Architect", detail, mission.status)


def _activity_section(
    *,
    autopilot_records: list[object],
    command_runs: list[object],
    receipts: list[object],
) -> ContextSection:
    lines = [
        "Autopilot:",
        _bullets(tuple(_recent_record_line(record) for record in autopilot_records[:4]), "no prepared runs"),
        "",
        "Run ledger:",
        _bullets(tuple(_recent_record_line(record) for record in command_runs[:4]), "no recent launches"),
        "",
        "Receipts:",
        _bullets(tuple(_recent_record_line(record) for record in receipts[:4]), "no receipts"),
    ]
    return ContextSection("Recent Activity", "\n".join(lines), "ready")


def build_context_packet(
    *,
    project: str,
    prompt: str,
    mode: str,
    snapshot: SnapshotLike | None = None,
    preflight: PreflightLike | None = None,
    quality: QualityLike | None = None,
    mission: MissionLike | None = None,
    autopilot_records: list[object] | None = None,
    command_runs: list[object] | None = None,
    receipts: list[object] | None = None,
) -> ContextPacket:
    project_name = _project_name(project, snapshot)
    status = "ready"
    if preflight is not None:
        status = preflight.status
    elif mission is not None:
        status = mission.status
    title = f"Launch {project_name} with {mode or 'Codex'}"
    prompt_detail = "\n".join([
        f"Mode: {_clean(mode, 'config default')}",
        "",
        "Prompt:",
        _redact(prompt).strip() or "No prompt entered yet.",
    ])
    sections = (
        ContextSection("Primary Objective", prompt_detail, "ready" if prompt.strip() else "needs prompt"),
        _snapshot_section(snapshot),
        _preflight_section(preflight),
        _quality_section(quality),
        _mission_section(mission),
        _activity_section(
            autopilot_records=autopilot_records or [],
            command_runs=command_runs or [],
            receipts=receipts or [],
        ),
    )
    return ContextPacket(
        generated=int(time.time()),
        project=str(Path(project).expanduser()),
        title=title,
        status=status,
        score=_packet_score(snapshot=snapshot, preflight=preflight, quality=quality, mission=mission),
        prompt=prompt,
        sections=sections,
    )
