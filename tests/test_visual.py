import unittest

from codex_visual import REQUIRED_SELECTORS, TOKENS, audit_visual_system, visual_system_css, visual_system_summary


class VisualSystemTests(unittest.TestCase):
    def test_visual_css_contains_required_selectors(self) -> None:
        css = visual_system_css()
        for selector in REQUIRED_SELECTORS:
            self.assertIn(selector, css)

    def test_visual_audit_passes_for_overlay(self) -> None:
        audit = audit_visual_system(visual_system_css())

        self.assertTrue(audit.passed, audit.summary())
        self.assertEqual(audit.selectors_missing, ())

    def test_visual_system_uses_multiple_color_roles(self) -> None:
        roles = {token.role for token in TOKENS}

        self.assertGreaterEqual(len(TOKENS), 16)
        self.assertIn("surface", roles)
        self.assertIn("accent", roles)
        self.assertIn("status", roles)
        self.assertIn("text", roles)

    def test_visual_system_avoids_gradient_decoration(self) -> None:
        self.assertNotIn("gradient", visual_system_css().lower())

    def test_summary_is_concrete(self) -> None:
        summary = visual_system_summary()

        self.assertIn("tokens", summary)
        self.assertIn("surfaces", summary)


if __name__ == "__main__":
    unittest.main()
