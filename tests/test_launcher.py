import os
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_setup import SetupCheck

import codex_launcher


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ready_report = SimpleNamespace(
            status="ready",
            score=100,
            summary=lambda: "Setup ready",
            detail_text=lambda: "setup ok\n",
            checks=(),
        )

    def test_ensure_repo_on_path_adds_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "project"
            repo.mkdir()
            (repo / "codex_gui.py").write_text("pass\n", encoding="utf-8")

            with patch.dict(os.environ, {"CODEX_GUI_ROOT": str(repo)}):
                original = list(sys.path)
                try:
                    self.assertTrue(codex_launcher._ensure_repo_on_path())
                    self.assertIn(str(repo), sys.path)
                finally:
                    sys.path[:] = original[:]

    def test_ensure_repo_on_path_returns_false_without_visible_repo(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_tmp:
            with (
                patch("codex_launcher.Path.cwd", return_value=Path(cwd_tmp)),
                patch("codex_launcher.Path.home", return_value=Path(cwd_tmp)),
                patch("codex_launcher._repo_candidates", return_value=(Path(cwd_tmp),)),
                patch.dict(os.environ, {"CODEX_GUI_ROOT": "/nonexistent/codex-gui"}),
            ):
                self.assertFalse(codex_launcher._ensure_repo_on_path())

    def test_main_uses_gui_main_result(self) -> None:
        fake_gui = SimpleNamespace(main=lambda: 97)

        with (
            patch("codex_launcher._collect_setup_report", return_value=(Path.home(), self.ready_report)),
            patch.dict("sys.modules", {"codex_gui": fake_gui}),
        ):
            self.assertEqual(codex_launcher.main([]), 97)

    def test_main_raises_helpful_error_when_launch_path_missing(self) -> None:
        with patch("codex_launcher._ensure_repo_on_path", return_value=False):
            with (
                patch("codex_launcher._collect_setup_report", return_value=(Path.home(), self.ready_report)),
                self.assertRaises(ModuleNotFoundError) as exc,
            ):
                codex_launcher.main([])

            text = str(exc.exception)
            self.assertIn("could not locate `codex_gui`", text.lower())

    def test_main_blocks_start_when_smoke_check_fails(self) -> None:
        blocked_report = SimpleNamespace(
            status="review",
            score=80,
            summary=lambda: "Setup review: 1 warning",
            detail_text=lambda: "warn\n",
            checks=(SetupCheck("terminal", "Terminal", "warn", "No terminal", "Install terminal"),),
        )

        fake_gui = SimpleNamespace(main=lambda: 99)

        with (
            patch("codex_launcher._collect_setup_report", return_value=(Path.home(), blocked_report)),
            patch.dict("sys.modules", {"codex_gui": fake_gui}),
            patch("sys.stdout", new=io.StringIO()) as captured,
        ):
            self.assertEqual(codex_launcher.main([]), 1)
            self.assertIn("Codex GUI launch preflight", captured.getvalue())
            self.assertIn("Codex GUI launch blocked", captured.getvalue())

    def test_main_allows_override_when_force_start_is_set(self) -> None:
        blocked_report = SimpleNamespace(
            status="review",
            score=80,
            summary=lambda: "Setup review: 1 warning",
            detail_text=lambda: "warn\n",
            checks=(SetupCheck("terminal", "Terminal", "warn", "No terminal", "Install terminal"),),
        )

        fake_gui = SimpleNamespace(main=lambda: 99)

        with (
            patch("codex_launcher._collect_setup_report", return_value=(Path.home(), blocked_report)),
            patch.dict("sys.modules", {"codex_gui": fake_gui}),
        ):
            self.assertEqual(codex_launcher.main(["--force-start"]), 99)

    def test_smoke_check_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "launcher-smoke.log"
            with (
                patch("codex_launcher._collect_setup_report", return_value=(Path.home(), self.ready_report)),
                patch("codex_launcher._smoke_log_path", return_value=log_path),
                patch.dict("sys.modules", {"codex_gui": SimpleNamespace(main=lambda: 7)}),
            ):
                self.assertEqual(codex_launcher.main(["--force-start"]), 7)

            data = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
            self.assertEqual(data["status"], "ready")

    def test_self_check_runs_setup_report(self) -> None:
        fake_report = SimpleNamespace(
            status="ready",
            detail_text=lambda: "setup ok\n",
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "project"
            repo.mkdir()
            (repo / "codex_gui.py").write_text("pass\n", encoding="utf-8")

            with (
                patch("codex_setup.build_setup_report", return_value=fake_report) as build,
                patch("codex_launcher.Path.home", return_value=Path(tmp)),
                patch("sys.stdout", new=io.StringIO()) as captured,
            ):
                result = codex_launcher.main(["--self-check", "--project", str(repo)])

            self.assertEqual(result, 0)
            self.assertIn(str(repo), str(build.call_args.kwargs["project"]))
            self.assertEqual(build.call_args.kwargs["codex_bin"], "codex")
            self.assertEqual(build.call_args.kwargs["desktop_file"], Path(tmp) / ".local" / "share" / "applications" / "codex-gui.desktop")
            self.assertEqual(build.call_args.kwargs["devices_file"], Path(tmp) / ".config" / "codex-gui" / "devices.json")
            self.assertIn("Codex GUI Self-Check", captured.getvalue())

    def test_self_check_status_code_maps_blocking_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "project"
            repo.mkdir()
            (repo / "codex_gui.py").write_text("pass\n", encoding="utf-8")

            with (
                patch("codex_launcher.Path.home", return_value=Path(tmp)),
                patch("codex_setup.build_setup_report") as build,
            ):
                for status, expected in (("ready", 0), ("review", 1), ("blocked", 2)):
                    def _detail(current_status: str = status) -> str:
                        return f"{current_status}\n"

                    build.return_value = SimpleNamespace(
                        status=status,
                        detail_text=_detail,
                    )
                    with patch("sys.stdout", new=io.StringIO()):
                        self.assertEqual(
                            codex_launcher.main(["--self-check", "--project", str(repo)]),
                            expected,
                        )

    def test_self_check_json_mode_emits_machine_readable_payload(self) -> None:
        fake_report = SimpleNamespace(
            status="ready",
            score=100,
            checks=(SetupCheck("python", "Python", "ok", "ok", ""),),
            summary=lambda: "Setup ready",
            detail_text=lambda: "ignored",
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "project"
            repo.mkdir()
            (repo / "codex_gui.py").write_text("pass\n", encoding="utf-8")

            with (
                patch("codex_launcher.Path.home", return_value=Path(tmp)),
                patch("codex_setup.build_setup_report", return_value=fake_report),
                patch("sys.stdout", new=io.StringIO()) as captured,
            ):
                self.assertEqual(
                    codex_launcher.main([
                        "--self-check",
                        "--project",
                        str(repo),
                        "--json",
                    ]),
                    0,
                )

            payload = json.loads(captured.getvalue().splitlines()[-1])
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["score"], 100)


if __name__ == "__main__":
    unittest.main()
