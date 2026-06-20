#!/usr/bin/env python3
"""Multi-device Codex mesh and portable memory helpers."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping


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


@dataclass(frozen=True)
class MeshReadinessRow:
    device_id: str
    device_name: str
    host: str
    status: str
    blocker_category: str
    action_priority: int
    summary: str
    next_actions: tuple[str, ...]
    checked: int = 0
    source: str = "saved"

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @property
    def readiness(self) -> str:
        if _is_local_host(self.host) and self.status == "ready":
            return "local-ready"
        if self.status == "ready" and self.blocker_category == "stale-checkout":
            return "stale-checkout"
        if self.status == "review" and self.blocker_category == "missing-project":
            return "missing-project"
        if self.status == "review" and self.blocker_category == "missing-codex":
            return "missing-codex"
        if self.status == "review":
            return "needs-review"
        if self.status == "offline":
            return "offline-or-timeout"
        if self.status == "blocked":
            return {
                "tailscale-approval": "blocked-tailscale-approval",
                "ssh-auth": "blocked-ssh-auth",
                "dns": "blocked-dns",
                "connection-refused": "blocked-connection-refused",
            }.get(self.blocker_category, "blocked-ssh")
        if self.status == "ready":
            return "ready"
        return "needs-check"

    @property
    def blocker(self) -> str:
        return self.summary

    @property
    def next_action(self) -> str:
        return self.next_actions[0] if self.next_actions else ""


@dataclass(frozen=True)
class MeshReadinessReport:
    generated: int
    rows: tuple[MeshReadinessRow, ...]

    @property
    def ready_count(self) -> int:
        return sum(1 for row in self.rows if row.is_ready)

    @property
    def review_count(self) -> int:
        return sum(1 for row in self.rows if row.status in {"review", "unknown"})

    @property
    def offline_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "offline")

    @property
    def blocked_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "blocked")

    @property
    def warning_count(self) -> int:
        return sum(
            1
            for row in self.rows
            if row.readiness in {"missing-project", "missing-codex", "stale-checkout", "needs-review"}
        )

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def summary(self) -> str:
        return (
            f"{self.total} device(s) | "
            f"{self.ready_count} ready | "
            f"{self.blocked_count} blocked | "
            f"{self.review_count} review | "
            f"{self.offline_count} offline"
        )

    def by_device(self, device_id: str) -> MeshReadinessRow | None:
        return next((row for row in self.rows if row.device_id == device_id), None)

    @property
    def entries(self) -> tuple[MeshReadinessRow, ...]:
        return self.rows

    def summary_text(self) -> str:
        return (
            f"{self.total} device(s) | {self.ready_count} ready | "
            f"{self.warning_count} warning | {self.blocked_count} blocked"
        )

    def detail_text(self) -> str:
        lines = [
            "# Mesh readiness",
            self.summary,
            "",
        ]
        for row in self.rows:
            lines.extend([
                f"## {row.device_name} ({row.host})",
                f"Status: {row.status}",
                f"Category: {row.blocker_category}",
                f"Priority: {row.action_priority}",
                f"Summary: {row.summary}",
            ])
            if row.checked:
                lines.append(f"Checked: {row.checked}")
            if row.next_actions:
                lines.append("Next steps:")
                lines.extend([f"- {item}" for item in row.next_actions])
            lines.append("")
        return "\n".join(lines).strip() + "\n"


def now() -> int:
    return int(time.time())


def _is_local_host(host: str) -> bool:
    return host.strip().lower() in {"localhost", "127.0.0.1", "::1"}


def _git_state_change_count(git_state: str) -> int:
    for token in git_state.replace("|", " ").replace(";", " ").split():
        if token.startswith("changes="):
            try:
                return int(token.split("=", 1)[1])
            except ValueError:
                return 0
    return 0


def _is_stale_checkout(git_state: str) -> bool:
    lower = git_state.lower().strip()
    if not lower:
        return False
    if "detached" in lower or "not currently on a branch" in lower:
        return True
    if "[behind" in lower or "behind " in lower or "diverged" in lower:
        return True
    return False


def _has_uncommitted_changes(git_state: str) -> bool:
    return _git_state_change_count(git_state) > 0


def _missing_codex_hint(probe: DeviceProbe, device: DeviceRecord) -> bool:
    haystack = f"{probe.raw} {probe.summary} {probe.codex_version} {probe.returncode}".lower()
    codex_name = Path(device.codex_bin).name.lower() if device.codex_bin else "codex"
    if "codex cli missing" in haystack or "codex executable not found" in haystack:
        return True
    if "no such file" in haystack and ("codex" in haystack or codex_name in haystack):
        return True
    if "command not found" in haystack:
        return True
    return False


def _ssh_probe_hint_category(probe: DeviceProbe) -> str:
    return _ssh_text_hint_category(f"{probe.summary} {probe.raw}")


def _ssh_text_hint_category(text: str) -> str:
    haystack = text.lower()
    if (
        "host cannot be resolved" in haystack
        or "could not resolve hostname" in haystack
        or "name or service not known" in haystack
        or "temporary failure in name resolution" in haystack
        or "nodename nor servname provided" in haystack
    ):
        return "ssh-host-unresolved"
    if "host key verification failed" in haystack or "remote host identification has changed" in haystack:
        return "ssh-host-key-unverified"
    if "connection refused" in haystack:
        return "ssh-connection-refused"
    if "host unreachable" in haystack or "no route to host" in haystack or "network is unreachable" in haystack:
        return "ssh-host-unreachable"
    if "connection closed" in haystack or "connection reset by peer" in haystack:
        return "ssh-connection-closed"
    return ""


def _saved_note_blocker_category(device: DeviceRecord) -> str:
    haystack = f"{device.status} {device.note}".lower()
    if not haystack.strip():
        return "needs-probe"
    if "login.tailscale.com/a/" in haystack or ("tailscale" in haystack and "approval" in haystack):
        return "tailscale-approval-required"
    if (
        "ssh auth denied" in haystack
        or "permission denied" in haystack
        or "publickey" in haystack
        or "auth denied" in haystack
    ):
        return "ssh-auth-denied"
    if ssh_category := _ssh_text_hint_category(haystack):
        return ssh_category
    if "timed out" in haystack or "timeout" in haystack or "offline" in haystack:
        return "offline-or-timeout"
    if (
        "codex cli missing" in haystack
        or "codex executable not found" in haystack
        or "codex: command not found" in haystack
        or ("no such file" in haystack and "codex" in haystack)
    ):
        return "missing-codex"
    if "project missing" in haystack or "project_exists=no" in haystack:
        return "missing-project"
    if "checkout is stale" in haystack or "detached" in haystack or "[behind" in haystack or "behind " in haystack or "diverged" in haystack:
        return "stale-checkout"
    if "uncommitted changes" in haystack or "changes=" in haystack:
        return "needs-review"
    return "needs-probe"


def _saved_note_status(device: DeviceRecord, category: str) -> str:
    if device.status == "offline" or category in {"offline-or-timeout", "ssh-host-unreachable"}:
        return "offline"
    if category in {"missing-project", "stale-checkout", "needs-review"}:
        return "review"
    if device.status == "blocked" or category in {
        "tailscale-approval-required",
        "ssh-auth-denied",
        "ssh-host-unresolved",
        "ssh-host-key-unverified",
        "ssh-connection-refused",
        "ssh-connection-closed",
        "missing-codex",
    }:
        return "blocked"
    return "review"


def _saved_note_summary(category: str, status: str) -> str:
    summaries = {
        "tailscale-approval-required": "Saved mesh state indicates Tailscale SSH approval is required.",
        "ssh-auth-denied": "Saved mesh state indicates SSH authentication is denied.",
        "ssh-host-unresolved": "Saved mesh state indicates the SSH host cannot be resolved.",
        "ssh-host-key-unverified": "Saved mesh state indicates SSH host key trust needs review.",
        "ssh-connection-refused": "Saved mesh state indicates SSH is refusing connections.",
        "ssh-host-unreachable": "Saved mesh state indicates the SSH host is unreachable.",
        "ssh-connection-closed": "Saved mesh state indicates SSH closes the session early.",
        "offline-or-timeout": "Saved mesh state indicates the device is offline or timing out.",
        "missing-codex": "Saved mesh state indicates the Codex CLI is missing.",
        "missing-project": "Saved mesh state indicates the project checkout is missing.",
        "stale-checkout": "Saved mesh state indicates the checkout is stale.",
        "needs-review": "Saved mesh state needs operator review before team launch.",
        "needs-probe": "Saved mesh state needs a fresh probe before team launch.",
    }
    return summaries.get(category, f"Saved mesh state is {status} and needs review.")


def _readiness_action_priority(status: str, category: str) -> int:
    if status == "blocked":
        if category in {"tailscale-approval-required", "ssh-auth-denied", "ssh-host-key-unverified"}:
            return 10
        if category in {"ssh-host-unresolved", "ssh-connection-refused", "ssh-host-unreachable", "ssh-connection-closed"}:
            return 15
        if category == "missing-codex":
            return 20
        return 25
    if status == "offline":
        return 15
    if category in {"missing-project", "stale-checkout"}:
        return 30
    if category in {"needs-probe", "needs-review"}:
        return 40
    if status == "ready":
        return 90
    return 50


TAILSCALE_APPROVAL_RE = re.compile(r"https://login\.tailscale\.com/a/[A-Za-z0-9_-]+")


def tailscale_approval_url(text: str) -> str:
    match = TAILSCALE_APPROVAL_RE.search(text)
    return match.group(0) if match else ""


def _probe_actions(category: str, device: DeviceRecord, approval_url: str = "") -> tuple[str, ...]:
    if category == "ready-saved":
        return ("Run Check Fleet to refresh this saved status before assigning team work.",)
    if category == "local-ready":
        return ("Device is local and probe-ready. Rerun Check Fleet when the project changes.",)
    if category == "missing-project":
        return (
            "Sync the project to the device or update the profile device root.",
            f"Project root target: {device.project_root}",
            "Run Check Fleet after syncing before assigning work.",
        )
    if category == "missing-codex":
        return (
            "Install Codex CLI on this device and verify `codex --version` works.",
            f"Expected binary path: {device.codex_bin}",
            "Rerun Check Fleet once installed.",
        )
    if category == "tailscale-approval-required":
        if approval_url:
            return (
                f"Open Tailscale approval link: {approval_url}",
                "Wait for auth to complete, then rerun Check Fleet.",
            )
        return (
            "Open your Tailscale approval link in this device's browser.",
            "Wait for auth to complete, then rerun Check Fleet.",
        )
    if category == "ssh-auth-denied":
        return (
            "Fix SSH key auth for this machine on the launcher and target device.",
            "Rerun Check Fleet after trust/auth is updated.",
        )
    if category == "ssh-host-unresolved":
        return (
            "Verify the saved host or MagicDNS name for this device.",
            "Run Tailnet Discover to refresh device records before assigning work.",
            "Rerun Check Fleet after the host resolves.",
        )
    if category == "ssh-host-key-unverified":
        return (
            "Verify the target device identity before changing known_hosts.",
            "Update the stale SSH host key entry only after identity is confirmed.",
            "Rerun Check Fleet after host key trust is repaired.",
        )
    if category == "ssh-connection-refused":
        return (
            "Start or enable SSH/Tailscale SSH on the target device.",
            f"Verify port {device.port} is correct for {device.host}.",
            "Rerun Check Fleet after SSH accepts connections.",
        )
    if category == "ssh-host-unreachable":
        return (
            "Verify this device is online in Tailscale and reachable from the launcher.",
            "Check local network or Tailscale routing before assigning work.",
            "Rerun Check Fleet.",
        )
    if category == "ssh-connection-closed":
        return (
            "Verify SSH/Tailscale SSH is accepting sessions on the target device.",
            "Check remote login shell or startup failures before assigning work.",
            "Rerun Check Fleet.",
        )
    if category == "offline-or-timeout":
        return (
            "Verify this device is online in Tailscale.",
            "Confirm SSH service/daemon is running and the host is reachable.",
            "Rerun Check Fleet.",
        )
    if category == "stale-checkout":
        return (
            "Open the device and fix checkout state (commit/stash/rebase) first.",
            "A clean, current checkout is recommended before team launch.",
            "Run Check Fleet after checkout is refreshed.",
        )
    if category == "needs-probe":
        return ("Run Check Fleet to collect fresh readiness before assigning this device to team lanes.",)
    if category == "needs-review":
        return ("Collect a fresh probe and resolve the review reason before team assignment.",)
    if category == "ready":
        return ()
    return ("Inspect probe summary and rerun Check Fleet after remediation.",)


def _row_from_device_probe(device: DeviceRecord, probe: DeviceProbe | None) -> MeshReadinessRow:
    if probe is None:
        if device.status in {"ready", "ok", "prepared", "launched", "done", "passed"}:
            if _is_local_host(device.host):
                category = "local-ready"
                return MeshReadinessRow(
                    device_id=device.id,
                    device_name=device.name,
                    host=device.host,
                    status="ready",
                    blocker_category=category,
                    action_priority=_readiness_action_priority("ready", category),
                    summary="Saved device state is ready.",
                    next_actions=_probe_actions(category, device),
                    checked=0,
                    source="saved",
                )
            category = "needs-probe"
            status = "review"
            return MeshReadinessRow(
                device_id=device.id,
                device_name=device.name,
                host=device.host,
                status=status,
                blocker_category=category,
                action_priority=_readiness_action_priority(status, category),
                summary="Saved remote ready state needs a fresh probe before team launch.",
                next_actions=_probe_actions(category, device),
                checked=0,
                source="saved",
            )
        category = _saved_note_blocker_category(device)
        status = _saved_note_status(device, category)
        return MeshReadinessRow(
            device_id=device.id,
            device_name=device.name,
            host=device.host,
            status=status,
            blocker_category=category,
            action_priority=_readiness_action_priority(status, category),
            summary=_saved_note_summary(category, status),
            next_actions=_probe_actions(category, device),
            checked=0,
            source="saved",
        )

    status = probe.status
    category = "ready" if probe.status == "ready" else "needs-review"
    summary = probe.summary

    if status == "ready":
        if _is_stale_checkout(probe.git_state):
            status = "review"
            category = "stale-checkout"
            summary = "Codex ready but checkout requires refresh"
        elif _has_uncommitted_changes(probe.git_state):
            status = "review"
            category = "needs-review"
            summary = "Working tree has uncommitted changes"
        return MeshReadinessRow(
            device_id=device.id,
            device_name=device.name,
            host=device.host,
            status=status,
            blocker_category=category,
            action_priority=_readiness_action_priority(status, category),
            summary=summary,
            next_actions=_probe_actions(category if status != "ready" else "local-ready" if _is_local_host(device.host) else "ready", device),
            checked=probe.checked,
            source="probe",
        )

    if status == "review":
        if not probe.project_exists:
            category = "missing-project"
            summary = f"Project missing at {probe.project_root or device.project_root}"
        elif _is_stale_checkout(probe.git_state):
            category = "stale-checkout"
            summary = "Checkout is stale and should be refreshed"
        elif _has_uncommitted_changes(probe.git_state):
            summary = "Working tree has uncommitted changes"
            category = "needs-review"
        else:
            category = "needs-review"
        return MeshReadinessRow(
            device_id=device.id,
            device_name=device.name,
            host=device.host,
            status="review",
            blocker_category=category,
            action_priority=_readiness_action_priority("review", category),
            summary=summary,
            next_actions=_probe_actions(category, device),
            checked=probe.checked,
            source="probe",
        )

    if status in {"offline", "blocked"}:
        lower = probe.summary.lower()
        if "approval" in lower and "tailscale" in lower:
            category = "tailscale-approval-required"
        elif "permission denied" in lower or "auth denied" in lower:
            category = "ssh-auth-denied"
        elif ssh_category := _ssh_probe_hint_category(probe):
            category = ssh_category
        elif "timed out" in lower or "timeout" in lower or "connection timed out" in lower:
            category = "offline-or-timeout"
        elif status == "offline" and "offline" not in lower:
            category = "offline-or-timeout"
        elif _missing_codex_hint(probe, device):
            category = "missing-codex"
        else:
            category = "blocked"
        approval_url = tailscale_approval_url(probe.raw) if category == "tailscale-approval-required" else ""
        if status == "offline":
            row_status = "offline"
        else:
            row_status = "blocked"
        return MeshReadinessRow(
            device_id=device.id,
            device_name=device.name,
            host=device.host,
            status=row_status,
            blocker_category=category,
            action_priority=_readiness_action_priority(row_status, category),
            summary=summary,
            next_actions=_probe_actions(category, device, approval_url),
            checked=probe.checked,
            source="probe",
        )

    return MeshReadinessRow(
        device_id=device.id,
        device_name=device.name,
        host=device.host,
        status="unknown",
        blocker_category="needs-review",
        action_priority=_readiness_action_priority("unknown", "needs-review"),
        summary=probe.summary or "No usable readiness data",
        next_actions=_probe_actions("needs-review", device),
        checked=probe.checked,
        source="probe",
    )


def mesh_readiness_report(
    devices: tuple[DeviceRecord, ...],
    probes: Mapping[str, DeviceProbe] | None = None,
) -> MeshReadinessReport:
    probe_map: Mapping[str, DeviceProbe] = probes or {}
    rows = [
        _row_from_device_probe(device, probe_map.get(device.id))
        for device in devices
    ]
    return MeshReadinessReport(generated=now(), rows=tuple(rows))


def build_mesh_readiness_report(devices: tuple[DeviceRecord, ...]) -> MeshReadinessReport:
    rows: list[MeshReadinessRow] = []
    for device in devices:
        summary = device.note or "Not checked yet."
        if _is_local_host(device.host) and device.status == "ready":
            readiness = "local-ready"
            blocker = "Local execution"
            action = "Use local execution path for local workflows."
        else:
            readiness, blocker, action = readiness_from_probe_summary(device.status, summary)

        status = {
            "local-ready": "ready",
            "ready": "ready",
            "stale-checkout": "ready",
            "missing-project": "review",
            "missing-codex": "review",
            "needs-review": "review",
            "offline-or-timeout": "offline",
            "blocked-tailscale-approval": "blocked",
            "blocked-ssh-auth": "blocked",
            "blocked-dns": "blocked",
            "blocked-connection-refused": "blocked",
            "blocked-ssh": "blocked",
            "needs-check": "unknown",
        }.get(readiness, "unknown")
        category = {
            "local-ready": "local-ready",
            "ready": "ready",
            "stale-checkout": "stale-checkout",
            "missing-project": "missing-project",
            "missing-codex": "missing-codex",
            "needs-review": "needs-review",
            "offline-or-timeout": "offline-or-timeout",
            "blocked-tailscale-approval": "tailscale-approval",
            "blocked-ssh-auth": "ssh-auth",
            "blocked-dns": "dns",
            "blocked-connection-refused": "connection-refused",
            "blocked-ssh": "ssh-blocked",
            "needs-check": "needs-probe",
        }.get(readiness, "needs-review")
        rows.append(
            MeshReadinessRow(
                device_id=device.id,
                device_name=device.name,
                host=device.host,
                status=status,
                blocker_category=category,
                action_priority=_readiness_action_priority(status, category),
                summary=summary if blocker == summary else blocker,
                next_actions=(action,) if action else (),
                checked=device.updated,
                source="saved",
            )
        )
    return MeshReadinessReport(generated=now(), rows=tuple(rows))


def mesh_readiness_markdown(report: MeshReadinessReport) -> str:
    lines = ["# Mesh readiness", "", report.summary_text()]
    if not report.entries:
        lines.append("- no devices")
    else:
        for entry in report.entries:
            lines.append(f"- {entry.device_name} ({entry.host}): {entry.blocker}")
            lines.append(f"  next: {entry.next_action}")
            if entry.summary:
                lines.append(f"  detail: {entry.summary}")
    return "\n".join(lines) + "\n"


def readiness_from_probe_summary(status: str, summary: str) -> tuple[str, str, str]:
    text = summary.lower()
    if status == "ready":
        if "behind" in text or "stale" in text or "diverged" in text or "detached" in text:
            return (
                "stale-checkout",
                "Branch appears stale",
                "Push/pull to align with remote branches before dispatching this lane.",
            )
        return ("ready", "Ready for remote execution", "No blocker. Dispatch lane and run as needed.")

    if status == "review":
        if "project missing" in text or "project_exists=no" in text:
            return (
                "missing-project",
                "Project path missing",
                "Create/sync the project root path and retry Check Fleet.",
            )
        if "not a git repository" in text:
            return (
                "missing-project",
                "Project root is not a repository",
                "Point project_root at a valid project directory and retry Check Fleet.",
            )
        if "codex" in text and ("not found" in text or "missing" in text):
            return (
                "missing-codex",
                "Codex CLI missing",
                "Install Codex or fix PATH/codex_bin for this target.",
            )
        return (
            "needs-review",
            "Needs review",
            "Inspect device output and resolve the review condition.",
        )

    if status == "offline":
        return (
            "offline-or-timeout",
            "Offline",
            "Bring the device online, then rerun Check Fleet.",
        )

    if status == "blocked":
        if "requires an additional check" in text or "approval required" in text:
            return (
                "blocked-tailscale-approval",
                "Tailscale approval required",
                "Approve the Tailscale SSH request from this identity in the browser.",
            )
        if "auth denied" in text or "permission denied" in text or "publickey" in text:
            return (
                "blocked-ssh-auth",
                "SSH auth denied",
                "Add this machine's public key to the device authorized_keys.",
            )
        if "timed out" in text:
            return (
                "offline-or-timeout",
                "Probe timed out",
                "Check connectivity and firewall, then retry Check Fleet.",
            )
        if "cannot be resolved" in text or "could not resolve hostname" in text:
            return (
                "blocked-dns",
                "DNS/host resolution failed",
                "Validate hostname and Tailscale DNS mapping.",
            )
        if "refused" in text:
            return (
                "blocked-connection-refused",
                "SSH service unavailable",
                "Check sshd availability and target firewall policy.",
            )
        if "codex" in text and "not found" in text:
            return (
                "missing-codex",
                "Codex CLI missing",
                "Install Codex or fix PATH/codex_bin for this target.",
            )
        return (
            "blocked-ssh",
            "SSH blocked",
            "Inspect SSH command output on the target and rerun Check Fleet.",
        )

    return (
        "needs-check",
        "Needs a fleet check",
        "Run Check Fleet to get a current readiness verdict.",
    )


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


def tailscale_status_command() -> tuple[str, ...]:
    return ("tailscale", "status", "--json")


def _clean_dns_name(value: object) -> str:
    return str(value or "").strip().rstrip(".")


def _tailnet_ipv4(record: dict[str, Any]) -> str:
    ips = record.get("TailscaleIPs", [])
    if not isinstance(ips, list):
        return ""
    for value in ips:
        text = str(value or "").strip()
        if text.count(".") == 3:
            return text
    return str(ips[0]).strip() if ips else ""


def _tailnet_name(record: dict[str, Any], magic_dns_suffix: str) -> str:
    dns_name = _clean_dns_name(record.get("DNSName"))
    suffix = magic_dns_suffix.strip().strip(".").lower()
    if dns_name:
        lower = dns_name.lower()
        if suffix and lower.endswith("." + suffix):
            return dns_name[: -(len(suffix) + 1)] or dns_name.split(".", 1)[0]
        return dns_name.split(".", 1)[0]
    return str(record.get("HostName") or _tailnet_ipv4(record) or "tailnet-device").strip()


def _tailnet_host(record: dict[str, Any]) -> str:
    return _clean_dns_name(record.get("DNSName")) or _tailnet_ipv4(record) or str(record.get("HostName") or "").strip()


def _tailnet_note(record: dict[str, Any], online: bool) -> str:
    parts = [f"tailnet {'online' if online else 'offline'}"]
    os_name = str(record.get("OS") or "").strip()
    ip = _tailnet_ipv4(record)
    last_seen = str(record.get("LastSeen") or "").strip()
    if os_name:
        parts.append(os_name)
    if ip:
        parts.append(ip)
    if last_seen and not last_seen.startswith("0001-"):
        parts.append(f"last seen {last_seen}")
    return " | ".join(parts)


def devices_from_tailscale_status_json(
    text: str,
    *,
    user: str = "",
    port: int = 22,
    project_root: str = "~/Projects/codex-gui",
    codex_bin: str = "~/.local/bin/codex",
    include_self: bool = True,
    local_self_host: str = "",
    include_offline: bool = True,
    worker_os: tuple[str, ...] = (),
) -> tuple[DeviceRecord, ...]:
    data = json.loads(text)
    if not isinstance(data, dict):
        return ()
    current_tailnet = data.get("CurrentTailnet", {})
    magic_dns_suffix = ""
    if isinstance(current_tailnet, dict):
        magic_dns_suffix = str(current_tailnet.get("MagicDNSSuffix") or "")
    magic_dns_suffix = magic_dns_suffix or str(data.get("MagicDNSSuffix") or "")

    records: list[tuple[int, bool, dict[str, Any]]] = []
    self_record = data.get("Self")
    if include_self and isinstance(self_record, dict):
        records.append((0, True, self_record))
    peers = data.get("Peer", {})
    if isinstance(peers, dict):
        for peer in peers.values():
            if isinstance(peer, dict):
                records.append((1, False, peer))

    timestamp = now()
    devices: list[tuple[int, DeviceRecord]] = []
    for order, is_self, record in records:
        host = local_self_host.strip() if is_self and local_self_host.strip() else _tailnet_host(record)
        if not host:
            continue
        online = bool(record.get("Online"))
        if not include_offline and not online:
            continue
        os_name = str(record.get("OS") or "").strip().lower()
        if worker_os and os_name not in {item.lower() for item in worker_os}:
            continue
        name = _tailnet_name(record, magic_dns_suffix)
        status = "unknown" if online else "offline"
        devices.append((
            order,
            DeviceRecord(
                id=device_id(name, host),
                name=name,
                host=host,
                user="" if is_self and local_self_host.strip() else user.strip(),
                port=int(port or 22),
                project_root=project_root.strip() or "~/Projects/codex-gui",
                codex_bin=codex_bin.strip() or "~/.local/bin/codex",
                status=status,
                note=_tailnet_note(record, online),
                updated=timestamp,
            ),
        ))
    return tuple(device for _order, device in sorted(devices, key=lambda item: (item[0], item[1].name.lower())))


def _looks_like_tailnet_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return parts[0] == "100" and all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def _device_match_keys(device: DeviceRecord) -> set[str]:
    keys = {f"id:{device.id}"}
    if device.name:
        keys.add(f"name:{slugify(device.name)}")
    host = _clean_dns_name(device.host).lower()
    if host:
        keys.add(f"host:{host}")
        keys.add(f"short:{host.split('.', 1)[0]}")
        if _looks_like_tailnet_ipv4(host):
            keys.add(f"ip:{host}")
    for token in device.note.replace("|", " ").replace(",", " ").split():
        clean = token.strip().strip("[]()")
        if _looks_like_tailnet_ipv4(clean):
            keys.add(f"ip:{clean}")
    return keys


def _merged_tailnet_device(existing: DeviceRecord, discovered: DeviceRecord) -> DeviceRecord:
    if discovered.status == "offline":
        status = "offline"
        note = discovered.note
    else:
        status = "unknown" if existing.status == "offline" else existing.status
        note = discovered.note if not existing.note or existing.note.startswith("tailnet ") else existing.note
    return update_device(
        existing,
        name=existing.name or discovered.name,
        host=discovered.host or existing.host,
        user=existing.user or discovered.user,
        port=existing.port or discovered.port,
        project_root=existing.project_root or discovered.project_root,
        codex_bin=existing.codex_bin or discovered.codex_bin,
        status=status,
        note=note,
    )


def merge_discovered_devices(
    existing: tuple[DeviceRecord, ...],
    discovered: tuple[DeviceRecord, ...],
) -> tuple[DeviceRecord, ...]:
    merged = list(existing)
    key_to_index: dict[str, int] = {}
    for index, device in enumerate(merged):
        for key in _device_match_keys(device):
            key_to_index.setdefault(key, index)

    for device in discovered:
        match_index: int | None = None
        for key in _device_match_keys(device):
            if key in key_to_index:
                match_index = key_to_index[key]
                break
        if match_index is None:
            merged.append(device)
            match_index = len(merged) - 1
        else:
            merged[match_index] = _merged_tailnet_device(merged[match_index], device)
        for key in _device_match_keys(merged[match_index]):
            key_to_index[key] = match_index
    return tuple(sorted(merged, key=lambda item: item.updated, reverse=True))


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


def _codex_probe_candidates(device: DeviceRecord) -> tuple[str, ...]:
    explicit = (device.codex_bin or "").strip()
    candidates: list[str] = []
    if explicit and "/" in explicit:
        candidates.append(remote_path_expr(explicit))
    candidates.extend([
        '"$HOME"/.npm-global/bin/codex',
        '"$HOME"/.local/bin/codex',
        '"/usr/local/bin/codex"',
        '"/usr/bin/codex"',
    ])
    return tuple(candidates)


def _codex_resolver_script(device: DeviceRecord) -> str:
    candidates = " ".join(list(_codex_probe_candidates(device)) + ['"$(command -v codex 2>/dev/null)"'])
    return "\n".join([
        "resolve_codex() {",
        f"  for candidate in {candidates}; do",
        "    if [ -n \"$candidate\" ] && [ -x \"$candidate\" ]; then",
        "      printf '%s' \"$candidate\"",
        "      return 0",
        "    fi",
        "  done",
        "  return 1",
        "}",
    ])


def _codex_launcher_expression(device: DeviceRecord) -> str:
    return "\n".join([
        _codex_resolver_script(device),
        "CODEX_BIN=\"$(resolve_codex)\"",
        "if [ -z \"$CODEX_BIN\" ]; then",
        "  printf 'codex executable not found\\n'",
        "  exit 127",
        "fi",
    ])


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
    return (*device.ssh_prefix(), f"{_codex_launcher_expression(device)} && $CODEX_BIN --version && pwd")


def ssh_launch_command(device: DeviceRecord, prompt_path: str = "~/.config/codex-gui/memory.md") -> tuple[str, ...]:
    remote = (
        f"cd {remote_path_expr(device.project_root)} && "
        f"{_codex_launcher_expression(device)} && "
        f"$CODEX_BIN -C {remote_path_expr(device.project_root)} "
        f"\"Use the Codex Control portable memory at {prompt_path} and continue the active project.\""
    )
    return (*device.ssh_prefix(), remote)


def device_probe_script(device: DeviceRecord) -> str:
    project_expr = remote_path_expr(device.project_root)
    return "\n".join([
        "set -u",
        "export PATH=\"$HOME/.local/bin:$HOME/.npm-global/bin:$PATH\"",
        _codex_launcher_expression(device),
        "printf 'CODEX_PROBE=1\\n'",
        "printf 'HOSTNAME=%s\\n' \"$(hostname 2>/dev/null || printf unknown)\"",
        "printf 'UNAME=%s\\n' \"$(uname -srmo 2>/dev/null || uname -a 2>/dev/null || printf unknown)\"",
        "codex_out=$($CODEX_BIN --version 2>&1)",
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
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
        "-p",
        str(device.port),
        device.target(),
        "bash -lc " + shlex.quote(device_probe_script(device)),
    )


def local_probe_command(device: DeviceRecord) -> tuple[str, ...]:
    return ("bash", "-lc", device_probe_script(device))


def classify_probe_failure(text: str, returncode: int) -> tuple[str, str]:
    clean = " ".join(line.strip() for line in text.splitlines() if line.strip())
    lower = clean.lower()
    if (
        "codex executable not found" in lower
        or "codex: command not found" in lower
        or ("no such file" in lower and "codex" in lower)
    ):
        return "blocked", "Codex CLI missing"
    if "login.tailscale.com/a/" in lower or "tailscale ssh requires an additional check" in lower:
        return "blocked", "Tailscale SSH approval required"
    if "permission denied" in lower:
        return "blocked", "SSH auth denied"
    if (
        "could not resolve hostname" in lower
        or "name or service not known" in lower
        or "temporary failure in name resolution" in lower
        or "nodename nor servname provided" in lower
    ):
        return "blocked", "SSH host cannot be resolved"
    if "host key verification failed" in lower or "remote host identification has changed" in lower:
        return "blocked", "SSH host key unverified"
    if "no route to host" in lower or "network is unreachable" in lower:
        return "offline", "SSH host unreachable"
    if "connection timed out" in lower or "operation timed out" in lower or returncode == 124:
        return "offline", "SSH probe timed out"
    if "connection refused" in lower:
        return "blocked", "SSH connection refused"
    if "connection closed" in lower or "connection reset by peer" in lower:
        return "blocked", "SSH connection closed"
    return "blocked", clean or "probe failed"


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
        status, summary = classify_probe_failure(text or codex_version, returncode)
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


TEAM_CHAT_FILE = "team-chat.md"


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


def rsync_team_chat_command(team_dir: Path, device: DeviceRecord, run_id: str) -> tuple[str, ...]:
    target_dir = remote_team_dir(run_id) + "/out/"
    return (
        *rsync_base_args(device),
        str(team_dir / "out" / TEAM_CHAT_FILE),
        f"{device.target()}:{target_dir}",
    )


def rsync_team_chat_pull_command(team_dir: Path, device: DeviceRecord, run_id: str) -> tuple[str, ...]:
    target_path = f"{remote_team_dir(run_id)}/out/{TEAM_CHAT_FILE}"
    local_dir = team_dir / "collected" / slugify(device.name)
    return (
        *rsync_base_args(device),
        f"{device.target()}:{remote_path_expr(target_path)}",
        str(local_dir) + "/",
    )


def remote_file_sha256sum_command(device: DeviceRecord, remote_path: str) -> tuple[str, ...]:
    path_expr = remote_path_expr(remote_path)
    remote = (
        f"if [ -f {path_expr} ]; then "
        f"sha256sum {path_expr} | awk '{{print $1}}'; "
        f"else printf 'missing\\n'; fi"
    )
    return (*device.ssh_prefix(), remote)


def agent_shell_script(device: DeviceRecord, run_id: str, lane_slug: str) -> str:
    remote_dir = remote_team_dir(run_id)
    out_dir = f"{remote_dir}/out"
    prompt_path = f"{remote_dir}/lanes/{slugify(lane_slug)}.md"
    final_path = f"{out_dir}/{slugify(lane_slug)}.final.txt"
    status_path = f"{out_dir}/{slugify(lane_slug)}.status.txt"
    chat_path = remote_path_expr(f"{out_dir}/{TEAM_CHAT_FILE}")
    lane_slug_safe = shlex.quote(slugify(lane_slug))
    lane_device_safe = shlex.quote(device.name)
    run_id_safe = shlex.quote(run_id)
    return (
        f"ensure_team_chat() {{ "
        f"if [ ! -s {chat_path} ]; then "
        f"{{ printf '# Codex Team Chat\\n\\n'; "
        f"printf 'Team: %s\\n' {run_id_safe}; "
        "printf 'Started: %s\\n' \"$(date -Is)\"; "
        "printf '\\nInstructions: concise team updates, blockers, and next steps.\\n\\n'; "
        f"}} > {chat_path} || true; "
        f"chmod 600 {chat_path} 2>/dev/null || true; "
        "fi; "
        "return 0; "
        "} && "
        f"append_team_chat() {{ "
        "message=$1; "
        "if [ -n \"$message\" ]; then "
        "ensure_team_chat; "
        f"if ! printf '[%s] %s (%s): %s\\n' \"$(date '+%Y-%m-%d %H:%M:%S')\" {lane_slug_safe} {lane_device_safe} \"$message\" >> {chat_path}; then "
        "printf 'team chat write failed\\n' >&2; "
        "fi; "
        f"chmod 600 {chat_path} 2>/dev/null || true; "
        "fi; "
        "return 0; "
        "} && "
        f"mkdir -p {remote_path_expr(out_dir)} && "
        f"cd {remote_path_expr(device.project_root)} && "
        "append_team_chat \"started\" && "
        f"prompt=$(cat {remote_path_expr(prompt_path)}) && "
        f"printf 'Remote Codex lane: %s\\n' {shlex.quote(slugify(lane_slug))} && "
        "role_profile=$(printf '%s\\n' \"$prompt\" | sed -n 's/^Role preset: //p' | head -n 1) && "
        "role_focus=$(printf '%s\\n' \"$prompt\" | sed -n 's/^Role focus: //p' | head -n 1) && "
        "role_boundary=$(printf '%s\\n' \"$prompt\" | sed -n 's/^Role boundary: //p' | head -n 1) && "
        "if [ -n \"$role_profile\" ]; then printf 'Role preset: %s\\n' \"$role_profile\"; fi && "
        "if [ -n \"$role_focus\" ]; then printf 'Role focus: %s\\n' \"$role_focus\"; fi && "
        "if [ -n \"$role_boundary\" ]; then printf 'Role boundary: %s\\n' \"$role_boundary\"; fi && "
        f"if [ -n \"$role_profile\" ]; then "
        f"  {_codex_launcher_expression(device)} && "
        f"  $CODEX_BIN -p \"$role_profile\" exec -s workspace-write -C {remote_path_expr(device.project_root)} "
        f"--add-dir {remote_path_expr(out_dir)} --skip-git-repo-check --output-last-message {remote_path_expr(final_path)} \"$prompt\"; "
        "else "
        f"  {_codex_launcher_expression(device)} && "
        f"  $CODEX_BIN exec -s workspace-write -C {remote_path_expr(device.project_root)} "
        f"--add-dir {remote_path_expr(out_dir)} --skip-git-repo-check --output-last-message {remote_path_expr(final_path)} \"$prompt\"; "
        "fi; "
        "status=$?; "
        "append_team_chat \"complete status=$status finished=$(date -Is)\"; "
        f"printf 'lane=%s\\nstatus=%s\\nfinished=%s\\n' {shlex.quote(slugify(lane_slug))} \"$status\" \"$(date -Is)\" > {remote_path_expr(status_path)}; "
        "exit \"$status\""
    )


def remote_agent_command(device: DeviceRecord, run_id: str, lane_slug: str) -> tuple[str, ...]:
    return (*device.ssh_prefix(), agent_shell_script(device, run_id, lane_slug))


def local_agent_command(device: DeviceRecord, run_id: str, lane_slug: str) -> tuple[str, ...]:
    return ("bash", "-lc", agent_shell_script(device, run_id, lane_slug))


def team_prompt(
    *,
    lane_title: str,
    lane_slug: str,
    focus: str,
    base_prompt: str,
    run_id: str,
    device: DeviceRecord,
    teammates: tuple[str, ...],
    role_id: str = "",
    role_title: str = "",
    role_profile: str = "",
    role_focus: str = "",
    role_boundary: str = "",
) -> str:
    teammate_text = "\n".join(f"- {item}" for item in teammates) if teammates else "- none"
    remote_dir = remote_team_dir(run_id)
    return "\n".join([
        "Use $best-upfront-codex.",
        "",
        f"You are the {lane_title} lane in a distributed Codex Control team.",
        *(() if not role_id and not role_title else (f"Assigned role: {role_title or role_id}",)),
        *(() if not role_profile else (f"Role preset: {role_profile}",)),
        *(() if not role_focus else (f"Role focus: {role_focus}",)),
        *(() if not role_boundary else (f"Role boundary: {role_boundary}",)),
        f"Main focus: {focus}",
        f"Assigned device: {device.name} ({device.target()}:{device.port})",
        f"Project root: {device.project_root}",
        "",
        "Team protocol:",
        f"- Read `{remote_dir}/team-ledger.md` before acting.",
        f"- Read any existing files under `{remote_dir}/out/` as teammate handoffs.",
        f"- Use `{remote_dir}/out/team-chat.md` as the live role-to-role communication stream.",
        f"- Keep work scoped to `{device.project_root}` unless the ledger explicitly says otherwise.",
        f"- Keep the stream current: append concise progress updates to `{remote_dir}/out/team-chat.md` as blockers are resolved and milestones are met.",
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
