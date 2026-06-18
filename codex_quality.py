#!/usr/bin/env python3
"""Quality gate planning and execution for Codex Control."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

class CommandLike(Protocol):
    label: str
    command: str


class SnapshotLike(Protocol):
    root: str
    name: str
    commands: tuple[CommandLike, ...]


@dataclass(frozen=True)
class QualityCheckSpec:
    label: str
    command: tuple[str, ...]
    cwd: str
    timeout: int = 90
    required: bool = True

    def command_text(self) -> str:
        return " ".join(self.command)


@dataclass(frozen=True)
class QualityPlan:
    project: str
    checks: tuple[QualityCheckSpec, ...]

    def summary(self) -> str:
        return f"{len(self.checks)} checks ready for {Path(self.project).name or self.project}"


@dataclass(frozen=True)
class QualityCheckResult:
    label: str
    command: tuple[str, ...]
    cwd: str
    status: str
    exit_code: int | None
    duration_ms: int
    output_tail: str
    required: bool = True

    def command_text(self) -> str:
        return " ".join(self.command)


@dataclass(frozen=True)
class QualityReport:
    generated: int
    project: str
    status: str
    score: int
    checks: tuple[QualityCheckResult, ...]

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for check in self.checks if check.status == "passed")
        failed = sum(1 for check in self.checks if check.status == "failed")
        return f"{self.score}/100 | {passed}/{total} passed | {failed} failed"

    def detail_text(self) -> str:
        lines = [
            "# Codex Control Quality Gate",
            f"Project: {self.project}",
            f"Status: {self.status}",
            f"Score: {self.score}",
            f"Generated: {self.generated}",
            "",
        ]
        for check in self.checks:
            lines.extend([
                f"## {check.label}",
                f"Status: {check.status}",
                f"Exit: {check.exit_code if check.exit_code is not None else 'timeout'}",
                f"Duration: {check.duration_ms} ms",
                f"CWD: {check.cwd}",
                f"Command: {check.command_text()}",
            ])
            if check.output_tail:
                lines.extend(["", check.output_tail.strip()])
            lines.append("")
        return "\n".join(lines).strip() + "\n"


def _shell_check(label: str, command: str, cwd: str, timeout: int = 120) -> QualityCheckSpec:
    return QualityCheckSpec(label=label, command=("bash", "-lc", command), cwd=cwd, timeout=timeout)


def build_quality_plan(
    *,
    project: str,
    snapshot: SnapshotLike | None,
    codex_bin: str,
    desktop_file: Path | None = None,
) -> QualityPlan:
    cwd = str(Path(snapshot.root if snapshot is not None else project).expanduser())
    checks: list[QualityCheckSpec] = []
    seen: set[str] = set()

    for command in snapshot.commands if snapshot is not None else ():
        if command.command in seen:
            continue
        checks.append(_shell_check(command.label, command.command, cwd))
        seen.add(command.command)
        if len(checks) >= 4:
            break

    visual_module = Path(cwd) / "codex_visual.py"
    if visual_module.exists():
        checks.append(QualityCheckSpec(
            "Visual system audit",
            (
                "python3",
                "-c",
                "from codex_visual import audit_visual_system, visual_system_css; "
                "audit = audit_visual_system(visual_system_css()); "
                "print(audit.summary()); "
                "raise SystemExit(0 if audit.passed else 1)",
            ),
            cwd,
            timeout=20,
        ))

    checks.append(QualityCheckSpec(
        "Setup readiness",
        (
            "python3",
            "-c",
            "from codex_setup import build_setup_report; "
            f"report = build_setup_report(project='.', codex_bin={codex_bin!r}); "
            "print(report.summary()); "
            "raise SystemExit(0 if report.blocks == 0 else 1)",
        ),
        cwd,
        timeout=45,
    ))

    if codex_bin:
        command = (codex_bin, "doctor", "--summary", "--ascii")
        checks.append(QualityCheckSpec("Codex doctor", command, cwd, timeout=45))

    if desktop_file is not None and desktop_file.exists() and shutil.which("desktop-file-validate"):
        checks.append(QualityCheckSpec(
            "Desktop entry",
            ("desktop-file-validate", str(desktop_file)),
            cwd,
            timeout=20,
        ))

    if not checks:
        checks.append(QualityCheckSpec("Project exists", ("test", "-d", cwd), cwd, timeout=10))

    return QualityPlan(project=cwd, checks=tuple(checks))


def _tail(text: str, limit: int = 5000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def run_quality_plan(plan: QualityPlan) -> QualityReport:
    results: list[QualityCheckResult] = []
    for check in plan.checks:
        started = time.monotonic()
        try:
            result = subprocess.run(
                list(check.command),
                cwd=check.cwd,
                text=True,
                capture_output=True,
                timeout=check.timeout,
                check=False,
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            status = "passed" if result.returncode == 0 else "failed"
            exit_code: int | None = result.returncode
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\n[stderr]\n" + exc.stderr if exc.stderr else "")
            status = "failed"
            exit_code = None
        except OSError as exc:
            output = str(exc)
            status = "failed"
            exit_code = 1
        duration_ms = int((time.monotonic() - started) * 1000)
        results.append(QualityCheckResult(
            label=check.label,
            command=check.command,
            cwd=check.cwd,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            output_tail=_tail(output),
            required=check.required,
        ))

    required = [check for check in results if check.required]
    passed = sum(1 for check in required if check.status == "passed")
    score = int((passed / len(required)) * 100) if required else 100
    status = "passed" if passed == len(required) else "failed"
    return QualityReport(
        generated=int(time.time()),
        project=plan.project,
        status=status,
        score=score,
        checks=tuple(results),
    )


def report_to_dict(report: QualityReport) -> dict[str, object]:
    return asdict(report)


def report_from_dict(data: dict[str, object]) -> QualityReport:
    checks = tuple(
        QualityCheckResult(
            label=str(item.get("label") or "check"),
            command=tuple(str(part) for part in item.get("command", ())),
            cwd=str(item.get("cwd") or ""),
            status=str(item.get("status") or "failed"),
            exit_code=item.get("exit_code") if isinstance(item.get("exit_code"), int) else None,
            duration_ms=int(item.get("duration_ms") or 0),
            output_tail=str(item.get("output_tail") or ""),
            required=bool(item.get("required", True)),
        )
        for item in data.get("checks", ())
        if isinstance(item, dict)
    )
    return QualityReport(
        generated=int(data.get("generated") or 0),
        project=str(data.get("project") or ""),
        status=str(data.get("status") or "failed"),
        score=int(data.get("score") or 0),
        checks=checks,
    )


def save_quality_report(path: Path, report: QualityReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report_to_dict(report), indent=2, sort_keys=True), encoding="utf-8")


def load_quality_report(path: Path) -> QualityReport | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report_from_dict(data) if isinstance(data, dict) else None
