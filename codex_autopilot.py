#!/usr/bin/env python3
"""Autopilot script generation for Codex Control."""

from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from codex_mission import MissionBlueprint
from codex_receipts import sha256_text, slugify


@dataclass(frozen=True)
class AutopilotStep:
    title: str
    command: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class AutopilotPlan:
    id: str
    title: str
    project: str
    artifacts_dir: str
    main_command: tuple[str, ...]
    steps: tuple[AutopilotStep, ...]

    def script(self) -> str:
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'export PATH="$HOME/.local/bin:$PATH"',
            f"cd -- {shlex.quote(self.project)}",
            f"mkdir -p -- {shlex.quote(self.artifacts_dir)}",
            f"printf '%s\\n' {shlex.quote('[Codex Control] Autopilot: ' + self.title)}",
            f"printf '%s\\n' {shlex.quote('[Codex Control] artifacts: ' + self.artifacts_dir)}",
            "",
        ]
        for step in self.steps:
            lines.extend([
                f"printf '\\n%s\\n' {shlex.quote('[Codex Control] step: ' + step.title)}",
                shlex.join(step.command),
                "",
            ])
        lines.append("printf '%s\\n' '[Codex Control] autopilot finished'")
        return "\n".join(lines)

    def detail_text(self) -> str:
        lines = [
            "# Autopilot Plan",
            "",
            f"ID: {self.id}",
            f"Title: {self.title}",
            f"Project: {self.project}",
            f"Artifacts: {self.artifacts_dir}",
            f"Steps: {len(self.steps)}",
            "",
            "Main Codex command:",
            shlex.join(self.main_command),
            "",
            "Steps:",
        ]
        for index, step in enumerate(self.steps, start=1):
            lines.extend([
                f"{index}. {step.title}",
                shlex.join(step.command),
                "",
            ])
        return "\n".join(lines).strip()


@dataclass(frozen=True)
class AutopilotRecord:
    id: str
    title: str
    project_name: str
    project_hash: str
    status: str
    created: int
    updated: int
    artifacts_dir: str
    script_path: str
    blueprint_path: str
    final_path: str
    jsonl_path: str
    log_path: str
    manifest_path: str
    main_command_hash: str
    prompt_hash: str
    script_hash: str
    blueprint_hash: str
    steps: int
    pid: int = 0
    exit_code: int | None = None
    started: int = 0
    finished: int = 0
    note: str = ""


def now() -> int:
    return int(time.time())


def project_name(project: str) -> str:
    name = Path(project).expanduser().name
    return name or "project"


def autopilot_id(prompt: str, timestamp: int | None = None) -> str:
    stamp = timestamp or int(time.time())
    return f"autopilot-{stamp}-{sha256_text(prompt)[:10]}"


def autopilot_paths(plan: AutopilotPlan) -> dict[str, Path]:
    root = Path(plan.artifacts_dir).expanduser()
    return {
        "artifacts_dir": root,
        "script_path": root / "autopilot.sh",
        "blueprint_path": root / "blueprint.md",
        "final_path": root / "codex-final.txt",
        "jsonl_path": root / "codex-events.jsonl",
        "log_path": root / "autopilot.log",
        "manifest_path": root / "manifest.txt",
    }


def _write_private(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)


def record_from_plan(
    plan: AutopilotPlan,
    *,
    prompt: str,
    blueprint_text: str,
    script_text: str | None = None,
    status: str = "prepared",
    note: str = "",
    existing: AutopilotRecord | None = None,
) -> AutopilotRecord:
    paths = autopilot_paths(plan)
    created = existing.created if existing is not None else now()
    script = script_text if script_text is not None else plan.script()
    return AutopilotRecord(
        id=plan.id,
        title=plan.title,
        project_name=project_name(plan.project),
        project_hash=sha256_text(str(Path(plan.project).expanduser())),
        status=status,
        created=created,
        updated=now(),
        artifacts_dir=str(paths["artifacts_dir"]),
        script_path=str(paths["script_path"]),
        blueprint_path=str(paths["blueprint_path"]),
        final_path=str(paths["final_path"]),
        jsonl_path=str(paths["jsonl_path"]),
        log_path=str(paths["log_path"]),
        manifest_path=str(paths["manifest_path"]),
        main_command_hash=sha256_text(shlex.join(plan.main_command)),
        prompt_hash=sha256_text(prompt),
        script_hash=sha256_text(script),
        blueprint_hash=sha256_text(blueprint_text),
        steps=len(plan.steps),
        note=note,
    )


def update_autopilot_record(record: AutopilotRecord, **changes: object) -> AutopilotRecord:
    return replace(record, updated=now(), **changes)


def write_autopilot_artifacts(
    plan: AutopilotPlan,
    *,
    blueprint_text: str,
    prompt: str,
    status: str = "prepared",
    note: str = "",
    existing: AutopilotRecord | None = None,
) -> AutopilotRecord:
    paths = autopilot_paths(plan)
    paths["artifacts_dir"].mkdir(parents=True, exist_ok=True)
    os.chmod(paths["artifacts_dir"], 0o700)

    script_text = plan.script() + "\n"
    detail_text = "\n\n".join(part.strip() for part in [blueprint_text, plan.detail_text()] if part.strip()) + "\n"
    record = record_from_plan(
        plan,
        prompt=prompt,
        blueprint_text=detail_text,
        script_text=script_text,
        status=status,
        note=note,
        existing=existing,
    )
    manifest = "\n".join([
        "# Codex Control Autopilot Manifest",
        f"id={record.id}",
        f"title={record.title}",
        f"status={record.status}",
        f"created={record.created}",
        f"updated={record.updated}",
        f"project_name={record.project_name}",
        f"project_sha256={record.project_hash}",
        f"prompt_sha256={record.prompt_hash}",
        f"main_command_sha256={record.main_command_hash}",
        f"script_sha256={record.script_hash}",
        f"blueprint_sha256={record.blueprint_hash}",
        f"steps={record.steps}",
        f"script={record.script_path}",
        f"blueprint={record.blueprint_path}",
        f"final={record.final_path}",
        f"events={record.jsonl_path}",
        f"log={record.log_path}",
        f"note={record.note}",
        "metadata_record_raw_prompt=false",
        "metadata_record_raw_command=false",
        "",
    ])
    _write_private(paths["script_path"], script_text, 0o700)
    _write_private(paths["blueprint_path"], detail_text, 0o600)
    _write_private(paths["manifest_path"], manifest, 0o600)
    return record


def _record_from_dict(item: dict[str, object]) -> AutopilotRecord:
    return AutopilotRecord(
        id=str(item.get("id") or ""),
        title=str(item.get("title") or "Autopilot"),
        project_name=str(item.get("project_name") or "project"),
        project_hash=str(item.get("project_hash") or ""),
        status=str(item.get("status") or "unknown"),
        created=int(item.get("created") or now()),
        updated=int(item.get("updated") or item.get("created") or now()),
        artifacts_dir=str(item.get("artifacts_dir") or ""),
        script_path=str(item.get("script_path") or ""),
        blueprint_path=str(item.get("blueprint_path") or ""),
        final_path=str(item.get("final_path") or ""),
        jsonl_path=str(item.get("jsonl_path") or ""),
        log_path=str(item.get("log_path") or str(Path(str(item.get("artifacts_dir") or "")) / "autopilot.log")),
        manifest_path=str(item.get("manifest_path") or ""),
        main_command_hash=str(item.get("main_command_hash") or ""),
        prompt_hash=str(item.get("prompt_hash") or ""),
        script_hash=str(item.get("script_hash") or ""),
        blueprint_hash=str(item.get("blueprint_hash") or ""),
        steps=int(item.get("steps") or 0),
        pid=int(item.get("pid") or 0),
        exit_code=int(item["exit_code"]) if item.get("exit_code") is not None else None,
        started=int(item.get("started") or 0),
        finished=int(item.get("finished") or 0),
        note=str(item.get("note") or ""),
    )


def load_autopilot_records(path: Path) -> list[AutopilotRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    records: list[AutopilotRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            record = _record_from_dict(item)
        except (TypeError, ValueError):
            continue
        if record.id:
            records.append(record)
    return sorted(records, key=lambda record: record.updated, reverse=True)


def save_autopilot_records(path: Path, records: list[AutopilotRecord], limit: int = 60) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record.updated, reverse=True)[:limit]
    path.write_text(json.dumps([asdict(record) for record in ordered], indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def upsert_autopilot_record(records: list[AutopilotRecord], record: AutopilotRecord) -> list[AutopilotRecord]:
    replaced = False
    next_records: list[AutopilotRecord] = []
    for existing in records:
        if existing.id == record.id:
            next_records.append(record)
            replaced = True
        else:
            next_records.append(existing)
    if not replaced:
        next_records.insert(0, record)
    return sorted(next_records, key=lambda item: item.updated, reverse=True)


def remove_autopilot_record(records: list[AutopilotRecord], record_id: str) -> list[AutopilotRecord]:
    return [record for record in records if record.id != record_id]


def autopilot_detail(record: AutopilotRecord | None) -> str:
    if record is None:
        return "No Autopilot run selected."
    return "\n".join([
        f"# {record.title}",
        "",
        f"Status: {record.status}",
        f"Run id: {record.id}",
        f"Project: {record.project_name}",
        f"Created: {record.created}",
        f"Updated: {record.updated}",
        f"Started: {record.started or 'not started'}",
        f"Finished: {record.finished or 'pending'}",
        f"PID: {record.pid or 'not running'}",
        f"Exit code: {record.exit_code if record.exit_code is not None else 'pending'}",
        f"Steps: {record.steps}",
        f"Prompt SHA-256: {record.prompt_hash}",
        f"Main command SHA-256: {record.main_command_hash}",
        f"Script SHA-256: {record.script_hash}",
        f"Blueprint SHA-256: {record.blueprint_hash}",
        f"Artifacts: {record.artifacts_dir}",
        f"Script: {record.script_path}",
        f"Blueprint: {record.blueprint_path}",
        f"Final answer: {record.final_path}",
        f"Event stream: {record.jsonl_path}",
        f"Log: {record.log_path}",
        f"Manifest: {record.manifest_path}",
        f"Note: {record.note or 'none'}",
        "",
        "Metadata record: raw prompt and raw command are not stored here. The replay script and blueprint live in the artifact folder.",
    ])


def build_autopilot_plan(
    *,
    blueprint: MissionBlueprint,
    project: str,
    prompt: str,
    codex_bin: str,
    common_args: list[str],
    skip_git: bool,
    artifacts_root: Path,
    validation_commands: tuple[str, ...],
    timestamp: int | None = None,
) -> AutopilotPlan:
    run_id = autopilot_id(prompt, timestamp=timestamp)
    title = slugify(blueprint.headline, "mission")
    artifacts_dir = artifacts_root / run_id
    final_path = artifacts_dir / "codex-final.txt"
    jsonl_path = artifacts_dir / "codex-events.jsonl"
    main_command = [codex_bin, *common_args, "exec", "--json", "--output-last-message", str(final_path)]
    if skip_git:
        main_command.append("--skip-git-repo-check")
    main_command.append(prompt)

    codex_stream_command = f"set -o pipefail; {shlex.join(main_command)} | tee {shlex.quote(str(jsonl_path))}"
    steps: list[AutopilotStep] = [
        AutopilotStep("Codex doctor", (codex_bin, "doctor", "--summary", "--ascii")),
        AutopilotStep("Maximum Codex exec", ("bash", "-lc", codex_stream_command)),
    ]
    for index, command in enumerate(validation_commands[:4], start=1):
        if command.strip():
            steps.append(AutopilotStep(f"Validation {index}", ("bash", "-lc", command.strip())))
    manifest_path = artifacts_dir / "manifest.txt"
    manifest_update = (
        f"printf 'completed=%s\\n' \"$(date -Is)\" >> {shlex.quote(str(manifest_path))}; "
        f"printf '%s\\n' {shlex.quote('final=' + str(final_path))} {shlex.quote('events=' + str(jsonl_path))} >> {shlex.quote(str(manifest_path))}"
    )
    steps.append(AutopilotStep("Artifact manifest", (
        "bash",
        "-lc",
        manifest_update,
    )))
    return AutopilotPlan(
        id=run_id,
        title=blueprint.headline,
        project=str(Path(project).expanduser()),
        artifacts_dir=str(artifacts_dir),
        main_command=tuple(main_command),
        steps=tuple(steps),
    )
