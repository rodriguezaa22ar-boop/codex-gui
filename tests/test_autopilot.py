import json
import stat
import tempfile
import subprocess
import unittest
from pathlib import Path

from codex_autopilot import (
    build_autopilot_plan,
    load_autopilot_records,
    remove_autopilot_record,
    save_autopilot_records,
    update_autopilot_record,
    upsert_autopilot_record,
    write_autopilot_artifacts,
)
from codex_mission import MissionBlueprint, MissionPhase


def blueprint() -> MissionBlueprint:
    return MissionBlueprint(
        headline="Ship polished GTK workstation work",
        objective="Build it.",
        status="ready",
        score=100,
        recommended_prompt_id="best-upfront",
        recommended_prompt_title="Best Upfront",
        recommended_action="interactive",
        recommended_profile="maximum-power",
        recommended_web="live",
        phases=(MissionPhase("Execute", "Run Codex.", "ready"),),
        agents=("Builder",),
        validation=("python3 -m unittest",),
        risks=(),
    )


class AutopilotPlanTests(unittest.TestCase):
    def test_autopilot_plan_runs_codex_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_autopilot_plan(
                blueprint=blueprint(),
                project=tmp,
                prompt="Build the best possible GUI.",
                codex_bin="/usr/bin/codex",
                common_args=["-p", "maximum-power", "-C", tmp, "--search"],
                skip_git=True,
                artifacts_root=Path(tmp) / "artifacts",
                validation_commands=("python3 -m unittest discover -s tests",),
                timestamp=123,
            )
        text = plan.detail_text()
        self.assertIn("Maximum Codex exec", text)
        self.assertIn("--output-last-message", text)
        self.assertIn("--skip-git-repo-check", text)
        self.assertIn("python3 -m unittest discover -s tests", text)
        self.assertIn("codex-events.jsonl", plan.script())

    def test_prompt_is_shell_quoted_in_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_autopilot_plan(
                blueprint=blueprint(),
                project=tmp,
                prompt="quote ' this && do not split",
                codex_bin="/usr/bin/codex",
                common_args=["-p", "maximum-power"],
                skip_git=False,
                artifacts_root=Path(tmp) / "artifacts",
                validation_commands=(),
                timestamp=123,
            )
        script = plan.script()
        self.assertIn("/usr/bin/codex", script)
        self.assertIn("do not split", script)
        parsed = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True, check=False)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertNotIn("--skip-git-repo-check", script)

    def test_write_autopilot_artifacts_creates_replay_package(self) -> None:
        prompt = "Build the best possible GUI."
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_autopilot_plan(
                blueprint=blueprint(),
                project=tmp,
                prompt=prompt,
                codex_bin="/usr/bin/codex",
                common_args=["-p", "maximum-power"],
                skip_git=True,
                artifacts_root=Path(tmp) / "artifacts",
                validation_commands=("python3 -m unittest discover -s tests",),
                timestamp=123,
            )
            record = write_autopilot_artifacts(
                plan,
                blueprint_text="# Blueprint\n\nShip it.",
                prompt=prompt,
                status="prepared",
            )
            script = Path(record.script_path)
            blueprint_path = Path(record.blueprint_path)
            manifest = Path(record.manifest_path)

            self.assertTrue(script.exists())
            self.assertTrue(blueprint_path.exists())
            self.assertTrue(manifest.exists())
            self.assertEqual(Path(record.log_path), Path(record.artifacts_dir) / "autopilot.log")
            self.assertEqual(stat.S_IMODE(script.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(blueprint_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
            self.assertIn("#!/usr/bin/env bash", script.read_text(encoding="utf-8"))
            self.assertIn("Autopilot Plan", blueprint_path.read_text(encoding="utf-8"))
            self.assertIn("log=", manifest.read_text(encoding="utf-8"))
            self.assertIn("metadata_record_raw_prompt=false", manifest.read_text(encoding="utf-8"))
            self.assertNotEqual(record.prompt_hash, "")
            self.assertNotEqual(record.main_command_hash, "")

    def test_save_load_upsert_remove_records_are_metadata_only(self) -> None:
        prompt = "secret-ish prompt text that must not be in the record json"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autopilot-runs.json"
            plan = build_autopilot_plan(
                blueprint=blueprint(),
                project=tmp,
                prompt=prompt,
                codex_bin="/usr/bin/codex",
                common_args=["-p", "maximum-power"],
                skip_git=True,
                artifacts_root=Path(tmp) / "artifacts",
                validation_commands=(),
                timestamp=123,
            )
            record = write_autopilot_artifacts(plan, blueprint_text="Blueprint", prompt=prompt)
            records = upsert_autopilot_record([], record)
            save_autopilot_records(path, records)

            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            self.assertEqual(len(data), 1)
            self.assertNotIn(prompt, text)
            self.assertNotIn("Build polished GTK workstation work", text)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            loaded = load_autopilot_records(path)
            self.assertEqual([item.id for item in loaded], [record.id])
            running = update_autopilot_record(loaded[0], status="running", pid=4242, started=1234)
            save_autopilot_records(path, upsert_autopilot_record(loaded, running))
            loaded_running = load_autopilot_records(path)[0]
            self.assertEqual(loaded_running.status, "running")
            self.assertEqual(loaded_running.pid, 4242)
            self.assertEqual(loaded_running.started, 1234)
            removed = remove_autopilot_record(loaded, record.id)
            self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
