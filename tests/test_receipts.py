import json
import os
import tempfile
import unittest
from pathlib import Path

from codex_receipts import (
    CodexReceiptRecord,
    ReviewerBundle,
    atlas_binary,
    build_codex_event,
    create_reviewer_bundle,
    latest_event_hash,
    linked_receipt_chain,
    load_receipt_records,
    receipt_detail,
    replay_receipts,
    stamp_codex_receipt,
    utc_timestamp,
)


FAKE_RECEIPT = """{
  "schema_version": "atlas.receipt.v1",
  "receipt_id": "fake",
  "timestamp": "2026-06-16T00:00:00Z",
  "metadata_only": true,
  "raw_artifacts_embedded": false,
  "action": "codex_gui.command.prepared",
  "actor": "local:test",
  "subject": {"type": "codex-gui-command", "ref": "codex-gui://project/app/abc"},
  "evidence_refs": [],
  "artifact_refs": [],
  "approval_refs": [],
  "prev_hash": null,
  "event_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "receipt_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "known_limitations": ["fake receipt"],
  "verifier": {"name": "atlas receipt verify", "schema": "schemas/atlas.receipt.v1.schema.json"}
}
"""


def make_fake_atlas(root: Path) -> Path:
    binary = root / "tools" / "atlas" / "bin" / "atlas"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = receipt ] && [ "$2" = import-generic-event ]; then
  out=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --out ]; then
      out="$2"
      shift 2
      continue
    fi
    shift
  done
  [ -n "$out" ] || exit 2
  cat >"$out" <<'JSON'
""" + FAKE_RECEIPT + """JSON
  printf 'receipt: %s\\n' "$out"
elif [ "$1" = receipt ] && [ "$2" = verify ]; then
  printf '{"status":"ok"}\\n'
elif [ "$1" = receipt ] && [ "$2" = replay ]; then
  printf 'receipt replay: ok\\nmetadata-only boundary: ok\\n'
else
  exit 2
fi
""",
        encoding="utf-8",
    )
    os.chmod(binary, 0o755)
    return binary


class CodexReceiptTests(unittest.TestCase):
    def test_event_is_metadata_only_and_hashes_sensitive_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "event.json"
            event = build_codex_event(
                event_id="event-one",
                observed_at=utc_timestamp(),
                event_path=event_path,
                project="/tmp/private-project",
                action="interactive",
                profile="maximum-power",
                prompt="please do not store raw prompt token=abc123",
                command="codex secret command body",
                actor="local:test",
            )
            encoded = json.dumps(event)
            self.assertTrue(event["metadata_only"])
            self.assertFalse(event["raw_artifacts_embedded"])
            self.assertIn("sha256:prompt:", encoded)
            self.assertIn("sha256:command:", encoded)
            self.assertNotIn("token=abc123", encoded)
            self.assertNotIn("secret command body", encoded)

    def test_stamp_uses_atlas_import_verify_and_loads_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "atlas"
            make_fake_atlas(root)
            base = Path(tmp) / "receipts"
            result = stamp_codex_receipt(
                base,
                atlas_root=root,
                project="/tmp/project",
                action="interactive",
                profile="maximum-power",
                prompt="build it",
                command="codex build it",
                actor="local:test",
            )
            self.assertFalse(result.error)
            self.assertEqual(result.record.status, "verified")
            self.assertTrue(Path(result.record.event_path).exists())
            self.assertTrue(Path(result.record.receipt_path).exists())
            records = load_receipt_records(base)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].event_hash, "a" * 64)
            self.assertIn("Metadata-only", receipt_detail(records[0]))

    def test_replay_requires_two_receipts_and_uses_atlas_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "atlas"
            binary = make_fake_atlas(root)
            self.assertEqual(atlas_binary(root), binary)
            one = Path(tmp) / "one.json"
            two = Path(tmp) / "two.json"
            one.write_text(FAKE_RECEIPT, encoding="utf-8")
            two.write_text(FAKE_RECEIPT, encoding="utf-8")
            result = replay_receipts(root, [one, two])
            self.assertEqual(result.status, 0)
            self.assertIn("receipt replay: ok", result.output)

    def test_linked_chain_uses_prev_hash_not_timestamp_sorting(self) -> None:
        oldest = CodexReceiptRecord(
            id="b-oldest",
            observed_at="2026-06-16T00:00:00Z",
            event_type="codex_gui.command.prepared",
            project_name="app",
            project_hash="p",
            action="interactive",
            profile="maximum-power",
            prompt_hash="p1",
            command_hash="c1",
            event_path="/tmp/one.event.json",
            receipt_path="/tmp/one.receipt.json",
            event_hash="1" * 64,
            receipt_hash="a" * 64,
            prev_hash="",
            status="verified",
        )
        newest = CodexReceiptRecord(
            id="a-newest",
            observed_at="2026-06-16T00:00:00Z",
            event_type="codex_gui.command.prepared",
            project_name="app",
            project_hash="p",
            action="exec",
            profile="maximum-power",
            prompt_hash="p2",
            command_hash="c2",
            event_path="/tmp/two.event.json",
            receipt_path="/tmp/two.receipt.json",
            event_hash="2" * 64,
            receipt_hash="b" * 64,
            prev_hash="1" * 64,
            status="verified",
        )
        chain = linked_receipt_chain([newest, oldest], newest)
        self.assertEqual([record.id for record in chain], ["b-oldest", "a-newest"])

    def test_latest_event_hash_uses_newest_receipt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipts = Path(tmp) / "receipts"
            receipts.mkdir()
            old = receipts / "z-old.receipt.json"
            new = receipts / "a-new.receipt.json"
            old.write_text('{"event_hash":"' + ("1" * 64) + '"}', encoding="utf-8")
            new.write_text('{"event_hash":"' + ("2" * 64) + '"}', encoding="utf-8")
            os.utime(old, (100, 100))
            os.utime(new, (200, 200))
            self.assertEqual(latest_event_hash(Path(tmp)), "2" * 64)

    def test_create_reviewer_bundle_copies_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipts_root = Path(tmp) / "receipts"
            output_root = Path(tmp) / "bundle-output"
            receipts_root.mkdir()
            event_one = receipts_root / "events"
            event_one_file = receipts_root / "event-one.json"
            event_one_file.write_text("{\"id\": \"event-one\"}\n", encoding="utf-8")
            records = [
                CodexReceiptRecord(
                    id="event-one",
                    observed_at="2026-06-20T00:00:00Z",
                    event_type="codex_gui.command.prepared",
                    project_name="app",
                    project_hash="p",
                    action="interactive",
                    profile="maximum-power",
                    prompt_hash="a" * 64,
                    command_hash="b" * 64,
                    event_path=str(event_one_file),
                    receipt_path=str(event_one_file),
                    event_hash="e1",
                    receipt_hash="r1",
                    prev_hash="",
                    status="verified",
                )
            ]
            event_one.mkdir()
            (receipts_root / "events" / "event-one.json").write_text("{\"id\": \"event-one-mirror\"}\n", encoding="utf-8")

            run_rows = [
                {"id": "run-1", "status": "done", "command_hash": "c" * 64, "prompt_hash": "p" * 64,
                 "project_name": "app", "project_hash": "p", "action": "interactive", "profile": "maximum-power", "surface": "embedded"},
            ]
            team_summary = Path(tmp) / "team-summary.md"
            team_summary.write_text("team summary", encoding="utf-8")
            team_chat = Path(tmp) / "team-chat.md"
            team_chat.write_text("[2026-06-20 09:00:00] lane: kickoff\n", encoding="utf-8")

            bundle = create_reviewer_bundle(
                output_root,
                bundle_name="bundle-test",
                project="/tmp/app",
                receipt_records=records,
                run_records=run_rows,
                selected_receipt=records[0],
                launch_package_text="run package",
                context_summary="context",
                team_artifacts=[
                    (team_summary, "team/team-summary.md"),
                    (team_chat, "team/team-chat.md"),
                ],
                max_receipts=5,
            )

            self.assertIsInstance(bundle, ReviewerBundle)
            self.assertEqual(bundle.receipt_count, 1)
            self.assertEqual(bundle.run_count, 1)
            manifest = json.loads(Path(bundle.manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["selected_receipt_id"], "event-one")
            self.assertEqual(manifest["receipt_count"], 1)
            summary = Path(Path(bundle.bundle_dir) / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Project: /tmp/app", summary)
            self.assertTrue((Path(bundle.bundle_dir) / "evidence" / "receipts" / "events" / "event-one.json").exists())
            self.assertTrue((Path(bundle.bundle_dir) / "team" / "team-summary.md").exists())
            self.assertTrue((Path(bundle.bundle_dir) / "team" / "team-chat.md").exists())
            self.assertEqual(manifest["team_artifact_count"], 2)
            artifact_destinations = [row[1] for row in manifest["team_artifacts"]]
            self.assertIn("team/team-chat.md", artifact_destinations)


if __name__ == "__main__":
    unittest.main()
