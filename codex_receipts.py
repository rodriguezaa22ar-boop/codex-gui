#!/usr/bin/env python3
"""Metadata-only receipt helpers for Codex Control."""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import os
import shutil
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


EVENT_SCHEMA = "generic.external_event.v1"
EVENT_TYPE = "codex_gui.command.prepared"


@dataclass(frozen=True)
class CodexReceiptRecord:
    id: str
    observed_at: str
    event_type: str
    project_name: str
    project_hash: str
    action: str
    profile: str
    prompt_hash: str
    command_hash: str
    event_path: str
    receipt_path: str = ""
    event_hash: str = ""
    receipt_hash: str = ""
    prev_hash: str = ""
    status: str = "event-only"


@dataclass(frozen=True)
class ReceiptCommandResult:
    command: tuple[str, ...]
    status: int
    output: str


@dataclass(frozen=True)
class ReceiptStampResult:
    record: CodexReceiptRecord
    import_result: ReceiptCommandResult | None = None
    verify_result: ReceiptCommandResult | None = None
    error: str = ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _coalesce_text(value: object, fallback: str = "") -> str:
    value_text = str(value or "").strip()
    return value_text or fallback


def utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, fallback: str = "receipt") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:56] or fallback


def default_receipts_dir() -> Path:
    return Path.home() / ".config" / "codex-gui" / "receipts"


def candidate_atlas_roots() -> tuple[Path, ...]:
    candidates: list[Path] = []
    env_root = os.environ.get("ATLAS_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend([
        Path.home() / "Projects" / "atlas-trust-infrastructure",
        Path.home() / "workspace" / "atlas-trust-infrastructure",
    ])
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def atlas_binary(atlas_root: str | Path | None = None) -> Path | None:
    roots = [Path(atlas_root).expanduser()] if atlas_root else list(candidate_atlas_roots())
    for root in roots:
        binary = root / "tools" / "atlas" / "bin" / "atlas"
        if binary.exists() and os.access(binary, os.X_OK):
            return binary
    return None


def event_paths(base_dir: Path, event_id: str) -> tuple[Path, Path]:
    return base_dir / "events" / f"{event_id}.json", base_dir / "receipts" / f"{event_id}.receipt.json"


def _safe_project_name(project: str) -> str:
    name = Path(project).expanduser().name
    return name or "project"


def build_codex_event(
    *,
    event_id: str,
    observed_at: str,
    event_path: Path,
    project: str,
    action: str,
    profile: str,
    prompt: str,
    command: str,
    actor: str | None = None,
) -> dict[str, object]:
    project_name = _safe_project_name(project)
    project_hash = sha256_text(str(Path(project).expanduser()))
    prompt_hash = sha256_text(prompt)
    command_hash = sha256_text(command)
    actor_value = actor or f"local:{getpass.getuser()}"
    return {
        "schema_version": EVENT_SCHEMA,
        "adapter_id": EVENT_SCHEMA,
        "event_id": event_id,
        "observed_at": observed_at,
        "event_type": EVENT_TYPE,
        "actor": actor_value,
        "source_ref": str(event_path),
        "subject": {
            "type": "codex-gui-command",
            "ref": f"codex-gui://project/{slugify(project_name, 'project')}/{project_hash[:12]}",
        },
        "evidence_refs": [
            "codex-gui://receipt_profile/command_prepared.v1",
            f"codex-gui://project_name/{slugify(project_name, 'project')}",
            f"codex-gui://project_hash/sha256:{project_hash}",
            f"codex-gui://action/{slugify(action, 'action')}",
            f"codex-gui://profile/{slugify(profile or 'none', 'profile')}",
            f"sha256:prompt:{prompt_hash}",
            f"sha256:command:{command_hash}",
            "codex-gui://metadata_only/true",
        ],
        "artifact_refs": [],
        "approval_refs": [],
        "metadata_only": True,
        "raw_artifacts_embedded": False,
        "known_limitations": [
            "Codex Control records local command metadata only; raw prompts, command bodies, terminal output, logs, and model output are not embedded.",
            "Atlas receipt verification checks metadata shape, deterministic hashing, and optional prev-hash linkage; it does not prove source-system truth, task correctness, authorization, compliance, or production readiness.",
            "Project paths are represented by project name and SHA-256 references for local review without embedding private file contents.",
        ],
    }


def write_event(
    base_dir: Path,
    *,
    project: str,
    action: str,
    profile: str,
    prompt: str,
    command: str,
    actor: str | None = None,
) -> CodexReceiptRecord:
    observed_at = utc_timestamp()
    stem = f"{observed_at.replace(':', '').replace('-', '')}-{slugify(action, 'action')}-{sha256_text(command)[:10]}"
    event_id = f"codex-gui-{stem}"
    event_path, receipt_path = event_paths(base_dir, event_id)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    event = build_codex_event(
        event_id=event_id,
        observed_at=observed_at,
        event_path=event_path,
        project=project,
        action=action,
        profile=profile,
        prompt=prompt,
        command=command,
        actor=actor,
    )
    event_path.write_text(json.dumps(event, indent=2), encoding="utf-8")
    os.chmod(event_path, 0o600)
    return record_from_event(event, event_path, receipt_path)


def _run(args: list[str], timeout: int = 20) -> ReceiptCommandResult:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        return ReceiptCommandResult(tuple(args), result.returncode, output.strip())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ReceiptCommandResult(tuple(args), 1, str(exc))


def load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def record_from_event(event: dict[str, object], event_path: Path, receipt_path: Path | None = None) -> CodexReceiptRecord:
    evidence_refs = event.get("evidence_refs")
    refs = [str(item) for item in evidence_refs] if isinstance(evidence_refs, list) else []

    def ref_value(prefix: str) -> str:
        for ref in refs:
            if ref.startswith(prefix):
                return ref.removeprefix(prefix)
        return ""

    project_hash = ref_value("codex-gui://project_hash/sha256:")
    prompt_hash = ref_value("sha256:prompt:")
    command_hash = ref_value("sha256:command:")
    profile = ref_value("codex-gui://profile/")
    action = ref_value("codex-gui://action/")
    project_name = ref_value("codex-gui://project_name/")
    return CodexReceiptRecord(
        id=str(event.get("event_id") or event_path.stem),
        observed_at=str(event.get("observed_at") or ""),
        event_type=str(event.get("event_type") or ""),
        project_name=project_name or "project",
        project_hash=project_hash,
        action=action or "action",
        profile=profile or "profile",
        prompt_hash=prompt_hash,
        command_hash=command_hash,
        event_path=str(event_path),
        receipt_path=str(receipt_path or ""),
    )


def record_from_paths(event_path: Path, receipt_path: Path | None = None) -> CodexReceiptRecord:
    event = load_json(event_path)
    receipt = load_json(receipt_path) if receipt_path and receipt_path.exists() else {}
    base = record_from_event(event, event_path, receipt_path)
    if not receipt:
        return base
    return CodexReceiptRecord(
        **{
            **base.__dict__,
            "event_hash": str(receipt.get("event_hash") or ""),
            "receipt_hash": str(receipt.get("receipt_hash") or ""),
            "prev_hash": str(receipt.get("prev_hash") or "") if receipt.get("prev_hash") is not None else "",
            "status": "verified" if receipt.get("receipt_hash") else "receipt",
        }
    )


def load_receipt_records(base_dir: Path) -> list[CodexReceiptRecord]:
    events_dir = base_dir / "events"
    receipts_dir = base_dir / "receipts"
    records: list[CodexReceiptRecord] = []
    if not events_dir.exists():
        return records
    for event_path in sorted(events_dir.glob("*.json")):
        receipt_path = receipts_dir / f"{event_path.stem}.receipt.json"
        records.append(record_from_paths(event_path, receipt_path if receipt_path.exists() else None))
    return sorted(records, key=lambda record: (record.observed_at, record.id), reverse=True)


def latest_event_hash(base_dir: Path) -> str:
    receipts_dir = base_dir / "receipts"
    if receipts_dir.exists():
        receipt_paths = sorted(receipts_dir.glob("*.receipt.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for receipt_path in receipt_paths:
            receipt = load_json(receipt_path)
            event_hash = str(receipt.get("event_hash") or "")
            if event_hash:
                return event_hash
    for record in load_receipt_records(base_dir):
        if record.event_hash:
            return record.event_hash
    return ""


def linked_receipt_chain(
    records: list[CodexReceiptRecord],
    head: CodexReceiptRecord | None = None,
) -> list[CodexReceiptRecord]:
    candidates = [record for record in records if record.event_hash and record.receipt_path]
    if not candidates:
        return []
    current = head if head is not None and head.event_hash else candidates[0]
    by_hash = {record.event_hash: record for record in candidates}
    chain = [current]
    seen = {current.event_hash}
    while current.prev_hash:
        previous = by_hash.get(current.prev_hash)
        if previous is None or previous.event_hash in seen:
            break
        chain.insert(0, previous)
        seen.add(previous.event_hash)
        current = previous
    return chain


@dataclass(frozen=True)
class ReviewerBundle:
    bundle_dir: str
    manifest_path: str
    receipt_count: int
    run_count: int


def _run_to_dict(record: object) -> dict[str, object]:
    if isinstance(record, dict):
        return {
            "id": str(record.get("id") or ""),
            "created": int(record.get("created") or 0),
            "updated": int(record.get("updated") or 0),
            "project_name": str(record.get("project_name") or "project"),
            "project_hash": str(record.get("project_hash") or ""),
            "action": str(record.get("action") or "action"),
            "profile": str(record.get("profile") or "profile"),
            "surface": str(record.get("surface") or "surface"),
            "status": str(record.get("status") or "unknown"),
            "prompt_hash": str(record.get("prompt_hash") or ""),
            "command_hash": str(record.get("command_hash") or ""),
            "receipt_id": str(record.get("receipt_id") or ""),
            "receipt_path": str(record.get("receipt_path") or ""),
            "event_hash": str(record.get("event_hash") or ""),
            "receipt_hash": str(record.get("receipt_hash") or ""),
            "pid": int(record.get("pid") or 0),
            "exit_code": record.get("exit_code"),
            "note": str(record.get("note") or ""),
        }
    return {
        "id": _coalesce_text(getattr(record, "id", "")),
        "created": int(getattr(record, "created", 0) or 0),
        "updated": int(getattr(record, "updated", 0) or 0),
        "project_name": _coalesce_text(getattr(record, "project_name", ""), "project"),
        "project_hash": _coalesce_text(getattr(record, "project_hash", "")),
        "action": _coalesce_text(getattr(record, "action", ""), "action"),
        "profile": _coalesce_text(getattr(record, "profile", ""), "profile"),
        "surface": _coalesce_text(getattr(record, "surface", ""), "surface"),
        "status": _coalesce_text(getattr(record, "status", ""), "unknown"),
        "prompt_hash": _coalesce_text(getattr(record, "prompt_hash", "")),
        "command_hash": _coalesce_text(getattr(record, "command_hash", "")),
        "receipt_id": _coalesce_text(getattr(record, "receipt_id", "")),
        "receipt_path": _coalesce_text(getattr(record, "receipt_path", "")),
        "event_hash": _coalesce_text(getattr(record, "event_hash", "")),
        "receipt_hash": _coalesce_text(getattr(record, "receipt_hash", "")),
        "pid": int(getattr(record, "pid", 0) or 0),
        "exit_code": getattr(record, "exit_code", None),
        "note": _coalesce_text(getattr(record, "note", "")),
    }


def _receipt_manifest_rows(records: Iterable[CodexReceiptRecord]) -> list[dict[str, object]]:
    return [
        {
            "id": record.id,
            "event_file": Path(record.event_path).name if record.event_path else "",
            "receipt_file": Path(record.receipt_path).name if record.receipt_path else "",
            "status": record.status,
            "action": record.action,
            "project_hash": record.project_hash,
            "event_hash": record.event_hash,
            "receipt_hash": record.receipt_hash,
        }
        for record in records
    ]


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def import_receipt(
    atlas_root: str | Path | None,
    event_path: Path,
    receipt_path: Path,
    *,
    prev_hash: str = "",
) -> ReceiptCommandResult:
    binary = atlas_binary(atlas_root)
    if binary is None:
        return ReceiptCommandResult((), 1, "Atlas binary not found")
    args = [str(binary), "receipt", "import-generic-event", str(event_path)]
    if prev_hash:
        args.extend(["--prev-hash", prev_hash])
    args.extend(["--out", str(receipt_path)])
    return _run(args)


def verify_receipt(atlas_root: str | Path | None, receipt_path: Path) -> ReceiptCommandResult:
    binary = atlas_binary(atlas_root)
    if binary is None:
        return ReceiptCommandResult((), 1, "Atlas binary not found")
    return _run([str(binary), "receipt", "verify", str(receipt_path)])


def replay_receipts(atlas_root: str | Path | None, receipt_paths: list[Path]) -> ReceiptCommandResult:
    binary = atlas_binary(atlas_root)
    if binary is None:
        return ReceiptCommandResult((), 1, "Atlas binary not found")
    if len(receipt_paths) < 2:
        return ReceiptCommandResult((), 1, "Need at least two receipts to replay")
    return _run([str(binary), "receipt", "replay", *[str(path) for path in receipt_paths]], timeout=30)


def create_reviewer_bundle(
    output_root: Path,
    *,
    bundle_name: str,
    project: str,
    receipt_records: Iterable[CodexReceiptRecord],
    run_records: Iterable[object] = (),
    selected_receipt: CodexReceiptRecord | None = None,
    launch_package_text: str = "",
    context_summary: str = "",
    team_artifacts: Iterable[tuple[Path, str]] = (),
    max_receipts: int = 20,
) -> ReviewerBundle:
    """Build a metadata-only reviewer bundle from local records.

    The bundle contains copied event/receipt files, command-run JSON, and a manifest.
    """
    bundle_dir = output_root / bundle_name
    evidence_dir = bundle_dir / "evidence"
    receipts_dir = evidence_dir / "receipts"
    receipt_events_dir = receipts_dir / "events"
    receipt_files_dir = receipts_dir / "files"
    run_file = evidence_dir / "command-runs.json"
    manifest_path = bundle_dir / "manifest.json"
    summary_path = bundle_dir / "summary.md"

    included_receipts = list(receipt_records)
    if selected_receipt is not None:
        included_receipts = linked_receipt_chain(included_receipts, selected_receipt)
        if not included_receipts:
            included_receipts = [selected_receipt]

    included_receipts = included_receipts[:max_receipts]
    copied_events = 0
    copied_files = 0

    for record in included_receipts:
        event_source = Path(record.event_path)
        event_dest = receipt_events_dir / event_source.name
        if _copy_if_exists(event_source, event_dest):
            copied_events += 1
        receipt_source = Path(record.receipt_path)
        receipt_dest = receipt_files_dir / receipt_source.name
        if _copy_if_exists(receipt_source, receipt_dest):
            copied_files += 1

    run_rows = [_run_to_dict(row) for row in run_records]
    run_file.parent.mkdir(parents=True, exist_ok=True)
    run_file.write_text(json.dumps(run_rows, indent=2), encoding="utf-8")

    copied_team_artifacts: list[tuple[str, str]] = []
    for source, destination in team_artifacts:
        if source.exists():
            copied = _copy_if_exists(source, bundle_dir / destination)
            if copied:
                copied_team_artifacts.append((str(source), str(destination)))

    artifact_count = len(copied_team_artifacts)

    summary_lines = [
        "# Reviewer Bundle",
        "",
        f"Project: {project}",
        f"Bundle: {bundle_name}",
        f"Created: {dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')}",
        f"Included receipts: {len(included_receipts)}",
        f"Included runs: {len(run_rows)}",
        "",
        "## Evidence",
        f"Events copied: {copied_events}",
        f"Receipt files copied: {copied_files}",
        f"Selected receipt: {selected_receipt.id if selected_receipt is not None else 'none'}",
        "",
        "## Bundle Layout",
        "- manifest.json",
        "- summary.md",
        "- evidence/command-runs.json",
        "- evidence/receipts/events/",
        "- evidence/receipts/files/",
    ]
    if copied_team_artifacts:
        summary_lines.append("")
        summary_lines.extend(["## Team Artifacts", f"Team files copied: {len(copied_team_artifacts)}"])
        for _, destination in copied_team_artifacts:
            summary_lines.append(f"- {destination}")

    if context_summary:
        summary_lines.extend(["", "## Context Summary", context_summary.strip()])
    if launch_package_text:
        summary_lines.extend(["", "## Launch Package", launch_package_text.strip()])

    summary = "\n".join(summary_lines).strip() + "\n"
    manifest = {
        "created": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project": project,
        "bundle_name": bundle_name,
        "selected_receipt_id": selected_receipt.id if selected_receipt is not None else "",
        "entries": {
            "manifest": "manifest.json",
            "summary": "summary.md",
            "command_runs": "evidence/command-runs.json",
            "receipt_events": "evidence/receipts/events",
            "receipt_files": "evidence/receipts/files",
        },
        "receipt_count": len(included_receipts),
        "run_count": len(run_rows),
        "team_artifact_count": artifact_count,
        "team_artifacts": copied_team_artifacts,
        "receipt_index": _receipt_manifest_rows(included_receipts),
        "metadata_boundary": "No raw prompt, command body, terminal output, or model output is embedded.",
    }

    bundle_dir.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")

    return ReviewerBundle(
        bundle_dir=str(bundle_dir),
        manifest_path=str(manifest_path),
        receipt_count=len(included_receipts),
        run_count=len(run_rows),
    )


def stamp_codex_receipt(
    base_dir: Path,
    *,
    atlas_root: str | Path | None,
    project: str,
    action: str,
    profile: str,
    prompt: str,
    command: str,
    actor: str | None = None,
    link_previous: bool = True,
) -> ReceiptStampResult:
    previous_hash = latest_event_hash(base_dir) if link_previous else ""
    record = write_event(
        base_dir,
        project=project,
        action=action,
        profile=profile,
        prompt=prompt,
        command=command,
        actor=actor,
    )
    event_path = Path(record.event_path)
    receipt_path = Path(record.receipt_path)
    import_result = import_receipt(atlas_root, event_path, receipt_path, prev_hash=previous_hash)
    if import_result.status != 0:
        return ReceiptStampResult(record=record, import_result=import_result, error=import_result.output)
    verify_result = verify_receipt(atlas_root, receipt_path)
    stamped = record_from_paths(event_path, receipt_path)
    status = "verified" if verify_result.status == 0 else "unverified"
    stamped = CodexReceiptRecord(**{**stamped.__dict__, "status": status})
    return ReceiptStampResult(
        record=stamped,
        import_result=import_result,
        verify_result=verify_result,
        error="" if verify_result.status == 0 else verify_result.output,
    )


def receipt_detail(record: CodexReceiptRecord | None) -> str:
    if record is None:
        return "No receipt selected."
    lines = [
        f"# {record.id}",
        "",
        f"Status: {record.status}",
        f"Observed: {record.observed_at}",
        f"Event type: {record.event_type}",
        f"Project: {record.project_name}",
        f"Action: {record.action}",
        f"Profile: {record.profile}",
        f"Prompt SHA-256: {record.prompt_hash}",
        f"Command SHA-256: {record.command_hash}",
        f"Event hash: {record.event_hash or 'not imported'}",
        f"Receipt hash: {record.receipt_hash or 'not imported'}",
        f"Previous hash: {record.prev_hash or 'none'}",
        f"Event file: {record.event_path}",
        f"Receipt file: {record.receipt_path or 'not written'}",
        "",
        "Metadata-only: raw prompt, command body, terminal output, logs, and model output are not embedded.",
    ]
    return "\n".join(lines)
