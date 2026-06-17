#!/usr/bin/env python3
"""Agent lane planning for Codex Control."""

from __future__ import annotations

import re
import json
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class AgentTemplate:
    title: str
    slug: str
    objective: str
    profile: str = "maximum-power"


@dataclass(frozen=True)
class AgentLane:
    title: str
    slug: str
    objective: str
    profile: str
    project: str
    workdir: str
    branch: str
    prompt: str
    uses_worktree: bool
    status: str = "planned"


@dataclass(frozen=True)
class AgentPlan:
    run_id: str
    project: str
    root: str
    is_git: bool
    prompt: str
    lanes: tuple[AgentLane, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class AgentResult:
    lane_slug: str
    title: str
    workdir: str
    branch: str
    exists: bool
    git: bool
    status: str
    tracked: int
    untracked: int
    status_lines: tuple[str, ...]
    diff_stat: tuple[str, ...]
    note: str
    can_apply: bool
    can_merge: bool


@dataclass(frozen=True)
class AgentRunRecord:
    id: str
    title: str
    project: str
    prompt: str
    status: str
    plan: AgentPlan
    results: tuple[AgentResult, ...]
    artifacts: tuple[str, ...]
    created: int
    updated: int


@dataclass(frozen=True)
class AgentExecutionRecord:
    id: str
    run_id: str
    lane_slug: str
    title: str
    workdir: str
    command: tuple[str, ...]
    log_path: str
    final_path: str
    status: str
    pid: int = 0
    exit_code: int | None = None
    started: int = 0
    finished: int = 0


DEFAULT_AGENT_TEMPLATES: tuple[AgentTemplate, ...] = (
    AgentTemplate(
        "Architect",
        "architect",
        "Map the implementation approach, identify high-leverage files, risks, and validation commands.",
    ),
    AgentTemplate(
        "Builder",
        "builder",
        "Implement the core working change end to end while staying scoped to the user request.",
    ),
    AgentTemplate(
        "Reviewer",
        "reviewer",
        "Review the planned or completed change for bugs, regressions, missing tests, and weak assumptions.",
        "deep-review",
    ),
    AgentTemplate(
        "UI Polish",
        "ui-polish",
        "Improve the rendered user experience, visual hierarchy, fit, copy, and interaction details.",
    ),
    AgentTemplate(
        "Verifier",
        "verifier",
        "Run focused checks, repair failures where appropriate, and report remaining risk clearly.",
    ),
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "agent"


def default_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _now() -> int:
    return int(time.time())


def run_title(prompt: str, fallback: str = "Agent Run") -> str:
    text = " ".join(prompt.strip().split())
    if not text:
        return fallback
    return text[:58] + ("..." if len(text) > 58 else "")


def execution_id(run_id: str, lane_slug: str) -> str:
    return f"{slugify(run_id)}-{slugify(lane_slug)}"


def execution_paths(base_dir: Path, run_id: str, lane_slug: str) -> tuple[Path, Path]:
    run_dir = base_dir / slugify(run_id)
    stem = slugify(lane_slug)
    return run_dir / f"{stem}.jsonl", run_dir / f"{stem}.final.txt"


def new_execution_record(base_dir: Path, run_id: str, lane: AgentLane, command: list[str]) -> AgentExecutionRecord:
    log_path, final_path = execution_paths(base_dir, run_id, lane.slug)
    return AgentExecutionRecord(
        id=execution_id(run_id, lane.slug),
        run_id=run_id,
        lane_slug=lane.slug,
        title=lane.title,
        workdir=lane.workdir,
        command=tuple(command),
        log_path=str(log_path),
        final_path=str(final_path),
        status="queued",
        started=_now(),
    )


def update_execution_record(record: AgentExecutionRecord, **changes: object) -> AgentExecutionRecord:
    return replace(record, **changes)


def tail_text(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def worktree_path(root: str, run_id: str, slug: str) -> str:
    repo = Path(root).expanduser()
    return str(repo.parent / f"{repo.name}-agent-{slugify(run_id)}-{slugify(slug)}")


def lane_prompt(template: AgentTemplate, prompt: str, project_context: str) -> str:
    user_prompt = prompt.strip() or "Improve this project using the current Codex Control workflow."
    context = project_context.strip() or "No project snapshot was available. Inspect the local files before acting."
    return "\n".join([
        f"You are the {template.title} lane in a Codex Control multi-agent run.",
        "",
        "Primary user request:",
        user_prompt,
        "",
        "Lane objective:",
        template.objective,
        "",
        "Project context:",
        context,
        "",
        "Working rules:",
        "- Stay scoped to this lane and the user request.",
        "- Prefer concrete implementation or verification over broad discussion.",
        "- Keep changes reversible and avoid unrelated refactors.",
        "- At the end, report files changed, commands run, failures, and recommended next action.",
    ])


def build_agent_plan(
    project: str,
    prompt: str,
    project_context: str = "",
    *,
    is_git: bool = False,
    git_root: str | None = None,
    run_id: str | None = None,
    templates: tuple[AgentTemplate, ...] = DEFAULT_AGENT_TEMPLATES,
) -> AgentPlan:
    project_path = str(Path(project).expanduser())
    root = str(Path(git_root or project_path).expanduser())
    plan_id = slugify(run_id or default_run_id())
    lanes: list[AgentLane] = []
    for template in templates:
        slug = slugify(template.slug)
        branch = f"codex/{plan_id}/{slug}" if is_git else ""
        lane_workdir = worktree_path(root, plan_id, slug) if is_git else project_path
        lanes.append(AgentLane(
            title=template.title,
            slug=slug,
            objective=template.objective,
            profile=template.profile,
            project=project_path,
            workdir=lane_workdir,
            branch=branch,
            prompt=lane_prompt(template, prompt, project_context),
            uses_worktree=is_git,
        ))
    notes = (
        "Git project detected: each lane is isolated in its own worktree.",
        "Use Prep before running all lanes if you want to create the worktrees first.",
    ) if is_git else (
        "No Git repository detected: lanes run against the shared project directory.",
        "Use one lane at a time for write-heavy work, or initialize Git before parallel edits.",
    )
    return AgentPlan(
        run_id=plan_id,
        project=project_path,
        root=root,
        is_git=is_git,
        prompt=prompt.strip(),
        lanes=tuple(lanes),
        notes=notes,
    )


def lane_from_dict(data: dict[str, object]) -> AgentLane:
    return AgentLane(
        title=str(data.get("title") or "Lane"),
        slug=str(data.get("slug") or "lane"),
        objective=str(data.get("objective") or ""),
        profile=str(data.get("profile") or "maximum-power"),
        project=str(data.get("project") or ""),
        workdir=str(data.get("workdir") or ""),
        branch=str(data.get("branch") or ""),
        prompt=str(data.get("prompt") or ""),
        uses_worktree=bool(data.get("uses_worktree")),
        status=str(data.get("status") or "planned"),
    )


def plan_from_dict(data: dict[str, object]) -> AgentPlan:
    lanes_data = data.get("lanes")
    lanes = tuple(lane_from_dict(item) for item in lanes_data if isinstance(item, dict)) if isinstance(lanes_data, list) else ()
    notes_data = data.get("notes")
    notes = tuple(str(item) for item in notes_data) if isinstance(notes_data, list) else ()
    return AgentPlan(
        run_id=str(data.get("run_id") or "run"),
        project=str(data.get("project") or ""),
        root=str(data.get("root") or data.get("project") or ""),
        is_git=bool(data.get("is_git")),
        prompt=str(data.get("prompt") or ""),
        lanes=lanes,
        notes=notes,
    )


def result_from_dict(data: dict[str, object]) -> AgentResult:
    status_lines_data = data.get("status_lines")
    diff_stat_data = data.get("diff_stat")
    return AgentResult(
        lane_slug=str(data.get("lane_slug") or ""),
        title=str(data.get("title") or "Lane"),
        workdir=str(data.get("workdir") or ""),
        branch=str(data.get("branch") or ""),
        exists=bool(data.get("exists")),
        git=bool(data.get("git")),
        status=str(data.get("status") or "unknown"),
        tracked=int(data.get("tracked") or 0),
        untracked=int(data.get("untracked") or 0),
        status_lines=tuple(str(item) for item in status_lines_data) if isinstance(status_lines_data, list) else (),
        diff_stat=tuple(str(item) for item in diff_stat_data) if isinstance(diff_stat_data, list) else (),
        note=str(data.get("note") or ""),
        can_apply=bool(data.get("can_apply")),
        can_merge=bool(data.get("can_merge")),
    )


def record_from_dict(data: dict[str, object]) -> AgentRunRecord:
    plan_data = data.get("plan")
    plan = plan_from_dict(plan_data if isinstance(plan_data, dict) else {})
    results_data = data.get("results")
    artifacts_data = data.get("artifacts")
    created = int(data.get("created") or _now())
    return AgentRunRecord(
        id=str(data.get("id") or plan.run_id),
        title=str(data.get("title") or run_title(plan.prompt)),
        project=str(data.get("project") or plan.project),
        prompt=str(data.get("prompt") or plan.prompt),
        status=str(data.get("status") or "planned"),
        plan=plan,
        results=tuple(result_from_dict(item) for item in results_data if isinstance(item, dict)) if isinstance(results_data, list) else (),
        artifacts=tuple(str(item) for item in artifacts_data) if isinstance(artifacts_data, list) else (),
        created=created,
        updated=int(data.get("updated") or created),
    )


def record_from_plan(
    plan: AgentPlan,
    results: tuple[AgentResult, ...] = (),
    *,
    status: str = "planned",
    artifacts: tuple[str, ...] = (),
    existing: AgentRunRecord | None = None,
) -> AgentRunRecord:
    created = existing.created if existing is not None else _now()
    return AgentRunRecord(
        id=existing.id if existing is not None else plan.run_id,
        title=run_title(plan.prompt),
        project=plan.project,
        prompt=plan.prompt,
        status=status,
        plan=plan,
        results=results,
        artifacts=artifacts or (existing.artifacts if existing is not None else ()),
        created=created,
        updated=_now(),
    )


def load_agent_runs(path: Path) -> list[AgentRunRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    records: list[AgentRunRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            records.append(record_from_dict(item))
        except (TypeError, ValueError):
            continue
    return sorted(records, key=lambda record: record.updated, reverse=True)


def save_agent_runs(path: Path, records: list[AgentRunRecord], limit: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record.updated, reverse=True)[:limit]
    path.write_text(json.dumps([asdict(record) for record in ordered], indent=2), encoding="utf-8")


def upsert_agent_run(records: list[AgentRunRecord], record: AgentRunRecord) -> list[AgentRunRecord]:
    replaced = False
    next_records: list[AgentRunRecord] = []
    for existing in records:
        if existing.id == record.id:
            next_records.append(record)
            replaced = True
        else:
            next_records.append(existing)
    if not replaced:
        next_records.insert(0, record)
    return sorted(next_records, key=lambda item: item.updated, reverse=True)


def remove_agent_run(records: list[AgentRunRecord], record_id: str) -> list[AgentRunRecord]:
    return [record for record in records if record.id != record_id]


def prepare_worktree_script(lane: AgentLane, root: str) -> str:
    target = shlex.quote(lane.workdir)
    if not lane.uses_worktree:
        return f"cd -- {target}"
    repo = shlex.quote(root)
    branch = shlex.quote(lane.branch)
    return "\n".join([
        "set -e",
        f"if [ ! -d {target} ]; then",
        f"  if git -C {repo} show-ref --verify --quiet refs/heads/{branch}; then",
        f"    git -C {repo} worktree add {target} {branch}",
        "  else",
        f"    git -C {repo} worktree add -b {branch} {target}",
        "  fi",
        "fi",
        f"cd -- {target}",
    ])


def _run_text(args: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    text = result.stdout
    if result.stderr:
        text += ("\n" if text else "") + result.stderr
    return result.returncode, text.strip()


def _git_lines(workdir: str, *args: str) -> tuple[str, ...]:
    code, text = _run_text(["git", "-C", workdir, *args])
    if code != 0:
        return ()
    return tuple(line.rstrip() for line in text.splitlines() if line.strip())


def collect_lane_result(lane: AgentLane, root: str) -> AgentResult:
    path = Path(lane.workdir).expanduser()
    if not path.exists():
        return AgentResult(
            lane_slug=lane.slug,
            title=lane.title,
            workdir=str(path),
            branch=lane.branch,
            exists=False,
            git=False,
            status="missing",
            tracked=0,
            untracked=0,
            status_lines=(),
            diff_stat=(),
            note="Workdir has not been created yet.",
            can_apply=False,
            can_merge=False,
        )

    git_code, git_text = _run_text(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"])
    if git_code != 0 or git_text.strip() != "true":
        return AgentResult(
            lane_slug=lane.slug,
            title=lane.title,
            workdir=str(path),
            branch=lane.branch,
            exists=True,
            git=False,
            status="no-git",
            tracked=0,
            untracked=0,
            status_lines=(),
            diff_stat=(),
            note="No Git status is available for this lane.",
            can_apply=False,
            can_merge=False,
        )

    status_lines = _git_lines(str(path), "status", "--short")
    tracked = sum(1 for line in status_lines if not line.startswith("??"))
    untracked = sum(1 for line in status_lines if line.startswith("??"))
    diff_stat = _git_lines(str(path), "diff", "--stat", "HEAD")
    if status_lines:
        status = "changed"
        note = f"{tracked} tracked and {untracked} untracked changes."
    else:
        status = "clean"
        note = "No working tree changes detected."
    return AgentResult(
        lane_slug=lane.slug,
        title=lane.title,
        workdir=str(path),
        branch=lane.branch,
        exists=True,
        git=True,
        status=status,
        tracked=tracked,
        untracked=untracked,
        status_lines=status_lines,
        diff_stat=diff_stat,
        note=note,
        can_apply=lane.uses_worktree and tracked > 0,
        can_merge=lane.uses_worktree and bool(lane.branch),
    )


def collect_agent_results(plan: AgentPlan) -> tuple[AgentResult, ...]:
    return tuple(collect_lane_result(lane, plan.root) for lane in plan.lanes)


def lane_diff_script(lane: AgentLane) -> str:
    target = shlex.quote(lane.workdir)
    return "\n".join([
        "set -e",
        f"if [ ! -d {target} ]; then echo 'Lane workdir missing: {lane.workdir}'; exit 0; fi",
        f"cd -- {target}",
        "if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then",
        "  git status --short --branch",
        "  printf '\\n[diff stat]\\n'",
        "  git diff --stat HEAD || git diff --stat",
        "  printf '\\n[diff]\\n'",
        "  git diff --binary HEAD || git diff --binary",
        "else",
        "  printf '%s\\n' 'No Git repository in this lane. Showing top-level files instead.'",
        "  find . -maxdepth 2 -type f | sort | head -120",
        "fi",
    ])


def lane_apply_script(lane: AgentLane, root: str) -> str:
    target = shlex.quote(lane.workdir)
    repo = shlex.quote(root)
    return "\n".join([
        "set -e",
        f"if [ ! -d {target} ]; then echo 'Lane workdir missing: {lane.workdir}'; exit 1; fi",
        f"if ! git -C {target} rev-parse --is-inside-work-tree >/dev/null 2>&1; then echo 'Lane is not a Git worktree.'; exit 1; fi",
        f"if ! git -C {repo} rev-parse --is-inside-work-tree >/dev/null 2>&1; then echo 'Target project is not a Git repository.'; exit 1; fi",
        "patch_file=$(mktemp)",
        "trap 'rm -f \"$patch_file\"' EXIT",
        f"git -C {target} diff --binary HEAD > \"$patch_file\" || git -C {target} diff --binary > \"$patch_file\"",
        "if [ ! -s \"$patch_file\" ]; then echo 'No tracked diff to apply.'; exit 0; fi",
        f"git -C {repo} apply --3way \"$patch_file\"",
        f"git -C {repo} status --short",
    ])


def lane_merge_script(lane: AgentLane, root: str) -> str:
    repo = shlex.quote(root)
    branch = shlex.quote(lane.branch)
    if not lane.branch:
        return "echo 'Lane has no branch to merge.'; exit 1"
    return "\n".join([
        "set -e",
        f"if ! git -C {repo} rev-parse --is-inside-work-tree >/dev/null 2>&1; then echo 'Target project is not a Git repository.'; exit 1; fi",
        f"git -C {repo} show-ref --verify --quiet refs/heads/{branch} || (echo 'Lane branch missing: {lane.branch}'; exit 1)",
        f"git -C {repo} merge --no-ff {branch}",
        f"git -C {repo} status --short",
    ])


def plan_markdown(plan: AgentPlan) -> str:
    lines = [
        f"# Codex Agent Plan {plan.run_id}",
        "",
        f"- Project: `{plan.project}`",
        f"- Root: `{plan.root}`",
        f"- Isolation: {'Git worktrees' if plan.is_git else 'shared project directory'}",
        "",
        "## Notes",
    ]
    lines.extend(f"- {note}" for note in plan.notes)
    lines.append("")
    lines.append("## Lanes")
    for lane in plan.lanes:
        lines.extend([
            f"### {lane.title}",
            f"- Profile: `{lane.profile}`",
            f"- Workdir: `{lane.workdir}`",
            f"- Branch: `{lane.branch or 'none'}`",
            f"- Objective: {lane.objective}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"
