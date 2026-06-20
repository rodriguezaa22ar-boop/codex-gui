import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_team import (
    TeamBusReport,
    TeamBusTargetStatus,
    TeamBundleReport,
    TeamBundleTargetStatus,
    TeamLaneStatus,
    TeamRunStatus,
    summarize_team_chat,
    is_team_summary_reviewed,
    load_bus_report,
    load_bundle_report,
    inspect_team_run,
    latest_team_run_dir,
    mark_team_summary_reviewed,
    merge_team_chat_texts,
    read_team_chat,
    team_operator_summary,
    team_role_for_device,
    team_roles_markdown,
    team_run_dirs,
    write_team_chat_entry,
    write_bus_report,
    write_bundle_report,
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

    def test_write_team_summary_falls_back_to_out_when_root_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            original_write_text = Path.write_text

            def write_text(path: Path, *args, **kwargs):
                if path == team_dir / "summary.md":
                    raise OSError("read-only run root")
                return original_write_text(path, *args, **kwargs)

            with patch.object(Path, "write_text", write_text):
                summary = write_team_summary(team_dir)

            self.assertEqual(summary, team_dir / "out" / "team-summary.md")
            self.assertTrue(summary.exists())
            self.assertIn("No collected handoff", summary.read_text(encoding="utf-8"))

    def test_summary_review_marker_falls_back_with_out_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            original_write_text = Path.write_text

            def write_text(path: Path, *args, **kwargs):
                if path in {team_dir / "summary.md", team_dir / "summary-reviewed.json"}:
                    raise OSError("read-only run root")
                return original_write_text(path, *args, **kwargs)

            with patch.object(Path, "write_text", write_text):
                marker = mark_team_summary_reviewed(team_dir)

            self.assertEqual(marker, team_dir / "out" / "summary-reviewed.json")
            self.assertTrue(is_team_summary_reviewed(team_dir))

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

    def test_summarize_team_chat_reports_active_senders_and_latest(self) -> None:
        text = (
            "# Codex Team Chat\n"
            "[2026-01-01 12:00:00] Atlas Builder (backend-builder): started\n"
            "[2026-01-01 12:02:00] UI Engineer (ui-polish): review this blocker\n"
            "[2026-01-01 12:01:00] Atlas Builder (backend-builder): synced\n"
            "[2026-01-01 12:03:00] Atlas Builder (backend-builder): blocked by missing artifact"
        )
        summary = summarize_team_chat(text)
        self.assertEqual(summary.total_updates, 4)
        self.assertEqual(summary.active_senders, ("Atlas Builder", "UI Engineer"))
        self.assertEqual(summary.sender_counts, (("Atlas Builder", 2), ("UI Engineer", 1)))
        self.assertEqual(summary.lane_activity[0], ("backend-builder", 3, "Atlas Builder", summary.events[3].ts, "blocked by missing artifact"))
        self.assertIsNotNone(summary.latest)
        if summary.latest is None:
            self.fail("expected a latest team chat event")
        self.assertEqual(summary.latest.sender, "Atlas Builder")
        self.assertEqual(summary.latest.lane, "backend-builder")
        self.assertEqual(summary.blocked_mentions, 2)
        self.assertEqual(summary.review_mentions, 1)
        self.assertIn("blocked", summary.latest.message)

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

    def test_merge_team_chat_texts_orders_by_timestamp(self) -> None:
        merged = merge_team_chat_texts(
            "[2026-01-01 12:05:00] atlas-builder: blocked\n# Codex Team Chat\n"
            "[2026-01-01 12:10:00] atlas-main: resolved",
            "[2026-01-01 12:00:00] atlas-builder: started",
        )
        lines = [line for line in merged.splitlines() if line.strip()]
        self.assertEqual(lines[0], "# Codex Team Chat")
        self.assertEqual(lines[1], "[2026-01-01 12:00:00] atlas-builder: started")
        self.assertEqual(lines[2], "[2026-01-01 12:05:00] atlas-builder: blocked")
        self.assertEqual(lines[3], "[2026-01-01 12:10:00] atlas-main: resolved")

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

    def test_write_and_load_bundle_report_with_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            bundle_dir = team_dir / "out" / "evidence-demo"
            bundle_dir.mkdir(parents=True, exist_ok=True)

            report_path = write_bundle_report(
                team_dir,
                sent=2,
                failures=("atlas-main: stale",),
                bundle_name="evidence-demo",
                bundle_path=bundle_dir,
                bundle_sha256="bundle-sha",
                target_statuses=(
                    TeamBundleTargetStatus(
                        lane_slug="backend-builder-atlas-builder",
                        device_name="atlas-builder",
                        target="ao@atlas-builder",
                        status="synced",
                        detail="ok",
                        artifact_path=str(bundle_dir),
                        artifact_sha256="bundle-sha",
                        artifact_remote_sha256="bundle-sha",
                        marker_path=str(bundle_dir / "marker"),
                        ts=1710000000,
                    ),
                    TeamBundleTargetStatus(
                        lane_slug="ui-polish-atlas-main",
                        device_name="atlas-main",
                        target="ao@atlas-main",
                        status="stale",
                        detail="checksum mismatch",
                        artifact_path=str(bundle_dir),
                        artifact_sha256="bundle-sha",
                        artifact_remote_sha256="old-sha",
                        marker_path=str(bundle_dir / "marker-main"),
                        ts=1710000001,
                    ),
                ),
            )
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            parsed = load_bundle_report(team_dir)

            self.assertEqual(report_path.name, "evidence-bundle-report.json")
            self.assertEqual(payload["sent"], 2)
            self.assertEqual(payload["bundle_name"], "evidence-demo")
            self.assertIsNotNone(parsed)
            if parsed is None:
                self.fail("Expected parsed bundle report")
            self.assertEqual(parsed.synced_count, 1)
            self.assertEqual(parsed.stale_count, 1)
            self.assertEqual(parsed.targets[0].device_name, "atlas-builder")
            self.assertEqual(parsed.targets[1].status, "stale")
            self.assertEqual(parsed.failures, ("atlas-main: stale",))
            self.assertEqual(parsed.bundle_path, str(bundle_dir))
            self.assertEqual(parsed.bundle_name, "evidence-demo")

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

    def test_team_operator_summary_guides_unprepared_fleet(self) -> None:
        blocked = team_operator_summary(None, ready_devices=0, saved_runs=0)
        ready = team_operator_summary(None, ready_devices=3, saved_runs=2)

        self.assertEqual(blocked.next_action, "Check Fleet")
        self.assertEqual(blocked.status, "review")
        self.assertEqual(blocked.lane_text, "no lanes")
        self.assertEqual(ready.next_action, "Prepare Team")
        self.assertEqual(ready.status, "ready")

    def test_team_operator_summary_guides_team_lifecycle(self) -> None:
        run_status = TeamRunStatus(
            run_id="team-one",
            team_dir=Path("/tmp/team-one"),
            project="/work/codex-gui",
            created="2026-06-18T12:00:00-07:00",
            assignments=(),
            lanes=(
                TeamLaneStatus(
                    lane_slug="backend",
                    lane_title="Backend",
                    device_name="atlas-builder",
                    focus="backend",
                    status="prepared",
                    detail="waiting",
                ),
                TeamLaneStatus(
                    lane_slug="verify",
                    lane_title="Verify",
                    device_name="atlas-cockpit",
                    focus="verify",
                    status="prepared",
                    detail="waiting",
                ),
            ),
        )
        prepared = team_operator_summary(run_status)

        self.assertEqual(prepared.next_action, "Launch Team")
        self.assertIn("prepared", prepared.lane_text)

        prepared_bus = TeamBusReport(
            run_id="team-one",
            team_dir="/tmp/team-one",
            bus_path="/tmp/team-one/out/handoff-bus.md",
            sent=2,
            failures=(),
            generated="2026-06-18T12:05:00-07:00",
            generated_epoch=1710000000,
            targets=(
                TeamBusTargetStatus("backend", "atlas-builder", "atlas-builder", "synced", "ok"),
                TeamBusTargetStatus("verify", "atlas-cockpit", "atlas-cockpit", "synced", "ok"),
            ),
        )
        synced_prepared = team_operator_summary(run_status, prepared_bus)

        self.assertEqual(synced_prepared.next_action, "Launch Team")
        reviewed_prepared = team_operator_summary(run_status, prepared_bus, summary_reviewed=True)

        self.assertEqual(reviewed_prepared.next_action, "Prepare Team")
        self.assertEqual(reviewed_prepared.status, "ready")

        collected = TeamRunStatus(
            run_id=run_status.run_id,
            team_dir=run_status.team_dir,
            project=run_status.project,
            created=run_status.created,
            assignments=run_status.assignments,
            lanes=(
                TeamLaneStatus("backend", "Backend", "atlas-builder", "backend", "collected", "handoff"),
                TeamLaneStatus("verify", "Verify", "atlas-cockpit", "verify", "collected", "handoff"),
            ),
        )
        needs_bus = team_operator_summary(collected)

        self.assertEqual(needs_bus.next_action, "Sync Bus")

        healthy_bus = TeamBusReport(
            run_id="team-one",
            team_dir="/tmp/team-one",
            bus_path="/tmp/team-one/out/handoff-bus.md",
            sent=2,
            failures=(),
            generated="2026-06-18T12:10:00-07:00",
            generated_epoch=1710000000,
            targets=(
                TeamBusTargetStatus("backend", "atlas-builder", "atlas-builder", "synced", "ok"),
                TeamBusTargetStatus("verify", "atlas-cockpit", "atlas-cockpit", "synced", "ok"),
            ),
        )
        needs_review = team_operator_summary(collected, healthy_bus)
        reviewed = team_operator_summary(collected, healthy_bus, summary_reviewed=True)

        self.assertEqual(needs_review.next_action, "Review Summary")
        self.assertEqual(reviewed.next_action, "Prepare Team")

    def test_team_operator_summary_closes_reviewed_partial_run(self) -> None:
        run_status = TeamRunStatus(
            run_id="team-partial",
            team_dir=Path("/tmp/team-partial"),
            project="/work/codex-gui",
            created="2026-06-18T12:00:00-07:00",
            assignments=(),
            lanes=(
                TeamLaneStatus("backend", "Backend", "atlas-builder", "backend", "collected", "handoff"),
                TeamLaneStatus("verify", "Verify", "atlas-cockpit", "verify", "prepared", "waiting"),
            ),
        )

        needs_collection = team_operator_summary(run_status, summary_reviewed=False)
        reviewed = team_operator_summary(run_status, summary_reviewed=True)

        self.assertEqual(needs_collection.next_action, "Collect Team")
        self.assertEqual(needs_collection.status, "review")
        self.assertEqual(reviewed.next_action, "Prepare Team")
        self.assertEqual(reviewed.status, "ready")

    def test_mark_team_summary_reviewed_tracks_current_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_dir = Path(tmp) / "team-one"
            self.write_manifest(team_dir, "team-one")
            out_dir = team_dir / "collected" / "atlas-builder"
            out_dir.mkdir(parents=True)
            final = out_dir / "backend-builder-atlas-builder.final.txt"
            final.write_text("Reviewed handoff", encoding="utf-8")

            self.assertFalse(is_team_summary_reviewed(team_dir))
            marker = mark_team_summary_reviewed(team_dir)

            self.assertTrue(marker.exists())
            self.assertTrue(is_team_summary_reviewed(team_dir))

            summary = team_dir / "summary.md"
            summary.write_text(summary.read_text(encoding="utf-8") + "\nChanged\n", encoding="utf-8")
            self.assertFalse(is_team_summary_reviewed(team_dir))

    def test_team_operator_summary_prioritizes_bus_repair(self) -> None:
        run_status = TeamRunStatus(
            run_id="team-one",
            team_dir=Path("/tmp/team-one"),
            project="/work/codex-gui",
            created="2026-06-18T12:00:00-07:00",
            assignments=(),
            lanes=(TeamLaneStatus("backend", "Backend", "atlas-builder", "backend", "collected", "handoff"),),
        )
        bus = TeamBusReport(
            run_id="team-one",
            team_dir="/tmp/team-one",
            bus_path="/tmp/team-one/out/handoff-bus.md",
            sent=1,
            failures=("atlas-builder: stale",),
            generated="2026-06-18T12:10:00-07:00",
            generated_epoch=1710000000,
            targets=(
                TeamBusTargetStatus(
                    lane_slug="backend",
                    device_name="atlas-builder",
                    target="atlas-builder",
                    status="stale",
                    detail="checksum mismatch",
                ),
            ),
        )
        summary = team_operator_summary(run_status, bus)

        self.assertEqual(summary.next_action, "Repair Bus")
        self.assertEqual(summary.status, "blocked")
        self.assertIn("stale", summary.bus_text)

        legacy_bus = TeamBusReport(
            run_id="team-one",
            team_dir="/tmp/team-one",
            bus_path="/tmp/team-one/out/handoff-bus.md",
            sent=1,
            failures=("atlas-builder: timeout",),
            generated="2026-06-18T12:10:00-07:00",
            generated_epoch=1710000000,
        )
        legacy_summary = team_operator_summary(run_status, legacy_bus)

        self.assertEqual(legacy_summary.next_action, "Repair Bus")
        self.assertIn("failure", legacy_summary.bus_text)

    def test_team_operator_summary_closes_reviewed_stale_bus_run(self) -> None:
        run_status = TeamRunStatus(
            run_id="team-one",
            team_dir=Path("/tmp/team-one"),
            project="/work/codex-gui",
            created="2026-06-18T12:00:00-07:00",
            assignments=(),
            lanes=(
                TeamLaneStatus("backend", "Backend", "atlas-builder", "backend", "collected", "handoff"),
                TeamLaneStatus("ui", "UI", "atlas-main", "ui", "prepared", "waiting"),
            ),
        )
        bus = TeamBusReport(
            run_id="team-one",
            team_dir="/tmp/team-one",
            bus_path="/tmp/team-one/out/handoff-bus.md",
            sent=1,
            failures=(),
            generated="2026-06-18T12:10:00-07:00",
            generated_epoch=1710000000,
            targets=(
                TeamBusTargetStatus("backend", "atlas-builder", "atlas-builder", "synced", "ok"),
                TeamBusTargetStatus("ui", "atlas-main", "atlas-main", "stale", "checksum mismatch"),
            ),
        )

        blocked = team_operator_summary(run_status, bus, summary_reviewed=False)
        reviewed = team_operator_summary(run_status, bus, summary_reviewed=True)

        self.assertEqual(blocked.next_action, "Repair Bus")
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(reviewed.next_action, "Prepare Team")
        self.assertEqual(reviewed.status, "ready")
        self.assertIn("stale", reviewed.bus_text)

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
        self.assertEqual(team_role_for_device("atlas-cockpit", "localhost").id, "verifier")
        self.assertEqual(team_role_for_device("This Device Test", "localhost").id, "coordinator")

    def test_team_roles_markdown_documents_boundaries(self) -> None:
        text = team_roles_markdown()

        self.assertIn("Core Systems Engineer", text)
        self.assertIn("Product / GTK UX Engineer", text)
        self.assertIn("Boundary:", text)
        self.assertIn("Verifier / Release Engineer", text)


if __name__ == "__main__":
    unittest.main()
