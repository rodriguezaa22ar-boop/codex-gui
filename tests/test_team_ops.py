import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_devices import DeviceProbe, DeviceRecord, save_devices
from codex_team import load_bus_report
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
            self.assertEqual(payload["operator"]["next_action"], "Launch Team")
            self.assertIn("prepared", payload["operator"]["lane_text"])
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_summary_json_writes_reviewable_summary(self) -> None:
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
            run_dir = ctx.team_dir / "team-summary"
            collected = run_dir / "collected" / "atlas-builder"
            collected.mkdir(parents=True, exist_ok=True)
            manifest = {
                "run_id": "team-summary",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "lane_title": "Core Systems Engineer",
                        "device_name": "atlas-builder",
                        "focus": "Backend",
                    }
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (collected / "backend-builder-atlas-builder.final.txt").write_text("Final handoff", encoding="utf-8")

            args = team_ops.parse_args(["--json", "summary", "--run-id", "team-summary"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_summary(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            summary_path = Path(payload["summary_path"])
            self.assertTrue(summary_path.exists())
            self.assertEqual(payload["run_id"], "team-summary")
            self.assertEqual(payload["lane_count"], 1)
            self.assertEqual(payload["collected_count"], 1)
            self.assertIn("Final handoff", summary_path.read_text(encoding="utf-8"))

            args = team_ops.parse_args(["summary", "--run-id", "team-summary", "--print"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_summary(args), 0)
                    output.seek(0)
                    printed = output.read()
            self.assertIn("# Codex Team Summary", printed)
            self.assertIn("Final handoff", printed)

            args = team_ops.parse_args(["--json", "summary", "--run-id", "team-summary", "--mark-reviewed"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_summary(args), 0)
                    output.seek(0)
                    reviewed_payload = json.loads(output.read())
            self.assertTrue(reviewed_payload["reviewed"])
            self.assertTrue(Path(reviewed_payload["review_path"]).exists())
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_cmd_sync_writes_bus_report(self) -> None:
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
            device = DeviceRecord(
                id="local-1",
                name="Local",
                host="localhost",
                user="ao",
                status="ready",
                project_root=str(ctx.workspace),
            )
            save_devices(ctx.devices, (device,))
            run_dir = ctx.team_dir / "team-sync"
            (run_dir / "lanes").mkdir(parents=True)
            manifest = {
                "run_id": "team-sync",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "device_id": "local-1",
                        "device_name": "Local",
                        "lane_slug": "coordinator-local",
                        "lane_title": "Commander / Integrator",
                        "focus": "Coordinate",
                        "target": "ao@localhost:22",
                    }
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            args = team_ops.parse_args([
                "--json",
                "sync",
                "--run-id",
                "team-sync",
                "--project-root",
                str(ctx.workspace),
            ])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_sync(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertEqual(payload["synced"], 1)
            self.assertEqual(payload["errors"], [])
            self.assertTrue(Path(payload["bus_report"]).exists())
            report = load_bus_report(run_dir)
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report.synced_count, 1)
            self.assertEqual(report.targets[0].status, "local")
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_cmd_sync_resolves_stale_device_id_by_name(self) -> None:
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
            device = DeviceRecord(
                id="new-local-id",
                name="atlas-ubuntu",
                host="localhost",
                user="ao",
                status="ready",
                project_root=str(ctx.workspace),
            )
            save_devices(ctx.devices, (device,))
            assignment = {
                "device_id": "stale-local-id",
                "device_name": "atlas-ubuntu",
                "lane_slug": "coordinator-atlas-ubuntu",
                "lane_title": "Commander / Integrator",
                "focus": "Coordinate",
                "target": "ao@localhost:22",
            }
            self.assertEqual(team_ops.device_for_assignment((device,), assignment), device)

            run_dir = ctx.team_dir / "team-stale-id"
            (run_dir / "lanes").mkdir(parents=True)
            (run_dir / "manifest.json").write_text(json.dumps({
                "run_id": "team-stale-id",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [assignment],
            }), encoding="utf-8")

            args = team_ops.parse_args([
                "--json",
                "sync",
                "--run-id",
                "team-stale-id",
                "--project-root",
                str(ctx.workspace),
            ])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_sync(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertEqual(payload["synced"], 1)
            self.assertEqual(payload["errors"], [])
            report = load_bus_report(run_dir)
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report.targets[0].device_name, "atlas-ubuntu")
            self.assertEqual(report.targets[0].status, "local")
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_json_guides_ready_fleet_without_run(self) -> None:
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
            save_devices(ctx.devices, (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
            ))

            args = team_ops.parse_args(["doctor"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_doctor(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertTrue(payload["actionable"])
            self.assertEqual(payload["next_action"], "Prepare Team")
            self.assertEqual(payload["ready_device_count"], 1)
            self.assertEqual(payload["latest_run_id"], "")
            self.assertEqual(payload["latest_run_path"], "")
            self.assertEqual(payload["lane_counts"]["total"], 0)
            self.assertEqual(payload["bus_health"]["status"], "not_started")
            self.assertEqual(payload["blockers"], [])
            self.assertEqual(len(payload["readiness"]["rows"]), 1)
            row = payload["readiness"]["rows"][0]
            self.assertEqual(row["device_id"], "atlas-builder-1")
            self.assertEqual(row["status"], "ready")
            self.assertEqual(row["blocker_category"], "ready-saved")
            self.assertEqual(row["source"], "saved")
            self.assertTrue(row["trusted"])
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_check_no_persist_reports_fresh_probe_without_saving(self) -> None:
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
            saved = DeviceRecord(
                id="atlas-builder-1",
                name="atlas-builder",
                host="atlas-builder",
                user="ao",
                status="blocked",
                note="stale blocker",
            )
            checked = DeviceRecord(
                id="atlas-builder-1",
                name="atlas-builder",
                host="atlas-builder",
                user="ao",
                status="ready",
                note="fresh ready",
            )
            probe = DeviceProbe(
                device_id="atlas-builder-1",
                status="ready",
                summary="codex-cli 0.141.0 | ## main...origin/main | branch=main | changes=0",
                project_exists=True,
                git_state="## main...origin/main | branch=main | changes=0",
            )
            save_devices(ctx.devices, (saved,))

            with patch.object(team_ops, "check_devices", wraps=team_ops.check_devices) as wrapped:
                with patch.object(team_ops, "probe_device", return_value=probe):
                    args = team_ops.parse_args(["--json", "check", "--no-persist"])
                    with tempfile.TemporaryFile(mode="w+") as output:
                        with patch("sys.stdout", new=output):
                            self.assertEqual(team_ops.cmd_check(args), 0)
                            output.seek(0)
                            payload = json.loads(output.read())

            self.assertEqual(wrapped.call_args.kwargs["persist"], False)
            self.assertFalse(payload["persisted"])
            self.assertEqual(payload["rows"][0]["status"], "ready")
            saved_after = team_ops.load_devices(ctx.devices)
            self.assertEqual(saved_after[0].status, "blocked")
            self.assertEqual(checked.id, saved_after[0].id)
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_check_uses_fresh_probe_readiness(self) -> None:
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
            saved = (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="blocked",
                    note="stale saved blocker",
                ),
            )
            checked = (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
            )
            probes = {
                "atlas-builder-1": DeviceProbe(
                    device_id="atlas-builder-1",
                    status="ready",
                    summary="codex-cli 0.141.0 | ## main...origin/main | branch=main | changes=0",
                    project_exists=True,
                    git_state="## main...origin/main | branch=main | changes=0",
                )
            }
            save_devices(ctx.devices, saved)

            with patch.object(team_ops, "check_devices", return_value=(checked, probes)):
                args = team_ops.parse_args(["--json", "doctor", "--check"])
                with tempfile.TemporaryFile(mode="w+") as output:
                    with patch("sys.stdout", new=output):
                        self.assertEqual(team_ops.cmd_doctor(args), 0)
                        output.seek(0)
                        payload = json.loads(output.read())

            self.assertEqual(payload["probe_mode"], "checked")
            self.assertEqual(payload["checked_device_count"], 1)
            self.assertEqual(payload["ready_device_count"], 1)
            self.assertEqual(payload["readiness"]["ready"], 1)
            self.assertEqual(payload["blockers"], [])
            row = payload["readiness"]["rows"][0]
            self.assertEqual(row["device_id"], "atlas-builder-1")
            self.assertEqual(row["source"], "probe")
            self.assertEqual(row["status"], "ready")
            self.assertNotIn("raw", row)
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_readiness_rows_exclude_raw_probe_output(self) -> None:
        ctx = self._with_workspace()
        device = DeviceRecord(
            id="atlas-builder-1",
            name="atlas-builder",
            host="atlas-builder",
            user="ao",
            status="blocked",
        )
        probe = DeviceProbe(
            device_id=device.id,
            status="blocked",
            summary="SSH auth denied",
            raw="PRIVATE_RAW_PROBE_OUTPUT",
            returncode=255,
            checked=123,
        )

        payload = team_ops.build_team_doctor_report(
            (device,),
            team_root=ctx.team_dir,
            probes={device.id: probe},
            probe_mode="checked",
        )

        row = payload["readiness"]["rows"][0]
        self.assertEqual(row["device_id"], device.id)
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(row["blocker_category"], "ssh-auth-denied")
        self.assertEqual(row["action_priority"], 10)
        self.assertEqual(row["checked"], 123)
        self.assertNotIn("raw", row)
        self.assertNotIn("PRIVATE_RAW_PROBE_OUTPUT", json.dumps(payload))

    def test_doctor_check_reports_probe_errors(self) -> None:
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
            save_devices(ctx.devices, (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
            ))

            with patch.object(team_ops, "check_devices", side_effect=RuntimeError("network\nfailed")):
                args = team_ops.parse_args(["--json", "doctor", "--check"])
                with tempfile.TemporaryFile(mode="w+") as output:
                    with patch("sys.stdout", new=output):
                        self.assertEqual(team_ops.cmd_doctor(args), 0)
                        output.seek(0)
                        payload = json.loads(output.read())

            self.assertEqual(payload["probe_mode"], "error")
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["next_action"], "Check Fleet")
            self.assertTrue(any(item["category"] == "fleet-probe-failed" for item in payload["blockers"]))
            self.assertIn("network failed", payload["blockers"][0]["summary"])
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_json_reports_latest_run_bus_health_and_blockers(self) -> None:
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
            save_devices(ctx.devices, (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
                DeviceRecord(
                    id="atlas-main-1",
                    name="atlas-main",
                    host="atlas-main",
                    user="ao",
                    status="offline",
                ),
            ))
            run_dir = ctx.team_dir / "team-doctor"
            out_dir = run_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "run_id": "team-doctor",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "lane_title": "Core Systems Engineer",
                        "device_name": "atlas-builder",
                        "focus": "Backend",
                    },
                    {
                        "lane_slug": "ui-polish-atlas-main",
                        "lane_title": "Product / GTK UX Engineer",
                        "device_name": "atlas-main",
                        "focus": "UI",
                    },
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (out_dir / "backend-builder-atlas-builder.status.txt").write_text(
                "status=0\nfinished=2026-06-18T00:10:00-07:00\n",
                encoding="utf-8",
            )
            (out_dir / "backend-builder-atlas-builder.handoff.md").write_text("Backend done", encoding="utf-8")
            (out_dir / "ui-polish-atlas-main.status.txt").write_text(
                "status=1\nfinished=2026-06-18T00:11:00-07:00\n",
                encoding="utf-8",
            )
            bus_path = out_dir / "handoff-bus.md"
            bus_path.write_text("bus", encoding="utf-8")
            (out_dir / "handoff-bus-report.json").write_text(json.dumps({
                "run_id": "team-doctor",
                "team_dir": str(run_dir),
                "bus_path": str(bus_path),
                "sent": 2,
                "failures": [],
                "generated": "2026-06-18T00:12:00-07:00",
                "generated_epoch": 1710000000,
                "targets": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "device_name": "atlas-builder",
                        "target": "atlas-builder",
                        "status": "synced",
                        "detail": "ok",
                        "artifact_path": str(bus_path),
                        "artifact_sha256": "",
                        "artifact_remote_sha256": "",
                        "ts": 1710000001,
                    },
                    {
                        "lane_slug": "ui-polish-atlas-main",
                        "device_name": "atlas-main",
                        "target": "atlas-main",
                        "status": "stale",
                        "detail": "checksum mismatch",
                        "artifact_path": str(bus_path),
                        "artifact_sha256": "",
                        "artifact_remote_sha256": "",
                        "ts": 1710000002,
                    },
                ],
            }), encoding="utf-8")

            args = team_ops.parse_args(["--json", "doctor"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_doctor(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertFalse(payload["actionable"])
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["next_action"], "Repair Bus")
            self.assertEqual(payload["ready_device_count"], 1)
            self.assertEqual(payload["latest_run_id"], "team-doctor")
            self.assertEqual(Path(payload["latest_run_path"]), run_dir)
            self.assertEqual(payload["lane_counts"]["total"], 2)
            self.assertEqual(payload["lane_counts"]["collected"], 1)
            self.assertEqual(payload["lane_counts"]["failed"], 1)
            self.assertEqual(payload["bus_health"]["status"], "repair")
            self.assertEqual(payload["bus_health"]["synced"], 1)
            self.assertEqual(payload["bus_health"]["stale"], 1)
            self.assertTrue(any(item["scope"] == "fleet" for item in payload["blockers"]))
            self.assertTrue(any(item["scope"] == "run" for item in payload["blockers"]))
            self.assertTrue(any(item["scope"] == "bus" for item in payload["blockers"]))
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_json_reports_missing_lane_handoff(self) -> None:
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
            save_devices(ctx.devices, (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
            ))
            run_dir = ctx.team_dir / "team-missing-handoff"
            out_dir = run_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "run_id": "team-missing-handoff",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "lane_title": "Core Systems Engineer",
                        "device_name": "atlas-builder",
                        "focus": "Backend",
                    },
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (out_dir / "backend-builder-atlas-builder.status.txt").write_text(
                "status=0\nfinished=2026-06-18T00:10:00-07:00\n",
                encoding="utf-8",
            )
            (out_dir / "backend-builder-atlas-builder.final.txt").write_text(
                "Final message without handoff",
                encoding="utf-8",
            )

            args = team_ops.parse_args(["--json", "doctor"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_doctor(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertTrue(payload["actionable"])
            self.assertEqual(payload["status"], "review")
            self.assertEqual(payload["next_action"], "Review Summary")
            self.assertEqual(payload["handoff_health"]["status"], "missing")
            self.assertEqual(payload["handoff_health"]["missing"], 1)
            self.assertEqual(payload["handoff_health"]["final_only"], 1)
            lane = payload["handoff_health"]["lanes"][0]
            self.assertEqual(lane["lane_slug"], "backend-builder-atlas-builder")
            self.assertEqual(lane["handoff"], "final_only")
            self.assertTrue(any(item["category"] == "missing-handoff" for item in payload["blockers"]))
            self.assertNotIn("Final message without handoff", json.dumps(payload))
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_json_treats_reviewed_stale_bus_run_as_closed(self) -> None:
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
            save_devices(ctx.devices, (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
            ))
            run_dir = ctx.team_dir / "team-reviewed-stale"
            out_dir = run_dir / "out"
            collected_dir = run_dir / "collected" / "atlas-builder"
            out_dir.mkdir(parents=True, exist_ok=True)
            collected_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "run_id": "team-reviewed-stale",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "lane_title": "Core Systems Engineer",
                        "device_name": "atlas-builder",
                        "focus": "Backend",
                    },
                    {
                        "lane_slug": "ui-polish-atlas-main",
                        "lane_title": "Product / GTK UX Engineer",
                        "device_name": "atlas-main",
                        "focus": "UI",
                    },
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (collected_dir / "backend-builder-atlas-builder.handoff.md").write_text("Backend done", encoding="utf-8")
            bus_path = out_dir / "handoff-bus.md"
            bus_path.write_text("bus", encoding="utf-8")
            (out_dir / "handoff-bus-report.json").write_text(json.dumps({
                "run_id": "team-reviewed-stale",
                "team_dir": str(run_dir),
                "bus_path": str(bus_path),
                "sent": 2,
                "failures": [],
                "generated": "2026-06-18T00:12:00-07:00",
                "generated_epoch": 1710000000,
                "targets": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "device_name": "atlas-builder",
                        "target": "atlas-builder",
                        "status": "synced",
                        "detail": "ok",
                        "artifact_path": str(bus_path),
                    },
                    {
                        "lane_slug": "ui-polish-atlas-main",
                        "device_name": "atlas-main",
                        "target": "atlas-main",
                        "status": "stale",
                        "detail": "offline worker left stale bus artifact",
                        "artifact_path": str(bus_path),
                    },
                ],
            }), encoding="utf-8")
            team_ops.mark_team_summary_reviewed(run_dir)

            args = team_ops.parse_args(["--json", "doctor"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_doctor(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertTrue(payload["summary_reviewed"])
            self.assertTrue(payload["actionable"])
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["next_action"], "Prepare Team")
            self.assertEqual(payload["latest_run_id"], "team-reviewed-stale")
            self.assertEqual(payload["bus_health"]["status"], "reviewed")
            self.assertEqual(payload["bus_health"]["stale"], 1)
            self.assertFalse(any(item["scope"] in {"run", "bus"} for item in payload["blockers"]))
        finally:
            team_ops.CONFIG_DIR = original_config
            team_ops.DEVICES_FILE = original_devices
            team_ops.TEAM_DIR = original_team
            team_ops.LAST_TEAM_RUN_FILE = original_last

    def test_doctor_json_treats_reviewed_prepared_run_as_closed(self) -> None:
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
            save_devices(ctx.devices, (
                DeviceRecord(
                    id="atlas-builder-1",
                    name="atlas-builder",
                    host="atlas-builder",
                    user="ao",
                    status="ready",
                ),
            ))
            run_dir = ctx.team_dir / "team-reviewed-prepared"
            out_dir = run_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "run_id": "team-reviewed-prepared",
                "created": "2026-06-18T00:00:00-07:00",
                "project": str(ctx.workspace),
                "assignments": [
                    {
                        "lane_slug": "backend-builder-atlas-builder",
                        "lane_title": "Core Systems Engineer",
                        "device_name": "atlas-builder",
                        "focus": "Backend",
                    },
                ],
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            team_ops.mark_team_summary_reviewed(run_dir)

            args = team_ops.parse_args(["--json", "doctor"])
            with tempfile.TemporaryFile(mode="w+") as output:
                with patch("sys.stdout", new=output):
                    self.assertEqual(team_ops.cmd_doctor(args), 0)
                    output.seek(0)
                    payload = json.loads(output.read())

            self.assertTrue(payload["summary_reviewed"])
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["next_action"], "Prepare Team")
            self.assertEqual(payload["bus_health"]["status"], "reviewed")
            self.assertEqual(payload["handoff_health"]["status"], "reviewed")
            self.assertFalse(any(item["scope"] in {"run", "bus", "handoff"} for item in payload["blockers"]))
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
