#!/usr/bin/env python3
"""Persistent Codex Team run inspection and result summaries."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TeamLaneStatus:
    lane_slug: str
    lane_title: str
    device_name: str
    focus: str
    status: str
    detail: str
    handoff_path: str = ""
    final_path: str = ""
    status_path: str = ""
    handoff_bytes: int = 0
    final_bytes: int = 0


@dataclass(frozen=True)
class TeamRunStatus:
    run_id: str
    team_dir: Path
    project: str
    created: str
    assignments: tuple[dict[str, str], ...]
    lanes: tuple[TeamLaneStatus, ...]

    @property
    def collected_count(self) -> int:
        return sum(1 for lane in self.lanes if lane.status in {"collected", "finished"})

    @property
    def lane_count(self) -> int:
        return len(self.lanes)

    def summary_line(self) -> str:
        return f"{self.run_id} | {self.collected_count}/{self.lane_count} lanes collected | {self.project}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_text(path: Path, limit: int = 2400) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[truncated]\n"


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def team_manifest(team_dir: Path) -> dict[str, Any]:
    return _read_json(team_dir / "manifest.json")


def team_assignments(team_dir: Path) -> tuple[dict[str, str], ...]:
    manifest = team_manifest(team_dir)
    raw_assignments = manifest.get("assignments", [])
    assignments: list[dict[str, str]] = []
    if isinstance(raw_assignments, list):
        for item in raw_assignments:
            if isinstance(item, dict):
                assignments.append({str(key): str(value) for key, value in item.items()})
    return tuple(assignments)


def team_run_dirs(team_root: Path) -> tuple[Path, ...]:
    if not team_root.exists():
        return ()
    dirs = [
        path for path in team_root.iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    ]
    return tuple(sorted(dirs, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True))


def latest_team_run_dir(team_root: Path) -> Path | None:
    dirs = team_run_dirs(team_root)
    return dirs[0] if dirs else None


def _lane_file_candidates(team_dir: Path, assignment: dict[str, str], suffix: str) -> tuple[Path, ...]:
    lane_slug = assignment.get("lane_slug", "")
    device_name = assignment.get("device_name", "")
    collected = team_dir / "collected"
    candidates = [
        team_dir / "out" / f"{lane_slug}.{suffix}",
        collected / device_name.lower().replace(" ", "-") / f"{lane_slug}.{suffix}",
    ]
    if collected.exists():
        for folder in collected.iterdir():
            if folder.is_dir():
                candidates.append(folder / f"{lane_slug}.{suffix}")
    return tuple(dict.fromkeys(candidates))


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _lane_status_from_status_file(path: Path | None) -> tuple[str, str]:
    if path is None:
        return "prepared", "waiting for lane output"
    text = _safe_text(path, limit=1000)
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    code = values.get("status", "")
    finished = values.get("finished", "")
    if code == "0":
        return "finished", f"finished {finished}".strip()
    if code:
        return "failed", f"exit {code} {finished}".strip()
    return "finished", text.strip() or "status file present"


def inspect_team_run(team_dir: Path) -> TeamRunStatus:
    manifest = team_manifest(team_dir)
    assignments = team_assignments(team_dir)
    lanes: list[TeamLaneStatus] = []
    for assignment in assignments:
        lane_slug = assignment.get("lane_slug", "")
        handoff = _first_existing(_lane_file_candidates(team_dir, assignment, "handoff.md"))
        final = _first_existing(_lane_file_candidates(team_dir, assignment, "final.txt"))
        status_file = _first_existing(_lane_file_candidates(team_dir, assignment, "status.txt"))
        status, detail = _lane_status_from_status_file(status_file)
        if handoff is not None or final is not None:
            status = "collected" if "collected" in str(handoff or final) else status
            detail = "handoff collected" if handoff is not None else "final message collected"
        lanes.append(TeamLaneStatus(
            lane_slug=lane_slug,
            lane_title=assignment.get("lane_title", "Lane"),
            device_name=assignment.get("device_name", "device"),
            focus=assignment.get("focus", ""),
            status=status,
            detail=detail,
            handoff_path=str(handoff or ""),
            final_path=str(final or ""),
            status_path=str(status_file or ""),
            handoff_bytes=_file_size(handoff) if handoff is not None else 0,
            final_bytes=_file_size(final) if final is not None else 0,
        ))
    return TeamRunStatus(
        run_id=str(manifest.get("run_id") or team_dir.name),
        team_dir=team_dir,
        project=str(manifest.get("project") or ""),
        created=str(manifest.get("created") or ""),
        assignments=assignments,
        lanes=tuple(lanes),
    )


def write_team_summary(team_dir: Path) -> Path:
    status = inspect_team_run(team_dir)
    lines = [
        "# Codex Team Summary",
        "",
        f"Run: {status.run_id}",
        f"Created: {status.created or 'unknown'}",
        f"Project: {status.project or 'unknown'}",
        f"Lanes: {status.collected_count}/{status.lane_count} collected",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        "",
        "## Lanes",
        "",
    ]
    for lane in status.lanes:
        lines.extend([
            f"### {lane.lane_title} | {lane.device_name}",
            "",
            f"Status: {lane.status}",
            f"Focus: {lane.focus}",
            f"Detail: {lane.detail}",
            "",
        ])
        if lane.handoff_path:
            lines.extend(["Handoff:", "", "```text", _safe_text(Path(lane.handoff_path)).strip(), "```", ""])
        if lane.final_path:
            lines.extend(["Final message:", "", "```text", _safe_text(Path(lane.final_path)).strip(), "```", ""])
        if not lane.handoff_path and not lane.final_path:
            lines.append("No collected handoff or final message yet.")
            lines.append("")
    output = team_dir / "summary.md"
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass
    return output


def write_handoff_bus(team_dir: Path) -> Path:
    """Write the redistributed team context every remote lane can read next round."""
    summary_path = write_team_summary(team_dir)
    status = inspect_team_run(team_dir)
    out_dir = team_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    bus_path = out_dir / "handoff-bus.md"
    summary_copy = out_dir / "team-summary.md"
    summary_copy.write_text(summary_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    lines = [
        "# Codex Team Handoff Bus",
        "",
        f"Run: {status.run_id}",
        f"Project: {status.project or 'unknown'}",
        f"Lanes: {status.collected_count}/{status.lane_count} collected",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        "",
        "Next-round protocol:",
        "- Read this file before continuing the lane.",
        "- Read `team-summary.md` for the full current team summary.",
        "- Avoid duplicating teammate work already described below.",
        "- If you continue, write a fresh lane handoff and final message.",
        "- Keep secrets, tokens, passwords, and sudo codes out of handoffs.",
        "",
        "## Lane Handoffs",
        "",
    ]
    for lane in status.lanes:
        lines.extend([
            f"### {lane.lane_title} | {lane.device_name}",
            "",
            f"Status: {lane.status}",
            f"Focus: {lane.focus}",
            f"Detail: {lane.detail}",
            "",
        ])
        if lane.handoff_path:
            lines.extend([
                "Handoff excerpt:",
                "",
                "```text",
                _safe_text(Path(lane.handoff_path), limit=1800).strip(),
                "```",
                "",
            ])
        if lane.final_path:
            lines.extend([
                "Final excerpt:",
                "",
                "```text",
                _safe_text(Path(lane.final_path), limit=1200).strip(),
                "```",
                "",
            ])
        if not lane.handoff_path and not lane.final_path:
            lines.extend(["No collected output yet.", ""])
    bus_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    for path in (bus_path, summary_copy):
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return bus_path


def write_bus_report(team_dir: Path, *, sent: int, failures: list[str], bus_path: Path) -> Path:
    report = {
        "run_id": inspect_team_run(team_dir).run_id,
        "team_dir": str(team_dir),
        "bus_path": str(bus_path),
        "sent": sent,
        "failures": failures,
        "generated": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    path = team_dir / "out" / "handoff-bus-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
