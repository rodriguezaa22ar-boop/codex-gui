#!/usr/bin/env python3
"""Visual system tokens and GTK CSS overlays for Codex Control."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VisualToken:
    name: str
    value: str
    role: str


@dataclass(frozen=True)
class VisualAudit:
    selectors_present: tuple[str, ...]
    selectors_missing: tuple[str, ...]
    color_count: int
    has_gradient: bool

    @property
    def passed(self) -> bool:
        return not self.selectors_missing and self.color_count >= 10 and not self.has_gradient

    def summary(self) -> str:
        status = "passed" if self.passed else "review"
        return f"{status}: {len(self.selectors_present)} selectors, {self.color_count} colors"


TOKENS: tuple[VisualToken, ...] = (
    VisualToken("root", "#070b10", "surface"),
    VisualToken("toolbar", "#0b1017", "surface"),
    VisualToken("panel", "#101821", "surface"),
    VisualToken("panel_alt", "#0d141c", "surface"),
    VisualToken("panel_deep", "#080d13", "surface"),
    VisualToken("row", "#0d141d", "surface"),
    VisualToken("row_hover", "#13212b", "surface"),
    VisualToken("border", "#2a3a46", "border"),
    VisualToken("border_strong", "#365366", "border"),
    VisualToken("text", "#f3f7f5", "text"),
    VisualToken("muted", "#aebbc4", "text"),
    VisualToken("subtle", "#7f909b", "text"),
    VisualToken("accent", "#28a98f", "accent"),
    VisualToken("accent_hover", "#32b99f", "accent"),
    VisualToken("accent_edge", "#b88438", "accent"),
    VisualToken("amber", "#f0b34d", "accent"),
    VisualToken("success_bg", "#11342f", "status"),
    VisualToken("success_text", "#a8f0dd", "status"),
    VisualToken("danger_bg", "#321c1b", "status"),
    VisualToken("danger_text", "#ffb3aa", "status"),
)

REQUIRED_SELECTORS = (
    ".topbar",
    ".nav",
    ".nav-more",
    ".page",
    ".panel",
    ".operator-console",
    ".terminal-panel",
    ".composer",
    ".orchestration-panel",
    ".roadmap-panel",
    ".context-packet",
    ".action-preview",
    ".action-preview-title",
    ".action-feedback",
    ".action-feedback-title",
    ".action-history",
    ".action-history-title",
    ".chip-flow",
    ".next-step-banner",
    ".next-step-title",
    ".next-step-detail",
    ".device-mesh",
    ".device-row",
    ".mesh-detail",
    ".team-panel",
    ".team-row",
    ".memory-panel",
    ".primary",
    ".secondary",
    ".code-view",
)


def _define_colors() -> str:
    return "\n".join(f"@define-color cc_{token.name} {token.value};" for token in TOKENS)


def visual_system_css() -> str:
    """Return final GTK CSS overrides for the premium Codex Control surface."""
    return _define_colors() + r"""

window {
  background: @cc_root;
  color: @cc_text;
}

.topbar {
  background: @cc_toolbar;
  color: @cc_text;
  padding: 16px 18px;
  border-bottom: 1px solid @cc_accent_edge;
}

.brand-badge {
  background: @cc_amber;
  color: @cc_root;
  border-radius: 8px;
  padding: 8px 10px;
  font-weight: 800;
}

.app-title {
  font-size: 22px;
  font-weight: 800;
}

.subtitle {
  color: @cc_muted;
}

.nav {
  background: @cc_root;
  border-right: 1px solid #1d2a33;
  padding: 12px 8px;
}

.nav-row {
  min-height: 44px;
}

.nav row {
  color: @cc_text;
  border-radius: 8px;
  margin: 4px 0;
  padding: 10px 14px;
}

.nav row:hover {
  background: @cc_row_hover;
}

.nav row:selected {
  background: #23816f;
  color: #ffffff;
}

.nav row:selected image,
.nav row:selected label {
  color: #ffffff;
}

.nav-more {
  margin: 4px 0;
  padding: 4px;
  border-color: #1d2a33;
}

.page {
  background: @cc_root;
  padding: 16px;
}

.workbench {
  background: @cc_root;
}

.panel {
  background: @cc_panel;
  color: @cc_text;
  border: 1px solid @cc_border;
  border-radius: 8px;
  padding: 10px;
}

.operator-console {
  background: @cc_panel_alt;
  border: 1px solid @cc_border_strong;
  border-radius: 8px;
  padding: 12px;
}

.operator-card,
.stat-card,
.session-row,
.device-row,
.team-row,
.project-command,
.quality-row,
.action-row,
.context-row,
.roadmap-row,
.orchestration-row,
.mission-row,
.autopilot-row,
.receipt-row,
.command-run-row,
.agent-row,
.result-row,
.execution-row,
.run-row {
  background: @cc_row;
  border: 1px solid @cc_border;
  border-radius: 8px;
}

.operator-title,
.power-title,
.mission-title,
.quality-title,
.context-title,
.roadmap-title,
.orchestration-title {
  color: @cc_text;
  font-weight: 800;
}

.operator-subtitle,
.operator-card-detail,
.muted,
.context-detail,
.roadmap-detail,
.orchestration-detail,
.quality-check-detail,
.action-detail,
.action-preview-detail,
.action-feedback-detail,
.action-history-detail,
.mission-detail,
.autopilot-meta {
  color: @cc_muted;
}

button {
  min-height: 34px;
  border-radius: 7px;
  padding: 7px 12px;
  border: 1px solid @cc_border_strong;
  background: #17202a;
  color: @cc_text;
}

button:hover {
  background: #1d2a35;
}

.command-grid button {
  min-width: 0;
}

.command-grid label {
  font-weight: 700;
}

.workflow-panel {
  background: transparent;
  border-top: 1px solid #20313d;
  padding-top: 9px;
}

.next-step-banner {
  background: @cc_panel_alt;
  border: 1px solid @cc_border_strong;
  border-left: 3px solid @cc_accent;
  border-radius: 8px;
  padding: 10px;
}

.next-step-title {
  color: @cc_text;
  font-weight: 800;
}

.next-step-detail {
  color: @cc_muted;
}

.mesh-summary-actions {
  margin-top: 2px;
}

.primary {
  background: @cc_accent;
  color: #ffffff;
  border-color: @cc_accent_hover;
  font-weight: 800;
}

.primary:hover {
  background: @cc_accent_hover;
}

.secondary {
  background: #151c25;
  color: @cc_text;
  border-color: @cc_border_strong;
}

.accent {
  background: #2d2418;
  color: #f6cf86;
  border-color: @cc_accent_edge;
  font-weight: 800;
}

.status-pill {
  background: #dff5ee;
  color: #10251f;
  border: 1px solid #a7d7cb;
  border-radius: 999px;
  padding: 8px 13px;
  font-weight: 800;
}

.chip,
.mode-pill {
  background: #151e28;
  color: #e7edf0;
  border: 1px solid @cc_border_strong;
  border-radius: 999px;
}

.chip-flow {
  background: transparent;
}

.chip-flow flowboxchild {
  padding: 0;
}

.chip-strong {
  background: @cc_success_bg;
  color: @cc_success_text;
  border-color: #287565;
  border-radius: 999px;
}

.chip-danger {
  background: @cc_danger_bg;
  color: @cc_danger_text;
  border-color: #74423b;
  border-radius: 999px;
}

.action-preview {
  background: @cc_panel_alt;
  border: 1px solid @cc_border_strong;
  border-radius: 8px;
  padding: 10px;
}

.action-preview-title {
  color: @cc_text;
  font-weight: 800;
}

.action-preview-detail {
  color: @cc_muted;
}

.action-preview-command {
  background: @cc_panel_deep;
  color: @cc_text;
  border: 1px solid @cc_border;
  border-radius: 7px;
  padding: 8px;
  font-family: monospace;
}

.action-feedback {
  background: @cc_panel_alt;
  border: 1px solid @cc_border;
  border-radius: 8px;
  padding: 10px;
}

.action-feedback-title {
  color: @cc_success_text;
  font-weight: 800;
}

.action-feedback-detail {
  color: @cc_muted;
}

.action-history {
  background: @cc_panel_alt;
  border: 1px solid @cc_border;
  border-radius: 8px;
  padding: 10px;
}

.action-history-title {
  color: @cc_text;
  font-weight: 800;
}

.action-history-detail {
  color: @cc_muted;
}

.action-history-command {
  background: @cc_panel_deep;
  color: @cc_text;
  border: 1px solid @cc_border;
  border-radius: 7px;
  padding: 8px;
  font-family: monospace;
}

.terminal-panel,
.composer,
.command-preview,
.mesh-summary,
.mesh-detail,
.team-panel,
.team-stream-panel,
.memory-panel,
.project-intel,
.session-workspace,
.quality-gate,
.action-palette,
.context-packet,
.roadmap-panel,
.orchestration-panel,
.mission-architect,
.autopilot-panel,
.receipt-vault,
.run-ledger,
.agent-studio,
.result-console {
  background: @cc_panel;
  border-color: @cc_border_strong;
}

.terminal-panel {
  padding: 10px;
  border-color: @cc_accent;
}

.composer {
  padding: 10px;
}

.side-rail .panel,
.side-rail expander {
  background: transparent;
  border-color: #1b2934;
  padding: 8px;
}

.terminal-frame,
.code-view {
  background: #020509;
  color: #f0f6f4;
  border: 1px solid @cc_border_strong;
  border-radius: 7px;
}

.composer-view {
  background: @cc_panel_deep;
  color: @cc_text;
  border: 1px solid #1f303b;
  border-radius: 8px;
}

.side-rail {
  background: @cc_root;
  border-left: 1px solid #1b2934;
  padding-left: 10px;
}

entry, textview, dropdown, expander {
  background: @cc_panel_deep;
  color: @cc_text;
  border-color: @cc_border;
}

expander {
  border: 1px solid #1b2934;
  border-radius: 8px;
  padding: 6px;
}

expander title {
  color: @cc_muted;
  font-weight: 700;
}

.device-mesh {
  background: @cc_root;
}

.mesh-summary {
  border-color: @cc_accent_edge;
}

.device-list {
  background: @cc_panel_deep;
}

.team-list {
  background: @cc_panel_deep;
}

.device-row,
.team-row {
  margin: 4px 0;
  padding: 10px;
}

.device-row:hover,
.team-row:hover {
  background: @cc_row_hover;
}

.mesh-detail .code-view,
.memory-panel .code-view,
.team-stream-panel .code-view {
  min-height: 180px;
}
"""


def audit_visual_system(css: str) -> VisualAudit:
    selectors_present = tuple(selector for selector in REQUIRED_SELECTORS if selector in css)
    selectors_missing = tuple(selector for selector in REQUIRED_SELECTORS if selector not in css)
    color_count = len(set(re.findall(r"#[0-9a-fA-F]{6}", css)))
    return VisualAudit(
        selectors_present=selectors_present,
        selectors_missing=selectors_missing,
        color_count=color_count,
        has_gradient="gradient" in css.lower(),
    )


def visual_system_summary() -> str:
    surfaces = sum(1 for token in TOKENS if token.role == "surface")
    accents = sum(1 for token in TOKENS if token.role == "accent")
    statuses = sum(1 for token in TOKENS if token.role == "status")
    return f"{len(TOKENS)} tokens | {surfaces} surfaces | {accents} accents | {statuses} status colors"
