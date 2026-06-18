"""Robust launcher for the Codex GUI.

The installed `codex-gui` entry point should normally import ``codex_gui``
directly from the editable site import path. If that resolution path is ever
missing (for example due to PATH/python env drift on a workstation),
the launcher attempts a small set of local checkout candidates before launching
the real app.
"""

from __future__ import annotations

import argparse
import json
import textwrap
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="codex-gui",
        description="Run Codex GUI or launcher health checks.",
    )
    parser.add_argument("--self-check", action="store_true", help="Run startup checks only")
    parser.add_argument("--json", action="store_true", help="Emit self-check output as JSON")
    parser.add_argument("--project", help="Codex GUI project directory")
    parser.add_argument("--codex-binary", default="codex", help="Codex CLI executable path/name")
    parser.add_argument("--force-start", action="store_true", help="Start anyway when checks return warnings")
    args, _ = parser.parse_known_args(argv)
    return args


def _repo_candidates() -> tuple[Path, ...]:
    home = Path.home()
    cwd = Path.cwd()
    launch_root = Path(__file__).resolve().parent
    candidates: list[Path] = []

    explicit_root = os.environ.get("CODEX_GUI_ROOT")
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser().resolve())

    candidates.extend(
        (
            cwd,
            cwd.parent,
            home / "Projects" / "codex-gui",
            launch_root,
            launch_root.parent,
        )
    )

    normalized: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in normalized:
            normalized.append(resolved)
    return tuple(normalized)


def _ensure_repo_on_path() -> bool:
    for path in _repo_candidates():
        if (path / "codex_gui.py").exists():
            path_text = str(path)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
            return True
    return False


def _project_path(argument: str | None = None) -> Path:
    if argument:
        return Path(argument).expanduser().resolve()
    for path in _repo_candidates():
        if (path / "codex_gui.py").exists():
            return path
    return Path.cwd().resolve()


def _devices_path() -> Path:
    return Path.home() / ".config" / "codex-gui" / "devices.json"


def _desktop_file_path() -> Path:
    return Path.home() / ".local" / "share" / "applications" / "codex-gui.desktop"


def _smoke_log_path() -> Path:
    return Path.home() / ".config" / "codex-gui" / "launcher-smoke.log"


def _status_code(status: str) -> int:
    if status == "blocked":
        return 2
    if status == "review":
        return 1
    return 0


def _collect_setup_report(args: argparse.Namespace):
    from codex_setup import build_setup_report  # local import to keep launcher behavior consistent

    project = _project_path(args.project)
    codex_bin = args.codex_binary.strip() or "codex"

    report = build_setup_report(
        project=str(project),
        codex_bin=codex_bin,
        desktop_file=_desktop_file_path(),
        devices_file=_devices_path(),
    )
    return project, report


def _self_check(args: argparse.Namespace) -> int:
    project, report = _collect_setup_report(args)

    print("Codex GUI Self-Check")
    print(f"Project: {project}")
    if args.json:
        payload = {
            "status": report.status,
            "score": report.score,
            "project": str(project),
            "checks": [asdict(check) for check in report.checks],
            "summary": report.summary(),
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print(report.detail_text())

    return _status_code(report.status)


def _emit_smoke_block(report) -> None:
    blockers = [
        item
        for item in report.checks
        if item.status in {"block", "warn"}
    ]
    if not blockers:
        return

    print("Codex GUI launch blocked: setup checks are not clean.")
    print()
    print("Remediation priority:")
    for item in blockers:
        print(f"- {item.title}: {item.detail}")
        if item.fix:
            print(f"  Fix: {item.fix}")


def _log_smoke_report(project: Path, report, status_code: int) -> None:
    path = _smoke_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": int(time.time()),
        "status": report.status,
        "status_code": status_code,
        "score": report.score,
        "project": str(project),
        "summary": report.summary(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.self_check:
        return _self_check(args)

    project, report = _collect_setup_report(args)
    status = _status_code(report.status)
    _log_smoke_report(project, report, status)

    if status and not args.force_start:
        print(f"Codex GUI launch preflight failed for {project}")
        _emit_smoke_block(report)
        print()
        print("Run one of the following:")
        print(f"  codex-gui --self-check --project {project}")
        print(f"  codex-gui --self-check --project {project} --json")
        print("You can retry with --force-start for temporary bypass.")
        return status

    if not _ensure_repo_on_path():
        _explain_launch_context_and_fail()
    from codex_gui import main as gui_main  # local import, after sys.path guard

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())


def _launch_candidates() -> Iterable[str]:
    return [str(path) for path in _repo_candidates()]


def _explain_launch_context_and_fail() -> None:
    raise ModuleNotFoundError(
        textwrap.dedent(
            """
            Codex GUI launcher failed to resolve `codex_gui`.

            Tried these local checkout candidates:
              {candidates}

            Set CODEX_GUI_ROOT to the absolute codex-gui project directory, or run:
              python3 -m pip install --user .

            Original error: codex_launcher could not locate `codex_gui` after path
            fallback.
            """
        ).format(candidates="\n  ".join(_launch_candidates()))
    )
