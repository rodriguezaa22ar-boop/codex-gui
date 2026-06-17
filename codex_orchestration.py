#!/usr/bin/env python3
"""Launch orchestration package synthesis for Codex Control."""

from __future__ import annotations

import hashlib
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PreflightLike(Protocol):
    status: str
    score: int

    def summary(self) -> str: ...


class QualityLike(Protocol):
    status: str
    score: int

    def summary(self) -> str: ...


class ContextLike(Protocol):
    status: str
    score: int

    def summary(self) -> str: ...


class RoadmapLike(Protocol):
    status: str
    score: int

    def summary(self) -> str: ...


@dataclass(frozen=True)
class LaunchStep:
    title: str
    detail: str
    status: str = "ready"


@dataclass(frozen=True)
class LaunchPackage:
    generated: int
    project: str
    title: str
    status: str
    score: int
    action: str
    profile: str
    surface: str
    command_hash: str
    prompt_hash: str
    command_preview: str
    receipt_mode: str
    steps: tuple[LaunchStep, ...]

    def summary(self) -> str:
        return f"{self.score}/100 | {self.status} | {self.surface} | {len(self.steps)} steps"

    def detail_text(self) -> str:
        lines = [
            "# Codex Control Launch Package",
            "",
            f"Title: {self.title}",
            f"Project: {self.project}",
            f"Status: {self.status}",
            f"Score: {self.score}",
            f"Generated: {self.generated}",
            f"Action: {self.action}",
            f"Profile: {self.profile}",
            f"Surface: {self.surface}",
            f"Receipt mode: {self.receipt_mode}",
            f"Prompt SHA-256: {self.prompt_hash}",
            f"Command SHA-256: {self.command_hash}",
            "",
            "Command preview:",
            self.command_preview,
            "",
            "Steps:",
        ]
        for step in self.steps:
            lines.extend([
                f"## {step.title}",
                f"Status: {step.status}",
                step.detail,
                "",
            ])
        lines.extend([
            "Privacy boundary:",
            "This launch package is metadata-oriented. Prompts and commands are represented by hashes and a redacted command preview; run ledger and receipt records also avoid raw prompt, command body, terminal output, logs, and model output.",
        ])
        return "\n".join(lines).strip() + "\n"


SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|sudo|authorization)\s*[:=]\s*([^\s,;'\"]+)"),
    re.compile(r"(?i)\b(bearer)\s+([a-z0-9._~+/=-]{12,})"),
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=[redacted]", redacted)
    return redacted


def _clean(text: object, fallback: str = "") -> str:
    value = " ".join(str(text or "").replace("\x00", "").split())
    return _redact(value) or fallback


def _clip(text: str, limit: int = 900) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _command_preview(command: tuple[str, ...], prompt: str = "") -> str:
    if not command:
        return "No command is prepared."
    safe_parts: list[str] = []
    for part in command:
        if prompt and part == prompt:
            safe_parts.append("[prompt redacted; see prompt hash]")
        elif prompt and prompt in part:
            safe_parts.append(part.replace(prompt, "[prompt redacted; see prompt hash]"))
        else:
            safe_parts.append(part)
    return _clip(_redact(shlex.join(tuple(safe_parts))))


def _status_from_inputs(
    *,
    command: tuple[str, ...],
    preflight: PreflightLike | None,
    receipt_auto: bool,
    atlas_ready: bool,
    terminal_ready: bool,
) -> str:
    if not command:
        return "blocked"
    if preflight is not None and preflight.status == "blocked":
        return "blocked"
    if not terminal_ready:
        return "blocked"
    if preflight is not None and preflight.status == "review":
        return "review"
    if receipt_auto and not atlas_ready:
        return "review"
    return "ready"


def _score(
    *,
    command: tuple[str, ...],
    preflight: PreflightLike | None,
    quality: QualityLike | None,
    context: ContextLike | None,
    roadmap: RoadmapLike | None,
    receipt_auto: bool,
    atlas_ready: bool,
    terminal_ready: bool,
) -> int:
    score = 48
    if command:
        score += 10
    if terminal_ready:
        score += 8
    if preflight is not None:
        score += int(preflight.score * 0.14)
        if preflight.status == "blocked":
            score -= 25
        elif preflight.status == "ready":
            score += 8
    if quality is not None:
        score += 12 if quality.status == "passed" else -12
        score += min(6, max(0, quality.score // 18))
    if context is not None:
        score += min(8, max(0, context.score // 14))
    if roadmap is not None:
        score += min(6, max(0, roadmap.score // 18))
    if receipt_auto and atlas_ready:
        score += 5
    elif receipt_auto and not atlas_ready:
        score -= 4
    return max(0, min(100, score))


def _receipt_mode(receipt_auto: bool, atlas_ready: bool) -> str:
    if receipt_auto and atlas_ready:
        return "auto Atlas receipt"
    if receipt_auto:
        return "local ledger, Atlas unavailable"
    return "local ledger only"


def build_launch_package(
    *,
    project: str,
    action: str,
    profile: str,
    surface: str,
    command: tuple[str, ...],
    prompt: str,
    preflight: PreflightLike | None = None,
    quality: QualityLike | None = None,
    context: ContextLike | None = None,
    roadmap: RoadmapLike | None = None,
    receipt_auto: bool = True,
    atlas_ready: bool = False,
    embedded_terminal: bool = False,
    external_terminal: bool = False,
    recent_runs: int = 0,
    receipts: int = 0,
) -> LaunchPackage:
    terminal_ready = embedded_terminal or external_terminal or action in {"doctor", "update", "login", "exec"}
    status = _status_from_inputs(
        command=command,
        preflight=preflight,
        receipt_auto=receipt_auto,
        atlas_ready=atlas_ready,
        terminal_ready=terminal_ready,
    )
    score = _score(
        command=command,
        preflight=preflight,
        quality=quality,
        context=context,
        roadmap=roadmap,
        receipt_auto=receipt_auto,
        atlas_ready=atlas_ready,
        terminal_ready=terminal_ready,
    )
    receipt_mode = _receipt_mode(receipt_auto, atlas_ready)
    command_text = shlex.join(command)
    project_name = Path(project).expanduser().name or project
    steps = [
        LaunchStep(
            "Context Brief",
            context.summary() if context is not None else "Context Packet is not prepared yet.",
            context.status if context is not None else "review",
        ),
        LaunchStep(
            "Roadmap Intent",
            roadmap.summary() if roadmap is not None else "Roadmap is not planned yet.",
            roadmap.status if roadmap is not None else "review",
        ),
        LaunchStep(
            "Preflight",
            preflight.summary() if preflight is not None else "Preflight has not run yet.",
            preflight.status if preflight is not None else "review",
        ),
        LaunchStep(
            "Quality Gate",
            quality.summary() if quality is not None else "No completed Quality Gate report is available.",
            quality.status if quality is not None else "review",
        ),
        LaunchStep(
            "Terminal Surface",
            "Embedded terminal available." if embedded_terminal else ("External terminal fallback available." if external_terminal else "No terminal surface available for interactive launch."),
            "ready" if terminal_ready else "blocked",
        ),
        LaunchStep(
            "Ledger and Receipts",
            f"{recent_runs} run(s) recorded, {receipts} receipt(s) retained, {receipt_mode}.",
            "ready" if not receipt_auto or atlas_ready else "review",
        ),
        LaunchStep(
            "Command Preview",
            _command_preview(command, prompt),
            "ready" if command else "blocked",
        ),
    ]
    return LaunchPackage(
        generated=int(time.time()),
        project=str(Path(project).expanduser()),
        title=f"Launch {project_name} via {surface}",
        status=status,
        score=score,
        action=_clean(action, "interactive"),
        profile=_clean(profile, "none"),
        surface=_clean(surface, "embedded"),
        command_hash=sha256_text(command_text),
        prompt_hash=sha256_text(prompt),
        command_preview=_command_preview(command, prompt),
        receipt_mode=receipt_mode,
        steps=tuple(steps),
    )
