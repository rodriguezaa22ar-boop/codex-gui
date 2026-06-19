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
        self.assertIn("_mesh_freshness_label", ast.unparse(render_device_list))
        self.assertIn("top.append(freshness)", ast.unparse(render_device_list))

    def test_mesh_operator_chips_use_team_doctor_report(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        current_doctor = _method_named(tree, "current_team_doctor_report")
        refresh_chips = _method_named(tree, "refresh_mesh_operator_chips")
        self.assertIn("build_team_doctor_report", ast.unparse(current_doctor))
        self.assertIn("mesh_doctor_lane_text", ast.unparse(refresh_chips))
        self.assertIn("mesh_doctor_bus_text", ast.unparse(refresh_chips))
        self.assertIn("blocker", ast.unparse(refresh_chips))

    def test_chips_and_meta_labels_are_ellipsized_with_tooltips(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        chip_label = _method_named(tree, "chip_label")
        muted_meta_label = _method_named(tree, "muted_meta_label")
        set_chip = _method_named(tree, "set_chip")

        self.assertIn("set_ellipsize", ast.unparse(chip_label))
        self.assertIn("set_max_width_chars", ast.unparse(chip_label))
        self.assertIn("set_tooltip_text", ast.unparse(chip_label))
        self.assertIn("Pango.EllipsizeMode.MIDDLE", ast.unparse(muted_meta_label))
        self.assertIn("set_tooltip_text", ast.unparse(set_chip))

    def test_palette_rows_surface_readiness_metadata(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        render_action_list = _method_named(tree, "render_action_list")
        text = ast.unparse(render_action_list)

        self.assertIn("build_palette_preview", text)
        self.assertIn("preview.status", text)
        self.assertIn("preview.surface", text)
        self.assertIn("preview.requirement_text", text)

    def test_quality_rows_surface_exit_and_duration_metadata(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        render_quality = _method_named(tree, "render_quality_check_rows")
        text = ast.unparse(render_quality)

        self.assertIn("QualityCheckResult", text)
        self.assertIn("exit_text", text)
        self.assertIn("duration_ms", text)
        self.assertIn("set_tooltip_text(item.command_text())", text)


if __name__ == "__main__":
    unittest.main()
