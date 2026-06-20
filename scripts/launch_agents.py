#!/usr/bin/env python3
"""
Launch codex agents across multiple machines with retry/backoff logic
and support for JSON or YAML device configuration.
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
from typing import Callable, List, TypeVar

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

    sftp = ssh.open_sftp()
    sftp.put(str(prompt_local), remote_prompt)
    sftp.close()

    cmd = (
        f"cd {shlex.quote(repo_path)} && "
        "git fetch --all --prune && "
        f"nohup codex exec --json "
        f"--profile {shlex.quote(device.profile)} "
        f"--prompt-file {shlex.quote(remote_prompt)} "
        f">> {shlex.quote(str(remote_log))} 2>&1 < /dev/null & echo $!"
    )
    pid = run_remote(ssh, cmd)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch codex agents across machines (with retries & YAML)")
    parser.add_argument("--devices", required=True, help="Path to devices configuration (JSON or YAML)")
    parser.add_argument("--prompts-dir", default="role_prompts", help="Directory with role markdown prompts")
    parser.add_argument("--logs-dir", default="agent_logs")
    parser.add_argument("--repo-path", default=DEFAULT_REPO_PATH)
    parser.add_argument("--sync-repo", action="store_true", help="Run git fetch/pull before starting each agent")
    parser.add_argument("--collect-results", action="store_true", help="Collect changed files with git status after launch")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum number of retries for SSH operations")
    parser.add_argument("--backoff-seconds", type=float, default=2.0, help="Initial backoff time in seconds")
    args = parser.parse_args()

    prompt_path = Path(args.prompts_dir)
    log_dir = Path(args.logs_dir)
    repo_path = args.repo_path
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    devices = build_devices(args.devices)
    results: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(devices)) as executor:
        future_map: dict[concurrent.futures.Future, Device] = {}

        def task(device: Device) -> dict:
            ssh = with_retry(connect, args.max_retries, args.backoff_seconds, device)
            try:
                if args.sync_repo:
                    with_retry(
                        run_remote,
                        args.max_retries,
                        args.backoff_seconds,
                        ssh,
                        f"cd {shlex.quote(repo_path)} && git fetch --all --prune && git pull --ff-only",
                    )
                out = with_retry(
                    launch_agent,
                    args.max_retries,
                    args.backoff_seconds,
                    ssh,
                    device,
                    prompt_path,
                    log_dir,
                    repo_path,
                )
                out["status"] = "started"
                return out
            finally:
                ssh.close()

        def collect_task(device: Device, initial_out: dict) -> dict:
            collector = with_retry(connect, args.max_retries, args.backoff_seconds, device)
            try:
                modified_files = with_retry(
                    collect_modified_files,
                    args.max_retries,
                    args.backoff_seconds,
                    collector,
                    repo_path,
                )
                initial_out["modified_files"] = modified_files
            finally:
                collector.close()
            return initial_out

        for d in devices:
            future_map[executor.submit(task, d)] = d

        for fut in concurrent.futures.as_completed(future_map):
            dev = future_map[fut]
            try:
                result = fut.result()
                if args.collect_results and result.get("status") == "started":
                    result = collect_task(dev, result)
                results.append(result)
            except Exception as exc:
                results.append({
                    "host": dev.host,
                    "role": dev.role,
                    "status": "failed",
                    "error": str(exc),
                })

    for r in results:
        logging.info(json.dumps(r))


if __name__ == "__main__":
    main()
