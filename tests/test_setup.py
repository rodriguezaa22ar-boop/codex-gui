import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from codex_setup import SetupCheck, SetupReport, _desktop_check, build_setup_report


class SetupReportTests(unittest.TestCase):
    def test_summary_counts_blockers_and_warnings(self) -> None:
        report = SetupReport(
            status="blocked",
            score=42,
            checks=(
                SetupCheck("python", "Python", "ok", "ok"),
                SetupCheck("codex", "Codex", "block", "missing"),
                SetupCheck("terminal", "Terminal", "warn", "missing"),
            ),
        )

        self.assertEqual(report.blocks, 1)
        self.assertEqual(report.warnings, 1)
        self.assertIn("Setup blocked", report.summary())
        self.assertIn("Fix: repair", SetupReport("review", 80, (SetupCheck("x", "X", "warn", "d", "repair"),)).detail_text())

    def test_build_setup_report_scores_ready_public_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project.scripts]\ncodex-gui = 'codex_gui:main'\n", encoding="utf-8")

            def fake_run(args, cwd=None, timeout=10):
                command = tuple(args)
                if command[:4] == ("git", "-C", str(root), "rev-parse"):
                    return type("Result", (), {"returncode": 0, "stdout": "true\n", "stderr": ""})()
                if command[:4] == ("git", "-C", str(root), "remote"):
                    return type("Result", (), {"returncode": 0, "stdout": "git@github.com:owner/repo.git\n", "stderr": ""})()
                return type("Result", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()

            with patch("codex_setup._run", fake_run), patch("codex_setup._is_executable", return_value=True):
                report = build_setup_report(project=str(root), codex_bin="codex")

        self.assertEqual(report.blocks, 0)
        self.assertTrue(any(check.id == "packaging" and check.status == "ok" for check in report.checks))
        self.assertTrue(any(check.id == "project" and check.status == "ok" for check in report.checks))

    def test_missing_project_blocks(self) -> None:
        with patch("codex_setup._gtk_check", return_value=SetupCheck("gtk", "GTK", "ok", "ok")):
            report = build_setup_report(
                project="/tmp/definitely-missing-codex-control-project",
                codex_bin="missing-codex",
            )

        self.assertGreaterEqual(report.blocks, 1)
        self.assertEqual(report.status, "blocked")

    def test_codex_check_uses_expanded_binary_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex = root / "codex"
            codex.write_text("#!/bin/sh\nprintf 'codex-cli test\\n'\n", encoding="utf-8")
            codex.chmod(0o755)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project.scripts]\ncodex-gui = 'codex_gui:main'\n", encoding="utf-8")

            with patch("codex_setup._gtk_check", return_value=SetupCheck("gtk", "GTK", "ok", "ok")):
                report = build_setup_report(project=str(root), codex_bin=str(codex))

        codex_check = next(check for check in report.checks if check.id == "codex")
        self.assertEqual(codex_check.status, "ok")
        self.assertIn("codex-cli test", codex_check.detail)

    def test_launcher_check_reports_ok_when_entrypoint_imports_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project.scripts]\ncodex-gui = 'codex_launcher:main'\n",
                encoding="utf-8",
            )
            home = Path(tmp) / "home"
            script = home / ".local" / "bin" / "codex-gui"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text("#!/usr/bin/env python3\nfrom codex_launcher import main\n", encoding="utf-8")
            script.chmod(0o755)

            def fake_run(args, cwd=None, timeout=10):
                command = tuple(args)
                if command[:2] == (sys.executable, "-c"):
                    if "import codex_launcher" in command[2]:
                        return type("Result", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()
                if command[:4] == ("git", "-C", str(root), "rev-parse"):
                    return type("Result", (), {"returncode": 0, "stdout": "true\n", "stderr": ""})()
                if command[:4] == ("git", "-C", str(root), "remote"):
                    return type("Result", (), {"returncode": 0, "stdout": "git@github.com:owner/repo.git\n", "stderr": ""})()
                if command == (str(sys.executable), "-c", "import codex_launcher; import codex_gui; print('ok')"):
                    return type("Result", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()
                return type("Result", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()

            with (
                patch("codex_setup._run", fake_run),
                patch("codex_setup.Path.home", return_value=home),
                patch("codex_setup._is_executable", return_value=True),
            ):
                report = build_setup_report(project=str(root), codex_bin="codex")

            launcher_check = next(check for check in report.checks if check.id == "launcher")
            self.assertEqual(launcher_check.status, "ok")
            self.assertIn("imports and resolves", launcher_check.detail)

    def test_launcher_check_warns_when_modules_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project.scripts]\ncodex-gui = 'codex_launcher:main'\n",
                encoding="utf-8",
            )
            home = Path(tmp) / "home"
            script = home / ".local" / "bin" / "codex-gui"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            script.chmod(0o755)

            def fake_run(args, cwd=None, timeout=10):
                command = tuple(args)
                if command[:4] == ("git", "-C", str(root), "rev-parse"):
                    return type("Result", (), {"returncode": 0, "stdout": "true\n", "stderr": ""})()
                if command[:4] == ("git", "-C", str(root), "remote"):
                    return type("Result", (), {"returncode": 0, "stdout": "git@github.com:owner/repo.git\n", "stderr": ""})()
                if command == (str(sys.executable), "-c", "import codex_launcher; import codex_gui; print('ok')"):
                    return type("Result", (), {"returncode": 2, "stdout": "", "stderr": "ModuleNotFoundError: No module named codex_launcher\n"})()
                return type("Result", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()

            with (
                patch("codex_setup._run", fake_run),
                patch("codex_setup.Path.home", return_value=home),
                patch("codex_setup._is_executable", return_value=True),
            ):
                report = build_setup_report(project=str(root), codex_bin="codex")

            launcher_check = next(check for check in report.checks if check.id == "launcher")
            self.assertEqual(launcher_check.status, "warn")
            self.assertIn("python3 -m pip install", launcher_check.fix)

    def test_desktop_check_missing_file_reports_repair_script(self) -> None:
        desktop_file = Path("/tmp") / "does-not-exist-codex-gui.desktop"
        if desktop_file.exists():
            self.fail(f"{desktop_file} unexpectedly exists")

        check = _desktop_check(desktop_file)
        self.assertEqual(check.id, "desktop")
        self.assertEqual(check.status, "note")
        self.assertIn("install-codex-gui-desktop-entry.sh", check.fix)


if __name__ == "__main__":
    unittest.main()
