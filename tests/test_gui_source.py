import ast
import unittest
from pathlib import Path


def _method_named(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")


def _thread_start_targets_worker(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    call = node.value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr != "start":
        return False
    thread_call = call.func.value
    if not isinstance(thread_call, ast.Call):
        return False
    thread_func = thread_call.func
    if not isinstance(thread_func, ast.Attribute) or thread_func.attr != "Thread":
        return False
    return any(
        keyword.arg == "target"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "worker"
        for keyword in thread_call.keywords
    )


class GuiSourceTests(unittest.TestCase):
    def test_tailnet_discovery_starts_worker_from_handler_scope(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        method = _method_named(ast.parse(source), "on_discover_tailnet")
        worker = next(
            node for node in method.body
            if isinstance(node, ast.FunctionDef) and node.name == "worker"
        )

        self.assertTrue(any(_thread_start_targets_worker(node) for node in method.body))
        self.assertFalse(any(_thread_start_targets_worker(node) for node in worker.body))

    def test_mesh_device_rows_surface_probe_freshness(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        _method_named(tree, "_mesh_freshness_label")
        render_device_list = _method_named(tree, "render_device_list")
        text = ast.unparse(render_device_list)
        self.assertIn("_mesh_freshness_label", ast.unparse(render_device_list))
        self.assertIn("self.flow_append(chip_flow, freshness)", text)

    def test_mesh_operator_chips_use_team_doctor_report(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        current_doctor = _method_named(tree, "current_team_doctor_report")
        refresh_chips = _method_named(tree, "refresh_mesh_operator_chips")
        self.assertIn("build_team_doctor_report", ast.unparse(current_doctor))
        self.assertIn("mesh_doctor_lane_text", ast.unparse(refresh_chips))
        self.assertIn("mesh_doctor_bus_text", ast.unparse(refresh_chips))
        self.assertIn("blocker", ast.unparse(refresh_chips))

    def test_mesh_summary_review_action_is_wired(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_mesh = _method_named(tree, "build_mesh_page")
        current_operator = _method_named(tree, "current_team_operator_summary")
        review_summary = _method_named(tree, "on_review_mesh_team_summary")
        execute_action = _method_named(tree, "execute_action")

        self.assertIn("Review", ast.unparse(build_mesh))
        self.assertIn("on_review_mesh_team_summary", ast.unparse(build_mesh))
        self.assertIn("mark_team_summary_reviewed", ast.unparse(review_summary))
        self.assertIn("is_team_summary_reviewed", ast.unparse(current_operator))
        self.assertIn("mesh.review_summary", ast.unparse(execute_action))

    def test_mesh_launch_console_surfaces_prelaunch_review(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_mesh = _method_named(tree, "build_mesh_page")
        render_console = _method_named(tree, "render_mesh_launch_console")
        refresh_stage = _method_named(tree, "refresh_mesh_launch_stage_strip")
        render_team = _method_named(tree, "render_mesh_team")

        build_text = ast.unparse(build_mesh)
        render_text = ast.unparse(render_console)
        self.assertIn("Launch Console", build_text)
        self.assertIn("mesh_launch_console_list", build_text)
        self.assertIn("mesh_launch_stage_chips", build_text)
        self.assertIn("on_sync_mesh_handoff_bus", build_text)
        self.assertIn("build_mesh_team_assignments", render_text)
        self.assertIn("refresh_mesh_launch_stage_strip", render_text)
        self.assertIn("chip-strong", ast.unparse(refresh_stage))
        self.assertIn("chip-danger", ast.unparse(refresh_stage))
        self.assertIn("role_profile", render_text)
        self.assertIn("should_sync_project_to_device", render_text)
        self.assertIn("Expected: out/", render_text)
        self.assertIn("render_mesh_launch_console", ast.unparse(render_team))
        self.assertIn("mesh_launch_pulse_label", build_text)
        self.assertIn("mesh_launch_pulse_ready_chip", build_text)
        self.assertIn("_mesh_launch_readiness_pulse", ast.unparse(render_console))

    def test_mesh_launch_console_row_actions_include_recheck_sync_and_session(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        render_console = _method_named(tree, "render_mesh_launch_console")
        build_mesh = _method_named(tree, "build_mesh_page")
        sync_project_handler = _method_named(tree, "on_sync_launch_console_project")
        open_session_handler = _method_named(tree, "on_open_launch_console_session")

        render_text = ast.unparse(render_console)
        self.assertIn("Open Session", render_text)
        self.assertIn("on_open_launch_console_session", render_text)
        self.assertIn("on_recheck_lane", render_text)
        self.assertIn("Copy Launch", render_text)
        self.assertIn("Fix Now", render_text)
        self.assertIn("should_sync_project_to_device", render_text)
        self.assertIn("utilities-terminal-symbolic", render_text)
        self.assertIn("launch_console_command_copy", render_text)
        self.assertIn("on_mesh_lane_fix_now", render_text)
        self.assertIn("mesh_launch_blocker_timeline_text", render_text)
        self.assertIn("on_recheck_launch_blocked_lanes", ast.unparse(build_mesh))
        self.assertIn("on_launch_console_blocked_only_toggled", ast.unparse(build_mesh))

        self.assertIn("def on_open_launch_console_session", ast.unparse(open_session_handler))
        self.assertIn("is_local_mesh_device", ast.unparse(open_session_handler))
        self.assertIn("ssh_launch_command", ast.unparse(open_session_handler))

        self.assertIn("def on_sync_launch_console_project", ast.unparse(sync_project_handler))

    def test_mesh_stream_and_memory_controls_use_command_buttons(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_mesh = _method_named(tree, "build_mesh_page")
        text = ast.unparse(build_mesh)

        self.assertIn("self.command_button('Post'", text)
        self.assertIn("self.command_button('Refresh'", text)
        self.assertIn("self.command_button('Copy'", text)
        self.assertIn("self.command_button('Import'", text)
        self.assertIn("mail-send-symbolic", text)
        self.assertIn("document-import-symbolic", text)

    def test_chips_and_meta_labels_are_ellipsized_with_tooltips(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        chip_label = _method_named(tree, "chip_label")
        muted_meta_label = _method_named(tree, "muted_meta_label")
        set_chip = _method_named(tree, "set_chip")
        make_button = _method_named(tree, "make_button")

        self.assertIn("set_ellipsize", ast.unparse(chip_label))
        self.assertIn("set_max_width_chars", ast.unparse(chip_label))
        self.assertIn("set_tooltip_text", ast.unparse(chip_label))
        self.assertIn("Pango.EllipsizeMode.MIDDLE", ast.unparse(muted_meta_label))
        self.assertIn("set_tooltip_text", ast.unparse(set_chip))
        self.assertIn("button.set_tooltip_text(label)", ast.unparse(make_button))

    def test_launch_workbench_prioritizes_guided_run_flow(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_launch = _method_named(tree, "build_launch_page")
        build_operator = _method_named(tree, "build_operator_console")
        build_mission = _method_named(tree, "build_mission_panel")
        refresh_focus = _method_named(tree, "refresh_workbench_focus")

        self.assertIn("build_power_banner", ast.unparse(build_launch))
        self.assertIn("operator_next_step_banner", ast.unparse(build_operator))
        self.assertIn("command_grid", ast.unparse(build_operator))
        self.assertIn("mission_project_chip", ast.unparse(build_mission))
        self.assertIn("mission_validation_label", ast.unparse(build_mission))
        self.assertIn("composer_summary_label", source)
        self.assertIn("prompt_summary_text", ast.unparse(refresh_focus))

    def test_dense_chip_rows_use_wrapping_flowbox(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        flow_row = _method_named(tree, "flow_row")
        build_mesh = _method_named(tree, "build_mesh_page")
        build_palette = _method_named(tree, "build_palette_page")
        build_quality = _method_named(tree, "build_quality_page")

        self.assertIn("Gtk.FlowBox", ast.unparse(flow_row))
        self.assertIn("set_selection_mode(Gtk.SelectionMode.NONE)", ast.unparse(flow_row))
        self.assertIn("set_max_children_per_line", ast.unparse(flow_row))
        self.assertIn("chip_flow", ast.unparse(build_mesh))
        self.assertIn("preview_chip_flow", ast.unparse(build_palette))
        self.assertIn("history_chip_flow", ast.unparse(build_palette))
        self.assertIn("quality_chip_flow", ast.unparse(build_quality))

    def test_palette_rows_surface_readiness_metadata(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        render_action_list = _method_named(tree, "render_action_list")
        text = ast.unparse(render_action_list)

        self.assertIn("build_palette_preview", text)
        self.assertIn("preview.status", text)
        self.assertIn("preview.surface", text)
        self.assertIn("preview.requirement_text", text)
        self.assertIn("chip_flow", text)

    def test_palette_page_surfaces_readiness_summary_and_clamped_preview(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_palette = _method_named(tree, "build_palette_page")
        render_palette = _method_named(tree, "render_action_palette")

        self.assertIn("palette_readiness_label", ast.unparse(build_palette))
        self.assertIn("set_lines(4)", ast.unparse(build_palette))
        self.assertIn("Pango.EllipsizeMode.MIDDLE", ast.unparse(build_palette))
        self.assertIn("palette_readiness_label", ast.unparse(render_palette))
        self.assertIn("need setup", ast.unparse(render_palette))

    def test_palette_execute_controls_follow_preview_readiness(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_palette = _method_named(tree, "build_palette_page")
        build_compact = _method_named(tree, "build_palette_panel")
        refresh_execute = _method_named(tree, "refresh_palette_execute_buttons")
        render_preview = _method_named(tree, "render_palette_preview")

        self.assertIn("palette_execute_buttons", ast.unparse(build_palette))
        self.assertIn("palette_execute_buttons", ast.unparse(build_compact))
        self.assertIn("button.set_sensitive(enabled)", ast.unparse(refresh_execute))
        self.assertIn("preview.requirement_text()", ast.unparse(refresh_execute))
        self.assertIn("refresh_palette_execute_buttons(None)", ast.unparse(render_preview))
        self.assertIn("refresh_palette_execute_buttons(preview)", ast.unparse(render_preview))
        self.assertIn("enabled=preview.ready", ast.unparse(render_preview))

    def test_palette_preview_surfaces_operator_decision_and_command_label(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_palette = _method_named(tree, "build_palette_page")
        render_preview = _method_named(tree, "render_palette_preview")

        self.assertIn("palette_preview_decision_label", ast.unparse(build_palette))
        self.assertIn("Decision: select an action", ast.unparse(build_palette))
        self.assertIn("Command Preview", ast.unparse(build_palette))
        self.assertIn("Decision: ready to execute", ast.unparse(render_preview))
        self.assertIn("Decision: blocked until", ast.unparse(render_preview))

    def test_quality_rows_surface_exit_and_duration_metadata(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        render_quality = _method_named(tree, "render_quality_check_rows")
        text = ast.unparse(render_quality)

        self.assertIn("QualityCheckResult", text)
        self.assertIn("exit_text", text)
        self.assertIn("duration_ms", text)
        self.assertIn("set_tooltip_text(item.command_text())", text)
        self.assertIn("chip_flow", text)

    def test_quality_page_surfaces_pass_fail_counts(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_quality = _method_named(tree, "build_quality_page")
        render_quality = _method_named(tree, "render_quality_gate")

        self.assertIn("quality_page_pass_label", ast.unparse(build_quality))
        self.assertIn("quality_page_fail_label", ast.unparse(build_quality))
        self.assertIn("quality_page_artifact_label", ast.unparse(build_quality))
        self.assertIn("pass_count", ast.unparse(render_quality))
        self.assertIn("fail_count", ast.unparse(render_quality))
        self.assertIn("Artifact:", ast.unparse(render_quality))
        self.assertIn("quality_page_artifact_label", ast.unparse(render_quality))

    def test_mesh_launch_console_surfaces_decision_copy(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_mesh = _method_named(tree, "build_mesh_page")
        render_console = _method_named(tree, "render_mesh_launch_console")

        self.assertIn("mesh_launch_console_decision_label", ast.unparse(build_mesh))
        self.assertIn("mesh_launch_blocker_timeline_label", ast.unparse(build_mesh))
        self.assertIn("Decision:", ast.unparse(render_console))
        self.assertIn("launch blocked", ast.unparse(render_console))
        self.assertIn("_mesh_launch_blocking_reason_map", ast.unparse(render_console))
        self.assertIn("on_recheck_lane", ast.unparse(render_console))
        self.assertIn("on_mesh_lane_fix_now", ast.unparse(render_console))
        self.assertIn("set_tooltip_text", ast.unparse(render_console))
        self.assertIn("mesh_launch_console_blocked_only_toggle", ast.unparse(build_mesh))
        self.assertIn("Blocked only", ast.unparse(build_mesh))

    def test_mesh_launch_blocker_timeline_method_exists(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        render_console = _method_named(tree, "render_mesh_launch_console")
        timeline_lines = _method_named(tree, "_mesh_launch_blocker_timeline_lines")
        timeline = _method_named(tree, "mesh_launch_blocker_timeline_text")

        self.assertIn("mesh_launch_blocker_timeline_label", ast.unparse(render_console))
        self.assertIn("mesh_launch_blocker_timeline_text", ast.unparse(render_console))
        self.assertIn("_mesh_launch_blocker_timeline_lines", ast.unparse(timeline))
        self.assertIn("mesh_readiness_report", ast.unparse(timeline))
        self.assertIn("row.next_actions", ast.unparse(timeline_lines))

    def test_mesh_launch_blocker_timeline_display_helpers(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        render_console = _method_named(tree, "render_mesh_launch_console")
        build_mesh = _method_named(tree, "build_mesh_page")
        display = _method_named(tree, "_mesh_launch_console_display_assignments")
        timeline = _method_named(tree, "mesh_launch_blocker_timeline_text")
        blocked_lines = _method_named(tree, "_mesh_launch_blocker_timeline_lines")
        sort_text = ast.unparse(display)
        self.assertIn("mesh_launch_console_blocked_only", ast.unparse(render_console))
        self.assertIn("only_blocked", sort_text)
        self.assertIn("sorted(assignments", ast.unparse(display))
        self.assertIn("mesh_launch_console_blocked_only_toggle", ast.unparse(build_mesh))
        self.assertIn("on_recheck_launch_blocked_lanes", ast.unparse(build_mesh))
        self.assertIn("_mesh_launch_blocker_timeline_lines", ast.unparse(timeline))
        self.assertIn("row.next_actions", ast.unparse(blocked_lines))

    def test_mesh_launch_readiness_pulse_helper(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_mesh = _method_named(tree, "build_mesh_page")
        render_console = _method_named(tree, "render_mesh_launch_console")
        pulse = _method_named(tree, "_mesh_launch_readiness_pulse")

        self.assertIn("mesh_launch_pulse_ready_chip", ast.unparse(build_mesh))
        self.assertIn("mesh_launch_pulse_offline_chip", ast.unparse(build_mesh))
        self.assertIn("mesh_launch_pulse_label", ast.unparse(render_console))
        self.assertIn("_mesh_launch_readiness_pulse", ast.unparse(render_console))
        self.assertIn("human_time", ast.unparse(pulse))

    def test_mesh_launch_pulse_focus_controls_are_wired(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        build_mesh = _method_named(tree, "build_mesh_page")
        on_ready = _method_named(tree, "on_mesh_launch_pulse_focus_ready")
        on_blocked = _method_named(tree, "on_mesh_launch_pulse_focus_blocked")
        on_review = _method_named(tree, "on_mesh_launch_pulse_focus_review")
        on_offline = _method_named(tree, "on_mesh_launch_pulse_focus_offline")
        set_focus = _method_named(tree, "_set_mesh_launch_console_focus_filter")
        render_assignments = _method_named(tree, "_mesh_launch_console_display_assignments")
        render_console = _method_named(tree, "render_mesh_launch_console")
        timeline = _method_named(tree, "mesh_launch_blocker_timeline_text")
        timeline_lines = ast.unparse(timeline)
        cycle = _method_named(tree, "on_cycle_mesh_launch_focus")
        focus_name = _method_named(tree, "_mesh_launch_console_focus_name")

        build = ast.unparse(build_mesh)
        console_text = ast.unparse(render_console)
        self.assertIn("mesh_launch_console_focus_filter", ast.unparse(build_mesh))
        self.assertIn("mesh_launch_console_focus_label", build)
        self.assertIn("_mesh_launch_console_focus_name(self.mesh_launch_console_focus_filter)", build)
        self.assertIn("on_mesh_launch_pulse_focus_ready", build)
        self.assertIn("on_mesh_launch_pulse_focus_blocked", build)
        self.assertIn("on_mesh_launch_pulse_focus_review", build)
        self.assertIn("on_mesh_launch_pulse_focus_offline", build)
        self.assertIn("on_cycle_mesh_launch_focus", build)
        self.assertIn("Cycle Focus", build)
        self.assertIn("self.mesh_launch_console_focus_filter == 'ready'", console_text)
        self.assertIn("ready_css =", console_text)
        self.assertIn("blocked_count == 0", console_text)
        self.assertIn("focus_filter", ast.unparse(render_assignments))
        self.assertIn("self._launch_console_focus_filter(", ast.unparse(render_assignments))
        self.assertIn("focus_filter=", timeline_lines)
        self.assertIn("_set_mesh_launch_console_focus_filter", ast.unparse(on_ready))
        self.assertIn("_set_mesh_launch_console_focus_filter('ready')", ast.unparse(on_ready))
        self.assertIn("_set_mesh_launch_console_focus_filter", ast.unparse(on_blocked))
        self.assertIn("_set_mesh_launch_console_focus_filter", ast.unparse(on_review))
        self.assertIn("_set_mesh_launch_console_focus_filter", ast.unparse(on_offline))
        self.assertIn("_mesh_launch_console_focus_name", ast.unparse(focus_name))
        self.assertIn("_set_mesh_launch_console_focus_filter", ast.unparse(cycle))
        self.assertIn("'ready'", ast.unparse(cycle))
        self.assertIn("Cycle through launch focus filters: all, ready, blocked, review, offline.", build)
        blocked_only_toggle = _method_named(tree, "on_launch_console_blocked_only_toggled")
        self.assertIn("mesh_launch_console_blocked_only_toggle", ast.unparse(blocked_only_toggle))

    def test_workstation_pages_have_stateful_next_step_banners(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        next_step = _method_named(tree, "next_step_banner")
        update_next_step = _method_named(tree, "update_next_step_banner")
        build_palette = _method_named(tree, "build_palette_page")
        build_mesh = _method_named(tree, "build_mesh_page")
        build_quality = _method_named(tree, "build_quality_page")
        render_palette = _method_named(tree, "render_palette_preview")
        refresh_mesh = _method_named(tree, "refresh_mesh_operator_chips")
        render_quality = _method_named(tree, "render_quality_gate")

        self.assertIn("next-step-banner", ast.unparse(next_step))
        self.assertIn("set_button_text", ast.unparse(update_next_step))
        self.assertIn("set_sensitive(enabled)", ast.unparse(update_next_step))
        self.assertIn("palette_next_step_banner", ast.unparse(build_palette))
        self.assertIn("mesh_next_step_banner", ast.unparse(build_mesh))
        self.assertIn("quality_next_step_banner", ast.unparse(build_quality))
        self.assertIn("update_next_step_banner", ast.unparse(render_palette))
        self.assertIn("enabled=False", ast.unparse(render_palette))
        self.assertIn("update_next_step_banner", ast.unparse(refresh_mesh))
        self.assertIn("update_next_step_banner", ast.unparse(render_quality))
        self.assertIn("next_enabled = False", ast.unparse(render_quality))

if __name__ == "__main__":
    unittest.main()
