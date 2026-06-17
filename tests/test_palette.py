import unittest
import tempfile
from pathlib import Path

from codex_actions import action_by_id
from codex_palette import (
    PaletteContext,
    build_palette_preview,
    load_palette_history,
    palette_history_detail,
    palette_history_log,
    record_palette_event,
    save_palette_history,
    update_palette_record,
)


class PalettePreviewTests(unittest.TestCase):
    def test_exec_requires_prompt(self) -> None:
        action = action_by_id("run.exec")
        self.assertIsNotNone(action)

        preview = build_palette_preview(action, PaletteContext(prompt_chars=0))

        self.assertFalse(preview.ready)
        self.assertIn("prompt", preview.requirements)

    def test_exec_preview_redacts_prompt_command(self) -> None:
        action = action_by_id("run.exec")
        self.assertIsNotNone(action)

        preview = build_palette_preview(
            action,
            PaletteContext(prompt_chars=32),
            ["/usr/bin/codex", "exec", "[prompt redacted]"],
            prompt_redacted=True,
        )

        self.assertTrue(preview.ready)
        self.assertIn("[prompt redacted]", preview.command_text)
        self.assertNotIn("real user prompt", preview.command_text)

    def test_navigation_is_ready_without_project(self) -> None:
        action = action_by_id("page.quality")
        self.assertIsNotNone(action)

        preview = build_palette_preview(action, PaletteContext(project_exists=False))

        self.assertTrue(preview.ready)
        self.assertEqual(preview.surface, "Navigation")

    def test_prompt_use_requires_selected_choice(self) -> None:
        action = action_by_id("prompt.use")
        self.assertIsNotNone(action)

        preview = build_palette_preview(action, PaletteContext(selected_prompt_choice=False))

        self.assertFalse(preview.ready)
        self.assertIn("selected prompt choice", preview.requirements)

    def test_launch_actions_report_command_risk(self) -> None:
        action = action_by_id("run.max")
        self.assertIsNotNone(action)

        preview = build_palette_preview(action, PaletteContext(project_exists=True))

        self.assertEqual(preview.risk, "launches command")
        self.assertEqual(preview.surface, "Embedded terminal")

    def test_history_records_last_result_per_action(self) -> None:
        action = action_by_id("run.max")
        self.assertIsNotNone(action)
        preview = build_palette_preview(action, PaletteContext(project_exists=True), ["codex", "[prompt redacted]"], prompt_redacted=True)

        records, first = record_palette_event([], action, preview, phase="queued", detail="Queued", timestamp=10)
        records, second = record_palette_event(records, action, preview, phase="dispatched", detail="Dispatched", timestamp=20)

        self.assertEqual(len(records), 1)
        self.assertEqual(second.count, first.count + 1)
        self.assertEqual(records[0].phase, "dispatched")
        self.assertIn("[prompt redacted]", records[0].command_preview)

    def test_history_update_preserves_count(self) -> None:
        action = action_by_id("quality.run")
        self.assertIsNotNone(action)

        records, record = record_palette_event([], action, None, phase="queued", detail="Queued", timestamp=10)
        records, updated = update_palette_record(records, record.action_id, phase="passed", detail="Quality passed", timestamp=30)

        self.assertIsNotNone(updated)
        self.assertEqual(records[0].count, 1)
        self.assertEqual(records[0].phase, "passed")
        self.assertEqual(records[0].updated, 30)

    def test_history_round_trips_json(self) -> None:
        action = action_by_id("page.quality")
        self.assertIsNotNone(action)
        records, _record = record_palette_event([], action, None, phase="opened", detail="Opened Quality", timestamp=99)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "palette-history.json"
            save_palette_history(path, records)
            loaded = load_palette_history(path)

        self.assertEqual(loaded[0].action_id, "page.quality")
        self.assertEqual(loaded[0].phase, "opened")

    def test_history_detail_and_log_are_concrete(self) -> None:
        action = action_by_id("run.max")
        self.assertIsNotNone(action)
        records, record = record_palette_event([], action, None, phase="dispatched", detail="Ran", timestamp=42)

        self.assertIn("Run Max", palette_history_detail(record))
        self.assertIn("Codex Control Palette History", palette_history_log(records))


if __name__ == "__main__":
    unittest.main()
