#!/usr/bin/env python3
"""Persistent Codex Team run inspection and result summaries."""

from __future__ import annotations

import json
import hashlib
import time
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class TeamRole:
    id: str
    title: str
    focus: str
    boundary: str
    match_terms: tuple[str, ...] = ()

    def assignment_focus(self) -> str:
        return f"{self.focus} Boundary: {self.boundary}"


@dataclass(frozen=True)
class TeamBusTargetStatus:
    lane_slug: str
    device_name: str
    target: str
    status: str
    detail: str
    artifact_path: str = ""
    artifact_sha256: str = ""
    artifact_remote_sha256: str = ""
    ts: int = 0

    @property
    def is_success(self) -> bool:
        return self.status in {"synced", "local"}

    @property
    def is_failure(self) -> bool:
        return self.status == "failed"

    def detail_line(self) -> str:
        return f"{self.device_name}: {self.status} | {self.detail}"


@dataclass(frozen=True)
class TeamBusReport:
    run_id: str
    team_dir: str
    bus_path: str
    sent: int
    failures: tuple[str, ...]
    generated: str
    generated_epoch: int
    targets: tuple[TeamBusTargetStatus, ...] = ()

    @property
    def synced_count(self) -> int:
        return sum(1 for target in self.targets if target.is_success)

    @property
    def failed_count(self) -> int:
        return sum(1 for target in self.targets if target.is_failure)

    @property
    def stale_count(self) -> int:
        return sum(1 for target in self.targets if target.status == "stale")

    def target_for_device(self, device_name: str) -> TeamBusTargetStatus | None:
        return next((
            item for item in self.targets
            if item.device_name == device_name
        ), None)

    def device_status_map(self) -> dict[str, str]:
        return {item.device_name: item.status for item in self.targets}


TEAM_ROLES: tuple[TeamRole, ...] = (
    TeamRole(
        id="coordinator",
        title="Commander / Integrator",
        focus="Own main, GitHub sync, mission packets, merge order, release notes, conflict resolution, and the final quality gate.",
        boundary="Do not disappear into a large feature lane; keep the whole team moving and integrate only reviewed, passing work.",
        match_terms=("localhost", "127.0.0.1", "this device", "local", "atlas-ubuntu", "ubuntu"),
    ),
    TeamRole(
        id="backend-builder",
        title="Core Systems Engineer",
        focus="Own core implementation: mesh orchestration, Tailscale/SSH readiness, local and remote workers, config, persistence, command safety, packaging, setup automation, and tests.",
        boundary="Do not spend time on visual redesign except where backend state or controls need UI exposure.",
        match_terms=("atlas-builder", "builder"),
    ),
    TeamRole(
        id="ui-polish",
        title="Product / GTK UX Engineer",
        focus="Own the user-facing workstation: Mesh page, Command Palette, Quality Gate, Agent Team surfaces, layout, visual hierarchy, text fit, interaction states, and workflow ergonomics.",
        boundary="Do not alter backend behavior beyond small UI plumbing without handing it to Core Systems.",
        match_terms=("atlas-main", "main", "ui", "ux"),
    ),
    TeamRole(
        id="verifier",
        title="Verifier / Release Engineer",
        focus="Own independent validation: fresh clone install, pip launcher, Nix shell, unit tests, compile checks, Quality Gate, docs verification, public release checklist, screenshots, and regression notes.",
        boundary="Prefer exact failing commands, logs, and minimal fix recommendations over broad edits.",
        match_terms=("atlas-cockpit", "cockpit", "verifier", "release", "fresh-clone", "fourth-laptop", "laptop"),
    ),
    TeamRole(
        id="architect",
        title="Architect",
        focus="Split the mission into high-leverage next actions and identify risky assumptions.",
        boundary="Produce plans and interfaces; leave implementation to Builder lanes when possible.",
    ),
    TeamRole(
        id="reviewer",
        title="Reviewer",
        focus="Review diffs for regressions, missing tests, unsafe behavior, and UX gaps.",
        boundary="Do not rewrite large areas unless the review finds a concrete blocker.",
    ),
)


FALLBACK_ROLE_IDS = ("architect", "backend-builder", "reviewer", "ui-polish", "verifier")

ROLE_PRESET_HINTS = {
    "coordinator": "maximum-power",
    "backend-builder": "maximum-power",
    "ui-polish": "maximum-power",
    "verifier": "pro-default",
    "architect": "safe-review",
    "reviewer": "deep-review",
}


def role_profile_hint(role_id: str) -> str:
    return ROLE_PRESET_HINTS.get(role_id, "maximum-power")


def _safe_str(value: Any) -> str:
    text = str(value).strip()
    return text.replace("\n", " ")


def team_role_by_id(role_id: str) -> TeamRole:
    return next((role for role in TEAM_ROLES if role.id == role_id), TEAM_ROLES[0])


def team_role_for_device(name: str, host: str, index: int = 0) -> TeamRole:
    identity = f"{name} {host}".lower()
    for role in TEAM_ROLES:
        if role.match_terms and any(term in identity for term in role.match_terms):
            return role
    fallback_id = FALLBACK_ROLE_IDS[index % len(FALLBACK_ROLE_IDS)]
    return team_role_by_id(fallback_id)


def team_roles_markdown() -> str:
    lines = ["# Codex Team Roles", ""]
    for role in TEAM_ROLES:
        lines.extend([
            f"## {role.title}",
            "",
            f"ID: `{role.id}`",
            f"Focus: {role.focus}",
            f"Boundary: {role.boundary}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


TEAM_CHAT_FILE = "team-chat.md"


def write_role_bootstrap(
    team_dir: Path,
    assignments: tuple[dict[str, str], ...] | None = None,
) -> Path:
    manifest = team_manifest(team_dir)
    manifest_assignments = team_assignments(team_dir) if assignments is None else assignments
    run_id = str(manifest.get("run_id") or str(team_dir.name))
    generated = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = [
        "# Codex Team Role Bootstrap",
        "",
        f"Run: {run_id}",
        f"Project: {manifest.get('project', 'unknown')}",
        f"Generated: {generated}",
        "",
        "## Lane Bootstrap",
        "",
    ]
    lane_payload: list[dict[str, str]] = []
    for assignment in manifest_assignments:
        role_id = assignment.get("role_id", "")
        role = team_role_by_id(role_id)
        role_profile = assignment.get("role_profile", role_profile_hint(role.id))
        role_title = assignment.get("role_title", role.title)
        role_focus = assignment.get("role_focus", role.focus)
        role_boundary = assignment.get("role_boundary", role.boundary)
        device_name = assignment.get("device_name", "unknown")
        lane_slug = assignment.get("lane_slug", "")
        lines.extend([
            f"- {device_name} / {lane_slug}",
            f"  - role_id: {role_id}",
            f"  - role_title: {role_title}",
            f"  - role_profile: {role_profile}",
            f"  - role_focus: {_safe_str(role_focus)}",
            f"  - role_boundary: {_safe_str(role_boundary)}",
            f"  - startup: codex -p {role_profile}",
            "",
        ])
        lane_payload.append({
            "lane_slug": lane_slug,
            "device_name": device_name,
            "role_id": role_id,
            "role_title": role_title,
            "role_profile": role_profile,
            "role_focus": role_focus,
            "role_boundary": role_boundary,
            "startup_command": f"codex -p {role_profile}",
        })

    payload = {
        "run_id": run_id,
        "generated": generated,
        "project": str(manifest.get("project", "")),
        "lane_count": len(manifest_assignments),
        "roles": lane_payload,
    }
    out_dir = team_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        out_dir.chmod(0o700)
    except OSError:
        pass
    markdown_path = out_dir / "role-bootstrap.md"
    json_path = out_dir / "role-bootstrap.json"
    markdown_text = "\n".join(lines).rstrip() + "\n"
    markdown_path.write_text(markdown_text, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        markdown_path.chmod(0o600)
    except OSError:
        pass
    try:
        json_path.chmod(0o600)
    except OSError:
        pass
    return json_path


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


def _file_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
    except Exception:  # noqa: BLE001
        return ""
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


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
        "- Read `team-chat.md` for live role-level updates between lanes.",
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


def load_bus_report(team_dir: Path) -> TeamBusReport | None:
    raw = _read_json(team_dir / "out" / "handoff-bus-report.json")
    if not raw:
        return None
    run_id = str(raw.get("run_id") or inspect_team_run(team_dir).run_id)
    targets: list[TeamBusTargetStatus] = []
    raw_targets = raw.get("targets")
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            targets.append(TeamBusTargetStatus(
                lane_slug=str(item.get("lane_slug", "")),
                device_name=str(item.get("device_name", "")),
                target=str(item.get("target", "")),
                status=str(item.get("status", "")),
                detail=str(item.get("detail", "")),
                artifact_path=str(item.get("artifact_path", "")),
                artifact_sha256=str(item.get("artifact_sha256", "")),
                artifact_remote_sha256=str(item.get("artifact_remote_sha256", "")),
                ts=int(item.get("ts", 0) or 0),
            ))
    return TeamBusReport(
        run_id=run_id,
        team_dir=str(raw.get("team_dir") or team_dir),
        bus_path=str(raw.get("bus_path") or team_dir / "out" / "handoff-bus.md"),
        sent=int(raw.get("sent", 0) or 0),
        failures=tuple(str(item) for item in raw.get("failures", ()) if isinstance(item, str)),
        generated=str(raw.get("generated") or time.strftime('%Y-%m-%dT%H:%M:%S%z')),
        generated_epoch=int(raw.get("generated_epoch") or 0),
        targets=tuple(targets),
    )


def write_bus_report(
    team_dir: Path,
    *,
    sent: int,
    failures: list[str],
    bus_path: Path,
    target_statuses: tuple[TeamBusTargetStatus, ...] | list[TeamBusTargetStatus] = (),
) -> Path:
    target_records = tuple(target_statuses)
    if not target_records:
        target_records = tuple(
            TeamBusTargetStatus(
                lane_slug="",
                device_name=str(failure.split(":", 1)[0].strip() or "legacy"),
                target=str(failure),
                status="failed",
                detail=failure,
                artifact_path=str(bus_path),
                artifact_sha256=_file_sha256(bus_path),
                artifact_remote_sha256="",
                ts=int(time.time()),
            )
            for failure in failures
        )
    generated = int(time.time())
    report = {
        "run_id": inspect_team_run(team_dir).run_id,
        "team_dir": str(team_dir),
        "bus_path": str(bus_path),
        "sent": sent,
        "failures": failures,
        "targets": [asdict(item) for item in target_records],
        "generated_epoch": generated,
        "generated": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    path = team_dir / "out" / "handoff-bus-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def team_chat_path(team_dir: Path) -> Path:
    return team_dir / "out" / TEAM_CHAT_FILE


def read_team_chat(team_dir: Path, max_lines: int = 200) -> str:
    path = team_chat_path(team_dir)
    if not path.exists():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line for line in raw.splitlines() if line.strip()]
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def merge_team_chat_texts(*texts: str) -> str:
    seen: set[str] = set()
    merged: list[str] = []
    for raw in texts:
        for line in raw.splitlines():
            text = line.strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return "\n".join(merged).rstrip() + ("\n" if merged else "")


def write_team_chat_entry(
    team_dir: Path,
    *,
    sender: str,
    lane: str,
    message: str,
) -> Path:
    cleaned_sender = str(sender).strip().replace("\n", " ") or "operator"
    cleaned_lane = str(lane).strip().replace("\n", " ") or "lane"
    cleaned_message = " ".join(str(message).strip().splitlines())
    chat_path = team_chat_path(team_dir)
    out_dir = chat_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        out_dir.chmod(0o700)
    except OSError:
        pass
    if not chat_path.exists():
        header = [
            "# Codex Team Chat",
            "",
            f"Team: {team_dir.name}",
            f"Started: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
            "",
            "Instructions: concise team updates, blockers, and next steps.",
            "",
        ]
        chat_path.write_text("\n".join(header).rstrip() + "\n", encoding="utf-8")
    if cleaned_message:
        line = (
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{cleaned_sender} ({cleaned_lane}): {cleaned_message}"
        )
        with chat_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    try:
        chat_path.chmod(0o600)
    except OSError:
        pass
    return chat_path
