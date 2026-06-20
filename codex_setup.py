#!/usr/bin/env python3
"""First-run setup readiness checks for Codex Control."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetupCheck:
    id: str
    title: str
    status: str
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class SetupReport:
    status: str
    score: int
    checks: tuple[SetupCheck, ...]

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
            return f"Setup blocked: {self.blocks} required item{'s' if self.blocks != 1 else ''} missing"
        if self.status == "review":
            return f"Setup review: {self.warnings} warning{'s' if self.warnings != 1 else ''}"
        return "Setup ready"

    def detail_text(self) -> str:
        lines = [
            "# Codex Control Setup Readiness",
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
            ])
            if check.fix:
                lines.append(f"Fix: {check.fix}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"


def _is_executable(command: str) -> bool:
    path = Path(command).expanduser()
    if path.exists():
        return os.access(path, os.X_OK)
    return shutil.which(command) is not None


def _command_path(command: str) -> str:
    path = Path(command).expanduser()
    return str(path) if path.exists() else command


def _run(args: tuple[str, ...], cwd: Path | None = None, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout, check=False)


def _python_check() -> SetupCheck:
    version = sys.version_info
    text = f"Python {version.major}.{version.minor}.{version.micro}"
    if version >= (3, 11):
        return SetupCheck("python", "Python", "ok", f"{text} satisfies the >=3.11 requirement.")
    return SetupCheck("python", "Python", "block", f"{text} is too old.", "Install Python 3.11 or newer.")


def _gtk_check() -> SetupCheck:
    command = (
        sys.executable,
        "-c",
        "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print(Gtk.MAJOR_VERSION)",
    )
    try:
        result = _run(command, timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SetupCheck("gtk", "GTK 4", "block", f"GTK import check failed: {exc}", "Install PyGObject and GTK 4 runtime packages.")
    if result.returncode == 0:
        return SetupCheck("gtk", "GTK 4", "ok", "PyGObject can import GTK 4.")
    detail = (result.stderr or result.stdout or "GTK import failed").strip().splitlines()[-1]
    return SetupCheck("gtk", "GTK 4", "block", detail, "Install PyGObject and GTK 4 runtime packages.")


def _codex_check(codex_bin: str) -> SetupCheck:
    if not _is_executable(codex_bin):
        return SetupCheck("codex", "Codex CLI", "block", f"Codex executable was not found: {codex_bin}", "Install Codex CLI and confirm `codex --version` works.")
    try:
        result = _run((_command_path(codex_bin), "--version"), timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SetupCheck("codex", "Codex CLI", "block", f"Codex version check failed: {exc}", "Repair the Codex CLI installation.")
    if result.returncode == 0:
        version = (result.stdout or result.stderr).strip().splitlines()[0]
        return SetupCheck("codex", "Codex CLI", "ok", version)
    return SetupCheck("codex", "Codex CLI", "block", (result.stderr or result.stdout).strip(), "Run `codex login` or reinstall the CLI if version checks fail.")


def _terminal_check() -> SetupCheck:
    terminals = ("konsole", "kgx", "gnome-terminal", "xterm")
    found = [name for name in terminals if shutil.which(name)]
    if found:
        return SetupCheck("terminal", "Terminal", "ok", "External terminal fallback: " + ", ".join(found[:3]))
    return SetupCheck("terminal", "Terminal", "warn", "No known external terminal fallback was found.", "Install Konsole, GNOME Console, GNOME Terminal, or xterm.")


def _project_check(project: Path) -> SetupCheck:
    if not project.exists():
        return SetupCheck("project", "Project", "block", f"{project} does not exist.", "Clone or create the project directory.")
    if not project.is_dir():
        return SetupCheck("project", "Project", "block", f"{project} is not a directory.")
    git = _run(("git", "-C", str(project), "rev-parse", "--is-inside-work-tree"), timeout=8)
    if git.returncode != 0:
        return SetupCheck("project", "Project", "warn", f"{project} exists but is not a Git working tree.", "Run `git init` or clone from GitHub.")
    remote = _run(("git", "-C", str(project), "remote", "get-url", "origin"), timeout=8)
    remote_text = remote.stdout.strip()
    if remote.returncode == 0 and remote_text:
        return SetupCheck("project", "Project", "ok", f"Git working tree with origin {remote_text}.")
    return SetupCheck("project", "Project", "note", "Git working tree has no `origin` remote.", "Add a GitHub remote before sharing changes.")


def _packaging_check(project: Path) -> SetupCheck:
    pyproject = project / "pyproject.toml"
    readme = project / "README.md"
    license_file = project / "LICENSE"
    missing = [path.name for path in (pyproject, readme, license_file) if not path.exists()]
    if missing:
        return SetupCheck("packaging", "Public Packaging", "warn", "Missing: " + ", ".join(missing), "Add packaging metadata before publishing.")
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    if "codex-gui" in text and "[project.scripts]" in text:
        return SetupCheck("packaging", "Public Packaging", "ok", "README, LICENSE, pyproject, and `codex-gui` launcher metadata are present.")
    return SetupCheck("packaging", "Public Packaging", "warn", "`codex-gui` launcher metadata is incomplete.", "Add a `[project.scripts]` entry.")


def _launcher_check(project: Path) -> SetupCheck:
    script = Path.home() / ".local" / "bin" / "codex-gui"
    if not script.exists():
        return SetupCheck(
            "launcher",
            "Launcher",
            "note",
            f"{script} is not currently installed.",
            "Run `python3 -m pip install --user .` from this project root.",
        )
    if not os.access(script, os.X_OK):
        return SetupCheck(
            "launcher",
            "Launcher",
            "warn",
            f"{script} is not executable.",
            f"Run `chmod +x {script}` and then reinstall with pip.",
        )
    if not project.exists() or not project.is_dir():
        return SetupCheck(
            "launcher",
            "Launcher",
            "note",
            f"Project path {project} does not exist for launcher import check.",
            "Select a valid codex-gui checkout and rerun setup diagnostics.",
        )
    command = (
        sys.executable,
        "-c",
        "from pathlib import Path; import codex_launcher; import codex_gui; "
        "print(Path(codex_launcher.__file__).resolve()); print(Path(codex_gui.__file__).resolve())",
    )
    result = _run(command, cwd=project, timeout=20)
    if result.returncode == 0:
        lines = (result.stdout or "").splitlines()
        resolved = [line.strip() for line in lines if line.strip()]
        if len(resolved) >= 2:
            launcher_path = Path(resolved[0])
            gui_path = Path(resolved[1])
            if not str(launcher_path).startswith(str(project)):
                return SetupCheck(
                    "launcher",
                    "Launcher",
                    "warn",
                    f"{script} resolves `codex_launcher` from {launcher_path}, not this project.",
                    "Run `python3 -m pip install --user --upgrade --force-reinstall .` or "
                    f"run `CODEX_GUI_ROOT={project} codex-gui --self-check --project {project}` and verify.",
                )
            if not str(gui_path).startswith(str(project)):
                return SetupCheck(
                    "launcher",
                    "Launcher",
                    "warn",
                    f"{script} resolves `codex_gui` from {gui_path}, not this project.",
                    "Run `python3 -m pip install --user --upgrade --force-reinstall .` or "
                    f"run `CODEX_GUI_ROOT={project} codex-gui --self-check --project {project}` and verify.",
                )
        return SetupCheck(
            "launcher",
            "Launcher",
            "ok",
            f"{script} imports and resolves the installed launch path.",
        )
    detail = (result.stderr or result.stdout or "").strip() or "unable to import launcher modules"
    message = f"{script} failed startup checks: {detail}"
    if "could not locate `codex_gui`" in detail.lower():
        return SetupCheck("launcher", "Launcher", "warn", message, "Run `python3 -m pip install --user .` to refresh the entrypoint and `PYTHONPATH` behavior.")
    return SetupCheck(
        "launcher",
        "Launcher",
        "warn",
        message,
        "Run `python3 -m pip install --user .` from this project root.",
    )


def _desktop_check(desktop_file: Path | None) -> SetupCheck:
    if desktop_file is None:
        return SetupCheck("desktop", "Desktop Entry", "note", "No desktop entry path was provided.")
    if not desktop_file.exists():
        return SetupCheck(
            "desktop",
            "Desktop Entry",
            "note",
            f"{desktop_file} is not installed yet.",
            "Run `bash scripts/install-codex-gui-desktop-entry.sh` after install.",
        )
    validator = shutil.which("desktop-file-validate")
    if not validator:
        return SetupCheck("desktop", "Desktop Entry", "note", "desktop-file-validate is not installed.")
    result = _run((validator, str(desktop_file)), timeout=10)
    if result.returncode == 0:
        return SetupCheck("desktop", "Desktop Entry", "ok", f"{desktop_file} validates.")
    return SetupCheck("desktop", "Desktop Entry", "warn", (result.stderr or result.stdout).strip(), "Fix the desktop entry file.")


def _mesh_check(devices_file: Path | None) -> SetupCheck:
    if devices_file is None or not devices_file.exists():
        return SetupCheck("mesh", "Device Mesh", "note", "No trusted devices are configured yet.")
    text = devices_file.read_text(encoding="utf-8", errors="replace")
    ready = text.count('"status": "ready"')
    if ready:
        return SetupCheck("mesh", "Device Mesh", "ok", f"{ready} ready device record{'s' if ready != 1 else ''} configured.")
    return SetupCheck("mesh", "Device Mesh", "note", "Device records exist, but no ready device is recorded yet.")


def build_setup_report(
    *,
    project: str,
    codex_bin: str,
    desktop_file: Path | None = None,
    devices_file: Path | None = None,
) -> SetupReport:
    project_path = Path(project).expanduser()
    checks = (
        _python_check(),
        _gtk_check(),
        _codex_check(codex_bin),
        _terminal_check(),
        _project_check(project_path),
        _packaging_check(project_path),
        _launcher_check(project_path),
        _desktop_check(desktop_file),
        _mesh_check(devices_file),
    )
    blocks = sum(1 for check in checks if check.status == "block")
    warnings = sum(1 for check in checks if check.status == "warn")
    notes = sum(1 for check in checks if check.status == "note")
    status = "blocked" if blocks else ("review" if warnings else "ready")
    score = max(0, 100 - blocks * 30 - warnings * 12 - notes * 3)
    return SetupReport(status=status, score=score, checks=checks)
