import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_devices import DeviceRecord, save_devices
import codex_team_ops as team_ops


class TeamOpsTests(unittest.TestCase):
    def _with_workspace(self):
        workspace = Path(tempfile.mkdtemp()) / "codex-team-ops-workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        config_dir = workspace / ".config" / "codex-gui"
        config_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            workspace=workspace,
            config_dir=config_dir,
            devices=config_dir / "devices.json",
            team_dir=config_dir / "team",
            last_run=config_dir / "team-last-run.json",
        )

    def test_prepare_json_writes_team_manifest(self) -> None:
        ctx = self._with_workspace()
        original_config = team_ops.CONFIG_DIR
        original_devices = team_ops.DEVICES_FILE
        original_team = team_ops.TEAM_DIR
        original_last = team_ops.LAST_TEAM_RUN_FILE

        team_ops.CONFIG_DIR = ctx.config_dir.parent
        team_ops.DEVICES_FILE = ctx.devices
        team_ops.TEAM_DIR = ctx.team_dir
        team_ops.LAST_TEAM_RUN_FILE = ctx.last_run

        try:
            local_devices = (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                    project_root="~/Projects/codex-gui",
                ),
                DeviceRecord(
                    id="atlas-ubuntu-1",
                    name="atlas-ubuntu",
                    host="localhost",
                    user="ao",
                    status="ready",
                    project_root="~/Projects/codex-gui",
                ),
            )
            save_devices(ctx.devices, local_devices)

            prepared = (
                {
                    "device_id": "atlas-builder-1",
                    "device_name": "atlas-builder",
                    "lane_slug": "backend-builder-atlas-builder",
                    "lane_title": "Core Systems Engineer",
                    "focus": "Implementation",
                    "target": "ao@atlas-builder:22",
                    "project_root": "~/Projects/codex-gui",
                    "role_id": "backend-builder",
                    "role_title": "Core Systems Engineer",
                    "role_profile": "maximum-power",
                    "role_focus": "Focus",
                    "role_boundary": "Boundary",
                },
                {
                    "device_id": "atlas-ubuntu-1",
                    "device_name": "atlas-ubuntu",
                    "lane_slug": "coordinator-atlas-ubuntu",
                    "lane_title": "Commander / Integrator",
                    "focus": "Coordination",
                    "target": "ao@localhost:22",
                    "project_root": "~/Projects/codex-gui",
                    "role_id": "coordinator",
                    "role_title": "Commander / Integrator",
                    "role_profile": "maximum-power",
                    "role_focus": "Focus",
                    "role_boundary": "Boundary",
                },
            )

            with (
                patch.object(team_ops, "check_devices", return_value=(local_devices, {})),
                patch.object(team_ops, "build_team_assignments", return_value=list(prepared)),
            ):
                args = team_ops.parse_args([
                    "--json",
                    "prepare",
                    "--project-root",
                    str(ctx.workspace),
                    "--check",
                ])

                with tempfile.TemporaryFile(mode="w+") as output:
                    with patch("sys.stdout", new=output):
                        status = team_ops.cmd_prepare(args)
                        output.seek(0)
                        payload = json.loads(output.read())

            self.assertEqual(status, 0)
            self.assertEqual(len(payload["assignments"]), 2)
            self.assertEqual(payload["lanes"], 2)

            run_dir = Path(payload["team_dir"])
            manifest_path = run_dir / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["project"], str(ctx.workspace))
            self.assertEqual(len(manifest["assignments"]), 2)
            self.assertEqual(manifest["run_id"], run_dir.name)
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_status_json_returns_team_summary(self) -> None:
        ctx = self._with_workspace()
        original_config = team_ops.CONFIG_DIR
        original_devices = team_ops.DEVICES_FILE
        original_team = team_ops.TEAM_DIR
        original_last = team_ops.LAST_TEAM_RUN_FILE

        team_ops.CONFIG_DIR = ctx.config_dir.parent
        team_ops.DEVICES_FILE = ctx.devices
        team_ops.TEAM_DIR = ctx.team_dir
        team_ops.LAST_TEAM_RUN_FILE = ctx.last_run

        try:
            run_dir = ctx.team_dir / "team-status"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "lanes").mkdir()
            (run_dir / "out").mkdir()
            (run_dir / "collected").mkdir()
            manifest = {
                "run_id": "team-status",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "lane_slug": "ui-polish-atlas-main",
                        "lane_title": "Product / GTK UX Engineer",
                        "device_name": "atlas-main",
                        "focus": "Improve UI",
                    }
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            args = team_ops.parse_args(["--json", "status", "--run-id", "team-status"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_status(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertEqual(payload["run_id"], "team-status")
            self.assertEqual(payload["lane_count"], 1)
            self.assertEqual(len(payload["assignments"]), 1)
            self.assertIn("project", payload)
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_cmd_roles_reports_assignments(self) -> None:
        ctx = self._with_workspace()
        original_config = team_ops.CONFIG_DIR
        original_devices = team_ops.DEVICES_FILE
        original_team = team_ops.TEAM_DIR
        original_last = team_ops.LAST_TEAM_RUN_FILE

        team_ops.CONFIG_DIR = ctx.config_dir.parent
        team_ops.DEVICES_FILE = ctx.devices
        team_ops.TEAM_DIR = ctx.team_dir
        team_ops.LAST_TEAM_RUN_FILE = ctx.last_run

        try:
            with (
                patch.object(team_ops, "load_devices", return_value=(
                    DeviceRecord(id="atlas-main", name="atlas-main", host="atlas-main", user="ao"),
                    DeviceRecord(id="atlas-builder", name="atlas-builder", host="atlas-builder", user="ao"),
                )),
                patch.object(team_ops, "team_readiness", return_value=SimpleNamespace(by_device=lambda _: SimpleNamespace(status="ready"))),
            ):
                assignments = team_ops.build_team_assignments(team_ops.load_devices())
                with patch.object(team_ops, "build_team_assignments", return_value=assignments):
                    with tempfile.TemporaryFile(mode="w+") as output:
                        with patch("sys.stdout", new=output):
                            args = team_ops.parse_args(["--json", "roles"])
                            self.assertEqual(team_ops.cmd_roles(args), 0)
                            output.seek(0)
                            payload = json.loads(output.read())

            self.assertEqual(len(payload), 2)
            self.assertEqual(payload[0]["role_title"], "Product / GTK UX Engineer")
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_resolve_team_dir_falls_back_to_last_run_marker(self) -> None:
        ctx = self._with_workspace()
        original_config = team_ops.CONFIG_DIR
        original_devices = team_ops.DEVICES_FILE
        original_team = team_ops.TEAM_DIR
        original_last = team_ops.LAST_TEAM_RUN_FILE

        team_ops.CONFIG_DIR = ctx.config_dir.parent
        team_ops.DEVICES_FILE = ctx.devices
        team_ops.TEAM_DIR = ctx.team_dir
        team_ops.LAST_TEAM_RUN_FILE = ctx.last_run

        try:
            marker_target = ctx.team_dir / "legacy"
            marker_target.mkdir(parents=True, exist_ok=True)
            marker_payload = {"run_id": "legacy", "team_dir": str(marker_target)}
            ctx.last_run.write_text(json.dumps(marker_payload), encoding="utf-8")

            resolved = team_ops._resolve_team_dir(team_ops.TEAM_DIR, None)
            self.assertEqual(resolved, marker_target)
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last


if __name__ == "__main__":
    unittest.main()
