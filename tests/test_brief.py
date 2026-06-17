import unittest
from dataclasses import dataclass

from codex_brief import build_operator_brief
from codex_project import ProjectSnapshot


@dataclass(frozen=True)
class MiniPreflight:
    status: str
    score: int
    blocks: int = 0
    warnings: int = 0
    notes: int = 0

    def summary(self) -> str:
        return f"{self.status} at {self.score}"


@dataclass(frozen=True)
class MiniRecord:
    status: str


def snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(
        path="/tmp/codex-gui",
        root="/tmp/codex-gui",
        name="codex-gui",
        is_git=True,
        branch="main",
        dirty=1,
        untracked=2,
        stack=("Python", "GTK"),
        commands=(),
        recommendation="Build with validation commands ready.",
    )


class OperatorBriefTests(unittest.TestCase):
    def test_recommends_prepare_when_no_autopilot_package_exists(self) -> None:
        brief = build_operator_brief(
            project="/tmp/codex-gui",
            profile="maximum-power",
            mode="maximum-power + live",
            health={"version": "0.140.0", "auth": "auth is configured"},
            snapshot=snapshot(),
            preflight=MiniPreflight("ready", 96),
            sessions=[],
            autopilot_records=[],
            command_runs=[],
            agent_runs=[],
            receipts=[],
        )
        self.assertEqual(brief.next_action, "Prepare Autopilot")
        self.assertEqual(brief.title, "codex-gui command deck")
        self.assertTrue(any(signal.title == "Autopilot" and signal.value == "none" for signal in brief.signals))

    def test_blocked_preflight_takes_priority(self) -> None:
        brief = build_operator_brief(
            project="/tmp/codex-gui",
            profile="none",
            mode="config default",
            health={"version": "0.140.0", "auth": "unknown"},
            snapshot=None,
            preflight=MiniPreflight("blocked", 20, blocks=2),
            sessions=[object()],
            autopilot_records=[MiniRecord("prepared")],
            command_runs=[MiniRecord("done")],
            agent_runs=[],
            receipts=[],
        )
        self.assertEqual(brief.next_action, "Open Preflight")
        self.assertEqual(brief.readiness_status, "blocked")


if __name__ == "__main__":
    unittest.main()
