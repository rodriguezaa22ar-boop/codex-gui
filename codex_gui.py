#!/usr/bin/env python3
"""
Codex Control: a Linux workstation for the Codex CLI.

The app treats the terminal as the primary execution surface, because Codex is
still strongest as a TUI on Linux. When VTE GTK4 is available, Codex runs inside
the app. External Konsole remains available as a fallback and for detached work.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shlex
import sys
import time
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from codex_autopilot import (
    AutopilotPlan,
    AutopilotRecord,
    autopilot_detail,
    build_autopilot_plan,
    load_autopilot_records,
    remove_autopilot_record,
    save_autopilot_records,
    update_autopilot_record,
    upsert_autopilot_record,
    write_autopilot_artifacts,
)
from codex_brief import OperatorBrief, build_operator_brief
from codex_agents import (
    AgentExecutionRecord,
    AgentLane,
    AgentPlan,
    AgentResult,
    AgentRunRecord,
    build_agent_plan,
    collect_agent_results,
    lane_apply_script,
    lane_diff_script,
    lane_merge_script,
    load_agent_runs,
    new_execution_record,
    plan_markdown,
    prepare_worktree_script,
    record_from_plan,
    remove_agent_run,
    save_agent_runs,
    tail_text,
    update_execution_record,
    upsert_agent_run,
)
from codex_actions import ACTION_SPECS, ActionSpec, action_by_id, action_groups, rank_actions
from codex_context import ContextPacket, build_context_packet
from codex_devices import (
    DeviceRecord,
    DeviceProbe,
    MemoryItem,
    MeshReadinessReport,
    devices_from_tailscale_status_json,
    import_memory_text,
    local_agent_command,
    local_probe_command,
    load_devices,
    load_memory,
    merge_discovered_devices,
    memory_markdown,
    mesh_readiness_report,
    new_device,
    parse_probe_output,
    remote_agent_command,
    remote_file_sha256sum_command,
    remote_team_dir,
    remove_device,
    rsync_memory_command,
    rsync_project_command,
    rsync_team_package_command,
    rsync_team_chat_command,
    rsync_team_chat_pull_command,
    rsync_team_results_command,
    save_devices,
    save_memory,
    ssh_launch_command,
    ssh_mkdir_command,
    ssh_probe_command,
    ssh_test_command,
    slugify,
    tailscale_status_command,
    team_prompt,
    update_device_from_probe,
    upsert_device,
)
from codex_mission import MissionBlueprint, build_mission_blueprint
from codex_orchestration import LaunchPackage, build_launch_package
from codex_palette import (
    PaletteContext,
    PaletteHistoryRecord,
    PalettePreview,
    build_palette_preview,
    find_palette_record,
    load_palette_history,
    palette_history_detail,
    palette_history_log,
    record_palette_event,
    save_palette_history,
    update_palette_record,
)
from codex_project import ProjectCommand, ProjectSnapshot, inspect_project
from codex_quality import (
    QualityCheckResult,
    QualityPlan,
    QualityReport,
    build_quality_plan,
    load_quality_report,
    run_quality_plan,
    save_quality_report,
)
from codex_roadmap import Roadmap, RoadmapMilestone, build_roadmap
from codex_setup import SetupReport, build_setup_report
from codex_preflight import PreflightReport, build_preflight_report, codex_available
from codex_prompting import PromptVariant, enhance_prompt, model_variant_request, parse_model_variants
from codex_receipts import (
    CodexReceiptRecord,
    ReceiptCommandResult,
    ReceiptStampResult,
    atlas_binary,
    linked_receipt_chain,
    load_receipt_records,
    receipt_detail,
    replay_receipts,
    stamp_codex_receipt,
    verify_receipt,
)
from codex_runs import (
    CodexRunRecord,
    load_run_records,
    new_run_record,
    remove_run_record,
    run_detail,
    save_run_records,
    update_run_record,
    upsert_run_record,
)
from codex_sessions import (
    WorkspaceSession,
    load_sessions,
    new_session,
    remove_session,
    replace_session,
    save_sessions,
    touch_session,
    upsert_session,
)
from codex_team import (
    TeamBusTargetStatus,
    TeamBusReport,
    inspect_team_run,
    read_team_chat,
    load_bus_report,
    latest_team_run_dir,
    merge_team_chat_texts,
    role_profile_hint,
    team_operator_summary,
    team_role_for_device,
    team_run_dirs,
    write_role_bootstrap,
    write_bus_report,
    write_handoff_bus,
    write_team_summary,
    write_team_chat_entry,
)
from codex_visual import visual_system_css
from codex_workstation import (
    ActionFeedback,
    WorkstationLayout,
    action_feedback,
    layout_from_config,
    layout_to_config,
    layout_with_pane,
    layout_with_window,
    pane_position,
)

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte  # type: ignore  # noqa: E402
except (ImportError, ValueError):
    Vte = None  # type: ignore

warnings.filterwarnings("ignore", category=DeprecationWarning, message="Vte.Terminal.spawn_sync is deprecated")


APP_ID = "local.codex.control"
APP_NAME = "Codex Control"
CONFIG_DIR = Path.home() / ".config" / "codex-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_FILE = CONFIG_DIR / "sessions.json"
AGENT_RUNS_FILE = CONFIG_DIR / "agent-runs.json"
EXECUTIONS_DIR = CONFIG_DIR / "executions"
RECEIPTS_DIR = CONFIG_DIR / "receipts"
RUNS_FILE = CONFIG_DIR / "command-runs.json"
AUTOPILOT_DIR = CONFIG_DIR / "autopilot"
AUTOPILOT_RECORDS_FILE = CONFIG_DIR / "autopilot-runs.json"
QUALITY_FILE = CONFIG_DIR / "quality-report.json"
CONTEXT_FILE = CONFIG_DIR / "context-packet.md"
ROADMAP_FILE = CONFIG_DIR / "milestone-roadmap.md"
ORCHESTRATION_FILE = CONFIG_DIR / "launch-package.md"
PALETTE_HISTORY_FILE = CONFIG_DIR / "palette-history.json"
PALETTE_HISTORY_LOG = CONFIG_DIR / "palette-history.md"
DEVICES_FILE = CONFIG_DIR / "devices.json"
MEMORY_FILE = CONFIG_DIR / "memory.md"
TEAM_DIR = CONFIG_DIR / "team"
CODEX_HOME = Path.home() / ".codex"
CODEX_CONFIG = CODEX_HOME / "config.toml"
DEFAULT_PROJECT = Path.home() / "Projects"

NAV_ITEMS = (
    ("launch", "Workbench", "view-grid-symbolic"),
    ("palette", "Palette", "system-search-symbolic"),
    ("context", "Context", "text-x-generic-symbolic"),
    ("roadmap", "Roadmap", "view-list-symbolic"),
    ("orchestrate", "Orchestrate", "media-playback-start-symbolic"),
    ("mission", "Mission", "go-next-symbolic"),
    ("autopilot", "Autopilot", "system-run-symbolic"),
    ("mesh", "Mesh", "network-workgroup-symbolic"),
    ("dashboard", "Status", "applications-system-symbolic"),
    ("quality", "Quality", "tools-check-spelling-symbolic"),
    ("preflight", "Preflight", "checkbox-checked-symbolic"),
    ("ledger", "Ledger", "view-list-symbolic"),
    ("runs", "Runs", "system-run-symbolic"),
    ("monitor", "Monitor", "utilities-terminal-symbolic"),
    ("receipts", "Receipts", "text-x-generic-symbolic"),
    ("projects", "Projects", "folder-symbolic"),
    ("threads", "Threads", "mail-reply-all-symbolic"),
    ("git", "Git", "document-properties-symbolic"),
    ("config", "Config", "preferences-system-symbolic"),
    ("health", "Health", "security-high-symbolic"),
)

PRIMARY_NAV_PAGES = {
    "launch",
    "mesh",
    "quality",
    "mission",
    "runs",
    "monitor",
    "projects",
    "git",
}

MODELS = [
    ("config", "Config default"),
    ("gpt-5.5", "GPT-5.5 - best default"),
    ("gpt-5.3-codex-spark", "GPT-5.3 Codex Spark - Pro fast"),
    ("gpt-5.4-mini", "GPT-5.4 mini - fast scans"),
    ("gpt-5.4", "GPT-5.4 - compatibility"),
]

MESH_FILTER_OPTIONS = (
    ("all", "All"),
    ("ready", "Ready"),
    ("review", "Review"),
    ("blocked", "Blocked"),
    ("offline", "Offline"),
)

REASONING = [
    ("config", "Config default"),
    ("none", "None"),
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra high"),
]

SANDBOXES = [
    ("config", "Config default"),
    ("workspace-write", "Workspace write"),
    ("read-only", "Read only"),
    ("danger-full-access", "Full access"),
]

APPROVALS = [
    ("config", "Config default"),
    ("on-request", "Ask when needed"),
    ("never", "Never ask"),
    ("untrusted", "Ask for untrusted commands"),
]

WEB_MODES = [
    ("config", "Config default"),
    ("cached", "Cached search"),
    ("live", "Live search"),
    ("disabled", "Disabled"),
]

PERSONALITIES = [
    ("config", "Config default"),
    ("pragmatic", "Pragmatic"),
    ("friendly", "Friendly"),
    ("none", "None"),
]

ACTIONS = [
    ("interactive", "Interactive session"),
    ("exec", "One-shot exec"),
    ("resume", "Resume latest"),
    ("review", "Review changes"),
    ("doctor", "Health check"),
    ("update", "Update CLI"),
    ("login", "Sign in"),
]

PROMPTS = {
    "Best": (
        "Use $best-upfront-codex. Build the best practical version upfront: "
        "research current primary sources when needed, inspect the local code first, "
        "implement end to end, polish the user-facing result, and validate before finishing."
    ),
    "Explore": (
        "Tell me about this project. Identify the stack, main entry points, how "
        "to run it, and the highest-risk areas. Do not edit files."
    ),
    "Build": (
        "Implement the requested change end to end. Read the existing code first, "
        "keep changes scoped, run relevant checks, and summarize exactly what changed."
    ),
    "Fix": (
        "Find and fix the bug with the smallest high-confidence change. Add or run "
        "a focused verification step before finishing."
    ),
    "Review": (
        "Review the current uncommitted changes. Prioritize bugs, regressions, "
        "security issues, and missing tests. Do not modify files."
    ),
    "UI Polish": (
        "Polish the UI like a production app. Preserve existing patterns, verify "
        "responsive layout, and avoid unrelated refactors."
    ),
    "Plan": (
        "Read the project and produce a concrete implementation plan. Do not edit "
        "files until I approve the plan."
    ),
}

PROFILE_TEMPLATES = {
    "maximum-power": """model = "gpt-5.5"
model_reasoning_effort = "xhigh"
approval_policy = "never"
sandbox_mode = "danger-full-access"
web_search = "cached"
personality = "pragmatic"

[shell_environment_policy]
inherit = "all"
""",
    "pro-default": """model = "gpt-5.5"
model_reasoning_effort = "xhigh"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
web_search = "cached"
personality = "pragmatic"
""",
    "spark-fast": """model = "gpt-5.3-codex-spark"
model_reasoning_effort = "low"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
web_search = "cached"
personality = "pragmatic"
""",
    "safe-explore": """model = "gpt-5.5"
model_reasoning_effort = "high"
approval_policy = "on-request"
sandbox_mode = "read-only"
web_search = "cached"
personality = "pragmatic"
""",
    "deep-review": """model = "gpt-5.5"
model_reasoning_effort = "xhigh"
approval_policy = "on-request"
sandbox_mode = "read-only"
web_search = "cached"
personality = "pragmatic"
""",
    "autonomous-workspace": """model = "gpt-5.5"
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "cached"
personality = "pragmatic"
""",
}

CSS = """
window {
  background: #080a0f;
  color: #f4f7f6;
}

.topbar {
  background: #0c1118;
  color: #f8fbfa;
  padding: 14px 18px;
  border-bottom: 1px solid #a9792f;
}

.brand-badge {
  background: #f0b34d;
  color: #101216;
  border-radius: 8px;
  padding: 6px 8px;
  font-weight: 800;
}

.app-title {
  font-size: 21px;
  font-weight: 700;
}

.subtitle {
  color: #adb8c3;
}

.nav {
  background: #080d12;
  border-right: 1px solid #26313c;
  padding: 10px 8px;
}

.nav row {
  color: #dce5e8;
  border-radius: 6px;
  margin: 3px 0;
  padding: 8px 10px;
}

.nav row:selected {
  background: #207363;
  color: #ffffff;
}

.nav label {
  color: #dce5e8;
}

.nav row:selected label {
  color: #ffffff;
}

.page {
  padding: 14px;
  background: #0a0d12;
}

.panel {
  background: #10161d;
  color: #eef4f2;
  border: 1px solid #2b3744;
  border-radius: 8px;
  padding: 12px;
}

.workbench-panel {
  background: #111a1e;
}

.section {
  color: #d8a85d;
  font-weight: 700;
  font-size: 13px;
}

.muted {
  color: #aeb9c1;
}

.status-pill {
  background: #dff5ee;
  color: #10251f;
  border-radius: 999px;
  padding: 8px 12px;
  font-weight: 600;
  border: 1px solid #a7d7cb;
}

.stat-strip {
  background: #10161d;
  border: 1px solid #2a3946;
  border-radius: 8px;
  padding: 8px;
}

.stat-card {
  background: #0b1118;
  color: #edf6f3;
  border: 1px solid #283844;
  border-radius: 7px;
  padding: 8px 10px;
}

.stat-value {
  font-size: 14px;
  font-weight: 700;
}

.power-banner {
  background: #131920;
  border: 1px solid #4b3b21;
  border-radius: 8px;
  padding: 14px;
}

.power-title {
  color: #f5f2e9;
  font-size: 19px;
  font-weight: 800;
}

.power-subtitle {
  color: #c2cbd1;
}

.mode-pill {
  background: #241b10;
  color: #f6c16b;
  border: 1px solid #8b6326;
  border-radius: 999px;
  padding: 7px 10px;
  font-weight: 700;
}

.chip {
  background: #151d26;
  color: #e7edf0;
  border: 1px solid #354554;
  border-radius: 999px;
  padding: 6px 9px;
}

.chip-strong {
  background: #12332d;
  color: #a8f0dd;
  border-color: #287565;
}

.chip-danger {
  background: #321c19;
  color: #ffb2a8;
  border-color: #74423b;
}

.warn {
  background: #fff0cc;
  color: #5a3b00;
}

.bad {
  background: #ffe0de;
  color: #79221e;
}

.primary {
  background: #218a75;
  color: #ffffff;
  border-color: #35aa91;
  font-weight: 700;
}

.primary:hover {
  background: #2b9e87;
}

.secondary {
  background: #181e27;
  color: #e8eef0;
  border-color: #35414d;
}

.accent {
  background: #2d2418;
  color: #f6cf86;
  border-color: #7b5a2a;
  font-weight: 700;
}

.code-view {
  background: #05080d;
  color: #eef8f6;
  border-radius: 8px;
  padding: 8px;
  font-family: monospace;
}

.terminal-frame {
  background: #020409;
  color: #f2f8f6;
  border: 1px solid #2f4654;
  border-radius: 8px;
}

.terminal-panel {
  background: #091015;
  border-color: #314a59;
}

.composer {
  background: #10161d;
  border-color: #334452;
}

.composer-view {
  background: #0a1015;
  color: #eef8f6;
  border: 1px solid #293947;
  border-radius: 8px;
}

.side-rail {
  background: #0c1118;
}

.power-controls {
  background: #10161d;
  border-color: #3a4a57;
}

.quick-grid button {
  min-height: 34px;
}

.command-preview {
  background: #080c12;
  border-color: #39495a;
}

.prompt-lab {
  background: #10161d;
  border-color: #3b4c5b;
}

.prompt-option {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 9px;
}

.prompt-option:selected {
  background: #173a34;
  border-color: #38a58d;
}

.prompt-option-title {
  color: #f4f7f6;
  font-weight: 700;
}

.prompt-option-summary {
  color: #b6c2ca;
}

.project-intel {
  background: #10161d;
  border-color: #3f5362;
}

.project-intel-value {
  color: #edf5f3;
  font-weight: 700;
}

.project-command {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.session-workspace {
  background: #10161d;
  border-color: #425668;
}

.session-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.session-scroll, .session-list {
  background: #0b1118;
}

.session-row:selected {
  background: #173a34;
  border-color: #38a58d;
}

.session-title {
  color: #f4f7f6;
  font-weight: 700;
}

.session-meta {
  color: #aeb9c1;
}

.agent-studio {
  background: #10161d;
  border-color: #4a5364;
}

.agent-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.agent-scroll, .agent-list {
  background: #0b1118;
}

.agent-row:selected {
  background: #172f3d;
  border-color: #5794b8;
}

.agent-role {
  color: #f4f7f6;
  font-weight: 700;
}

.agent-objective {
  color: #b6c2ca;
}

.result-console {
  background: #10161d;
  border-color: #4a5364;
}

.result-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.result-row:selected {
  background: #24301e;
  border-color: #8aab5e;
}

.result-title {
  color: #f4f7f6;
  font-weight: 700;
}

.result-meta {
  color: #b6c2ca;
}

.result-scroll, .result-list {
  background: #0b1118;
}

.run-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 10px;
}

.run-row:selected {
  background: #173a34;
  border-color: #38a58d;
}

.run-title {
  color: #f4f7f6;
  font-weight: 700;
}

.run-meta {
  color: #b6c2ca;
}

.run-scroll, .run-list {
  background: #0b1118;
}

.execution-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 10px;
}

.execution-row:selected {
  background: #172f3d;
  border-color: #5794b8;
}

.execution-title {
  color: #f4f7f6;
  font-weight: 700;
}

.execution-meta {
  color: #b6c2ca;
}

.execution-scroll, .execution-list {
  background: #0b1118;
}

.receipt-vault {
  background: #10161d;
  border-color: #53624a;
}

.receipt-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.receipt-row:selected {
  background: #2a331e;
  border-color: #97b96a;
}

.receipt-title {
  color: #f4f7f6;
  font-weight: 700;
}

.receipt-meta {
  color: #b6c2ca;
}

.receipt-scroll, .receipt-list {
  background: #0b1118;
}

.run-ledger {
  background: #10161d;
  border-color: #555f72;
}

.preflight-panel {
  background: #10161d;
  border-color: #685936;
}

.mission-architect {
  background: #111821;
  border-color: #8a6428;
}

.mission-title {
  color: #f5f2e9;
  font-size: 17px;
  font-weight: 800;
}

.mission-detail {
  color: #b8c3ca;
}

.mission-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.mission-row:selected {
  background: #2b2618;
  border-color: #b68637;
}

.mission-row-title {
  color: #f4f7f6;
  font-weight: 700;
}

.mission-scroll, .mission-list {
  background: #0b1118;
}

.autopilot-panel {
  background: #111821;
  border-color: #87632d;
}

.autopilot-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 9px;
}

.autopilot-row:selected {
  background: #2b2618;
  border-color: #b68637;
}

.autopilot-title {
  color: #f5f2e9;
  font-weight: 800;
}

.autopilot-meta {
  color: #b8c3ca;
}

.autopilot-scroll, .autopilot-list {
  background: #0b1118;
}

.preflight-title {
  color: #f5f2e9;
  font-size: 16px;
  font-weight: 800;
}

.preflight-check-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.preflight-check-row:selected {
  background: #2b2618;
  border-color: #b68637;
}

.preflight-check-title {
  color: #f4f7f6;
  font-weight: 700;
}

.preflight-check-detail {
  color: #b6c2ca;
}

.preflight-scroll, .preflight-list {
  background: #0b1118;
}

.command-run-row {
  background: #111923;
  border: 1px solid #314353;
  border-radius: 7px;
  padding: 8px;
}

.command-run-row:selected {
  background: #172f3d;
  border-color: #5794b8;
}

.command-run-title {
  color: #f4f7f6;
  font-weight: 700;
}

.command-run-meta {
  color: #b6c2ca;
}

.command-run-scroll, .command-run-list {
  background: #0b1118;
}

entry, textview, dropdown, expander {
  color: #eef8f6;
  background: #131922;
}

.row-title {
  font-weight: 700;
}

.danger-text {
  color: #ffb2a8;
  font-weight: 700;
}

.topbar {
  background: #090d13;
  padding: 18px 18px;
  border-bottom: 1px solid #765528;
}

.brand-badge {
  background: #f0b34d;
  color: #090d13;
  border-radius: 8px;
  padding: 8px 10px;
}

.nav {
  background: #070b10;
  border-right: 1px solid #1c2733;
  padding: 12px 8px;
}

.nav row {
  border-radius: 8px;
  margin: 4px 0;
  padding: 10px 14px;
}

.nav row:selected {
  background: #227e6d;
}

.page {
  background: #080c12;
  padding: 16px;
}

.panel {
  background: #0f151d;
  border: 1px solid #273646;
  border-radius: 8px;
  padding: 12px;
}

.operator-console {
  background: #101720;
  border: 1px solid #8a6428;
  border-radius: 8px;
  padding: 16px;
}

.operator-title {
  color: #f7f4ed;
  font-size: 22px;
  font-weight: 800;
}

.operator-subtitle {
  color: #bec9d0;
}

.operator-card {
  background: #0b1118;
  border: 1px solid #2d4050;
  border-radius: 8px;
  padding: 10px 12px;
}

.operator-card-value {
  color: #f5f8f6;
  font-size: 15px;
  font-weight: 800;
}

.operator-card-detail {
  color: #aebbc4;
}

.mission-architect, .autopilot-panel {
  background: #101720;
}

.terminal-panel {
  background: #0d141c;
  border-color: #355064;
  padding: 12px;
}

.terminal-frame {
  background: #010306;
  border: 1px solid #30495d;
  border-radius: 6px;
}

.composer {
  background: #0f151d;
  border-color: #304253;
}

.nav-kicker {
  color: #6f8793;
  font-size: 11px;
  font-weight: 800;
}

.nav-list {
  background: transparent;
}

.nav-row {
  min-height: 42px;
}

.nav-row image {
  color: #91a4ad;
}

.nav row:selected image {
  color: #ffffff;
}

.operator-card.signal-ok {
  border-color: #2c7667;
  background: #0d1819;
}

.operator-card.signal-review {
  border-color: #7d5c28;
  background: #12161c;
}

.operator-card.signal-bad {
  border-color: #7d423c;
  background: #181314;
}

.quality-gate {
  background: #0f171b;
  border-color: #31576a;
}

.quality-title {
  color: #f4f7f6;
  font-size: 18px;
  font-weight: 800;
}

.quality-row {
  background: #0b1118;
  border: 1px solid #263947;
  border-radius: 8px;
  margin: 4px;
  padding: 9px;
}

.quality-check-title {
  color: #f2f8f6;
  font-weight: 700;
}

.quality-check-detail {
  color: #aebbc4;
}

.quality-scroll, .quality-list {
  background: #0b1118;
}

.action-palette {
  background: #101720;
  border-color: #35506b;
}

.action-detail-panel {
  background: #0f151d;
  border-color: #304253;
}

.action-row {
  background: #0b1118;
  border: 1px solid #263947;
  border-radius: 8px;
  margin: 4px;
  padding: 9px;
}

.action-row:selected {
  background: #122d35;
  border-color: #3f7f91;
}

.action-title {
  color: #f4f7f6;
  font-weight: 800;
}

.action-detail {
  color: #aebbc4;
}

.action-scroll, .action-list {
  background: #0b1118;
}

.context-packet {
  background: #10171d;
  border-color: #4f6b78;
}

.context-title {
  color: #f4f7f6;
  font-size: 18px;
  font-weight: 800;
}

.context-detail {
  color: #b8c6cc;
}

.context-row {
  background: #0b1118;
  border: 1px solid #263947;
  border-radius: 8px;
  margin: 4px;
  padding: 9px;
}

.context-row:selected {
  background: #142d35;
  border-color: #5c93a7;
}

.context-section-title {
  color: #f4f7f6;
  font-weight: 800;
}

.context-scroll, .context-list {
  background: #0b1118;
}

.roadmap-panel {
  background: #10161f;
  border-color: #78633a;
}

.roadmap-title {
  color: #f6f1e8;
  font-size: 18px;
  font-weight: 800;
}

.roadmap-detail {
  color: #bdc8cf;
}

.roadmap-row {
  background: #0b1118;
  border: 1px solid #314353;
  border-radius: 8px;
  margin: 4px;
  padding: 9px;
}

.roadmap-row:selected {
  background: #2b2618;
  border-color: #b68637;
}

.roadmap-row-title {
  color: #f4f7f6;
  font-weight: 800;
}

.roadmap-scroll, .roadmap-list {
  background: #0b1118;
}

.orchestration-panel {
  background: #101820;
  border-color: #2f7f75;
}

.orchestration-title {
  color: #f4f7f6;
  font-size: 18px;
  font-weight: 800;
}

.orchestration-detail {
  color: #b8c6cc;
}

.orchestration-row {
  background: #0b1118;
  border: 1px solid #2a4650;
  border-radius: 8px;
  margin: 4px;
  padding: 9px;
}

.orchestration-row:selected {
  background: #12332d;
  border-color: #38a58d;
}

.orchestration-row-title {
  color: #f4f7f6;
  font-weight: 800;
}

.orchestration-scroll, .orchestration-list {
  background: #0b1118;
}
"""


@dataclass
class ProjectInfo:
    path: str
    name: str
    is_git: bool
    branch: str
    dirty: int
    untracked: int
    remote: str


@dataclass
class ThreadInfo:
    id: str
    title: str
    cwd: str
    model: str
    reasoning: str
    tokens: int
    updated: int
    archived: bool
    preview: str


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run_cmd(args: list[str], cwd: str | None = None, timeout: int = 12) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def which_codex() -> str:
    candidates = [Path.home() / ".local" / "bin" / "codex", shutil.which("codex")]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
    return "codex"


def first_terminal() -> tuple[str, str] | None:
    for binary, kind in [
        ("konsole", "konsole"),
        ("kgx", "kgx"),
        ("gnome-terminal", "gnome-terminal"),
        ("xterm", "xterm"),
    ]:
        path = shutil.which(binary)
        if path:
            return path, kind
    return None


def shell_join(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def human_time(value: int | None) -> str:
    if not value:
        return "unknown"
    seconds = value / 1000 if value > 10_000_000_000 else value
    try:
        return dt.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return str(value)


def short_id(value: str, width: int = 8) -> str:
    return value[:width] if value else ""


def ensure_dir(path: str) -> str:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def git_root(path: str) -> str | None:
    try:
        result = run_cmd(["git", "-C", path, "rev-parse", "--show-toplevel"], timeout=6)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def git_project_info(path: str) -> ProjectInfo:
    p = Path(path).expanduser()
    name = p.name or str(p)
    root = git_root(str(p))
    if not root:
        return ProjectInfo(str(p), name, False, "", 0, 0, "")
    branch = run_cmd(["git", "-C", root, "branch", "--show-current"], timeout=6).stdout.strip()
    if not branch:
        branch = "detached"
    status = run_cmd(["git", "-C", root, "status", "--porcelain=v1"], timeout=8).stdout.splitlines()
    dirty = sum(1 for line in status if not line.startswith("??"))
    untracked = sum(1 for line in status if line.startswith("??"))
    remote = run_cmd(["git", "-C", root, "remote", "get-url", "origin"], timeout=6).stdout.strip()
    return ProjectInfo(root, Path(root).name, True, branch, dirty, untracked, remote)


def discover_git_repos() -> list[str]:
    roots: set[str] = set()
    for base in [DEFAULT_PROJECT, Path.home()]:
        if not base.exists():
            continue
        max_depth = 5 if base == DEFAULT_PROJECT else 2
        try:
            result = run_cmd(
                ["find", str(base), "-maxdepth", str(max_depth), "-type", "d", "-name", ".git", "-print"],
                timeout=12,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in result.stdout.splitlines():
            repo = str(Path(line).parent)
            if ".codex" not in repo:
                roots.add(repo)
    return sorted(roots)


def read_threads(search: str = "") -> list[ThreadInfo]:
    db = CODEX_HOME / "state_5.sqlite"
    if not db.exists():
        return []
    query = """
        select id, title, cwd, model, reasoning_effort, tokens_used, updated_at,
               archived, preview
        from threads
        order by updated_at desc
        limit 300
    """
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        rows = con.execute(query).fetchall()
        con.close()
    except sqlite3.Error:
        return []
    needle = search.strip().lower()
    items: list[ThreadInfo] = []
    for row in rows:
        info = ThreadInfo(
            id=row["id"] or "",
            title=row["title"] or "(untitled)",
            cwd=row["cwd"] or "",
            model=row["model"] or "",
            reasoning=row["reasoning_effort"] or "",
            tokens=int(row["tokens_used"] or 0),
            updated=int(row["updated_at"] or 0),
            archived=bool(row["archived"]),
            preview=row["preview"] or "",
        )
        haystack = " ".join([info.id, info.title, info.cwd, info.preview]).lower()
        if not needle or needle in haystack:
            items.append(info)
    return items


def profile_names() -> list[str]:
    names = []
    for path in sorted(CODEX_HOME.glob("*.config.toml")):
        names.append(path.name.removesuffix(".config.toml"))
    return names


class CodexControl(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.config = load_json(CONFIG_FILE)
        self.layout_state: WorkstationLayout = layout_from_config(self.config)
        self.codex_bin = which_codex()
        self.mesh_filter_mode = self.config.get("mesh_filter_mode", "all")
        if self.mesh_filter_mode not in {"all", "ready", "review", "blocked", "offline"}:
            self.mesh_filter_mode = "all"
        self.mesh_team_only = bool(self.config.get("mesh_team_only", False))
        self.focus_mode = bool(self.config.get("focus_mode", False))
        self.mesh_live_refresh = bool(self.config.get("mesh_live_refresh", True))
        try:
            self.mesh_live_refresh_seconds = max(10, min(300, int(self.config.get("mesh_live_refresh_seconds", 30))))
        except (TypeError, ValueError):
            self.mesh_live_refresh_seconds = 30
        self.mesh_live_refresh_busy = False
        self.mesh_live_refresh_timer_id = 0
        self.window: Gtk.ApplicationWindow | None = None
        self.status_label: Gtk.Label | None = None
        self.stack: Gtk.Stack | None = None
        self.paned_widgets: dict[str, Gtk.Paned] = {}
        self.command_buffer: Gtk.TextBuffer | None = None
        self.prompt_buffer: Gtk.TextBuffer | None = None
        self.config_buffer: Gtk.TextBuffer | None = None
        self.health_buffer: Gtk.TextBuffer | None = None
        self.headless_buffer: Gtk.TextBuffer | None = None
        self.git_buffer: Gtk.TextBuffer | None = None
        self.mesh_detail_buffer: Gtk.TextBuffer | None = None
        self.memory_buffer: Gtk.TextBuffer | None = None
        self.mesh_team_chat_buffer: Gtk.TextBuffer | None = None
        self.terminal: Any | None = None
        self.headless_proc: subprocess.Popen[str] | None = None
        self.projects: list[ProjectInfo] = []
        self.selected_thread: ThreadInfo | None = None
        self.prompt_variants: list[PromptVariant] = []
        self.selected_prompt_variant: PromptVariant | None = None
        self.project_snapshot: ProjectSnapshot | None = None
        self.ai_prompt_busy = False
        self.sessions: list[WorkspaceSession] = load_sessions(SESSIONS_FILE)
        self.selected_workspace_session: WorkspaceSession | None = self.sessions[0] if self.sessions else None
        self.agent_plan: AgentPlan | None = None
        self.selected_agent_lane: AgentLane | None = None
        self.agent_results: list[AgentResult] = []
        self.selected_agent_result: AgentResult | None = None
        self.agent_runs: list[AgentRunRecord] = load_agent_runs(AGENT_RUNS_FILE)
        self.selected_agent_run: AgentRunRecord | None = self.agent_runs[0] if self.agent_runs else None
        self.agent_executions: list[AgentExecutionRecord] = []
        self.selected_agent_execution: AgentExecutionRecord | None = None
        self.agent_execution_procs: dict[str, subprocess.Popen[str]] = {}
        self.receipt_records: list[CodexReceiptRecord] = load_receipt_records(RECEIPTS_DIR)
        self.selected_receipt: CodexReceiptRecord | None = self.receipt_records[0] if self.receipt_records else None
        self.receipt_last_output = ""
        self.rendering_receipts = False
        self.command_runs: list[CodexRunRecord] = load_run_records(RUNS_FILE)
        self.selected_command_run: CodexRunRecord | None = self.command_runs[0] if self.command_runs else None
        self.rendering_command_runs = False
        self.preflight_report: PreflightReport | None = None
        self.quality_plan: QualityPlan | None = None
        self.quality_report: QualityReport | None = load_quality_report(QUALITY_FILE)
        self.quality_running = False
        self.context_packet: ContextPacket | None = None
        self.roadmap: Roadmap | None = None
        self.selected_roadmap_milestone: RoadmapMilestone | None = None
        self.rendering_roadmap = False
        self.launch_package: LaunchPackage | None = None
        self.action_query = ""
        self.selected_action: ActionSpec | None = None
        self.rendering_actions = False
        self.last_action_feedback: ActionFeedback = action_feedback("app.ready", "Action Console", "App", "ready", "Workbench ready")
        self.last_action_preview: PalettePreview | None = None
        self.palette_history: list[PaletteHistoryRecord] = load_palette_history(PALETTE_HISTORY_FILE)
        self.selected_palette_record: PaletteHistoryRecord | None = self.palette_history[0] if self.palette_history else None
        self.devices: tuple[DeviceRecord, ...] = load_devices(DEVICES_FILE)
        self.selected_device: DeviceRecord | None = self.devices[0] if self.devices else None
        self.memory_items: tuple[MemoryItem, ...] = load_memory(MEMORY_FILE)
        self.mesh_probe_records: dict[str, DeviceProbe] = {}
        self._mesh_filter_toggling = False
        self.mesh_team_run_id = ""
        self.mesh_team_dir: Path | None = None
        self.mesh_team_assignments: list[dict[str, str]] = []
        self.mesh_team_last_bus_sent = 0
        self.mesh_team_last_bus_failures: list[str] = []
        self.mesh_team_last_bus_path: Path | None = None
        self.mesh_team_last_bus_report: TeamBusReport | None = None
        latest_team_dir = latest_team_run_dir(TEAM_DIR)
        if latest_team_dir is not None:
            latest_status = inspect_team_run(latest_team_dir)
            self.mesh_team_run_id = latest_status.run_id
            self.mesh_team_dir = latest_team_dir
            self.mesh_team_assignments = [dict(item) for item in latest_status.assignments]
            self.mesh_team_last_bus_report = load_bus_report(latest_team_dir)
        self.mission_blueprint: MissionBlueprint | None = None
        self.autopilot_plan: AutopilotPlan | None = None
        self.autopilot_prompt = ""
        self.autopilot_records: list[AutopilotRecord] = load_autopilot_records(AUTOPILOT_RECORDS_FILE)
        self.selected_autopilot_record: AutopilotRecord | None = self.autopilot_records[0] if self.autopilot_records else None
        self.rendering_autopilot = False
        self.autopilot_procs: dict[str, subprocess.Popen[str]] = {}
        self.autopilot_run_ids: dict[str, str] = {}
        self.operator_brief: OperatorBrief | None = None
        self.operator_signal_labels: list[tuple[Gtk.Label, Gtk.Label, Gtk.Label]] = []
        self.operator_signal_cards: list[Gtk.Widget] = []
        self.nav_rows: dict[str, Gtk.ListBoxRow] = {}
        self.nav_lists: list[Gtk.ListBox] = []
        self.sidebar_widget: Gtk.Widget | None = None
        self.focus_button: Gtk.Button | None = None
        self.health_summary: dict[str, Any] = {}
        self.headless_run_id = ""
        self.execution_run_ids: dict[str, str] = {}

    def do_activate(self) -> None:
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        self.install_css()
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title(APP_NAME)
        self.window.set_default_size(self.layout_state.window_width, self.layout_state.window_height)
        self.window.connect("close-request", self.on_close)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(self.build_topbar())

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.sidebar_widget = self.build_sidebar()
        body.append(self.sidebar_widget)
        body.append(self.stack)
        root.append(body)

        self.stack.add_titled(self.build_launch_page(), "launch", "Workbench")
        self.stack.add_titled(self.build_palette_page(), "palette", "Palette")
        self.stack.add_titled(self.build_context_page(), "context", "Context")
        self.stack.add_titled(self.build_roadmap_page(), "roadmap", "Roadmap")
        self.stack.add_titled(self.build_orchestration_page(), "orchestrate", "Orchestrate")
        self.stack.add_titled(self.build_mission_page(), "mission", "Mission")
        self.stack.add_titled(self.build_autopilot_page(), "autopilot", "Autopilot")
        self.stack.add_titled(self.build_mesh_page(), "mesh", "Mesh")
        self.stack.add_titled(self.build_dashboard_page(), "dashboard", "Status")
        self.stack.add_titled(self.build_quality_page(), "quality", "Quality")
        self.stack.add_titled(self.build_preflight_page(), "preflight", "Preflight")
        self.stack.add_titled(self.build_command_ledger_page(), "ledger", "Ledger")
        self.stack.add_titled(self.build_agent_runs_page(), "runs", "Runs")
        self.stack.add_titled(self.build_execution_monitor_page(), "monitor", "Monitor")
        self.stack.add_titled(self.build_receipts_page(), "receipts", "Receipts")
        self.stack.add_titled(self.build_projects_page(), "projects", "Projects")
        self.stack.add_titled(self.build_threads_page(), "threads", "Threads")
        self.stack.add_titled(self.build_git_page(), "git", "Git")
        self.stack.add_titled(self.build_config_page(), "config", "Config")
        self.stack.add_titled(self.build_health_page(), "health", "Health")

        self.window.set_child(root)
        self.window.present()
        if self.layout_state.start_maximized:
            self.window.maximize()
        self.show_page("launch")
        self.install_actions()
        self.refresh_all()
        self.apply_focus_mode()
        self.ensure_mesh_live_refresh_timer()
        GLib.idle_add(self.on_run_setup_check)
        self.save_current_state()

    def install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data((CSS + "\n" + visual_system_css()).encode("utf-8"))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def build_sidebar(self) -> Gtk.Widget:
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        nav.add_css_class("nav")
        nav.set_size_request(self.layout_state.sidebar_width, -1)

        header = Gtk.Label(label="CONTROL", xalign=0)
        header.add_css_class("nav-kicker")
        header.set_margin_start(14)
        header.set_margin_end(14)
        nav.append(header)

        self.nav_list = Gtk.ListBox()
        self.nav_list.add_css_class("nav-list")
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_rows = {}
        self.nav_lists = [self.nav_list]
        for page_name, title, icon_name in NAV_ITEMS:
            if page_name not in PRIMARY_NAV_PAGES:
                continue
            row = self.build_nav_row(page_name, title, icon_name)
            self.nav_list.append(row)
            self.nav_rows[page_name] = row
        self.nav_list.connect("row-selected", self.on_nav_selected)
        nav.append(self.nav_list)

        more = Gtk.Expander(label="More")
        more.add_css_class("nav-more")
        self.nav_more_expander = more
        secondary_list = Gtk.ListBox()
        secondary_list.add_css_class("nav-list")
        secondary_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_lists.append(secondary_list)
        for page_name, title, icon_name in NAV_ITEMS:
            if page_name in PRIMARY_NAV_PAGES:
                continue
            row = self.build_nav_row(page_name, title, icon_name)
            secondary_list.append(row)
            self.nav_rows[page_name] = row
        secondary_list.connect("row-selected", self.on_nav_selected)
        more.set_child(secondary_list)
        nav.append(more)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        nav.append(spacer)
        return nav

    def build_nav_row(self, page_name: str, title: str, icon_name: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.page_name = page_name
        row.add_css_class("nav-row")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.set_valign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.add_css_class("nav-icon")
        image.set_pixel_size(16)
        label = Gtk.Label(label=title, xalign=0)
        label.set_hexpand(True)
        content.append(image)
        content.append(label)
        row.set_child(content)
        return row

    def on_nav_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is not None:
            self.show_page(getattr(row, "page_name", "launch"))

    def make_button(self, label: str, icon_name: str | None = None) -> Gtk.Button:
        button = Gtk.Button()
        if icon_name is None:
            button.set_label(label)
            return button
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        content.set_valign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(15)
        text = Gtk.Label(label=label)
        button.text_label = text
        content.append(image)
        content.append(text)
        button.set_child(content)
        return button

    def set_button_text(self, button: Gtk.Button, label: str) -> None:
        text_label = getattr(button, "text_label", None)
        if text_label is not None:
            text_label.set_text(label)
        else:
            button.set_label(label)

    def apply_focus_mode(self) -> None:
        if self.sidebar_widget is not None:
            self.sidebar_widget.set_visible(not self.focus_mode)
        if self.focus_button is not None:
            self.set_button_text(self.focus_button, "Exit Focus" if self.focus_mode else "Focus")
            self.focus_button.remove_css_class("primary")
            self.focus_button.remove_css_class("secondary")
            self.focus_button.add_css_class("primary" if self.focus_mode else "secondary")

    def on_toggle_focus_mode(self, _button: Gtk.Button) -> None:
        self.focus_mode = not self.focus_mode
        self.apply_focus_mode()
        self.save_current_state()
        self.set_status("Focus mode enabled" if self.focus_mode else "Focus mode disabled")

    def install_actions(self) -> None:
        actions = [
            ("run", lambda *_args: self.on_run_embedded(Gtk.Button())),
            ("detach", lambda *_args: self.on_run_external(Gtk.Button())),
            ("copy-command", lambda *_args: self.on_copy_command(Gtk.Button())),
            ("refresh", lambda *_args: self.refresh_all()),
            ("focus-prompt", lambda *_args: self.focus_prompt()),
            ("focus-project", lambda *_args: self.focus_project()),
            ("show-palette", lambda *_args: self.show_palette()),
            ("show-workbench", lambda *_args: self.show_page("launch")),
            ("show-context", lambda *_args: self.show_context_page()),
            ("show-roadmap", lambda *_args: self.show_roadmap_page()),
            ("show-orchestrate", lambda *_args: self.show_orchestration_page()),
            ("show-mission", lambda *_args: self.show_page("mission")),
            ("show-autopilot", lambda *_args: self.show_page("autopilot")),
            ("show-mesh", lambda *_args: self.show_page("mesh")),
            ("mesh-discover", lambda *_args: self.on_discover_tailnet(Gtk.Button())),
            ("mesh-check", lambda *_args: self.on_check_fleet(Gtk.Button())),
            ("mesh-latest", lambda *_args: self.on_load_latest_mesh_team(Gtk.Button())),
            ("mesh-prepare-team", lambda *_args: self.on_prepare_mesh_team(Gtk.Button())),
            ("mesh-launch-team", lambda *_args: self.on_launch_mesh_team(Gtk.Button())),
            ("mesh-collect-team", lambda *_args: self.on_collect_mesh_team(Gtk.Button())),
            ("mesh-sync-bus", lambda *_args: self.on_sync_mesh_handoff_bus(Gtk.Button())),
            ("mesh-retry-bus", lambda *_args: self.on_retry_mesh_handoff_bus(Gtk.Button())),
            ("mesh-verify-bus", lambda *_args: self.on_verify_mesh_bus_integrity(Gtk.Button())),
            ("mesh-sync-chat", lambda *_args: self.on_sync_team_chat(Gtk.Button())),
            ("mesh-refresh-chat", lambda *_args: self.on_refresh_team_chat(Gtk.Button())),
            ("mesh-copy-chat", lambda *_args: self.on_copy_team_chat(Gtk.Button())),
            ("mesh-copy-bus-report", lambda *_args: self.on_copy_mesh_team_bus_report(Gtk.Button())),
            ("mesh-copy-role-bootstrap", lambda *_args: self.on_copy_role_bootstrap(Gtk.Button())),
            ("mesh-summary", lambda *_args: self.on_copy_mesh_team_summary(Gtk.Button())),
            ("mesh-open", lambda *_args: self.on_open_mesh_team(Gtk.Button())),
            ("show-preflight", lambda *_args: self.show_page("preflight")),
            ("show-quality", lambda *_args: self.show_page("quality")),
            ("show-runs", lambda *_args: self.show_page("runs")),
            ("show-monitor", lambda *_args: self.show_page("monitor")),
            ("toggle-focus", lambda *_args: self.on_toggle_focus_mode(Gtk.Button())),
        ]
        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("app.run", ["<Control>Return"])
        self.set_accels_for_action("app.detach", ["<Control><Shift>Return"])
        self.set_accels_for_action("app.copy-command", ["<Control><Shift>C"])
        self.set_accels_for_action("app.refresh", ["F5"])
        self.set_accels_for_action("app.show-palette", ["<Control>K"])
        self.set_accels_for_action("app.show-context", ["<Control>J"])
        self.set_accels_for_action("app.show-roadmap", ["<Control><Shift>M"])
        self.set_accels_for_action("app.show-orchestrate", ["<Control><Shift>O"])
        self.set_accels_for_action("app.show-mesh", ["<Control><Shift>D"])
        self.set_accels_for_action("app.toggle-focus", ["<Control><Shift>F"])
        self.set_accels_for_action("app.focus-prompt", ["<Control>L"])
        self.set_accels_for_action("app.focus-project", ["<Control><Shift>L"])

    def build_topbar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        bar.add_css_class("topbar")
        badge = Gtk.Label(label="C>")
        badge.add_css_class("brand-badge")
        badge.set_valign(Gtk.Align.CENTER)
        bar.append(badge)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=APP_NAME, xalign=0)
        title.add_css_class("app-title")
        subtitle = Gtk.Label(label="Maximum-power local workstation", xalign=0)
        subtitle.add_css_class("subtitle")
        title_box.append(title)
        title_box.append(subtitle)
        title_box.set_hexpand(True)
        bar.append(title_box)

        refresh = self.make_button("Refresh", "view-refresh-symbolic")
        refresh.connect("clicked", lambda _b: self.refresh_all())
        self.focus_button = self.make_button("Focus", "view-fullscreen-symbolic")
        self.focus_button.add_css_class("secondary")
        self.focus_button.connect("clicked", self.on_toggle_focus_mode)
        launch = self.make_button("Run", "media-playback-start-symbolic")
        launch.add_css_class("primary")
        launch.connect("clicked", self.on_run_embedded)
        self.status_label = Gtk.Label(label="Starting...")
        self.status_label.add_css_class("status-pill")
        bar.append(refresh)
        bar.append(self.focus_button)
        bar.append(launch)
        bar.append(self.status_label)
        return bar

    def page_box(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.add_css_class("page")
        return box

    def panel(self, title: str | None = None) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("panel")
        if title:
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("section")
            box.append(label)
        return box

    def label(self, text: str, css: str | None = None, wrap: bool = False) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.set_wrap(wrap)
        if css:
            label.add_css_class(css)
        return label

    def make_dropdown(self, values: list[tuple[str, str]], active_id: str) -> Gtk.DropDown:
        labels = [label for _item_id, label in values]
        dropdown = Gtk.DropDown.new(Gtk.StringList.new(labels), None)
        dropdown.codex_ids = [item_id for item_id, _label in values]
        dropdown.set_selected(self.dropdown_index(dropdown, active_id))
        dropdown.connect("notify::selected", self.on_setting_changed)
        return dropdown

    def dropdown_index(self, dropdown: Gtk.DropDown, item_id: str) -> int:
        ids = getattr(dropdown, "codex_ids", [])
        try:
            return ids.index(item_id)
        except ValueError:
            return 0

    def dropdown_value(self, dropdown: Gtk.DropDown) -> str | None:
        ids = getattr(dropdown, "codex_ids", [])
        selected = dropdown.get_selected()
        if 0 <= selected < len(ids):
            return ids[selected]
        return None

    def set_dropdown(self, dropdown: Gtk.DropDown, item_id: str) -> None:
        dropdown.set_selected(self.dropdown_index(dropdown, item_id))

    def configure_paned(self, paned: Gtk.Paned, key: str, default: int) -> Gtk.Paned:
        paned.set_wide_handle(True)
        paned.set_position(pane_position(self.layout_state, key, default))
        paned.set_hexpand(True)
        paned.set_vexpand(True)
        self.paned_widgets[key] = paned
        paned.connect("notify::position", self.on_paned_position_changed, key)
        return paned

    def on_paned_position_changed(self, paned: Gtk.Paned, _param: object, key: str) -> None:
        self.layout_state = layout_with_pane(self.layout_state, key, paned.get_position())
        self.save_current_state()

    def text_buffer(self, view: Gtk.TextView) -> Gtk.TextBuffer:
        buf = view.get_buffer()
        return buf

    def text_from_buffer(self, buf: Gtk.TextBuffer | None) -> str:
        if buf is None:
            return ""
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        return buf.get_text(start, end, True)

    def set_status(self, text: str, level: str = "ok") -> None:
        if self.status_label is None:
            return
        self.status_label.set_text(text)
        self.status_label.remove_css_class("warn")
        self.status_label.remove_css_class("bad")
        if level == "warn":
            self.status_label.add_css_class("warn")
        elif level == "bad":
            self.status_label.add_css_class("bad")

    def build_dashboard_page(self) -> Gtk.Widget:
        box = self.page_box()
        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        self.card_codex = self.metric_card("Codex", "checking")
        self.card_auth = self.metric_card("Auth", "checking")
        self.card_model = self.metric_card("Default Model", "checking")
        self.card_terminal = self.metric_card("Terminal", "checking")
        self.card_appserver = self.metric_card("App Server", "checking")
        self.card_project = self.metric_card("Active Project", "checking")
        for index, card in enumerate([
            self.card_codex,
            self.card_auth,
            self.card_model,
            self.card_terminal,
            self.card_appserver,
            self.card_project,
        ]):
            grid.attach(card, index % 3, index // 3, 1, 1)
        box.append(grid)

        quick = self.panel("Fast Start")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for label, action, profile in [
            ("Max Power", "interactive", "maximum-power"),
            ("GPT-5.5 Work", "interactive", "pro-default"),
            ("Spark Fast Edit", "interactive", "spark-fast"),
            ("Safe Explore", "interactive", "safe-explore"),
            ("Deep Review", "review", "deep-review"),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("secondary")
            button.connect("clicked", self.on_fast_profile, action, profile)
            row.append(button)
        quick.append(row)
        box.append(quick)

        return self.wrap_scroll(box)

    def build_palette_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.palette_search_entry = Gtk.Entry()
        self.palette_search_entry.set_placeholder_text("Search commands, pages, checks, agents, receipts...")
        self.palette_search_entry.set_hexpand(True)
        self.palette_search_entry.connect("changed", self.on_action_query_changed)
        execute = self.make_button("Execute", "media-playback-start-symbolic")
        execute.add_css_class("primary")
        execute.connect("clicked", self.on_execute_selected_action)
        clear = self.make_button("Clear", "edit-clear-symbolic")
        clear.add_css_class("secondary")
        clear.connect("clicked", self.on_clear_action_query)
        toolbar.append(self.palette_search_entry)
        toolbar.append(execute)
        toolbar.append(clear)
        box.append(toolbar)

        summary = self.panel("Command Palette")
        summary.add_css_class("action-palette")
        self.palette_summary_label = self.label("Search every major Codex Control capability.", "action-detail", wrap=True)
        summary.append(self.palette_summary_label)
        groups = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for group, count in action_groups():
            groups.append(self.chip_label(f"{group} {count}", "chip"))
        summary.append(groups)
        box.append(summary)

        paned = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "palette", 540)

        self.palette_list = Gtk.ListBox()
        self.palette_list.add_css_class("action-list")
        self.palette_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.palette_list.connect("row-selected", self.on_action_selected)
        self.palette_list.connect("row-activated", self.on_action_activated)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("action-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.palette_list)

        detail = self.panel("Selected Action")
        detail.add_css_class("action-detail-panel")
        self.palette_action_title_label = self.label("No action selected", "action-title", wrap=True)
        self.palette_action_group_label = self.chip_label("idle", "chip")
        self.palette_action_detail_label = self.label("Search or select an action.", "action-detail", wrap=True)
        detail_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.palette_action_title_label.set_hexpand(True)
        detail_header.append(self.palette_action_title_label)
        detail_header.append(self.palette_action_group_label)
        detail.append(detail_header)
        detail.append(self.palette_action_detail_label)
        detail.append(self.label("Action ID", "section"))
        self.palette_action_id_label = self.label("-", "muted", wrap=True)
        detail.append(self.palette_action_id_label)
        preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview.add_css_class("action-preview")
        preview_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.palette_preview_title_label = self.label("Would Run", "action-preview-title", wrap=True)
        self.palette_preview_title_label.set_hexpand(True)
        self.palette_preview_status_label = self.chip_label("ready", "chip")
        self.palette_preview_surface_label = self.chip_label("surface", "chip")
        self.palette_preview_risk_label = self.chip_label("risk", "chip")
        preview_header.append(self.palette_preview_title_label)
        preview_header.append(self.palette_preview_status_label)
        preview_header.append(self.palette_preview_surface_label)
        preview_header.append(self.palette_preview_risk_label)
        preview.append(preview_header)
        self.palette_preview_summary_label = self.label("Select an action to preview its effect.", "action-preview-detail", wrap=True)
        self.palette_preview_requirements_label = self.label("Ready", "action-preview-detail", wrap=True)
        self.palette_preview_command_label = self.label("-", "action-preview-command", wrap=True)
        preview.append(self.palette_preview_summary_label)
        preview.append(self.palette_preview_requirements_label)
        preview.append(self.palette_preview_command_label)
        detail.append(preview)
        feedback = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        feedback.add_css_class("action-feedback")
        feedback.append(self.label("Action Console", "section"))
        self.palette_action_feedback_label = self.label(self.last_action_feedback.headline(), "action-feedback-title", wrap=True)
        self.palette_action_feedback_detail_label = self.label(self.last_action_feedback.detail, "action-feedback-detail", wrap=True)
        feedback.append(self.palette_action_feedback_label)
        feedback.append(self.palette_action_feedback_detail_label)
        detail.append(feedback)
        history = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        history.add_css_class("action-history")
        history_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.palette_history_title_label = self.label("Last Result", "action-history-title", wrap=True)
        self.palette_history_title_label.set_hexpand(True)
        self.palette_history_status_label = self.chip_label("none", "chip")
        self.palette_history_time_label = self.chip_label("never", "chip")
        history_header.append(self.palette_history_title_label)
        history_header.append(self.palette_history_status_label)
        history_header.append(self.palette_history_time_label)
        history.append(history_header)
        self.palette_history_detail_label = self.label("No action history yet.", "action-history-detail", wrap=True)
        self.palette_history_command_label = self.label("-", "action-history-command", wrap=True)
        history.append(self.palette_history_detail_label)
        history.append(self.palette_history_command_label)
        history_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Rerun", self.on_rerun_palette_action, True),
            ("Copy", self.on_copy_palette_history, False),
            ("Open Log", self.on_open_palette_history, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            history_controls.append(button)
        history.append(history_controls)
        detail.append(history)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail)
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(False)
        box.append(paned)
        self.render_action_palette()
        return box

    def build_context_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Refresh Packet", self.on_refresh_context_packet, True),
            ("Use as Prompt", self.on_use_context_packet, False),
            ("Copy Markdown", self.on_copy_context_packet, False),
            ("Save", self.on_save_context_packet, False),
            ("Run Max", self.on_run_embedded, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Context Packet")
        summary.add_css_class("context-packet")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.context_page_title_label = self.label("Building launch packet", "context-title", wrap=True)
        self.context_page_title_label.set_hexpand(True)
        self.context_page_score_label = self.chip_label("score --", "chip")
        self.context_page_status_label = self.chip_label("checking", "chip")
        header.append(self.context_page_title_label)
        header.append(self.context_page_score_label)
        header.append(self.context_page_status_label)
        summary.append(header)
        self.context_page_summary_label = self.label("Project, prompt, quality, mission, runs, and receipts are folded into one Codex-ready brief.", "context-detail", wrap=True)
        summary.append(self.context_page_summary_label)
        box.append(summary)

        paned = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "context", 430)

        self.context_page_list = Gtk.ListBox()
        self.context_page_list.add_css_class("context-list")
        self.context_page_list.set_selection_mode(Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("context-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.context_page_list)

        self.context_detail_view = self.code_text_view(editable=False)
        self.context_detail_buffer = self.context_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.context_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_context_packet()
        return box

    def build_roadmap_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Plan Roadmap", self.on_refresh_roadmap, True),
            ("Use Next Prompt", self.on_use_next_roadmap_prompt, False),
            ("Copy Roadmap", self.on_copy_roadmap, False),
            ("Save", self.on_save_roadmap, False),
            ("Run Max", self.on_run_embedded, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Milestone Roadmap")
        summary.add_css_class("roadmap-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.roadmap_page_title_label = self.label("Planning next milestone", "roadmap-title", wrap=True)
        self.roadmap_page_title_label.set_hexpand(True)
        self.roadmap_page_score_label = self.chip_label("score --", "chip")
        self.roadmap_page_status_label = self.chip_label("planning", "chip")
        header.append(self.roadmap_page_title_label)
        header.append(self.roadmap_page_score_label)
        header.append(self.roadmap_page_status_label)
        summary.append(header)
        self.roadmap_page_summary_label = self.label("Ranks the next best upgrades from local project, quality, context, mission, run, and receipt state.", "roadmap-detail", wrap=True)
        summary.append(self.roadmap_page_summary_label)
        box.append(summary)

        paned = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "roadmap", 470)

        self.roadmap_page_list = Gtk.ListBox()
        self.roadmap_page_list.add_css_class("roadmap-list")
        self.roadmap_page_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.roadmap_page_list.connect("row-selected", self.on_roadmap_milestone_selected)
        self.roadmap_page_list.connect("row-activated", self.on_roadmap_milestone_activated)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("roadmap-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.roadmap_page_list)

        self.roadmap_detail_view = self.code_text_view(editable=False)
        self.roadmap_detail_buffer = self.roadmap_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.roadmap_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_roadmap()
        return box

    def build_orchestration_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Prepare Package", self.on_prepare_launch_package, True),
            ("Run Package", self.on_run_launch_package, False),
            ("Copy Package", self.on_copy_launch_package, False),
            ("Save", self.on_save_launch_package, False),
            ("Stamp Receipt", self.on_stamp_receipt, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Run Orchestration")
        summary.add_css_class("orchestration-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.orchestration_page_title_label = self.label("Preparing launch package", "orchestration-title", wrap=True)
        self.orchestration_page_title_label.set_hexpand(True)
        self.orchestration_page_score_label = self.chip_label("score --", "chip")
        self.orchestration_page_status_label = self.chip_label("preparing", "chip")
        header.append(self.orchestration_page_title_label)
        header.append(self.orchestration_page_score_label)
        header.append(self.orchestration_page_status_label)
        summary.append(header)
        self.orchestration_page_summary_label = self.label("Unifies context, roadmap, preflight, quality, command preview, run ledger, and receipt posture before launch.", "orchestration-detail", wrap=True)
        summary.append(self.orchestration_page_summary_label)
        box.append(summary)

        paned = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "orchestration", 470)

        self.orchestration_page_list = Gtk.ListBox()
        self.orchestration_page_list.add_css_class("orchestration-list")
        self.orchestration_page_list.set_selection_mode(Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("orchestration-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.orchestration_page_list)

        self.orchestration_detail_view = self.code_text_view(editable=False)
        self.orchestration_detail_buffer = self.orchestration_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.orchestration_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_launch_package()
        return box

    def build_quality_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Run Gate", self.on_run_quality_gate, True),
            ("Copy Report", self.on_copy_quality_report, False),
            ("Refresh Plan", self.on_refresh_quality_gate, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Quality Gate")
        summary.add_css_class("quality-gate")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.quality_page_summary_label = self.label("No quality report yet", "quality-title", wrap=True)
        self.quality_page_summary_label.set_hexpand(True)
        self.quality_page_score_label = self.chip_label("not run", "chip")
        self.quality_page_status_label = self.chip_label("idle", "chip")
        header.append(self.quality_page_summary_label)
        header.append(self.quality_page_score_label)
        header.append(self.quality_page_status_label)
        summary.append(header)
        box.append(summary)

        paned = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "quality", 470)

        self.quality_page_list = Gtk.ListBox()
        self.quality_page_list.add_css_class("quality-list")
        self.quality_page_list.set_selection_mode(Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("quality-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.quality_page_list)

        self.quality_detail_view = self.code_text_view(editable=False)
        self.quality_detail_buffer = self.quality_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.quality_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_quality_gate()
        return box

    def build_agent_runs_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Save Current", self.on_save_agent_run, True),
            ("Load", self.on_load_agent_run, False),
            ("Delete", self.on_delete_agent_run, False),
            ("Copy", self.on_copy_agent_run, False),
            ("Refresh", self.on_reload_agent_runs, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(420)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.agent_run_list = Gtk.ListBox()
        self.agent_run_list.add_css_class("run-list")
        self.agent_run_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.agent_run_list.connect("row-selected", self.on_agent_run_selected)
        self.agent_run_list.connect("row-activated", self.on_agent_run_activated)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("run-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.agent_run_list)

        self.agent_run_detail_view = self.code_text_view(editable=False)
        self.agent_run_detail_buffer = self.agent_run_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.agent_run_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_agent_runs()
        return box

    def build_mission_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Architect", self.on_architect_mission, True),
            ("Use Prompt", self.on_use_mission_prompt, False),
            ("Plan Agents", self.on_plan_agents, False),
            ("Run Auto", self.on_run_autopilot, False),
            ("Run Max", self.on_run_embedded, False),
            ("Copy", self.on_copy_mission_blueprint, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Mission Architect")
        summary.add_css_class("mission-architect")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.mission_page_title_label = self.label("Architecting mission", "mission-title", wrap=True)
        self.mission_page_title_label.set_hexpand(True)
        self.mission_page_score_label = self.chip_label("score --", "chip")
        self.mission_page_status_label = self.chip_label("checking", "chip")
        header.append(self.mission_page_title_label)
        header.append(self.mission_page_score_label)
        header.append(self.mission_page_status_label)
        summary.append(header)
        self.mission_page_meta_label = self.label("Prompt, agents, validation, and launch path will appear here.", "mission-detail", wrap=True)
        summary.append(self.mission_page_meta_label)
        box.append(summary)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(470)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.mission_page_list = Gtk.ListBox()
        self.mission_page_list.add_css_class("mission-list")
        self.mission_page_list.set_selection_mode(Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("mission-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.mission_page_list)

        self.mission_detail_view = self.code_text_view(editable=False)
        self.mission_detail_buffer = self.mission_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.mission_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.refresh_mission_blueprint()
        return box

    def build_autopilot_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Prepare", self.on_prepare_autopilot, True),
            ("Track", self.on_track_autopilot, False),
            ("Terminal", self.on_run_selected_autopilot, False),
            ("Stop", self.on_stop_autopilot, False),
            ("Log", self.on_show_autopilot_log, False),
            ("Final", self.on_show_autopilot_final, False),
            ("Open", self.on_open_autopilot, False),
            ("Copy Detail", self.on_copy_autopilot, False),
            ("Delete Record", self.on_delete_autopilot, False),
            ("Refresh", self.on_refresh_autopilot, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Autopilot History")
        summary.add_css_class("autopilot-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.autopilot_page_title_label = self.label("No prepared Autopilot run", "mission-title", wrap=True)
        self.autopilot_page_title_label.set_hexpand(True)
        self.autopilot_page_status_label = self.chip_label("idle", "chip")
        self.autopilot_page_count_label = self.chip_label("0 runs", "chip")
        header.append(self.autopilot_page_title_label)
        header.append(self.autopilot_page_status_label)
        header.append(self.autopilot_page_count_label)
        summary.append(header)
        self.autopilot_page_meta_label = self.label("Prepare from Mission Architect to create a replayable script, blueprint, event stream, and manifest.", "autopilot-meta", wrap=True)
        summary.append(self.autopilot_page_meta_label)
        box.append(summary)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(470)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.autopilot_page_list = Gtk.ListBox()
        self.autopilot_page_list.add_css_class("autopilot-list")
        self.autopilot_page_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.autopilot_page_list.connect("row-selected", self.on_autopilot_selected)
        self.autopilot_page_list.connect("row-activated", self.on_autopilot_activated)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("autopilot-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.autopilot_page_list)

        self.autopilot_detail_view = self.code_text_view(editable=False)
        self.autopilot_detail_buffer = self.autopilot_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.autopilot_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_autopilot_records()
        return box

    def build_preflight_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Refresh", self.on_refresh_preflight, True),
            ("Copy Detail", self.on_copy_preflight, False),
            ("Run Max", self.on_run_embedded, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        summary = self.panel("Launch Preflight")
        summary.add_css_class("preflight-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.preflight_page_summary_label = self.label("Checking launch readiness", "preflight-title", wrap=True)
        self.preflight_page_summary_label.set_hexpand(True)
        self.preflight_page_score_label = self.chip_label("score --", "chip")
        self.preflight_page_status_label = self.chip_label("checking", "chip")
        header.append(self.preflight_page_summary_label)
        header.append(self.preflight_page_score_label)
        header.append(self.preflight_page_status_label)
        summary.append(header)
        box.append(summary)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(430)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.preflight_page_list = Gtk.ListBox()
        self.preflight_page_list.add_css_class("preflight-list")
        self.preflight_page_list.set_selection_mode(Gtk.SelectionMode.NONE)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("preflight-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.preflight_page_list)

        self.preflight_detail_view = self.code_text_view(editable=False)
        self.preflight_detail_buffer = self.preflight_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.preflight_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.refresh_preflight()
        return box

    def build_command_ledger_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Refresh", self.on_refresh_command_runs, True),
            ("Copy Detail", self.on_copy_command_run, False),
            ("Open Receipt", self.on_open_command_run_receipt, False),
            ("Delete", self.on_delete_command_run, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(460)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.command_run_page_list = Gtk.ListBox()
        self.command_run_page_list.add_css_class("command-run-list")
        self.command_run_page_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.command_run_page_list.connect("row-selected", self.on_command_run_selected)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("command-run-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.command_run_page_list)

        self.command_run_detail_view = self.code_text_view(editable=False)
        self.command_run_detail_buffer = self.command_run_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.command_run_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_command_runs()
        return box

    def build_receipts_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Stamp Current", self.on_stamp_receipt, True),
            ("Verify", self.on_verify_receipt, False),
            ("Replay Chain", self.on_replay_receipts, False),
            ("Open Folder", self.on_open_receipts, False),
            ("Copy Detail", self.on_copy_receipt, False),
            ("Refresh", self.on_refresh_receipts, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(460)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.receipt_page_list = Gtk.ListBox()
        self.receipt_page_list.add_css_class("receipt-list")
        self.receipt_page_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.receipt_page_list.connect("row-selected", self.on_receipt_selected)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("receipt-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.receipt_page_list)

        self.receipt_detail_view = self.code_text_view(editable=False)
        self.receipt_detail_buffer = self.receipt_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.receipt_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_receipts()
        return box

    def build_execution_monitor_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Run Selected", self.on_run_monitored_agent_lane, True),
            ("Run All", self.on_run_all_monitored_agents, False),
            ("Stop", self.on_stop_agent_execution, False),
            ("Logs", self.on_show_execution_log, False),
            ("Final", self.on_show_execution_final, False),
            ("Open", self.on_open_execution_artifacts, False),
            ("Copy", self.on_copy_execution_detail, False),
            ("Refresh", self.on_refresh_execution_monitor, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            toolbar.append(button)
        box.append(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(440)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        self.execution_list = Gtk.ListBox()
        self.execution_list.add_css_class("execution-list")
        self.execution_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.execution_list.connect("row-selected", self.on_execution_selected)
        self.execution_list.connect("row-activated", self.on_execution_activated)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add_css_class("execution-scroll")
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(self.execution_list)

        self.execution_detail_view = self.code_text_view(editable=False)
        self.execution_detail_buffer = self.execution_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_child(self.execution_detail_view)

        paned.set_start_child(list_scroll)
        paned.set_end_child(detail_scroll)
        paned.set_resize_start_child(False)
        paned.set_resize_end_child(True)
        box.append(paned)
        self.render_execution_monitor()
        return box

    def metric_card(self, title: str, value: str) -> Gtk.Box:
        card = self.panel()
        card.set_size_request(260, 92)
        card.append(self.label(title, "muted"))
        value_label = self.label(value)
        value_label.add_css_class("row-title")
        card.value_label = value_label
        card.append(value_label)
        return card

    def compact_stat(self, title: str, value: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.add_css_class("stat-card")
        label = self.label(title, "muted")
        value_label = self.label(value)
        value_label.add_css_class("stat-value")
        card.value_label = value_label
        card.append(label)
        card.append(value_label)
        return card

    def build_launch_page(self) -> Gtk.Widget:
        outer = self.page_box()
        outer.add_css_class("workbench")

        self.project_entry = Gtk.Entry()
        self.project_entry.set_hexpand(True)
        self.project_entry.set_text(self.config.get("project", str(DEFAULT_PROJECT if DEFAULT_PROJECT.exists() else Path.home())))
        self.project_entry.connect("changed", self.on_setting_changed)
        self.profile_combo = self.make_dropdown(self.profile_options(), self.config.get("profile", "none"))
        self.model_combo = self.make_dropdown(MODELS, self.config.get("model", "config"))
        self.reasoning_combo = self.make_dropdown(REASONING, self.config.get("reasoning", "config"))
        self.sandbox_combo = self.make_dropdown(SANDBOXES, self.config.get("sandbox", "config"))
        self.approval_combo = self.make_dropdown(APPROVALS, self.config.get("approval", "config"))
        self.web_combo = self.make_dropdown(WEB_MODES, self.config.get("web", "config"))
        self.personality_combo = self.make_dropdown(PERSONALITIES, self.config.get("personality", "config"))
        self.action_combo = self.make_dropdown(ACTIONS, self.config.get("action", "interactive"))

        outer.append(self.build_operator_console())
        outer.append(self.build_mission_panel())
        outer.append(self.build_mission_architect_panel())

        workspace = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "workbench", 940)

        main_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_col.set_hexpand(True)
        main_col.set_vexpand(True)
        main_col.append(self.build_terminal_panel())
        main_col.append(self.build_composer_panel())

        control_rail = self.build_control_rail()
        workspace.set_start_child(main_col)
        workspace.set_end_child(control_rail)
        workspace.set_resize_start_child(True)
        workspace.set_resize_end_child(False)
        workspace.set_shrink_start_child(False)
        workspace.set_shrink_end_child(False)
        outer.append(workspace)
        return outer

    def build_operator_console(self) -> Gtk.Widget:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        panel.add_css_class("operator-console")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        copy.set_hexpand(True)
        self.operator_title_label = self.label("Command deck", "operator-title", wrap=True)
        self.operator_subtitle_label = self.label("checking", "operator-subtitle", wrap=True)
        copy.append(self.operator_title_label)
        copy.append(self.operator_subtitle_label)
        header.append(copy)
        self.operator_readiness_label = self.chip_label("checking", "chip")
        self.operator_action_button = self.make_button("Prepare", "media-playback-start-symbolic")
        self.operator_action_button.add_css_class("primary")
        self.operator_action_button.connect("clicked", self.on_operator_action)
        header.append(self.operator_readiness_label)
        header.append(self.operator_action_button)
        panel.append(header)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.operator_signal_labels = []
        self.operator_signal_cards = []
        for index in range(6):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.add_css_class("operator-card")
            title = self.label("Signal", "muted")
            value = self.label("checking", "operator-card-value")
            detail = self.label("", "operator-card-detail", wrap=True)
            card.append(title)
            card.append(value)
            card.append(detail)
            card.set_hexpand(True)
            grid.attach(card, index % 3, index // 3, 1, 1)
            self.operator_signal_labels.append((title, value, detail))
            self.operator_signal_cards.append(card)
        panel.append(grid)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, icon_name, handler, primary in [
            ("Run Max", "media-playback-start-symbolic", self.on_run_embedded, True),
        ]:
            button = self.make_button(label, icon_name)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            action_row.append(button)
        panel.append(action_row)

        secondary_actions = Gtk.Expander(label="Operator actions")
        secondary_action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, icon_name, handler, primary in [
            ("Prepare Auto", "document-new-symbolic", self.on_prepare_autopilot, False),
            ("Track Auto", "view-refresh-symbolic", self.on_track_autopilot, False),
            ("Review", "edit-find-symbolic", lambda button: self.on_run_action_button(button, "review"), False),
            ("Preflight", "checkbox-checked-symbolic", self.on_show_preflight, False),
        ]:
            button = self.make_button(label, icon_name)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            secondary_action_row.append(button)
        secondary_actions.set_child(secondary_action_row)
        panel.append(secondary_actions)
        self.render_operator_brief()
        return panel

    def build_power_banner(self) -> Gtk.Widget:
        banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        banner.add_css_class("power-banner")
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        title = Gtk.Label(label="Maximum Power", xalign=0)
        title.add_css_class("power-title")
        subtitle = Gtk.Label(label="maximum-power | gpt-5.5 | xhigh | live", xalign=0)
        subtitle.add_css_class("power-subtitle")
        left.append(title)
        left.append(subtitle)
        left.set_hexpand(True)
        banner.append(left)

        chip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        self.power_mode_label = self.chip_label(self.selected_mode_label(), "mode-pill")
        self.power_reasoning_label = self.chip_label("xhigh", "chip-strong")
        self.power_sandbox_label = self.chip_label("full access", "chip-danger")
        self.power_search_label = self.chip_label("live search", "chip")
        for chip in [
            self.power_mode_label,
            self.power_reasoning_label,
            self.power_sandbox_label,
            self.power_search_label,
        ]:
            chip_row.append(chip)
        banner.append(chip_row)
        return banner

    def build_mission_panel(self) -> Gtk.Widget:
        command_bar = self.panel("Mission")
        command_bar.add_css_class("workbench-panel")
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_row.append(self.project_entry)
        browse = Gtk.Button(label="Browse")
        browse.connect("clicked", self.on_browse_project)
        top_row.append(browse)
        command_bar.append(top_row)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        max_power = Gtk.Button(label="Max Power")
        max_power.add_css_class("accent")
        max_power.connect("clicked", self.on_fast_profile, "interactive", "maximum-power")
        action_row.append(max_power)
        for label, action, primary in [
            ("Start", "interactive", True),
            ("Review", "review", False),
            ("Resume", "resume", False),
            ("Exec", "exec", False),
        ]:
            button = Gtk.Button(label=label)
            if primary:
                button.add_css_class("primary")
            else:
                button.add_css_class("secondary")
            button.connect("clicked", self.on_run_action_button, action)
            action_row.append(button)
        detach = Gtk.Button(label="Detach")
        detach.add_css_class("secondary")
        detach.connect("clicked", self.on_run_external)
        action_row.append(detach)
        command_bar.append(action_row)
        return command_bar

    def build_preflight_panel(self) -> Gtk.Widget:
        panel = self.panel("Preflight")
        panel.add_css_class("preflight-panel")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.preflight_summary_label = self.label("Checking launch readiness", "preflight-title", wrap=True)
        self.preflight_summary_label.set_hexpand(True)
        self.preflight_score_label = self.chip_label("score --", "chip")
        self.preflight_status_label = self.chip_label("checking", "chip")
        top.append(self.preflight_summary_label)
        top.append(self.preflight_score_label)
        top.append(self.preflight_status_label)
        panel.append(top)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.preflight_hint_label = self.label("Checks update with project, prompt, and profile changes.", "muted", wrap=True)
        self.preflight_hint_label.set_hexpand(True)
        controls.append(self.preflight_hint_label)
        for label, handler, primary in [
            ("Refresh", self.on_refresh_preflight, True),
            ("Details", self.on_show_preflight, False),
            ("Copy", self.on_copy_preflight, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.append(button)
        panel.append(controls)
        self.refresh_preflight()
        return panel

    def build_mission_architect_panel(self) -> Gtk.Widget:
        panel = self.panel("Mission Architect")
        panel.add_css_class("mission-architect")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.mission_title_label = self.label("Architecting mission", "mission-title", wrap=True)
        self.mission_title_label.set_hexpand(True)
        self.mission_score_label = self.chip_label("score --", "chip")
        self.mission_status_label = self.chip_label("checking", "chip")
        top.append(self.mission_title_label)
        top.append(self.mission_score_label)
        top.append(self.mission_status_label)
        panel.append(top)

        self.mission_meta_label = self.label("Prompt, agents, validation, and launch path will appear here.", "mission-detail", wrap=True)
        panel.append(self.mission_meta_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Architect", self.on_architect_mission, True),
            ("Use Prompt", self.on_use_mission_prompt, False),
            ("Plan Agents", self.on_plan_agents, False),
            ("Run Auto", self.on_run_autopilot, False),
            ("Details", self.on_show_mission, False),
            ("Run Max", self.on_run_embedded, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.append(button)
        panel.append(controls)
        self.refresh_mission_blueprint()
        return panel

    def build_terminal_panel(self) -> Gtk.Widget:
        terminal_panel = self.panel()
        terminal_panel.add_css_class("terminal-panel")
        terminal_panel.set_vexpand(True)
        terminal_panel.set_size_request(-1, 400)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = self.label("Terminal", "section")
        self.terminal_cwd_label = self.label(self.selected_project(), "muted")
        self.terminal_cwd_label.set_ellipsize(Pango.EllipsizeMode.START)
        self.terminal_cwd_label.set_hexpand(True)
        self.terminal_state_label = self.chip_label("ready", "chip-strong")
        clear = Gtk.Button(label="Clear")
        clear.add_css_class("secondary")
        clear.connect("clicked", self.on_terminal_clear)
        shell = Gtk.Button(label="Shell")
        shell.add_css_class("secondary")
        shell.connect("clicked", self.on_terminal_shell)
        copy = Gtk.Button(label="Copy")
        copy.add_css_class("secondary")
        copy.connect("clicked", self.on_copy_command)
        for widget in [title, self.terminal_cwd_label, self.terminal_state_label, clear, shell, copy]:
            header.append(widget)
        terminal_panel.append(header)
        terminal_panel.append(self.build_terminal_widget())
        return terminal_panel

    def build_composer_panel(self) -> Gtk.Widget:
        composer = self.panel("Ask Codex")
        composer.add_css_class("composer")
        primary_template_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for name in ("Best", "Build", "Fix"):
            prompt = PROMPTS[name]
            button = Gtk.Button(label=name)
            button.add_css_class("secondary")
            if name == "Best":
                button.add_css_class("accent")
            button.connect("clicked", self.on_prompt_template, prompt, name)
            primary_template_row.append(button)
        composer.append(primary_template_row)

        template_expander = Gtk.Expander(label="Prompt templates")
        button_grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        secondary_prompts = [
            (name, prompt)
            for name, prompt in PROMPTS.items()
            if name not in {"Best", "Build", "Fix"}
        ]
        for index, (name, prompt) in enumerate(secondary_prompts):
            button = Gtk.Button(label=name)
            button.add_css_class("secondary")
            button.connect("clicked", self.on_prompt_template, prompt, name)
            button_grid.attach(button, index % 4, index // 4, 1, 1)
        template_expander.set_child(button_grid)
        composer.append(template_expander)

        self.prompt_view = Gtk.TextView()
        self.prompt_view.add_css_class("composer-view")
        self.prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.prompt_view.set_top_margin(10)
        self.prompt_view.set_bottom_margin(10)
        self.prompt_view.set_left_margin(10)
        self.prompt_view.set_right_margin(10)
        self.prompt_buffer = self.prompt_view.get_buffer()
        self.prompt_buffer.set_text(self.config.get("prompt") or PROMPTS["Best"])
        self.prompt_buffer.connect("changed", self.on_setting_changed)
        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(106)
        prompt_scroll.set_child(self.prompt_view)
        composer.append(prompt_scroll)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Run Max", self.on_run_embedded, True),
            ("Enhance", self.on_enhance_prompt, False),
        ]:
            button = Gtk.Button(label=label)
            if primary:
                button.add_css_class("primary")
            else:
                button.add_css_class("secondary")
            button.connect("clicked", handler)
            button_row.append(button)
        composer.append(button_row)

        run_options = Gtk.Expander(label="Run options")
        option_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("AI Enhance", self.on_ai_enhance_prompt, False),
            ("Detach", self.on_run_external, False),
            ("Exec JSON", self.on_run_headless, False),
            ("Copy Command", self.on_copy_command, False),
        ]:
            button = Gtk.Button(label=label)
            if primary:
                button.add_css_class("primary")
            else:
                button.add_css_class("secondary")
            button.connect("clicked", handler)
            option_row.append(button)
        run_options.set_child(option_row)
        composer.append(run_options)
        return composer

    def build_control_rail(self) -> Gtk.Widget:
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        rail.add_css_class("side-rail")
        rail.set_size_request(self.layout_state.rail_width - 20, -1)
        rail.append(self.build_session_workspace_panel())
        rail.append(self.build_launch_package_panel())
        rail.append(self.build_roadmap_panel())
        rail.append(self.build_context_packet_panel())
        rail.append(self.build_palette_panel())
        rail.append(self.build_quality_gate_panel())
        rail.append(self.build_autopilot_panel())
        rail.append(self.build_command_ledger_panel())
        rail.append(self.build_receipt_vault_panel())
        rail.append(self.build_agent_studio_panel())
        rail.append(self.build_agent_results_panel())
        rail.append(self.build_project_intelligence_panel())
        rail.append(self.build_prompt_choices_panel())
        rail.append(self.build_power_controls_panel())
        rail.append(self.build_quick_launch_panel())
        rail.append(self.build_command_preview_panel())
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(self.layout_state.rail_width, -1)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(rail)
        return scroll

    def build_palette_panel(self) -> Gtk.Widget:
        panel = self.panel("Command Palette")
        panel.add_css_class("action-palette")
        self.palette_compact_entry = Gtk.Entry()
        self.palette_compact_entry.set_placeholder_text("Search actions")
        self.palette_compact_entry.connect("changed", self.on_action_query_changed)
        panel.append(self.palette_compact_entry)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Run", self.on_execute_selected_action, True),
            ("Open", lambda button: self.show_palette(), False),
            ("Clear", self.on_clear_action_query, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.append(button)
        panel.append(controls)
        self.palette_compact_preview_label = self.label("Preview: select an action", "action-preview-detail", wrap=True)
        panel.append(self.palette_compact_preview_label)
        self.palette_compact_feedback_label = self.label(self.last_action_feedback.compact(), "action-feedback-detail", wrap=True)
        panel.append(self.palette_compact_feedback_label)
        self.palette_compact_history_label = self.label("Last: no action history yet", "action-history-detail", wrap=True)
        panel.append(self.palette_compact_history_label)

        self.palette_compact_list = Gtk.ListBox()
        self.palette_compact_list.add_css_class("action-list")
        self.palette_compact_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.palette_compact_list.connect("row-selected", self.on_action_selected)
        self.palette_compact_list.connect("row-activated", self.on_action_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("action-scroll")
        scroller.set_min_content_height(150)
        scroller.set_child(self.palette_compact_list)
        panel.append(scroller)
        self.render_action_palette()
        return panel

    def build_context_packet_panel(self) -> Gtk.Widget:
        panel = self.panel("Context Packet")
        panel.add_css_class("context-packet")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.context_title_label = self.label("Building launch packet", "context-section-title", wrap=True)
        self.context_title_label.set_hexpand(True)
        self.context_score_label = self.chip_label("score --", "chip")
        self.context_status_label = self.chip_label("checking", "chip")
        top.append(self.context_title_label)
        top.append(self.context_score_label)
        top.append(self.context_status_label)
        panel.append(top)

        self.context_summary_label = self.label("Synthesizes prompt, project state, mission, quality, runs, and receipts.", "context-detail", wrap=True)
        panel.append(self.context_summary_label)

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Refresh", self.on_refresh_context_packet, True),
            ("Use", self.on_use_context_packet, False),
            ("Copy", self.on_copy_context_packet, False),
            ("Open", lambda button: self.show_context_page(), False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 4, index // 4, 1, 1)
        panel.append(controls)

        self.context_compact_list = Gtk.ListBox()
        self.context_compact_list.add_css_class("context-list")
        self.context_compact_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("context-scroll")
        scroller.set_min_content_height(132)
        scroller.set_child(self.context_compact_list)
        panel.append(scroller)
        self.render_context_packet()
        return panel

    def build_roadmap_panel(self) -> Gtk.Widget:
        panel = self.panel("Milestone Roadmap")
        panel.add_css_class("roadmap-panel")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.roadmap_title_label = self.label("Planning next milestone", "roadmap-row-title", wrap=True)
        self.roadmap_title_label.set_hexpand(True)
        self.roadmap_score_label = self.chip_label("score --", "chip")
        self.roadmap_status_label = self.chip_label("planning", "chip")
        top.append(self.roadmap_title_label)
        top.append(self.roadmap_score_label)
        top.append(self.roadmap_status_label)
        panel.append(top)

        self.roadmap_summary_label = self.label("Ranks the next best upgrades from current app state.", "roadmap-detail", wrap=True)
        panel.append(self.roadmap_summary_label)

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Plan", self.on_refresh_roadmap, True),
            ("Use Next", self.on_use_next_roadmap_prompt, False),
            ("Copy", self.on_copy_roadmap, False),
            ("Open", lambda button: self.show_roadmap_page(), False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 4, index // 4, 1, 1)
        panel.append(controls)

        self.roadmap_compact_list = Gtk.ListBox()
        self.roadmap_compact_list.add_css_class("roadmap-list")
        self.roadmap_compact_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.roadmap_compact_list.connect("row-selected", self.on_roadmap_milestone_selected)
        self.roadmap_compact_list.connect("row-activated", self.on_roadmap_milestone_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("roadmap-scroll")
        scroller.set_min_content_height(132)
        scroller.set_child(self.roadmap_compact_list)
        panel.append(scroller)
        self.render_roadmap()
        return panel

    def build_launch_package_panel(self) -> Gtk.Widget:
        panel = self.panel("Run Orchestrator")
        panel.add_css_class("orchestration-panel")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.orchestration_title_label = self.label("Preparing launch package", "orchestration-row-title", wrap=True)
        self.orchestration_title_label.set_hexpand(True)
        self.orchestration_score_label = self.chip_label("score --", "chip")
        self.orchestration_status_label = self.chip_label("preparing", "chip")
        top.append(self.orchestration_title_label)
        top.append(self.orchestration_score_label)
        top.append(self.orchestration_status_label)
        panel.append(top)

        self.orchestration_summary_label = self.label("Context, preflight, command, ledger, and receipts before launch.", "orchestration-detail", wrap=True)
        panel.append(self.orchestration_summary_label)

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Prepare", self.on_prepare_launch_package, True),
            ("Run", self.on_run_launch_package, False),
            ("Copy", self.on_copy_launch_package, False),
            ("Open", lambda button: self.show_orchestration_page(), False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 4, index // 4, 1, 1)
        panel.append(controls)

        self.orchestration_compact_list = Gtk.ListBox()
        self.orchestration_compact_list.add_css_class("orchestration-list")
        self.orchestration_compact_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("orchestration-scroll")
        scroller.set_min_content_height(132)
        scroller.set_child(self.orchestration_compact_list)
        panel.append(scroller)
        self.render_launch_package()
        return panel

    def build_quality_gate_panel(self) -> Gtk.Widget:
        panel = self.panel("Quality Gate")
        panel.add_css_class("quality-gate")
        self.quality_status_label = self.label("No quality report yet", "muted", wrap=True)
        panel.append(self.quality_status_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Run", self.on_run_quality_gate, True),
            ("Plan", self.on_refresh_quality_gate, False),
            ("Copy", self.on_copy_quality_report, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.append(button)
        panel.append(controls)

        self.quality_compact_list = Gtk.ListBox()
        self.quality_compact_list.add_css_class("quality-list")
        self.quality_compact_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("quality-scroll")
        scroller.set_min_content_height(122)
        scroller.set_child(self.quality_compact_list)
        panel.append(scroller)
        self.render_quality_gate()
        return panel

    def build_power_controls_panel(self) -> Gtk.Widget:
        panel = self.panel("Power Matrix")
        panel.add_css_class("power-controls")
        for label, widget in [
            ("Action", self.action_combo),
            ("Profile", self.profile_combo),
            ("Model", self.model_combo),
            ("Reasoning", self.reasoning_combo),
            ("Sandbox", self.sandbox_combo),
            ("Approval", self.approval_combo),
            ("Web", self.web_combo),
            ("Persona", self.personality_combo),
        ]:
            panel.append(self.form_row(label, widget))

        self.add_dir_entry = Gtk.Entry()
        self.add_dir_entry.set_placeholder_text("Extra writable directory")
        self.add_dir_entry.set_text(self.config.get("add_dir", ""))
        self.add_dir_entry.connect("changed", self.on_setting_changed)
        panel.append(self.form_row("Add dir", self.add_dir_entry))

        self.inline_switch = Gtk.Switch()
        self.inline_switch.set_active(bool(self.config.get("inline", False)))
        self.inline_switch.connect("notify::active", self.on_setting_changed)
        self.skip_git_switch = Gtk.Switch()
        self.skip_git_switch.set_active(bool(self.config.get("skip_git", True)))
        self.skip_git_switch.connect("notify::active", self.on_setting_changed)
        panel.append(self.form_row("Inline", self.inline_switch))
        panel.append(self.form_row("No git gate", self.skip_git_switch))
        return panel

    def build_session_workspace_panel(self) -> Gtk.Widget:
        panel = self.panel("Session Workspace")
        panel.add_css_class("session-workspace")
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("New", self.on_new_workspace_session, False),
            ("Save", self.on_save_workspace_session, False),
            ("Use", self.on_use_workspace_session, True),
            ("Run", self.on_run_workspace_session, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.append(button)
        panel.append(controls)

        self.session_list = Gtk.ListBox()
        self.session_list.add_css_class("session-list")
        self.session_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.session_list.connect("row-selected", self.on_workspace_session_selected)
        self.session_list.connect("row-activated", self.on_workspace_session_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("session-scroll")
        scroller.set_min_content_height(82)
        scroller.set_child(self.session_list)
        panel.append(scroller)
        self.render_workspace_sessions()
        return panel

    def build_autopilot_panel(self) -> Gtk.Widget:
        panel = self.panel("Autopilot")
        panel.add_css_class("autopilot-panel")
        self.autopilot_status_label = self.label("Prepare a durable run package from Mission Architect", "autopilot-meta", wrap=True)
        panel.append(self.autopilot_status_label)

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Prepare", self.on_prepare_autopilot, True),
            ("Track", self.on_track_autopilot, False),
            ("Term", self.on_run_selected_autopilot, False),
            ("Stop", self.on_stop_autopilot, False),
            ("Open", self.on_open_autopilot, False),
            ("Copy", self.on_copy_autopilot, False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 2, index // 2, 1, 1)
        panel.append(controls)

        self.autopilot_compact_list = Gtk.ListBox()
        self.autopilot_compact_list.add_css_class("autopilot-list")
        self.autopilot_compact_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.autopilot_compact_list.connect("row-selected", self.on_autopilot_selected)
        self.autopilot_compact_list.connect("row-activated", self.on_autopilot_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("autopilot-scroll")
        scroller.set_min_content_height(132)
        scroller.set_child(self.autopilot_compact_list)
        panel.append(scroller)
        self.render_autopilot_records()
        return panel

    def build_agent_studio_panel(self) -> Gtk.Widget:
        panel = self.panel("Agent Studio")
        panel.add_css_class("agent-studio")
        self.agent_status_label = self.label("Plan lanes from the current prompt", "muted", wrap=True)
        panel.append(self.agent_status_label)

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Plan", self.on_plan_agents, True),
            ("Prep", self.on_prepare_agent_worktrees, False),
            ("Run", self.on_run_agent_lane, False),
            ("Track", self.on_run_monitored_agent_lane, False),
            ("All", self.on_launch_all_agents, False),
            ("Copy", self.on_copy_agent_script, False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 3, index // 3, 1, 1)
        panel.append(controls)

        self.agent_list = Gtk.ListBox()
        self.agent_list.add_css_class("agent-list")
        self.agent_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.agent_list.connect("row-selected", self.on_agent_lane_selected)
        self.agent_list.connect("row-activated", self.on_agent_lane_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("agent-scroll")
        scroller.set_min_content_height(152)
        scroller.set_child(self.agent_list)
        panel.append(scroller)
        self.plan_agent_lanes()
        return panel

    def build_agent_results_panel(self) -> Gtk.Widget:
        panel = self.panel("Results Console")
        panel.add_css_class("result-console")
        self.agent_result_status_label = self.label("Refresh after lanes run", "muted", wrap=True)
        panel.append(self.agent_result_status_label)

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Refresh", self.on_refresh_agent_results, True),
            ("Save", self.on_save_agent_run, False),
            ("Diff", self.on_diff_agent_result, False),
            ("Apply", self.on_apply_agent_result, False),
            ("Merge", self.on_merge_agent_result, False),
            ("Open", self.on_open_agent_result, False),
            ("Copy", self.on_copy_agent_result, False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 4, index // 4, 1, 1)
        panel.append(controls)

        self.agent_result_list = Gtk.ListBox()
        self.agent_result_list.add_css_class("result-list")
        self.agent_result_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.agent_result_list.connect("row-selected", self.on_agent_result_selected)
        self.agent_result_list.connect("row-activated", self.on_agent_result_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("result-scroll")
        scroller.set_min_content_height(136)
        scroller.set_child(self.agent_result_list)
        panel.append(scroller)
        self.refresh_agent_results(show_status=False)
        return panel

    def build_project_intelligence_panel(self) -> Gtk.Widget:
        panel = self.panel("Project Intelligence")
        panel.add_css_class("project-intel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.project_intel_name = self.label("scanning", "project-intel-value")
        self.project_intel_name.set_hexpand(True)
        refresh = Gtk.Button(label="Refresh")
        refresh.add_css_class("secondary")
        refresh.connect("clicked", lambda _b: self.refresh_project_snapshot_async())
        header.append(self.project_intel_name)
        header.append(refresh)
        panel.append(header)

        self.project_intel_stack = self.label("Stack: checking", "muted", wrap=True)
        self.project_intel_git = self.label("Git: checking", "muted", wrap=True)
        self.project_intel_recommendation = self.label("Recommendation: checking", "muted", wrap=True)
        self.project_intel_files = self.label("Files: checking", "muted", wrap=True)
        self.project_intel_changes = self.label("Changes: checking", "muted", wrap=True)
        self.project_intel_threads = self.label("Threads: checking", "muted", wrap=True)
        for label in [
            self.project_intel_stack,
            self.project_intel_git,
            self.project_intel_recommendation,
            self.project_intel_files,
            self.project_intel_changes,
            self.project_intel_threads,
        ]:
            panel.append(label)

        panel.append(self.label("Validation", "section"))
        self.project_command_list = Gtk.ListBox()
        self.project_command_list.set_selection_mode(Gtk.SelectionMode.NONE)
        command_scroll = Gtk.ScrolledWindow()
        command_scroll.set_min_content_height(128)
        command_scroll.set_child(self.project_command_list)
        panel.append(command_scroll)
        return panel

    def build_quick_launch_panel(self) -> Gtk.Widget:
        panel = self.panel("Launch Profiles")
        panel.add_css_class("quick-grid")
        for label, action, profile, accent in [
            ("Maximum Power", "interactive", "maximum-power", True),
            ("Pro Work", "interactive", "pro-default", False),
            ("Spark Fast", "interactive", "spark-fast", False),
            ("Safe Explore", "interactive", "safe-explore", False),
            ("Deep Review", "review", "deep-review", False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("accent" if accent else "secondary")
            button.connect("clicked", self.on_fast_profile, action, profile)
            panel.append(button)
        return panel

    def build_prompt_choices_panel(self) -> Gtk.Widget:
        panel = self.panel("Prompt Lab")
        panel.add_css_class("prompt-lab")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        enhance = Gtk.Button(label="Enhance")
        enhance.add_css_class("accent")
        enhance.connect("clicked", self.on_enhance_prompt)
        ai_enhance = Gtk.Button(label="AI Enhance")
        ai_enhance.add_css_class("secondary")
        ai_enhance.connect("clicked", self.on_ai_enhance_prompt)
        use = Gtk.Button(label="Use Choice")
        use.add_css_class("primary")
        use.connect("clicked", self.on_use_prompt_choice)
        row.append(enhance)
        row.append(ai_enhance)
        row.append(use)
        panel.append(row)

        self.prompt_choice_list = Gtk.ListBox()
        self.prompt_choice_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.prompt_choice_list.connect("row-selected", self.on_prompt_choice_selected)
        self.prompt_choice_list.connect("row-activated", self.on_prompt_choice_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(190)
        scroller.set_child(self.prompt_choice_list)
        panel.append(scroller)
        self.prompt_variants = enhance_prompt(self.selected_prompt(), self.project_context_text())
        self.render_prompt_variants()
        return panel

    def default_atlas_root(self) -> str:
        configured = str(self.config.get("atlas_root") or "").strip()
        if configured:
            return configured
        binary = atlas_binary()
        if binary is not None:
            return str(binary.parents[3])
        return ""

    def build_receipt_vault_panel(self) -> Gtk.Widget:
        panel = self.panel("Receipt Vault")
        panel.add_css_class("receipt-vault")
        self.receipt_status_label = self.label("Stamp Codex runs as metadata-only Atlas receipts", "muted", wrap=True)
        panel.append(self.receipt_status_label)

        self.atlas_root_entry = Gtk.Entry()
        self.atlas_root_entry.set_placeholder_text("Atlas root, optional")
        self.atlas_root_entry.set_text(self.default_atlas_root())
        self.atlas_root_entry.connect("changed", self.on_setting_changed)
        panel.append(self.form_row("Atlas", self.atlas_root_entry))

        self.receipt_auto_switch = Gtk.Switch()
        self.receipt_auto_switch.set_active(bool(self.config.get("receipt_auto", True)))
        self.receipt_auto_switch.connect("notify::active", self.on_setting_changed)
        panel.append(self.form_row("Auto", self.receipt_auto_switch))

        controls = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, (label, handler, primary) in enumerate([
            ("Stamp", self.on_stamp_receipt, True),
            ("Verify", self.on_verify_receipt, False),
            ("Replay", self.on_replay_receipts, False),
            ("Open", self.on_open_receipts, False),
            ("Copy", self.on_copy_receipt, False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.attach(button, index % 3, index // 3, 1, 1)
        panel.append(controls)

        self.receipt_compact_list = Gtk.ListBox()
        self.receipt_compact_list.add_css_class("receipt-list")
        self.receipt_compact_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.receipt_compact_list.connect("row-selected", self.on_receipt_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("receipt-scroll")
        scroller.set_min_content_height(134)
        scroller.set_child(self.receipt_compact_list)
        panel.append(scroller)
        self.render_receipts()
        return panel

    def build_command_ledger_panel(self) -> Gtk.Widget:
        panel = self.panel("Run Ledger")
        panel.add_css_class("run-ledger")
        self.command_run_status_label = self.label("Recent Codex launches are recorded metadata-only", "muted", wrap=True)
        panel.append(self.command_run_status_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Refresh", self.on_refresh_command_runs, True),
            ("Copy", self.on_copy_command_run, False),
            ("Open", self.on_open_command_run_receipt, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            controls.append(button)
        panel.append(controls)

        self.command_run_compact_list = Gtk.ListBox()
        self.command_run_compact_list.add_css_class("command-run-list")
        self.command_run_compact_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.command_run_compact_list.connect("row-selected", self.on_command_run_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("command-run-scroll")
        scroller.set_min_content_height(126)
        scroller.set_child(self.command_run_compact_list)
        panel.append(scroller)
        self.render_command_runs()
        return panel

    def build_command_preview_panel(self) -> Gtk.Widget:
        panel = self.panel("Command Preview")
        panel.add_css_class("command-preview")
        self.command_view = self.code_text_view(editable=False)
        self.command_buffer = self.command_view.get_buffer()
        command_scroll = Gtk.ScrolledWindow()
        command_scroll.set_min_content_height(150)
        command_scroll.set_vexpand(True)
        command_scroll.set_child(self.command_view)
        panel.append(command_scroll)
        return panel

    def chip_label(self, text: str, css: str = "chip") -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.add_css_class(css)
        return label

    def build_terminal_widget(self) -> Gtk.Widget:
        if Vte is None:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.add_css_class("terminal-frame")
            box.append(self.label("VTE is not installed. Use Run External.", "danger-text"))
            return box
        self.terminal = Vte.Terminal()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self.terminal.set_size(132, 34)
        self.terminal.set_size_request(-1, 300)
        self.terminal.set_scrollback_lines(20_000)
        self.terminal.set_font(Pango.FontDescription("Monospace 10"))
        self.terminal.add_css_class("terminal-frame")
        self.spawn_shell_in_terminal()
        return self.terminal

    def build_mesh_page(self) -> Gtk.Widget:
        box = self.page_box()
        box.add_css_class("device-mesh")

        summary = self.panel()
        summary.add_css_class("mesh-summary")
        initial_readiness = mesh_readiness_report(self.devices, self.mesh_probe_records)
        initial_operator = self.current_team_operator_summary()
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        title_col.set_hexpand(True)
        title_col.append(self.label("Device Mesh", "operator-title"))
        self.mesh_summary_label = self.label(f"{initial_readiness.summary} | {len(self.memory_items)} memory item(s)", "muted", wrap=True)
        title_col.append(self.mesh_summary_label)
        top.append(title_col)
        self.mesh_device_count_label = self.chip_label("0 devices", "chip")
        self.mesh_memory_count_label = self.chip_label("0 memories", "chip")
        self.mesh_selected_label = self.chip_label("none selected", "chip")
        self.mesh_ready_count_label = self.chip_label(
            f"{initial_readiness.ready_count} ready",
            "chip-strong" if initial_readiness.ready_count else "chip",
        )
        self.mesh_lane_count_label = self.chip_label(
            initial_operator.lane_text,
            self.chip_css_for_status(initial_operator.status),
        )
        self.mesh_bus_health_label = self.chip_label(
            initial_operator.bus_text,
            self.chip_css_for_status(initial_operator.status),
        )
        self.mesh_next_action_label = self.chip_label(f"Next: {initial_operator.next_action}", "mode-pill")
        for chip in [
            self.mesh_device_count_label,
            self.mesh_memory_count_label,
            self.mesh_selected_label,
            self.mesh_ready_count_label,
            self.mesh_lane_count_label,
            self.mesh_bus_health_label,
            self.mesh_next_action_label,
        ]:
            top.append(chip)
        summary.append(top)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Refresh", self.on_refresh_mesh, False),
            ("Discover Tailnet", self.on_discover_tailnet, True),
            ("Check Fleet", self.on_check_fleet, False),
            ("Prepare Team", self.on_prepare_mesh_team, True),
            ("Launch Team", self.on_launch_mesh_team, False),
            ("Collect Team", self.on_collect_mesh_team, False),
            ("Save Memory", self.on_save_memory, True),
            ("Copy Memory", self.on_copy_memory, False),
            ("Open Memory", self.on_open_memory, False),
            ("Open Devices", self.on_open_devices, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            actions.append(button)
        summary.append(actions)
        box.append(summary)

        workspace = self.configure_paned(Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL), "mesh", 720)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.set_hexpand(False)
        right.set_hexpand(True)
        right.set_vexpand(True)

        form = self.panel("Device")
        self.device_name_entry = Gtk.Entry()
        self.device_name_entry.set_placeholder_text("Laptop, workstation, atlas-builder")
        self.device_host_entry = Gtk.Entry()
        self.device_host_entry.set_placeholder_text("host or IP")
        self.device_user_entry = Gtk.Entry()
        self.device_user_entry.set_placeholder_text("SSH user")
        self.device_port_entry = Gtk.Entry()
        self.device_port_entry.set_text("22")
        self.device_project_entry = Gtk.Entry()
        self.device_project_entry.set_text("~/Projects/codex-gui")
        self.device_codex_entry = Gtk.Entry()
        self.device_codex_entry.set_text("~/.local/bin/codex")
        for label, widget in [
            ("Name", self.device_name_entry),
            ("Host", self.device_host_entry),
            ("User", self.device_user_entry),
            ("Port", self.device_port_entry),
            ("Project", self.device_project_entry),
            ("Codex", self.device_codex_entry),
        ]:
            form.append(self.form_row(label, widget))
        device_buttons = Gtk.Grid(column_spacing=8, row_spacing=8)
        self.mesh_selected_device_buttons: list[Gtk.Button] = []
        for index, (label, handler, primary) in enumerate([
            ("New", self.on_new_device_form, False),
            ("Add/Update", self.on_add_device, True),
            ("Remove", self.on_remove_device, False),
            ("Check", self.on_check_selected_device, True),
            ("Check Visible", self.on_check_visible_devices, True),
            ("Copy Test", self.on_copy_device_test, False),
            ("Copy Launch", self.on_copy_device_launch, False),
            ("Sync Memory", self.on_sync_memory_to_device, False),
            ("Open Session", self.on_open_device_session, False),
        ]):
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            if label in {"Remove", "Check", "Copy Test", "Copy Launch", "Sync Memory", "Open Session"}:
                button.set_tooltip_text("Select a device first.")
                self.mesh_selected_device_buttons.append(button)
            device_buttons.attach(button, index % 3, index // 3, 1, 1)
        form.append(device_buttons)
        left.append(form)

        devices_panel = self.panel("Devices")
        self.device_list = Gtk.ListBox()
        self.device_list.add_css_class("device-list")
        self.device_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.device_list.connect("row-selected", self.on_device_selected)
        self.mesh_filter_buttons: dict[str, Gtk.ToggleButton] = {}
        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for filter_key, filter_label in MESH_FILTER_OPTIONS:
            button = Gtk.ToggleButton(label=f"{filter_label} 0")
            button.set_active(filter_key == self.mesh_filter_mode)
            button.connect("toggled", self.on_mesh_filter_toggled, filter_key)
            self.mesh_filter_buttons[filter_key] = button
            filter_bar.append(button)
        self.mesh_team_only_toggle = Gtk.ToggleButton(label="Team-only")
        self.mesh_team_only_toggle.set_active(self.mesh_team_only)
        self.mesh_team_only_toggle.connect("toggled", self.on_mesh_team_only_toggled)
        filter_bar.append(self.mesh_team_only_toggle)
        self.refresh_mesh_filter_bar(mesh_readiness_report(self.devices, self.mesh_probe_records))
        devices_panel.append(filter_bar)

        device_scroll = Gtk.ScrolledWindow()
        device_scroll.set_min_content_width(360)
        device_scroll.set_vexpand(True)
        device_scroll.set_child(self.device_list)
        devices_panel.append(device_scroll)
        left.append(devices_panel)

        detail = self.panel("Connection Plan")
        detail.add_css_class("mesh-detail")
        self.mesh_detail_view = self.code_text_view(editable=False)
        self.mesh_detail_buffer = self.mesh_detail_view.get_buffer()
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_min_content_height(220)
        detail_scroll.set_size_request(-1, 300)
        detail_scroll.set_vexpand(False)
        detail_scroll.set_child(self.mesh_detail_view)
        detail.append(detail_scroll)
        right.append(detail)

        team = self.panel("Codex Team")
        team.add_css_class("team-panel")
        self.mesh_team_status_label = self.label("No team package yet", "muted", wrap=True)
        team.append(self.mesh_team_status_label)
        team_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.mesh_prepared_team_buttons: list[Gtk.Button] = []
        for label, handler, primary in [
            ("Check", self.on_check_fleet, False),
            ("Latest", self.on_load_latest_mesh_team, False),
            ("Prepare", self.on_prepare_mesh_team, True),
            ("Prepare Visible", self.on_prepare_visible_mesh_team, False),
            ("Launch", self.on_launch_mesh_team, False),
            ("Collect", self.on_collect_mesh_team, False),
            ("Bus", self.on_sync_mesh_handoff_bus, False),
            ("Verify Bus", self.on_verify_mesh_bus_integrity, False),
            ("Repair Bus", self.on_retry_mesh_handoff_bus, False),
            ("Preview Repair", self.on_preview_mesh_bus_repair, False),
            ("Copy Bus Report", self.on_copy_mesh_team_bus_report, False),
            ("Copy Role Bootstrap", self.on_copy_role_bootstrap, False),
            ("Summary", self.on_copy_mesh_team_summary, False),
            ("Broadcast Stream", self.on_sync_team_chat, False),
            ("Open", self.on_open_mesh_team, False),
        ]:
            button = Gtk.Button(label=label)
            button.add_css_class("primary" if primary else "secondary")
            button.connect("clicked", handler)
            if label not in {"Check", "Latest", "Prepare", "Prepare Visible"}:
                button.set_tooltip_text("Prepare or load a team first.")
                self.mesh_prepared_team_buttons.append(button)
            team_buttons.append(button)
        team.append(team_buttons)
        self.mesh_team_list = Gtk.ListBox()
        self.mesh_team_list.add_css_class("team-list")
        team_scroll = Gtk.ScrolledWindow()
        team_scroll.set_min_content_height(130)
        team_scroll.set_size_request(-1, 150)
        team_scroll.set_vexpand(False)
        team_scroll.set_child(self.mesh_team_list)
        team.append(team_scroll)
        right.append(team)

        stream = self.panel("Team Stream")
        stream.add_css_class("team-stream-panel")
        self.mesh_team_chat_status_label = self.label("No team stream yet", "muted", wrap=True)
        stream.append(self.mesh_team_chat_status_label)
        live_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        live_row.append(self.label("Live refresh", "muted"))
        self.mesh_live_refresh_switch = Gtk.Switch()
        self.mesh_live_refresh_switch.set_active(self.mesh_live_refresh)
        self.mesh_live_refresh_switch.connect("state-set", self.on_mesh_live_refresh_toggled)
        live_row.append(self.mesh_live_refresh_switch)
        self.mesh_live_refresh_label = self.label(f"every {self.mesh_live_refresh_seconds}s", "muted")
        live_row.append(self.mesh_live_refresh_label)
        stream.append(live_row)
        self.mesh_chat_view = self.code_text_view(editable=False)
        self.mesh_team_chat_buffer = self.mesh_chat_view.get_buffer()
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_min_content_height(170)
        chat_scroll.set_size_request(-1, 210)
        chat_scroll.set_vexpand(False)
        chat_scroll.set_child(self.mesh_chat_view)
        stream.append(chat_scroll)
        chat_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.mesh_chat_entry = Gtk.Entry()
        self.mesh_chat_entry.set_placeholder_text("Post team status, blockers, next step.")
        self.mesh_chat_entry.set_hexpand(True)
        self.mesh_chat_entry.connect("activate", self.on_post_team_chat)
        post_chat = Gtk.Button(label="Post")
        post_chat.connect("clicked", self.on_post_team_chat)
        refresh_chat = Gtk.Button(label="Refresh")
        refresh_chat.connect("clicked", self.on_refresh_team_chat)
        copy_chat = Gtk.Button(label="Copy")
        copy_chat.connect("clicked", self.on_copy_team_chat)
        post_chat.add_css_class("primary")
        refresh_chat.add_css_class("secondary")
        copy_chat.add_css_class("secondary")
        chat_controls.append(self.mesh_chat_entry)
        chat_controls.append(post_chat)
        chat_controls.append(refresh_chat)
        chat_controls.append(copy_chat)
        stream.append(chat_controls)
        right.append(stream)

        memory = self.panel("Portable Memory")
        memory.add_css_class("memory-panel")
        self.memory_view = self.code_text_view(editable=True)
        self.memory_buffer = self.memory_view.get_buffer()
        memory_scroll = Gtk.ScrolledWindow()
        memory_scroll.set_min_content_height(170)
        memory_scroll.set_size_request(-1, 210)
        memory_scroll.set_vexpand(False)
        memory_scroll.set_child(self.memory_view)
        memory.append(memory_scroll)

        import_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.memory_import_entry = Gtk.Entry()
        self.memory_import_entry.set_placeholder_text("Paste one memory line or key: value")
        self.memory_import_entry.set_hexpand(True)
        import_button = Gtk.Button(label="Import")
        import_button.add_css_class("secondary")
        import_button.connect("clicked", self.on_import_memory)
        import_row.append(self.memory_import_entry)
        import_row.append(import_button)
        memory.append(import_row)
        right.append(memory)

        workspace.set_start_child(left)
        workspace.set_end_child(right)
        workspace.set_resize_start_child(False)
        workspace.set_resize_end_child(True)
        workspace.set_shrink_start_child(False)
        workspace.set_shrink_end_child(False)
        box.append(workspace)
        self.render_mesh()
        return box

    def selected_mesh_device(self) -> DeviceRecord | None:
        readiness = mesh_readiness_report(self.devices, self.mesh_probe_records)
        candidates = self._filtered_mesh_devices(readiness)
        if self.selected_device is not None:
            return next((device for device in candidates if device.id == self.selected_device.id), candidates[0] if candidates else None)
        return candidates[0] if candidates else None

    def _mesh_readiness_status(self, device: DeviceRecord, readiness: MeshReadinessReport) -> str:
        row = readiness.by_device(device.id)
        return row.status if row is not None else device.status

    def _mesh_device_matches_filter(self, device: DeviceRecord, readiness: MeshReadinessReport) -> bool:
        if self.mesh_team_only:
            return self.trusted_mesh_device(device) and self._mesh_readiness_status(device, readiness) == "ready"
        if self.mesh_filter_mode == "all":
            return True
        if self.mesh_filter_mode == "review":
            return self._mesh_readiness_status(device, readiness) in {"review", "unknown"}
        return self._mesh_readiness_status(device, readiness) == self.mesh_filter_mode

    def _filtered_mesh_devices(self, readiness: MeshReadinessReport) -> list[DeviceRecord]:
        return [device for device in self.devices if self._mesh_device_matches_filter(device, readiness)]

    def refresh_mesh_filter_bar(self, readiness: MeshReadinessReport) -> None:
        counts = {
            "all": readiness.total,
            "ready": readiness.ready_count,
            "review": readiness.review_count,
            "blocked": readiness.blocked_count,
            "offline": readiness.offline_count,
        }
        for filter_key, label in MESH_FILTER_OPTIONS:
            button = self.mesh_filter_buttons.get(filter_key)
            if button is None:
                continue
            button.set_label(f"{label} {counts.get(filter_key, 0)}")
            button.remove_css_class("primary")
            button.remove_css_class("secondary")
            button.add_css_class("secondary")
            if not self.mesh_team_only and filter_key == self.mesh_filter_mode:
                button.remove_css_class("secondary")
                button.add_css_class("primary")
            if self.mesh_team_only:
                button.add_css_class("secondary")
        self.mesh_team_only_toggle.remove_css_class("primary")
        self.mesh_team_only_toggle.remove_css_class("secondary")
        self.mesh_team_only_toggle.add_css_class("secondary")
        if self.mesh_team_only:
            self.mesh_team_only_toggle.remove_css_class("secondary")
            self.mesh_team_only_toggle.add_css_class("primary")

    def _mesh_device_role(self, device: DeviceRecord) -> str:
        for index, item in enumerate(self.devices):
            if item.id == device.id:
                return team_role_for_device(item.name, item.host, index).title
        return team_role_for_device(device.name, device.host).title

    def _mesh_device_role_chip(self, device: DeviceRecord) -> str:
        return self._mesh_device_role(device).replace(" / ", "/")

    def is_local_mesh_device(self, device: DeviceRecord) -> bool:
        return device.host.strip().lower() in {"localhost", "127.0.0.1", "::1"}

    def on_mesh_filter_toggled(self, button: Gtk.ToggleButton, filter_key: str) -> None:
        if self._mesh_filter_toggling:
            return
        if not button.get_active():
            if self.mesh_filter_mode == filter_key:
                self._mesh_filter_toggling = True
                button.set_active(True)
                self._mesh_filter_toggling = False
            return
        self._mesh_filter_toggling = True
        for key, current in self.mesh_filter_buttons.items():
            if current is button:
                continue
            if current.get_active():
                current.set_active(False)
        self._mesh_filter_toggling = False
        self.mesh_filter_mode = filter_key
        self.save_current_state()
        self.render_mesh()

    def on_mesh_team_only_toggled(self, button: Gtk.ToggleButton) -> None:
        self.mesh_team_only = button.get_active()
        self.save_current_state()
        self.render_mesh()

    def fill_device_form(self, device: DeviceRecord | None) -> None:
        if not hasattr(self, "device_name_entry"):
            return
        self.device_name_entry.set_text(device.name if device else "")
        self.device_host_entry.set_text(device.host if device else "")
        self.device_user_entry.set_text(device.user if device else "")
        self.device_port_entry.set_text(str(device.port if device else 22))
        self.device_project_entry.set_text(device.project_root if device else "~/Projects/codex-gui")
        self.device_codex_entry.set_text(device.codex_bin if device else "~/.local/bin/codex")

    def device_from_form(self) -> DeviceRecord | None:
        name = self.device_name_entry.get_text().strip() if hasattr(self, "device_name_entry") else ""
        host = self.device_host_entry.get_text().strip() if hasattr(self, "device_host_entry") else ""
        user = self.device_user_entry.get_text().strip() if hasattr(self, "device_user_entry") else ""
        port_text = self.device_port_entry.get_text().strip() if hasattr(self, "device_port_entry") else "22"
        if not host:
            self.set_status("Device host required", "warn")
            return None
        try:
            port = int(port_text or "22")
        except ValueError:
            self.set_status("SSH port must be a number", "warn")
            return None
        if port < 1 or port > 65535:
            self.set_status("SSH port is out of range", "warn")
            return None
        device = new_device(
            name=name or host,
            host=host,
            user=user,
            port=port,
            project_root=self.device_project_entry.get_text().strip() if hasattr(self, "device_project_entry") else "~/Projects/codex-gui",
            codex_bin=self.device_codex_entry.get_text().strip() if hasattr(self, "device_codex_entry") else "~/.local/bin/codex",
        )
        if self.selected_device is None:
            return device
        return DeviceRecord(
            id=self.selected_device.id,
            name=device.name,
            host=device.host,
            user=device.user,
            port=device.port,
            project_root=device.project_root,
            codex_bin=device.codex_bin,
            status=device.status,
            note=device.note,
            updated=device.updated,
        )

    def persist_devices(self) -> None:
        save_devices(DEVICES_FILE, self.devices)

    def persist_memory_from_editor(self) -> None:
        text = self.text_from_buffer(self.memory_buffer)
        self.memory_items = import_memory_text((), text, source="editor")
        save_memory(MEMORY_FILE, self.memory_items)
        self.set_text(self.memory_buffer, memory_markdown(self.memory_items))

    def render_device_list(self) -> None:
        if not hasattr(self, "device_list"):
            return
        self.clear_listbox(self.device_list)
        readiness_report = mesh_readiness_report(self.devices, self.mesh_probe_records)
        self.refresh_mesh_filter_bar(readiness_report)
        filtered_devices = self._filtered_mesh_devices(readiness_report)
        if self.selected_device is not None and all(device.id != self.selected_device.id for device in filtered_devices):
            self.selected_device = filtered_devices[0] if filtered_devices else None
        selected_row: Gtk.ListBoxRow | None = None
        if not filtered_devices:
            self.selected_device = None
            row = Gtk.ListBoxRow()
            row.add_css_class("device-row")
            if self.mesh_team_only:
                row.set_child(self.label("No team-ready devices match current filters", "muted", wrap=True))
            else:
                row.set_child(self.label("No devices match current filters", "muted", wrap=True))
            self.device_list.append(row)
            self.fill_device_form(None)
            return
        for index, device in enumerate(filtered_devices):
            row = Gtk.ListBoxRow()
            row.device = device
            row.add_css_class("device-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(device.name, "row-title")
            title.set_hexpand(True)
            status = self.chip_label(device.status, self.chip_css_for_status(device.status))
            role = self.chip_label(self._mesh_device_role_chip(device), "mode-pill")
            readiness = readiness_report.by_device(device.id)
            fleet_status = self.chip_label(
                readiness.status if readiness is not None else device.status,
                self.chip_css_for_status(readiness.status if readiness is not None else device.status),
            )
            top.append(title)
            top.append(status)
            top.append(role)
            top.append(fleet_status)
            target = self.label(f"{device.target()}:{device.port}", "muted")
            target.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            project = self.label(device.project_root, "muted")
            project.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            content.append(top)
            content.append(target)
            content.append(project)
            if readiness is not None and readiness.blocker_category:
                content.append(self.label(f"Readiness: {readiness.blocker_category}", "muted"))
            if device.note:
                note = self.label(device.note, "muted", wrap=True)
                note.set_lines(2)
                note.set_ellipsize(Pango.EllipsizeMode.END)
                content.append(note)
            row.set_child(content)
            self.device_list.append(row)
            if self.selected_device is not None and device.id == self.selected_device.id:
                selected_row = row
        if selected_row is None:
            selected_row = self.device_list.get_row_at_index(0)
            self.selected_device = getattr(selected_row, "device", None) if selected_row is not None else None
        if selected_row is not None:
            self.device_list.select_row(selected_row)

    def current_team_operator_summary(self, run_status=None):
        ready = len(self.ready_mesh_devices())
        saved = len(team_run_dirs(TEAM_DIR))
        assignment_count = len(self.mesh_team_assignments)
        if run_status is None and self.mesh_team_dir is not None:
            run_status = inspect_team_run(self.mesh_team_dir)
        return team_operator_summary(
            run_status,
            self._team_bus_report(),
            ready_devices=ready,
            saved_runs=saved,
            assignment_count=assignment_count,
        )

    def refresh_mesh_operator_chips(self, readiness: MeshReadinessReport) -> None:
        if not hasattr(self, "mesh_next_action_label"):
            return
        operator = self.current_team_operator_summary()
        ready = readiness.ready_count
        self.set_chip(
            self.mesh_ready_count_label,
            f"{ready} ready",
            "chip-strong" if ready else "chip",
        )
        self.set_chip(
            self.mesh_lane_count_label,
            operator.lane_text,
            self.chip_css_for_status(operator.status),
        )
        self.set_chip(
            self.mesh_bus_health_label,
            operator.bus_text,
            self.chip_css_for_status(operator.status),
        )
        self.set_chip(
            self.mesh_next_action_label,
            f"Next: {operator.next_action}",
            "mode-pill",
        )

    def render_mesh_detail(self) -> None:
        if not hasattr(self, "mesh_summary_label"):
            return
        readiness = mesh_readiness_report(self.devices, self.mesh_probe_records)
        visible_devices = self._filtered_mesh_devices(readiness)
        self.mesh_summary_label.set_text(f"{readiness.summary} | {len(self.memory_items)} memory item(s)")
        self.refresh_mesh_operator_chips(readiness)
        self.set_chip(
            self.mesh_device_count_label,
            f"{len(visible_devices)}/{len(self.devices)} devices",
            "chip-strong" if visible_devices else "chip",
        )
        self.set_chip(self.mesh_memory_count_label, f"{len(self.memory_items)} memories", "chip-strong" if self.memory_items else "chip")
        device = self.selected_mesh_device()
        self.set_chip(self.mesh_selected_label, device.name if device else "none selected", "mode-pill" if device else "chip")
        self.refresh_mesh_action_sensitivity()
        if device is None:
            text = (
                "No selected device.\n\n"
                f"Devices file: {DEVICES_FILE}\n"
                f"Portable memory: {MEMORY_FILE}\n"
            )
            self.set_text(self.mesh_detail_buffer, text)
            return
        if self.is_local_mesh_device(device):
            test_command = shell_join(["bash", "-lc", f"{device.codex_bin} --version && pwd"])
            probe_command = shell_join(list(local_probe_command(device)))
            launch_command = shell_join(list(local_agent_command(device, "team-run", "local-lane")))
            sync_command = "local device: portable memory is already on this machine"
        else:
            test_command = shell_join(list(ssh_test_command(device)))
            probe_command = shell_join(list(ssh_probe_command(device)))
            launch_command = shell_join(list(ssh_launch_command(device)))
            sync_command = shell_join(list(rsync_memory_command(MEMORY_FILE, device)))
        detail = [
            f"Selected: {device.name}",
            f"Target: {device.target()}",
            f"Project: {device.project_root}",
            f"Codex: {device.codex_bin}",
            f"Role: {self._mesh_device_role(device)}",
            f"Status: {device.status}",
            f"Note: {device.note or 'none'}",
            "",
            "SSH test",
            test_command,
            "",
            "Fleet probe",
            probe_command,
            "",
            "Launch remote Codex with portable memory",
            launch_command,
            "",
            "Sync portable memory",
            sync_command,
            "",
            f"Devices file: {DEVICES_FILE}",
            f"Portable memory: {MEMORY_FILE}",
        ]
        readiness_row = readiness.by_device(device.id)
        if readiness_row is not None:
            detail.append(f"Fleet status: {readiness_row.status}")
            detail.extend([
                "",
                "Fleet readiness",
                f"Category: {readiness_row.blocker_category}",
                f"Summary: {readiness_row.summary}",
            ])
            if readiness_row.next_actions:
                detail.append("Next actions:")
                detail.extend([f"- {item}" for item in readiness_row.next_actions])
        probe = self.mesh_probe_records.get(device.id)
        if probe is not None:
            detail.extend(["", "Last probe", probe.detail_text()])
        self.set_text(self.mesh_detail_buffer, "\n".join(detail) + "\n")

    def refresh_mesh_action_sensitivity(self) -> None:
        has_device = self.selected_mesh_device() is not None
        has_team = self.mesh_team_dir is not None and bool(self.mesh_team_assignments) and bool(self.mesh_team_run_id)
        for button in getattr(self, "mesh_selected_device_buttons", []):
            button.set_sensitive(has_device)
            button.set_tooltip_text("" if has_device else "Select a device first.")
        for button in getattr(self, "mesh_prepared_team_buttons", []):
            button.set_sensitive(has_team)
            button.set_tooltip_text("" if has_team else "Prepare or load a team first.")

    def render_mesh(self) -> None:
        self.render_device_list()
        if hasattr(self, "memory_buffer"):
            self.set_text(self.memory_buffer, memory_markdown(self.memory_items))
        self.render_mesh_detail()
        self.render_mesh_team_chat()
        self.render_mesh_team()

    def _mesh_team_lane_for_selected_device(self) -> tuple[str, str]:
        device = self.selected_mesh_device()
        if device is None:
            return "operator", "orchestrator"
        lane_slug = ""
        for assignment in self.mesh_team_assignments:
            if assignment.get("device_name") == device.name:
                lane_slug = assignment.get("lane_slug", "")
                break
        return device.name, lane_slug or slugify(device.name)

    def _team_chat_path(self, run_dir: Path | None = None) -> Path:
        base = self.mesh_team_dir if run_dir is None else run_dir
        return base / "out" / "team-chat.md"

    def sync_team_chat_to_devices(self) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_assignments or not self.mesh_team_run_id:
            return
        assignments = list(self.mesh_team_assignments)
        run_id = self.mesh_team_run_id
        team_dir = self.mesh_team_dir
        team_chat_path = self._team_chat_path(team_dir)
        if not team_chat_path.exists():
            return

        def worker() -> None:
            for assignment in assignments:
                device = self.mesh_assignment_device(assignment)
                if device is None or self.is_local_mesh_device(device):
                    continue
                try:
                    run_cmd(list(rsync_team_chat_command(team_dir, device, run_id)), timeout=20)
                except Exception:
                    continue

        threading.Thread(target=worker, daemon=True).start()

    def collect_team_chat_from_devices(self, team_dir: Path, run_id: str) -> None:
        collected = []
        base_chat = ""
        base_path = self._team_chat_path(team_dir)
        if base_path.exists():
            try:
                base_chat = base_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                base_chat = ""
        collected.append(base_chat)

        for assignment in self.mesh_team_assignments:
            if assignment.get("device_name", "").strip() == "":
                continue
            device = self.mesh_assignment_device(assignment)
            if device is None or self.is_local_mesh_device(device):
                continue
            try:
                run_cmd(list(rsync_team_chat_pull_command(team_dir, device, run_id)), timeout=20)
            except Exception:
                pass
            device_path = team_dir / "collected" / slugify(device.name) / "team-chat.md"
            if not device_path.exists():
                continue
            try:
                collected.append(device_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        merged = merge_team_chat_texts(*collected)
        if not merged:
            return
        base_path.write_text(merged, encoding="utf-8")

    def render_mesh_team_chat(self) -> None:
        if not hasattr(self, "mesh_team_chat_buffer"):
            return
        if self.mesh_team_dir is None:
            self.set_text(self.mesh_team_chat_buffer, "No team run loaded.\nPrepare a team to begin a shared stream.")
            if hasattr(self, "mesh_team_chat_status_label"):
                self.mesh_team_chat_status_label.set_text("No team run loaded")
            if hasattr(self, "mesh_live_refresh_label"):
                self.mesh_live_refresh_label.set_text(f"{'on' if self.mesh_live_refresh else 'off'} | no team loaded")
            return
        text = read_team_chat(self.mesh_team_dir).strip()
        if not text:
            text = "# Team Stream\n\nNo chat entries yet. Use Post to send updates."
        self.set_text(self.mesh_team_chat_buffer, text + ("\n" if text else ""))
        if hasattr(self, "mesh_team_chat_status_label"):
            self.mesh_team_chat_status_label.set_text(
                f"{self.mesh_team_run_id} | stream active | {len(self.mesh_team_assignments)} lane(s)"
            )
        if hasattr(self, "mesh_live_refresh_label"):
            self.mesh_live_refresh_label.set_text(f"{'on' if self.mesh_live_refresh else 'off'} | every {self.mesh_live_refresh_seconds}s")

    def finish_team_chat_refresh(self, status_text: str = "") -> bool:
        self.mesh_live_refresh_busy = False
        self.render_mesh_team_chat()
        self.render_mesh_detail()
        if status_text:
            self.set_status(status_text)
        return False

    def refresh_team_chat_async(self, *, status_text: str = "Team stream refreshed", quiet: bool = False) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_run_id:
            self.render_mesh_team_chat()
            if not quiet:
                self.set_status("No team stream to refresh", "warn")
            return
        if self.mesh_live_refresh_busy:
            if not quiet:
                self.set_status("Team stream refresh already running", "warn")
            return

        team_dir = self.mesh_team_dir
        run_id = self.mesh_team_run_id
        self.mesh_live_refresh_busy = True

        def worker() -> None:
            try:
                self.collect_team_chat_from_devices(team_dir, run_id)
            finally:
                GLib.idle_add(self.finish_team_chat_refresh, "" if quiet else status_text)

        threading.Thread(target=worker, daemon=True).start()
        if not quiet:
            self.set_status("Refreshing team stream")

    def on_refresh_team_chat(self, _button: Gtk.Button) -> None:
        self.refresh_team_chat_async(status_text="Team stream refreshed")

    def on_mesh_live_refresh_toggled(self, _switch: Gtk.Switch, state: bool) -> bool:
        self.mesh_live_refresh = bool(state)
        self.ensure_mesh_live_refresh_timer()
        self.save_current_state()
        self.render_mesh_team_chat()
        self.set_status(f"Mesh live refresh {'enabled' if self.mesh_live_refresh else 'disabled'}")
        return False

    def ensure_mesh_live_refresh_timer(self) -> None:
        if self.mesh_live_refresh_timer_id:
            return
        self.mesh_live_refresh_timer_id = GLib.timeout_add_seconds(
            self.mesh_live_refresh_seconds,
            self.on_mesh_live_refresh_tick,
        )

    def on_mesh_live_refresh_tick(self) -> bool:
        if self.mesh_live_refresh:
            self.refresh_team_chat_async(status_text="Team stream auto-refresh", quiet=True)
        return True

    def on_sync_team_chat(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_assignments:
            self.set_status("No team package loaded", "warn")
            return
        self.sync_team_chat_to_devices()
        self.set_status("Broadcasting team stream")

    def on_copy_team_chat(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None:
            self.set_status("No team run loaded", "warn")
            return
        self.render_mesh_team_chat()
        text = self.text_from_buffer(self.mesh_team_chat_buffer)
        if not text:
            text = "No team stream content"
        self.copy_mesh_text(text, "Team stream copied")
        self.set_status("Team stream copied")

    def on_post_team_chat(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None:
            self.set_status("No team run loaded", "warn")
            return
        if not hasattr(self, "mesh_chat_entry"):
            self.set_status("Team chat input missing", "warn")
            return
        message = self.mesh_chat_entry.get_text().strip()
        if not message:
            self.set_status("Team update is empty", "warn")
            return
        sender, lane_slug = self._mesh_team_lane_for_selected_device()
        try:
            write_team_chat_entry(self.mesh_team_dir, sender=sender, lane=lane_slug, message=message)
            self.mesh_chat_entry.set_text("")
            self.render_mesh_team_chat()
            self.sync_team_chat_to_devices()
            self.set_status(f"Posted team update for {sender}")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Failed to post team update: {exc}", "bad")

    def trusted_mesh_device(self, device: DeviceRecord) -> bool:
        identity = f"{device.name} {device.host} {device.note}".lower()
        return "atlas-security" not in identity and device.status != "untrusted"

    def ready_mesh_devices(self, candidates: tuple[DeviceRecord, ...] | None = None) -> tuple[DeviceRecord, ...]:
        readiness = mesh_readiness_report(self.devices, self.mesh_probe_records)
        candidate_devices = self.devices if candidates is None else candidates
        return tuple(
            device for device in candidate_devices
            if self.trusted_mesh_device(device) and (row := readiness.by_device(device.id)) is not None and row.status == "ready"
        )

    def _mesh_team_seed_devices(self) -> tuple[DeviceRecord, ...]:
        readiness = mesh_readiness_report(self.devices, self.mesh_probe_records)
        if self.mesh_team_only or self.mesh_filter_mode != "all":
            return tuple(self._filtered_mesh_devices(readiness))
        return self.devices

    def focus_for_mesh_device(self, device: DeviceRecord, index: int) -> tuple[str, str]:
        role = team_role_for_device(device.name, device.host, index)
        return role.title, role.assignment_focus()

    def mesh_base_prompt(self) -> str:
        prompt = self.selected_prompt()
        if prompt:
            return prompt
        return (
            "Continue improving Codex Control toward the best practical version. "
            "Prioritize a premium GTK workstation, robust backend orchestration, "
            "trusted multi-device Codex teamwork, validation, and reversible changes."
        )

    def mesh_assignment_device(self, assignment: dict[str, str]) -> DeviceRecord | None:
        device_id = assignment.get("device_id", "")
        return next((device for device in self.devices if device.id == device_id), None)

    def build_mesh_team_assignments(self, candidate_devices: tuple[DeviceRecord, ...] | None = None) -> list[dict[str, str]]:
        assignments: list[dict[str, str]] = []
        for index, device in enumerate(self.ready_mesh_devices(candidate_devices)):
            lane_title, focus = self.focus_for_mesh_device(device, index)
            lane_slug = slugify(f"{lane_title}-{device.name}")
            role = team_role_for_device(device.name, device.host, index)
            assignments.append({
                "device_id": device.id,
                "device_name": device.name,
                "role_id": role.id,
                "role_title": role.title,
                "role_profile": role_profile_hint(role.id),
                "role_focus": role.focus,
                "role_boundary": role.boundary,
                "target": f"{device.target()}:{device.port}",
                "lane_title": lane_title,
                "lane_slug": lane_slug,
                "focus": focus,
                "project_root": device.project_root,
            })
        return assignments

    def write_private_text(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def write_mesh_team_package(self, assignments: list[dict[str, str]]) -> Path:
        run_id = dt.datetime.now().strftime("team-%Y%m%d-%H%M%S")
        team_dir = TEAM_DIR / run_id
        lanes_dir = team_dir / "lanes"
        out_dir = team_dir / "out"
        collected_dir = team_dir / "collected"
        for directory in (team_dir, lanes_dir, out_dir, collected_dir):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                directory.chmod(0o700)
            except OSError:
                pass
        base_prompt = self.mesh_base_prompt()
        assignment_lines = [
            f"- {item.get('role_title', item['lane_title'])} on {item['device_name']} ({item['target']}): {item['focus']}"
            for item in assignments
        ]
        ledger = "\n".join([
            "# Codex Control Team Ledger",
            "",
            f"Run: {run_id}",
            f"Created: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"Local project: {self.selected_project()}",
            "",
            "Communication protocol:",
            "- Every lane reads this ledger before acting.",
            "- Every lane reads available files in `out/` before finalizing.",
            "- Team chat lives at `out/team-chat.md`; post concise updates here as status changes.",
            "- Every lane writes a concise handoff to `out/<lane>.handoff.md`.",
            "- Collected outputs are pulled back to this run folder with Collect Team.",
            "- No secrets, tokens, passwords, sudo codes, or private credentials go into prompts, logs, or handoffs.",
            "",
            "Assignments:",
            *assignment_lines,
            "",
            "Shared mission:",
            base_prompt.strip(),
            "",
        ])
        self.write_private_text(team_dir / "team-ledger.md", ledger)
        for assignment in assignments:
            device = self.mesh_assignment_device(assignment)
            if device is None:
                continue
            teammates = tuple(
                f"{item['lane_title']} on {item['device_name']}"
                for item in assignments
                if item["lane_slug"] != assignment["lane_slug"]
            )
            prompt = team_prompt(
                lane_title=assignment["lane_title"],
                lane_slug=assignment["lane_slug"],
                focus=assignment["focus"],
                base_prompt=base_prompt,
                run_id=run_id,
                device=device,
                teammates=teammates,
                role_id=assignment.get("role_id", ""),
                role_title=assignment.get("role_title", ""),
                role_profile=assignment.get("role_profile", ""),
                role_focus=assignment.get("role_focus", ""),
                role_boundary=assignment.get("role_boundary", ""),
            )
            self.write_private_text(lanes_dir / f"{assignment['lane_slug']}.md", prompt)
        manifest = {
            "run_id": run_id,
            "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "project": self.selected_project(),
            "prompt_sha256": hashlib.sha256(base_prompt.encode("utf-8", errors="replace")).hexdigest(),
            "assignments": assignments,
        }
        self.write_private_text(team_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        write_role_bootstrap(team_dir, assignments=tuple(assignments))
        self.mesh_team_run_id = run_id
        self.mesh_team_dir = team_dir
        self.mesh_team_assignments = assignments
        self.mesh_team_last_bus_sent = 0
        self.mesh_team_last_bus_failures = []
        self.mesh_team_last_bus_path = None
        self.mesh_team_last_bus_report = None
        return team_dir

    def prepare_mesh_team_package(self, candidate_devices: tuple[DeviceRecord, ...] | None = None) -> bool:
        if hasattr(self, "memory_buffer"):
            self.persist_memory_from_editor()
        assignments = self.build_mesh_team_assignments(candidate_devices)
        if not assignments:
            self.set_mesh_team_status("No ready trusted devices. Run Check Fleet first.", "warn")
            self.set_status("No ready trusted devices", "warn")
            return False
        team_dir = self.write_mesh_team_package(assignments)
        self.render_mesh_team()
        self.set_mesh_team_status(f"Prepared {len(assignments)} lanes | {self.mesh_team_run_id} | {team_dir}")
        return True

    def load_mesh_team_dir(self, team_dir: Path) -> bool:
        if not team_dir.exists():
            return False
        status = inspect_team_run(team_dir)
        if not status.assignments:
            return False
        self.mesh_team_run_id = status.run_id
        self.mesh_team_dir = team_dir
        self.mesh_team_assignments = [dict(item) for item in status.assignments]
        self.mesh_team_last_bus_sent = 0
        self.mesh_team_last_bus_failures = []
        self.mesh_team_last_bus_path = None
        self.mesh_team_last_bus_report = None
        return True

    def on_load_latest_mesh_team(self, _button: Gtk.Button) -> None:
        team_dir = latest_team_run_dir(TEAM_DIR)
        if team_dir is None or not self.load_mesh_team_dir(team_dir):
            self.set_mesh_team_status("No saved team run found.", "warn")
            self.set_status("No saved team run found", "warn")
            return
        self.render_mesh_team()
        self.render_mesh_team_chat()
        self.set_status(f"Loaded Codex Team {self.mesh_team_run_id}")

    def on_open_mesh_team(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None:
            self.set_mesh_team_status("No team run to open.", "warn")
            self.set_status("No team run to open", "warn")
            return
        subprocess.Popen(["xdg-open", str(self.mesh_team_dir)], start_new_session=True)
        self.set_status("Opened team run folder")

    def on_copy_mesh_team_summary(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None:
            self.set_mesh_team_status("No team run to summarize.", "warn")
            self.set_status("No team run to summarize", "warn")
            return
        summary_path = write_team_summary(self.mesh_team_dir)
        self.copy_mesh_text(summary_path.read_text(encoding="utf-8", errors="replace"), "Team summary copied")
        self.render_mesh_team()

    def _team_bus_report(self) -> TeamBusReport | None:
        if self.mesh_team_dir is None:
            return None
        if self.mesh_team_last_bus_report is not None and str(self.mesh_team_last_bus_report.team_dir) == str(self.mesh_team_dir):
            return self.mesh_team_last_bus_report
        self.mesh_team_last_bus_report = load_bus_report(self.mesh_team_dir)
        return self.mesh_team_last_bus_report

    def on_copy_mesh_team_bus_report(self, _button: Gtk.Button) -> None:
        report = self._team_bus_report()
        if report is None:
            self.set_mesh_team_status("No bus report available. Sync the handoff bus first.", "warn")
            self.set_status("No bus report", "warn")
            return
        self.copy_mesh_text(json.dumps({
            "run_id": report.run_id,
            "team_dir": report.team_dir,
            "bus_path": report.bus_path,
            "sent": report.sent,
            "failures": report.failures,
            "generated": report.generated,
            "generated_epoch": report.generated_epoch,
            "targets": [
                {
                    "lane_slug": item.lane_slug,
                    "device_name": item.device_name,
                    "target": item.target,
                    "status": item.status,
                    "detail": item.detail,
                    "artifact_path": item.artifact_path,
                    "artifact_sha256": item.artifact_sha256,
                    "artifact_remote_sha256": item.artifact_remote_sha256,
                    "ts": item.ts,
                }
                for item in report.targets
            ],
        }, indent=2, sort_keys=True), "Bus report copied")
        self.set_status(f"Copied bus report for {report.run_id}")

    def on_copy_role_bootstrap(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None:
            self.set_mesh_team_status("No team run to copy role bootstrap.", "warn")
            self.set_status("No team run to copy role bootstrap", "warn")
            return
        bootstrap_json = write_role_bootstrap(self.mesh_team_dir)
        bootstrap_md = bootstrap_json.with_name("role-bootstrap.md")
        if bootstrap_md.exists():
            text = bootstrap_md.read_text(encoding="utf-8", errors="replace")
        else:
            text = bootstrap_json.read_text(encoding="utf-8", errors="replace")
        self.copy_mesh_text(text, "Role bootstrap copied")
        self.set_status(f"Copied role bootstrap for {self.mesh_team_run_id}")
        self.render_mesh_team()

    def _bus_status_css(self, status: str) -> str:
        return {
            "local": "chip-strong",
            "synced": "chip-strong",
            "failed": "chip-danger",
            "stale": "chip-danger",
        }.get(status, "chip")

    def _file_sha256_hex(self, path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _is_valid_sha256(value: str) -> bool:
        return (
            len(value) == 64
            and all(char.lower() in "0123456789abcdef" for char in value.strip())
        )

    def _parse_remote_sha256(self, output: str) -> str:
        for token in output.strip().split():
            if self._is_valid_sha256(token):
                return token.lower()
        return ""

    def _remote_handoff_bus_sha256(self, device: DeviceRecord, bus_path: str) -> str:
        command = list(remote_file_sha256sum_command(device, bus_path))
        try:
            result = run_cmd(command, timeout=15)
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Bus hash probe failed on {device.name}: {exc}")
            return ""
        if result.returncode != 0:
            return ""
        return self._parse_remote_sha256(result.stdout)

    def _build_bus_target_status(
        self,
        assignment: dict[str, str],
        status: str,
        detail: str,
        bus_path: Path,
        remote_artifact_sha256: str = "",
    ) -> TeamBusTargetStatus:
        local_artifact_sha256 = self._file_sha256_hex(bus_path)
        if status == "local":
            remote_artifact_sha256 = local_artifact_sha256
        return TeamBusTargetStatus(
            lane_slug=assignment.get("lane_slug", ""),
            device_name=assignment.get("device_name", "unknown"),
            target=assignment.get("target", "unknown"),
            status=status,
            detail=detail,
            artifact_path=(
                f"{assignment.get('target', 'unknown')}:{remote_team_dir(self.mesh_team_run_id)}/out/handoff-bus.md"
                if self.mesh_team_run_id
                else str(bus_path)
            ),
            artifact_sha256=local_artifact_sha256,
            artifact_remote_sha256=remote_artifact_sha256,
            ts=int(time.time()),
        )

    def _bus_assignment_by_device(self, device_name: str) -> dict[str, str] | None:
        return next((item for item in self.mesh_team_assignments if item.get("device_name") == device_name), None)

    def _sync_mesh_bus_targets(
        self,
        assignments: list[dict[str, str]],
        bus_path: Path,
    ) -> tuple[tuple[TeamBusTargetStatus, ...], int, list[str]]:
        results: list[TeamBusTargetStatus] = []
        sent = 0
        errors: list[str] = []
        lock = threading.Lock()
        if not self.mesh_team_run_id:
            return (), 0, ["No run id"]
        run_id = self.mesh_team_run_id

        def sync_one(assignment: dict[str, str]) -> None:
            nonlocal sent
            device = self.mesh_assignment_device(assignment)
            if device is None:
                msg = f"{assignment.get('device_name', 'device')}: missing device record"
                with lock:
                    errors.append(msg)
                    results.append(self._build_bus_target_status(assignment, "failed", msg, bus_path))
                return
            if self.is_local_mesh_device(device):
                with lock:
                    sent += 1
                    result = self._build_bus_target_status(assignment, "local", "local machine", bus_path)
                    results.append(result)
                return
            try:
                team_mkdir = run_cmd(list(ssh_mkdir_command(device, remote_team_dir(run_id))), timeout=20)
            except Exception as exc:  # noqa: BLE001
                msg = f"{device.name}: team mkdir failed: {exc}"
                with lock:
                    errors.append(msg)
                    results.append(self._build_bus_target_status(assignment, "failed", msg, bus_path))
                return
            if team_mkdir.returncode != 0:
                detail = (team_mkdir.stderr or team_mkdir.stdout or "mkdir failed").strip().splitlines()
                msg = f"{device.name}: team mkdir failed: {detail[-1] if detail else 'mkdir failed'}"
                with lock:
                    errors.append(msg)
                    results.append(self._build_bus_target_status(assignment, "failed", msg, bus_path))
                return
            try:
                result = run_cmd(list(rsync_team_package_command(self.mesh_team_dir, device, run_id)), timeout=35)
            except Exception as exc:  # noqa: BLE001
                msg = f"{device.name}: {exc}"
                with lock:
                    errors.append(msg)
                    results.append(self._build_bus_target_status(assignment, "failed", msg, bus_path))
                return
            if result.returncode == 0:
                artifact_path = f"{remote_team_dir(run_id)}/out/handoff-bus.md"
                remote_sha = self._remote_handoff_bus_sha256(device, artifact_path)
                with lock:
                    sent += 1
                    results.append(
                        self._build_bus_target_status(
                            assignment,
                            "synced",
                            f"{device.name}: synced" + ("" if remote_sha else " (remote hash unavailable)"),
                            bus_path,
                            remote_artifact_sha256=remote_sha,
                        )
                    )
                    if not remote_sha:
                        detail = f"{assignment.get('device_name', 'device')}: remote checksum could not be read"
                        errors.append(detail)
                        results[-1] = self._build_bus_target_status(
                            assignment,
                            "synced",
                            f"{device.name}: synced (remote hash unavailable)",
                            bus_path,
                            remote_artifact_sha256="",
                        )
            else:
                detail = (result.stderr or result.stdout or "rsync failed").strip().splitlines()
                msg = f"{device.name}: {detail[-1] if detail else 'rsync failed'}"
                with lock:
                    errors.append(msg)
                    results.append(self._build_bus_target_status(assignment, "failed", msg, bus_path))

        threads = [threading.Thread(target=sync_one, args=(assignment,), daemon=True) for assignment in assignments]
        for thread in threads:
            thread.start()
        for assignment, thread in zip(assignments, threads, strict=False):
            thread.join(42)
            if thread.is_alive():
                msg = f"{assignment.get('device_name', 'device')}: sync still running after timeout"
                with lock:
                    errors.append(msg)
                    results.append(self._build_bus_target_status(assignment, "failed", msg, bus_path))
        return tuple(results), sent, errors

    def finish_mesh_handoff_bus_sync(
        self,
        sent: int,
        bus_path: Path,
        errors: list[str],
        target_statuses: tuple[TeamBusTargetStatus, ...],
    ) -> bool:
        self.mesh_team_last_bus_sent = sent
        self.mesh_team_last_bus_failures = list(errors)
        self.mesh_team_last_bus_path = bus_path
        report: TeamBusReport | None = None
        if self.mesh_team_dir is not None:
            write_bus_report(
                self.mesh_team_dir,
                sent=sent,
                failures=errors,
                bus_path=bus_path,
                target_statuses=target_statuses,
            )
            self.mesh_team_last_bus_report = load_bus_report(self.mesh_team_dir)
            report = self.mesh_team_last_bus_report
        self.render_mesh_team()
        if errors:
            self.set_mesh_team_status(f"Handoff bus synced to {sent}; review needed: " + " | ".join(errors[:4]), "bad")
            self.set_status("Handoff bus sync needs review", "warn")
        else:
            self.set_mesh_team_status(f"Handoff bus synced to {sent} team device(s): {bus_path}")
            self.set_status(f"Synced handoff bus to {sent} device(s)")
        if report is not None:
            def verifier() -> None:
                checked = self._bus_targets_with_integrity(report)
                GLib.idle_add(self.finish_mesh_bus_verification, checked, report)

            threading.Thread(target=verifier, daemon=True).start()
        return False

    def on_sync_mesh_handoff_bus(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_assignments or not self.mesh_team_run_id:
            self.set_mesh_team_status("No team run to sync.", "warn")
            self.set_status("Prepare or load a team first", "warn")
            return
        team_dir = self.mesh_team_dir
        run_id = self.mesh_team_run_id
        assignments = list(self.mesh_team_assignments)
        bus_path = write_handoff_bus(team_dir)
        self.set_mesh_team_status(f"Syncing handoff bus for {run_id} to {len(assignments)} device(s)...")
        self.set_status("Syncing handoff bus")

        def worker() -> None:
            target_statuses, sent, errors = self._sync_mesh_bus_targets(assignments, bus_path)
            GLib.idle_add(self.finish_mesh_handoff_bus_sync, sent, bus_path, errors, target_statuses)

        threading.Thread(target=worker, daemon=True).start()

    def bus_failed_device_names(self) -> tuple[str, ...]:
        names: set[str] = set()
        report = self._team_bus_report()
        if report is not None:
            for target in report.targets:
                if target.status in {"failed", "stale"}:
                    names.add(target.device_name)
        for error in self.mesh_team_last_bus_failures:
            if ":" in error:
                names.add(error.split(":", 1)[0].strip())
        return tuple(sorted(names))

    def bus_repair_assignments(self) -> tuple[dict[str, str], ...]:
        if self.mesh_team_dir is None:
            return ()
        fail_names = set(self.bus_failed_device_names())
        if not fail_names:
            return ()
        return tuple(
            assignment
            for assignment in self.mesh_team_assignments
            if assignment.get("device_name", "") in fail_names
        )

    def on_preview_mesh_bus_repair(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_assignments:
            self.set_mesh_team_status("No team run loaded for repair preview.", "warn")
            self.set_status("Prepare or load a team first", "warn")
            return
        repair_assignments = self.bus_repair_assignments()
        if not repair_assignments:
            self.set_mesh_team_status("No bus repair targets to preview.", "warn")
            self.set_status("No bus repair targets", "warn")
            return
        report = self._team_bus_report()
        status_map = {item.device_name: item for item in (report.targets if report is not None else ())}
        lines = [
            "# Bus Repair Preview",
            "",
            f"Team run: {self.mesh_team_run_id}",
            f"Candidates: {len(repair_assignments)}",
            "",
            "Targets to retry:",
        ]
        for assignment in repair_assignments:
            device = assignment.get("device_name", "unknown")
            status = "failed"
            detail = "unknown"
            target = assignment.get("target", "")
            match = status_map.get(device)
            if match is not None:
                status = match.status
                detail = match.detail
            lines.append(f"- {device} | {target} | {status} | {detail}")
        if report is None and self.mesh_team_last_bus_failures:
            lines.extend([
                "",
                "Recent failure details:",
                *[f"- {item}" for item in self.mesh_team_last_bus_failures],
            ])
        text = "\n".join(lines)
        self.copy_mesh_text(text, f"Bus repair preview copied ({len(repair_assignments)} target(s))")
        self.set_mesh_team_status(f"Preview prepared for {len(repair_assignments)} repair target(s).")

    def on_retry_mesh_handoff_bus(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_assignments:
            self.set_mesh_team_status("No team run to retry.", "warn")
            self.set_status("Prepare or load a team first", "warn")
            return
        repair_assignments = list(self.bus_repair_assignments())
        if not repair_assignments:
            self.set_mesh_team_status("No failed bus targets to retry.", "warn")
            self.set_status("No failed bus targets to retry", "warn")
            return
        if not repair_assignments:
            self.set_mesh_team_status("No matching failed assignments to retry.", "warn")
            self.set_status("No matching failed assignments", "warn")
            return
        self.set_mesh_team_status(f"Retrying handoff bus for {len(repair_assignments)} failed device(s)...")
        self.set_status("Retrying handoff bus")

        def worker() -> None:
            if self.mesh_team_last_bus_path is None:
                bus_path = write_handoff_bus(self.mesh_team_dir)
            else:
                bus_path = self.mesh_team_last_bus_path
            target_statuses, sent, errors = self._sync_mesh_bus_targets(repair_assignments, bus_path)
            GLib.idle_add(self.finish_mesh_handoff_bus_sync, sent, bus_path, errors, target_statuses)

        threading.Thread(target=worker, daemon=True).start()

    def _bus_targets_with_integrity(self, report: TeamBusReport | None) -> tuple[TeamBusTargetStatus, ...]:
        if report is None:
            return ()
        bus_path = Path(report.bus_path)
        current_sha = self._file_sha256_hex(bus_path)
        if not current_sha:
            return report.targets
        updated: list[TeamBusTargetStatus] = []
        team_run_id = str(report.run_id)
        for target in report.targets:
            status = target.status
            detail = target.detail
            remote_artifact_sha256 = target.artifact_remote_sha256
            if status not in {"local", "synced", "stale"} and status != "failed":
                detail = f"{detail} | integrity check skipped"
                updated.append(
                    TeamBusTargetStatus(
                        lane_slug=target.lane_slug,
                        device_name=target.device_name,
                        target=target.target,
                        status=status,
                        detail=detail,
                        artifact_path=target.artifact_path,
                        artifact_sha256=target.artifact_sha256,
                        artifact_remote_sha256=target.artifact_remote_sha256,
                        ts=target.ts,
                    )
                )
                continue
            normalized_status = status
            if status == "stale":
                normalized_status = "synced"
            if status == "failed":
                updated.append(target)
                continue
            target_hash = target.artifact_sha256
            if not target_hash:
                updated.append(target)
                continue
            if target_hash != current_sha:
                normalized_status = "stale"
                detail = f"{detail} | checksum mismatch"
                updated.append(
                    TeamBusTargetStatus(
                        lane_slug=target.lane_slug,
                        device_name=target.device_name,
                        target=target.target,
                        status=normalized_status,
                        detail=detail,
                        artifact_path=target.artifact_path,
                        artifact_sha256=target.artifact_sha256,
                        artifact_remote_sha256=target.artifact_remote_sha256,
                        ts=target.ts,
                    )
                )
                continue
            if normalized_status == "synced":
                assignment = self._bus_assignment_by_device(target.device_name)
                device = self.mesh_assignment_device(assignment) if assignment is not None else None
                if device is None:
                    detail = f"{detail} | integrity target lookup failed"
                    updated.append(
                        TeamBusTargetStatus(
                            lane_slug=target.lane_slug,
                            device_name=target.device_name,
                            target=target.target,
                            status=status,
                            detail=detail,
                            artifact_path=target.artifact_path,
                            artifact_sha256=target.artifact_sha256,
                            artifact_remote_sha256=target.artifact_remote_sha256,
                            ts=target.ts,
                        )
                    )
                    continue
                remote_path = f"{remote_team_dir(team_run_id)}/out/handoff-bus.md"
                remote_hash = self._remote_handoff_bus_sha256(device, remote_path)
                if not remote_hash:
                    detail = f"{detail} | remote checksum unavailable"
                    updated.append(
                        TeamBusTargetStatus(
                            lane_slug=target.lane_slug,
                            device_name=target.device_name,
                            target=target.target,
                            status=status,
                            detail=detail,
                            artifact_path=target.artifact_path,
                            artifact_sha256=target.artifact_sha256,
                            artifact_remote_sha256=target.artifact_remote_sha256,
                            ts=target.ts,
                        )
                    )
                    continue
                expected_remote = target.artifact_remote_sha256 or target.artifact_sha256
                if remote_hash != expected_remote:
                    normalized_status = "stale"
                    detail = f"{detail} | remote checksum mismatch"
                remote_artifact_sha256 = remote_hash
            updated.append(TeamBusTargetStatus(
                lane_slug=target.lane_slug,
                device_name=target.device_name,
                target=target.target,
                status=normalized_status,
                detail=detail,
                artifact_path=target.artifact_path,
                artifact_sha256=target.artifact_sha256,
                artifact_remote_sha256=remote_artifact_sha256,
                ts=target.ts,
            ))
        return tuple(updated)

    def finish_mesh_bus_verification(
        self,
        target_statuses: tuple[TeamBusTargetStatus, ...],
        report: TeamBusReport | None,
    ) -> bool:
        if self.mesh_team_dir is None or report is None:
            self.set_mesh_team_status("No bus report to verify.", "bad")
            self.set_status("No bus report", "warn")
            return False
        baseline = tuple(report.failures or ())
        stale_failures = [
            f"{target.device_name}: {target.detail}"
            for target in target_statuses
            if target.status == "stale"
        ]
        seen = set()
        merged_failures = []
        for item in (*baseline, *stale_failures):
            if item not in seen:
                seen.add(item)
                merged_failures.append(item)
        self.mesh_team_last_bus_report = TeamBusReport(
            run_id=report.run_id,
            team_dir=report.team_dir,
            bus_path=report.bus_path,
            sent=report.sent,
            failures=tuple(merged_failures),
            generated=report.generated,
            generated_epoch=report.generated_epoch,
            targets=target_statuses,
        )
        write_bus_report(
            Path(report.team_dir),
            sent=report.sent,
            failures=list(merged_failures),
            bus_path=Path(report.bus_path),
            target_statuses=target_statuses,
        )
        self.render_mesh_team()
        if stale_failures:
            self.set_mesh_team_status(
                f"Bus verification found {len(stale_failures)} stale target(s): " + " | ".join(stale_failures[:4]),
                "bad",
            )
            self.set_status("Bus verification needs repair", "warn")
        else:
            self.set_mesh_team_status("Bus integrity verified. All synced targets match current bus artifact hash.")
        return False

    def on_verify_mesh_bus_integrity(self, _button: Gtk.Button) -> None:
        report = self._team_bus_report()
        if report is None:
            self.set_mesh_team_status("No bus report available. Sync the handoff bus first.", "warn")
            self.set_status("No bus report", "warn")
            return
        bus_path = Path(report.bus_path)
        if not bus_path.exists():
            self.set_mesh_team_status(f"Bus artifact missing: {bus_path}", "bad")
            self.set_status("Bus artifact missing", "warn")
            return
        self.set_mesh_team_status("Verifying bus integrity across local and remote targets...")
        self.set_status("Verifying handoff bus integrity")

        def worker() -> None:
            checked = self._bus_targets_with_integrity(report)
            GLib.idle_add(self.finish_mesh_bus_verification, checked, report)

        threading.Thread(target=worker, daemon=True).start()

    def render_mesh_team(self) -> None:
        if not hasattr(self, "mesh_team_list"):
            return
        self.refresh_mesh_action_sensitivity()
        self.clear_listbox(self.mesh_team_list)
        if not self.mesh_team_assignments:
            row = Gtk.ListBoxRow()
            row.add_css_class("team-row")
            row.set_child(self.label("No prepared team yet. Check Fleet, then Prepare Team.", "muted", wrap=True))
            self.mesh_team_list.append(row)
            if hasattr(self, "mesh_team_status_label") and not self.mesh_team_run_id:
                ready = len(self.ready_mesh_devices())
                saved = len(team_run_dirs(TEAM_DIR))
                self.mesh_team_status_label.set_text(
                    f"{ready} ready trusted device(s). {saved} saved team run(s). Prepare Team creates lanes and prompts."
                )
            return
        run_status = inspect_team_run(self.mesh_team_dir) if self.mesh_team_dir is not None else None
        if hasattr(self, "mesh_team_status_label"):
            if run_status is not None:
                bus_report = self._team_bus_report()
                bus_suffix = ""
                if bus_report is not None and bus_report.targets:
                    stale = getattr(bus_report, "stale_count", 0)
                    bus_suffix = (
                        f" | bus {bus_report.synced_count} synced / {bus_report.failed_count} failed"
                        f" / {stale} stale of {len(bus_report.targets)}"
                    )
                self.mesh_team_status_label.set_text(f"{run_status.summary_line()} | {self.mesh_team_dir}{bus_suffix}")
            else:
                self.mesh_team_status_label.set_text(
                    f"{len(self.mesh_team_assignments)} lane(s) | {self.mesh_team_run_id} | {self.mesh_team_dir}"
                )
        lanes = list(run_status.lanes) if run_status is not None else []
        if not lanes:
            for assignment in self.mesh_team_assignments:
                lanes.append(type("Lane", (), {
                    "lane_slug": assignment.get("lane_slug", ""),
                    "lane_title": assignment.get("lane_title", "Lane"),
                    "device_name": assignment.get("device_name", "device"),
                    "focus": assignment.get("focus", ""),
                    "status": "prepared",
                    "detail": "waiting for launch",
                })())
        for lane in lanes:
            assignment = next(
                (item for item in self.mesh_team_assignments if item.get("lane_slug") == lane.lane_slug),
                {},
            )
            bus_report = self._team_bus_report()
            bus_status = bus_report.target_for_device(lane.device_name) if bus_report is not None else None
            row = Gtk.ListBoxRow()
            row.add_css_class("team-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(f"{lane.lane_title} | {lane.device_name}", "row-title")
            title.set_hexpand(True)
            top.append(title)
            top.append(self.chip_label(lane.status, self.chip_css_for_status(lane.status)))
            if assignment.get("role_id"):
                role_title = assignment.get("role_title", "") or assignment.get("role_id", "")
                top.append(self.chip_label(role_title.replace("-", " ").title(), "chip"))
            if bus_status is not None:
                top.append(self.chip_label(f"bus: {bus_status.status}", self._bus_status_css(bus_status.status)))
            content.append(top)
            content.append(self.label(lane.focus, "muted", wrap=True))
            detail = lane.detail
            if getattr(lane, "handoff_bytes", 0) or getattr(lane, "final_bytes", 0):
                detail += f" | handoff {getattr(lane, 'handoff_bytes', 0)} bytes | final {getattr(lane, 'final_bytes', 0)} bytes"
            if bus_status is not None:
                detail += f" | comm: {bus_status.detail}"
            else:
                detail += " | comm: not synced"
            content.append(self.label(detail, "muted", wrap=True))
            target = self.label(
                f"{assignment.get('target', 'target unknown')} | {assignment.get('project_root', 'project unknown')}",
                "muted",
            )
            target.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            content.append(target)
            row.set_child(content)
            self.mesh_team_list.append(row)

    def set_mesh_team_status(self, text: str, level: str = "ok") -> None:
        if hasattr(self, "mesh_team_status_label"):
            self.mesh_team_status_label.set_text(text)
            for css_class in ["muted", "danger-text", "warn"]:
                self.mesh_team_status_label.remove_css_class(css_class)
            if level == "bad":
                self.mesh_team_status_label.add_css_class("danger-text")
            else:
                self.mesh_team_status_label.add_css_class("muted")

    def apply_mesh_probe(self, device_id_value: str, probe: DeviceProbe) -> bool:
        self.mesh_probe_records[device_id_value] = probe
        updated_devices: list[DeviceRecord] = []
        updated_device: DeviceRecord | None = None
        for device in self.devices:
            if device.id == device_id_value:
                updated_device = update_device_from_probe(device, probe)
                updated_devices.append(updated_device)
            else:
                updated_devices.append(device)
        self.devices = tuple(updated_devices)
        if updated_device is not None and self.selected_device is not None and self.selected_device.id == updated_device.id:
            self.selected_device = updated_device
        self.persist_devices()
        self.render_mesh()
        device_name = updated_device.name if updated_device is not None else device_id_value
        self.set_status(f"Fleet probe {device_name}: {probe.status}")
        return False

    def finish_mesh_probe(self, checked: int) -> bool:
        ready = len(self.ready_mesh_devices())
        self.set_mesh_team_status(f"Fleet check complete | {ready} ready trusted device(s) of {checked} checked")
        self.set_status(f"Fleet check complete: {ready} ready")
        self.render_mesh_team()
        return False

    def tailnet_discovery_defaults(self) -> tuple[str, str, str]:
        form_user = self.device_user_entry.get_text().strip() if hasattr(self, "device_user_entry") else ""
        project_root = (
            self.device_project_entry.get_text().strip()
            if hasattr(self, "device_project_entry")
            else "~/Projects/codex-gui"
        )
        codex_bin = (
            self.device_codex_entry.get_text().strip()
            if hasattr(self, "device_codex_entry")
            else "~/.local/bin/codex"
        )
        return form_user or os.environ.get("USER", ""), project_root, codex_bin

    def finish_tailnet_discovery(self, discovered: tuple[DeviceRecord, ...], error: str = "") -> bool:
        if error:
            detail = error.strip().splitlines()[-1] if error.strip() else "tailscale discovery failed"
            self.set_mesh_team_status(f"Tailnet discovery failed: {detail}", "bad")
            self.set_status("Tailnet discovery failed", "bad")
            return False
        if not discovered:
            self.set_mesh_team_status("No Tailnet devices found.", "warn")
            self.set_status("No Tailnet devices found", "warn")
            return False
        self.devices = merge_discovered_devices(self.devices, discovered)
        if self.selected_device is None or all(device.id != self.selected_device.id for device in self.devices):
            self.selected_device = self.devices[0] if self.devices else None
        else:
            self.selected_device = next(
                (device for device in self.devices if self.selected_device is not None and device.id == self.selected_device.id),
                self.selected_device,
            )
        self.persist_devices()
        self.render_mesh()
        online = sum(1 for device in discovered if device.status != "offline")
        offline = len(discovered) - online
        self.set_mesh_team_status(
            f"Discovered {len(discovered)} Tailnet device(s): {online} online, {offline} offline. Run Check Fleet next."
        )
        self.set_status(f"Tailnet discovered: {online} online")
        return False

    def on_discover_tailnet(self, _button: Gtk.Button) -> None:
        user, project_root, codex_bin = self.tailnet_discovery_defaults()
        self.set_mesh_team_status("Discovering Tailnet devices from Tailscale...")
        self.set_status("Tailnet discovery running")

        def worker() -> None:
            try:
                result = run_cmd(list(tailscale_status_command()), timeout=10)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self.finish_tailnet_discovery, (), str(exc))
                return
            if result.returncode != 0:
                GLib.idle_add(self.finish_tailnet_discovery, (), result.stderr or result.stdout or "tailscale status failed")
                return
            try:
                discovered = devices_from_tailscale_status_json(
                    result.stdout,
                    user=user,
                    project_root=project_root,
                    codex_bin=codex_bin,
                    include_self=True,
                    local_self_host="localhost",
                    include_offline=False,
                    worker_os=("linux", "macos"),
                )
            except (ValueError, json.JSONDecodeError) as exc:
                GLib.idle_add(self.finish_tailnet_discovery, (), str(exc))
                return
            GLib.idle_add(self.finish_tailnet_discovery, discovered, "")

            threading.Thread(target=worker, daemon=True).start()

    def probe_mesh_device(self, device: DeviceRecord) -> DeviceProbe:
        try:
            command = local_probe_command(device) if self.is_local_mesh_device(device) else ssh_probe_command(device)
            result = run_cmd(list(command), timeout=25)
            text = result.stdout
            if result.stderr:
                text += "\n[stderr]\n" + result.stderr
            return parse_probe_output(device, text, result.returncode)
        except subprocess.TimeoutExpired as exc:
            text = str(exc.stdout or "")
            if exc.stderr:
                text += "\n[stderr]\n" + str(exc.stderr)
            return parse_probe_output(device, text or "probe timed out", 124)
        except Exception as exc:  # noqa: BLE001
            return parse_probe_output(device, str(exc), 1)

    def finish_mesh_check(self, device: DeviceRecord, status: str) -> None:
        self.set_mesh_team_status(f"Checked {device.name}: {status}")

    def on_check_selected_device(self, _button: Gtk.Button) -> None:
        device = self.selected_mesh_device()
        if device is None:
            self.set_mesh_team_status("No device selected", "warn")
            self.set_status("Select a device", "warn")
            return
        self.set_mesh_team_status(f"Checking {device.name}...")

        def worker() -> None:
            probe = self.probe_mesh_device(device)
            GLib.idle_add(self.apply_mesh_probe, device.id, probe)
            GLib.idle_add(self.finish_mesh_check, device, probe.status)

        threading.Thread(target=worker, daemon=True).start()

    def _filtered_check_targets(self) -> tuple[DeviceRecord, ...]:
        readiness = mesh_readiness_report(self.devices, self.mesh_probe_records)
        return tuple(self._filtered_mesh_devices(readiness))

    def _trusted_devices_from(self, devices: tuple[DeviceRecord, ...]) -> tuple[DeviceRecord, ...]:
        return tuple(device for device in devices if self.trusted_mesh_device(device))

    def on_check_visible_devices(self, _button: Gtk.Button) -> None:
        targets = self._trusted_devices_from(self._filtered_check_targets())
        if not targets:
            self.set_mesh_team_status("No visible trusted devices to check.", "warn")
            self.set_status("No visible trusted devices", "warn")
            return
        self.set_mesh_team_status(f"Checking {len(targets)} visible trusted device(s)...")
        self.set_status("Mesh visible check running")

        def worker() -> None:
            for device in targets:
                probe = self.probe_mesh_device(device)
                GLib.idle_add(self.apply_mesh_probe, device.id, probe)
            GLib.idle_add(self.finish_mesh_probe, len(targets))

        threading.Thread(target=worker, daemon=True).start()

    def on_check_fleet(self, _button: Gtk.Button) -> None:
        targets = tuple(device for device in self.devices if self.trusted_mesh_device(device))
        if not targets:
            self.set_mesh_team_status("No trusted devices to check.", "warn")
            self.set_status("No trusted devices", "warn")
            return
        self.set_mesh_team_status(f"Checking {len(targets)} trusted device(s)...")
        self.set_status("Fleet check running")

        def worker() -> None:
            for device in targets:
                probe = self.probe_mesh_device(device)
                GLib.idle_add(self.apply_mesh_probe, device.id, probe)
            GLib.idle_add(self.finish_mesh_probe, len(targets))

        threading.Thread(target=worker, daemon=True).start()

    def on_prepare_mesh_team(self, _button: Gtk.Button) -> None:
        if self.prepare_mesh_team_package():
            self.set_status(f"Prepared Codex Team {self.mesh_team_run_id}")
            self.render_mesh_team_chat()

    def on_prepare_visible_mesh_team(self, _button: Gtk.Button) -> None:
        candidate_devices = self._mesh_team_seed_devices()
        if not candidate_devices:
            self.set_mesh_team_status("No visible devices to prepare from current filter set.", "warn")
            self.set_status("No visible devices to prepare", "warn")
            return
        if not self.ready_mesh_devices(candidate_devices):
            self.set_mesh_team_status("No visible ready devices. Run Check Fleet or change filters.", "warn")
            self.set_status("No visible ready devices", "warn")
            return
        if self.prepare_mesh_team_package(candidate_devices):
            self.set_status(f"Prepared Codex Team {self.mesh_team_run_id} from visible devices")
            self.render_mesh_team_chat()

    def should_sync_project_to_device(self, device: DeviceRecord, project_path: Path) -> bool:
        if self.is_local_mesh_device(device):
            return False
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if device.host in local_hosts:
            try:
                return Path(device.project_root).expanduser().resolve() != project_path.resolve()
            except OSError:
                return True
        return True

    def sync_mesh_team_package(self, assignments: list[dict[str, str]], team_dir: Path, run_id: str) -> list[str]:
        errors: list[str] = []
        project_path = Path(self.selected_project()).expanduser()
        if not project_path.exists():
            return [f"local project missing: {project_path}"]
        for assignment in assignments:
            device = self.mesh_assignment_device(assignment)
            if device is None:
                errors.append(f"{assignment.get('device_name', 'device')}: missing device record")
                continue
            if self.is_local_mesh_device(device):
                continue
            if self.should_sync_project_to_device(device, project_path):
                try:
                    mkdir_result = run_cmd(list(ssh_mkdir_command(device, device.project_root)), timeout=20)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{device.name}: project mkdir failed: {exc}")
                    continue
                if mkdir_result.returncode != 0:
                    detail = (mkdir_result.stderr or mkdir_result.stdout or "mkdir failed").strip().splitlines()
                    errors.append(f"{device.name}: project mkdir failed: {detail[-1] if detail else 'mkdir failed'}")
                    continue
                try:
                    project_result = run_cmd(list(rsync_project_command(project_path, device)), timeout=60)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{device.name}: project sync failed: {exc}")
                    continue
                if project_result.returncode != 0:
                    detail = (project_result.stderr or project_result.stdout or "rsync failed").strip().splitlines()
                    errors.append(f"{device.name}: project sync failed: {detail[-1] if detail else 'rsync failed'}")
                    continue
            try:
                team_mkdir = run_cmd(list(ssh_mkdir_command(device, remote_team_dir(run_id))), timeout=20)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{device.name}: team mkdir failed: {exc}")
                continue
            if team_mkdir.returncode != 0:
                detail = (team_mkdir.stderr or team_mkdir.stdout or "mkdir failed").strip().splitlines()
                errors.append(f"{device.name}: team mkdir failed: {detail[-1] if detail else 'mkdir failed'}")
                continue
            try:
                result = run_cmd(list(rsync_team_package_command(team_dir, device, run_id)), timeout=45)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{device.name}: {exc}")
                continue
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "rsync failed").strip().splitlines()
                errors.append(f"{device.name}: {detail[-1] if detail else 'rsync failed'}")
        return errors

    def launch_mesh_team_sessions(self, assignments: list[dict[str, str]], run_id: str) -> bool:
        launched = 0
        for assignment in assignments:
            device = self.mesh_assignment_device(assignment)
            if device is None:
                continue
            title = f"{assignment['lane_title']} {device.name}"
            command = (
                list(local_agent_command(device, run_id, assignment["lane_slug"]))
                if self.is_local_mesh_device(device)
                else list(remote_agent_command(device, run_id, assignment["lane_slug"]))
            )
            self.launch_external(command, title, stamp=False)
            launched += 1
        self.set_mesh_team_status(f"Launched {launched} Codex team lane(s). Collect Team after terminals finish.")
        self.set_status(f"Launched {launched} team lane(s)")
        return False

    def mesh_team_launch_failed(self, errors: list[str]) -> bool:
        text = "Team sync failed: " + " | ".join(errors[:4])
        self.set_mesh_team_status(text, "bad")
        self.set_status("Team sync failed", "bad")
        return False

    def on_launch_mesh_team(self, _button: Gtk.Button) -> None:
        if (self.mesh_team_dir is None or not self.mesh_team_assignments) and not self.prepare_mesh_team_package():
            return
        assert self.mesh_team_dir is not None
        assignments = list(self.mesh_team_assignments)
        team_dir = self.mesh_team_dir
        run_id = self.mesh_team_run_id
        self.set_mesh_team_status(f"Syncing project and team package {run_id} to {len(assignments)} device(s)...")
        self.set_status("Syncing project and team package")

        def worker() -> None:
            errors = self.sync_mesh_team_package(assignments, team_dir, run_id)
            if errors:
                GLib.idle_add(self.mesh_team_launch_failed, errors)
                return
            GLib.idle_add(self.launch_mesh_team_sessions, assignments, run_id)

        threading.Thread(target=worker, daemon=True).start()

    def finish_mesh_collect(self, collected: int, errors: list[str]) -> bool:
        summary_path: Path | None = None
        if self.mesh_team_dir is not None:
            summary_path = write_team_summary(self.mesh_team_dir)
        self.render_mesh_team()
        if errors:
            self.set_mesh_team_status(f"Collected {collected}; review needed: " + " | ".join(errors[:4]), "bad")
            self.set_status("Team collection needs review", "warn")
        else:
            suffix = f" | summary {summary_path}" if summary_path is not None else ""
            self.set_mesh_team_status(f"Collected outputs from {collected} Codex team lane(s) into {self.mesh_team_dir}{suffix}")
            self.set_status(f"Collected {collected} team lane(s)")
        return False

    def on_collect_mesh_team(self, _button: Gtk.Button) -> None:
        if self.mesh_team_dir is None or not self.mesh_team_assignments or not self.mesh_team_run_id:
            self.set_mesh_team_status("No team package to collect.", "warn")
            self.set_status("Prepare or launch a team first", "warn")
            return
        assignments = list(self.mesh_team_assignments)
        team_dir = self.mesh_team_dir
        run_id = self.mesh_team_run_id
        self.set_mesh_team_status(f"Collecting team outputs for {run_id}...")
        self.set_status("Collecting team outputs")

        def worker() -> None:
            errors: list[str] = []
            collected = 0
            for assignment in assignments:
                device = self.mesh_assignment_device(assignment)
                if device is None:
                    errors.append(f"{assignment.get('device_name', 'device')}: missing device record")
                    continue
                if self.is_local_mesh_device(device):
                    collected += 1
                    continue
                try:
                    result = run_cmd(list(rsync_team_results_command(team_dir, device, run_id)), timeout=35)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{device.name}: {exc}")
                    continue
                if result.returncode == 0:
                    collected += 1
                else:
                    detail = (result.stderr or result.stdout or "rsync failed").strip().splitlines()
                    errors.append(f"{device.name}: {detail[-1] if detail else 'rsync failed'}")
            if self.mesh_team_run_id is not None:
                self.collect_team_chat_from_devices(team_dir, self.mesh_team_run_id)
            GLib.idle_add(self.finish_mesh_collect, collected, errors)

        threading.Thread(target=worker, daemon=True).start()

    def on_refresh_mesh(self, _button: Gtk.Button) -> None:
        self.devices = load_devices(DEVICES_FILE)
        if self.selected_device is not None and all(device.id != self.selected_device.id for device in self.devices):
            self.selected_device = self.devices[0] if self.devices else None
        self.memory_items = load_memory(MEMORY_FILE)
        self.render_mesh()
        self.set_status("Mesh refreshed")

    def on_new_device_form(self, _button: Gtk.Button) -> None:
        self.selected_device = None
        self.fill_device_form(None)
        self.render_mesh_detail()
        self.set_status("Device form cleared")

    def on_add_device(self, _button: Gtk.Button) -> None:
        device = self.device_from_form()
        if device is None:
            return
        self.devices = upsert_device(self.devices, device)
        self.selected_device = device
        self.persist_devices()
        self.render_mesh()
        self.set_status(f"Saved device {device.name}")

    def on_remove_device(self, _button: Gtk.Button) -> None:
        device = self.selected_mesh_device()
        if device is None:
            self.set_status("Select a device", "warn")
            return
        self.devices = remove_device(self.devices, device.id)
        self.selected_device = self.devices[0] if self.devices else None
        self.persist_devices()
        self.render_mesh()
        self.set_status(f"Removed {device.name}")

    def on_device_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        device = getattr(row, "device", None) if row is not None else None
        if device is None:
            return
        self.selected_device = device
        self.fill_device_form(device)
        self.render_mesh_detail()

    def copy_mesh_text(self, text: str, status: str) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(text)
        self.set_status(status)

    def on_copy_device_test(self, _button: Gtk.Button) -> None:
        device = self.selected_mesh_device()
        if device is None:
            self.set_status("Select a device", "warn")
            return
        self.copy_mesh_text(shell_join(list(ssh_test_command(device))), "SSH test copied")

    def on_copy_device_launch(self, _button: Gtk.Button) -> None:
        device = self.selected_mesh_device()
        if device is None:
            self.set_status("Select a device", "warn")
            return
        self.copy_mesh_text(shell_join(list(ssh_launch_command(device))), "Launch command copied")

    def on_sync_memory_to_device(self, _button: Gtk.Button) -> None:
        device = self.selected_mesh_device()
        if device is None:
            self.set_status("Select a device", "warn")
            return
        self.persist_memory_from_editor()
        self.render_mesh_detail()
        if self.is_local_mesh_device(device):
            self.set_status("Local memory saved")
            return
        self.launch_external(list(rsync_memory_command(MEMORY_FILE, device)), f"Sync {device.name}", stamp=False)

    def on_open_device_session(self, _button: Gtk.Button) -> None:
        device = self.selected_mesh_device()
        if device is None:
            self.set_status("Select a device", "warn")
            return
        self.launch_external(list(ssh_launch_command(device)), f"Codex {device.name}", stamp=False)

    def on_import_memory(self, _button: Gtk.Button) -> None:
        if not hasattr(self, "memory_import_entry"):
            return
        text = self.memory_import_entry.get_text().strip()
        if not text:
            self.set_status("Memory import is empty", "warn")
            return
        self.memory_items = import_memory_text(self.memory_items, text, source="import")
        self.memory_import_entry.set_text("")
        save_memory(MEMORY_FILE, self.memory_items)
        self.render_mesh()
        self.set_status("Memory imported")

    def on_save_memory(self, _button: Gtk.Button) -> None:
        self.persist_memory_from_editor()
        self.render_mesh_detail()
        self.set_status("Portable memory saved")

    def on_copy_memory(self, _button: Gtk.Button) -> None:
        text = self.text_from_buffer(self.memory_buffer) or memory_markdown(self.memory_items)
        self.copy_mesh_text(text, "Memory copied")

    def on_open_memory(self, _button: Gtk.Button) -> None:
        self.persist_memory_from_editor()
        subprocess.Popen(["xdg-open", str(MEMORY_FILE)], start_new_session=True)
        self.set_status("Opened memory file")

    def on_open_devices(self, _button: Gtk.Button) -> None:
        self.persist_devices()
        subprocess.Popen(["xdg-open", str(DEVICES_FILE)], start_new_session=True)
        self.set_status("Opened devices file")

    def build_projects_page(self) -> Gtk.Widget:
        box = self.page_box()
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.project_search = Gtk.SearchEntry()
        self.project_search.set_placeholder_text("Filter projects")
        self.project_search.connect("search-changed", lambda _w: self.render_projects())
        scan = Gtk.Button(label="Scan")
        scan.connect("clicked", lambda _b: self.refresh_projects())
        add_current = Gtk.Button(label="Use Active")
        add_current.connect("clicked", lambda _b: self.add_active_project())
        top.append(self.project_search)
        top.append(scan)
        top.append(add_current)
        box.append(top)

        self.projects_list = Gtk.ListBox()
        self.projects_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.projects_list.connect("row-activated", self.on_project_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.projects_list)
        box.append(scroller)
        return box

    def build_threads_page(self) -> Gtk.Widget:
        box = self.page_box()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.thread_search = Gtk.SearchEntry()
        self.thread_search.set_placeholder_text("Search local Codex threads")
        self.thread_search.connect("search-changed", lambda _w: self.refresh_threads())
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _b: self.refresh_threads())
        resume = Gtk.Button(label="Resume")
        resume.add_css_class("primary")
        resume.connect("clicked", self.on_resume_selected_thread)
        fork = Gtk.Button(label="Fork")
        fork.connect("clicked", self.on_fork_selected_thread)
        archive = Gtk.Button(label="Archive")
        archive.connect("clicked", self.on_archive_selected_thread)
        toolbar.append(self.thread_search)
        toolbar.append(refresh)
        toolbar.append(resume)
        toolbar.append(fork)
        toolbar.append(archive)
        box.append(toolbar)

        self.threads_list = Gtk.ListBox()
        self.threads_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.threads_list.connect("row-selected", self.on_thread_selected)
        self.threads_list.connect("row-activated", self.on_threads_row_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.threads_list)
        box.append(scroller)
        return box

    def build_git_page(self) -> Gtk.Widget:
        box = self.page_box()
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Status", self.on_git_status, True),
            ("Diff Stat", self.on_git_diff_stat, False),
            ("Recent Log", self.on_git_log, False),
            ("Worktrees", self.on_git_worktrees, False),
            ("Prune Worktrees", self.on_git_prune, False),
            ("Open Terminal", self.on_open_project_terminal, False),
        ]:
            button = Gtk.Button(label=label)
            if primary:
                button.add_css_class("primary")
            button.connect("clicked", handler)
            controls.append(button)
        box.append(controls)

        wt_panel = self.panel("Create Worktree")
        wt_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.worktree_name_entry = Gtk.Entry()
        self.worktree_name_entry.set_placeholder_text("worktree folder name")
        self.worktree_branch_entry = Gtk.Entry()
        self.worktree_branch_entry.set_placeholder_text("optional new branch")
        make = Gtk.Button(label="Create")
        make.connect("clicked", self.on_git_worktree_create)
        wt_row.append(self.worktree_name_entry)
        wt_row.append(self.worktree_branch_entry)
        wt_row.append(make)
        wt_panel.append(wt_row)
        box.append(wt_panel)

        self.git_view = self.code_text_view(editable=False)
        self.git_buffer = self.git_view.get_buffer()
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.git_view)
        box.append(scroller)
        return box

    def build_config_page(self) -> Gtk.Widget:
        box = self.page_box()
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Reload Config", self.on_reload_config, False),
            ("Save Config", self.on_save_config, True),
            ("Install Profiles", self.on_install_profiles, False),
            ("Refresh Profiles", self.on_refresh_profiles, False),
        ]:
            button = Gtk.Button(label=label)
            if primary:
                button.add_css_class("primary")
            button.connect("clicked", handler)
            buttons.append(button)
        box.append(buttons)

        profile_panel = self.panel("Profile Files")
        self.profile_list_label = self.label("", "muted", wrap=True)
        profile_panel.append(self.profile_list_label)
        box.append(profile_panel)

        self.config_view = self.code_text_view(editable=True)
        self.config_buffer = self.config_view.get_buffer()
        config_scroll = Gtk.ScrolledWindow()
        config_scroll.set_vexpand(True)
        config_scroll.set_child(self.config_view)
        box.append(config_scroll)
        return box

    def build_health_page(self) -> Gtk.Widget:
        box = self.page_box()

        self.launcher_health_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.launcher_health_banner.set_hexpand(True)
        self.launcher_health_banner.set_margin_top(8)
        self.launcher_health_banner.set_margin_bottom(4)
        self.launcher_health_banner.set_visible(False)

        self.launcher_health_banner_label = self.label(
            "Launcher diagnostics not yet run",
            "warning",
            wrap=True,
        )
        self.launcher_health_banner_label.set_xalign(0)
        self.launcher_health_banner.append(self.launcher_health_banner_label)

        self.launcher_health_banner_button = Gtk.Button(label="Repair Launcher")
        self.launcher_health_banner_button.connect("clicked", self.on_launcher_repair)
        self.launcher_health_banner_button.add_css_class("destructive-action")
        self.launcher_health_banner.append(self.launcher_health_banner_button)
        box.append(self.launcher_health_banner)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler, primary in [
            ("Run Doctor", self.on_run_doctor, True),
            ("Setup Check", self.on_run_setup_check, False),
            ("Launcher Diagnostics", self.on_launcher_diagnostics, False),
            ("Repair Launcher", self.on_launcher_repair, False),
            ("Update Codex", self.on_update_codex, False),
            ("Login", self.on_login_codex, False),
            ("App Server Start", self.on_app_server_start, False),
            ("App Server Stop", self.on_app_server_stop, False),
            ("App Server Version", self.on_app_server_version, False),
        ]:
            button = Gtk.Button(label=label)
            if primary:
                button.add_css_class("primary")
            button.connect("clicked", handler)
            buttons.append(button)
        box.append(buttons)

        headless_panel = self.panel("Headless Output")
        hrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stop = Gtk.Button(label="Stop Headless")
        stop.connect("clicked", self.on_stop_headless)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda _b: self.set_text(self.headless_buffer, ""))
        hrow.append(stop)
        hrow.append(clear)
        headless_panel.append(hrow)
        self.headless_view = self.code_text_view(editable=False)
        self.headless_buffer = self.headless_view.get_buffer()
        hs = Gtk.ScrolledWindow()
        hs.set_min_content_height(190)
        hs.set_child(self.headless_view)
        headless_panel.append(hs)
        box.append(headless_panel)

        doctor_panel = self.panel("Doctor and System")
        self.health_view = self.code_text_view(editable=False)
        self.health_buffer = self.health_view.get_buffer()
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.health_view)
        doctor_panel.append(scroller)
        box.append(doctor_panel)
        return box

    def wrap_scroll(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(child)
        return scroll

    def code_text_view(self, editable: bool) -> Gtk.TextView:
        view = Gtk.TextView()
        view.set_editable(editable)
        view.set_cursor_visible(editable)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_top_margin(8)
        view.set_bottom_margin(8)
        view.set_left_margin(8)
        view.set_right_margin(8)
        view.add_css_class("code-view")
        return view

    def form_row(self, label_text: str, widget: Gtk.Widget) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_valign(Gtk.Align.CENTER)
        label = Gtk.Label(label=label_text, xalign=0)
        label.set_size_request(92, -1)
        label.add_css_class("muted")
        if isinstance(widget, Gtk.Switch):
            widget.set_hexpand(False)
            widget.set_halign(Gtk.Align.END)
        else:
            widget.set_hexpand(True)
        row.append(label)
        row.append(widget)
        return row

    def profile_options(self) -> list[tuple[str, str]]:
        return [("none", "No profile")] + [(name, name) for name in profile_names()]

    def selected_project(self) -> str:
        if hasattr(self, "project_entry"):
            text = self.project_entry.get_text().strip()
            if text:
                return str(Path(text).expanduser())
        return str(DEFAULT_PROJECT if DEFAULT_PROJECT.exists() else Path.home())

    def selected_prompt(self) -> str:
        return self.text_from_buffer(self.prompt_buffer).strip()

    def selected_mode_label(self) -> str:
        profile = self.dropdown_value(self.profile_combo) if hasattr(self, "profile_combo") else self.config.get("profile", "none")
        web = self.dropdown_value(self.web_combo) if hasattr(self, "web_combo") else self.config.get("web", "config")
        sandbox = self.dropdown_value(self.sandbox_combo) if hasattr(self, "sandbox_combo") else self.config.get("sandbox", "config")
        approval = self.dropdown_value(self.approval_combo) if hasattr(self, "approval_combo") else self.config.get("approval", "config")
        if profile and profile != "none":
            suffix = " + live" if web == "live" else ""
            return f"{profile}{suffix}"
        if sandbox == "danger-full-access" and approval == "never":
            return "full access"
        return "config default"

    def selected_power_values(self) -> tuple[str, str, str]:
        profile = self.dropdown_value(self.profile_combo) if hasattr(self, "profile_combo") else self.config.get("profile", "maximum-power")
        reasoning = self.dropdown_value(self.reasoning_combo) if hasattr(self, "reasoning_combo") else self.config.get("reasoning", "config")
        sandbox = self.dropdown_value(self.sandbox_combo) if hasattr(self, "sandbox_combo") else self.config.get("sandbox", "config")
        approval = self.dropdown_value(self.approval_combo) if hasattr(self, "approval_combo") else self.config.get("approval", "config")
        web = self.dropdown_value(self.web_combo) if hasattr(self, "web_combo") else self.config.get("web", "live")

        if profile == "maximum-power":
            reasoning_label = "xhigh"
            sandbox_label = "full access"
            approval_label = "no approvals"
        else:
            reasoning_label = "config" if reasoning == "config" else str(reasoning)
            if sandbox == "danger-full-access":
                sandbox_label = "full access"
            elif sandbox == "config":
                sandbox_label = "config access"
            else:
                sandbox_label = str(sandbox)
            approval_label = "config approval" if approval == "config" else str(approval)
        search_label = "live search" if web == "live" else ("cached search" if web == "cached" else str(web))
        return reasoning_label, f"{sandbox_label} | {approval_label}", search_label

    def refresh_power_labels(self) -> None:
        if not hasattr(self, "power_mode_label"):
            return
        reasoning, access, search = self.selected_power_values()
        self.power_mode_label.set_text(self.selected_mode_label())
        self.power_reasoning_label.set_text(reasoning)
        self.power_sandbox_label.set_text(access)
        self.power_search_label.set_text(search)

    def current_operator_brief(self) -> OperatorBrief:
        profile = self.dropdown_value(self.profile_combo) if hasattr(self, "profile_combo") else str(self.config.get("profile") or "none")
        return build_operator_brief(
            project=self.selected_project(),
            profile=profile or "none",
            mode=self.selected_mode_label(),
            health=self.health_summary,
            snapshot=self.current_project_snapshot(),
            preflight=self.preflight_report,
            sessions=self.sessions,
            autopilot_records=self.autopilot_records,
            command_runs=self.command_runs,
            agent_runs=self.agent_runs,
            receipts=self.receipt_records,
        )

    def render_operator_brief(self) -> None:
        if not hasattr(self, "operator_title_label"):
            return
        brief = self.current_operator_brief()
        self.operator_brief = brief
        self.operator_title_label.set_text(brief.title)
        self.operator_subtitle_label.set_text(brief.subtitle)
        self.set_chip(self.operator_readiness_label, brief.readiness, self.chip_css_for_status(brief.readiness_status))
        self.set_button_text(self.operator_action_button, brief.next_action)
        for index, (title_label, value_label, detail_label) in enumerate(self.operator_signal_labels):
            if index >= len(brief.signals):
                title_label.set_text("")
                value_label.set_text("")
                detail_label.set_text("")
                continue
            signal = brief.signals[index]
            title_label.set_text(signal.title)
            value_label.set_text(signal.value)
            detail_label.set_text(signal.detail)
            if index < len(self.operator_signal_cards):
                card = self.operator_signal_cards[index]
                for css_class in ["signal-ok", "signal-review", "signal-bad"]:
                    card.remove_css_class(css_class)
                css_class = "signal-bad" if signal.status in {"blocked", "block", "failed", "bad", "stopped"} else ("signal-ok" if signal.status in {"ready", "ok", "prepared", "queued", "launched", "running", "done"} else "signal-review")
                card.add_css_class(css_class)

    def on_operator_action(self, button: Gtk.Button) -> None:
        action = (self.operator_brief or self.current_operator_brief()).next_action
        if action == "Open Preflight":
            self.on_show_preflight(button)
        elif action == "Prepare Autopilot":
            self.on_prepare_autopilot(button)
        elif action == "Track Autopilot":
            self.on_track_autopilot(button)
        elif action == "Save Session":
            self.on_save_workspace_session(button)
        else:
            self.on_run_embedded(button)

    def chip_css_for_status(self, status: str) -> str:
        if status in {"ready", "ok", "prepared", "queued", "launched", "running", "done", "passed", "opened", "focused", "dispatched", "finished", "collected"}:
            return "chip-strong"
        if status in {"blocked", "block", "failed", "bad", "stopped", "missing"}:
            return "chip-danger"
        if status == "next":
            return "mode-pill"
        return "chip"

    def set_chip(self, label: Gtk.Label, text: str, css: str) -> None:
        label.set_text(text)
        for item in ["chip", "chip-strong", "chip-danger", "mode-pill"]:
            label.remove_css_class(item)
        label.add_css_class(css)

    def current_context_packet(self) -> ContextPacket:
        plan = self.current_quality_plan()
        quality = self.active_quality_report(plan)
        preflight = self.preflight_report or self.build_current_preflight_report()
        mission = self.mission_blueprint
        if mission is None:
            try:
                mission = self.build_current_mission_blueprint()
            except Exception:  # noqa: BLE001
                mission = None
        packet = build_context_packet(
            project=self.selected_project(),
            prompt=self.selected_prompt(),
            mode=self.selected_mode_label(),
            snapshot=self.current_project_snapshot(),
            preflight=preflight,
            quality=quality,
            mission=mission,
            autopilot_records=self.autopilot_records,
            command_runs=self.command_runs,
            receipts=self.receipt_records,
        )
        self.context_packet = packet
        return packet

    def render_context_section_rows(self, listbox: Gtk.ListBox, packet: ContextPacket, compact: bool = False) -> None:
        self.clear_listbox(listbox)
        sections = packet.sections[:4] if compact else packet.sections
        for section in sections:
            row = Gtk.ListBoxRow()
            row.add_css_class("context-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(section.title, "context-section-title")
            title.set_hexpand(True)
            top.append(title)
            top.append(self.chip_label(section.status, self.chip_css_for_status(section.status)))
            detail_line = section.detail.strip().splitlines()[0] if section.detail.strip() else "ready"
            detail = self.label(detail_line[:180], "context-detail", wrap=True)
            content.append(top)
            content.append(detail)
            row.set_child(content)
            listbox.append(row)

    def render_context_packet(self) -> None:
        if not any(hasattr(self, name) for name in ["context_title_label", "context_page_title_label", "context_detail_buffer"]):
            return
        packet = self.current_context_packet()
        title = packet.title
        summary = packet.summary()
        for name in ["context_title_label", "context_page_title_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(title)
        for name in ["context_summary_label", "context_page_summary_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(summary)
        for name in ["context_score_label", "context_page_score_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), f"score {packet.score}", self.chip_css_for_status(packet.status))
        for name in ["context_status_label", "context_page_status_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), packet.status, self.chip_css_for_status(packet.status))
        if hasattr(self, "context_compact_list"):
            self.render_context_section_rows(self.context_compact_list, packet, compact=True)
        if hasattr(self, "context_page_list"):
            self.render_context_section_rows(self.context_page_list, packet, compact=False)
        self.set_text(getattr(self, "context_detail_buffer", None), packet.markdown())

    def on_refresh_context_packet(self, _button: Gtk.Button) -> None:
        self.context_packet = self.current_context_packet()
        self.render_context_packet()
        self.set_status("Context packet refreshed")

    def on_use_context_packet(self, _button: Gtk.Button) -> None:
        packet = self.current_context_packet()
        if self.prompt_buffer is not None:
            self.prompt_buffer.set_text(packet.launch_prompt())
        if "maximum-power" in profile_names():
            self.set_dropdown(self.profile_combo, "maximum-power")
            self.set_dropdown(self.web_combo, "live")
        self.set_dropdown(self.action_combo, "interactive")
        self.update_command_preview()
        self.set_status("Context packet applied as prompt")

    def on_copy_context_packet(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(self.current_context_packet().markdown())
        self.set_status("Context packet copied")

    def on_save_context_packet(self, _button: Gtk.Button) -> None:
        packet = self.current_context_packet()
        CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTEXT_FILE.write_text(packet.markdown(), encoding="utf-8")
        os.chmod(CONTEXT_FILE, 0o600)
        self.render_context_packet()
        self.set_status(f"Context saved: {CONTEXT_FILE.name}")

    def show_context_page(self) -> None:
        self.render_context_packet()
        self.show_page("context")

    def current_roadmap(self) -> Roadmap:
        plan = self.current_quality_plan()
        quality = self.active_quality_report(plan)
        preflight = self.preflight_report or self.build_current_preflight_report()
        context = self.context_packet
        if context is None:
            try:
                context = self.current_context_packet()
            except Exception:  # noqa: BLE001
                context = None
        mission = self.mission_blueprint
        if mission is None:
            try:
                mission = self.build_current_mission_blueprint()
            except Exception:  # noqa: BLE001
                mission = None
        roadmap = build_roadmap(
            project=self.selected_project(),
            prompt=self.selected_prompt(),
            snapshot=self.current_project_snapshot(),
            preflight=preflight,
            quality=quality,
            context=context,
            mission=mission,
            autopilot_records=self.autopilot_records,
            command_runs=self.command_runs,
            receipts=self.receipt_records,
        )
        self.roadmap = roadmap
        if self.selected_roadmap_milestone is None or all(item.id != self.selected_roadmap_milestone.id for item in roadmap.milestones):
            self.selected_roadmap_milestone = roadmap.next_milestone()
        return roadmap

    def render_roadmap_rows(self, listbox: Gtk.ListBox, roadmap: Roadmap, compact: bool = False) -> None:
        self.clear_listbox(listbox)
        rows = roadmap.milestones[:3] if compact else roadmap.milestones
        for milestone in rows:
            row = Gtk.ListBoxRow()
            row.milestone = milestone
            row.add_css_class("roadmap-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(milestone.title, "roadmap-row-title", wrap=True)
            title.set_hexpand(True)
            top.append(title)
            top.append(self.chip_label(milestone.status, self.chip_css_for_status(milestone.status)))
            meta = self.label(f"priority {milestone.priority} | impact {milestone.impact} | effort {milestone.effort}", "roadmap-detail")
            detail = self.label(milestone.outcome, "roadmap-detail", wrap=True)
            content.append(top)
            content.append(meta)
            content.append(detail)
            row.set_child(content)
            listbox.append(row)
            if self.selected_roadmap_milestone is not None and milestone.id == self.selected_roadmap_milestone.id:
                listbox.select_row(row)

    def roadmap_prompt_for_milestone(self, milestone: RoadmapMilestone) -> str:
        return "\n".join([
            "Use $best-upfront-codex.",
            "",
            f"Milestone: {milestone.title}",
            "",
            "Outcome:",
            milestone.outcome,
            "",
            "Why this is next:",
            *[f"- {signal}" for signal in milestone.signals],
            "",
            "Implementation request:",
            milestone.prompt.strip(),
            "",
            "Validation:",
            *[f"- {check}" for check in milestone.validation],
        ]).strip()

    def selected_roadmap_detail(self) -> str:
        roadmap = self.roadmap or self.current_roadmap()
        milestone = self.selected_roadmap_milestone or roadmap.next_milestone()
        if milestone is None:
            return roadmap.detail_text()
        return roadmap.detail_text() + "\n\n# Selected Milestone Prompt\n\n" + self.roadmap_prompt_for_milestone(milestone) + "\n"

    def render_roadmap(self) -> None:
        if not any(hasattr(self, name) for name in ["roadmap_title_label", "roadmap_page_title_label", "roadmap_detail_buffer"]):
            return
        roadmap = self.current_roadmap()
        next_item = roadmap.next_milestone()
        title = next_item.title if next_item is not None else roadmap.title
        summary = roadmap.summary()
        for name in ["roadmap_title_label", "roadmap_page_title_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(title)
        for name in ["roadmap_summary_label", "roadmap_page_summary_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(summary)
        for name in ["roadmap_score_label", "roadmap_page_score_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), f"score {roadmap.score}", self.chip_css_for_status(roadmap.status))
        for name in ["roadmap_status_label", "roadmap_page_status_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), roadmap.status, self.chip_css_for_status(roadmap.status))
        self.rendering_roadmap = True
        try:
            if hasattr(self, "roadmap_compact_list"):
                self.render_roadmap_rows(self.roadmap_compact_list, roadmap, compact=True)
            if hasattr(self, "roadmap_page_list"):
                self.render_roadmap_rows(self.roadmap_page_list, roadmap, compact=False)
        finally:
            self.rendering_roadmap = False
        self.set_text(getattr(self, "roadmap_detail_buffer", None), self.selected_roadmap_detail())

    def on_refresh_roadmap(self, _button: Gtk.Button) -> None:
        self.roadmap = self.current_roadmap()
        self.render_roadmap()
        self.set_status("Roadmap planned")

    def on_roadmap_milestone_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self.rendering_roadmap:
            return
        self.selected_roadmap_milestone = getattr(row, "milestone", None) if row is not None else None
        self.set_text(getattr(self, "roadmap_detail_buffer", None), self.selected_roadmap_detail())
        if self.selected_roadmap_milestone is not None:
            self.set_status(f"Selected {self.selected_roadmap_milestone.title}")

    def on_roadmap_milestone_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        milestone = getattr(row, "milestone", None)
        if milestone is not None:
            self.selected_roadmap_milestone = milestone
            self.on_use_next_roadmap_prompt(Gtk.Button())

    def on_use_next_roadmap_prompt(self, _button: Gtk.Button) -> None:
        roadmap = self.roadmap or self.current_roadmap()
        milestone = self.selected_roadmap_milestone or roadmap.next_milestone()
        if milestone is None:
            self.set_status("No roadmap milestone available", "warn")
            return
        prompt = self.roadmap_prompt_for_milestone(milestone)
        if self.prompt_buffer is not None:
            self.prompt_buffer.set_text(prompt)
        if "maximum-power" in profile_names():
            self.set_dropdown(self.profile_combo, "maximum-power")
            self.set_dropdown(self.web_combo, "live")
        self.set_dropdown(self.action_combo, "interactive")
        self.update_command_preview()
        self.set_status(f"Using roadmap prompt: {milestone.title}")

    def on_copy_roadmap(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set((self.roadmap or self.current_roadmap()).detail_text())
        self.set_status("Roadmap copied")

    def on_save_roadmap(self, _button: Gtk.Button) -> None:
        roadmap = self.roadmap or self.current_roadmap()
        ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROADMAP_FILE.write_text(roadmap.detail_text(), encoding="utf-8")
        os.chmod(ROADMAP_FILE, 0o600)
        self.render_roadmap()
        self.set_status(f"Roadmap saved: {ROADMAP_FILE.name}")

    def show_roadmap_page(self) -> None:
        self.render_roadmap()
        self.show_page("roadmap")

    def current_launch_package(self, surface: str | None = None) -> LaunchPackage:
        action = self.dropdown_value(self.action_combo) if hasattr(self, "action_combo") else str(self.config.get("action") or "interactive")
        action = action or "interactive"
        profile = self.dropdown_value(self.profile_combo) if hasattr(self, "profile_combo") else str(self.config.get("profile") or "none")
        surface_value = surface or ("headless" if action == "exec" else ("embedded" if Vte is not None and self.terminal is not None else "external"))
        command = tuple(self.build_command(action))
        plan = self.current_quality_plan()
        quality = self.active_quality_report(plan)
        preflight = self.preflight_report or self.build_current_preflight_report()
        context = self.context_packet
        if context is None:
            try:
                context = self.current_context_packet()
            except Exception:  # noqa: BLE001
                context = None
        roadmap = self.roadmap
        if roadmap is None:
            try:
                roadmap = self.current_roadmap()
            except Exception:  # noqa: BLE001
                roadmap = None
        receipt_auto = self.receipt_auto_switch.get_active() if hasattr(self, "receipt_auto_switch") else bool(self.config.get("receipt_auto", True))
        atlas_ready = atlas_binary(self.selected_atlas_root() or None) is not None
        package = build_launch_package(
            project=self.selected_project(),
            action=action,
            profile=profile or "none",
            surface=surface_value,
            command=command,
            prompt=self.selected_prompt(),
            preflight=preflight,
            quality=quality,
            context=context,
            roadmap=roadmap,
            receipt_auto=receipt_auto,
            atlas_ready=atlas_ready,
            embedded_terminal=Vte is not None and self.terminal is not None,
            external_terminal=first_terminal() is not None,
            recent_runs=len(self.command_runs),
            receipts=len(self.receipt_records),
        )
        self.launch_package = package
        return package

    def render_launch_step_rows(self, listbox: Gtk.ListBox, package: LaunchPackage, compact: bool = False) -> None:
        self.clear_listbox(listbox)
        steps = package.steps[:4] if compact else package.steps
        for step in steps:
            row = Gtk.ListBoxRow()
            row.add_css_class("orchestration-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(step.title, "orchestration-row-title")
            title.set_hexpand(True)
            top.append(title)
            top.append(self.chip_label(step.status, self.chip_css_for_status(step.status)))
            detail = self.label(step.detail.strip().splitlines()[0][:180] if step.detail.strip() else "ready", "orchestration-detail", wrap=True)
            content.append(top)
            content.append(detail)
            row.set_child(content)
            listbox.append(row)

    def render_launch_package(self) -> None:
        if not any(hasattr(self, name) for name in ["orchestration_title_label", "orchestration_page_title_label", "orchestration_detail_buffer"]):
            return
        package = self.current_launch_package()
        for name in ["orchestration_title_label", "orchestration_page_title_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(package.title)
        for name in ["orchestration_summary_label", "orchestration_page_summary_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(package.summary())
        for name in ["orchestration_score_label", "orchestration_page_score_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), f"score {package.score}", self.chip_css_for_status(package.status))
        for name in ["orchestration_status_label", "orchestration_page_status_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), package.status, self.chip_css_for_status(package.status))
        if hasattr(self, "orchestration_compact_list"):
            self.render_launch_step_rows(self.orchestration_compact_list, package, compact=True)
        if hasattr(self, "orchestration_page_list"):
            self.render_launch_step_rows(self.orchestration_page_list, package, compact=False)
        self.set_text(getattr(self, "orchestration_detail_buffer", None), package.detail_text())

    def on_prepare_launch_package(self, _button: Gtk.Button) -> None:
        package = self.current_launch_package()
        self.render_launch_package()
        self.set_status(f"Launch package {package.status}")

    def on_run_launch_package(self, button: Gtk.Button) -> None:
        package = self.current_launch_package()
        self.render_launch_package()
        if package.status == "blocked":
            self.set_status("Launch package is blocked", "warn")
            return
        action = self.dropdown_value(self.action_combo) or "interactive"
        if action == "exec":
            self.on_run_headless(button)
        else:
            self.run_embedded_command(self.build_command(action))
        self.set_status(f"Running package: {package.action}")

    def on_copy_launch_package(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set((self.launch_package or self.current_launch_package()).detail_text())
        self.set_status("Launch package copied")

    def on_save_launch_package(self, _button: Gtk.Button) -> None:
        package = self.launch_package or self.current_launch_package()
        ORCHESTRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ORCHESTRATION_FILE.write_text(package.detail_text(), encoding="utf-8")
        os.chmod(ORCHESTRATION_FILE, 0o600)
        self.render_launch_package()
        self.set_status(f"Launch package saved: {ORCHESTRATION_FILE.name}")

    def show_orchestration_page(self) -> None:
        self.render_launch_package()
        self.show_page("orchestrate")

    def current_project_snapshot(self) -> ProjectSnapshot | None:
        if self.project_snapshot is None:
            return None
        try:
            selected = Path(self.selected_project()).expanduser()
            scanned = Path(self.project_snapshot.path).expanduser()
        except OSError:
            return None
        return self.project_snapshot if selected == scanned else None

    def ensure_project_snapshot(self) -> ProjectSnapshot:
        snapshot = self.current_project_snapshot()
        if snapshot is not None:
            return snapshot
        snapshot = inspect_project(self.selected_project())
        self.project_snapshot = snapshot
        return snapshot

    def build_current_preflight_report(self) -> PreflightReport:
        receipt_auto = self.receipt_auto_switch.get_active() if hasattr(self, "receipt_auto_switch") else bool(self.config.get("receipt_auto", True))
        report = build_preflight_report(
            project=self.selected_project(),
            prompt=self.selected_prompt(),
            action=self.dropdown_value(self.action_combo) or "interactive",
            profile=self.dropdown_value(self.profile_combo) or "none",
            model=self.dropdown_value(self.model_combo) or "config",
            reasoning=self.dropdown_value(self.reasoning_combo) or "config",
            sandbox=self.dropdown_value(self.sandbox_combo) or "config",
            approval=self.dropdown_value(self.approval_combo) or "config",
            web=self.dropdown_value(self.web_combo) or "config",
            skip_git=self.skip_git_switch.get_active() if hasattr(self, "skip_git_switch") else True,
            receipt_auto=receipt_auto,
            codex_bin=self.codex_bin,
            codex_ready=codex_available(self.codex_bin),
            auth_summary=str(self.health_summary.get("auth", "unknown")),
            terminal_available=Vte is not None or first_terminal() is not None,
            embedded_terminal=Vte is not None,
            atlas_ready=atlas_binary(self.selected_atlas_root() or None) is not None,
            available_profiles=tuple(profile_names()),
            snapshot=self.current_project_snapshot(),
        )
        self.preflight_report = report
        return report

    def current_quality_plan(self) -> QualityPlan:
        desktop_file = Path.home() / ".local" / "share" / "applications" / "codex-gui.desktop"
        return build_quality_plan(
            project=self.selected_project(),
            snapshot=self.current_project_snapshot(),
            codex_bin=self.codex_bin,
            desktop_file=desktop_file,
        )

    def active_quality_report(self, plan: QualityPlan) -> QualityReport | None:
        if self.quality_report is None:
            return None
        try:
            report_project = Path(self.quality_report.project).expanduser()
            plan_project = Path(plan.project).expanduser()
        except OSError:
            return None
        return self.quality_report if report_project == plan_project else None

    def quality_plan_text(self, plan: QualityPlan) -> str:
        lines = ["# Codex Control Quality Gate Plan", f"Project: {plan.project}", "", "Checks:"]
        for check in plan.checks:
            lines.append(f"- {check.label}: {check.command_text()}")
        return "\n".join(lines) + "\n"

    def render_quality_check_rows(self, listbox: Gtk.ListBox, compact: bool = False) -> None:
        self.clear_listbox(listbox)
        plan = self.quality_plan or self.current_quality_plan()
        report = self.active_quality_report(plan)
        if report is not None and not self.quality_running:
            rows = list(report.checks)
        else:
            rows = list(plan.checks)
        if compact:
            rows = rows[:4]
        for item in rows:
            row = Gtk.ListBoxRow()
            row.add_css_class("quality-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(item.label, "quality-check-title")
            title.set_hexpand(True)
            status = getattr(item, "status", "running" if self.quality_running else "ready")
            top.append(title)
            top.append(self.chip_label(status, self.chip_css_for_status(status)))
            detail = self.label(item.command_text(), "quality-check-detail", wrap=True)
            content.append(top)
            content.append(detail)
            if isinstance(item, QualityCheckResult) and item.output_tail and not compact:
                output = self.label(item.output_tail.strip().splitlines()[-1][:160], "quality-check-detail", wrap=True)
                content.append(output)
            row.set_child(content)
            listbox.append(row)

    def render_quality_gate(self) -> None:
        if not hasattr(self, "quality_status_label") and not hasattr(self, "quality_page_summary_label"):
            return
        plan = self.current_quality_plan()
        self.quality_plan = plan
        report = self.active_quality_report(plan)
        if self.quality_running:
            summary = f"Running {len(plan.checks)} quality checks..."
            status = "running"
            score = "running"
        elif report is not None:
            summary = report.summary()
            status = report.status
            score = f"score {report.score}"
        else:
            summary = plan.summary()
            status = "ready"
            score = "not run"
        if hasattr(self, "quality_status_label"):
            self.quality_status_label.set_text(summary)
        if hasattr(self, "quality_page_summary_label"):
            self.quality_page_summary_label.set_text(summary)
            self.set_chip(self.quality_page_score_label, score, self.chip_css_for_status(status))
            self.set_chip(self.quality_page_status_label, status, self.chip_css_for_status(status))
        if hasattr(self, "quality_compact_list"):
            self.render_quality_check_rows(self.quality_compact_list, compact=True)
        if hasattr(self, "quality_page_list"):
            self.render_quality_check_rows(self.quality_page_list, compact=False)
        if hasattr(self, "quality_detail_buffer"):
            text = report.detail_text() if report is not None and not self.quality_running else self.quality_plan_text(plan)
            self.set_text(self.quality_detail_buffer, text)

    def on_refresh_quality_gate(self, _button: Gtk.Button) -> None:
        self.quality_plan = self.current_quality_plan()
        self.render_quality_gate()
        self.set_status("Quality plan refreshed")

    def on_run_quality_gate(self, _button: Gtk.Button) -> None:
        if self.quality_running:
            self.set_status("Quality gate is already running", "warn")
            return
        plan = self.current_quality_plan()
        self.quality_plan = plan
        self.quality_running = True
        self.render_quality_gate()
        self.set_status("Quality gate running")

        def worker() -> None:
            try:
                report = run_quality_plan(plan)
            except Exception as exc:  # noqa: BLE001
                report = QualityReport(
                    generated=int(dt.datetime.now().timestamp()),
                    project=plan.project,
                    status="failed",
                    score=0,
                    checks=(QualityCheckResult(
                        label="Quality gate",
                        command=("quality-gate",),
                        cwd=plan.project,
                        status="failed",
                        exit_code=1,
                        duration_ms=0,
                        output_tail=str(exc),
                    ),),
                )
            GLib.idle_add(self.apply_quality_report, report)
        threading.Thread(target=worker, daemon=True).start()

    def apply_quality_report(self, report: QualityReport) -> bool:
        self.quality_report = report
        self.quality_running = False
        save_quality_report(QUALITY_FILE, report)
        self.render_quality_gate()
        self.render_context_packet()
        self.render_roadmap()
        self.set_status("Quality gate passed" if report.status == "passed" else "Quality gate failed", "ok" if report.status == "passed" else "warn")
        return False

    def on_copy_quality_report(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        plan = self.current_quality_plan()
        report = self.active_quality_report(plan)
        if report is not None:
            display.get_clipboard().set(report.detail_text())
            self.set_status("Quality report copied")
        else:
            display.get_clipboard().set(self.quality_plan_text(plan))
            self.set_status("Quality plan copied")

    def refresh_preflight(self) -> None:
        report = self.build_current_preflight_report()
        self.render_preflight(report)

    def render_preflight_list(self, listbox: Gtk.ListBox, report: PreflightReport, compact: bool = False) -> None:
        self.clear_listbox(listbox)
        checks = list(report.checks)
        if compact:
            priority = {"block": 0, "warn": 1, "note": 2, "ok": 3}
            checks = sorted(checks, key=lambda check: priority.get(check.status, 4))[:4]
        for check in checks:
            row = Gtk.ListBoxRow()
            row.add_css_class("preflight-check-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(check.title, "preflight-check-title")
            title.set_hexpand(True)
            chip = self.chip_label(check.status, self.chip_css_for_status(check.status))
            top.append(title)
            top.append(chip)
            detail = self.label(check.detail, "preflight-check-detail", wrap=True)
            content.append(top)
            content.append(detail)
            row.set_child(content)
            listbox.append(row)

    def render_preflight(self, report: PreflightReport | None = None) -> None:
        report = report or self.preflight_report or self.build_current_preflight_report()
        for name in ["preflight_summary_label", "preflight_page_summary_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(report.summary())
        for name in ["preflight_score_label", "preflight_page_score_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), f"score {report.score}", self.chip_css_for_status(report.status))
        for name in ["preflight_status_label", "preflight_page_status_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), report.status, self.chip_css_for_status(report.status))
        if hasattr(self, "preflight_hint_label"):
            notable = [check.title for check in report.checks if check.status != "ok"][:4]
            self.preflight_hint_label.set_text("Watch: " + ", ".join(notable) if notable else "All preflight checks are clean.")
        if hasattr(self, "preflight_compact_list"):
            self.render_preflight_list(self.preflight_compact_list, report, compact=True)
        if hasattr(self, "preflight_page_list"):
            self.render_preflight_list(self.preflight_page_list, report, compact=False)
        self.set_text(getattr(self, "preflight_detail_buffer", None), report.detail_text())
        self.render_operator_brief()

    def on_refresh_preflight(self, _button: Gtk.Button) -> None:
        self.refresh_preflight()
        report = self.preflight_report
        self.set_status(report.summary() if report is not None else "Preflight refreshed")

    def on_show_preflight(self, _button: Gtk.Button) -> None:
        self.refresh_preflight()
        self.show_page("preflight")

    def on_copy_preflight(self, _button: Gtk.Button) -> None:
        self.refresh_preflight()
        display = Gdk.Display.get_default()
        if display is not None and self.preflight_report is not None:
            display.get_clipboard().set(self.preflight_report.detail_text())
            self.set_status("Preflight copied")

    def build_current_mission_blueprint(self) -> MissionBlueprint:
        prompt = self.selected_prompt()
        snapshot = self.ensure_project_snapshot()
        context = self.project_context_text()
        variants = enhance_prompt(prompt, context)
        preflight = self.build_current_preflight_report()
        project = self.selected_project()
        root = git_root(project)
        plan = build_agent_plan(
            project,
            prompt,
            context,
            is_git=bool(root),
            git_root=root,
        )
        blueprint = build_mission_blueprint(
            prompt=prompt,
            variants=variants,
            snapshot=snapshot,
            preflight=preflight,
            agent_plan=plan,
        )
        self.mission_blueprint = blueprint
        return blueprint

    def refresh_mission_blueprint(self) -> None:
        blueprint = self.build_current_mission_blueprint()
        self.render_mission_blueprint(blueprint)

    def render_mission_list(self, listbox: Gtk.ListBox, blueprint: MissionBlueprint) -> None:
        self.clear_listbox(listbox)
        for phase in blueprint.phases:
            row = Gtk.ListBoxRow()
            row.add_css_class("mission-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(phase.title, "mission-row-title")
            title.set_hexpand(True)
            chip = self.chip_label(phase.status, self.chip_css_for_status(phase.status))
            top.append(title)
            top.append(chip)
            content.append(top)
            content.append(self.label(phase.detail, "mission-detail", wrap=True))
            row.set_child(content)
            listbox.append(row)

    def render_mission_blueprint(self, blueprint: MissionBlueprint | None = None) -> None:
        blueprint = blueprint or self.mission_blueprint or self.build_current_mission_blueprint()
        autopilot = self.build_current_autopilot_plan(blueprint)
        for name in ["mission_title_label", "mission_page_title_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(blueprint.headline)
        for name in ["mission_score_label", "mission_page_score_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), f"score {blueprint.score}", self.chip_css_for_status(blueprint.status))
        for name in ["mission_status_label", "mission_page_status_label"]:
            if hasattr(self, name):
                self.set_chip(getattr(self, name), blueprint.status, self.chip_css_for_status(blueprint.status))
        meta = (
            f"{blueprint.recommended_prompt_title} -> {blueprint.recommended_action} "
            f"| {len(blueprint.agents)} lanes | {len(blueprint.validation)} checks"
        )
        for name in ["mission_meta_label", "mission_page_meta_label"]:
            if hasattr(self, name):
                getattr(self, name).set_text(meta)
        if hasattr(self, "mission_page_list"):
            self.render_mission_list(self.mission_page_list, blueprint)
        detail = blueprint.detail_text() + "\n\n" + autopilot.detail_text()
        self.set_text(getattr(self, "mission_detail_buffer", None), detail)
        self.render_context_packet()
        self.render_roadmap()

    def mission_recommended_variant(self) -> PromptVariant | None:
        blueprint = self.mission_blueprint or self.build_current_mission_blueprint()
        for variant in enhance_prompt(self.selected_prompt(), self.project_context_text()):
            if variant.id == blueprint.recommended_prompt_id:
                return variant
        return None

    def build_current_autopilot_plan(self, blueprint: MissionBlueprint | None = None) -> AutopilotPlan:
        blueprint = blueprint or self.mission_blueprint or self.build_current_mission_blueprint()
        variant = self.mission_recommended_variant()
        prompt = variant.prompt if variant is not None else self.selected_prompt()
        self.autopilot_prompt = prompt
        snapshot = self.current_project_snapshot()
        validations = tuple(command.command for command in snapshot.commands[:4]) if snapshot is not None else ()
        plan = build_autopilot_plan(
            blueprint=blueprint,
            project=self.selected_project(),
            prompt=prompt,
            codex_bin=self.codex_bin,
            common_args=self.common_args_for_project(self.selected_project(), blueprint.recommended_profile),
            skip_git=self.skip_git_switch.get_active() if hasattr(self, "skip_git_switch") else True,
            artifacts_root=AUTOPILOT_DIR,
            validation_commands=validations,
        )
        self.autopilot_plan = plan
        return plan

    def on_architect_mission(self, _button: Gtk.Button) -> None:
        self.refresh_project_snapshot_async()
        self.refresh_mission_blueprint()
        blueprint = self.mission_blueprint
        self.set_status(blueprint.summary() if blueprint is not None else "Mission architected")

    def on_show_mission(self, _button: Gtk.Button) -> None:
        self.refresh_mission_blueprint()
        self.show_page("mission")

    def on_use_mission_prompt(self, _button: Gtk.Button) -> None:
        variant = self.mission_recommended_variant()
        if variant is None:
            self.set_status("No mission prompt available", "warn")
            return
        self.apply_prompt_variant(variant)
        self.set_status(f"Using mission prompt: {variant.title}")

    def on_copy_mission_blueprint(self, _button: Gtk.Button) -> None:
        self.refresh_mission_blueprint()
        display = Gdk.Display.get_default()
        if display is not None and self.mission_blueprint is not None:
            detail = self.mission_blueprint.detail_text()
            if self.autopilot_plan is not None:
                detail += "\n\n" + self.autopilot_plan.detail_text() + "\n\nScript:\n" + self.autopilot_plan.script()
            if self.selected_autopilot_record is not None:
                detail += "\n\n" + autopilot_detail(self.selected_autopilot_record)
            display.get_clipboard().set(detail)
            self.set_status("Mission blueprint copied")

    def on_run_autopilot(self, _button: Gtk.Button) -> None:
        self.refresh_mission_blueprint()
        blueprint = self.mission_blueprint
        if blueprint is not None and blueprint.status == "blocked":
            self.set_status("Autopilot blocked by preflight", "warn")
            self.show_page("mission")
            return
        record = self.prepare_current_autopilot_record(
            status="launched",
            note="Launched in embedded terminal",
            show_status=False,
        )
        plan = self.autopilot_plan or self.build_current_autopilot_plan(blueprint)
        if record is None:
            self.set_status("Autopilot package unavailable", "bad")
            return
        self.stamp_command_receipt(list(plan.main_command), "autopilot", surface="autopilot", run_status="launched")
        self.run_embedded_command(["bash", record.script_path])
        self.set_status("Autopilot running")

    def persist_autopilot_records(self) -> None:
        save_autopilot_records(AUTOPILOT_RECORDS_FILE, self.autopilot_records)

    def refresh_autopilot_records(self) -> None:
        selected_id = self.selected_autopilot_record.id if self.selected_autopilot_record else ""
        self.autopilot_records = load_autopilot_records(AUTOPILOT_RECORDS_FILE)
        self.selected_autopilot_record = next(
            (record for record in self.autopilot_records if record.id == selected_id),
            self.autopilot_records[0] if self.autopilot_records else None,
        )

    def autopilot_record_detail_text(self, record: AutopilotRecord | None, mode: str = "summary") -> str:
        detail = autopilot_detail(record)
        if record is None:
            return detail
        additions: list[str] = []
        for title, filename, limit in [
            ("Manifest", record.manifest_path, 5000),
            ("Blueprint", record.blueprint_path, 12000),
            ("Final Answer", record.final_path, 12000),
            ("Log Tail", record.log_path, 18000),
        ]:
            if mode == "log" and title != "Log Tail":
                continue
            if mode == "final" and title != "Final Answer":
                continue
            path = Path(filename)
            if path.exists():
                text = tail_text(path, limit=limit)
                additions.extend(["", f"{title}:", text or "(empty)"])
        return detail + ("\n" + "\n".join(additions) if additions else "")

    def render_autopilot_list(self, listbox: Gtk.ListBox, compact: bool = False) -> None:
        self.clear_listbox(listbox)
        records = self.autopilot_records[:8 if compact else 60]
        if not records:
            row = Gtk.ListBoxRow()
            row.add_css_class("autopilot-row")
            row.set_child(self.label("No Autopilot packages yet", "autopilot-meta"))
            listbox.append(row)
            return
        for record in records:
            row = Gtk.ListBoxRow()
            row.record = record
            row.add_css_class("autopilot-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(record.title, "autopilot-title")
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_hexpand(True)
            chip_class = "chip-strong" if record.status in {"prepared", "launched", "running", "done"} else ("chip-danger" if record.status in {"failed", "blocked", "stopped"} else "chip")
            top.append(title)
            top.append(self.chip_label(record.status, chip_class))
            meta = self.label(
                f"{record.project_name} | {human_time(record.updated)} | pid {record.pid or '-'} | exit {record.exit_code if record.exit_code is not None else '-'}",
                "autopilot-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(top)
            content.append(meta)
            row.set_child(content)
            listbox.append(row)
            if self.selected_autopilot_record and record.id == self.selected_autopilot_record.id:
                listbox.select_row(row)

    def render_autopilot_records(self) -> None:
        self.rendering_autopilot = True
        try:
            if hasattr(self, "autopilot_compact_list"):
                self.render_autopilot_list(self.autopilot_compact_list, compact=True)
            if hasattr(self, "autopilot_page_list"):
                self.render_autopilot_list(self.autopilot_page_list, compact=False)
        finally:
            self.rendering_autopilot = False
        record = self.selected_autopilot_record
        self.set_text(getattr(self, "autopilot_detail_buffer", None), self.autopilot_record_detail_text(record))
        if hasattr(self, "autopilot_status_label"):
            if record is None:
                self.autopilot_status_label.set_text("No run package yet. Prepare from Mission Architect.")
            else:
                self.autopilot_status_label.set_text(f"Latest: {record.status} | pid {record.pid or '-'} | exit {record.exit_code if record.exit_code is not None else '-'}")
        if hasattr(self, "autopilot_page_title_label"):
            if record is None:
                self.autopilot_page_title_label.set_text("No prepared Autopilot run")
                self.set_chip(self.autopilot_page_status_label, "idle", "chip")
                self.autopilot_page_meta_label.set_text("Prepare from Mission Architect to create a replayable script, blueprint, event stream, and manifest.")
            else:
                self.autopilot_page_title_label.set_text(record.title)
                self.set_chip(self.autopilot_page_status_label, record.status, self.chip_css_for_status(record.status))
                self.autopilot_page_meta_label.set_text(f"{record.project_name} | {human_time(record.updated)} | pid {record.pid or '-'} | {record.artifacts_dir}")
            self.autopilot_page_count_label.set_text(f"{len(self.autopilot_records)} runs")
        self.render_operator_brief()

    def set_autopilot_record(self, record_id: str, **changes: object) -> AutopilotRecord | None:
        for record in self.autopilot_records:
            if record.id != record_id:
                continue
            updated = update_autopilot_record(record, **changes)
            self.autopilot_records = upsert_autopilot_record(self.autopilot_records, updated)
            self.selected_autopilot_record = updated
            self.persist_autopilot_records()
            self.render_autopilot_records()
            return updated
        return None

    def prepare_current_autopilot_record(
        self,
        *,
        status: str = "prepared",
        note: str = "Prepared by Mission Architect",
        show_status: bool = True,
    ) -> AutopilotRecord | None:
        self.refresh_mission_blueprint()
        blueprint = self.mission_blueprint
        if blueprint is None:
            return None
        plan = self.autopilot_plan or self.build_current_autopilot_plan(blueprint)
        prompt = self.autopilot_prompt or self.selected_prompt()
        existing = next((record for record in self.autopilot_records if record.id == plan.id), None)
        record = write_autopilot_artifacts(
            plan,
            blueprint_text=blueprint.detail_text(),
            prompt=prompt,
            status=status,
            note=note,
            existing=existing,
        )
        self.autopilot_records = upsert_autopilot_record(self.autopilot_records, record)
        self.selected_autopilot_record = record
        self.persist_autopilot_records()
        self.render_autopilot_records()
        if show_status:
            self.set_status(f"Autopilot prepared: {short_id(record.id, 18)}")
            self.show_page("autopilot")
        return record

    def on_prepare_autopilot(self, _button: Gtk.Button) -> None:
        self.prepare_current_autopilot_record()

    def on_run_selected_autopilot(self, _button: Gtk.Button) -> None:
        record = self.selected_autopilot_record
        if record is None:
            record = self.prepare_current_autopilot_record(show_status=False)
        if record is None:
            self.set_status("No Autopilot package selected", "warn")
            return
        script = Path(record.script_path)
        if not script.exists():
            self.set_status("Autopilot script missing; preparing a fresh package", "warn")
            record = self.prepare_current_autopilot_record(status="launched", note="Recreated missing script", show_status=False)
            if record is None:
                return
            script = Path(record.script_path)
        updated = update_autopilot_record(record, status="launched", note="Replayed from Autopilot history")
        self.autopilot_records = upsert_autopilot_record(self.autopilot_records, updated)
        self.selected_autopilot_record = updated
        self.persist_autopilot_records()
        self.render_autopilot_records()
        self.run_embedded_command(["bash", str(script)])
        self.set_status("Autopilot replay running")

    def on_track_autopilot(self, _button: Gtk.Button) -> None:
        record = self.selected_autopilot_record
        if record is None:
            record = self.prepare_current_autopilot_record(show_status=False)
        if record is None:
            self.set_status("No Autopilot package selected", "warn")
            return
        self.start_tracked_autopilot(record)

    def start_tracked_autopilot(self, record: AutopilotRecord) -> None:
        if record.id in self.autopilot_procs and self.autopilot_procs[record.id].poll() is None:
            self.set_status("Autopilot is already running", "warn")
            return
        script = Path(record.script_path)
        if not script.exists():
            self.set_status("Autopilot script missing; preparing a fresh package", "warn")
            fresh = self.prepare_current_autopilot_record(status="queued", note="Recreated missing script", show_status=False)
            if fresh is None:
                return
            record = fresh
            script = Path(record.script_path)
        log_path = Path(record.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command_run = None
        if self.autopilot_plan is not None and self.autopilot_plan.id == record.id:
            command_run = self.stamp_command_receipt(list(self.autopilot_plan.main_command), "autopilot", surface="autopilot-track", run_status="queued")
        if command_run is not None:
            self.autopilot_run_ids[record.id] = command_run.id
        queued = self.set_autopilot_record(
            record.id,
            status="queued",
            pid=0,
            exit_code=None,
            started=int(dt.datetime.now().timestamp()),
            finished=0,
            note="Queued for tracked execution",
        ) or record
        if self.stack is not None:
            self.stack.set_visible_child_name("autopilot")

        def worker() -> None:
            try:
                with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
                    log_file.write(f"[Codex Control] tracked Autopilot: {queued.title}\n")
                    log_file.write(f"[Codex Control] script: {queued.script_path}\n\n")
                    log_file.flush()
                    proc = subprocess.Popen(
                        ["bash", str(script)],
                        cwd=queued.artifacts_dir,
                        text=True,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    GLib.idle_add(self.on_autopilot_started, queued.id, proc)
                    code = proc.wait()
                GLib.idle_add(self.on_autopilot_finished, queued.id, int(code))
            except Exception as exc:  # noqa: BLE001
                try:
                    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
                        log_file.write(f"\n[Codex Control] Autopilot launch failed: {exc}\n")
                except OSError:
                    pass
                GLib.idle_add(self.on_autopilot_finished, queued.id, 1)

        threading.Thread(target=worker, daemon=True).start()
        self.set_status("Autopilot tracking started")

    def on_autopilot_started(self, record_id: str, proc: subprocess.Popen[str]) -> bool:
        self.autopilot_procs[record_id] = proc
        self.set_autopilot_record(record_id, status="running", pid=proc.pid, note="Tracked execution running")
        self.update_command_run_status(self.autopilot_run_ids.get(record_id, ""), "running", pid=proc.pid)
        self.set_status("Autopilot running")
        return False

    def on_autopilot_finished(self, record_id: str, code: int) -> bool:
        self.autopilot_procs.pop(record_id, None)
        current = next((record for record in self.autopilot_records if record.id == record_id), None)
        status = "stopped" if current is not None and current.status == "stopping" else ("done" if code == 0 else "failed")
        self.set_autopilot_record(
            record_id,
            status=status,
            exit_code=code,
            pid=0,
            finished=int(dt.datetime.now().timestamp()),
            note="Tracked execution finished" if code == 0 else "Tracked execution failed",
        )
        self.update_command_run_status(self.autopilot_run_ids.get(record_id, ""), status, exit_code=code)
        self.refresh_threads()
        self.set_status("Autopilot finished" if code == 0 else "Autopilot failed", "ok" if code == 0 else "warn")
        return False

    def on_stop_autopilot(self, _button: Gtk.Button) -> None:
        record = self.selected_autopilot_record
        if record is None:
            self.set_status("Select an Autopilot run", "warn")
            return
        proc = self.autopilot_procs.get(record.id)
        if proc is None or proc.poll() is not None:
            self.set_status("Autopilot is not running in this app session", "warn")
            return
        self.set_autopilot_record(record.id, status="stopping", note="Stop requested")
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        self.set_status("Stopping Autopilot", "warn")

    def on_show_autopilot_log(self, _button: Gtk.Button) -> None:
        self.set_text(getattr(self, "autopilot_detail_buffer", None), self.autopilot_record_detail_text(self.selected_autopilot_record, "log"))

    def on_show_autopilot_final(self, _button: Gtk.Button) -> None:
        self.set_text(getattr(self, "autopilot_detail_buffer", None), self.autopilot_record_detail_text(self.selected_autopilot_record, "final"))

    def on_open_autopilot(self, _button: Gtk.Button) -> None:
        record = self.selected_autopilot_record
        if record is None:
            self.set_status("Select an Autopilot run", "warn")
            return
        Path(record.artifacts_dir).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", record.artifacts_dir], start_new_session=True)
        self.set_status("Opened Autopilot artifacts")

    def on_copy_autopilot(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(self.autopilot_record_detail_text(self.selected_autopilot_record))
            self.set_status("Autopilot detail copied")

    def on_delete_autopilot(self, _button: Gtk.Button) -> None:
        record = self.selected_autopilot_record
        if record is None:
            self.set_status("Select an Autopilot run", "warn")
            return
        self.autopilot_records = remove_autopilot_record(self.autopilot_records, record.id)
        self.selected_autopilot_record = self.autopilot_records[0] if self.autopilot_records else None
        self.persist_autopilot_records()
        self.render_autopilot_records()
        self.set_status("Autopilot record removed; artifacts kept")

    def on_refresh_autopilot(self, _button: Gtk.Button) -> None:
        self.refresh_autopilot_records()
        self.render_autopilot_records()
        self.set_status("Autopilot history refreshed")

    def on_autopilot_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self.rendering_autopilot:
            return
        self.selected_autopilot_record = getattr(row, "record", None) if row is not None else None
        self.render_autopilot_records()

    def on_autopilot_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self.selected_autopilot_record = getattr(row, "record", None)
        self.on_run_selected_autopilot(Gtk.Button())

    def common_args_for_project(self, project: str, profile_override: str | None = None) -> list[str]:
        args: list[str] = []
        profile = profile_override if profile_override is not None else self.dropdown_value(self.profile_combo)
        model = self.dropdown_value(self.model_combo)
        reasoning = self.dropdown_value(self.reasoning_combo)
        sandbox = self.dropdown_value(self.sandbox_combo)
        approval = self.dropdown_value(self.approval_combo)
        web = self.dropdown_value(self.web_combo)
        personality = self.dropdown_value(self.personality_combo)

        if profile and profile != "none":
            args.extend(["-p", profile])
        if model and model != "config":
            args.extend(["-m", model])
        if project:
            args.extend(["-C", project])
        if sandbox and sandbox != "config":
            args.extend(["-s", sandbox])
        if approval and approval != "config":
            args.extend(["-a", approval])
        if web == "live":
            args.append("--search")
        elif web in {"cached", "disabled"}:
            args.extend(["-c", f'web_search="{web}"'])
        if reasoning and reasoning != "config":
            args.extend(["-c", f'model_reasoning_effort="{reasoning}"'])
        if personality and personality != "config":
            args.extend(["-c", f'personality="{personality}"'])
        add_dir = self.add_dir_entry.get_text().strip() if hasattr(self, "add_dir_entry") else ""
        if add_dir:
            args.extend(["--add-dir", str(Path(add_dir).expanduser())])
        if getattr(self, "inline_switch", None) and self.inline_switch.get_active():
            args.append("--no-alt-screen")
        return args

    def common_args(self) -> list[str]:
        return self.common_args_for_project(self.selected_project())

    def build_command(self, action: str | None = None, prompt: str | None = None) -> list[str]:
        action = action or self.dropdown_value(self.action_combo) or "interactive"
        prompt = self.selected_prompt() if prompt is None else prompt
        args = [self.codex_bin]
        if action == "doctor":
            return args + ["doctor", "--summary", "--ascii"]
        if action == "update":
            return args + ["update"]
        if action == "login":
            return args + ["login"]

        args.extend(self.common_args())
        if action == "interactive":
            if prompt:
                args.append(prompt)
            return args
        if action == "exec":
            args.append("exec")
            if self.skip_git_switch.get_active() if hasattr(self, "skip_git_switch") else bool(self.config.get("skip_git", True)):
                args.append("--skip-git-repo-check")
            if prompt:
                args.append(prompt)
            return args
        if action == "resume":
            args.extend(["resume", "--last"])
            if prompt:
                args.append(prompt)
            return args
        if action == "review":
            args.extend(["review", "--uncommitted"])
            if prompt:
                args.append(prompt)
            return args
        return args

    def update_command_preview(self) -> None:
        if self.command_buffer is not None and hasattr(self, "action_combo"):
            self.command_buffer.set_text(shell_join(self.build_command()))
        if hasattr(self, "launch_mode_card"):
            self.launch_mode_card.value_label.set_text(self.selected_mode_label())
        if hasattr(self, "terminal_cwd_label"):
            self.terminal_cwd_label.set_text(self.selected_project())
        self.refresh_power_labels()
        if hasattr(self, "preflight_summary_label") or hasattr(self, "preflight_page_summary_label"):
            self.refresh_preflight()
        if hasattr(self, "mission_title_label") or hasattr(self, "mission_page_title_label"):
            self.refresh_mission_blueprint()
        self.render_quality_gate()
        self.render_context_packet()
        self.render_roadmap()
        self.render_launch_package()
        self.render_operator_brief()
        self.render_palette_preview(self.selected_action)
        self.save_current_state()

    def current_layout_state(self) -> WorkstationLayout:
        layout = self.layout_state
        if self.window is not None:
            try:
                maximized = self.window.is_maximized()
                if maximized:
                    layout = layout_with_window(layout, layout.window_width, layout.window_height, True)
                else:
                    width, height = self.window.get_default_size()
                    layout = layout_with_window(layout, width, height, False)
            except Exception:  # noqa: BLE001
                pass
        for key, paned in self.paned_widgets.items():
            layout = layout_with_pane(layout, key, paned.get_position())
        self.layout_state = layout
        return layout

    def save_current_state(self) -> None:
        if not hasattr(self, "project_entry"):
            return
        save_json(CONFIG_FILE, {
            "project": self.selected_project(),
            "profile": self.dropdown_value(self.profile_combo),
            "model": self.dropdown_value(self.model_combo),
            "reasoning": self.dropdown_value(self.reasoning_combo),
            "sandbox": self.dropdown_value(self.sandbox_combo),
            "approval": self.dropdown_value(self.approval_combo),
            "web": self.dropdown_value(self.web_combo),
            "personality": self.dropdown_value(self.personality_combo),
            "action": self.dropdown_value(self.action_combo),
            "add_dir": self.add_dir_entry.get_text().strip(),
            "inline": self.inline_switch.get_active(),
            "skip_git": self.skip_git_switch.get_active(),
            "atlas_root": self.atlas_root_entry.get_text().strip() if hasattr(self, "atlas_root_entry") else "",
            "receipt_auto": self.receipt_auto_switch.get_active() if hasattr(self, "receipt_auto_switch") else True,
            "prompt": self.selected_prompt(),
            "focus_mode": self.focus_mode,
            "mesh_filter_mode": self.mesh_filter_mode,
            "mesh_team_only": self.mesh_team_only,
            "mesh_live_refresh": self.mesh_live_refresh,
            "mesh_live_refresh_seconds": self.mesh_live_refresh_seconds,
            "layout": layout_to_config(self.current_layout_state()),
        })

    def build_shell_script(self, args: list[str], keep_shell: bool = True) -> str:
        cwd = shlex.quote(ensure_dir(self.selected_project()))
        command = shell_join(args)
        preview = shlex.quote("$ " + command)
        tail = 'exec bash -i\n' if keep_shell else ''
        return (
            "set -o pipefail\n"
            f"cd -- {cwd} || exit 1\n"
            'export PATH="$HOME/.local/bin:$PATH"\n'
            "clear\n"
            f"printf '%s\\n' {preview}\n"
            f"{command}\n"
            "status=$?\n"
            'printf "\\n[Codex Control] command exited with code %s\\n" "$status"\n'
            f"{tail}"
        )

    def spawn_shell_in_terminal(self) -> None:
        if Vte is None or self.terminal is None:
            return
        cwd = ensure_dir(self.selected_project())
        script = (
            f"cd -- {shlex.quote(cwd)}\n"
            'export PATH="$HOME/.local/bin:$PATH"\n'
            'printf "Codex Control embedded terminal ready.\\n"\n'
            'printf "Project: %s\\n\\n" "$PWD"\n'
            "exec bash -i\n"
        )
        self.terminal.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            cwd,
            ["bash", "-lc", script],
            [f"{k}={v}" for k, v in os.environ.items()],
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            None,
        )
        if hasattr(self, "terminal_state_label"):
            self.terminal_state_label.set_text("shell ready")

    def run_embedded_command(self, args: list[str]) -> None:
        self.stamp_command_receipt(args, surface="embedded", run_status="launched")
        if Vte is None or self.terminal is None:
            self.launch_external(args, "Codex", stamp=False)
            return
        cwd = ensure_dir(self.selected_project())
        script = self.build_shell_script(args, keep_shell=True)
        self.terminal.reset(True, True)
        self.terminal.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            cwd,
            ["bash", "-lc", script],
            [f"{k}={v}" for k, v in os.environ.items()],
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            None,
        )
        self.set_status("Running embedded")
        if hasattr(self, "terminal_state_label"):
            self.terminal_state_label.set_text("running")

    def on_terminal_clear(self, _button: Gtk.Button) -> None:
        if Vte is None or self.terminal is None:
            return
        self.terminal.reset(True, True)
        self.spawn_shell_in_terminal()
        self.set_status("Terminal reset")

    def on_terminal_shell(self, _button: Gtk.Button) -> None:
        self.spawn_shell_in_terminal()
        self.set_status("Shell ready")

    def focus_prompt(self) -> None:
        if hasattr(self, "prompt_view"):
            self.prompt_view.grab_focus()

    def focus_project(self) -> None:
        if hasattr(self, "project_entry"):
            self.project_entry.grab_focus()

    def show_palette(self) -> None:
        self.show_page("palette")
        if hasattr(self, "palette_search_entry"):
            self.palette_search_entry.grab_focus()

    def show_page(self, name: str) -> None:
        if self.stack is not None:
            self.stack.set_visible_child_name(name)
        row = self.nav_rows.get(name) if hasattr(self, "nav_rows") else None
        nav_lists = getattr(self, "nav_lists", [])
        if row is not None and name not in PRIMARY_NAV_PAGES and hasattr(self, "nav_more_expander"):
            self.nav_more_expander.set_expanded(True)
        for listbox in nav_lists:
            selected = listbox.get_selected_row()
            if row is not None and row.get_parent() is listbox:
                if selected is not row:
                    listbox.select_row(row)
            elif selected is not None:
                listbox.unselect_row(selected)

    def render_action_list(self, listbox: Gtk.ListBox, actions: tuple[ActionSpec, ...]) -> None:
        self.clear_listbox(listbox)
        for action in actions:
            row = Gtk.ListBoxRow()
            row.action = action
            row.add_css_class("action-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(action.title, "action-title")
            title.set_hexpand(True)
            top.append(title)
            top.append(self.chip_label(action.group, "chip"))
            detail = self.label(action.detail, "action-detail", wrap=True)
            content.append(top)
            content.append(detail)
            row.set_child(content)
            listbox.append(row)
            if self.selected_action is not None and action.id == self.selected_action.id:
                listbox.select_row(row)

    def sync_action_query_entries(self, source: Gtk.Entry | None = None) -> None:
        for name in ["palette_search_entry", "palette_compact_entry"]:
            entry = getattr(self, name, None)
            if entry is not None and entry is not source and entry.get_text() != self.action_query:
                entry.set_text(self.action_query)

    def render_action_palette(self) -> None:
        if not hasattr(self, "palette_compact_list") and not hasattr(self, "palette_list"):
            return
        ranked = rank_actions(self.action_query)
        if self.selected_action is None or all(action.id != self.selected_action.id for action in ranked):
            self.selected_action = ranked[0] if ranked else None
        self.rendering_actions = True
        try:
            if hasattr(self, "palette_compact_list"):
                self.render_action_list(self.palette_compact_list, ranked[:5])
            if hasattr(self, "palette_list"):
                self.render_action_list(self.palette_list, ranked[:80])
        finally:
            self.rendering_actions = False
        self.update_action_detail()

    def update_action_detail(self) -> None:
        action = self.selected_action
        if action is None:
            if hasattr(self, "palette_action_title_label"):
                self.palette_action_title_label.set_text("No action selected")
                self.set_chip(self.palette_action_group_label, "idle", "chip")
                self.palette_action_detail_label.set_text("Search or select an action.")
                self.palette_action_id_label.set_text("-")
            self.render_palette_preview(None)
            return
        if hasattr(self, "palette_action_title_label"):
            self.palette_action_title_label.set_text(action.title)
            self.set_chip(self.palette_action_group_label, action.group, "chip-strong")
            keywords = ", ".join(action.keywords) if action.keywords else "none"
            self.palette_action_detail_label.set_text(f"{action.detail}\nKeywords: {keywords}")
            self.palette_action_id_label.set_text(action.id)
        self.render_palette_preview(action)

    def palette_context(self) -> PaletteContext:
        project = self.selected_project()
        return PaletteContext(
            project=project,
            project_exists=Path(project).exists(),
            prompt_chars=len(self.selected_prompt()),
            selected_prompt_choice=self.selected_prompt_variant is not None,
            context_ready=self.context_packet is not None,
            roadmap_ready=self.roadmap is not None,
            launch_package_ready=self.launch_package is not None,
            session_selected=self.selected_workspace_session is not None,
            agent_plan_ready=self.agent_plan is not None,
            agent_lane_selected=self.selected_agent_lane is not None,
            autopilot_selected=self.selected_autopilot_record is not None,
            receipt_selected=self.selected_receipt is not None,
        )

    def command_for_palette_action(self, action_id: str) -> list[str]:
        prompt = "[prompt redacted]" if self.selected_prompt() else ""
        current_action = self.dropdown_value(self.action_combo) or "interactive"
        if action_id == "run.max":
            return self.build_command("interactive", prompt)
        if action_id == "run.review":
            return self.build_command("review", prompt)
        if action_id == "run.exec":
            return self.build_command("exec", prompt)
        if action_id in {"run.external", "command.copy"}:
            return self.build_command(current_action, prompt)
        if action_id == "doctor.run":
            return self.build_command("doctor", "")
        if action_id == "codex.login":
            return self.build_command("login", "")
        if action_id == "codex.update":
            return self.build_command("update", "")
        if action_id == "launcher.diagnostics":
            return []
        if action_id == "launcher.repair":
            return [sys.executable, "-m", "pip", "install", "--user", "."]
        return []

    def render_palette_preview(self, action: ActionSpec | None) -> None:
        if action is None:
            self.last_action_preview = None
            if hasattr(self, "palette_preview_title_label"):
                self.palette_preview_title_label.set_text("Would Run")
                self.set_chip(self.palette_preview_status_label, "idle", "chip")
                self.set_chip(self.palette_preview_surface_label, "surface", "chip")
                self.set_chip(self.palette_preview_risk_label, "risk", "chip")
                self.palette_preview_summary_label.set_text("Select an action to preview its effect.")
                self.palette_preview_requirements_label.set_text("Ready")
                self.palette_preview_command_label.set_text("-")
            if hasattr(self, "palette_compact_preview_label"):
                self.palette_compact_preview_label.set_text("Preview: select an action")
            self.render_palette_history(None)
            return
        command = self.command_for_palette_action(action.id)
        preview = build_palette_preview(
            action,
            self.palette_context(),
            command,
            prompt_redacted=bool(self.selected_prompt()),
        )
        self.last_action_preview = preview
        status_css = "chip-strong" if preview.ready else "chip-danger"
        if hasattr(self, "palette_preview_title_label"):
            self.palette_preview_title_label.set_text("Would Run")
            self.set_chip(self.palette_preview_status_label, preview.status, status_css)
            self.set_chip(self.palette_preview_surface_label, preview.surface, "chip")
            self.set_chip(self.palette_preview_risk_label, preview.risk, "chip")
            self.palette_preview_summary_label.set_text(preview.summary)
            self.palette_preview_requirements_label.set_text(preview.requirement_text())
            self.palette_preview_command_label.set_text(preview.command_text or preview.detail_text())
        if hasattr(self, "palette_compact_preview_label"):
            command_hint = f" | {preview.command_text}" if preview.command_text else ""
            self.palette_compact_preview_label.set_text(
                f"Preview: {preview.surface} | {preview.status} | {preview.risk}{command_hint}"
            )
        self.render_palette_history(action)

    def persist_palette_history(self) -> None:
        save_palette_history(PALETTE_HISTORY_FILE, self.palette_history)
        PALETTE_HISTORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        PALETTE_HISTORY_LOG.write_text(palette_history_log(self.palette_history), encoding="utf-8")

    def render_palette_history(self, action: ActionSpec | None = None) -> None:
        action_id = action.id if action is not None else (self.selected_action.id if self.selected_action is not None else "")
        record = find_palette_record(self.palette_history, action_id) if action_id else self.selected_palette_record
        self.selected_palette_record = record
        if record is None:
            if hasattr(self, "palette_history_title_label"):
                self.palette_history_title_label.set_text("Last Result")
                self.set_chip(self.palette_history_status_label, "none", "chip")
                self.set_chip(self.palette_history_time_label, "never", "chip")
                self.palette_history_detail_label.set_text("No action history yet.")
                self.palette_history_command_label.set_text("-")
            if hasattr(self, "palette_compact_history_label"):
                self.palette_compact_history_label.set_text("Last: no action history yet")
            return
        if hasattr(self, "palette_history_title_label"):
            self.palette_history_title_label.set_text("Last Result")
            self.set_chip(self.palette_history_status_label, record.phase, self.chip_css_for_status(record.phase))
            self.set_chip(self.palette_history_time_label, human_time(record.updated), "chip")
            self.palette_history_detail_label.set_text(f"{record.summary()} | {record.surface} | {record.risk}\n{record.detail}")
            self.palette_history_command_label.set_text(record.command_preview or "-")
        if hasattr(self, "palette_compact_history_label"):
            self.palette_compact_history_label.set_text(
                f"Last: {record.title} | {record.phase} | {human_time(record.updated)} | {record.count} run(s)"
            )

    def begin_palette_history(self, action: ActionSpec, preview: PalettePreview | None, detail: str) -> None:
        self.palette_history, record = record_palette_event(
            self.palette_history,
            action,
            preview,
            phase="queued",
            detail=detail,
        )
        self.selected_palette_record = record
        self.persist_palette_history()
        self.render_palette_history(action)

    def finish_palette_history(self, action_id: str, phase: str, detail: str) -> None:
        self.palette_history, record = update_palette_record(
            self.palette_history,
            action_id,
            phase=phase,
            detail=detail,
        )
        if record is not None:
            self.selected_palette_record = record
        else:
            action = action_by_id(action_id)
            if action is not None:
                self.palette_history, self.selected_palette_record = record_palette_event(
                    self.palette_history,
                    action,
                    self.last_action_preview if self.last_action_preview and self.last_action_preview.action_id == action_id else None,
                    phase=phase,
                    detail=detail,
                )
        self.persist_palette_history()
        self.render_palette_history(action_by_id(action_id))

    def on_rerun_palette_action(self, _button: Gtk.Button) -> None:
        action_id = self.selected_action.id if self.selected_action is not None else (self.selected_palette_record.action_id if self.selected_palette_record else "")
        if not action_id:
            self.set_status("No palette action selected", "warn")
            return
        self.execute_action(action_id)

    def on_copy_palette_history(self, _button: Gtk.Button) -> None:
        record = self.selected_palette_record
        if record is None and self.selected_action is not None:
            record = find_palette_record(self.palette_history, self.selected_action.id)
        if record is None:
            self.set_status("No palette history to copy", "warn")
            return
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(palette_history_detail(record))
            self.set_status("Palette history copied")

    def on_open_palette_history(self, _button: Gtk.Button) -> None:
        self.persist_palette_history()
        subprocess.Popen(["xdg-open", str(PALETTE_HISTORY_LOG)], start_new_session=True)
        self.set_status("Opened palette history log")

    def set_action_feedback(self, feedback: ActionFeedback) -> None:
        self.last_action_feedback = feedback
        if hasattr(self, "palette_action_feedback_label"):
            self.palette_action_feedback_label.set_text(feedback.headline())
        if hasattr(self, "palette_action_feedback_detail_label"):
            self.palette_action_feedback_detail_label.set_text(feedback.detail)
        if hasattr(self, "palette_compact_feedback_label"):
            self.palette_compact_feedback_label.set_text(feedback.compact())

    def feedback_for_action(self, action_id: str, phase: str, detail: str | None = None) -> ActionFeedback:
        action = action_by_id(action_id)
        return action_feedback(
            action_id,
            action.title if action is not None else action_id,
            action.group if action is not None else "Action",
            phase,
            detail if detail is not None else (action.detail if action is not None else action_id),
        )

    def on_action_query_changed(self, entry: Gtk.Entry) -> None:
        self.action_query = entry.get_text().strip()
        self.sync_action_query_entries(entry)
        self.render_action_palette()

    def on_clear_action_query(self, _button: Gtk.Button) -> None:
        self.action_query = ""
        self.sync_action_query_entries(None)
        self.render_action_palette()

    def on_action_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self.rendering_actions:
            return
        self.selected_action = getattr(row, "action", None) if row is not None else None
        self.update_action_detail()

    def on_action_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        action = getattr(row, "action", None)
        if action is not None:
            self.selected_action = action
            self.execute_action(action.id)

    def on_execute_selected_action(self, _button: Gtk.Button) -> None:
        action = self.selected_action or (rank_actions(self.action_query, limit=1)[0] if rank_actions(self.action_query, limit=1) else None)
        if action is None:
            self.set_status("No action selected", "warn")
            return
        self.selected_action = action
        self.execute_action(action.id)

    def execute_action(self, action_id: str) -> None:
        action = action_by_id(action_id)
        button = Gtk.Button()
        self.set_action_feedback(self.feedback_for_action(action_id, "queued"))
        if action is not None:
            preview = build_palette_preview(
                action,
                self.palette_context(),
                self.command_for_palette_action(action_id),
                prompt_redacted=bool(self.selected_prompt()),
            )
            self.last_action_preview = preview
            self.begin_palette_history(action, preview, "Queued from palette")
            if not preview.ready:
                detail = preview.requirement_text()
                self.set_action_feedback(self.feedback_for_action(action_id, "blocked", detail))
                self.finish_palette_history(action_id, "blocked", detail)
                self.render_palette_preview(action)
                self.set_status(detail, "warn")
                return
        try:
            page_map = {
                "page.workbench": "launch",
                "page.palette": "palette",
                "page.context": "context",
                "page.roadmap": "roadmap",
                "page.orchestrate": "orchestrate",
                "page.quality": "quality",
                "page.mission": "mission",
                "page.autopilot": "autopilot",
                "page.mesh": "mesh",
                "page.monitor": "monitor",
                "page.receipts": "receipts",
                "page.git": "git",
            }
            if action_id in page_map:
                if action_id == "page.context":
                    self.show_context_page()
                elif action_id == "page.roadmap":
                    self.show_roadmap_page()
                elif action_id == "page.orchestrate":
                    self.show_orchestration_page()
                else:
                    self.show_page(page_map[action_id])
                self.set_status(f"Opened {action.title if action else action_id}")
                self.set_action_feedback(self.feedback_for_action(action_id, "opened"))
                self.finish_palette_history(action_id, "opened", f"Opened {action.title if action else action_id}")
                return
            handlers = {
                "run.max": self.on_run_embedded,
                "run.exec": self.on_run_headless,
                "run.external": self.on_run_external,
                "command.copy": self.on_copy_command,
                "orchestrate.prepare": self.on_prepare_launch_package,
                "orchestrate.run": self.on_run_launch_package,
                "orchestrate.copy": self.on_copy_launch_package,
                "orchestrate.save": self.on_save_launch_package,
                "prompt.enhance": self.on_enhance_prompt,
                "prompt.ai": self.on_ai_enhance_prompt,
                "prompt.use": self.on_use_prompt_choice,
                "context.refresh": self.on_refresh_context_packet,
                "context.use": self.on_use_context_packet,
                "context.copy": self.on_copy_context_packet,
                "context.save": self.on_save_context_packet,
                "roadmap.plan": self.on_refresh_roadmap,
                "roadmap.use": self.on_use_next_roadmap_prompt,
                "roadmap.copy": self.on_copy_roadmap,
                "roadmap.save": self.on_save_roadmap,
                "mission.architect": self.on_architect_mission,
                "mission.use_prompt": self.on_use_mission_prompt,
                "agents.plan": self.on_plan_agents,
                "agents.prepare": self.on_prepare_agent_worktrees,
                "agents.run_lane": self.on_run_agent_lane,
                "agents.track_lane": self.on_run_monitored_agent_lane,
                "agents.results": self.on_refresh_agent_results,
                "autopilot.prepare": self.on_prepare_autopilot,
                "autopilot.track": self.on_track_autopilot,
                "autopilot.terminal": self.on_run_selected_autopilot,
                "autopilot.stop": self.on_stop_autopilot,
                "mesh.discover": self.on_discover_tailnet,
                "mesh.check": self.on_check_fleet,
                "mesh.latest": self.on_load_latest_mesh_team,
                "mesh.prepare_team": self.on_prepare_mesh_team,
                "mesh.launch_team": self.on_launch_mesh_team,
                "mesh.collect_team": self.on_collect_mesh_team,
                "mesh.sync_bus": self.on_sync_mesh_handoff_bus,
                "mesh.sync_chat": self.on_sync_team_chat,
                "mesh.repair_bus": self.on_retry_mesh_handoff_bus,
                "mesh.retry_bus": self.on_retry_mesh_handoff_bus,
                "mesh.preview_repair_bus": self.on_preview_mesh_bus_repair,
                "mesh.refresh_chat": self.on_refresh_team_chat,
                "mesh.copy_chat": self.on_copy_team_chat,
                "mesh.verify_bus": self.on_verify_mesh_bus_integrity,
                "mesh.copy_bus_report": self.on_copy_mesh_team_bus_report,
                "mesh.copy_role_bootstrap": self.on_copy_role_bootstrap,
                "mesh.summary": self.on_copy_mesh_team_summary,
                "mesh.open": self.on_open_mesh_team,
                "quality.run": self.on_run_quality_gate,
                "quality.copy": self.on_copy_quality_report,
                "preflight.open": self.on_show_preflight,
                "receipts.stamp": self.on_stamp_receipt,
                "receipts.verify": self.on_verify_receipt,
                "receipts.replay": self.on_replay_receipts,
                "session.new": self.on_new_workspace_session,
                "session.save": self.on_save_workspace_session,
                "session.run": self.on_run_workspace_session,
                "project.refresh": lambda _b: self.refresh_project_snapshot_async(),
                "project.terminal": self.on_open_project_terminal,
                "git.status": self.on_git_status,
                "git.diff": self.on_git_diff_stat,
                "git.log": self.on_git_log,
                "profiles.install": self.on_install_profiles,
                "doctor.run": self.on_run_doctor,
                "launcher.diagnostics": self.on_launcher_diagnostics,
                "launcher.repair": self.on_launcher_repair,
                "codex.login": self.on_login_codex,
                "codex.update": self.on_update_codex,
                "app.refresh": lambda _b: self.refresh_all(),
            }
            if action_id == "run.review":
                self.on_run_action_button(button, "review")
                self.set_action_feedback(self.feedback_for_action(action_id, "dispatched"))
                self.finish_palette_history(action_id, "dispatched", "Dispatched review in terminal")
            elif action_id == "prompt.focus":
                self.focus_prompt()
                self.set_status("Prompt focused")
                self.set_action_feedback(self.feedback_for_action(action_id, "focused"))
                self.finish_palette_history(action_id, "focused", "Prompt editor focused")
            elif action_id == "project.focus":
                self.focus_project()
                self.set_status("Project focused")
                self.set_action_feedback(self.feedback_for_action(action_id, "focused"))
                self.finish_palette_history(action_id, "focused", "Project field focused")
            elif action_id in handlers:
                handlers[action_id](button)
                self.set_action_feedback(self.feedback_for_action(action_id, "dispatched"))
                self.finish_palette_history(action_id, "dispatched", f"Dispatched {action.title if action else action_id}")
            else:
                self.set_status(f"No handler for {action_id}", "warn")
                self.set_action_feedback(self.feedback_for_action(action_id, "missing", "No handler is registered for this action."))
                self.finish_palette_history(action_id, "missing", "No handler is registered for this action.")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Action failed: {exc}", "bad")
            self.set_action_feedback(self.feedback_for_action(action_id, "failed", str(exc)))
            self.finish_palette_history(action_id, "failed", str(exc))

    def launch_external(self, args: list[str], title: str, stamp: bool = True) -> None:
        if stamp:
            self.stamp_command_receipt(args, surface="external", run_status="launched")
        terminal = first_terminal()
        if terminal is None:
            self.set_status("No terminal found", "bad")
            return
        cwd = ensure_dir(self.selected_project())
        script = self.build_shell_script(args, keep_shell=False) + 'printf "Press Enter to close."; read -r _\n'
        terminal_path, kind = terminal
        if kind == "konsole":
            term_args = [terminal_path, "--workdir", cwd, "-p", f"tabtitle={title}", "-e", "bash", "-lc", script]
        elif kind in {"kgx", "gnome-terminal"}:
            term_args = [terminal_path, "--working-directory", cwd, "--", "bash", "-lc", script]
        else:
            term_args = [terminal_path, "-T", title, "-e", "bash", "-lc", script]
        try:
            subprocess.Popen(term_args, start_new_session=True)
            self.set_status("Launched external")
        except OSError as exc:
            self.set_status(f"Launch failed: {exc}", "bad")

    def run_async_text(self, args: list[str], cwd: str | None, callback, timeout: int = 30) -> None:
        def worker() -> None:
            try:
                result = run_cmd(args, cwd=cwd, timeout=timeout)
                text = result.stdout
                if result.stderr:
                    text += "\n[stderr]\n" + result.stderr
                GLib.idle_add(callback, text, result.returncode)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(callback, str(exc), 1)
        threading.Thread(target=worker, daemon=True).start()

    def refresh_all(self) -> None:
        self.refresh_health_async()
        self.refresh_project_snapshot_async()
        self.refresh_projects()
        self.refresh_threads()
        self.load_config_text()
        self.refresh_profile_label()
        self.refresh_receipt_records()
        self.render_receipts()
        self.refresh_command_runs()
        self.render_command_runs()
        self.refresh_autopilot_records()
        self.render_autopilot_records()
        self.render_quality_gate()
        if hasattr(self, "device_list"):
            self.devices = load_devices(DEVICES_FILE)
            self.memory_items = load_memory(MEMORY_FILE)
            self.render_mesh()
        self.update_command_preview()

    def project_context_text(self) -> str:
        snapshot = self.current_project_snapshot()
        return snapshot.summary() if snapshot is not None else ""

    def refresh_project_snapshot_async(self) -> None:
        if hasattr(self, "project_intel_name"):
            self.project_intel_name.set_text("scanning")
        path = self.selected_project()

        def worker() -> None:
            try:
                snapshot = inspect_project(path)
                GLib.idle_add(self.apply_project_snapshot, snapshot)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self.apply_project_snapshot_error, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def apply_project_snapshot(self, snapshot: ProjectSnapshot) -> bool:
        self.project_snapshot = snapshot
        if hasattr(self, "project_intel_name"):
            self.project_intel_name.set_text(snapshot.name)
            self.project_intel_stack.set_text("Stack: " + (", ".join(snapshot.stack) if snapshot.stack else "unknown"))
            if snapshot.is_git:
                git_text = f"Git: {snapshot.branch or 'detached'} | changed {snapshot.dirty} | untracked {snapshot.untracked}"
            else:
                git_text = "Git: not a repository"
            self.project_intel_git.set_text(git_text)
            self.project_intel_recommendation.set_text("Recommendation: " + snapshot.recommendation)
            self.project_intel_files.set_text("Files: " + (", ".join(snapshot.top_files[:10]) if snapshot.top_files else "none"))
            changes = ", ".join(snapshot.changed_files[:6]) if snapshot.changed_files else "clean"
            self.project_intel_changes.set_text("Changes: " + changes)
            threads = ", ".join(thread.title for thread in snapshot.threads[:3]) if snapshot.threads else "none for this project"
            self.project_intel_threads.set_text("Threads: " + threads)
            self.render_project_commands(snapshot.commands)
        if hasattr(self, "prompt_choice_list"):
            self.prompt_variants = enhance_prompt(self.selected_prompt(), self.project_context_text())
            self.render_prompt_variants()
        if hasattr(self, "preflight_summary_label") or hasattr(self, "preflight_page_summary_label"):
            self.refresh_preflight()
        if hasattr(self, "mission_title_label") or hasattr(self, "mission_page_title_label"):
            self.refresh_mission_blueprint()
        self.render_quality_gate()
        self.update_command_preview()
        return False

    def apply_project_snapshot_error(self, text: str) -> bool:
        if hasattr(self, "project_intel_name"):
            self.project_intel_name.set_text("scan failed")
            self.project_intel_stack.set_text(text)
        if hasattr(self, "preflight_summary_label") or hasattr(self, "preflight_page_summary_label"):
            self.refresh_preflight()
        self.render_quality_gate()
        self.render_context_packet()
        self.render_roadmap()
        return False

    def render_project_commands(self, commands: tuple[ProjectCommand, ...]) -> None:
        if not hasattr(self, "project_command_list"):
            return
        self.clear_listbox(self.project_command_list)
        if not commands:
            row = Gtk.ListBoxRow()
            content = self.label("No validation command detected", "muted")
            row.set_child(content)
            self.project_command_list.append(row)
            return
        for command in commands[:5]:
            row = Gtk.ListBoxRow()
            row.add_css_class("project-command")
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            left.set_hexpand(True)
            left.append(self.label(command.label, "row-title"))
            command_label = self.label(command.command, "muted")
            command_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            left.append(command_label)
            run = Gtk.Button(label="Run")
            run.add_css_class("secondary")
            run.connect("clicked", self.on_run_project_command, command)
            copy = Gtk.Button(label="Copy")
            copy.add_css_class("secondary")
            copy.connect("clicked", self.on_copy_project_command, command)
            content.append(left)
            content.append(run)
            content.append(copy)
            row.set_child(content)
            self.project_command_list.append(row)

    def persist_workspace_sessions(self) -> None:
        save_sessions(SESSIONS_FILE, self.sessions)

    def current_workspace_session(self, status: str = "ready") -> WorkspaceSession:
        return new_session(
            project=self.selected_project(),
            profile=self.dropdown_value(self.profile_combo) or "maximum-power",
            action=self.dropdown_value(self.action_combo) or "interactive",
            prompt=self.selected_prompt(),
        ) if self.selected_workspace_session is None else replace_session(
            self.selected_workspace_session,
            project=self.selected_project(),
            profile=self.dropdown_value(self.profile_combo) or "maximum-power",
            action=self.dropdown_value(self.action_combo) or "interactive",
            prompt=self.selected_prompt(),
            status=status,
        )

    def render_workspace_sessions(self) -> None:
        if not hasattr(self, "session_list"):
            return
        self.clear_listbox(self.session_list)
        if not self.sessions:
            row = Gtk.ListBoxRow()
            row.add_css_class("session-row")
            row.set_child(self.label("No saved sessions yet", "muted"))
            self.session_list.append(row)
            self.render_operator_brief()
            return
        for session in self.sessions[:12]:
            row = Gtk.ListBoxRow()
            row.session = session
            row.add_css_class("session-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(session.title, "session-title")
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_hexpand(True)
            status = self.chip_label(session.status, "chip")
            top.append(title)
            top.append(status)
            meta = self.label(
                f"{Path(session.project).name or session.project} | {session.profile} | {session.action}",
                "session-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for label, handler in [
                ("Use", self.on_use_session_button),
                ("Run", self.on_run_session_button),
                ("Del", self.on_delete_session_button),
            ]:
                button = Gtk.Button(label=label)
                button.add_css_class("secondary")
                button.connect("clicked", handler, session)
                actions.append(button)
            if session.thread_id:
                for label, handler in [
                    ("Resume", self.on_resume_session_button),
                    ("Fork", self.on_fork_session_button),
                ]:
                    button = Gtk.Button(label=label)
                    button.add_css_class("secondary")
                    button.connect("clicked", handler, session)
                    actions.append(button)
            content.append(top)
            content.append(meta)
            content.append(actions)
            row.set_child(content)
            self.session_list.append(row)
            if self.selected_workspace_session and session.id == self.selected_workspace_session.id:
                self.session_list.select_row(row)
        self.render_operator_brief()

    def on_workspace_session_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_workspace_session = getattr(row, "session", None) if row is not None else None
        if self.selected_workspace_session is not None:
            self.set_status(f"Selected {self.selected_workspace_session.title}")

    def on_workspace_session_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        session = getattr(row, "session", None)
        if session is not None:
            self.apply_workspace_session(session)

    def on_new_workspace_session(self, _button: Gtk.Button) -> None:
        session = new_session(
            self.selected_project(),
            self.dropdown_value(self.profile_combo) or "maximum-power",
            self.dropdown_value(self.action_combo) or "interactive",
            self.selected_prompt(),
        )
        self.sessions = upsert_session(self.sessions, session)
        self.selected_workspace_session = session
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        self.set_status("Session created")

    def on_save_workspace_session(self, _button: Gtk.Button) -> None:
        session = self.current_workspace_session()
        self.sessions = upsert_session(self.sessions, session)
        self.selected_workspace_session = session
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        self.set_status("Session saved")

    def apply_workspace_session(self, session: WorkspaceSession) -> None:
        self.project_entry.set_text(session.project)
        if self.prompt_buffer is not None:
            self.prompt_buffer.set_text(session.prompt)
        if session.profile not in ["none", *profile_names()]:
            self.on_install_profiles(Gtk.Button())
        self.set_dropdown(self.profile_combo, session.profile)
        self.set_dropdown(self.action_combo, session.action)
        self.selected_workspace_session = session
        self.refresh_project_snapshot_async()
        self.update_command_preview()
        self.set_status(f"Using {session.title}")

    def on_use_workspace_session(self, _button: Gtk.Button) -> None:
        if self.selected_workspace_session is None:
            self.set_status("Select a session", "warn")
            return
        self.apply_workspace_session(self.selected_workspace_session)

    def run_workspace_session(self, session: WorkspaceSession) -> None:
        self.apply_workspace_session(session)
        running = touch_session(session, "running")
        self.sessions = upsert_session(self.sessions, running)
        self.selected_workspace_session = running
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        self.run_embedded_command(self.build_command(session.action, session.prompt))

    def on_run_workspace_session(self, _button: Gtk.Button) -> None:
        if self.selected_workspace_session is None:
            self.set_status("Select a session", "warn")
            return
        self.run_workspace_session(self.selected_workspace_session)

    def on_use_session_button(self, _button: Gtk.Button, session: WorkspaceSession) -> None:
        self.apply_workspace_session(session)

    def on_run_session_button(self, _button: Gtk.Button, session: WorkspaceSession) -> None:
        self.run_workspace_session(session)

    def on_delete_session_button(self, _button: Gtk.Button, session: WorkspaceSession) -> None:
        self.sessions = remove_session(self.sessions, session.id)
        if self.selected_workspace_session and self.selected_workspace_session.id == session.id:
            self.selected_workspace_session = self.sessions[0] if self.sessions else None
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        self.set_status("Session deleted")

    def on_resume_session_button(self, _button: Gtk.Button, session: WorkspaceSession) -> None:
        self.apply_workspace_session(session)
        running = touch_session(session, "running")
        self.sessions = upsert_session(self.sessions, running)
        self.selected_workspace_session = running
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        self.run_embedded_command([self.codex_bin, *self.common_args(), "resume", session.thread_id])

    def on_fork_session_button(self, _button: Gtk.Button, session: WorkspaceSession) -> None:
        self.apply_workspace_session(session)
        running = touch_session(session, "running")
        self.sessions = upsert_session(self.sessions, running)
        self.selected_workspace_session = running
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        args = [self.codex_bin, *self.common_args(), "fork", session.thread_id]
        if session.prompt:
            args.append(session.prompt)
        self.run_embedded_command(args)

    def plan_agent_lanes(self) -> None:
        project = self.selected_project()
        prompt = self.selected_prompt()
        root = git_root(project)
        try:
            snapshot = inspect_project(project)
            context = snapshot.summary()
            self.project_snapshot = snapshot
        except Exception:  # noqa: BLE001
            context = self.project_snapshot.summary() if self.project_snapshot else ""
        self.agent_plan = build_agent_plan(
            project,
            prompt,
            context,
            is_git=bool(root),
            git_root=root,
        )
        self.selected_agent_lane = self.agent_plan.lanes[0] if self.agent_plan.lanes else None
        self.agent_results = []
        self.selected_agent_result = None
        self.render_agent_lanes()
        self.render_agent_results()
        mode = "worktree lanes" if self.agent_plan.is_git else "shared-directory lanes"
        if hasattr(self, "agent_status_label"):
            self.agent_status_label.set_text(f"{len(self.agent_plan.lanes)} {mode} planned")
        if hasattr(self, "agent_result_status_label"):
            self.agent_result_status_label.set_text("Refresh after lanes run")
        self.set_status("Agent lanes planned")

    def ensure_agent_plan(self) -> bool:
        prompt = self.selected_prompt().strip()
        project = self.selected_project()
        if self.agent_plan is None or self.agent_plan.project != project or self.agent_plan.prompt != prompt:
            self.plan_agent_lanes()
        return self.agent_plan is not None and bool(self.agent_plan.lanes)

    def render_agent_lanes(self) -> None:
        if not hasattr(self, "agent_list"):
            return
        self.clear_listbox(self.agent_list)
        if self.agent_plan is None or not self.agent_plan.lanes:
            row = Gtk.ListBoxRow()
            row.add_css_class("agent-row")
            row.set_child(self.label("No lanes planned yet", "muted"))
            self.agent_list.append(row)
            return
        for lane in self.agent_plan.lanes:
            row = Gtk.ListBoxRow()
            row.lane = lane
            row.add_css_class("agent-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(lane.title, "agent-role")
            title.set_hexpand(True)
            chip = self.chip_label("worktree" if lane.uses_worktree else "shared", "chip")
            top.append(title)
            top.append(chip)
            objective = self.label(lane.objective, "agent-objective", wrap=True)
            meta = self.label(f"{Path(lane.workdir).name} | {lane.profile}", "muted")
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(top)
            content.append(objective)
            content.append(meta)
            row.set_child(content)
            self.agent_list.append(row)
            if self.selected_agent_lane and lane.slug == self.selected_agent_lane.slug:
                self.agent_list.select_row(row)

    def on_agent_lane_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_agent_lane = getattr(row, "lane", None) if row is not None else None
        if self.selected_agent_lane is not None:
            self.set_status(f"Selected {self.selected_agent_lane.title} lane")

    def on_agent_lane_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        lane = getattr(row, "lane", None)
        if lane is not None:
            self.selected_agent_lane = lane
            self.on_run_agent_lane(Gtk.Button())

    def on_plan_agents(self, _button: Gtk.Button) -> None:
        self.plan_agent_lanes()
        self.save_current_agent_run("planned", silent=True)

    def agent_lane_args(self, lane: AgentLane) -> list[str]:
        args = [self.codex_bin]
        args.extend(self.common_args_for_project(lane.workdir, lane.profile))
        args.append("exec")
        if self.skip_git_switch.get_active() or not lane.uses_worktree:
            args.append("--skip-git-repo-check")
        args.append(lane.prompt)
        return args

    def agent_lane_script(self, lane: AgentLane) -> str:
        assert self.agent_plan is not None
        header = shlex.quote(f"[Codex Control] Agent lane: {lane.title}")
        return "\n".join([
            prepare_worktree_script(lane, self.agent_plan.root),
            f"printf '%s\\n' {header}",
            shell_join(self.agent_lane_args(lane)),
        ])

    def combined_agent_script(self) -> str:
        if not self.ensure_agent_plan() or self.agent_plan is None:
            return ""
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"# Codex Control agent plan {self.agent_plan.run_id}",
            "",
        ]
        lines.extend("# " + line if line else "#" for line in plan_markdown(self.agent_plan).splitlines())
        lines.append("")
        for lane in self.agent_plan.lanes:
            lines.extend([
                f"printf '%s\\n' {shlex.quote('[Codex Control] launching ' + lane.title)}",
                "(",
                self.agent_lane_script(lane),
                ") &",
                "",
            ])
        lines.extend(["wait", "printf '%s\\n' '[Codex Control] all agent lanes finished'"])
        return "\n".join(lines)

    def on_prepare_agent_worktrees(self, _button: Gtk.Button) -> None:
        if not self.ensure_agent_plan() or self.agent_plan is None:
            self.set_status("No agent plan", "warn")
            return
        if not self.agent_plan.is_git:
            self.set_status("No git repo for worktrees", "warn")
            return
        scripts = []
        for lane in self.agent_plan.lanes:
            scripts.append(f"printf '%s\\n' {shlex.quote('Preparing ' + lane.title)}")
            scripts.append(prepare_worktree_script(lane, self.agent_plan.root))
        self.run_embedded_command(["bash", "-lc", "\n".join(["set -e", *scripts, "git worktree list"])])

    def on_run_agent_lane(self, _button: Gtk.Button) -> None:
        if not self.ensure_agent_plan():
            self.set_status("No agent plan", "warn")
            return
        lane = self.selected_agent_lane or (self.agent_plan.lanes[0] if self.agent_plan else None)
        if lane is None:
            self.set_status("Select an agent lane", "warn")
            return
        self.save_current_agent_run("running", silent=True)
        self.run_embedded_command(["bash", "-lc", self.agent_lane_script(lane)])

    def on_launch_all_agents(self, _button: Gtk.Button) -> None:
        if not self.ensure_agent_plan() or self.agent_plan is None:
            self.set_status("No agent plan", "warn")
            return
        self.save_current_agent_run("launched", silent=True)
        for lane in self.agent_plan.lanes:
            self.launch_external(["bash", "-lc", self.agent_lane_script(lane)], f"Agent {lane.title}")
        self.set_status(f"Launched {len(self.agent_plan.lanes)} agent lanes")

    def on_copy_agent_script(self, _button: Gtk.Button) -> None:
        script = self.combined_agent_script()
        display = Gdk.Display.get_default()
        if display is not None and script:
            display.get_clipboard().set(script)
            self.set_status("Agent script copied")

    def persist_agent_runs(self) -> None:
        save_agent_runs(AGENT_RUNS_FILE, self.agent_runs)

    def save_current_agent_run(
        self,
        status: str = "planned",
        silent: bool = False,
        artifacts: tuple[str, ...] = (),
    ) -> AgentRunRecord | None:
        if not self.ensure_agent_plan() or self.agent_plan is None:
            if not silent:
                self.set_status("No agent plan", "warn")
            return None
        existing = next((record for record in self.agent_runs if record.id == self.agent_plan.run_id), None)
        merged_artifacts = tuple(dict.fromkeys([
            *((existing.artifacts if existing is not None else ())),
            *artifacts,
        ]))
        record = record_from_plan(
            self.agent_plan,
            tuple(self.agent_results),
            status=status,
            artifacts=merged_artifacts,
            existing=existing,
        )
        self.agent_runs = upsert_agent_run(self.agent_runs, record)
        self.selected_agent_run = record
        self.persist_agent_runs()
        self.render_agent_runs()
        if not silent:
            self.set_status("Agent run saved")
        return record

    def agent_run_detail_text(self, record: AgentRunRecord | None) -> str:
        if record is None:
            return "No agent run selected."
        lines = [
            f"# {record.title}",
            "",
            f"Status: {record.status}",
            f"Run id: {record.id}",
            f"Project: {record.project}",
            f"Created: {human_time(record.created)}",
            f"Updated: {human_time(record.updated)}",
            f"Isolation: {'Git worktrees' if record.plan.is_git else 'shared project directory'}",
            "",
            "Prompt:",
            record.prompt or "(empty)",
            "",
            "Lanes:",
        ]
        result_by_slug = {result.lane_slug: result for result in record.results}
        for lane in record.plan.lanes:
            result = result_by_slug.get(lane.slug)
            result_text = f" | {result.status}, {result.tracked} tracked, {result.untracked} untracked" if result else ""
            lines.append(f"- {lane.title}: {lane.workdir}{result_text}")
        if record.results:
            lines.extend(["", "Results:"])
            for result in record.results:
                lines.append(f"- {result.title}: {result.note}")
                if result.diff_stat:
                    lines.extend(f"  {line}" for line in result.diff_stat[:4])
        if record.artifacts:
            lines.extend(["", "Artifacts:"])
            lines.extend(f"- {artifact}" for artifact in record.artifacts)
        return "\n".join(lines)

    def render_agent_runs(self) -> None:
        if not hasattr(self, "agent_run_list"):
            return
        self.clear_listbox(self.agent_run_list)
        if not self.agent_runs:
            row = Gtk.ListBoxRow()
            row.add_css_class("run-row")
            row.set_child(self.label("No saved agent runs yet", "muted"))
            self.agent_run_list.append(row)
            self.set_text(getattr(self, "agent_run_detail_buffer", None), "No saved agent runs yet.")
            return
        for record in self.agent_runs:
            row = Gtk.ListBoxRow()
            row.record = record
            row.add_css_class("run-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(record.title, "run-title")
            title.set_hexpand(True)
            status = self.chip_label(record.status, "chip-strong" if record.status in {"running", "launched"} else "chip")
            top.append(title)
            top.append(status)
            changed = sum(1 for result in record.results if result.status == "changed")
            meta = self.label(
                f"{Path(record.project).name or record.project} | {human_time(record.updated)} | {len(record.plan.lanes)} lanes | {changed} changed",
                "run-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(top)
            content.append(meta)
            row.set_child(content)
            self.agent_run_list.append(row)
            if self.selected_agent_run and record.id == self.selected_agent_run.id:
                self.agent_run_list.select_row(row)
        self.set_text(getattr(self, "agent_run_detail_buffer", None), self.agent_run_detail_text(self.selected_agent_run))

    def apply_agent_run_record(self, record: AgentRunRecord) -> None:
        self.selected_agent_run = record
        self.agent_plan = record.plan
        self.agent_results = list(record.results)
        self.selected_agent_lane = record.plan.lanes[0] if record.plan.lanes else None
        self.selected_agent_result = self.agent_results[0] if self.agent_results else None
        self.project_entry.set_text(record.project)
        if self.prompt_buffer is not None:
            self.prompt_buffer.set_text(record.prompt)
        self.render_agent_lanes()
        self.render_agent_results()
        self.render_agent_runs()
        if hasattr(self, "agent_status_label"):
            mode = "worktree lanes" if record.plan.is_git else "shared-directory lanes"
            self.agent_status_label.set_text(f"{len(record.plan.lanes)} {mode} loaded")
        if hasattr(self, "agent_result_status_label"):
            changed = sum(1 for result in self.agent_results if result.status == "changed")
            missing = sum(1 for result in self.agent_results if result.status == "missing")
            self.agent_result_status_label.set_text(f"{changed} changed, {missing} missing, {len(self.agent_results)} lanes")
        if self.stack is not None:
            self.stack.set_visible_child_name("launch")
        self.update_command_preview()
        self.set_status(f"Loaded {record.title}")

    def on_agent_run_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_agent_run = getattr(row, "record", None) if row is not None else None
        self.set_text(getattr(self, "agent_run_detail_buffer", None), self.agent_run_detail_text(self.selected_agent_run))

    def on_agent_run_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        record = getattr(row, "record", None)
        if record is not None:
            self.apply_agent_run_record(record)

    def on_save_agent_run(self, _button: Gtk.Button) -> None:
        self.save_current_agent_run("saved", silent=False)

    def on_load_agent_run(self, _button: Gtk.Button) -> None:
        if self.selected_agent_run is None:
            self.set_status("Select an agent run", "warn")
            return
        self.apply_agent_run_record(self.selected_agent_run)

    def on_delete_agent_run(self, _button: Gtk.Button) -> None:
        if self.selected_agent_run is None:
            self.set_status("Select an agent run", "warn")
            return
        self.agent_runs = remove_agent_run(self.agent_runs, self.selected_agent_run.id)
        self.selected_agent_run = self.agent_runs[0] if self.agent_runs else None
        self.persist_agent_runs()
        self.render_agent_runs()
        self.set_status("Agent run deleted")

    def on_copy_agent_run(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(self.agent_run_detail_text(self.selected_agent_run))
            self.set_status("Agent run copied")

    def on_reload_agent_runs(self, _button: Gtk.Button) -> None:
        selected_id = self.selected_agent_run.id if self.selected_agent_run else ""
        self.agent_runs = load_agent_runs(AGENT_RUNS_FILE)
        self.selected_agent_run = next(
            (record for record in self.agent_runs if record.id == selected_id),
            self.agent_runs[0] if self.agent_runs else None,
        )
        self.render_agent_runs()
        self.set_status("Agent runs reloaded")

    def agent_lane_monitor_args(self, lane: AgentLane, final_path: str) -> list[str]:
        args = [self.codex_bin]
        args.extend(self.common_args_for_project(lane.workdir, lane.profile))
        args.extend(["exec", "--json", "--output-last-message", final_path])
        if self.skip_git_switch.get_active() or not lane.uses_worktree:
            args.append("--skip-git-repo-check")
        args.append(lane.prompt)
        return args

    def upsert_execution_record(self, record: AgentExecutionRecord) -> None:
        replaced = False
        records: list[AgentExecutionRecord] = []
        for existing in self.agent_executions:
            if existing.id == record.id:
                records.append(record)
                replaced = True
            else:
                records.append(existing)
        if not replaced:
            records.insert(0, record)
        self.agent_executions = records
        if self.selected_agent_execution is None or self.selected_agent_execution.id == record.id:
            self.selected_agent_execution = record
        self.render_execution_monitor()

    def execution_detail_text(self, record: AgentExecutionRecord | None, mode: str = "summary") -> str:
        if record is None:
            return "No execution selected."
        lines = [
            f"# {record.title}",
            "",
            f"Status: {record.status}",
            f"Execution id: {record.id}",
            f"Run id: {record.run_id}",
            f"Lane: {record.lane_slug}",
            f"Workdir: {record.workdir}",
            f"PID: {record.pid or 'not running'}",
            f"Exit code: {record.exit_code if record.exit_code is not None else 'pending'}",
            f"Started: {human_time(record.started)}",
            f"Finished: {human_time(record.finished) if record.finished else 'pending'}",
            f"Log: {record.log_path}",
            f"Final: {record.final_path}",
            "",
            "Command:",
            shell_join(list(record.command)) if record.command else "(not started)",
        ]
        final_text = tail_text(Path(record.final_path), limit=8000)
        log_text = tail_text(Path(record.log_path), limit=16000)
        if mode == "final":
            lines.extend(["", "Final message:", final_text or "(empty)"])
        elif mode == "log":
            lines.extend(["", "Log tail:", log_text or "(empty)"])
        else:
            if final_text:
                lines.extend(["", "Final message:", final_text])
            if log_text:
                lines.extend(["", "Log tail:", log_text])
        return "\n".join(lines)

    def render_execution_monitor(self) -> None:
        if not hasattr(self, "execution_list"):
            return
        self.clear_listbox(self.execution_list)
        if not self.agent_executions:
            row = Gtk.ListBoxRow()
            row.add_css_class("execution-row")
            row.set_child(self.label("No monitored executions yet", "muted"))
            self.execution_list.append(row)
            self.set_text(getattr(self, "execution_detail_buffer", None), "No monitored executions yet.")
            return
        for record in self.agent_executions:
            row = Gtk.ListBoxRow()
            row.record = record
            row.add_css_class("execution-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(record.title, "execution-title")
            title.set_hexpand(True)
            chip_class = "chip-strong" if record.status in {"running", "done"} else ("chip-danger" if record.status in {"failed", "stopped"} else "chip")
            top.append(title)
            top.append(self.chip_label(record.status, chip_class))
            meta = self.label(
                f"{Path(record.workdir).name or record.workdir} | pid {record.pid or '-'} | exit {record.exit_code if record.exit_code is not None else '-'}",
                "execution-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(top)
            content.append(meta)
            row.set_child(content)
            self.execution_list.append(row)
            if self.selected_agent_execution and record.id == self.selected_agent_execution.id:
                self.execution_list.select_row(row)
        self.set_text(getattr(self, "execution_detail_buffer", None), self.execution_detail_text(self.selected_agent_execution))

    def selected_atlas_root(self) -> str:
        if hasattr(self, "atlas_root_entry"):
            return self.atlas_root_entry.get_text().strip()
        return str(self.config.get("atlas_root") or "")

    def refresh_receipt_records(self) -> None:
        selected_id = self.selected_receipt.id if self.selected_receipt else ""
        self.receipt_records = load_receipt_records(RECEIPTS_DIR)
        self.selected_receipt = next(
            (record for record in self.receipt_records if record.id == selected_id),
            self.receipt_records[0] if self.receipt_records else None,
        )

    def render_receipt_list(self, listbox: Gtk.ListBox) -> None:
        self.clear_listbox(listbox)
        if not self.receipt_records:
            row = Gtk.ListBoxRow()
            row.add_css_class("receipt-row")
            row.set_child(self.label("No receipts yet", "muted"))
            listbox.append(row)
            return
        for record in self.receipt_records[:24]:
            row = Gtk.ListBoxRow()
            row.record = record
            row.add_css_class("receipt-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(f"{record.action} | {record.project_name}", "receipt-title")
            title.set_hexpand(True)
            chip_class = "chip-strong" if record.status == "verified" else ("chip-danger" if record.status == "unverified" else "chip")
            top.append(title)
            top.append(self.chip_label(record.status, chip_class))
            meta = self.label(
                f"{record.profile} | {record.observed_at or 'unknown'} | {short_id(record.event_hash or record.command_hash)}",
                "receipt-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(top)
            content.append(meta)
            row.set_child(content)
            listbox.append(row)
            if self.selected_receipt and record.id == self.selected_receipt.id:
                listbox.select_row(row)

    def render_receipts(self) -> None:
        self.rendering_receipts = True
        try:
            if hasattr(self, "receipt_compact_list"):
                self.render_receipt_list(self.receipt_compact_list)
            if hasattr(self, "receipt_page_list"):
                self.render_receipt_list(self.receipt_page_list)
        finally:
            self.rendering_receipts = False
        detail = receipt_detail(self.selected_receipt)
        if self.receipt_last_output:
            detail += "\n\nLast command output:\n" + self.receipt_last_output
        self.set_text(getattr(self, "receipt_detail_buffer", None), detail)
        if hasattr(self, "receipt_status_label"):
            if self.selected_receipt is None:
                text = "No receipts yet. Stamp the current command or run Codex with Auto enabled."
            else:
                text = f"Latest: {self.selected_receipt.action} | {self.selected_receipt.status} | {short_id(self.selected_receipt.event_hash or self.selected_receipt.command_hash)}"
            self.receipt_status_label.set_text(text)
        self.render_operator_brief()

    def apply_receipt_command_output(self, result: ReceiptCommandResult, title: str) -> None:
        self.receipt_last_output = f"$ {shell_join(list(result.command)) if result.command else title}\n\n{result.output}"
        self.refresh_receipt_records()
        self.render_receipts()
        self.set_status(title if result.status == 0 else f"{title} failed", "ok" if result.status == 0 else "warn")

    def apply_receipt_stamp(self, result: ReceiptStampResult) -> None:
        parts: list[str] = []
        if result.import_result is not None:
            parts.append(result.import_result.output)
        if result.verify_result is not None:
            parts.append(result.verify_result.output)
        if result.error:
            parts.append(result.error)
        self.receipt_last_output = "\n".join(part for part in parts if part).strip()
        self.refresh_receipt_records()
        self.selected_receipt = next(
            (record for record in self.receipt_records if record.id == result.record.id),
            result.record,
        )
        self.render_receipts()
        if result.error:
            self.set_status("Receipt event written", "warn")
        else:
            self.set_status("Receipt verified")

    def direct_codex_command(self, args: list[str]) -> bool:
        if not args:
            return False
        return Path(args[0]).name == Path(self.codex_bin).name

    def receipt_action_from_args(self, args: list[str]) -> str:
        for value in ["exec", "review", "resume", "fork", "doctor", "update", "login", "app-server"]:
            if value in args:
                return value
        return self.dropdown_value(self.action_combo) or "interactive"

    def persist_command_runs(self) -> None:
        save_run_records(RUNS_FILE, self.command_runs)

    def refresh_command_runs(self) -> None:
        selected_id = self.selected_command_run.id if self.selected_command_run else ""
        self.command_runs = load_run_records(RUNS_FILE)
        self.selected_command_run = next(
            (record for record in self.command_runs if record.id == selected_id),
            self.command_runs[0] if self.command_runs else None,
        )

    def record_codex_run(
        self,
        args: list[str],
        *,
        action: str,
        surface: str,
        status: str,
        receipt: CodexReceiptRecord | None = None,
        pid: int = 0,
        exit_code: int | None = None,
        note: str = "",
    ) -> CodexRunRecord:
        profile = self.dropdown_value(self.profile_combo) if hasattr(self, "profile_combo") else "none"
        record = new_run_record(
            project=self.selected_project(),
            action=action,
            profile=profile or "none",
            surface=surface,
            status=status,
            prompt=self.selected_prompt(),
            command=shell_join(args),
            receipt=receipt,
            pid=pid,
            exit_code=exit_code,
            note=note,
        )
        self.command_runs = upsert_run_record(self.command_runs, record)
        self.selected_command_run = record
        self.persist_command_runs()
        self.render_command_runs()
        return record

    def update_command_run_status(self, record_id: str, status: str, exit_code: int | None = None, pid: int = 0) -> None:
        if not record_id:
            return
        for record in self.command_runs:
            if record.id != record_id:
                continue
            changes: dict[str, object] = {"status": status}
            if exit_code is not None:
                changes["exit_code"] = exit_code
            if pid:
                changes["pid"] = pid
            updated = update_run_record(record, **changes)
            self.command_runs = upsert_run_record(self.command_runs, updated)
            self.selected_command_run = updated
            self.persist_command_runs()
            self.render_command_runs()
            return

    def stamp_command_receipt(
        self,
        args: list[str],
        action: str | None = None,
        force: bool = False,
        surface: str = "embedded",
        run_status: str = "launched",
    ) -> CodexRunRecord | None:
        if not self.direct_codex_command(args):
            return None
        profile = self.dropdown_value(self.profile_combo) if hasattr(self, "profile_combo") else "none"
        resolved_action = action or self.receipt_action_from_args(args)
        result: ReceiptStampResult | None = None
        if force or (hasattr(self, "receipt_auto_switch") and self.receipt_auto_switch.get_active()):
            result = stamp_codex_receipt(
                RECEIPTS_DIR,
                atlas_root=self.selected_atlas_root() or None,
                project=self.selected_project(),
                action=resolved_action,
                profile=profile or "none",
                prompt=self.selected_prompt(),
                command=shell_join(args),
            )
            self.apply_receipt_stamp(result)
        return self.record_codex_run(
            args,
            action=resolved_action,
            surface=surface,
            status=run_status,
            receipt=result.record if result is not None and not result.error else None,
            note="receipt verified" if result is not None and not result.error else ("receipt unavailable" if result is not None else "receipt disabled"),
        )

    def on_stamp_receipt(self, _button: Gtk.Button) -> None:
        action = self.dropdown_value(self.action_combo) or "interactive"
        self.stamp_command_receipt(self.build_command(action), action, force=True, surface="manual", run_status="prepared")

    def on_verify_receipt(self, _button: Gtk.Button) -> None:
        record = self.selected_receipt
        if record is None or not record.receipt_path or not Path(record.receipt_path).exists():
            self.set_status("Select a written receipt", "warn")
            return
        result = verify_receipt(self.selected_atlas_root() or None, Path(record.receipt_path))
        self.apply_receipt_command_output(result, "Receipt verify")

    def on_replay_receipts(self, _button: Gtk.Button) -> None:
        chain = linked_receipt_chain(self.receipt_records, self.selected_receipt)
        paths = [Path(record.receipt_path) for record in chain if Path(record.receipt_path).exists()]
        if len(paths) < 2:
            self.set_status("Need two receipts to replay", "warn")
            return
        result = replay_receipts(self.selected_atlas_root() or None, paths)
        self.apply_receipt_command_output(result, "Receipt replay")

    def on_open_receipts(self, _button: Gtk.Button) -> None:
        RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(RECEIPTS_DIR)], start_new_session=True)
        self.set_status("Opened receipts folder")

    def on_copy_receipt(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(receipt_detail(self.selected_receipt))
            self.set_status("Receipt detail copied")

    def on_refresh_receipts(self, _button: Gtk.Button) -> None:
        self.refresh_receipt_records()
        self.render_receipts()
        self.set_status("Receipts refreshed")

    def on_receipt_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self.rendering_receipts:
            return
        self.selected_receipt = getattr(row, "record", None) if row is not None else None
        self.render_receipts()

    def render_command_run_list(self, listbox: Gtk.ListBox) -> None:
        self.clear_listbox(listbox)
        if not self.command_runs:
            row = Gtk.ListBoxRow()
            row.add_css_class("command-run-row")
            row.set_child(self.label("No Codex launches recorded yet", "muted"))
            listbox.append(row)
            return
        for record in self.command_runs[:30]:
            row = Gtk.ListBoxRow()
            row.record = record
            row.add_css_class("command-run-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(f"{record.action} | {record.project_name}", "command-run-title")
            title.set_hexpand(True)
            chip_class = "chip-strong" if record.status in {"done", "launched", "prepared"} else ("chip-danger" if record.status in {"failed", "stopped"} else "chip")
            top.append(title)
            top.append(self.chip_label(record.status, chip_class))
            meta = self.label(
                f"{record.surface} | {record.profile} | {short_id(record.receipt_hash or record.command_hash)}",
                "command-run-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(top)
            content.append(meta)
            row.set_child(content)
            listbox.append(row)
            if self.selected_command_run and record.id == self.selected_command_run.id:
                listbox.select_row(row)

    def render_command_runs(self) -> None:
        self.rendering_command_runs = True
        try:
            if hasattr(self, "command_run_compact_list"):
                self.render_command_run_list(self.command_run_compact_list)
            if hasattr(self, "command_run_page_list"):
                self.render_command_run_list(self.command_run_page_list)
        finally:
            self.rendering_command_runs = False
        self.set_text(getattr(self, "command_run_detail_buffer", None), run_detail(self.selected_command_run))
        if hasattr(self, "command_run_status_label"):
            if self.selected_command_run is None:
                text = "No runs yet. Launch Codex to start the metadata-only ledger."
            else:
                text = f"Latest: {self.selected_command_run.action} | {self.selected_command_run.status} | {short_id(self.selected_command_run.receipt_hash or self.selected_command_run.command_hash)}"
            self.command_run_status_label.set_text(text)
        self.render_operator_brief()

    def on_command_run_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self.rendering_command_runs:
            return
        self.selected_command_run = getattr(row, "record", None) if row is not None else None
        self.render_command_runs()

    def on_refresh_command_runs(self, _button: Gtk.Button) -> None:
        self.refresh_command_runs()
        self.render_command_runs()
        self.set_status("Run ledger refreshed")

    def on_copy_command_run(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(run_detail(self.selected_command_run))
            self.set_status("Run detail copied")

    def on_open_command_run_receipt(self, _button: Gtk.Button) -> None:
        record = self.selected_command_run
        if record is None or not record.receipt_path:
            self.set_status("Selected run has no receipt", "warn")
            return
        path = Path(record.receipt_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(path.parent)], start_new_session=True)
        self.set_status("Opened linked receipt folder")

    def on_delete_command_run(self, _button: Gtk.Button) -> None:
        if self.selected_command_run is None:
            self.set_status("Select a run", "warn")
            return
        self.command_runs = remove_run_record(self.command_runs, self.selected_command_run.id)
        self.selected_command_run = self.command_runs[0] if self.command_runs else None
        self.persist_command_runs()
        self.render_command_runs()
        self.set_status("Run removed")

    def selected_execution_lane(self) -> AgentLane | None:
        if self.selected_agent_execution is None or self.agent_plan is None:
            return None
        for lane in self.agent_plan.lanes:
            if lane.slug == self.selected_agent_execution.lane_slug:
                return lane
        return None

    def start_monitored_lane(self, lane: AgentLane) -> None:
        if self.agent_plan is None:
            self.set_status("No agent plan", "warn")
            return
        base_record = new_execution_record(EXECUTIONS_DIR, self.agent_plan.run_id, lane, [])
        args = self.agent_lane_monitor_args(lane, base_record.final_path)
        command_run = self.stamp_command_receipt(args, f"agent-{lane.slug}", surface="agent-monitor", run_status="queued")
        record = update_execution_record(base_record, command=tuple(args), status="queued", started=int(dt.datetime.now().timestamp()))
        if command_run is not None:
            self.execution_run_ids[record.id] = command_run.id
        self.upsert_execution_record(record)
        self.save_current_agent_run("running", silent=True, artifacts=(record.log_path, record.final_path))
        if self.stack is not None:
            self.stack.set_visible_child_name("monitor")

        run_root = self.agent_plan.root

        def worker() -> None:
            log_path = Path(record.log_path)
            final_path = Path(record.final_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
                prep = subprocess.run(
                    ["bash", "-lc", prepare_worktree_script(lane, run_root)],
                    text=True,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                if prep.returncode != 0:
                    GLib.idle_add(self.on_execution_finished, record.id, prep.returncode)
                    return
                proc = subprocess.Popen(
                    args,
                    cwd=lane.workdir,
                    text=True,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                GLib.idle_add(self.on_execution_started, record.id, proc)
                code = proc.wait()
            GLib.idle_add(self.on_execution_finished, record.id, code)

        threading.Thread(target=worker, daemon=True).start()
        self.set_status(f"Tracking {lane.title}")

    def on_execution_started(self, execution_id_value: str, proc: subprocess.Popen[str]) -> bool:
        self.agent_execution_procs[execution_id_value] = proc
        self.update_command_run_status(self.execution_run_ids.get(execution_id_value, ""), "running", pid=proc.pid)
        for record in self.agent_executions:
            if record.id == execution_id_value:
                self.upsert_execution_record(update_execution_record(record, status="running", pid=proc.pid))
                break
        return False

    def on_execution_finished(self, execution_id_value: str, code: int) -> bool:
        self.agent_execution_procs.pop(execution_id_value, None)
        for record in self.agent_executions:
            if record.id != execution_id_value:
                continue
            status = "stopped" if record.status == "stopping" else ("done" if code == 0 else "failed")
            self.upsert_execution_record(update_execution_record(
                record,
                status=status,
                exit_code=code,
                finished=int(dt.datetime.now().timestamp()),
            ))
            self.update_command_run_status(self.execution_run_ids.get(execution_id_value, ""), status, exit_code=code)
            break
        if self.agent_plan is not None:
            self.agent_results = list(collect_agent_results(self.agent_plan))
            self.render_agent_results()
            self.save_current_agent_run("finished", silent=True, artifacts=tuple(
                artifact
                for execution in self.agent_executions
                for artifact in (execution.log_path, execution.final_path)
            ))
        self.set_status("Execution finished" if code == 0 else "Execution failed", "ok" if code == 0 else "warn")
        return False

    def on_run_monitored_agent_lane(self, _button: Gtk.Button) -> None:
        if not self.ensure_agent_plan():
            self.set_status("No agent plan", "warn")
            return
        lane = self.selected_agent_lane or (self.agent_plan.lanes[0] if self.agent_plan else None)
        if lane is None:
            self.set_status("Select an agent lane", "warn")
            return
        self.start_monitored_lane(lane)

    def on_run_all_monitored_agents(self, _button: Gtk.Button) -> None:
        if not self.ensure_agent_plan() or self.agent_plan is None:
            self.set_status("No agent plan", "warn")
            return
        for lane in self.agent_plan.lanes:
            self.start_monitored_lane(lane)
        self.set_status(f"Tracking {len(self.agent_plan.lanes)} lanes")

    def on_stop_agent_execution(self, _button: Gtk.Button) -> None:
        record = self.selected_agent_execution
        if record is None:
            self.set_status("Select an execution", "warn")
            return
        proc = self.agent_execution_procs.get(record.id)
        if proc is None or proc.poll() is not None:
            self.set_status("Execution is not running", "warn")
            return
        self.upsert_execution_record(update_execution_record(record, status="stopping"))
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        self.set_status("Stopping execution", "warn")

    def on_show_execution_log(self, _button: Gtk.Button) -> None:
        self.set_text(getattr(self, "execution_detail_buffer", None), self.execution_detail_text(self.selected_agent_execution, "log"))

    def on_show_execution_final(self, _button: Gtk.Button) -> None:
        self.set_text(getattr(self, "execution_detail_buffer", None), self.execution_detail_text(self.selected_agent_execution, "final"))

    def on_open_execution_artifacts(self, _button: Gtk.Button) -> None:
        record = self.selected_agent_execution
        if record is None:
            self.set_status("Select an execution", "warn")
            return
        Path(record.log_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(Path(record.log_path).parent)], start_new_session=True)
        self.set_status("Opened execution folder")

    def on_copy_execution_detail(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(self.execution_detail_text(self.selected_agent_execution))
            self.set_status("Execution detail copied")

    def on_refresh_execution_monitor(self, _button: Gtk.Button) -> None:
        for record in list(self.agent_executions):
            proc = self.agent_execution_procs.get(record.id)
            if proc is not None and proc.poll() is not None:
                self.on_execution_finished(record.id, int(proc.returncode or 0))
        self.render_execution_monitor()
        self.set_status("Monitor refreshed")

    def on_execution_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_agent_execution = getattr(row, "record", None) if row is not None else None
        self.set_text(getattr(self, "execution_detail_buffer", None), self.execution_detail_text(self.selected_agent_execution))

    def on_execution_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self.selected_agent_execution = getattr(row, "record", None)
        self.on_show_execution_log(Gtk.Button())

    def lane_for_result(self, result: AgentResult | None) -> AgentLane | None:
        if result is None or self.agent_plan is None:
            return None
        for lane in self.agent_plan.lanes:
            if lane.slug == result.lane_slug:
                return lane
        return None

    def result_summary_text(self, result: AgentResult) -> str:
        lines = [
            f"{result.title} [{result.status}]",
            f"Workdir: {result.workdir}",
            f"Branch: {result.branch or 'none'}",
            f"Tracked: {result.tracked}",
            f"Untracked: {result.untracked}",
            f"Note: {result.note}",
        ]
        if result.status_lines:
            lines.append("")
            lines.append("Status:")
            lines.extend(result.status_lines)
        if result.diff_stat:
            lines.append("")
            lines.append("Diff stat:")
            lines.extend(result.diff_stat)
        return "\n".join(lines)

    def refresh_agent_results(self, show_status: bool = True) -> None:
        if not self.ensure_agent_plan() or self.agent_plan is None:
            if show_status:
                self.set_status("No agent plan", "warn")
            return
        selected_slug = self.selected_agent_result.lane_slug if self.selected_agent_result else ""
        self.agent_results = list(collect_agent_results(self.agent_plan))
        self.selected_agent_result = next(
            (result for result in self.agent_results if result.lane_slug == selected_slug),
            self.agent_results[0] if self.agent_results else None,
        )
        self.render_agent_results()
        changed = sum(1 for result in self.agent_results if result.status == "changed")
        missing = sum(1 for result in self.agent_results if result.status == "missing")
        summary = f"{changed} changed, {missing} missing, {len(self.agent_results)} lanes"
        if hasattr(self, "agent_result_status_label"):
            self.agent_result_status_label.set_text(summary)
        if show_status:
            self.save_current_agent_run("refreshed", silent=True)
            self.set_status("Agent results refreshed")

    def render_agent_results(self) -> None:
        if not hasattr(self, "agent_result_list"):
            return
        self.clear_listbox(self.agent_result_list)
        if not self.agent_results:
            row = Gtk.ListBoxRow()
            row.add_css_class("result-row")
            row.set_child(self.label("No lane results collected yet", "muted"))
            self.agent_result_list.append(row)
            return
        for result in self.agent_results:
            row = Gtk.ListBoxRow()
            row.result = result
            row.add_css_class("result-row")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(result.title, "result-title")
            title.set_hexpand(True)
            chip = self.chip_label(result.status, "chip-strong" if result.status == "changed" else "chip")
            top.append(title)
            top.append(chip)
            meta = self.label(
                f"{Path(result.workdir).name} | {result.tracked} tracked | {result.untracked} untracked",
                "result-meta",
            )
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            note = self.label(result.note, "muted", wrap=True)
            content.append(top)
            content.append(meta)
            content.append(note)
            row.set_child(content)
            self.agent_result_list.append(row)
            if self.selected_agent_result and result.lane_slug == self.selected_agent_result.lane_slug:
                self.agent_result_list.select_row(row)

    def on_agent_result_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_agent_result = getattr(row, "result", None) if row is not None else None
        if self.selected_agent_result is not None:
            self.set_status(f"Selected {self.selected_agent_result.title} result")

    def on_agent_result_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        result = getattr(row, "result", None)
        if result is not None:
            self.selected_agent_result = result
            self.on_diff_agent_result(Gtk.Button())

    def on_refresh_agent_results(self, _button: Gtk.Button) -> None:
        self.refresh_agent_results(show_status=True)

    def on_diff_agent_result(self, _button: Gtk.Button) -> None:
        if not self.agent_results:
            self.refresh_agent_results(show_status=False)
        lane = self.lane_for_result(self.selected_agent_result)
        if lane is None:
            self.set_status("Select a lane result", "warn")
            return
        self.run_embedded_command(["bash", "-lc", lane_diff_script(lane)])

    def on_apply_agent_result(self, _button: Gtk.Button) -> None:
        result = self.selected_agent_result
        lane = self.lane_for_result(result)
        if lane is None or self.agent_plan is None:
            self.set_status("Select a lane result", "warn")
            return
        if result is None or not result.can_apply:
            self.set_status("No tracked lane diff to apply", "warn")
            return
        self.run_embedded_command(["bash", "-lc", lane_apply_script(lane, self.agent_plan.root)])

    def on_merge_agent_result(self, _button: Gtk.Button) -> None:
        result = self.selected_agent_result
        lane = self.lane_for_result(result)
        if lane is None or self.agent_plan is None:
            self.set_status("Select a lane result", "warn")
            return
        if result is None or not result.can_merge:
            self.set_status("Lane has no merge branch", "warn")
            return
        self.run_embedded_command(["bash", "-lc", lane_merge_script(lane, self.agent_plan.root)])

    def on_open_agent_result(self, _button: Gtk.Button) -> None:
        result = self.selected_agent_result
        if result is None:
            self.set_status("Select a lane result", "warn")
            return
        if not result.exists:
            self.set_status("Lane workdir missing", "warn")
            return
        subprocess.Popen(["xdg-open", result.workdir], start_new_session=True)
        self.set_status("Opened lane folder")

    def on_copy_agent_result(self, _button: Gtk.Button) -> None:
        result = self.selected_agent_result
        if result is None:
            self.set_status("Select a lane result", "warn")
            return
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(self.result_summary_text(result))
            self.set_status("Result summary copied")

    def on_run_project_command(self, _button: Gtk.Button, command: ProjectCommand) -> None:
        self.run_embedded_command(["bash", "-lc", command.command])

    def on_copy_project_command(self, _button: Gtk.Button, command: ProjectCommand) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(command.command)
            self.set_status(f"Copied {command.label}")

    def refresh_health_async(self) -> None:
        self.set_status("Checking...")
        def worker() -> None:
            try:
                result = run_cmd([self.codex_bin, "doctor", "--json"], timeout=35)
                if result.returncode != 0:
                    GLib.idle_add(self.apply_health_error, result.stdout + result.stderr)
                    return
                GLib.idle_add(self.apply_health, json.loads(result.stdout))
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self.apply_health_error, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def apply_health(self, data: dict[str, Any]) -> bool:
        checks = data.get("checks", {})
        config = checks.get("config.load", {}).get("details", {})
        auth = checks.get("auth.credentials", {}).get("summary", "auth unknown")
        update_details = checks.get("updates.status", {}).get("details", {})
        app_server = checks.get("app_server.status", {}).get("summary", "unknown")
        version = data.get("codexVersion", "unknown")
        model = config.get("model", "unknown")
        overall = data.get("overallStatus", "unknown")
        latest = update_details.get("latest version", "unknown")
        terminal = "Embedded VTE" if Vte is not None else "External terminal"
        project = self.selected_project()

        self.card_codex.value_label.set_text(f"{version} / latest {latest}")
        self.card_auth.value_label.set_text(auth)
        self.card_model.value_label.set_text(str(model))
        self.card_terminal.value_label.set_text(terminal)
        self.card_appserver.value_label.set_text(app_server)
        self.card_project.value_label.set_text(Path(project).name or project)
        if hasattr(self, "launch_codex_card"):
            self.launch_codex_card.value_label.set_text(str(version))
            self.launch_model_card.value_label.set_text(str(model))
            self.launch_mode_card.value_label.set_text(self.selected_mode_label())
            self.launch_auth_card.value_label.set_text("ChatGPT" if "configured" in auth else auth)
            self.launch_project_card.value_label.set_text(Path(project).name or project)
            self.refresh_power_labels()

        summary = {
            "overall": overall,
            "version": version,
            "latest": latest,
            "auth": auth,
            "default_model": model,
            "app_server": app_server,
            "terminal": terminal,
            "codex_bin": self.codex_bin,
            "project": project,
        }
        self.health_summary = summary
        self.set_text(self.health_buffer, json.dumps(summary, indent=2))
        if hasattr(self, "preflight_summary_label") or hasattr(self, "preflight_page_summary_label"):
            self.refresh_preflight()
        if hasattr(self, "mission_title_label") or hasattr(self, "mission_page_title_label"):
            self.refresh_mission_blueprint()
        self.render_operator_brief()
        self.set_status("Codex ready" if overall == "ok" else "Check health", "ok" if overall == "ok" else "warn")
        return False

    def apply_health_error(self, text: str) -> bool:
        self.health_summary = {"auth": "unknown", "overall": "error"}
        self.set_text(self.health_buffer, text)
        if hasattr(self, "preflight_summary_label") or hasattr(self, "preflight_page_summary_label"):
            self.refresh_preflight()
        if hasattr(self, "mission_title_label") or hasattr(self, "mission_page_title_label"):
            self.refresh_mission_blueprint()
        self.render_operator_brief()
        self.set_status("Health failed", "bad")
        return False

    def on_run_setup_check(self, _button: Gtk.Button | None = None) -> None:
        report = build_setup_report(
            project=self.selected_project(),
            codex_bin=self.codex_bin,
            desktop_file=Path.home() / ".local" / "share" / "applications" / "codex-gui.desktop",
            devices_file=DEVICES_FILE,
        )
        self.set_text(self.health_buffer, report.detail_text())
        self.render_launcher_health_banner(report)
        status = "ok" if report.status == "ready" else "warn" if report.status == "review" else "bad"
        self.set_status(report.summary(), status)

    def render_launcher_health_banner(self, report: SetupReport) -> None:
        if not hasattr(self, "launcher_health_banner") or not hasattr(self, "launcher_health_banner_label"):
            return
        launcher = next((item for item in report.checks if item.id == "launcher"), None)
        if launcher is None or launcher.status == "ok":
            self.launcher_health_banner.set_visible(False)
            return
        self.launcher_health_banner.set_visible(True)
        self.launcher_health_banner_label.set_text(f"{launcher.title}: {launcher.detail}")
        self.launcher_health_banner_label.remove_css_class("warning")
        self.launcher_health_banner_label.remove_css_class("muted")
        if launcher.status in {"block", "warn"}:
            self.launcher_health_banner_label.add_css_class("warning")
        else:
            self.launcher_health_banner_label.add_css_class("muted")
        if launcher.fix and hasattr(self, "launcher_health_banner_button"):
            self.launcher_health_banner_button.set_visible(True)
            self.launcher_health_banner_button.set_tooltip_text(launcher.fix)
        else:
            self.launcher_health_banner_button.set_visible(False)

    def on_launcher_diagnostics(self, _button: Gtk.Button) -> None:
        self.set_status("Running launcher diagnostics")
        self.on_run_setup_check(None)

    def on_launcher_repair(self, _button: Gtk.Button) -> None:
        project = Path(self.selected_project())
        if not (project / "pyproject.toml").exists():
            fallback = Path.home() / "Projects" / "codex-gui"
            if (fallback / "pyproject.toml").exists():
                project = fallback
            else:
                self.set_status("Selected project is not a valid codex-gui checkout", "warn")
                return
        project = str(project)
        args = [sys.executable, "-m", "pip", "install", "--user", "."]
        self.set_text(self.health_buffer, f"$ {shell_join(args)}\n\nStarting launcher repair...\n")
        self.set_status("Repairing launcher")
        self.run_async_text(args, project, self.on_launcher_repair_done, timeout=300)

    def on_launcher_repair_done(self, text: str, code: int) -> bool:
        self.set_text(self.health_buffer, text)
        if code == 0:
            self.set_status("Launcher repair complete")
            self.on_run_setup_check(None)
        else:
            self.set_status("Launcher repair failed", "warn")
        return False

    def refresh_projects(self) -> None:
        paths = {self.selected_project()}
        for thread in read_threads():
            if thread.cwd:
                paths.add(thread.cwd)
        for repo in discover_git_repos():
            paths.add(repo)
        projects = [git_project_info(path) for path in sorted(paths) if Path(path).exists()]
        self.projects = sorted(projects, key=lambda p: (not p.is_git, p.name.lower()))
        self.render_projects()

    def render_projects(self) -> None:
        if not hasattr(self, "projects_list"):
            return
        self.clear_listbox(self.projects_list)
        needle = self.project_search.get_text().strip().lower() if hasattr(self, "project_search") else ""
        for project in self.projects:
            haystack = " ".join([project.name, project.path, project.branch, project.remote]).lower()
            if needle and needle not in haystack:
                continue
            row = Gtk.ListBoxRow()
            row.project = project
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            left.set_hexpand(True)
            title = self.label(project.name, "row-title")
            meta = "Git" if project.is_git else "Folder"
            if project.is_git:
                meta += f" | {project.branch} | changed {project.dirty} | untracked {project.untracked}"
            left.append(title)
            left.append(self.label(project.path, "muted"))
            left.append(self.label(meta, "muted"))
            use = Gtk.Button(label="Use")
            use.connect("clicked", self.on_use_project_button, project.path)
            open_btn = Gtk.Button(label="Open")
            open_btn.connect("clicked", self.on_open_path_button, project.path)
            content.append(left)
            content.append(use)
            content.append(open_btn)
            row.set_child(content)
            self.projects_list.append(row)

    def refresh_threads(self) -> None:
        if not hasattr(self, "threads_list"):
            return
        self.clear_listbox(self.threads_list)
        search = self.thread_search.get_text() if hasattr(self, "thread_search") else ""
        for thread in read_threads(search):
            row = Gtk.ListBoxRow()
            row.thread = thread
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = self.label(thread.title, "row-title")
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_hexpand(True)
            badge = self.label("archived" if thread.archived else short_id(thread.id), "muted")
            title_row.append(title)
            title_row.append(badge)
            content.append(title_row)
            content.append(self.label(thread.cwd, "muted"))
            content.append(self.label(
                f"{human_time(thread.updated)} | {thread.model or 'model?'} | {thread.reasoning or 'reasoning?'} | {thread.tokens:,} tokens",
                "muted",
            ))
            if thread.preview:
                preview = self.label(thread.preview, "muted")
                preview.set_ellipsize(Pango.EllipsizeMode.END)
                content.append(preview)
            row.set_child(content)
            self.threads_list.append(row)

    def load_config_text(self) -> None:
        if self.config_buffer is None:
            return
        text = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""
        self.config_buffer.set_text(text)

    def refresh_profile_label(self) -> None:
        if not hasattr(self, "profile_list_label"):
            return
        names = profile_names()
        self.profile_list_label.set_text(", ".join(names) if names else "No profile files installed yet.")
        if hasattr(self, "profile_combo"):
            current = self.dropdown_value(self.profile_combo) or "none"
            self.profile_combo.set_model(Gtk.StringList.new([label for _id, label in self.profile_options()]))
            self.profile_combo.codex_ids = [item_id for item_id, _label in self.profile_options()]
            self.set_dropdown(self.profile_combo, current if current in ["none", *names] else "none")

    def clear_listbox(self, listbox: Gtk.ListBox) -> None:
        child = listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            listbox.remove(child)
            child = next_child

    def set_text(self, buffer: Gtk.TextBuffer | None, text: str) -> None:
        if buffer is not None:
            buffer.set_text(text)

    def append_text(self, buffer: Gtk.TextBuffer | None, text: str) -> None:
        if buffer is None:
            return
        end = buffer.get_end_iter()
        buffer.insert(end, text)

    def on_browse_project(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose project folder")
        current = Path(self.selected_project())
        if current.exists():
            dialog.set_initial_folder(Gio.File.new_for_path(str(current)))
        dialog.select_folder(self.window, None, self.on_folder_selected)

    def on_folder_selected(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = folder.get_path()
        if path:
            self.project_entry.set_text(path)
            self.refresh_project_snapshot_async()
            self.refresh_projects()

    def on_prompt_template(self, _button: Gtk.Button, prompt: str, name: str) -> None:
        if self.prompt_buffer is not None:
            self.prompt_buffer.set_text(prompt)
        if name == "Review":
            self.set_dropdown(self.action_combo, "review")
        else:
            self.set_dropdown(self.action_combo, "interactive")
        if hasattr(self, "prompt_choice_list"):
            self.prompt_variants = enhance_prompt(prompt, self.project_context_text())
            self.render_prompt_variants()
        self.update_command_preview()

    def render_prompt_variants(self) -> None:
        if not hasattr(self, "prompt_choice_list"):
            return
        self.clear_listbox(self.prompt_choice_list)
        for variant in self.prompt_variants:
            row = Gtk.ListBoxRow()
            row.variant = variant
            row.add_css_class("prompt-option")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = self.label(variant.title, "prompt-option-title")
            summary = self.label(variant.summary, "prompt-option-summary", wrap=True)
            content.append(title)
            content.append(summary)
            row.set_child(content)
            self.prompt_choice_list.append(row)
        first = self.prompt_choice_list.get_row_at_index(0)
        if first is not None:
            self.prompt_choice_list.select_row(first)
            self.selected_prompt_variant = getattr(first, "variant", None)

    def on_enhance_prompt(self, _button: Gtk.Button) -> None:
        raw = self.selected_prompt()
        self.prompt_variants = enhance_prompt(raw, self.project_context_text())
        self.render_prompt_variants()
        self.set_status(f"{len(self.prompt_variants)} prompt choices ready")

    def on_ai_enhance_prompt(self, _button: Gtk.Button) -> None:
        if self.ai_prompt_busy:
            self.set_status("AI Enhance already running", "warn")
            return
        raw = self.selected_prompt()
        if not raw:
            self.set_status("Prompt required", "warn")
            return
        project_context = self.project_context_text()
        request = model_variant_request(raw, project_context)
        output_file = tempfile.NamedTemporaryFile(prefix="codex-prompt-variants-", suffix=".json", delete=False)
        output_file.close()
        args = [
            self.codex_bin,
            "-p", "maximum-power",
            "-C", self.selected_project(),
            "-s", "read-only",
            "-a", "never",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--output-last-message", output_file.name,
            request,
        ]
        self.ai_prompt_busy = True
        self.set_status("AI Enhance running")

        def worker() -> None:
            try:
                result = subprocess.run(
                    args,
                    cwd=self.selected_project(),
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                final = Path(output_file.name).read_text(encoding="utf-8", errors="replace") if Path(output_file.name).exists() else ""
                Path(output_file.name).unlink(missing_ok=True)
                if not final.strip():
                    final = result.stdout + "\n" + result.stderr
                GLib.idle_add(self.on_ai_enhance_done, result.returncode, final, raw, project_context)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self.on_ai_enhance_done, 1, str(exc), raw, project_context)
        threading.Thread(target=worker, daemon=True).start()

    def on_ai_enhance_done(self, code: int, text: str, raw: str, project_context: str) -> bool:
        self.ai_prompt_busy = False
        variants = parse_model_variants(text, raw, project_context)
        self.prompt_variants = variants
        self.render_prompt_variants()
        if code == 0 and any(variant.id.startswith("ai-") for variant in variants):
            self.set_status(f"AI generated {len(variants)} prompt choices")
        else:
            self.set_status("AI Enhance fell back to local choices", "warn")
        return False

    def on_prompt_choice_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_prompt_variant = getattr(row, "variant", None) if row is not None else None
        if self.selected_prompt_variant is not None:
            self.set_status(f"Selected {self.selected_prompt_variant.title}")

    def on_prompt_choice_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        variant = getattr(row, "variant", None)
        if variant is not None:
            self.apply_prompt_variant(variant)

    def on_use_prompt_choice(self, _button: Gtk.Button) -> None:
        if self.selected_prompt_variant is None:
            self.set_status("Choose a prompt option first", "warn")
            return
        self.apply_prompt_variant(self.selected_prompt_variant)

    def apply_prompt_variant(self, variant: PromptVariant) -> None:
        if self.prompt_buffer is not None:
            self.prompt_buffer.set_text(variant.prompt)
        if variant.profile not in ["none", *profile_names()]:
            self.on_install_profiles(Gtk.Button())
        self.set_dropdown(self.action_combo, variant.action)
        self.set_dropdown(self.profile_combo, variant.profile)
        self.set_dropdown(self.web_combo, variant.web)
        self.update_command_preview()
        self.set_status(f"Using {variant.title}")

    def on_fast_profile(self, _button: Gtk.Button, action: str, profile: str) -> None:
        self.on_install_profiles(_button)
        self.set_dropdown(self.profile_combo, profile)
        self.set_dropdown(self.action_combo, action)
        self.set_dropdown(self.model_combo, "config")
        self.set_dropdown(self.reasoning_combo, "config")
        self.set_dropdown(self.sandbox_combo, "config")
        self.set_dropdown(self.approval_combo, "config")
        self.set_dropdown(self.personality_combo, "config")
        self.set_dropdown(self.web_combo, "live" if profile == "maximum-power" else "config")
        if self.stack is not None:
            self.stack.set_visible_child_name("launch")
        self.update_command_preview()

    def on_run_embedded(self, _button: Gtk.Button) -> None:
        self.run_embedded_command(self.build_command())

    def on_run_action_button(self, _button: Gtk.Button, action: str) -> None:
        self.set_dropdown(self.action_combo, action)
        if action == "exec":
            self.on_run_headless(_button)
            return
        self.run_embedded_command(self.build_command(action))

    def on_run_external(self, _button: Gtk.Button) -> None:
        action = self.dropdown_value(self.action_combo) or "interactive"
        self.launch_external(self.build_command(action), f"Codex {action}")

    def on_copy_command(self, _button: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(shell_join(self.build_command()))
            self.set_status("Command copied")

    def on_run_headless(self, _button: Gtk.Button) -> None:
        if self.headless_proc is not None and self.headless_proc.poll() is None:
            self.set_status("Headless already running", "warn")
            return
        prompt = self.selected_prompt()
        if not prompt:
            self.set_status("Prompt required", "warn")
            return
        output_file = tempfile.NamedTemporaryFile(prefix="codex-final-", suffix=".txt", delete=False)
        output_file.close()
        args = [self.codex_bin]
        args.extend(self.common_args())
        args.extend(["exec", "--json", "--output-last-message", output_file.name])
        if self.skip_git_switch.get_active():
            args.append("--skip-git-repo-check")
        args.append(prompt)
        command_run = self.stamp_command_receipt(args, "exec", surface="headless", run_status="running")
        self.headless_run_id = command_run.id if command_run is not None else ""
        self.set_text(self.headless_buffer, f"$ {shell_join(args)}\n\n")
        self.set_status("Headless running")

        def worker() -> None:
            try:
                self.headless_proc = subprocess.Popen(
                    args,
                    cwd=self.selected_project(),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    start_new_session=True,
                )
                assert self.headless_proc.stdout is not None
                for line in self.headless_proc.stdout:
                    GLib.idle_add(self.on_headless_line, line)
                code = self.headless_proc.wait()
                final = Path(output_file.name).read_text(encoding="utf-8", errors="replace") if Path(output_file.name).exists() else ""
                GLib.idle_add(self.on_headless_done, code, final)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self.on_headless_done, 1, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def on_headless_line(self, line: str) -> bool:
        try:
            event = json.loads(line)
            compact = event.get("type", "event")
            if "message" in event:
                compact += f": {event['message']}"
            self.append_text(self.headless_buffer, compact + "\n")
        except json.JSONDecodeError:
            self.append_text(self.headless_buffer, line)
        return False

    def on_headless_done(self, code: int, final: str) -> bool:
        self.append_text(self.headless_buffer, f"\n[exit {code}]\n")
        if final:
            self.append_text(self.headless_buffer, "\nFinal message:\n" + final + "\n")
        self.headless_proc = None
        self.update_command_run_status(self.headless_run_id, "done" if code == 0 else "failed", exit_code=code)
        self.headless_run_id = ""
        self.set_status("Headless done" if code == 0 else "Headless failed", "ok" if code == 0 else "warn")
        self.refresh_threads()
        return False

    def on_stop_headless(self, _button: Gtk.Button) -> None:
        if self.headless_proc is not None and self.headless_proc.poll() is None:
            os.killpg(self.headless_proc.pid, signal.SIGTERM)
            self.set_status("Stopping headless", "warn")

    def on_project_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        project = getattr(row, "project", None)
        if project:
            self.project_entry.set_text(project.path)
            self.refresh_project_snapshot_async()
            if self.stack is not None:
                self.stack.set_visible_child_name("launch")

    def on_use_project_button(self, _button: Gtk.Button, path: str) -> None:
        self.project_entry.set_text(path)
        self.refresh_project_snapshot_async()
        self.update_command_preview()
        if self.stack is not None:
            self.stack.set_visible_child_name("launch")

    def on_open_path_button(self, _button: Gtk.Button, path: str) -> None:
        subprocess.Popen(["xdg-open", path], start_new_session=True)

    def add_active_project(self) -> None:
        path = ensure_dir(self.selected_project())
        if all(p.path != path for p in self.projects):
            self.projects.append(git_project_info(path))
        self.render_projects()

    def on_thread_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.selected_thread = getattr(row, "thread", None) if row else None

    def on_threads_row_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self.selected_thread = getattr(row, "thread", None)
        self.on_resume_selected_thread(row)

    def session_from_thread(self, thread: ThreadInfo, prompt: str = "") -> WorkspaceSession:
        session = new_session(
            project=thread.cwd or self.selected_project(),
            profile=self.dropdown_value(self.profile_combo) or "maximum-power",
            action="interactive",
            prompt=prompt or thread.preview or thread.title,
            thread_id=thread.id,
        )
        return replace_session(
            session,
            project=session.project,
            profile=session.profile,
            action=session.action,
            prompt=session.prompt,
            status="running",
            thread_id=thread.id,
        )

    def on_resume_selected_thread(self, _button: Gtk.Button) -> None:
        if not self.selected_thread:
            self.set_status("Select a thread", "warn")
            return
        session = self.session_from_thread(self.selected_thread)
        self.sessions = upsert_session(self.sessions, session)
        self.selected_workspace_session = session
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        args = [self.codex_bin]
        args.extend(self.common_args())
        args.extend(["resume", self.selected_thread.id])
        self.project_entry.set_text(self.selected_thread.cwd)
        self.refresh_project_snapshot_async()
        self.run_embedded_command(args)

    def on_fork_selected_thread(self, _button: Gtk.Button) -> None:
        if not self.selected_thread:
            self.set_status("Select a thread", "warn")
            return
        prompt = self.selected_prompt()
        session = self.session_from_thread(self.selected_thread, prompt)
        self.sessions = upsert_session(self.sessions, session)
        self.selected_workspace_session = session
        self.persist_workspace_sessions()
        self.render_workspace_sessions()
        args = [self.codex_bin]
        args.extend(self.common_args())
        args.extend(["fork", self.selected_thread.id])
        if prompt:
            args.append(prompt)
        self.project_entry.set_text(self.selected_thread.cwd)
        self.refresh_project_snapshot_async()
        self.run_embedded_command(args)

    def on_archive_selected_thread(self, _button: Gtk.Button) -> None:
        if not self.selected_thread:
            self.set_status("Select a thread", "warn")
            return
        self.run_async_text([self.codex_bin, "archive", self.selected_thread.id], None, self.on_archive_done)

    def on_archive_done(self, text: str, code: int) -> bool:
        self.set_status("Archived" if code == 0 else "Archive failed", "ok" if code == 0 else "warn")
        self.refresh_threads()
        return False

    def git_command(self, args: list[str], title: str) -> None:
        root = git_root(self.selected_project())
        if not root:
            self.set_text(self.git_buffer, "Active project is not inside a Git repository.")
            self.set_status("Not a git repo", "warn")
            return
        self.run_async_text(["git", "-C", root, *args], root, lambda text, code: self.on_git_output(title, text, code))

    def on_git_output(self, title: str, text: str, code: int) -> bool:
        self.set_text(self.git_buffer, f"$ git {title}\n\n{text}")
        self.set_status("Git command done" if code == 0 else "Git command failed", "ok" if code == 0 else "warn")
        return False

    def on_git_status(self, _button: Gtk.Button) -> None:
        self.git_command(["status", "--short", "--branch"], "status --short --branch")

    def on_git_diff_stat(self, _button: Gtk.Button) -> None:
        self.git_command(["diff", "--stat"], "diff --stat")

    def on_git_log(self, _button: Gtk.Button) -> None:
        self.git_command(["log", "--oneline", "--decorate", "--graph", "-12"], "log --oneline --decorate --graph -12")

    def on_git_worktrees(self, _button: Gtk.Button) -> None:
        self.git_command(["worktree", "list"], "worktree list")

    def on_git_prune(self, _button: Gtk.Button) -> None:
        self.git_command(["worktree", "prune"], "worktree prune")

    def on_git_worktree_create(self, _button: Gtk.Button) -> None:
        root = git_root(self.selected_project())
        if not root:
            self.set_status("Not a git repo", "warn")
            return
        name = self.worktree_name_entry.get_text().strip()
        branch = self.worktree_branch_entry.get_text().strip()
        if not name:
            self.set_status("Worktree name required", "warn")
            return
        target = str(Path(root).parent / f"{Path(root).name}-{name}")
        args = ["git", "-C", root, "worktree", "add"]
        if branch:
            args.extend(["-b", branch])
        args.append(target)
        self.run_async_text(args, root, lambda text, code: self.on_git_output("worktree add", text, code))

    def on_open_project_terminal(self, _button: Gtk.Button) -> None:
        self.launch_external(["bash", "-i"], "Project terminal")

    def on_reload_config(self, _button: Gtk.Button) -> None:
        self.load_config_text()
        self.set_status("Config reloaded")

    def on_save_config(self, _button: Gtk.Button) -> None:
        CODEX_HOME.mkdir(parents=True, exist_ok=True)
        CODEX_CONFIG.write_text(self.text_from_buffer(self.config_buffer), encoding="utf-8")
        self.set_status("Config saved")
        self.refresh_health_async()

    def on_install_profiles(self, _button: Gtk.Button) -> None:
        CODEX_HOME.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        skipped: list[str] = []
        for name, text in PROFILE_TEMPLATES.items():
            path = CODEX_HOME / f"{name}.config.toml"
            if path.exists():
                skipped.append(name)
                continue
            path.write_text(text, encoding="utf-8")
            installed.append(name)
        self.refresh_profile_label()
        msg = []
        if installed:
            msg.append("installed " + ", ".join(installed))
        if skipped:
            msg.append("kept existing " + ", ".join(skipped))
        self.set_status("; ".join(msg) if msg else "Profiles ready")

    def on_refresh_profiles(self, _button: Gtk.Button) -> None:
        self.refresh_profile_label()
        self.set_status("Profiles refreshed")

    def on_run_doctor(self, _button: Gtk.Button) -> None:
        self.run_async_text([self.codex_bin, "doctor", "--json"], None, self.on_doctor_text)

    def on_doctor_text(self, text: str, code: int) -> bool:
        try:
            data = json.loads(text)
            text = json.dumps(data, indent=2)
        except json.JSONDecodeError:
            pass
        self.set_text(self.health_buffer, text)
        self.set_status("Doctor OK" if code == 0 else "Doctor failed", "ok" if code == 0 else "warn")
        return False

    def on_update_codex(self, _button: Gtk.Button) -> None:
        self.run_embedded_command([self.codex_bin, "update"])

    def on_login_codex(self, _button: Gtk.Button) -> None:
        self.run_embedded_command([self.codex_bin, "login"])

    def on_app_server_start(self, _button: Gtk.Button) -> None:
        self.run_embedded_command([self.codex_bin, "app-server", "daemon", "start"])

    def on_app_server_stop(self, _button: Gtk.Button) -> None:
        self.run_embedded_command([self.codex_bin, "app-server", "daemon", "stop"])

    def on_app_server_version(self, _button: Gtk.Button) -> None:
        self.run_async_text([self.codex_bin, "app-server", "daemon", "version"], None, self.on_doctor_text)

    def on_setting_changed(self, *_args: object) -> None:
        self.update_command_preview()

    def on_close(self, *_args: object) -> bool:
        self.save_current_state()
        return False


def main() -> int:
    return CodexControl().run()


if __name__ == "__main__":
    raise SystemExit(main())
