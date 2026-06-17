#!/usr/bin/env python3
"""Launch preflight checks for Codex Control."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SnapshotLike(Protocol):
    is_git: bool
    dirty: int
    untracked: int
    commands: tuple[object, ...]
    stack: tuple[str, ...]


@dataclass(frozen=True)
class PreflightCheck:
    id: str
    title: str
    status: str
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    status: str
    score: int
    checks: tuple[PreflightCheck, ...]

    @property
    def blocks(self) -> int:
        return sum(1 for check in self.checks if check.status == "block")

    @property
    def warnings(self) -> int:
        return sum(1 for check in self.checks if check.status == "warn")

    @property
    def notes(self) -> int:
        return sum(1 for check in self.checks if check.status == "note")

    @property
    def ok(self) -> int:
        return sum(1 for check in self.checks if check.status == "ok")

    def summary(self) -> str:
        if self.status == "blocked":
            return f"Blocked: {self.blocks} launch issue{'s' if self.blocks != 1 else ''}"
        if self.status == "review":
            return f"Review: {self.warnings} warning{'s' if self.warnings != 1 else ''}, {self.notes} notes"
        if self.notes:
            return f"Ready: {self.notes} operational notes"
        return "Ready: launch path is clean"

    def detail_text(self) -> str:
        lines = [
            "# Launch Preflight",
            "",
            f"Status: {self.status}",
            f"Score: {self.score}",
            f"Checks: {self.ok} ok, {self.notes} notes, {self.warnings} warnings, {self.blocks} blocked",
            "",
        ]
        for check in self.checks:
            lines.extend([
                f"## {check.title}",
                f"Status: {check.status}",
                check.detail,
                "",
            ])
        return "\n".join(lines).strip()


def codex_available(codex_bin: str) -> bool:
    path = Path(codex_bin).expanduser()
    if path.exists() and os.access(path, os.X_OK):
        return True
    return shutil.which(codex_bin) is not None


def build_preflight_report(
    *,
    project: str,
    prompt: str,
    action: str,
    profile: str,
    model: str,
    reasoning: str,
    sandbox: str,
    approval: str,
    web: str,
    skip_git: bool,
    receipt_auto: bool,
    codex_bin: str,
    codex_ready: bool,
    auth_summary: str,
    terminal_available: bool,
    embedded_terminal: bool,
    atlas_ready: bool,
    available_profiles: tuple[str, ...] = (),
    snapshot: SnapshotLike | None = None,
) -> PreflightReport:
    checks: list[PreflightCheck] = []
    project_path = Path(project).expanduser()

    if project_path.exists() and project_path.is_dir():
        checks.append(PreflightCheck("project", "Project", "ok", f"Using {project_path}"))
    else:
        checks.append(PreflightCheck("project", "Project", "block", f"{project_path} is not an existing directory."))

    if codex_ready:
        checks.append(PreflightCheck("codex", "Codex CLI", "ok", f"Command path is available: {codex_bin}"))
    else:
        checks.append(PreflightCheck("codex", "Codex CLI", "block", f"Codex CLI was not found or is not executable: {codex_bin}"))

    auth_text = auth_summary.strip() or "unknown"
    if "configured" in auth_text.lower() or "chatgpt" in auth_text.lower():
        checks.append(PreflightCheck("auth", "Auth", "ok", auth_text))
    else:
        checks.append(PreflightCheck("auth", "Auth", "warn", f"Codex auth is {auth_text}; launch may require sign-in."))

    prompt_text = prompt.strip()
    if action == "exec" and not prompt_text:
        checks.append(PreflightCheck("prompt", "Prompt", "block", "`codex exec` needs a concrete prompt."))
    elif action in {"doctor", "update", "login"}:
        checks.append(PreflightCheck("prompt", "Prompt", "ok", f"{action} does not require a prompt."))
    elif not prompt_text:
        checks.append(PreflightCheck("prompt", "Prompt", "note", "No prompt is set; Codex will open as an interactive session."))
    elif len(prompt_text) < 20:
        checks.append(PreflightCheck("prompt", "Prompt", "note", "Prompt is short; Prompt Lab can expand it before launch."))
    else:
        checks.append(PreflightCheck("prompt", "Prompt", "ok", f"{len(prompt_text)} characters ready."))

    if action in {"interactive", "resume", "review"}:
        if embedded_terminal:
            checks.append(PreflightCheck("terminal", "Terminal", "ok", "Embedded VTE terminal is available."))
        elif terminal_available:
            checks.append(PreflightCheck("terminal", "Terminal", "note", "External terminal fallback is available."))
        else:
            checks.append(PreflightCheck("terminal", "Terminal", "block", "No embedded or external terminal was found."))
    else:
        checks.append(PreflightCheck("terminal", "Terminal", "ok", f"{action} can run without an interactive terminal."))

    if profile in {"", "none", "config"}:
        checks.append(PreflightCheck("profile", "Profile", "ok", "Using Codex config defaults."))
    elif profile in available_profiles:
        checks.append(PreflightCheck("profile", "Profile", "ok", f"{profile} profile is installed."))
    else:
        checks.append(PreflightCheck("profile", "Profile", "warn", f"{profile} profile was not found in ~/.codex/*.config.toml."))

    high_trust = profile == "maximum-power" or (sandbox == "danger-full-access" and approval == "never")
    if high_trust:
        checks.append(PreflightCheck("power", "Power Mode", "note", "High-trust launch: full access and no approval prompts are intentional for this profile."))
    else:
        checks.append(PreflightCheck("power", "Power Mode", "ok", f"sandbox={sandbox}, approval={approval}, reasoning={reasoning}, web={web}, model={model}"))

    if snapshot is None:
        checks.append(PreflightCheck("project-scan", "Project Scan", "note", "Project intelligence is still scanning."))
    else:
        if action == "exec" and not snapshot.is_git and not skip_git:
            checks.append(PreflightCheck("git-gate", "Git Gate", "block", "Selected project is not a Git repo and `No git gate` is off for exec."))
        elif snapshot.is_git:
            state = "clean"
            status = "ok"
            if snapshot.dirty or snapshot.untracked:
                state = f"{snapshot.dirty} tracked and {snapshot.untracked} untracked changes"
                status = "note"
            checks.append(PreflightCheck("git-state", "Git State", status, f"Repository detected; state is {state}."))
        else:
            checks.append(PreflightCheck("git-state", "Git State", "note", "Not a Git repository; worktree isolation and Git diff tools may be limited."))

        if snapshot.commands:
            checks.append(PreflightCheck("validation", "Validation", "ok", f"{len(snapshot.commands)} validation command{'s' if len(snapshot.commands) != 1 else ''} detected."))
        else:
            checks.append(PreflightCheck("validation", "Validation", "note", "No project validation command was detected."))

        if snapshot.stack:
            checks.append(PreflightCheck("stack", "Stack", "ok", ", ".join(snapshot.stack)))
        else:
            checks.append(PreflightCheck("stack", "Stack", "note", "No common stack markers detected."))

    if not receipt_auto:
        checks.append(PreflightCheck("receipt", "Receipt", "note", "Automatic receipt stamping is off."))
    elif atlas_ready:
        checks.append(PreflightCheck("receipt", "Receipt", "ok", "Atlas receipt engine is available for metadata-only launch receipts."))
    else:
        checks.append(PreflightCheck("receipt", "Receipt", "warn", "Auto receipts are on, but Atlas binary is not available; only local run metadata will persist."))

    blocks = sum(1 for check in checks if check.status == "block")
    warnings = sum(1 for check in checks if check.status == "warn")
    notes = sum(1 for check in checks if check.status == "note")
    status = "blocked" if blocks else ("review" if warnings else "ready")
    score = max(0, 100 - blocks * 35 - warnings * 12 - notes * 4)
    return PreflightReport(status=status, score=score, checks=tuple(checks))
