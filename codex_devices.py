#!/usr/bin/env python3
"""Multi-device Codex mesh and portable memory helpers."""

from __future__ import annotations

import hashlib
import json
import shlex
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class DeviceRecord:
    id: str
    name: str
    host: str
    user: str = ""
    port: int = 22
    project_root: str = "~/Projects/codex-gui"
    codex_bin: str = "~/.local/bin/codex"
    status: str = "unknown"
    note: str = ""
    updated: int = 0

    def target(self) -> str:
        account = f"{self.user}@" if self.user else ""
        return f"{account}{self.host}"

    def ssh_prefix(self) -> tuple[str, ...]:
        return ("ssh", "-p", str(self.port), self.target())


@dataclass(frozen=True)
class MemoryItem:
    key: str
    value: str
    source: str = "local"
    updated: int = 0


@dataclass(frozen=True)
class MeshState:
    devices: tuple[DeviceRecord, ...]
    memories: tuple[MemoryItem, ...]

    def summary(self) -> str:
        ready = sum(1 for device in self.devices if device.status == "ready")
        return f"{len(self.devices)} device(s) | {ready} ready | {len(self.memories)} memory item(s)"


@dataclass(frozen=True)
class DeviceProbe:
    device_id: str
    status: str
    summary: str
    codex_version: str = ""
    project_root: str = ""
    project_exists: bool = False
    git_state: str = ""
    memory_state: str = ""
    system: str = ""
    checked: int = 0
    returncode: int = 0
    raw: str = ""

    def detail_text(self) -> str:
        lines = [
            f"Status: {self.status}",
            f"Summary: {self.summary}",
        ]
        if self.codex_version:
            lines.append(f"Codex: {self.codex_version}")
        if self.system:
            lines.append(f"System: {self.system}")
        if self.project_root:
            lines.append(f"Project: {self.project_root}")
        if self.git_state:
            lines.append(f"Git: {self.git_state}")
        if self.memory_state:
            lines.append(f"Memory: {self.memory_state}")
        return "\n".join(lines)


def now() -> int:
    return int(time.time())


def slugify(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    clean = "-".join(part for part in clean.split("-") if part)
    return clean or "device"


def device_id(name: str, host: str) -> str:
    seed = f"{name}|{host}".encode("utf-8", errors="replace")
    return f"{slugify(name or host)}-{hashlib.sha256(seed).hexdigest()[:10]}"


def new_device(
    *,
    name: str,
    host: str,
    user: str = "",
    port: int = 22,
    project_root: str = "~/Projects/codex-gui",
    codex_bin: str = "~/.local/bin/codex",
) -> DeviceRecord:
    timestamp = now()
    return DeviceRecord(
        id=device_id(name, host),
        name=name.strip() or host.strip(),
        host=host.strip(),
        user=user.strip(),
        port=int(port or 22),
        project_root=project_root.strip() or "~/Projects/codex-gui",
        codex_bin=codex_bin.strip() or "~/.local/bin/codex",
        updated=timestamp,
    )


def upsert_device(devices: tuple[DeviceRecord, ...], device: DeviceRecord) -> tuple[DeviceRecord, ...]:
    next_devices = [item for item in devices if item.id != device.id]
    next_devices.insert(0, device)
    return tuple(sorted(next_devices, key=lambda item: item.updated, reverse=True))


def remove_device(devices: tuple[DeviceRecord, ...], device_id_value: str) -> tuple[DeviceRecord, ...]:
    return tuple(device for device in devices if device.id != device_id_value)


def update_device(device: DeviceRecord, **changes: object) -> DeviceRecord:
    return replace(device, updated=now(), **changes)


def remote_path_expr(path: str) -> str:
    clean = path.strip() or "~"
    if clean == "~":
        return '"$HOME"'
    if clean.startswith("~/"):
        return '"$HOME"/' + shlex.quote(clean[2:])
    return shlex.quote(clean)


def load_devices(path: Path) -> tuple[DeviceRecord, ...]:
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    devices: list[DeviceRecord] = []
    raw_items = data if isinstance(data, list) else data.get("devices", []) if isinstance(data, dict) else []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        devices.append(DeviceRecord(
            id=str(item.get("id") or device_id(str(item.get("name") or item.get("host") or "device"), str(item.get("host") or ""))),
            name=str(item.get("name") or item.get("host") or "device"),
            host=str(item.get("host") or ""),
            user=str(item.get("user") or ""),
            port=int(item.get("port") or 22),
            project_root=str(item.get("project_root") or "~/Projects/codex-gui"),
            codex_bin=str(item.get("codex_bin") or "~/.local/bin/codex"),
            status=str(item.get("status") or "unknown"),
            note=str(item.get("note") or ""),
            updated=int(item.get("updated") or 0),
        ))
    return tuple(sorted([device for device in devices if device.host], key=lambda item: item.updated, reverse=True))


def save_devices(path: Path, devices: tuple[DeviceRecord, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(device) for device in devices], indent=2, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def load_memory(path: Path) -> tuple[MemoryItem, ...]:
    if not path.exists():
        return ()
    items: list[MemoryItem] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or ":" not in clean:
            continue
        key, value = clean.split(":", 1)
        items.append(MemoryItem(slugify(key), value.strip(), "memory.md", 0))
    return tuple(items)


def save_memory(path: Path, memories: tuple[MemoryItem, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Codex Control Portable Memory",
        "",
        "This file is local, explicit, and safe to sync across your own trusted Codex devices.",
        "It is not ChatGPT's private memory store; copy/import only details you intentionally want Codex Control to use.",
        "",
    ]
    for item in sorted(memories, key=lambda memory: memory.key):
        lines.append(f"- {item.key}: {item.value}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def import_memory_text(existing: tuple[MemoryItem, ...], text: str, source: str = "import") -> tuple[MemoryItem, ...]:
    memories = {item.key: item for item in existing}
    timestamp = now()
    for raw in text.splitlines():
        clean = raw.strip().lstrip("-*").strip()
        if not clean or clean.startswith("#"):
            continue
        if clean == "No memory items saved yet.":
            continue
        if clean.startswith("This file is local") or clean.startswith("It is not ChatGPT"):
            continue
        if ":" in clean:
            key, value = clean.split(":", 1)
        else:
            key, value = clean[:50], clean
        item = MemoryItem(slugify(key), value.strip(), source, timestamp)
        if item.value:
            memories[item.key] = item
    return tuple(sorted(memories.values(), key=lambda item: item.key))


def memory_markdown(memories: tuple[MemoryItem, ...]) -> str:
    if not memories:
        return "# Codex Control Portable Memory\n\nNo memory items saved yet.\n"
    lines = ["# Codex Control Portable Memory", ""]
    for item in sorted(memories, key=lambda memory: memory.key):
        lines.append(f"- {item.key}: {item.value}")
    return "\n".join(lines) + "\n"


def ssh_test_command(device: DeviceRecord) -> tuple[str, ...]:
    return (*device.ssh_prefix(), f"{remote_path_expr(device.codex_bin)} --version && pwd")


def ssh_launch_command(device: DeviceRecord, prompt_path: str = "~/.config/codex-gui/memory.md") -> tuple[str, ...]:
    remote = (
        f"cd {remote_path_expr(device.project_root)} && "
        f"{remote_path_expr(device.codex_bin)} -C {remote_path_expr(device.project_root)} "
        f"\"Use the Codex Control portable memory at {prompt_path} and continue the active project.\""
    )
    return (*device.ssh_prefix(), remote)


def device_probe_script(device: DeviceRecord) -> str:
    project_expr = remote_path_expr(device.project_root)
    codex_expr = remote_path_expr(device.codex_bin)
    return "\n".join([
        "set -u",
        "export PATH=\"$HOME/.local/bin:$HOME/.npm-global/bin:$PATH\"",
        "printf 'CODEX_PROBE=1\\n'",
        "printf 'HOSTNAME=%s\\n' \"$(hostname 2>/dev/null || printf unknown)\"",
        "printf 'UNAME=%s\\n' \"$(uname -srmo 2>/dev/null || uname -a 2>/dev/null || printf unknown)\"",
        f"codex_out=$({codex_expr} --version 2>&1)",
        "codex_code=$?",
        "codex_one_line=$(printf '%s' \"$codex_out\" | tr '\\n' ' ' | sed 's/[[:space:]]\\+/ /g')",
        "printf 'CODEX_EXIT=%s\\n' \"$codex_code\"",
        "printf 'CODEX_VERSION=%s\\n' \"$codex_one_line\"",
        "if [ \"$codex_code\" -ne 0 ]; then exit \"$codex_code\"; fi",
        f"PROJECT_ROOT={project_expr}",
        "printf 'PROJECT_ROOT=%s\\n' \"$PROJECT_ROOT\"",
        "if [ -d \"$PROJECT_ROOT\" ]; then",
        "  printf 'PROJECT_EXISTS=yes\\n'",
        "  cd \"$PROJECT_ROOT\" || exit 12",
        "  printf 'PROJECT_PWD=%s\\n' \"$PWD\"",
        "  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then",
        "    branch=$(git branch --show-current 2>/dev/null || printf detached)",
        "    changes=$(git status --porcelain=v1 2>/dev/null | wc -l | tr -d ' ')",
        "    headline=$(git status --short --branch 2>/dev/null | head -1 | sed 's/[[:space:]]\\+/ /g')",
        "    printf 'GIT_STATE=%s | branch=%s | changes=%s\\n' \"$headline\" \"$branch\" \"$changes\"",
        "  else",
        "    printf 'GIT_STATE=not a git repository\\n'",
        "  fi",
        "else",
        "  printf 'PROJECT_EXISTS=no\\n'",
        "fi",
        "if [ -f \"$HOME/.config/codex-gui/memory.md\" ]; then",
        "  bytes=$(wc -c < \"$HOME/.config/codex-gui/memory.md\" | tr -d ' ')",
        "  printf 'MEMORY_STATE=present bytes=%s\\n' \"$bytes\"",
        "else",
        "  printf 'MEMORY_STATE=missing\\n'",
        "fi",
    ]) + "\n"


def ssh_probe_command(device: DeviceRecord) -> tuple[str, ...]:
    return (*device.ssh_prefix(), "bash -lc " + shlex.quote(device_probe_script(device)))


def parse_probe_output(device: DeviceRecord, text: str, returncode: int, timestamp: int | None = None) -> DeviceProbe:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    checked = now() if timestamp is None else timestamp
    codex_exit = int(values.get("CODEX_EXIT") or returncode or 0)
    codex_version = values.get("CODEX_VERSION", "")
    project_exists = values.get("PROJECT_EXISTS") == "yes"
    project_root = values.get("PROJECT_PWD") or values.get("PROJECT_ROOT") or device.project_root
    git_state = values.get("GIT_STATE", "")
    memory_state = values.get("MEMORY_STATE", "")
    system = values.get("UNAME", "")
    if returncode != 0 or codex_exit != 0:
        status = "blocked"
        summary = codex_version or "probe failed"
    elif not project_exists:
        status = "review"
        summary = f"Codex ready, project missing: {device.project_root}"
    else:
        status = "ready"
        summary = f"{codex_version or 'Codex ready'} | {git_state or 'project ready'}"
    return DeviceProbe(
        device_id=device.id,
        status=status,
        summary=summary,
        codex_version=codex_version,
        project_root=project_root,
        project_exists=project_exists,
        git_state=git_state,
        memory_state=memory_state,
        system=system,
        checked=checked,
        returncode=returncode,
        raw=text,
    )


def note_from_probe(probe: DeviceProbe) -> str:
    parts = [probe.summary]
    if probe.memory_state:
        parts.append(probe.memory_state)
    return " | ".join(part for part in parts if part)


def update_device_from_probe(device: DeviceRecord, probe: DeviceProbe) -> DeviceRecord:
    return update_device(device, status=probe.status, note=note_from_probe(probe))


def rsync_ssh_transport(device: DeviceRecord) -> str:
    return (
        "ssh "
        "-o ConnectTimeout=8 "
        "-o ServerAliveInterval=5 "
        "-o ServerAliveCountMax=2 "
        f"-p {device.port}"
    )


def rsync_base_args(device: DeviceRecord) -> tuple[str, ...]:
    return (
        "rsync",
        "-az",
        "--timeout=20",
        "-e",
        rsync_ssh_transport(device),
    )


def rsync_memory_command(memory_path: Path, device: DeviceRecord) -> tuple[str, ...]:
    target_dir = "~/.config/codex-gui/"
    return (
        *rsync_base_args(device),
        str(memory_path),
        f"{device.target()}:{target_dir}",
    )


def ssh_mkdir_command(device: DeviceRecord, remote_path: str) -> tuple[str, ...]:
    return (*device.ssh_prefix(), f"mkdir -p {remote_path_expr(remote_path)}")


def rsync_project_command(project_path: Path, device: DeviceRecord) -> tuple[str, ...]:
    source = str(project_path).rstrip("/") + "/"
    target = f"{device.target()}:{device.project_root.rstrip('/')}/"
    return (
        *rsync_base_args(device),
        "--exclude",
        "__pycache__/",
        "--exclude",
        ".pytest_cache/",
        "--exclude",
        "*.pyc",
        source,
        target,
    )


def remote_team_dir(run_id: str) -> str:
    return f"~/.config/codex-gui/team/{slugify(run_id)}"


def rsync_team_package_command(team_dir: Path, device: DeviceRecord, run_id: str) -> tuple[str, ...]:
    target_dir = remote_team_dir(run_id) + "/"
    return (
        *rsync_base_args(device),
        str(team_dir).rstrip("/") + "/",
        f"{device.target()}:{target_dir}",
    )


def rsync_team_results_command(team_dir: Path, device: DeviceRecord, run_id: str) -> tuple[str, ...]:
    target_dir = remote_team_dir(run_id) + "/out/"
    local_dir = team_dir / "collected" / slugify(device.name)
    return (
        *rsync_base_args(device),
        f"{device.target()}:{target_dir}",
        str(local_dir) + "/",
    )


def remote_agent_command(device: DeviceRecord, run_id: str, lane_slug: str) -> tuple[str, ...]:
    remote_dir = remote_team_dir(run_id)
    prompt_path = f"{remote_dir}/lanes/{slugify(lane_slug)}.md"
    final_path = f"{remote_dir}/out/{slugify(lane_slug)}.final.txt"
    status_path = f"{remote_dir}/out/{slugify(lane_slug)}.status.txt"
    remote = (
        f"mkdir -p {remote_path_expr(remote_dir + '/out')} && "
        f"cd {remote_path_expr(device.project_root)} && "
        f"prompt=$(cat {remote_path_expr(prompt_path)}) && "
        f"printf 'Remote Codex lane: %s\\n' {shlex.quote(slugify(lane_slug))} && "
        f"{remote_path_expr(device.codex_bin)} -C {remote_path_expr(device.project_root)} "
        f"exec --skip-git-repo-check --output-last-message {remote_path_expr(final_path)} \"$prompt\"; "
        "status=$?; "
        f"printf 'lane=%s\\nstatus=%s\\nfinished=%s\\n' {shlex.quote(slugify(lane_slug))} \"$status\" \"$(date -Is)\" > {remote_path_expr(status_path)}; "
        "exit \"$status\""
    )
    return (*device.ssh_prefix(), remote)


def team_prompt(
    *,
    lane_title: str,
    lane_slug: str,
    focus: str,
    base_prompt: str,
    run_id: str,
    device: DeviceRecord,
    teammates: tuple[str, ...],
) -> str:
    teammate_text = "\n".join(f"- {item}" for item in teammates) if teammates else "- none"
    remote_dir = remote_team_dir(run_id)
    return "\n".join([
        "Use $best-upfront-codex.",
        "",
        f"You are the {lane_title} lane in a distributed Codex Control team.",
        f"Main focus: {focus}",
        f"Assigned device: {device.name} ({device.target()}:{device.port})",
        f"Project root: {device.project_root}",
        "",
        "Team protocol:",
        f"- Read `{remote_dir}/team-ledger.md` before acting.",
        f"- Read any existing files under `{remote_dir}/out/` as teammate handoffs.",
        f"- Keep work scoped to `{device.project_root}` unless the ledger explicitly says otherwise.",
        f"- Write your final handoff to `{remote_dir}/out/{slugify(lane_slug)}.handoff.md`.",
        "- Include changed files, commands run, risks, and exact next handoff needs.",
        "- Do not store secrets, tokens, passwords, or sudo codes.",
        "",
        "Teammates:",
        teammate_text,
        "",
        "Shared mission:",
        base_prompt.strip() or "Improve Codex Control toward the best practical version.",
        "",
    ])


def mesh_state(devices: tuple[DeviceRecord, ...], memories: tuple[MemoryItem, ...]) -> MeshState:
    return MeshState(devices=devices, memories=memories)
