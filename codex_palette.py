#!/usr/bin/env python3
"""Command palette previews and readiness summaries for Codex Control."""

from __future__ import annotations

import shlex
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol


class ActionLike(Protocol):
    id: str
    title: str
    group: str
    detail: str


@dataclass(frozen=True)
class PaletteContext:
    project: str = ""
    project_exists: bool = True
    prompt_chars: int = 0
    selected_prompt_choice: bool = False
    context_ready: bool = False
    roadmap_ready: bool = False
    launch_package_ready: bool = False
    session_selected: bool = False
    agent_plan_ready: bool = False
    agent_lane_selected: bool = False
    autopilot_selected: bool = False
    receipt_selected: bool = False

    @property
    def prompt_ready(self) -> bool:
        return self.prompt_chars > 0


@dataclass(frozen=True)
class PalettePreview:
    action_id: str
    title: str
    group: str
    surface: str
    risk: str
    status: str
    summary: str
    command_text: str = ""
    requirements: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def requirement_text(self) -> str:
        return "Ready" if self.ready else "Needs: " + ", ".join(self.requirements)

    def detail_text(self) -> str:
        lines = [
            f"Surface: {self.surface}",
            f"Risk: {self.risk}",
            f"Status: {self.status}",
            self.requirement_text(),
        ]
        if self.command_text:
            lines.extend(["", self.command_text])
        if self.notes:
            lines.extend(["", *self.notes])
        return "\n".join(lines)


@dataclass(frozen=True)
class PaletteHistoryRecord:
    action_id: str
    title: str
    group: str
    phase: str
    detail: str
    surface: str
    risk: str
    command_preview: str
    count: int
    created: int
    updated: int

    @property
    def status(self) -> str:
        return self.phase

    def summary(self) -> str:
        return f"{self.title} | {self.phase} | {self.count} run(s)"


COMMAND_ACTIONS = {
    "run.max",
    "run.review",
    "run.exec",
    "run.external",
    "command.copy",
    "doctor.run",
    "codex.login",
    "codex.update",
    "launcher.repair",
}

HIGH_RISK_ACTIONS = {
    "run.max",
    "run.exec",
    "run.external",
    "orchestrate.run",
    "agents.run_lane",
    "launcher.repair",
    "agents.track_lane",
    "autopilot.track",
    "autopilot.terminal",
    "codex.update",
}

PROMPT_REQUIRED = {
    "run.exec",
    "prompt.enhance",
    "prompt.ai",
}


def safe_shell_command(args: tuple[str, ...] | list[str], *, prompt_redacted: bool = False) -> str:
    parts = [str(part) for part in args]
    if prompt_redacted and parts:
        parts = ["[prompt redacted]" if part == "[prompt redacted]" else part for part in parts]
    return " ".join(shlex.quote(part) for part in parts)


def palette_now() -> int:
    return int(time.time())


def _surface_for(action_id: str) -> str:
    if action_id.startswith("page."):
        return "Navigation"
    if action_id in {"run.max", "autopilot.terminal", "agents.run_lane"}:
        return "Embedded terminal"
    if action_id == "run.external":
        return "External terminal"
    if action_id in {"run.exec", "agents.track_lane", "autopilot.track"}:
        return "Tracked process"
    if action_id.endswith(".copy") or action_id == "command.copy":
        return "Clipboard"
    if action_id.endswith(".save"):
        return "Local file"
    if action_id.startswith("git."):
        return "Git output"
    if action_id.startswith("receipts."):
        return "Receipt vault"
    if action_id.startswith("quality.") or action_id == "doctor.run":
        return "Local checks"
    if action_id.startswith("prompt.") or action_id.endswith(".use") or action_id.endswith(".use_prompt"):
        return "Composer"
    return "Workbench"


def _risk_for(action_id: str) -> str:
    if action_id in HIGH_RISK_ACTIONS:
        return "launches command"
    if action_id.startswith("git."):
        return "read-only git"
    if action_id.endswith(".save") or action_id in {"session.save", "profiles.install", "receipts.stamp"}:
        return "writes local metadata"
    if action_id == "receipts.bundle":
        return "writes local evidence bundle"
    if action_id.endswith(".copy") or action_id == "command.copy":
        return "clipboard only"
    if action_id.startswith("page.") or action_id.endswith(".focus"):
        return "navigation only"
    return "local UI action"


def _requirements(action_id: str, context: PaletteContext) -> tuple[str, ...]:
    missing: list[str] = []
    if not context.project_exists and action_id not in {"project.focus", "page.palette", "page.workbench"} and not action_id.startswith("page."):
        missing.append("existing project")
    if action_id in PROMPT_REQUIRED and not context.prompt_ready:
        missing.append("prompt")
    if action_id == "prompt.use" and not context.selected_prompt_choice:
        missing.append("selected prompt choice")
    if action_id == "session.run" and not context.session_selected:
        missing.append("saved session")
    if action_id in {"agents.prepare", "agents.results"} and not context.agent_plan_ready:
        missing.append("agent plan")
    if action_id in {"agents.run_lane", "agents.track_lane"} and not context.agent_lane_selected:
        missing.append("selected agent lane")
    if action_id in {"autopilot.track", "autopilot.terminal", "autopilot.stop"} and not context.autopilot_selected:
        missing.append("selected Autopilot package")
    if action_id in {"receipts.verify", "receipts.replay", "receipts.bundle"} and not context.receipt_selected:
        missing.append("selected receipt")
    return tuple(missing)


def build_palette_preview(
    action: ActionLike,
    context: PaletteContext,
    command: tuple[str, ...] | list[str] = (),
    *,
    prompt_redacted: bool = False,
) -> PalettePreview:
    requirements = _requirements(action.id, context)
    status = "ready" if not requirements else "needs setup"
    notes: list[str] = []
    if action.id in COMMAND_ACTIONS:
        notes.append("Command preview redacts prompt content.")
    if action.id == "run.exec":
        notes.append("Headless exec is for bounded one-shot work; interactive work should stay terminal-backed.")
    if action.id == "run.external":
        notes.append("Uses the current Action selector and opens a detached terminal.")

    command_text = safe_shell_command(command, prompt_redacted=prompt_redacted) if command else ""
    if prompt_redacted and "[prompt redacted]" not in command_text and command_text:
        notes.append("No prompt argument is currently present.")

    return PalettePreview(
        action_id=action.id,
        title=action.title,
        group=action.group,
        surface=_surface_for(action.id),
        risk=_risk_for(action.id),
        status=status,
        summary=action.detail,
        command_text=command_text,
        requirements=requirements,
        notes=tuple(notes),
    )


def load_palette_history(path: Path) -> list[PaletteHistoryRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records: list[PaletteHistoryRecord] = []
    if not isinstance(data, list):
        return records
    for item in data:
        if not isinstance(item, dict):
            continue
        records.append(PaletteHistoryRecord(
            action_id=str(item.get("action_id") or ""),
            title=str(item.get("title") or "Action"),
            group=str(item.get("group") or "Action"),
            phase=str(item.get("phase") or "unknown"),
            detail=str(item.get("detail") or ""),
            surface=str(item.get("surface") or "Workbench"),
            risk=str(item.get("risk") or "local UI action"),
            command_preview=str(item.get("command_preview") or ""),
            count=int(item.get("count") or 1),
            created=int(item.get("created") or 0),
            updated=int(item.get("updated") or 0),
        ))
    return sorted([record for record in records if record.action_id], key=lambda record: record.updated, reverse=True)


def save_palette_history(path: Path, records: list[PaletteHistoryRecord], limit: int = 120) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record.updated, reverse=True)[:limit]
    path.write_text(json.dumps([asdict(record) for record in ordered], indent=2, sort_keys=True), encoding="utf-8")


def find_palette_record(records: list[PaletteHistoryRecord], action_id: str) -> PaletteHistoryRecord | None:
    return next((record for record in records if record.action_id == action_id), None)


def record_palette_event(
    records: list[PaletteHistoryRecord],
    action: ActionLike,
    preview: PalettePreview | None,
    *,
    phase: str,
    detail: str,
    timestamp: int | None = None,
) -> tuple[list[PaletteHistoryRecord], PaletteHistoryRecord]:
    now = timestamp or palette_now()
    existing = find_palette_record(records, action.id)
    record = PaletteHistoryRecord(
        action_id=action.id,
        title=action.title,
        group=action.group,
        phase=phase,
        detail=detail,
        surface=preview.surface if preview is not None else _surface_for(action.id),
        risk=preview.risk if preview is not None else _risk_for(action.id),
        command_preview=preview.command_text if preview is not None else "",
        count=(existing.count + 1) if existing is not None else 1,
        created=existing.created if existing is not None else now,
        updated=now,
    )
    next_records = [item for item in records if item.action_id != action.id]
    next_records.insert(0, record)
    return sorted(next_records, key=lambda item: item.updated, reverse=True), record


def update_palette_record(
    records: list[PaletteHistoryRecord],
    action_id: str,
    *,
    phase: str,
    detail: str,
    timestamp: int | None = None,
) -> tuple[list[PaletteHistoryRecord], PaletteHistoryRecord | None]:
    now = timestamp or palette_now()
    updated_record: PaletteHistoryRecord | None = None
    next_records: list[PaletteHistoryRecord] = []
    for record in records:
        if record.action_id == action_id:
            updated_record = replace(record, phase=phase, detail=detail, updated=now)
            next_records.append(updated_record)
        else:
            next_records.append(record)
    return sorted(next_records, key=lambda item: item.updated, reverse=True), updated_record


def palette_history_detail(record: PaletteHistoryRecord | None) -> str:
    if record is None:
        return "No palette history for this action yet."
    lines = [
        f"# {record.title}",
        f"Action: {record.action_id}",
        f"Group: {record.group}",
        f"Status: {record.phase}",
        f"Surface: {record.surface}",
        f"Risk: {record.risk}",
        f"Count: {record.count}",
        f"Created: {record.created}",
        f"Updated: {record.updated}",
        f"Detail: {record.detail or 'none'}",
    ]
    if record.command_preview:
        lines.extend(["", "Command preview:", record.command_preview])
    return "\n".join(lines) + "\n"


def palette_history_log(records: list[PaletteHistoryRecord]) -> str:
    if not records:
        return "# Codex Control Palette History\n\nNo palette actions recorded yet.\n"
    lines = ["# Codex Control Palette History", ""]
    for record in sorted(records, key=lambda item: item.updated, reverse=True):
        lines.extend([
            f"## {record.title}",
            f"- Action: {record.action_id}",
            f"- Status: {record.phase}",
            f"- Surface: {record.surface}",
            f"- Risk: {record.risk}",
            f"- Count: {record.count}",
            f"- Updated: {record.updated}",
            f"- Detail: {record.detail or 'none'}",
            "",
        ])
    return "\n".join(lines)
