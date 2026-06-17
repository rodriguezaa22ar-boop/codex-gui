import json
import unittest

from codex_prompting import enhance_prompt, model_variant_request, parse_model_variants


class PromptEnhancementTests(unittest.TestCase):
    def test_generates_core_choices(self) -> None:
        variants = enhance_prompt("build the best GUI")
        titles = [variant.title for variant in variants]
        self.assertIn("Best Upfront", titles)
        self.assertIn("Use As Written", titles)
        self.assertIn("Product Polish", titles)

    def test_bug_prompt_gets_bug_hunt_choice(self) -> None:
        variants = enhance_prompt("fix crash when opening config")
        titles = [variant.title for variant in variants]
        self.assertIn("Bug Hunt", titles)

    def test_review_variant_sets_review_profile(self) -> None:
        variants = enhance_prompt("review this code")
        review = next(variant for variant in variants if variant.title == "Deep Review")
        self.assertEqual(review.action, "review")
        self.assertEqual(review.profile, "deep-review")

    def test_project_context_is_included(self) -> None:
        variants = enhance_prompt("fix the UI", "Stack: Python, GTK\nValidation commands: python3 -m unittest")
        self.assertIn("Project context:", variants[0].prompt)
        self.assertIn("Python, GTK", variants[0].prompt)

    def test_model_request_contains_json_contract(self) -> None:
        request = model_variant_request("build project mode", "Stack: Python")
        self.assertIn("Return only JSON", request)
        self.assertIn('"variants"', request)
        self.assertIn("Stack: Python", request)

    def test_parse_model_variants_accepts_json(self) -> None:
        payload = {
            "variants": [
                {
                    "title": "Ship It",
                    "summary": "Implement and validate.",
                    "prompt": "Build this end to end.",
                    "action": "interactive",
                    "profile": "maximum-power",
                    "web": "live",
                }
            ]
        }
        variants = parse_model_variants(json.dumps(payload), "raw")
        self.assertEqual(variants[0].title, "Ship It")
        self.assertEqual(variants[0].profile, "maximum-power")

    def test_parse_model_variants_sanitizes_invalid_values(self) -> None:
        text = '{"variants":[{"title":"Odd","summary":"x","prompt":"Do it","action":"delete","profile":"root","web":"internet"}]}'
        variant = parse_model_variants(text, "raw")[0]
        self.assertEqual(variant.action, "interactive")
        self.assertEqual(variant.profile, "maximum-power")
        self.assertEqual(variant.web, "live")

    def test_parse_model_variants_falls_back_on_bad_json(self) -> None:
        variants = parse_model_variants("not json", "fix crash")
        titles = [variant.title for variant in variants]
        self.assertIn("Bug Hunt", titles)


if __name__ == "__main__":
    unittest.main()
