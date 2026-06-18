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
    inspect_team_run,
    latest_team_run_dir,
    write_role_bootstrap,
    write_team_summary,
    team_role_for_device,
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


def _is_local_host(host: str) -> bool:
    return _safe_text(host).lower() in {"localhost", "127.0.0.1", "::1"}


def _is_trusted(device: DeviceRecord) -> bool:
    identity = f"{device.name} {device.host} {device.note}".lower()
    return "atlas-security" not in identity and device.status != "untrusted"


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
    if not LAST_TEAM_RUN_FILE.exists():
        return None
    try:
        payload = json.loads(LAST_TEAM_RUN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    path_text = payload.get("team_dir")
    if not path_text:
        return None
    candidate = Path(path_text)
    return candidate if candidate.exists() else None


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


def check_devices(devices: tuple[DeviceRecord, ...]) -> tuple[tuple[DeviceRecord, ...], dict[str, DeviceProbe]]:
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
    save_devices(DEVICES_FILE, updated_devices)
    return updated_devices, probes


def team_readiness(
    devices: tuple[DeviceRecord, ...],
    probes: Mapping[str, DeviceProbe] | None = None,
) -> MeshReadinessReport:
    return mesh_readiness_report(devices, probes)


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
) -> list[str]:
    local_project = Path(project_root).expanduser()
    if not local_project.exists():
        return [f"local project missing: {local_project}"]

    devices = load_devices(DEVICES_FILE)
    device_map = {item.id: item for item in devices}
    errors: list[str] = []

    for assignment in assignments:
        device = device_map.get(assignment.get("device_id", ""))
        if device is None:
            errors.append(f"{assignment.get('device_name', 'device')}: missing device record")
            continue
        if _is_local_host(device.host):
            continue

        target_project = Path(device.project_root).expanduser()
        if target_project != local_project:
            try:
                mkdir_result = run_cmd(list(ssh_mkdir_command(device, device.project_root)), timeout=20)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{device.name}: project mkdir failed: {exc}")
                continue
            if mkdir_result.returncode != 0:
                detail = (mkdir_result.stderr or mkdir_result.stdout or "mkdir failed").strip().splitlines()
                errors.append(f"{device.name}: project mkdir failed: {detail[-1] if detail else 'mkdir failed'}")
                continue

            try:
                project_result = run_cmd(list(rsync_project_command(local_project, device)), timeout=120)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{device.name}: project sync failed: {exc}")
                continue
            if project_result.returncode != 0:
                detail = (project_result.stderr or project_result.stdout or "rsync failed").strip().splitlines()
                errors.append(f"{device.name}: project sync failed: {detail[-1] if detail else 'rsync failed'}")
                continue

        try:
            team_mkdir = run_cmd(list(ssh_mkdir_command(device, remote_team_dir(run_id))), timeout=20)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{device.name}: team mkdir failed: {exc}")
            continue
        if team_mkdir.returncode != 0:
            detail = (team_mkdir.stderr or team_mkdir.stdout or "mkdir failed").strip().splitlines()
            errors.append(f"{device.name}: team mkdir failed: {detail[-1] if detail else 'mkdir failed'}")
            continue

        try:
            package_result = run_cmd(list(rsync_team_package_command(team_dir, device, run_id)), timeout=120)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{device.name}: {exc}")
            continue
        if package_result.returncode != 0:
            detail = (package_result.stderr or package_result.stdout or "rsync failed").strip().splitlines()
            errors.append(f"{device.name}: {detail[-1] if detail else 'package sync failed'}")

    return errors


def launch_team_sessions(run_id: str, assignments: list[dict[str, str]]) -> tuple[list[tuple[str, int]], list[str]]:
    devices = load_devices(DEVICES_FILE)
    device_map = {item.id: item for item in devices}
    launched: list[tuple[str, int]] = []
    errors: list[str] = []

    for assignment in assignments:
        device = device_map.get(assignment.get("device_id", ""))
        if device is None:
            errors.append(f"{assignment.get('device_name', 'device')}: missing device record")
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
    device_map = {item.id: item for item in devices}
    collected = 0
    errors: list[str] = []

    for assignment in assignments:
        device = device_map.get(assignment.get("device_id", ""))
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
        device = device_map.get(assignment.get("device_id", ""))
        if device is None or _is_local_host(device.host):
            continue
        try:
            run_cmd(list(rsync_team_chat_pull_command(team_dir, device, run_id)), timeout=30)
        except Exception:
            pass

    return collected, errors


def _serialize_run_status(run: Any) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "team_dir": str(run.team_dir),
        "project": run.project,
        "created": run.created,
        "assignments": [dict(item) for item in run.assignments],
        "lanes": [asdict(lane) for lane in run.lanes],
        "lane_count": run.lane_count,
        "collected_count": run.collected_count,
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

    fallback = load_last_run()
    if fallback is None or not fallback.exists():
        raise FileNotFoundError("No prior team run found. Run `prepare` first.")
    return fallback


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

    checked, probes = check_devices(devices)
    report = team_readiness(checked, probes)

    if args.json:
        rows = [asdict(row) for row in report.rows]
        print(json.dumps({"summary": report.summary, "rows": rows}, sort_keys=True, indent=2))
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
    for lane in run.lanes:
        print(f"- {lane.device_name}: {lane.status} :: {lane.detail}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    team_dir = _resolve_team_dir(TEAM_DIR, args.run_id)
    run = inspect_team_run(team_dir)
    assignments = [dict(item) for item in run.assignments]
    errors = sync_mesh_team_package(team_dir, team_dir.name, assignments, args.project_root)

    synced = max(0, len(assignments) - len(errors))
    if args.json:
        print(json.dumps({"team_dir": str(team_dir), "errors": errors, "synced": synced}, sort_keys=True))
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
        errors = sync_mesh_team_package(team_dir, team_dir.name, assignments, args.project_root)
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

    prepare = subparsers.add_parser("prepare", help="Prepare a Codex Team run")
    prepare.set_defaults(func=cmd_prepare)
    prepare.add_argument("--project-root", default="~/Projects/codex-gui")
    prepare.add_argument("--prompt", default=BASE_PROMPT)
    prepare.add_argument("--check", action="store_true", help="Run fleet probe before building assignments")
    prepare.add_argument("--run-id", default="")

    status = subparsers.add_parser("status", help="Show latest team run status")
    status.set_defaults(func=cmd_status)
    status.add_argument("--run-id", default="")

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
