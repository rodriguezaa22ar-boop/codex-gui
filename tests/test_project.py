import tempfile
import unittest
from pathlib import Path

from codex_project import detect_commands, detect_stack, inspect_project


class ProjectIntelligenceTests(unittest.TestCase):
    def test_detects_python_gtk_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "codex_gui.py").write_text("print('x')\n", encoding="utf-8")
            stack = detect_stack(root)
            self.assertIn("Python", stack)
            self.assertIn("GTK", stack)

    def test_detects_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "tests").mkdir()
            commands = detect_commands(root, ("Python",))
            command_text = [command.command for command in commands]
            self.assertIn("python3 -m unittest discover -s tests", command_text)

    def test_inspect_project_returns_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            snapshot = inspect_project(str(root))
            self.assertEqual(snapshot.root, str(root))
            self.assertIn("Python", snapshot.stack)
            self.assertTrue(snapshot.top_files)


if __name__ == "__main__":
    unittest.main()
