#!/usr/bin/env python3
"""Persistent workspace sessions for Codex Control."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceSession:
    id: str
    title: str
    project: str
    profile: str
    action: str
    prompt: str
    status: str = "ready"
    thread_id: str = ""
    updated: int = 0


def _now() -> int:
    return int(time.time())


def session_title(prompt: str, fallback: str = "New Session") -> str:
    text = " ".join(prompt.strip().split())
    if not text:
        return fallback
    return text[:58] + ("..." if len(text) > 58 else "")


def new_session(project: str, profile: str, action: str, prompt: str, thread_id: str = "") -> WorkspaceSession:
    return WorkspaceSession(
        id=uuid.uuid4().hex[:12],
        title=session_title(prompt),
        project=project,
        profile=profile or "maximum-power",
        action=action or "interactive",
        prompt=prompt,
        status="ready",
        thread_id=thread_id,
        updated=_now(),
    )


def touch_session(session: WorkspaceSession, status: str | None = None) -> WorkspaceSession:
    return WorkspaceSession(
        id=session.id,
        title=session.title,
        project=session.project,
        profile=session.profile,
        action=session.action,
        prompt=session.prompt,
        status=status or session.status,
        thread_id=session.thread_id,
        updated=_now(),
    )


def replace_session(
    session: WorkspaceSession,
    *,
    project: str,
    profile: str,
    action: str,
    prompt: str,
    status: str | None = None,
    thread_id: str | None = None,
) -> WorkspaceSession:
    return WorkspaceSession(
        id=session.id,
        title=session_title(prompt, session.title),
        project=project,
        profile=profile or session.profile,
        action=action or session.action,
        prompt=prompt,
        status=status or session.status,
        thread_id=session.thread_id if thread_id is None else thread_id,
        updated=_now(),
    )


def load_sessions(path: Path) -> list[WorkspaceSession]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    sessions: list[WorkspaceSession] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            sessions.append(WorkspaceSession(
                id=str(item.get("id") or uuid.uuid4().hex[:12]),
                title=str(item.get("title") or "Session"),
                project=str(item.get("project") or ""),
                profile=str(item.get("profile") or "maximum-power"),
                action=str(item.get("action") or "interactive"),
                prompt=str(item.get("prompt") or ""),
                status=str(item.get("status") or "ready"),
                thread_id=str(item.get("thread_id") or ""),
                updated=int(item.get("updated") or 0),
            ))
        except (TypeError, ValueError):
            continue
    return sorted(sessions, key=lambda session: session.updated, reverse=True)


def save_sessions(path: Path, sessions: list[WorkspaceSession], limit: int = 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(sessions, key=lambda session: session.updated, reverse=True)[:limit]
    path.write_text(json.dumps([asdict(session) for session in ordered], indent=2), encoding="utf-8")


def upsert_session(sessions: list[WorkspaceSession], session: WorkspaceSession) -> list[WorkspaceSession]:
    replaced = False
    next_sessions: list[WorkspaceSession] = []
    for existing in sessions:
        if existing.id == session.id:
            next_sessions.append(session)
            replaced = True
        else:
            next_sessions.append(existing)
    if not replaced:
        next_sessions.insert(0, session)
    return sorted(next_sessions, key=lambda item: item.updated, reverse=True)


def remove_session(sessions: list[WorkspaceSession], session_id: str) -> list[WorkspaceSession]:
    return [session for session in sessions if session.id != session_id]
