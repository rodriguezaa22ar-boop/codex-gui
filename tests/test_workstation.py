import unittest

from codex_workstation import (
    action_feedback,
    layout_from_config,
    layout_to_config,
    layout_with_pane,
    layout_with_window,
    pane_position,
)


class WorkstationLayoutTests(unittest.TestCase):
    def test_layout_defaults_to_maximized_workstation(self) -> None:
        layout = layout_from_config({})

        self.assertEqual(layout.window_width, 1600)
        self.assertEqual(layout.window_height, 980)
        self.assertTrue(layout.start_maximized)
        self.assertEqual(pane_position(layout, "workbench", 0), 980)

    def test_layout_clamps_bad_config_values(self) -> None:
        layout = layout_from_config({
            "layout": {
                "window_width": 80,
                "window_height": 9000,
                "start_maximized": "false",
                "panes": {"workbench": 20, "palette": 9000},
            }
        })

        self.assertEqual(layout.window_width, 1100)
        self.assertEqual(layout.window_height, 1800)
        self.assertFalse(layout.start_maximized)
        self.assertEqual(pane_position(layout, "workbench", 0), 720)
        self.assertEqual(pane_position(layout, "palette", 0), 900)

    def test_maximized_layout_uses_stable_fallback_size(self) -> None:
        layout = layout_from_config({
            "layout": {
                "window_width": 2200,
                "window_height": 1640,
                "start_maximized": True,
            }
        })

        self.assertEqual(layout.window_width, 1600)
        self.assertEqual(layout.window_height, 980)
        self.assertTrue(layout.start_maximized)

    def test_layout_round_trips_to_config(self) -> None:
        layout = layout_with_pane(layout_from_config({}), "quality", 640)
        stored = layout_to_config(layout)
        restored = layout_from_config({"layout": stored})

        self.assertEqual(pane_position(restored, "quality", 0), 640)

    def test_window_update_keeps_safe_bounds(self) -> None:
        layout = layout_with_window(layout_from_config({}), 9000, 200, False)

        self.assertEqual(layout.window_width, 2600)
        self.assertEqual(layout.window_height, 720)
        self.assertFalse(layout.start_maximized)


class ActionFeedbackTests(unittest.TestCase):
    def test_feedback_is_concise(self) -> None:
        feedback = action_feedback("quality.run", "Run Quality Gate", "Quality", "dispatched")

        self.assertEqual(feedback.headline(), "Dispatched: Run Quality Gate")
        self.assertEqual(feedback.compact(), "Run Quality Gate | Quality | dispatched")


if __name__ == "__main__":
    unittest.main()
