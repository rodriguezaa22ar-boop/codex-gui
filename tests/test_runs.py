import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_receipts import CodexReceiptRecord
from codex_runs import (
    load_run_records,
    new_run_record,
    remove_run_record,
    run_detail,
    save_run_records,
    update_run_record,
    upsert_run_record,
)


class CodexRunLedgerTests(unittest.TestCase):
    def test_run_record_is_metadata_only(self) -> None:
        record = new_run_record(
            project="/tmp/private-project",
            action="interactive",
            profile="maximum-power",
            surface="embedded",
            status="launched",
            prompt="do not store raw prompt token=abc123",
            command="codex raw command body",
        )
        encoded = json.dumps(record.__dict__)
        self.assertIn("prompt_hash", encoded)
        self.assertIn("command_hash", encoded)
        self.assertNotIn("token=abc123", encoded)
        self.assertNotIn("raw command body", encoded)
        self.assertIn("Metadata-only", run_detail(record))

    def test_run_record_can_link_receipt_metadata(self) -> None:
        receipt = CodexReceiptRecord(
            id="receipt-one",
            observed_at="2026-06-16T00:00:00Z",
            event_type="codex_gui.command.prepared",
            project_name="app",
            project_hash="p",
            action="interactive",
            profile="maximum-power",
            prompt_hash="p1",
            command_hash="c1",
            event_path="/tmp/event.json",
            receipt_path="/tmp/receipt.json",
            event_hash="1" * 64,
            receipt_hash="2" * 64,
            status="verified",
        )
        record = new_run_record(
            project="/tmp/app",
            action="interactive",
            profile="maximum-power",
            surface="external",
            status="launched",
            prompt="build",
            command="codex build",
            receipt=receipt,
        )
        self.assertEqual(record.receipt_id, "receipt-one")
        self.assertEqual(record.receipt_hash, "2" * 64)

    def test_identical_launches_in_same_second_keep_distinct_ids(self) -> None:
        with (
            patch("codex_runs.time.time", return_value=1_779_000_000),
            patch("codex_runs.time.time_ns", side_effect=[1_779_000_000_000_000_001, 1_779_000_000_000_000_002]),
        ):
            one = new_run_record(
                project="/tmp/app",
                action="interactive",
                profile="maximum-power",
                surface="embedded",
                status="launched",
                prompt="build",
                command="codex build",
            )
            two = new_run_record(
                project="/tmp/app",
                action="interactive",
                profile="maximum-power",
                surface="embedded",
                status="launched",
                prompt="build",
                command="codex build",
            )
        self.assertNotEqual(one.id, two.id)

    def test_save_load_upsert_remove_and_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.json"
            one = new_run_record(
                project="/tmp/one",
                action="interactive",
                profile="maximum-power",
                surface="embedded",
                status="launched",
                prompt="one",
                command="codex one",
            )
            two = new_run_record(
                project="/tmp/two",
                action="exec",
                profile="maximum-power",
                surface="headless",
                status="running",
                prompt="two",
                command="codex exec two",
            )
            records = upsert_run_record([], one)
            records = upsert_run_record(records, two)
            updated = update_run_record(two, status="done", exit_code=0)
            records = upsert_run_record(records, updated)
            save_run_records(path, records)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            loaded = load_run_records(path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(next(record for record in loaded if record.id == two.id).status, "done")
            self.assertEqual(remove_run_record(loaded, one.id)[0].id, two.id)


if __name__ == "__main__":
    unittest.main()
