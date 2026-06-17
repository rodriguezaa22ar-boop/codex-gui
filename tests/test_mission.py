import tempfile
import unittest
from pathlib import Path

from codex_agents import build_agent_plan
from codex_mission import build_mission_blueprint
from codex_preflight import build_preflight_report
from codex_project import ProjectCommand, ProjectSnapshot
from codex_prompting import enhance_prompt


def snapshot(path: str, *, is_git: bool = True, commands: tuple[ProjectCommand, ...] = (ProjectCommand("test", "python3 -m unittest"),)) -> ProjectSnapshot:
    return ProjectSnapshot(
        path=path,
        root=path,
        name=Path(path).name,
        is_git=is_git,
        stack=("Python", "GTK"),
        commands=commands,
        recommendation="Build with validation commands ready.",
    )


class MissionBlueprintTests(unittest.TestCase):
    def test_blueprint_synthesizes_prompt_agents_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt = "Create the best possible Codex GUI mission control experience."
            snap = snapshot(tmp)
            variants = enhance_prompt(prompt, snap.summary())
            preflight = build_preflight_report(
                project=tmp,
                prompt=prompt,
                action="interactive",
                profile="maximum-power",
                model="gpt-5.5",
                reasoning="xhigh",
                sandbox="danger-full-access",
                approval="never",
                web="live",
                skip_git=True,
                receipt_auto=False,
                codex_bin="/usr/bin/codex",
                codex_ready=True,
                auth_summary="auth is configured",
                terminal_available=True,
                embedded_terminal=True,
                atlas_ready=False,
                available_profiles=("maximum-power",),
                snapshot=snap,
            )
            plan = build_agent_plan(tmp, prompt, snap.summary(), is_git=True, git_root=tmp, run_id="mission")
            blueprint = build_mission_blueprint(
                prompt=prompt,
                variants=variants,
                snapshot=snap,
                preflight=preflight,
                agent_plan=plan,
            )
        self.assertEqual(blueprint.status, "ready")
        self.assertGreaterEqual(blueprint.score, 90)
        self.assertIn(blueprint.recommended_prompt_title, {"Product Polish", "Best Upfront"})
        self.assertGreaterEqual(len(blueprint.agents), 5)
        self.assertIn("python3 -m unittest", blueprint.detail_text())

    def test_blocked_preflight_moves_blocker_to_first_phase(self) -> None:
        prompt = "Run it."
        variants = enhance_prompt(prompt)
        preflight = build_preflight_report(
            project="/tmp/definitely-missing-mission-project",
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
            codex_bin="/missing/codex",
            codex_ready=False,
            auth_summary="auth is configured",
            terminal_available=False,
            embedded_terminal=False,
            atlas_ready=False,
            snapshot=None,
        )
        blueprint = build_mission_blueprint(
            prompt=prompt,
            variants=variants,
            snapshot=None,
            preflight=preflight,
            agent_plan=None,
        )
        self.assertEqual(blueprint.status, "blocked")
        self.assertEqual(blueprint.phases[0].title, "Fix Preflight")
        self.assertIn("Clear launch blockers", blueprint.headline)

    def test_missing_validation_is_a_mission_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snap = snapshot(tmp, is_git=False, commands=())
            preflight = build_preflight_report(
                project=tmp,
                prompt="Improve the app.",
                action="interactive",
                profile="maximum-power",
                model="gpt-5.5",
                reasoning="xhigh",
                sandbox="danger-full-access",
                approval="never",
                web="live",
                skip_git=True,
                receipt_auto=False,
                codex_bin="/usr/bin/codex",
                codex_ready=True,
                auth_summary="auth is configured",
                terminal_available=True,
                embedded_terminal=True,
                atlas_ready=False,
                available_profiles=("maximum-power",),
                snapshot=snap,
            )
            blueprint = build_mission_blueprint(
                prompt="Improve the app.",
                variants=enhance_prompt("Improve the app.", snap.summary()),
                snapshot=snap,
                preflight=preflight,
                agent_plan=build_agent_plan(tmp, "Improve the app.", snap.summary(), is_git=False, run_id="shared"),
            )
        self.assertTrue(any("No validation command" in risk for risk in blueprint.risks))
        self.assertTrue(any("No Git repository" in risk for risk in blueprint.risks))


if __name__ == "__main__":
    unittest.main()
