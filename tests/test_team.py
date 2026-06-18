import json
import os
import tempfile
import unittest
from pathlib import Path

from codex_team import (
    inspect_team_run,
    latest_team_run_dir,
    team_role_for_device,
    team_roles_markdown,
    team_run_dirs,
    write_bus_report,
    write_handoff_bus,
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
        self.assertEqual(team_role_for_device("atlas-ubuntu", "atlas-ubuntu.tailnet").id, "verifier")
        self.assertEqual(team_role_for_device("atlas-cockpit", "atlas-cockpit.tailnet").id, "ui-polish")
        self.assertEqual(team_role_for_device("This Device Test", "localhost").id, "coordinator")

    def test_team_roles_markdown_documents_boundaries(self) -> None:
        text = team_roles_markdown()

        self.assertIn("Backend Builder", text)
        self.assertIn("Boundary:", text)
        self.assertIn("Verifier", text)


if __name__ == "__main__":
    unittest.main()
