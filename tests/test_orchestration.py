import unittest
from dataclasses import dataclass

from codex_orchestration import build_launch_package


@dataclass(frozen=True)
class Preflight:
    status: str = "ready"
    score: int = 94

    def summary(self) -> str:
        return "Ready: launch path is clean"


@dataclass(frozen=True)
class Quality:
    status: str = "passed"
    score: int = 100

    def summary(self) -> str:
        return "100/100 | 5/5 passed | 0 failed"


@dataclass(frozen=True)
class Brief:
    status: str = "ready"
    score: int = 98
    label: str = "brief"

    def summary(self) -> str:
        return f"{self.label} ready"


class LaunchPackageTests(unittest.TestCase):
    def test_ready_package_includes_hashes_and_steps(self) -> None:
        package = build_launch_package(
            project="/tmp/codex-gui",
            action="interactive",
            profile="maximum-power",
            surface="embedded",
            command=("codex", "--profile", "maximum-power", "build"),
            prompt="build",
            preflight=Preflight(),
            quality=Quality(),
            context=Brief(label="context"),
            roadmap=Brief(label="roadmap"),
            receipt_auto=True,
            atlas_ready=True,
            embedded_terminal=True,
            recent_runs=2,
            receipts=3,
        )

        self.assertEqual(package.status, "ready")
        self.assertGreaterEqual(package.score, 90)
        self.assertEqual(len(package.command_hash), 64)
        self.assertEqual(len(package.prompt_hash), 64)
        self.assertGreaterEqual(len(package.steps), 6)

    def test_package_redacts_obvious_secrets(self) -> None:
        package = build_launch_package(
            project="/tmp/codex-gui",
            action="interactive",
            profile="maximum-power",
            surface="embedded",
            command=("codex", "token=secret-value", "do work"),
            prompt="token=secret-value",
            embedded_terminal=True,
        )

        detail = package.detail_text()

        self.assertIn("[prompt redacted; see prompt hash]", detail)
        self.assertNotIn("secret-value", detail)
        self.assertIn("Prompt SHA-256", detail)

    def test_package_redacts_prompt_argument_from_preview(self) -> None:
        package = build_launch_package(
            project="/tmp/codex-gui",
            action="interactive",
            profile="maximum-power",
            surface="embedded",
            command=("codex", "private objective body"),
            prompt="private objective body",
            embedded_terminal=True,
        )

        detail = package.detail_text()

        self.assertIn("[prompt redacted; see prompt hash]", detail)
        self.assertNotIn("private objective body", detail)

    def test_blocked_preflight_blocks_package(self) -> None:
        package = build_launch_package(
            project="/tmp/codex-gui",
            action="interactive",
            profile="maximum-power",
            surface="embedded",
            command=("codex", "build"),
            prompt="build",
            preflight=Preflight(status="blocked", score=35),
            embedded_terminal=True,
        )

        self.assertEqual(package.status, "blocked")
        self.assertLess(package.score, 80)

    def test_external_terminal_is_valid_fallback(self) -> None:
        package = build_launch_package(
            project="/tmp/codex-gui",
            action="interactive",
            profile="maximum-power",
            surface="external",
            command=("codex", "build"),
            prompt="build",
            external_terminal=True,
        )

        self.assertNotEqual(package.status, "blocked")

    def test_launch_package_tracks_latest_matching_run(self) -> None:
        package = build_launch_package(
            project="/tmp/codex-gui",
            action="interactive",
            profile="maximum-power",
            surface="embedded",
            command=("codex", "--profile", "maximum-power", "build"),
            prompt="build",
            embedded_terminal=True,
            last_run_id="run-4a2b1c6f-0123",
            last_run_status="done",
            last_run_profile="maximum-power",
            last_run_surface="embedded",
            last_run_created=1_700_000_000,
        )

        detail = package.detail_text()

        self.assertIn("Last matching run: run-4a2", detail)
        self.assertIn("Last run status: done", detail)
        self.assertIn("run run-4a2b", package.steps[6].detail)
        self.assertEqual(package.steps[6].title, "Launch History")
        self.assertIn("ready", package.steps[6].status)


if __name__ == "__main__":
    unittest.main()
