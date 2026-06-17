import tempfile
import subprocess
import unittest
from pathlib import Path

from codex_agents import (
    build_agent_plan,
    collect_agent_results,
    execution_id,
    execution_paths,
    lane_apply_script,
    lane_diff_script,
    lane_merge_script,
    load_agent_runs,
    new_execution_record,
    plan_markdown,
    prepare_worktree_script,
    record_from_plan,
    remove_agent_run,
    save_agent_runs,
    slugify,
    tail_text,
    update_execution_record,
    upsert_agent_run,
)


def run(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)


class AgentPlanningTests(unittest.TestCase):
    def test_slugify_keeps_safe_branch_parts(self) -> None:
        self.assertEqual(slugify("Best Possible UI!"), "best-possible-ui")
        self.assertEqual(slugify(""), "agent")

    def test_non_git_plan_uses_shared_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_agent_plan(tmp, "ship it", "Stack: Python", run_id="run one")
            self.assertFalse(plan.is_git)
            self.assertEqual(len(plan.lanes), 5)
            self.assertTrue(all(not lane.uses_worktree for lane in plan.lanes))
            self.assertTrue(all(lane.workdir == tmp for lane in plan.lanes))
            self.assertIn("shared project", " ".join(plan.notes))
            self.assertIn("ship it", plan.lanes[0].prompt)

    def test_git_plan_creates_isolated_worktree_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app"
            root.mkdir()
            plan = build_agent_plan(str(root), "build", is_git=True, git_root=str(root), run_id="run42")
            builder = next(lane for lane in plan.lanes if lane.slug == "builder")
            self.assertTrue(builder.uses_worktree)
            self.assertEqual(builder.branch, "codex/run42/builder")
            self.assertEqual(Path(builder.workdir).name, "app-agent-run42-builder")

    def test_prepare_worktree_script_handles_existing_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            plan = build_agent_plan(str(root), "build", is_git=True, git_root=str(root), run_id="x")
            script = prepare_worktree_script(plan.lanes[0], plan.root)
            self.assertIn("git -C", script)
            self.assertIn("show-ref --verify", script)
            self.assertIn("worktree add", script)
            self.assertIn("cd --", script)

    def test_plan_markdown_lists_lanes(self) -> None:
        plan = build_agent_plan("/tmp/project", "polish", run_id="x")
        text = plan_markdown(plan)
        self.assertIn("# Codex Agent Plan x", text)
        self.assertIn("Architect", text)
        self.assertIn("Verifier", text)

    def test_collect_results_reports_missing_non_git_lane(self) -> None:
        plan = build_agent_plan("/tmp/missing-codex-lane", "build", run_id="x")
        results = collect_agent_results(plan)
        self.assertEqual(results[0].status, "missing")
        self.assertFalse(results[0].can_apply)

    def test_collect_results_reports_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app"
            root.mkdir()
            run(["git", "init"], root)
            run(["git", "config", "user.email", "codex@example.test"], root)
            run(["git", "config", "user.name", "Codex Test"], root)
            (root / "app.py").write_text("print('one')\n", encoding="utf-8")
            run(["git", "add", "app.py"], root)
            run(["git", "commit", "-m", "initial"], root)

            plan = build_agent_plan(str(root), "build", is_git=True, git_root=str(root), run_id="x")
            lane = plan.lanes[0]
            run(["bash", "-lc", prepare_worktree_script(lane, plan.root)])
            Path(lane.workdir, "app.py").write_text("print('two')\n", encoding="utf-8")

            result = collect_agent_results(plan)[0]
            self.assertEqual(result.status, "changed")
            self.assertEqual(result.tracked, 1)
            self.assertTrue(result.can_apply)
            self.assertTrue(result.can_merge)
            self.assertTrue(any("app.py" in line for line in result.diff_stat))

    def test_lane_scripts_are_actionable(self) -> None:
        plan = build_agent_plan("/tmp/project", "build", is_git=True, git_root="/tmp/project", run_id="x")
        lane = plan.lanes[0]
        self.assertIn("git status --short --branch", lane_diff_script(lane))
        self.assertIn("git -C", lane_apply_script(lane, plan.root))
        self.assertIn("merge --no-ff", lane_merge_script(lane, plan.root))

    def test_agent_run_records_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-runs.json"
            plan = build_agent_plan("/tmp/project", "make it premium", run_id="run-a")
            record = record_from_plan(plan, status="planned", artifacts=("shot.png",))
            save_agent_runs(path, [record])
            loaded = load_agent_runs(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, "run-a")
            self.assertEqual(loaded[0].plan.lanes[0].title, "Architect")
            self.assertEqual(loaded[0].artifacts, ("shot.png",))

    def test_upsert_and_remove_agent_run_records(self) -> None:
        first = record_from_plan(build_agent_plan("/tmp/one", "one", run_id="one"))
        second = record_from_plan(build_agent_plan("/tmp/two", "two", run_id="two"))
        records = upsert_agent_run([], first)
        records = upsert_agent_run(records, second)
        updated = record_from_plan(second.plan, status="refreshed", existing=second)
        records = upsert_agent_run(records, updated)
        self.assertEqual(len(records), 2)
        self.assertEqual(next(record for record in records if record.id == "two").status, "refreshed")
        self.assertEqual(remove_agent_run(records, "one")[0].id, "two")

    def test_execution_records_have_stable_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_agent_plan("/tmp/project", "run", run_id="run 1")
            lane = plan.lanes[0]
            log_path, final_path = execution_paths(Path(tmp), plan.run_id, lane.slug)
            self.assertEqual(execution_id(plan.run_id, lane.slug), "run-1-architect")
            self.assertEqual(log_path.name, "architect.jsonl")
            self.assertEqual(final_path.name, "architect.final.txt")
            record = new_execution_record(Path(tmp), plan.run_id, lane, ["codex", "exec", "prompt"])
            self.assertEqual(record.status, "queued")
            self.assertEqual(record.command[0], "codex")
            updated = update_execution_record(record, status="done", exit_code=0)
            self.assertEqual(updated.status, "done")
            self.assertEqual(updated.exit_code, 0)

    def test_tail_text_reads_end_of_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.txt"
            path.write_text("0123456789", encoding="utf-8")
            self.assertEqual(tail_text(path, limit=4), "6789")
            self.assertEqual(tail_text(Path(tmp) / "missing.txt"), "")


if __name__ == "__main__":
    unittest.main()
