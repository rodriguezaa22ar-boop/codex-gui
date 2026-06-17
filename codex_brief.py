#!/usr/bin/env python3
"""Operator brief synthesis for Codex Control."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SnapshotLike(Protocol):
    name: str
    root: str
    is_git: bool
    branch: str
    dirty: int
    untracked: int
    stack: tuple[str, ...]
    commands: tuple[object, ...]
    recommendation: str


class PreflightLike(Protocol):
    status: str
    score: int
    blocks: int
    warnings: int
    notes: int

    def summary(self) -> str: ...


@dataclass(frozen=True)
class OperatorSignal:
    title: str
    value: str
    detail: str
    status: str = "ok"


@dataclass(frozen=True)
class OperatorBrief:
    generated: int
    title: str
    subtitle: str
    readiness: str
    readiness_status: str
    next_action: str
    signals: tuple[OperatorSignal, ...]


def _project_label(snapshot: SnapshotLike | None, fallback_project: str) -> str:
    if snapshot is not None and snapshot.name:
        return snapshot.name
    return Path(fallback_project).expanduser().name or "project"


def _project_detail(snapshot: SnapshotLike | None) -> tuple[str, str]:
    if snapshot is None:
        return "scanning", "Project intelligence is loading"
    stack = ", ".join(snapshot.stack[:3]) if snapshot.stack else "unknown stack"
    if snapshot.is_git:
        changes = "clean" if not (snapshot.dirty or snapshot.untracked) else f"{snapshot.dirty} tracked, {snapshot.untracked} untracked"
        return stack, f"{snapshot.branch or 'detached'} | {changes}"
    return stack, "folder | no git repo"


def _latest_status(records: list[object], attr: str = "status") -> str:
    if not records:
        return "none"
    return str(getattr(records[0], attr, "unknown") or "unknown")


def build_operator_brief(
    *,
    project: str,
    profile: str,
    mode: str,
    health: dict[str, object],
    snapshot: SnapshotLike | None,
    preflight: PreflightLike | None,
    sessions: list[object],
    autopilot_records: list[object],
    command_runs: list[object],
    agent_runs: list[object],
    receipts: list[object],
) -> OperatorBrief:
    project_name = _project_label(snapshot, project)
    title = f"{project_name} command deck"
    profile_text = profile if profile and profile != "none" else "config default"
    subtitle = f"{profile_text} | {mode}"

    if preflight is None:
        readiness = "checking"
        readiness_status = "review"
        next_action = "Run preflight"
    else:
        readiness = f"{preflight.score} / {preflight.status}"
        readiness_status = preflight.status
        if preflight.status == "blocked":
            next_action = "Open Preflight"
        elif not autopilot_records:
            next_action = "Prepare Autopilot"
        elif _latest_status(autopilot_records) in {"prepared", "done", "failed", "stopped"}:
            next_action = "Track Autopilot"
        elif not sessions:
            next_action = "Save Session"
        else:
            next_action = "Run Max"

    stack, project_state = _project_detail(snapshot)
    codex_version = str(health.get("version") or "checking")
    auth = str(health.get("auth") or "unknown")
    auth_value = "ChatGPT" if "configured" in auth.lower() else auth
    latest_auto = _latest_status(autopilot_records)
    latest_run = _latest_status(command_runs)
    latest_agent = _latest_status(agent_runs)

    signals = (
        OperatorSignal(
            "Readiness",
            readiness,
            preflight.summary() if preflight is not None else "Checking launch path",
            readiness_status,
        ),
        OperatorSignal("Codex", codex_version, auth_value, "ok" if "configured" in auth.lower() or auth_value == "ChatGPT" else "review"),
        OperatorSignal("Project", stack, project_state, "ok" if snapshot is not None else "review"),
        OperatorSignal("Autopilot", latest_auto, f"{len(autopilot_records)} packages", "ok" if autopilot_records else "review"),
        OperatorSignal("Ledger", latest_run, f"{len(command_runs)} runs | {len(receipts)} receipts", "ok" if command_runs else "review"),
        OperatorSignal("Agents", latest_agent, f"{len(agent_runs)} saved plans", "ok" if agent_runs else "review"),
    )
    return OperatorBrief(
        generated=int(time.time()),
        title=title,
        subtitle=subtitle,
        readiness=readiness,
        readiness_status=readiness_status,
        next_action=next_action,
        signals=signals,
    )
