import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTests(unittest.TestCase):
    def test_ci_workflow_exists_with_quality_gate(self) -> None:
        ci = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci.exists(), f"missing workflow: {ci}")
        text = ci.read_text(encoding="utf-8")

        self.assertIn("name: CI", text)
        self.assertIn("runs-on: ubuntu-latest", text)
        self.assertIn("strategy:", text)
        self.assertIn("matrix:", text)
        self.assertIn("python-version:", text)
        self.assertIn("bash scripts/ci-gate.sh", text)

    def test_release_workflow_exists_with_publish_path(self) -> None:
        release = ROOT / ".github" / "workflows" / "release.yml"
        self.assertTrue(release.exists(), f"missing workflow: {release}")
        text = release.read_text(encoding="utf-8")

        self.assertIn("name: Release", text)
        self.assertIn("python3 -m build", text)
        self.assertIn("twine upload", text)
        self.assertIn("tags:\n      - \"v*\"", text)

    def test_ci_gate_contains_quality_commands(self) -> None:
        gate = ROOT / "scripts" / "ci-gate.sh"
        self.assertTrue(gate.exists(), f"missing script: {gate}")
        text = gate.read_text(encoding="utf-8")

        self.assertIn("Python compile", text)
        self.assertIn("Unittest", text)
        self.assertIn("Pytest", text)
        self.assertIn("codex doctor", text)


if __name__ == "__main__":
    unittest.main()
