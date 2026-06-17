import tempfile
import unittest
from pathlib import Path

from codex_preflight import build_preflight_report
from codex_project import ProjectSnapshot


def snapshot(*, is_git: bool = True, dirty: int = 0, untracked: int = 0, commands: tuple = ("test",), stack: tuple[str, ...] = ("Python",)) -> ProjectSnapshot:
    return ProjectSnapshot(
        path="/tmp/app",
        root="/tmp/app",
        name="app",
        is_git=is_git,
        dirty=dirty,
        untracked=untracked,
        commands=commands,
        stack=stack,
    )


class PreflightTests(unittest.TestCase):
    def test_maximum_power_is_ready_with_notes_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_preflight_report(
                project=tmp,
                prompt="Build the best practical version and validate it.",
                action="interactive",
                profile="maximum-power",
                model="gpt-5.5",
                reasoning="xhigh",
                sandbox="danger-full-access",
                approval="never",
                web="live",
                skip_git=True,
                receipt_auto=True,
                codex_bin="/usr/bin/codex",
                codex_ready=True,
                auth_summary="auth is configured",
                terminal_available=True,
                embedded_terminal=True,
                atlas_ready=True,
                available_profiles=("maximum-power",),
                snapshot=snapshot(),
            )
        self.assertEqual(report.status, "ready")
        self.assertGreater(report.score, 80)
        self.assertEqual(report.blocks, 0)
        self.assertIn("High-trust", report.detail_text())

    def test_missing_codex_or_project_blocks_launch(self) -> None:
        report = build_preflight_report(
            project="/tmp/definitely-not-a-codex-preflight-project",
            prompt="build",
            action="interactive",
            profile="none",
            model="config",
            reasoning="config",
            sandbox="config",
            approval="config",
            web="config",
            skip_git=True,
            receipt_auto=False,
            codex_bin="/missing/codex",
            codex_ready=False,
            auth_summary="auth is configured",
            terminal_available=True,
            embedded_terminal=True,
            atlas_ready=False,
            snapshot=None,
        )
        self.assertEqual(report.status, "blocked")
        self.assertGreaterEqual(report.blocks, 2)

    def test_exec_without_prompt_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_preflight_report(
                project=tmp,
                prompt="",
                action="exec",
                profile="none",
                model="config",
                reasoning="config",
                sandbox="workspace-write",
                approval="on-request",
                web="cached",
                skip_git=True,
                receipt_auto=False,
                codex_bin="/usr/bin/codex",
                codex_ready=True,
                auth_summary="auth is configured",
                terminal_available=False,
                embedded_terminal=False,
                atlas_ready=False,
                snapshot=snapshot(),
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("`codex exec` needs", report.detail_text())

    def test_missing_profile_and_receipt_engine_are_review_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_preflight_report(
                project=tmp,
                prompt="Review this project and report risks.",
                action="review",
                profile="missing-profile",
                model="config",
                reasoning="high",
                sandbox="read-only",
                approval="on-request",
                web="cached",
                skip_git=True,
                receipt_auto=True,
                codex_bin="/usr/bin/codex",
                codex_ready=True,
                auth_summary="auth is configured",
                terminal_available=True,
                embedded_terminal=False,
                atlas_ready=False,
                available_profiles=("maximum-power",),
                snapshot=snapshot(is_git=False, commands=(), stack=()),
            )
        self.assertEqual(report.status, "review")
        self.assertEqual(report.warnings, 2)

    def test_non_git_exec_without_skip_git_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_preflight_report(
                project=tmp,
                prompt="Run this bounded command.",
                action="exec",
                profile="none",
                model="config",
                reasoning="medium",
                sandbox="workspace-write",
                approval="on-request",
                web="cached",
                skip_git=False,
                receipt_auto=False,
                codex_bin="/usr/bin/codex",
                codex_ready=True,
                auth_summary="auth is configured",
                terminal_available=False,
                embedded_terminal=False,
                atlas_ready=False,
                snapshot=snapshot(is_git=False),
            )
        self.assertEqual(report.status, "blocked")
        self.assertIn("No git gate", report.detail_text())


if __name__ == "__main__":
    unittest.main()
