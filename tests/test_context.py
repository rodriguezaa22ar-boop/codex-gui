import unittest
from dataclasses import dataclass

from codex_context import build_context_packet


@dataclass(frozen=True)
class Command:
    label: str
    command: str


@dataclass(frozen=True)
class Snapshot:
    root: str = "/tmp/codex-gui"
    name: str = "codex-gui"
    is_git: bool = True
    branch: str = "main"
    dirty: int = 1
    untracked: int = 2
    changed_files: tuple[str, ...] = ("codex_gui.py",)
    recent_commits: tuple[str, ...] = ("abc123 Ship UI",)
    stack: tuple[str, ...] = ("Python", "GTK")
    commands: tuple[Command, ...] = (Command("tests", "python3 -m unittest discover -s tests"),)
    top_files: tuple[str, ...] = ("codex_gui.py", "tests/")
    recommendation: str = "Build with validation commands ready."
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    title: str
    status: str
    detail: str


@dataclass(frozen=True)
class Preflight:
    status: str = "ready"
    score: int = 96
    checks: tuple[Check, ...] = (Check("Prompt", "ok", "strong prompt"),)

    def summary(self) -> str:
        return "Ready: launch path is clean"


@dataclass(frozen=True)
class Quality:
    generated: int = 123
    project: str = "/tmp/codex-gui"
    status: str = "passed"
    score: int = 100
    checks: tuple[Check, ...] = (Check("tests", "passed", "57 tests"),)

    def summary(self) -> str:
        return "100/100 | 1/1 passed | 0 failed"


@dataclass(frozen=True)
class Mission:
    headline: str = "Ship polished GTK workstation work in codex-gui"
    objective: str = "Make Codex Control premium."
    status: str = "ready"
    score: int = 99
    recommended_prompt_title: str = "Product Polish"
    recommended_action: str = "interactive"
    recommended_profile: str = "maximum-power"
    agents: tuple[str, ...] = ("Builder: implement feature",)
    validation: tuple[str, ...] = ("python3 -m unittest discover -s tests",)
    risks: tuple[str, ...] = ("No Git repository detected.",)


class ContextPacketTests(unittest.TestCase):
    def test_packet_includes_project_quality_and_mission(self) -> None:
        packet = build_context_packet(
            project="/tmp/codex-gui",
            prompt="Create a premium context packet.",
            mode="maximum-power + live",
            snapshot=Snapshot(),
            preflight=Preflight(),
            quality=Quality(),
            mission=Mission(),
        )

        text = packet.markdown()

        self.assertIn("codex-gui", packet.title)
        self.assertIn("Create a premium context packet.", text)
        self.assertIn("100/100", text)
        self.assertIn("Ship polished GTK workstation work", text)
        self.assertGreaterEqual(packet.score, 90)

    def test_launch_prompt_wraps_original_prompt_and_context(self) -> None:
        packet = build_context_packet(
            project="/tmp/codex-gui",
            prompt="Improve launch behavior.",
            mode="maximum-power",
            snapshot=Snapshot(),
            preflight=Preflight(),
            quality=Quality(),
            mission=Mission(),
        )

        prompt = packet.launch_prompt()

        self.assertIn("Use $best-upfront-codex.", prompt)
        self.assertIn("Primary objective:", prompt)
        self.assertIn("Improve launch behavior.", prompt)
        self.assertIn("# Codex Launch Context Packet", prompt)

    def test_missing_snapshot_still_builds_actionable_packet(self) -> None:
        packet = build_context_packet(
            project="/tmp/new-project",
            prompt="Map this project first.",
            mode="config default",
        )

        text = packet.markdown()

        self.assertIn("Project scan is still pending", text)
        self.assertIn("No completed quality report", text)
        self.assertEqual(packet.status, "ready")

    def test_obvious_secrets_are_redacted(self) -> None:
        packet = build_context_packet(
            project="/tmp/codex-gui",
            prompt="Use token=super-secret-value to test",
            mode="maximum-power",
        )

        self.assertNotIn("super-secret-value", packet.launch_prompt())
        self.assertIn("[redacted]", packet.launch_prompt())


if __name__ == "__main__":
    unittest.main()
