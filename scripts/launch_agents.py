#!/usr/bin/env python3
"""
Launch codex agents across multiple machines with retry/backoff logic,
support JSON or YAML device definitions, and optional result summaries.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import shlex
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, TypeVar

import paramiko
import yaml  # Requires PyYAML: pip install pyyaml


DEFAULT_REPO_PATH = "~/project"
RETRY_EXCEPTIONS = (
    paramiko.SSHException,
    socket.timeout,
    socket.error,
    RuntimeError,
)
T = TypeVar("T")


@dataclass
class Device:
    host: str
    user: str
    role: str
    profile: str
    key: str | None = None
    port: int = 22


def run_remote(ssh: paramiko.SSHClient, command: str) -> str:
    _, stdout, stderr = ssh.exec_command(command)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "ignore").strip()
    err = stderr.read().decode("utf-8", "ignore").strip()
    if rc != 0:
        raise RuntimeError(f"remote command failed (rc={rc}): {err or out}")
    return out


def build_launch_command(repo_path: str, device: Device, remote_prompt: str, remote_log: str) -> str:
    return (
        f"cd {shlex.quote(repo_path)} && "
        "git fetch --all --prune && "
        f"nohup codex exec --json "
        f"--profile {shlex.quote(device.profile)} "
        f"--prompt-file {shlex.quote(remote_prompt)} "
        f">> {shlex.quote(remote_log)} 2>&1 < /dev/null & echo $!"
    )


def launch_agent(
    ssh: paramiko.SSHClient,
    device: Device,
    prompt_path: Path,
    log_dir: Path,
    repo_path: str,
) -> dict:
    prompt_local = prompt_path / f"{device.role.lower()}.md"
    if not prompt_local.exists():
        raise FileNotFoundError(f"missing prompt file: {prompt_local}")
    remote_prompt = f"/tmp/codex_prompt_{device.role.lower()}.md"
    remote_log = log_dir / f"{device.role.lower()}_{device.host}.log"
    command = build_launch_command(repo_path, device, remote_prompt, str(remote_log))

    sftp = ssh.open_sftp()
    sftp.put(str(prompt_local), remote_prompt)
    sftp.close()

    pid = run_remote(ssh, command)
    return {"host": device.host, "role": device.role, "pid": pid, "log": str(remote_log)}


def build_devices(path: str) -> List[Device]:
    """Load devices from JSON or YAML."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return [Device(**item) for item in data]


def collect_modified_files(ssh: paramiko.SSHClient, repo_path: str) -> list[str]:
    output = run_remote(ssh, f"cd {shlex.quote(repo_path)} && git status --porcelain")
    if not output:
        return []
    changed_files: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            changed_files.append(parts[1])
        elif len(parts) == 1:
            changed_files.append(parts[0])
    return sorted(changed_files)


def collect_diff_summary(ssh: paramiko.SSHClient, repo_path: str, base: str) -> dict[str, object]:
    output = run_remote(
        ssh,
        f"cd {shlex.quote(repo_path)} && git diff --name-status --find-renames {shlex.quote(base)}..HEAD",
    )
    summary: Dict[str, object] = {
        "base": base,
        "files": {
            "added": [],
            "modified": [],
            "removed": [],
            "renamed": [],
        },
        "counts": {
            "added": 0,
            "modified": 0,
            "removed": 0,
            "renamed": 0,
            "total": 0,
        },
    }

    files = summary["files"]
    counts = summary["counts"]
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        status_and_paths = stripped.split("\t")
        if len(status_and_paths) < 2:
            continue

        status = status_and_paths[0]
        target = status_and_paths[1]
        if status.startswith("R") or status.startswith("C"):
            if len(status_and_paths) >= 3:
                target = status_and_paths[2]
            files["renamed"].append(target)
            counts["renamed"] += 1
        elif status.startswith("A"):
            files["added"].append(target)
            counts["added"] += 1
        elif status.startswith("D"):
            files["removed"].append(target)
            counts["removed"] += 1
        else:
            files["modified"].append(target)
            counts["modified"] += 1

    counts["total"] = (
        counts["added"]
        + counts["modified"]
        + counts["removed"]
        + counts["renamed"]
    )
    return summary


def collect_commit_metadata(ssh: paramiko.SSHClient, repo_path: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "head": None,
        "head_short": None,
        "branch": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
    }
    quoted_repo = shlex.quote(repo_path)
    metadata["head"] = run_remote(ssh, f"cd {quoted_repo} && git rev-parse HEAD").strip()
    metadata["head_short"] = run_remote(ssh, f"cd {quoted_repo} && git rev-parse --short HEAD").strip()
    metadata["branch"] = run_remote(ssh, f"cd {quoted_repo} && git branch --show-current").strip()

    try:
        upstream = run_remote(
            ssh,
            f"cd {quoted_repo} && git rev-parse --abbrev-ref --symbolic-full-name @{{u}}",
        )
        upstream = upstream.strip()
        if upstream:
            metadata["upstream"] = upstream
            ahead = run_remote(
                ssh,
                f"cd {quoted_repo} && git rev-list --count {shlex.quote(upstream)}..HEAD",
            )
            behind = run_remote(
                ssh,
                f"cd {quoted_repo} && git rev-list --count HEAD..{shlex.quote(upstream)}",
            )
            metadata["ahead"] = int(ahead.strip() or "0")
            metadata["behind"] = int(behind.strip() or "0")
    except Exception:
        pass
    return metadata


def _failure_result(
    device: Device, stage: str, error: Exception, command: str | None = None
) -> dict[str, str | int | None]:
    result: dict[str, str | int | None] = {
        "host": device.host,
        "role": device.role,
        "status": "failed",
        "failure_stage": stage,
        "error": str(error),
    }
    if command is not None:
        result["command"] = command
    return result


def connect(device: Device) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, object] = {
        "hostname": device.host,
        "username": device.user,
        "port": device.port,
        "timeout": 30,
    }
    if device.key:
        kwargs["key_filename"] = device.key
    ssh.connect(**kwargs)
    return ssh


def with_retry(
    func: Callable[..., T],
    max_retries: int,
    backoff: float,
    *args: object,
    **kwargs: object,
) -> T:
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except RETRY_EXCEPTIONS as exc:
            attempt += 1
            if attempt > max_retries:
                raise exc
            sleep_time = backoff * (2 ** (attempt - 1))
            logging.warning(
                "Retryable error (%s): %s. Retrying in %.1f s (%d/%d)",
                type(exc).__name__,
                exc,
                sleep_time,
                attempt,
                max_retries,
            )
            time.sleep(sleep_time)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch codex agents across machines (with retries, YAML, and summaries)"
    )
    parser.add_argument("--devices", required=True, help="Path to devices configuration (JSON or YAML)")
    parser.add_argument("--prompts-dir", default="role_prompts", help="Directory with role markdown prompts")
    parser.add_argument("--logs-dir", default="agent_logs")
    parser.add_argument("--repo-path", default=DEFAULT_REPO_PATH)
    parser.add_argument("--sync-repo", action="store_true", help="Run git fetch/pull before starting each agent")
    parser.add_argument("--collect-results", action="store_true", help="Collect changed files with git status after launch")
    parser.add_argument("--summarize-results", action="store_true", help="Collect diff summary and commit metadata")
    parser.add_argument(
        "--summary-base",
        default="HEAD~1",
        help="Base ref for --summarize-results (default: HEAD~1)",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum number of retries for SSH operations")
    parser.add_argument("--backoff-seconds", type=float, default=2.0, help="Initial backoff time in seconds")
    args = parser.parse_args()

    if args.summarize_results:
        args.collect_results = True

    prompt_path = Path(args.prompts_dir)
    log_dir = Path(args.logs_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    devices = build_devices(args.devices)
    results: list[dict] = []

    def task(device: Device) -> dict:
        stage = "connect"
        command: str | None = None
        try:
            ssh = with_retry(connect, args.max_retries, args.backoff_seconds, device)
        except Exception as exc:
            return _failure_result(device, stage, exc, command)

        try:
            if args.sync_repo:
                stage = "sync_repo"
                command = f"cd {shlex.quote(args.repo_path)} && git fetch --all --prune && git pull --ff-only"
                with_retry(
                    run_remote,
                    args.max_retries,
                    args.backoff_seconds,
                    ssh,
                    command,
                )

            stage = "launch_agent"
            remote_prompt = f"/tmp/codex_prompt_{device.role.lower()}.md"
            remote_log = log_dir / f"{device.role.lower()}_{device.host}.log"
            command = build_launch_command(args.repo_path, device, remote_prompt, str(remote_log))
            launch_result = with_retry(
                launch_agent,
                args.max_retries,
                args.backoff_seconds,
                ssh,
                device,
                prompt_path,
                log_dir,
                args.repo_path,
            )
            launch_result["status"] = "started"

            if args.collect_results:
                stage = "collect_modified_files"
                command = f"cd {shlex.quote(args.repo_path)} && git status --porcelain"
                launch_result["modified_files"] = with_retry(
                    collect_modified_files,
                    args.max_retries,
                    args.backoff_seconds,
                    ssh,
                    args.repo_path,
                )
                if args.summarize_results:
                    stage = "collect_diff_summary"
                    command = (
                        f"cd {shlex.quote(args.repo_path)} && "
                        f"git diff --name-status --find-renames {shlex.quote(args.summary_base)}..HEAD"
                    )
                    launch_result["diff_summary"] = with_retry(
                        collect_diff_summary,
                        args.max_retries,
                        args.backoff_seconds,
                        ssh,
                        args.repo_path,
                        args.summary_base,
                    )
                    stage = "collect_commit_metadata"
                    command = f"cd {shlex.quote(args.repo_path)} && git rev-parse HEAD"
                    launch_result["commit"] = with_retry(
                        collect_commit_metadata,
                        args.max_retries,
                        args.backoff_seconds,
                        ssh,
                        args.repo_path,
                    )

            return launch_result
        except Exception as exc:
            return _failure_result(device, stage, exc, command)
        finally:
            ssh.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(devices)) as executor:
        future_map: dict[concurrent.futures.Future, Device] = {}
        for d in devices:
            future_map[executor.submit(task, d)] = d

        for future in concurrent.futures.as_completed(future_map):
            results.append(future.result())

    for result in results:
        logging.info(json.dumps(result))


if __name__ == "__main__":
    main()
