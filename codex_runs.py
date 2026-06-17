#!/usr/bin/env python3
"""Persistent metadata-only Codex run ledger."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from codex_receipts import CodexReceiptRecord, sha256_text, slugify


@dataclass(frozen=True)
class CodexRunRecord:
    id: str
    created: int
    updated: int
    project_name: str
    project_hash: str
    action: str
    profile: str
    surface: str
    status: str
    prompt_hash: str
    command_hash: str
    receipt_id: str = ""
    receipt_path: str = ""
    event_hash: str = ""
    receipt_hash: str = ""
    pid: int = 0
    exit_code: int | None = None
    note: str = ""


def now() -> int:
    return int(time.time())


def project_name(project: str) -> str:
    name = Path(project).expanduser().name
    return name or "project"


def run_id(action: str, command: str, timestamp: int | None = None) -> str:
    return f"run-{timestamp or time.time_ns()}-{slugify(action, 'action')}-{sha256_text(command)[:10]}"


def new_run_record(
    *,
    project: str,
    action: str,
    profile: str,
    surface: str,
    status: str,
    prompt: str,
    command: str,
    receipt: CodexReceiptRecord | None = None,
    pid: int = 0,
    exit_code: int | None = None,
    note: str = "",
) -> CodexRunRecord:
    created = now()
    return CodexRunRecord(
        id=run_id(action, command),
        created=created,
        updated=created,
        project_name=project_name(project),
        project_hash=sha256_text(str(Path(project).expanduser())),
        action=slugify(action, "action"),
        profile=slugify(profile or "none", "profile"),
        surface=slugify(surface, "surface"),
        status=status,
        prompt_hash=sha256_text(prompt),
        command_hash=sha256_text(command),
        receipt_id=receipt.id if receipt else "",
        receipt_path=receipt.receipt_path if receipt else "",
        event_hash=receipt.event_hash if receipt else "",
        receipt_hash=receipt.receipt_hash if receipt else "",
        pid=pid,
        exit_code=exit_code,
        note=note,
    )


def update_run_record(record: CodexRunRecord, **changes: object) -> CodexRunRecord:
    return replace(record, updated=now(), **changes)


def load_run_records(path: Path) -> list[CodexRunRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    records: list[CodexRunRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            records.append(CodexRunRecord(
                id=str(item.get("id") or ""),
                created=int(item.get("created") or now()),
                updated=int(item.get("updated") or item.get("created") or now()),
                project_name=str(item.get("project_name") or "project"),
                project_hash=str(item.get("project_hash") or ""),
                action=str(item.get("action") or "action"),
                profile=str(item.get("profile") or "profile"),
                surface=str(item.get("surface") or "surface"),
                status=str(item.get("status") or "unknown"),
                prompt_hash=str(item.get("prompt_hash") or ""),
                command_hash=str(item.get("command_hash") or ""),
                receipt_id=str(item.get("receipt_id") or ""),
                receipt_path=str(item.get("receipt_path") or ""),
                event_hash=str(item.get("event_hash") or ""),
                receipt_hash=str(item.get("receipt_hash") or ""),
                pid=int(item.get("pid") or 0),
                exit_code=int(item["exit_code"]) if item.get("exit_code") is not None else None,
                note=str(item.get("note") or ""),
            ))
        except (TypeError, ValueError):
            continue
    return sorted(records, key=lambda record: record.updated, reverse=True)


def save_run_records(path: Path, records: list[CodexRunRecord], limit: int = 120) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record.updated, reverse=True)[:limit]
    path.write_text(json.dumps([asdict(record) for record in ordered], indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def upsert_run_record(records: list[CodexRunRecord], record: CodexRunRecord) -> list[CodexRunRecord]:
    replaced = False
    next_records: list[CodexRunRecord] = []
    for existing in records:
        if existing.id == record.id:
            next_records.append(record)
            replaced = True
        else:
            next_records.append(existing)
    if not replaced:
        next_records.insert(0, record)
    return sorted(next_records, key=lambda item: item.updated, reverse=True)


def remove_run_record(records: list[CodexRunRecord], record_id: str) -> list[CodexRunRecord]:
    return [record for record in records if record.id != record_id]


def run_detail(record: CodexRunRecord | None) -> str:
    if record is None:
        return "No run selected."
    return "\n".join([
        f"# {record.id}",
        "",
        f"Status: {record.status}",
        f"Project: {record.project_name}",
        f"Action: {record.action}",
        f"Profile: {record.profile}",
        f"Surface: {record.surface}",
        f"PID: {record.pid or 'not tracked'}",
        f"Exit code: {record.exit_code if record.exit_code is not None else 'pending'}",
        f"Prompt SHA-256: {record.prompt_hash}",
        f"Command SHA-256: {record.command_hash}",
        f"Receipt: {record.receipt_id or 'none'}",
        f"Receipt hash: {record.receipt_hash or 'none'}",
        f"Event hash: {record.event_hash or 'none'}",
        f"Receipt path: {record.receipt_path or 'none'}",
        f"Note: {record.note or 'none'}",
        "",
        "Metadata-only: raw prompts, command bodies, terminal output, logs, and model output are not stored in the run ledger.",
    ])
