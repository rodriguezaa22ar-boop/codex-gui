import json
import os
import tempfile
import unittest
from pathlib import Path

from codex_team import (
    TeamBusTargetStatus,
    load_bus_report,
    inspect_team_run,
    latest_team_run_dir,
    merge_team_chat_texts,
    read_team_chat,
    team_role_for_device,
    team_roles_markdown,
    team_run_dirs,
    write_team_chat_entry,
    write_bus_report,
    write_handoff_bus,
    write_role_bootstrap,
    write_team_summary,
)


class CodexTeamTests(unittest.TestCase):
    def write_manifest(self, team_dir: Path, run_id: str) -> None:
        team_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": run_id,
            "created": "2026-06-16T17:00:00-07:00",
            "project": "/work/codex-gui",
            "assignments": [
                {
                    "lane_slug": "backend-builder-atlas-builder",
                    "lane_title": "Backend Builder",
                    "device_name": "atlas-builder",
                    "target": "ao@atlas-builder:22",
                    "focus": "Implement backend orchestration.",
                    "project_root": "/home/ao/Projects/codex-gui",
                }
            ],
        }
        (team_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_inspect_team_run_reads_collected_lane_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            collected = team_dir / "collected" / "atlas-builder"
            collected.mkdir(parents=True)
            (collected / "backend-builder-atlas-builder.status.txt").write_text(
                "lane=backend-builder-atlas-builder\nstatus=0\nfinished=2026-06-16T17:10:00-07:00\n",
                encoding="utf-8",
            )
            (collected / "backend-builder-atlas-builder.handoff.md").write_text(
                "Changed backend sync logic.",
                encoding="utf-8",
            )
            (collected / "backend-builder-atlas-builder.final.txt").write_text(
                "Backend lane complete.",
                encoding="utf-8",
            )

            status = inspect_team_run(team_dir)

            self.assertEqual(status.run_id, "team-one")
            self.assertEqual(status.collected_count, 1)
            self.assertEqual(status.lanes[0].status, "collected")
            self.assertIn("handoff", status.lanes[0].detail)
            self.assertGreater(status.lanes[0].handoff_bytes, 0)

    def test_write_team_summary_combines_handoff_and_final_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            collected = team_dir / "collected" / "atlas-builder"
            collected.mkdir(parents=True)
            (collected / "backend-builder-atlas-builder.handoff.md").write_text("Handoff body", encoding="utf-8")
            (collected / "backend-builder-atlas-builder.final.txt").write_text("Final body", encoding="utf-8")

            summary = write_team_summary(team_dir)
            text = summary.read_text(encoding="utf-8")

            self.assertEqual(summary.name, "summary.md")
            self.assertIn("Backend Builder | atlas-builder", text)
            self.assertIn("Handoff body", text)
            self.assertIn("Final body", text)

    def test_write_handoff_bus_places_round_context_under_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            collected = team_dir / "collected" / "atlas-builder"
            collected.mkdir(parents=True)
            (collected / "backend-builder-atlas-builder.handoff.md").write_text("Backend handoff", encoding="utf-8")

            bus = write_handoff_bus(team_dir)
            text = bus.read_text(encoding="utf-8")
            summary_copy = team_dir / "out" / "team-summary.md"

            self.assertEqual(bus, team_dir / "out" / "handoff-bus.md")
            self.assertTrue(summary_copy.exists())
            self.assertIn("Next-round protocol", text)
            self.assertIn("Backend handoff", text)

    def test_team_chat_writes_and_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-chat"
            team_dir.mkdir(parents=True)
            path = write_team_chat_entry(
                team_dir,
                sender="Atlas Builder",
                lane="backend-builder-atlas-builder",
                message="Lane bootstrap started.\nNo blockers so far.",
            )
            self.assertTrue(path.exists())
            self.assertTrue(path.name.endswith("team-chat.md"))
            raw = read_team_chat(team_dir, max_lines=25)
            self.assertIn("Atlas Builder", raw)
            self.assertIn("Lane bootstrap started.", raw)

    def test_team_chat_truncates_to_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-chat"
            team_dir.mkdir(parents=True)
            for index in range(5):
                write_team_chat_entry(team_dir, sender=f"lane-{index}", lane=f"lane-{index}", message=f"update {index}")
            raw = read_team_chat(team_dir, max_lines=3)
            self.assertEqual(len(raw.strip().splitlines()), 3)

    def test_merge_team_chat_texts_deduplicates_entries(self) -> None:
        merged = merge_team_chat_texts(
            "# Codex Team Chat\n[2026-01-01 12:00:00] atlas-builder (backend-builder): started\n",
            "  # Codex Team Chat\n[2026-01-01 12:00:00] atlas-builder (backend-builder): started\n"
            "[2026-01-01 12:05:00] atlas-builder (backend-builder): blocked",
        )
        lines = [line for line in merged.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "# Codex Team Chat")
        self.assertEqual(lines[1], "[2026-01-01 12:00:00] atlas-builder (backend-builder): started")
        self.assertEqual(lines[2], "[2026-01-01 12:05:00] atlas-builder (backend-builder): blocked")

    def test_write_role_bootstrap_includes_lane_roles_and_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            bootstrap_json = write_role_bootstrap(team_dir)
            bootstrap_md = bootstrap_json.with_name("role-bootstrap.md")

            markdown = bootstrap_md.read_text(encoding="utf-8")
            payload = json.loads(bootstrap_json.read_text(encoding="utf-8"))

            self.assertEqual(payload["lane_count"], 1)
            self.assertEqual(payload["run_id"], "team-one")
            self.assertEqual(payload["roles"][0]["role_id"], "")
            self.assertIn("backend-builder-atlas-builder", markdown)
            self.assertIn("startup: codex -p maximum-power", markdown)
            self.assertIn("Codex Team Role Bootstrap", markdown)

    def test_write_role_bootstrap_respects_assignment_role_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-custom"
            payload = {
                "run_id": "team-custom",
                "created": "2026-06-16T17:00:00-07:00",
                "project": "/work/codex-gui",
                "assignments": [
                    {
                        "lane_slug": "custom-lane",
                        "lane_title": "Custom Lane",
                        "device_name": "builder",
                        "role_id": "verifier",
                        "role_title": "Custom Verifier",
                        "role_profile": "pro-default",
                        "role_focus": "Test release gate assumptions.",
                        "role_boundary": "Strict output-only review.",
                        "target": "ao@atlas-cockpit:22",
                        "focus": "validate checks.",
                        "project_root": "/home/ao/Projects/codex-gui",
                    }
                ],
            }
            team_dir.mkdir(parents=True, exist_ok=True)
            (team_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

            bootstrap_json = write_role_bootstrap(team_dir)
            payload_out = json.loads(bootstrap_json.read_text(encoding="utf-8"))
            lane_role = payload_out["roles"][0]

            self.assertEqual(lane_role["role_id"], "verifier")
            self.assertEqual(lane_role["role_title"], "Custom Verifier")
            self.assertEqual(lane_role["role_profile"], "pro-default")
            self.assertIn("Strict output-only review.", lane_role["role_boundary"])

    def test_write_bus_report_persists_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            bus_path = team_dir / "out" / "handoff-bus.md"
            bus_path.parent.mkdir(parents=True, exist_ok=True)
            bus_path.write_text("bus", encoding="utf-8")

            report = write_bus_report(team_dir, sent=2, failures=["atlas-cockpit: timeout"], bus_path=bus_path)
            payload = json.loads(report.read_text(encoding="utf-8"))

            self.assertEqual(report.name, "handoff-bus-report.json")
            self.assertEqual(payload["sent"], 2)
            self.assertEqual(payload["failures"], ["atlas-cockpit: timeout"])

    def test_bus_report_synced_and_stale_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            out_dir = team_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            bus_path = out_dir / "handoff-bus.md"
            bus_path.write_text("bus", encoding="utf-8")
            write_bus_report(
                team_dir,
                sent=2,
                failures=[],
                bus_path=bus_path,
                target_statuses=(
                    TeamBusTargetStatus(
                        lane_slug="backend-builder-atlas-builder",
                        device_name="atlas-builder",
                        target="atlas-builder",
                        status="synced",
                        detail="ok",
                        artifact_path=str(bus_path),
                        artifact_sha256="",
                        ts=1710000000,
                    ),
                    TeamBusTargetStatus(
                        lane_slug="ui-polish-atlas-main",
                        device_name="atlas-main",
                        target="atlas-main",
                        status="stale",
                        detail="stale",
                        artifact_path=str(bus_path),
                        artifact_sha256="abc",
                        ts=1710000001,
                    ),
                ),
            )
            status = load_bus_report(team_dir)
            self.assertIsNotNone(status)
            if status is None:
                self.fail("Expected bus report")
            self.assertEqual(status.synced_count, 1)
            self.assertEqual(status.failed_count, 0)
            self.assertEqual(status.stale_count, 1)

    def test_write_and_load_bus_report_with_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            out_dir = team_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            bus_path = out_dir / "handoff-bus.md"
            bus_path.write_text("bus", encoding="utf-8")
            report_path = write_bus_report(
                team_dir,
                sent=2,
                failures=["atlas-cockpit: timeout"],
                bus_path=bus_path,
                target_statuses=(
                    TeamBusTargetStatus(
                        lane_slug="backend-builder-atlas-builder",
                        device_name="atlas-builder",
                        target="atlas-builder",
                        status="synced",
                        detail="ok",
                        artifact_path="/tmp/bus",
                        artifact_sha256="sha",
                        artifact_remote_sha256="remote-sha",
                        ts=1710000000,
                    ),
                ),
            )
            self.assertEqual(report_path.name, "handoff-bus-report.json")
            parsed = load_bus_report(team_dir)

            self.assertIsNotNone(parsed)
            if parsed is None:
                self.fail("Expected parsed bus report")
            self.assertEqual(parsed.run_id, "team-one")
            self.assertEqual(parsed.targets[0].device_name, "atlas-builder")
            self.assertEqual(parsed.targets[0].status, "synced")
            self.assertEqual(parsed.targets[0].artifact_sha256, "sha")
            self.assertEqual(parsed.targets[0].artifact_remote_sha256, "remote-sha")

    def test_load_bus_report_legacy_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            out_dir = team_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            report_path = out_dir / "handoff-bus-report.json"
            report_path.write_text(json.dumps({
                "run_id": "team-one",
                "team_dir": str(team_dir),
                "bus_path": str(out_dir / "handoff-bus.md"),
                "sent": 1,
                "failures": ["atlas-cockpit: offline"],
                "generated": "2026-06-16T20:00:00-07:00",
            }), encoding="utf-8")

            status = load_bus_report(team_dir)

            self.assertIsNotNone(status)
            if status is None:
                self.fail("Expected bus report")
            self.assertEqual(status.targets, ())
            self.assertEqual(status.failed_count, 0)
            self.assertEqual(status.sent, 1)

    def test_latest_team_run_dir_sorts_by_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "team-old"
            newer = root / "team-new"
            self.write_manifest(older, "team-old")
            self.write_manifest(newer, "team-new")
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            self.assertEqual(team_run_dirs(root), (newer, older))
            self.assertEqual(latest_team_run_dir(root), newer)

    def test_named_atlas_devices_get_stable_separate_roles(self) -> None:
        self.assertEqual(team_role_for_device("atlas-builder", "atlas-builder.tailnet").id, "backend-builder")
        self.assertEqual(team_role_for_device("atlas-ubuntu", "atlas-ubuntu.tailnet").id, "coordinator")
        self.assertEqual(team_role_for_device("atlas-main", "atlas-main.tailnet").id, "ui-polish")
        self.assertEqual(team_role_for_device("atlas-cockpit", "atlas-cockpit.tailnet").id, "verifier")
        self.assertEqual(team_role_for_device("This Device Test", "localhost").id, "coordinator")

    def test_team_roles_markdown_documents_boundaries(self) -> None:
        text = team_roles_markdown()

        self.assertIn("Core Systems Engineer", text)
        self.assertIn("Product / GTK UX Engineer", text)
        self.assertIn("Boundary:", text)
        self.assertIn("Verifier / Release Engineer", text)


if __name__ == "__main__":
    unittest.main()
