import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from codex_quality import QualityPlan, QualityCheckSpec, build_quality_plan, report_from_dict, report_to_dict, run_quality_plan
from codex_project import ProjectCommand


@dataclass(frozen=True)
class MiniSnapshot:
    root: str
    name: str
    commands: tuple[ProjectCommand, ...]


class QualityGateTests(unittest.TestCase):
    def test_build_quality_plan_uses_snapshot_commands_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = MiniSnapshot(
                root=tmp,
                name="demo",
                commands=(ProjectCommand("unit", "python3 -c 'print(1)'"),),
            )
            plan = build_quality_plan(
                project=tmp,
                snapshot=snapshot,
                codex_bin="codex",
                desktop_file=None,
            )
        self.assertEqual(plan.project, tmp)
        self.assertEqual(plan.checks[0].label, "unit")
        self.assertEqual(plan.checks[1].label, "Codex doctor")

    def test_build_quality_plan_adds_visual_audit_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "codex_visual.py").write_text("", encoding="utf-8")
            snapshot = MiniSnapshot(root=tmp, name="demo", commands=())
            plan = build_quality_plan(
                project=tmp,
                snapshot=snapshot,
                codex_bin="",
                desktop_file=None,
            )

        self.assertEqual([check.label for check in plan.checks], ["Visual system audit"])

    def test_run_quality_plan_scores_failed_required_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = QualityPlan(
                project=tmp,
                checks=(
                    QualityCheckSpec("pass", ("python3", "-c", "print('ok')"), tmp, timeout=10),
                    QualityCheckSpec("fail", ("python3", "-c", "raise SystemExit(7)"), tmp, timeout=10),
                ),
            )
            report = run_quality_plan(plan)
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.score, 50)
        self.assertEqual([check.status for check in report.checks], ["passed", "failed"])

    def test_report_serialization_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = QualityPlan(
                project=tmp,
                checks=(QualityCheckSpec("pass", ("python3", "-c", "print('ok')"), tmp, timeout=10),),
            )
            report = run_quality_plan(plan)
        loaded = report_from_dict(report_to_dict(report))
        self.assertEqual(loaded.status, report.status)
        self.assertEqual(loaded.checks[0].label, "pass")


if __name__ == "__main__":
    unittest.main()
