#!/usr/bin/env python3
"""Headless Codex Team orchestration helpers.

This module mirrors the GUI Mesh Team workflow so a commander can run
prepare/sync/launch/collect cycles from terminal without opening GTK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from codex_devices import (
    DeviceRecord,
    DeviceProbe,
    MeshReadinessReport,
    load_devices,
    local_agent_command,
    local_probe_command,
    mesh_readiness_report,
    merge_discovered_devices,
    parse_probe_output,
    remote_agent_command,
    remote_team_dir,
    rsync_project_command,
    rsync_team_chat_pull_command,
    rsync_team_package_command,
    rsync_team_results_command,
    save_devices,
    ssh_mkdir_command,
    ssh_probe_command,
    slugify,
    team_prompt,
    tailscale_status_command,
    update_device_from_probe,
    devices_from_tailscale_status_json,
)
from codex_team import (
    TeamBusTargetStatus,
    is_team_summary_reviewed,
    inspect_team_run,
    latest_team_run_dir,
    load_bus_report,
    mark_team_summary_reviewed,
    team_lane_status_counts,
    write_role_bootstrap,
    write_bus_report,
    write_handoff_bus,
    write_team_summary,
    team_operator_summary,
    team_role_for_device,
    team_run_dirs,
    role_profile_hint,
)


CONFIG_DIR = Path.home() / ".config" / "codex-gui"
DEVICES_FILE = CONFIG_DIR / "devices.json"
TEAM_DIR = CONFIG_DIR / "team"
LAST_TEAM_RUN_FILE = CONFIG_DIR / "team-last-run.json"

BASE_PROMPT = (
    "Continue improving Codex Control toward the best practical version. "
    "Prioritize a premium GTK workstation, robust backend orchestration, "
    "trusted multi-device Codex teamwork, validation, and reversible changes."
)
LAUNCH_READY_STATUSES = {"ready", "ok", "prepared", "launched", "done", "passed"}

def run_cmd(args: list[str], cwd: str | Path | None = None, timeout: int = 20):
    """Run one shell command and return a CompletedProcess."""
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )


def spawn_cmd(args: list[str], cwd: str | Path | None = None):
    """Start a command in the background and return a Popen handle."""
    return subprocess.Popen(
        args,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _safe_text(value: object) -> str:
    return str(value or "").strip()


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text.replace("\n", " ").strip()[:240]


def _one_line(value: object, limit: int = 360) -> str:
    text = str(value or "").strip()
    clean = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return clean[:limit]


def _is_local_host(host: str) -> bool:
    return _safe_text(host).lower() in {"localhost", "127.0.0.1", "::1"}


def _is_trusted(device: DeviceRecord) -> bool:
    identity = f"{device.name} {device.host} {device.note}".lower()
    return "atlas-security" not in identity and device.status != "untrusted"


def _launch_preflight_error(device: DeviceRecord, assignment: Mapping[str, str]) -> str:
    lane_slug = assignment.get("lane_slug", "lane")
    if not _is_trusted(device):
        return f"{device.name}: launch blocked for {lane_slug}: device is not trusted for team lanes"
    if device.status not in LAUNCH_READY_STATUSES:
        status = device.status or "unknown"
        return f"{device.name}: launch blocked for {lane_slug}: saved status {status}; run codex-team-ops check before launching"
    report = mesh_readiness_report((device,), {})
    row = report.by_device(device.id)
    if row is None or not row.is_ready:
        category = row.blocker_category if row is not None else "needs-probe"
        next_action = row.next_actions[0] if row is not None and row.next_actions else "Run `codex-team-ops check` before launching."
        return f"{device.name}: launch blocked for {lane_slug}: {category}; {next_action}"
    return ""


def _run_label() -> str:
    return datetime.now().strftime("team-%Y%m%d-%H%M%S")


def _created_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _project_root_text(path: str) -> str:
    return str(Path(path).expanduser())


def write_last_run(run_dir: Path) -> None:
    payload = {
        "run_id": run_dir.name,
        "team_dir": str(run_dir),
    }
    LAST_TEAM_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_TEAM_RUN_FILE.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    try:
        LAST_TEAM_RUN_FILE.chmod(0o600)
    except OSError:
        pass


def load_last_run() -> Path | None:
    marker = _last_run_marker_status()
    if marker["status"] != "found" or not marker["team_dir"]:
        return None
    return Path(str(marker["team_dir"])).expanduser()


def _last_run_marker_path_for(team_root: Path) -> Path:
    return LAST_TEAM_RUN_FILE if team_root == TEAM_DIR else team_root.parent / LAST_TEAM_RUN_FILE.name


def _run_marker_record(
    status: str,
    summary: str,
    *,
    marker_path: Path | None = None,
    run_id: str = "",
    team_dir: str = "",
    next_actions: tuple[str, ...] = (),
) -> dict[str, Any]:
    marker_file = LAST_TEAM_RUN_FILE if marker_path is None else marker_path
    return {
        "status": status,
        "marker_path": str(marker_file),
        "run_id": _one_line(run_id),
        "team_dir": _one_line(team_dir),
        "summary": summary,
        "next_actions": list(next_actions),
    }


def _last_run_marker_status(marker_path: Path | None = None) -> dict[str, Any]:
    marker_file = LAST_TEAM_RUN_FILE if marker_path is None else marker_path
    if not marker_file.exists():
        return _run_marker_record(
            "absent",
            "No last team run marker was found.",
            marker_path=marker_file,
            next_actions=("Run `codex-team-ops prepare` to create a team run.",),
        )

    try:
        payload = json.loads(marker_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _run_marker_record(
            "corrupt",
            f"Last team run marker is unreadable: {_short_error(exc)}",
            marker_path=marker_file,
            next_actions=("Repair or remove the marker, then run `codex-team-ops prepare`.",),
        )

    if not isinstance(payload, dict):
        return _run_marker_record(
            "corrupt",
            "Last team run marker is not a JSON object.",
            marker_path=marker_file,
            next_actions=("Repair or remove the marker, then run `codex-team-ops prepare`.",),
        )

    run_id = _one_line(payload.get("run_id", ""))
    path_text = str(payload.get("team_dir") or "").strip()
    if not path_text:
        return _run_marker_record(
            "invalid",
            "Last team run marker does not include a team_dir.",
            marker_path=marker_file,
            run_id=run_id,
            next_actions=("Repair or remove the marker, then run `codex-team-ops prepare`.",),
        )

    candidate = Path(path_text).expanduser()
    team_dir = str(candidate)
    if not candidate.exists():
        return _run_marker_record(
            "missing",
            "Last team run marker points to a missing team run directory.",
            marker_path=marker_file,
            run_id=run_id,
            team_dir=team_dir,
            next_actions=("Run `codex-team-ops prepare` to create a fresh team run.",),
        )
    if not candidate.is_dir():
        return _run_marker_record(
            "invalid",
            "Last team run marker does not point to a directory.",
            marker_path=marker_file,
            run_id=run_id,
            team_dir=team_dir,
            next_actions=("Repair or remove the marker, then run `codex-team-ops prepare`.",),
        )
    if not (candidate / "manifest.json").exists():
        return _run_marker_record(
            "invalid",
            "Last team run marker points to a directory without manifest.json.",
            marker_path=marker_file,
            run_id=run_id,
            team_dir=team_dir,
            next_actions=("Select a valid team run or prepare a fresh one.",),
        )
    return _run_marker_record(
        "found",
        "Last team run marker resolves to a saved team run.",
        marker_path=marker_file,
        run_id=run_id or candidate.name,
        team_dir=team_dir,
    )


def discover_mesh_devices(
    *,
    user: str = "ao",
    project_root: str = "~/Projects/codex-gui",
    codex_bin: str = "~/.local/bin/codex",
    include_offline: bool = False,
) -> tuple[DeviceRecord, ...]:
    result = run_cmd(list(tailscale_status_command()), timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"tailscale status failed: {result.stderr or result.stdout}")

    payload = devices_from_tailscale_status_json(
        result.stdout,
        user=user,
        project_root=project_root,
        codex_bin=codex_bin,
        include_self=True,
        local_self_host="localhost",
        include_offline=include_offline,
        worker_os=("linux", "macos"),
    )
    existing = load_devices(DEVICES_FILE)
    merged = merge_discovered_devices(existing, payload)
    save_devices(DEVICES_FILE, merged)
    return merged


def probe_device(device: DeviceRecord) -> DeviceProbe:
    command = local_probe_command(device) if _is_local_host(device.host) else ssh_probe_command(device)
    result = run_cmd(list(command), timeout=35)
    text = result.stdout
    if result.stderr:
        text = f"{text}\n{result.stderr}"
    return parse_probe_output(device, text, result.returncode)


def check_devices(
    devices: tuple[DeviceRecord, ...],
    *,
    persist: bool = True,
) -> tuple[tuple[DeviceRecord, ...], dict[str, DeviceProbe]]:
    probes: dict[str, DeviceProbe] = {}
    updated: list[DeviceRecord] = []
    for device in devices:
        if not _is_trusted(device):
            updated.append(device)
            continue
        probe = probe_device(device)
        probes[device.id] = probe
        updated.append(update_device_from_probe(device, probe))
    updated_devices = tuple(sorted(updated, key=lambda item: item.updated, reverse=True))
    if persist:
        save_devices(DEVICES_FILE, updated_devices)
    return updated_devices, probes


def team_readiness(
    devices: tuple[DeviceRecord, ...],
    probes: Mapping[str, DeviceProbe] | None = None,
) -> MeshReadinessReport:
    return mesh_readiness_report(devices, probes)


def device_for_assignment(
    devices: tuple[DeviceRecord, ...],
    assignment: Mapping[str, str],
) -> DeviceRecord | None:
    device_id = assignment.get("device_id", "")
    if device_id:
        for device in devices:
            if device.id == device_id:
                return device
    device_name = assignment.get("device_name", "").lower()
    if device_name:
        for device in devices:
            if device.name.lower() == device_name:
                return device
    return None


def build_team_assignments(
    devices: tuple[DeviceRecord, ...],
    probes: Mapping[str, DeviceProbe] | None = None,
) -> list[dict[str, str]]:
    report = team_readiness(devices, probes)
    assignments: list[dict[str, str]] = []
    ready_devices = [
        device for device in devices
        if _is_trusted(device)
        and (row := report.by_device(device.id)) is not None
        and row.status == "ready"
    ]

    for index, device in enumerate(ready_devices):
        role = team_role_for_device(device.name, device.host, index)
        lane_title = role.title
        focus = role.assignment_focus()
        lane_slug = slugify(f"{lane_title}-{device.name}")

        assignments.append(
            {
                "device_id": device.id,
                "device_name": device.name,
                "role_id": role.id,
                "role_title": role.title,
                "role_profile": role_profile_hint(role.id),
                "role_focus": role.focus,
                "role_boundary": role.boundary,
                "target": f"{device.target()}:{device.port}",
                "lane_title": lane_title,
                "lane_slug": lane_slug,
                "focus": focus,
                "project_root": device.project_root,
            }
        )

    return assignments


def write_mesh_team_package(
    assignments: list[dict[str, str]],
    project_root: str,
    run_id: str | None = None,
    base_prompt: str = BASE_PROMPT,
    team_root: Path | None = None,
) -> Path:
    run_label = run_id or _run_label()
    root = TEAM_DIR if team_root is None else team_root
    root.mkdir(parents=True, exist_ok=True)
    team_dir = root / run_label
    lanes_dir = team_dir / "lanes"
    out_dir = team_dir / "out"
    collected_dir = team_dir / "collected"

    for directory in (team_dir, lanes_dir, out_dir, collected_dir):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass

    assignment_lines = [
        f"- {item.get('role_title', item['lane_title'])} on {item['device_name']} ({item['target']}): {item['focus']}"
        for item in assignments
    ]
    selected_project = _project_root_text(project_root)

    ledger = "\n".join([
        "# Codex Control Team Ledger",
        "",
        f"Run: {run_label}",
        f"Created: {_created_stamp()}",
        f"Local project: {selected_project}",
        "",
        "Communication protocol:",
        "- Every lane reads this ledger before acting.",
        "- Every lane reads available files in `out/` before finalizing.",
        "- Team chat lives at `out/team-chat.md`; post concise updates here as status changes.",
        "- Every lane writes a concise handoff to `out/<lane>.handoff.md`.",
        "- Collected outputs are pulled back to this run folder with Collect Team.",
        "- No secrets, tokens, passwords, sudo codes, or private credentials go into prompts, logs, or handoffs.",
        "",
        "Assignments:",
        *assignment_lines,
        "",
        "Shared mission:",
        base_prompt.strip(),
        "",
    ])
    (team_dir / "team-ledger.md").write_text(ledger, encoding="utf-8")

    devices = load_devices(DEVICES_FILE)
    device_index = {item.id: item for item in devices}
    for assignment in assignments:
        device = device_index.get(assignment.get("device_id", ""))
        if device is None:
            continue

        teammates = tuple(
            f"{item['lane_title']} on {item['device_name']}"
            for item in assignments
            if item["lane_slug"] != assignment["lane_slug"]
        )

        prompt = team_prompt(
            lane_title=assignment["lane_title"],
            lane_slug=assignment["lane_slug"],
            focus=assignment["focus"],
            base_prompt=base_prompt,
            run_id=run_label,
            device=device,
            teammates=teammates,
            role_id=assignment.get("role_id", ""),
            role_title=assignment.get("role_title", ""),
            role_profile=assignment.get("role_profile", ""),
            role_focus=assignment.get("role_focus", ""),
            role_boundary=assignment.get("role_boundary", ""),
        )
        (lanes_dir / f"{assignment['lane_slug']}.md").write_text(prompt, encoding="utf-8")

    manifest = {
        "run_id": run_label,
        "created": _created_stamp(),
        "project": selected_project,
        "prompt_sha256": hashlib.sha256(base_prompt.encode("utf-8", errors="replace")).hexdigest(),
        "assignments": assignments,
    }
    (team_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    write_role_bootstrap(team_dir, assignments=tuple(assignments))
    write_last_run(team_dir)
    return team_dir


def sync_mesh_team_package(
    team_dir: Path,
    run_id: str,
    assignments: list[dict[str, str]],
    project_root: str,
) -> tuple[list[str], list[TeamBusTargetStatus], Path]:
    bus_path = write_handoff_bus(team_dir)
    local_project = Path(project_root).expanduser()
    if not local_project.exists():
        return [f"local project missing: {local_project}"], [], bus_path

    devices = load_devices(DEVICES_FILE)
    errors: list[str] = []
    targets: list[TeamBusTargetStatus] = []

    def record_target(assignment: dict[str, str], status: str, detail: str, target: str = "") -> None:
        targets.append(TeamBusTargetStatus(
            lane_slug=assignment.get("lane_slug", ""),
            device_name=assignment.get("device_name", "device"),
            target=target or assignment.get("target", ""),
            status=status,
            detail=detail,
            artifact_path=str(bus_path),
        ))

    def record_error(assignment: dict[str, str], detail: str, target: str = "") -> None:
        errors.append(detail)
        record_target(assignment, "failed", detail, target)

    for assignment in assignments:
        device = device_for_assignment(devices, assignment)
        if device is None:
            record_error(
                assignment,
                f"{assignment.get('device_name', 'device')}: missing device record",
            )
            continue
        if _is_local_host(device.host):
            record_target(assignment, "local", "local team package ready", device.target())
            continue

        target_project = Path(device.project_root).expanduser()
        if target_project != local_project:
            try:
                mkdir_result = run_cmd(list(ssh_mkdir_command(device, device.project_root)), timeout=20)
            except Exception as exc:  # noqa: BLE001
                record_error(assignment, f"{device.name}: project mkdir failed: {exc}", device.target())
                continue
            if mkdir_result.returncode != 0:
                detail = (mkdir_result.stderr or mkdir_result.stdout or "mkdir failed").strip().splitlines()
                record_error(
                    assignment,
                    f"{device.name}: project mkdir failed: {detail[-1] if detail else 'mkdir failed'}",
                    device.target(),
                )
                continue

            try:
                project_result = run_cmd(list(rsync_project_command(local_project, device)), timeout=120)
            except Exception as exc:  # noqa: BLE001
                record_error(assignment, f"{device.name}: project sync failed: {exc}", device.target())
                continue
            if project_result.returncode != 0:
                detail = (project_result.stderr or project_result.stdout or "rsync failed").strip().splitlines()
                record_error(
                    assignment,
                    f"{device.name}: project sync failed: {detail[-1] if detail else 'rsync failed'}",
                    device.target(),
                )
                continue

        try:
            team_mkdir = run_cmd(list(ssh_mkdir_command(device, remote_team_dir(run_id))), timeout=20)
        except Exception as exc:  # noqa: BLE001
            record_error(assignment, f"{device.name}: team mkdir failed: {exc}", device.target())
            continue
        if team_mkdir.returncode != 0:
            detail = (team_mkdir.stderr or team_mkdir.stdout or "mkdir failed").strip().splitlines()
            record_error(
                assignment,
                f"{device.name}: team mkdir failed: {detail[-1] if detail else 'mkdir failed'}",
                device.target(),
            )
            continue

        try:
            package_result = run_cmd(list(rsync_team_package_command(team_dir, device, run_id)), timeout=120)
        except Exception as exc:  # noqa: BLE001
            record_error(assignment, f"{device.name}: {exc}", device.target())
            continue
        if package_result.returncode != 0:
            detail = (package_result.stderr or package_result.stdout or "rsync failed").strip().splitlines()
            record_error(assignment, f"{device.name}: {detail[-1] if detail else 'package sync failed'}", device.target())
            continue
        record_target(assignment, "synced", "team package synced", device.target())

    return errors, targets, bus_path


def launch_team_sessions(run_id: str, assignments: list[dict[str, str]]) -> tuple[list[tuple[str, int]], list[str]]:
    devices = load_devices(DEVICES_FILE)
    launched: list[tuple[str, int]] = []
    errors: list[str] = []

    for assignment in assignments:
        device = device_for_assignment(devices, assignment)
        if device is None:
            errors.append(f"{assignment.get('device_name', 'device')}: missing device record")
            continue
        preflight_error = _launch_preflight_error(device, assignment)
        if preflight_error:
            errors.append(preflight_error)
            continue

        command = (
            list(local_agent_command(device, run_id, assignment["lane_slug"]))
            if _is_local_host(device.host)
            else list(remote_agent_command(device, run_id, assignment["lane_slug"]))
        )
        proc = spawn_cmd(command)
        launched.append((assignment["lane_slug"], proc.pid))

    return launched, errors


def collect_team_results(
    team_dir: Path,
    run_id: str,
    assignments: list[dict[str, str]],
) -> tuple[int, list[str]]:
    devices = load_devices(DEVICES_FILE)
    collected = 0
    errors: list[str] = []

    for assignment in assignments:
        device = device_for_assignment(devices, assignment)
        if device is None:
            errors.append(f"{assignment.get('device_name', 'device')}: missing device record")
            continue

        if _is_local_host(device.host):
            collected += 1
            continue

        try:
            result = run_cmd(list(rsync_team_results_command(team_dir, device, run_id)), timeout=90)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{device.name}: {exc}")
            continue

        if result.returncode == 0:
            collected += 1
        else:
            detail = (result.stderr or result.stdout or "rsync failed").strip().splitlines()
            errors.append(f"{device.name}: {detail[-1] if detail else 'rsync failed'}")

    for assignment in assignments:
        device = device_for_assignment(devices, assignment)
        if device is None or _is_local_host(device.host):
            continue
        try:
            run_cmd(list(rsync_team_chat_pull_command(team_dir, device, run_id)), timeout=30)
        except Exception:
            pass

    return collected, errors


def _serialize_run_status(run: Any) -> dict[str, Any]:
    operator = team_operator_summary(run, load_bus_report(run.team_dir))
    return {
        "run_id": run.run_id,
        "team_dir": str(run.team_dir),
        "project": run.project,
        "created": run.created,
        "assignments": [dict(item) for item in run.assignments],
        "lanes": [asdict(lane) for lane in run.lanes],
        "lane_count": run.lane_count,
        "collected_count": run.collected_count,
        "operator": asdict(operator),
    }


def _ready_trusted_count(devices: tuple[DeviceRecord, ...], report: MeshReadinessReport) -> int:
    return sum(
        1 for device in devices
        if _is_trusted(device)
        and (row := report.by_device(device.id)) is not None
        and row.is_ready
    )


def _doctor_lane_counts(run: Any | None) -> dict[str, int]:
    counts = {
        "total": 0,
        "collected": 0,
        "finished": 0,
        "prepared": 0,
        "failed": 0,
    }
    if run is None:
        return counts
    counts.update(team_lane_status_counts(run))
    counts["total"] = run.lane_count
    counts["collected"] = run.collected_count
    return counts


def _doctor_bus_health(
    run: Any | None,
    bus_report: Any | None,
    *,
    summary_reviewed: bool = False,
) -> dict[str, Any]:
    if run is None:
        return {
            "status": "not_started",
            "path": "",
            "synced": 0,
            "failed": 0,
            "stale": 0,
            "targets": 0,
            "failures": 0,
    }
    if bus_report is None:
        status = "reviewed" if summary_reviewed else "not_synced"
        return {
            "status": status,
            "path": str(run.team_dir / "out" / "handoff-bus.md"),
            "synced": 0,
            "failed": 0,
            "stale": 0,
            "targets": 0,
            "failures": 0,
    }
    failures = len(bus_report.failures)
    if summary_reviewed:
        status = "reviewed"
    elif bus_report.failed_count or bus_report.stale_count or failures:
        status = "repair"
    elif bus_report.targets or bus_report.sent:
        status = "healthy"
    else:
        status = "not_synced"
    return {
        "status": status,
        "path": bus_report.bus_path,
        "synced": bus_report.synced_count,
        "failed": bus_report.failed_count,
        "stale": bus_report.stale_count,
        "targets": len(bus_report.targets),
        "failures": failures,
    }


def _doctor_handoff_health(run: Any | None, *, summary_reviewed: bool = False) -> dict[str, Any]:
    if run is None:
        return {
            "status": "not_started",
            "total": 0,
            "present": 0,
            "missing": 0,
            "final_only": 0,
            "pending": 0,
            "lanes": [],
        }

    lanes: list[dict[str, Any]] = []
    present = 0
    missing = 0
    final_only = 0
    pending = 0
    for lane in run.lanes:
        has_handoff = bool(getattr(lane, "handoff_path", ""))
        has_final = bool(getattr(lane, "final_path", ""))
        has_status = bool(getattr(lane, "status_path", ""))
        state = "present"
        if has_handoff:
            present += 1
        elif has_final:
            state = "final_only"
            final_only += 1
            missing += 1
        elif has_status or lane.status in {"finished", "collected"}:
            state = "missing"
            missing += 1
        else:
            state = "pending"
            pending += 1
        lanes.append({
            "lane_slug": lane.lane_slug,
            "device_name": lane.device_name,
            "status": lane.status,
            "handoff": state,
            "has_final": has_final,
            "has_status": has_status,
        })

    if summary_reviewed:
        status = "reviewed"
    elif missing:
        status = "missing"
    elif pending:
        status = "pending"
    elif present == run.lane_count and run.lane_count:
        status = "complete"
    else:
        status = "not_started"

    return {
        "status": status,
        "total": run.lane_count,
        "present": present,
        "missing": missing,
        "final_only": final_only,
        "pending": pending,
        "lanes": lanes,
    }


def _doctor_fleet_blockers(
    devices: tuple[DeviceRecord, ...],
    report: MeshReadinessReport,
) -> list[dict[str, Any]]:
    if not devices:
        return [{
            "scope": "fleet",
            "category": "no-devices",
            "status": "blocked",
            "summary": "No saved mesh devices were found.",
            "next_actions": ["Run `codex-team-ops discover` or add mesh devices before preparing a team."],
        }]

    device_map = {device.id: device for device in devices}
    blockers: list[dict[str, Any]] = []
    for row in report.rows:
        device = device_map.get(row.device_id)
        if row.is_ready and (device is None or _is_trusted(device)):
            continue
        if row.is_ready:
            category = "untrusted-device"
            status = "blocked"
            summary = "Device is ready but not trusted for team lanes."
            next_actions = ["Review the saved device record before assigning team work."]
        else:
            category = row.blocker_category
            status = row.status
            summary = row.summary
            next_actions = list(row.next_actions)
        blockers.append({
            "scope": "fleet",
            "device_id": row.device_id,
            "device_name": row.device_name,
            "category": category,
            "status": status,
            "summary": summary,
            "next_actions": next_actions,
        })
    return blockers


def _doctor_run_blockers(
    run: Any | None,
    bus_report: Any | None,
    inspect_error: str = "",
    *,
    summary_reviewed: bool = False,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if inspect_error:
        blockers.append({
            "scope": "run",
            "category": "inspect-failed",
            "status": "blocked",
            "summary": inspect_error,
            "next_actions": ["Inspect the latest team run manifest and repair unreadable run artifacts."],
        })
        return blockers
    if run is not None and summary_reviewed:
        return blockers
    if run is not None:
        for lane in run.lanes:
            if lane.status != "failed":
                continue
            blockers.append({
                "scope": "run",
                "lane_slug": lane.lane_slug,
                "device_name": lane.device_name,
                "category": "lane-failed",
                "status": lane.status,
                "summary": lane.detail,
                "next_actions": ["Inspect lane output, repair the failure, then collect the team run again."],
            })
    if bus_report is None:
        return blockers
    for target in bus_report.targets:
        if not target.is_failure and target.status != "stale":
            continue
        blockers.append({
            "scope": "bus",
            "lane_slug": target.lane_slug,
            "device_name": target.device_name,
            "category": "handoff-bus",
            "status": target.status,
            "summary": target.detail,
            "next_actions": ["Repair the bus target and sync the handoff bus again."],
        })
    if not bus_report.targets:
        for failure in bus_report.failures:
            blockers.append({
                "scope": "bus",
                "category": "handoff-bus",
                "status": "failed",
                "summary": failure,
                "next_actions": ["Repair the bus failure and sync the handoff bus again."],
            })
    return blockers


def _doctor_handoff_blockers(
    run: Any | None,
    *,
    summary_reviewed: bool = False,
) -> list[dict[str, Any]]:
    if run is None or summary_reviewed:
        return []

    blockers: list[dict[str, Any]] = []
    for lane in run.lanes:
        if lane.handoff_path or lane.status in {"prepared", "failed"}:
            continue
        if not lane.final_path and not lane.status_path and lane.status not in {"finished", "collected"}:
            continue
        if lane.final_path:
            summary = "Lane produced a final message but did not write the required handoff file."
        else:
            summary = "Lane has completion metadata but no required handoff file was collected."
        blockers.append({
            "scope": "handoff",
            "lane_slug": lane.lane_slug,
            "device_name": lane.device_name,
            "category": "missing-handoff",
            "status": "review",
            "summary": summary,
            "next_actions": [
                f"Ask {lane.device_name} to write out/{lane.lane_slug}.handoff.md.",
                "Collect Team again before syncing or reviewing the handoff bus.",
            ],
        })
    return blockers


def _doctor_probe_blockers(probe_error: str = "") -> list[dict[str, Any]]:
    if not probe_error:
        return []
    return [{
        "scope": "fleet",
        "category": "fleet-probe-failed",
        "status": "blocked",
        "summary": probe_error,
        "next_actions": [
            "Run `codex-team-ops check` to capture the exact device probe failure.",
            "Repair the unreachable or timing-out device, then rerun `codex-team-ops doctor --check`.",
        ],
    }]


def _doctor_run_marker_blockers(
    marker: Mapping[str, Any],
    selected_path: Path | None,
) -> list[dict[str, Any]]:
    status = str(marker.get("status") or "")
    if selected_path is not None or status in {"", "absent", "found"}:
        return []
    category = {
        "corrupt": "last-run-corrupt",
        "invalid": "last-run-invalid",
        "missing": "last-run-missing",
    }.get(status, "last-run-marker")
    return [{
        "scope": "run",
        "category": category,
        "status": "review",
        "summary": str(marker.get("summary") or "Last team run marker needs review."),
        "marker_path": str(marker.get("marker_path") or ""),
        "team_dir": str(marker.get("team_dir") or ""),
        "next_actions": list(marker.get("next_actions") or ()),
    }]


def _doctor_readiness_rows(
    devices: tuple[DeviceRecord, ...],
    report: MeshReadinessReport,
) -> list[dict[str, Any]]:
    trusted = {device.id: _is_trusted(device) for device in devices}
    return [
        {
            "device_id": row.device_id,
            "device_name": row.device_name,
            "host": row.host,
            "status": row.status,
            "blocker_category": row.blocker_category,
            "action_priority": row.action_priority,
            "summary": row.summary,
            "next_actions": list(row.next_actions),
            "checked": row.checked,
            "source": row.source,
            "trusted": trusted.get(row.device_id, False),
        }
        for row in report.rows
    ]


def build_team_doctor_report(
    devices: tuple[DeviceRecord, ...],
    *,
    team_root: Path | None = None,
    probes: Mapping[str, DeviceProbe] | None = None,
    probe_mode: str = "saved",
    probe_error: str = "",
) -> dict[str, Any]:
    root = TEAM_DIR if team_root is None else team_root
    probe_map = probes or {}
    readiness = team_readiness(devices, probe_map)
    ready_devices = _ready_trusted_count(devices, readiness)
    assignments = build_team_assignments(devices, probe_map)
    run_dirs = team_run_dirs(root)
    run_marker = _last_run_marker_status(_last_run_marker_path_for(root))
    latest_path = latest_team_run_dir(root)
    if latest_path is None and run_marker["status"] == "found":
        latest_path = Path(str(run_marker["team_dir"])).expanduser()

    run = None
    inspect_error = ""
    if latest_path is not None:
        try:
            run = inspect_team_run(latest_path)
        except Exception as exc:  # noqa: BLE001
            inspect_error = f"{latest_path}: {exc}"

    bus_report = load_bus_report(run.team_dir) if run is not None else None
    summary_reviewed = is_team_summary_reviewed(run.team_dir) if run is not None else False
    handoff_health = _doctor_handoff_health(run, summary_reviewed=summary_reviewed)
    saved_runs = len(run_dirs) if run_dirs else (1 if latest_path is not None else 0)
    operator = team_operator_summary(
        run,
        bus_report,
        ready_devices=ready_devices,
        saved_runs=saved_runs,
        assignment_count=len(assignments),
        summary_reviewed=summary_reviewed,
    )
    blockers = [
        *_doctor_probe_blockers(probe_error),
        *_doctor_fleet_blockers(devices, readiness),
        *_doctor_run_marker_blockers(run_marker, latest_path),
        *_doctor_run_blockers(run, bus_report, inspect_error, summary_reviewed=summary_reviewed),
        *_doctor_handoff_blockers(run, summary_reviewed=summary_reviewed),
    ]
    status = "blocked" if (inspect_error or probe_error) else operator.status
    if probe_error:
        next_action = "Check Fleet"
    elif inspect_error:
        next_action = "Inspect Run"
    elif handoff_health["status"] == "missing" and status != "blocked":
        status = "review"
        next_action = "Review Summary"
    else:
        next_action = operator.next_action
    actionable = status != "blocked" and (ready_devices > 0 or run is not None)

    return {
        "schema": "codex-team-ops-doctor/v1",
        "actionable": actionable,
        "status": status,
        "summary": operator.headline,
        "next_action": next_action,
        "probe_mode": probe_mode,
        "checked_device_count": len(probe_map),
        "ready_device_count": ready_devices,
        "device_count": readiness.total,
        "readiness": {
            "summary": readiness.summary,
            "ready": readiness.ready_count,
            "blocked": readiness.blocked_count,
            "review": readiness.review_count,
            "offline": readiness.offline_count,
            "total": readiness.total,
            "generated": readiness.generated,
            "rows": _doctor_readiness_rows(devices, readiness),
        },
        "saved_run_count": saved_runs,
        "latest_run_id": run.run_id if run is not None else "",
        "latest_run_path": str(run.team_dir if run is not None else latest_path or ""),
        "run_marker": run_marker,
        "summary_reviewed": summary_reviewed,
        "lane_counts": _doctor_lane_counts(run),
        "bus_health": _doctor_bus_health(run, bus_report, summary_reviewed=summary_reviewed),
        "handoff_health": handoff_health,
        "blockers": blockers,
    }


def _resolve_team_dir(team_root: Path, run_id: str | None = None) -> Path:
    if run_id:
        candidate = team_root / run_id
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"team run directory not found: {candidate}")

    latest = latest_team_run_dir(team_root)
    if latest is not None:
        return latest

    marker = _last_run_marker_status(_last_run_marker_path_for(team_root))
    if marker["status"] == "found":
        return Path(str(marker["team_dir"])).expanduser()
    if marker["status"] == "absent":
        raise FileNotFoundError("No prior team run found. Run `prepare` first.")
    actions = marker.get("next_actions") or ["Run `codex-team-ops prepare` to create a fresh team run."]
    raise FileNotFoundError(f"{marker['summary']} {actions[0]}")


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        merged = discover_mesh_devices(
            user=args.user,
            project_root=args.project_root,
            codex_bin=args.codex_bin,
            include_offline=args.include_offline,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"discover failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([asdict(item) for item in merged], indent=2, sort_keys=True))
    else:
        for item in merged:
            print(f"{item.name}\t{item.host}\t{item.status}\t{item.note}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    devices = load_devices(DEVICES_FILE)
    if not devices:
        print("No saved devices. Run discover first.", file=sys.stderr)
        return 2

    checked, probes = check_devices(devices, persist=not args.no_persist)
    report = team_readiness(checked, probes)

    if args.json:
        rows = [asdict(row) for row in report.rows]
        print(json.dumps({
            "persisted": not args.no_persist,
            "summary": report.summary,
            "rows": rows,
        }, sort_keys=True, indent=2))
    else:
        print(report.detail_text())
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    devices = load_devices(DEVICES_FILE)
    if not devices:
        print("No devices saved. Run discover first.", file=sys.stderr)
        return 2

    if args.check:
        devices, probes = check_devices(devices)
    else:
        probes = {}

    assignments = build_team_assignments(devices, probes)
    if not assignments:
        print("No ready trusted devices found. Run discover/check first.", file=sys.stderr)
        return 2

    team_dir = write_mesh_team_package(
        assignments,
        project_root=args.project_root,
        run_id=args.run_id or None,
        base_prompt=args.prompt,
    )

    if args.json:
        print(json.dumps({
            "team_dir": str(team_dir),
            "run_id": team_dir.name,
            "assignments": assignments,
            "lanes": len(assignments),
        }, sort_keys=True))
    else:
        print(team_dir)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    team_dir = _resolve_team_dir(TEAM_DIR, args.run_id)
    run = inspect_team_run(team_dir)

    if args.json:
        print(json.dumps(_serialize_run_status(run), indent=2, sort_keys=True))
        return 0

    print(run.summary_line())
    operator = team_operator_summary(run, load_bus_report(run.team_dir))
    print(f"next: {operator.next_action} | {operator.lane_text} | {operator.bus_text}")
    for lane in run.lanes:
        print(f"- {lane.device_name}: {lane.status} :: {lane.detail}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    devices = load_devices(DEVICES_FILE)
    probes: dict[str, DeviceProbe] = {}
    probe_mode = "saved"
    probe_error = ""
    if args.check and devices:
        probe_mode = "checked"
        try:
            devices, probes = check_devices(devices)
        except Exception as exc:  # noqa: BLE001
            probe_mode = "error"
            probe_error = f"fleet probe failed: {_short_error(exc)}"

    payload = build_team_doctor_report(
        devices,
        probes=probes,
        probe_mode=probe_mode,
        probe_error=probe_error,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    team_dir = _resolve_team_dir(TEAM_DIR, args.run_id)
    summary_path = write_team_summary(team_dir)
    review_path = None
    if args.mark_reviewed:
        review_path = mark_team_summary_reviewed(team_dir)
    text = summary_path.read_text(encoding="utf-8", errors="replace")
    run = inspect_team_run(team_dir)

    if args.json:
        print(json.dumps({
            "team_dir": str(team_dir),
            "summary_path": str(summary_path),
            "summary_bytes": summary_path.stat().st_size,
            "reviewed": review_path is not None,
            "review_path": str(review_path or ""),
            "run_id": run.run_id,
            "lane_count": run.lane_count,
            "collected_count": run.collected_count,
        }, sort_keys=True))
    elif args.print_summary:
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        print(summary_path)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    team_dir = _resolve_team_dir(TEAM_DIR, args.run_id)
    run = inspect_team_run(team_dir)
    assignments = [dict(item) for item in run.assignments]
    errors, targets, bus_path = sync_mesh_team_package(team_dir, team_dir.name, assignments, args.project_root)
    synced = sum(1 for target in targets if target.is_success)
    report_path = write_bus_report(
        team_dir,
        sent=synced,
        failures=errors,
        bus_path=bus_path,
        target_statuses=targets,
    )

    if args.json:
        print(json.dumps({
            "team_dir": str(team_dir),
            "bus_report": str(report_path),
            "errors": errors,
            "synced": synced,
        }, sort_keys=True))
    else:
        print(f"Synced {synced} lane package(s) to remote team dirs")

    if errors:
        for item in errors:
            print(item, file=sys.stderr)
        return 2
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    team_dir = _resolve_team_dir(TEAM_DIR, args.run_id)
    run = inspect_team_run(team_dir)
    assignments = [dict(item) for item in run.assignments]

    if args.sync_before_launch:
        errors, targets, bus_path = sync_mesh_team_package(team_dir, team_dir.name, assignments, args.project_root)
        synced = sum(1 for target in targets if target.is_success)
        write_bus_report(
            team_dir,
            sent=synced,
            failures=errors,
            bus_path=bus_path,
            target_statuses=targets,
        )
        if errors:
            for item in errors:
                print(item, file=sys.stderr)
            return 2

    launched, errors = launch_team_sessions(team_dir.name, assignments)
    if args.json:
        print(json.dumps({"team_dir": str(team_dir), "launched": launched, "errors": errors}))
    else:
        for lane_slug, pid in launched:
            print(f"launched {lane_slug} pid={pid}")

    if errors:
        for item in errors:
            print(item, file=sys.stderr)
        return 2
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    team_dir = _resolve_team_dir(TEAM_DIR, args.run_id)
    run = inspect_team_run(team_dir)
    assignments = [dict(item) for item in run.assignments]

    collected, errors = collect_team_results(team_dir, team_dir.name, assignments)
    try:
        write_team_summary(team_dir)
    except OSError:
        pass
    latest = inspect_team_run(team_dir)

    if args.json:
        print(json.dumps({
            "team_dir": str(team_dir),
            "collected": latest.collected_count,
            "transfer_attempts": collected,
            "lane_count": latest.lane_count,
            "errors": errors,
        }, sort_keys=True))
    else:
        print(f"Collected {latest.collected_count}/{latest.lane_count} lane output(s)")

    if errors:
        for item in errors:
            print(item, file=sys.stderr)
        return 2
    return 0


def cmd_roles(args: argparse.Namespace) -> int:
    devices = load_devices(DEVICES_FILE)
    device_map = {item.id: item for item in devices}
    assignments = build_team_assignments(devices)

    payload = []
    for index, item in enumerate(assignments):
        device = device_map.get(item.get("device_id", ""))
        if device is None:
            continue
        payload.append({
            "index": index,
            "device_name": item["device_name"],
            "device_host": device.host,
            "device_target": f"{device.target()}:{device.port}",
            "role_id": item["role_id"],
            "role_title": item["role_title"],
            "focus": item["focus"],
        })

    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        if not payload:
            print("No ready trusted devices found.")
            return 2
        for item in payload:
            print(f"{item['index']:>2}. {item['device_name']} ({item['device_host']})")
            print(f"    role: {item['role_title']}")
            print(f"    focus: {item['focus']}")
            print(f"    target: {item['device_target']}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="codex-team-ops",
        description="Headless Codex Team orchestration for mesh devices.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    subparsers = parser.add_subparsers(dest="action", required=True)

    discover = subparsers.add_parser("discover", help="Discover mesh devices from Tailscale")
    discover.set_defaults(func=cmd_discover)
    discover.add_argument("--project-root", default="~/Projects/codex-gui")
    discover.add_argument("--user", default="ao")
    discover.add_argument("--codex-bin", default="~/.local/bin/codex")
    discover.add_argument("--include-offline", action="store_true")

    check = subparsers.add_parser("check", help="Probe all saved mesh devices")
    check.set_defaults(func=cmd_check)
    check.add_argument("--no-persist", action="store_true", help="Probe devices without updating devices.json")

    prepare = subparsers.add_parser("prepare", help="Prepare a Codex Team run")
    prepare.set_defaults(func=cmd_prepare)
    prepare.add_argument("--project-root", default="~/Projects/codex-gui")
    prepare.add_argument("--prompt", default=BASE_PROMPT)
    prepare.add_argument("--check", action="store_true", help="Run fleet probe before building assignments")
    prepare.add_argument("--run-id", default="")

    status = subparsers.add_parser("status", help="Show latest team run status")
    status.set_defaults(func=cmd_status)
    status.add_argument("--run-id", default="")

    doctor = subparsers.add_parser("doctor", help="Emit fleet and latest team run doctor JSON")
    doctor.set_defaults(func=cmd_doctor)
    doctor.add_argument("--check", action="store_true", help="Probe saved devices before emitting the doctor report")

    summary = subparsers.add_parser("summary", help="Write and review a team run summary")
    summary.set_defaults(func=cmd_summary)
    summary.add_argument("--run-id", default="")
    summary.add_argument("--print", dest="print_summary", action="store_true", help="Print summary markdown instead of the path")
    summary.add_argument("--mark-reviewed", action="store_true", help="Mark the current summary as reviewed")

    sync = subparsers.add_parser("sync", help="Sync team package to selected devices")
    sync.set_defaults(func=cmd_sync)
    sync.add_argument("--run-id", default="")
    sync.add_argument("--project-root", default="~/Projects/codex-gui")

    launch = subparsers.add_parser("launch", help="Launch all team lanes")
    launch.set_defaults(func=cmd_launch)
    launch.add_argument("--run-id", default="")
    launch.add_argument("--sync", dest="sync_before_launch", action="store_true")
    launch.add_argument("--project-root", default="~/Projects/codex-gui")

    collect = subparsers.add_parser("collect", help="Collect handoff and final outputs")
    collect.set_defaults(func=cmd_collect)
    collect.add_argument("--run-id", default="")

    roles = subparsers.add_parser("roles", help="Show role assignment for ready devices")
    roles.set_defaults(func=cmd_roles)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
