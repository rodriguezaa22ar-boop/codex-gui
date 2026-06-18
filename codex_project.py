#!/usr/bin/env python3
"""Project intelligence for Codex Control."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


CODEX_HOME = Path.home() / ".codex"


@dataclass(frozen=True)
class ProjectCommand:
    label: str
    command: str


@dataclass(frozen=True)
class ProjectThread:
    title: str
    updated: int
    tokens: int


@dataclass(frozen=True)
class ProjectSnapshot:
    path: str
    root: str
    name: str
    is_git: bool
    branch: str = ""
    dirty: int = 0
    untracked: int = 0
    changed_files: tuple[str, ...] = ()
    recent_commits: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    commands: tuple[ProjectCommand, ...] = ()
    top_files: tuple[str, ...] = ()
    threads: tuple[ProjectThread, ...] = ()
    recommendation: str = "Explore"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        lines = [
            f"Project: {self.name}",
            f"Path: {self.root}",
            f"Git: {'yes' if self.is_git else 'no'}",
        ]
        if self.is_git:
            lines.append(f"Branch: {self.branch or 'detached'}")
            lines.append(f"Changes: {self.dirty} tracked, {self.untracked} untracked")
        if self.stack:
            lines.append("Stack: " + ", ".join(self.stack))
        if self.commands:
            lines.append("Validation commands: " + "; ".join(command.command for command in self.commands[:5]))
        if self.changed_files:
            lines.append("Changed files: " + ", ".join(self.changed_files[:8]))
        if self.recent_commits:
            lines.append("Recent commits: " + " | ".join(self.recent_commits[:3]))
        if self.threads:
            lines.append("Recent Codex threads: " + " | ".join(thread.title for thread in self.threads[:3]))
        if self.notes:
            lines.append("Notes: " + "; ".join(self.notes))
        return "\n".join(lines)


def run_cmd(args: list[str], cwd: str | None = None, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def git_root(path: str) -> str | None:
    try:
        result = run_cmd(["git", "-C", path, "rev-parse", "--show-toplevel"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def detect_stack(root: Path) -> tuple[str, ...]:
    markers: list[tuple[str, str]] = [
        ("pyproject.toml", "Python"),
        ("requirements.txt", "Python"),
        ("setup.py", "Python"),
        ("package.json", "Node"),
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "Yarn"),
        ("Cargo.toml", "Rust"),
        ("go.mod", "Go"),
        ("deno.json", "Deno"),
        ("bun.lockb", "Bun"),
        ("composer.json", "PHP"),
        ("Gemfile", "Ruby"),
        ("Makefile", "Make"),
        ("meson.build", "Meson"),
        ("CMakeLists.txt", "CMake"),
        ("Dockerfile", "Docker"),
    ]
    found: list[str] = []
    for filename, label in markers:
        if (root / filename).exists() and label not in found:
            found.append(label)
    if any(root.glob("*.sln")):
        found.append(".NET")
    if (root / "codex_gui.py").exists() or any(root.glob("*.ui")):
        if "GTK" not in found:
            found.append("GTK")
    return tuple(found)


def package_scripts(root: Path) -> list[ProjectCommand]:
    package_file = root / "package.json"
    if not package_file.exists():
        return []
    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = data.get("scripts", {})
    commands: list[ProjectCommand] = []
    for key in ["test", "lint", "typecheck", "build", "dev"]:
        if key in scripts:
            commands.append(ProjectCommand(key, f"npm run {key}"))
    return commands


def detect_commands(root: Path, stack: tuple[str, ...]) -> tuple[ProjectCommand, ...]:
    commands: list[ProjectCommand] = []
    if (root / "pyproject.toml").exists() or any(root.glob("*.py")):
        commands.append(ProjectCommand("compile", "python3 -m py_compile $(git ls-files '*.py' 2>/dev/null || find . -name '*.py')"))
        if (root / "tests").exists():
            commands.append(ProjectCommand("tests", "python3 -m unittest discover -s tests"))
    commands.extend(package_scripts(root))
    if (root / "Cargo.toml").exists():
        commands.append(ProjectCommand("cargo test", "cargo test"))
    if (root / "go.mod").exists():
        commands.append(ProjectCommand("go test", "go test ./..."))
    if (root / "Makefile").exists():
        commands.append(ProjectCommand("make", "make"))
    if "GTK" in stack and (root / "codex_gui.py").exists():
        commands.insert(0, ProjectCommand(
            "GUI compile",
            "python3 -m py_compile codex_gui.py codex_actions.py codex_context.py codex_devices.py codex_roadmap.py codex_orchestration.py codex_palette.py codex_visual.py codex_workstation.py codex_brief.py codex_quality.py codex_autopilot.py codex_mission.py codex_prompting.py codex_project.py codex_sessions.py codex_agents.py codex_receipts.py codex_runs.py codex_preflight.py codex_setup.py",
        ))
    seen: set[str] = set()
    unique: list[ProjectCommand] = []
    for command in commands:
        if command.command in seen:
            continue
        seen.add(command.command)
        unique.append(command)
    return tuple(unique[:8])


def top_files(root: Path) -> tuple[str, ...]:
    try:
        items = sorted(root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError:
        return ()
    labels: list[str] = []
    for item in items:
        if item.name.startswith(".") and item.name not in {".env.example", ".github"}:
            continue
        suffix = "/" if item.is_dir() else ""
        labels.append(item.name + suffix)
        if len(labels) >= 14:
            break
    return tuple(labels)


def git_state(root: Path) -> tuple[str, int, int, tuple[str, ...], tuple[str, ...]]:
    branch = run_cmd(["git", "-C", str(root), "branch", "--show-current"]).stdout.strip() or "detached"
    status = run_cmd(["git", "-C", str(root), "status", "--porcelain=v1"], timeout=10).stdout.splitlines()
    dirty = sum(1 for line in status if not line.startswith("??"))
    untracked = sum(1 for line in status if line.startswith("??"))
    changed = tuple(line[3:].strip() for line in status[:12] if len(line) > 3)
    commits = tuple(
        line.strip()
        for line in run_cmd(["git", "-C", str(root), "log", "--oneline", "-5"], timeout=10).stdout.splitlines()
        if line.strip()
    )
    return branch, dirty, untracked, changed, commits


def recent_threads(root: Path, limit: int = 5) -> tuple[ProjectThread, ...]:
    db = CODEX_HOME / "state_5.sqlite"
    if not db.exists():
        return ()
    query = """
        select title, updated_at, tokens_used
        from threads
        where cwd = ?
        order by updated_at desc
        limit ?
    """
    try:
        con = sqlite3.connect(db)
        rows = con.execute(query, (str(root), limit)).fetchall()
        con.close()
    except sqlite3.Error:
        return ()
    return tuple(ProjectThread(title=row[0] or "(untitled)", updated=int(row[1] or 0), tokens=int(row[2] or 0)) for row in rows)


def recommendation_for(snapshot: ProjectSnapshot) -> str:
    if snapshot.dirty or snapshot.untracked:
        return "Review changed work, then implement."
    if not snapshot.stack:
        return "Explore project structure first."
    if snapshot.commands:
        return "Build with validation commands ready."
    return "Map the project, then choose checks."


def inspect_project(path: str) -> ProjectSnapshot:
    selected = Path(path).expanduser()
    selected.mkdir(parents=True, exist_ok=True)
    root_text = git_root(str(selected))
    root = Path(root_text) if root_text else selected
    stack = detect_stack(root)
    commands = detect_commands(root, stack)
    branch = ""
    dirty = 0
    untracked = 0
    changed_files: tuple[str, ...] = ()
    recent_commits: tuple[str, ...] = ()
    if root_text:
        branch, dirty, untracked, changed_files, recent_commits = git_state(root)
    notes: list[str] = []
    if not commands:
        notes.append("No obvious validation command detected")
    if not stack:
        notes.append("No common stack markers found")
    snapshot = ProjectSnapshot(
        path=str(selected),
        root=str(root),
        name=root.name or str(root),
        is_git=bool(root_text),
        branch=branch,
        dirty=dirty,
        untracked=untracked,
        changed_files=changed_files,
        recent_commits=recent_commits,
        stack=stack,
        commands=commands,
        top_files=top_files(root),
        threads=recent_threads(root),
        notes=tuple(notes),
    )
    return ProjectSnapshot(
        **{**snapshot.__dict__, "recommendation": recommendation_for(snapshot)}
    )
