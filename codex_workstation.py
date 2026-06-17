#!/usr/bin/env python3
"""Workbench layout and action feedback helpers for Codex Control."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping


DEFAULT_PANES: dict[str, int] = {
    "workbench": 980,
    "palette": 560,
    "context": 440,
    "roadmap": 480,
    "orchestration": 500,
    "quality": 500,
}

PANE_LIMITS: dict[str, tuple[int, int]] = {
    "workbench": (720, 1400),
    "palette": (360, 900),
    "context": (320, 820),
    "roadmap": (340, 860),
    "orchestration": (360, 900),
    "quality": (360, 900),
}


@dataclass(frozen=True)
class WorkstationLayout:
    window_width: int = 1600
    window_height: int = 980
    start_maximized: bool = True
    sidebar_width: int = 178
    rail_width: int = 392
    panes: dict[str, int] | None = None

    def pane_positions(self) -> dict[str, int]:
        values = dict(DEFAULT_PANES)
        if self.panes:
            values.update(self.panes)
        return {
            key: clamp_int(value, DEFAULT_PANES.get(key, value), *PANE_LIMITS.get(key, (240, 1800)))
            for key, value in values.items()
        }


@dataclass(frozen=True)
class ActionFeedback:
    action_id: str
    title: str
    group: str
    phase: str
    detail: str

    def headline(self) -> str:
        return f"{self.phase.capitalize()}: {self.title}"

    def compact(self) -> str:
        return f"{self.title} | {self.group} | {self.phase}"


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def bool_from_config(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def layout_from_config(config: Mapping[str, Any]) -> WorkstationLayout:
    raw = config.get("layout")
    data = raw if isinstance(raw, Mapping) else {}
    raw_panes = data.get("panes")
    panes = raw_panes if isinstance(raw_panes, Mapping) else {}
    start_maximized = bool_from_config(data.get("start_maximized"), True)
    return WorkstationLayout(
        window_width=1600 if start_maximized else clamp_int(data.get("window_width"), 1600, 1100, 2600),
        window_height=980 if start_maximized else clamp_int(data.get("window_height"), 980, 720, 1800),
        start_maximized=start_maximized,
        sidebar_width=clamp_int(data.get("sidebar_width"), 178, 150, 260),
        rail_width=clamp_int(data.get("rail_width"), 392, 320, 560),
        panes={
            str(key): clamp_int(value, DEFAULT_PANES.get(str(key), 480), *PANE_LIMITS.get(str(key), (240, 1800)))
            for key, value in panes.items()
        },
    )


def layout_to_config(layout: WorkstationLayout) -> dict[str, Any]:
    return {
        "window_width": layout.window_width,
        "window_height": layout.window_height,
        "start_maximized": layout.start_maximized,
        "sidebar_width": layout.sidebar_width,
        "rail_width": layout.rail_width,
        "panes": layout.pane_positions(),
    }


def pane_position(layout: WorkstationLayout, key: str, default: int) -> int:
    return layout.pane_positions().get(key, default)


def layout_with_pane(layout: WorkstationLayout, key: str, position: int) -> WorkstationLayout:
    minimum, maximum = PANE_LIMITS.get(key, (240, 1800))
    panes = layout.pane_positions()
    panes[key] = clamp_int(position, DEFAULT_PANES.get(key, position), minimum, maximum)
    return replace(layout, panes=panes)


def layout_with_window(layout: WorkstationLayout, width: int, height: int, maximized: bool) -> WorkstationLayout:
    return replace(
        layout,
        window_width=clamp_int(width, layout.window_width, 1100, 2600),
        window_height=clamp_int(height, layout.window_height, 720, 1800),
        start_maximized=maximized,
    )


def action_feedback(
    action_id: str,
    title: str | None,
    group: str | None,
    phase: str,
    detail: str | None = None,
) -> ActionFeedback:
    clean_title = (title or action_id or "Action").strip()
    clean_group = (group or "Action").strip()
    clean_phase = (phase or "ready").strip().lower()
    clean_detail = (detail or action_id or "").strip()
    return ActionFeedback(
        action_id=action_id,
        title=clean_title,
        group=clean_group,
        phase=clean_phase,
        detail=clean_detail,
    )
