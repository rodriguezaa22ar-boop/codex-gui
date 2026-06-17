import unittest
from dataclasses import dataclass

from codex_roadmap import build_roadmap


@dataclass(frozen=True)
class Command:
    label: str
    command: str


@dataclass(frozen=True)
class Snapshot:
    name: str = "codex-gui"
    root: str = "/tmp/codex-gui"
    is_git: bool = False
    stack: tuple[str, ...] = ("Python", "GTK")
    commands: tuple[Command, ...] = (Command("tests", "python3 -m unittest discover -s tests"),)
    recommendation: str = "Build with validation commands ready."


@dataclass(frozen=True)
class Quality:
    status: str = "passed"
    score: int = 100

    def summary(self) -> str:
        return "100/100 | 5/5 passed | 0 failed"


@dataclass(frozen=True)
class Context:
    status: str = "ready"
    score: int = 100

    def summary(self) -> str:
        return "100/100 | next brief ready"


@dataclass(frozen=True)
class Preflight:
    status: str = "ready"
    score: int = 92


@dataclass(frozen=True)
class Mission:
    headline: str = "Ship polished GTK workstation work in codex-gui"
    status: str = "ready"
    score: int = 100
    validation: tuple[str, ...] = ("python3 -m unittest discover -s tests",)
    risks: tuple[str, ...] = ("No Git repository detected.",)


class RoadmapTests(unittest.TestCase):
    def test_builds_ordered_next_milestone(self) -> None:
        roadmap = build_roadmap(
            project="/tmp/codex-gui",
            prompt="Proceed with the next milestone.",
            snapshot=Snapshot(),
            preflight=Preflight(),
            quality=Quality(),
            context=Context(),
            mission=Mission(),
        )

        next_item = roadmap.next_milestone()

        self.assertIsNotNone(next_item)
        self.assertEqual(next_item.status, "next")
        self.assertGreaterEqual(roadmap.score, 80)
        self.assertIn("codex-gui", roadmap.title)

    def test_next_prompt_is_actionable(self) -> None:
        roadmap = build_roadmap(
            project="/tmp/codex-gui",
            prompt="Keep improving.",
            snapshot=Snapshot(),
            quality=Quality(),
            context=Context(),
            mission=Mission(),
        )

        prompt = roadmap.next_prompt()

        self.assertIn("Use $best-upfront-codex.", prompt)
        self.assertIn("Milestone:", prompt)
        self.assertIn("Validation:", prompt)

    def test_failed_quality_prioritizes_repair(self) -> None:
        failed = Quality(status="failed", score=60)
        roadmap = build_roadmap(
            project="/tmp/codex-gui",
            prompt="Continue.",
            snapshot=Snapshot(),
            quality=failed,
        )

        self.assertEqual(roadmap.next_milestone().id, "quality-repair")
        self.assertIn("Quality Repair", roadmap.detail_text())

    def test_missing_snapshot_still_produces_milestones(self) -> None:
        roadmap = build_roadmap(project="/tmp/new-project", prompt="")

        self.assertGreaterEqual(len(roadmap.milestones), 3)
        self.assertIn("new-project", roadmap.title)


if __name__ == "__main__":
    unittest.main()
