import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import codex_launch_agents

LAUNCH_AGENTS_PATH = Path(__file__).resolve().parents[1] / "scripts" / "launch_agents.py"


def _load_launch_agents_module():
    spec = importlib.util.spec_from_file_location("launch_agents_script", LAUNCH_AGENTS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load launch_agents script module")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    if not isinstance(module, ModuleType):
        raise RuntimeError("Invalid launch_agents module object")
    spec.loader.exec_module(module)
    return module


try:
    launch_agents = _load_launch_agents_module()
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    if exc.name == "paramiko":
        launch_agents = None
    else:
        raise
except RuntimeError:
    launch_agents = None


@unittest.skipIf(launch_agents is None, "paramiko is required for launch_agents test coverage")
class LaunchAgentsTests(unittest.TestCase):
    def _make_fake_ssh(self, command_responses):
        class FakeChannel:
            def recv_exit_status(self) -> int:
                return 0

        class FakeStream:
            def __init__(self, data: str = "") -> None:
                self._data = data.encode("utf-8")
                self.channel = FakeChannel()

            def read(self) -> bytes:
                return self._data

        class FakeSFTP:
            def __init__(self) -> None:
                self.last_put_source: str | None = None
                self.last_put_destination: str | None = None

            def put(self, source: str, destination: str) -> None:
                self.last_put_source = source
                self.last_put_destination = destination

            def close(self) -> None:
                return None

        class FakeSSH:
            def __init__(self) -> None:
                self.sftp = FakeSFTP()
                self.commands: list[str] = []

            def open_sftp(self) -> FakeSFTP:
                return self.sftp

            def exec_command(self, command: str):
                self.commands.append(command)
                for matcher, value in command_responses:
                    if callable(matcher):
                        if matcher(command):
                            return None, FakeStream(value), FakeStream("")
                    elif matcher in command:
                        return None, FakeStream(value), FakeStream("")
                return None, FakeStream("1234"), FakeStream("")

            def close(self) -> None:
                return None

        return FakeSSH()

    def _make_temp(self, suffix: str, content: str) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return tmp.name

    def test_build_devices_loads_json(self) -> None:
        payload = json.dumps(
            [
                {
                    "host": "127.0.0.1",
                    "user": "tester",
                    "role": "Planner",
                    "profile": "safe-explore",
                }
            ]
        )
        path = self._make_temp(".json", payload)
        devices = launch_agents.build_devices(path)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].host, "127.0.0.1")
        self.assertEqual(devices[0].port, 22)

    def test_build_devices_loads_yaml(self) -> None:
        payload = """
        - host: agent.local
          user: root
          role: Implementer
          profile: maximum-power
          key: ~/.ssh/id_ed25519
          port: 2222
        """
        path = self._make_temp(".yaml", payload)
        devices = launch_agents.build_devices(path)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].role, "Implementer")
        self.assertEqual(devices[0].port, 2222)

    def test_with_retry_retries_until_success(self) -> None:
        attempts = 0

        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise socket.timeout("temporary")
            return "ok"

        result = launch_agents.with_retry(
            flaky,
            max_retries=3,
            backoff=0.0,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 3)

    def test_with_retry_raises_after_limit(self) -> None:
        attempts = 0

        def always_fail() -> str:
            nonlocal attempts
            attempts += 1
            raise socket.error("still failing")

        with self.assertRaises(socket.error):
            launch_agents.with_retry(
                always_fail,
                max_retries=2,
                backoff=0.0,
            )
        self.assertEqual(attempts, 3)

    def test_collect_results_populates_modified_files_with_mocked_ssh(self) -> None:
        payload = """
        - host: localhost
          user: ao
          role: Planner
          profile: safe-explore
        """
        devices_file = self._make_temp(".yaml", payload)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            prompts_dir = tmp_path / "role_prompts"
            prompts_dir.mkdir()
            (prompts_dir / "planner.md").write_text("test prompt", encoding="utf-8")
            logs_dir = tmp_path / "agent_logs"

            fake_ssh = self._make_fake_ssh([("git status --porcelain", " M changed.py\n?? new.txt\n")])
            captured = []
            with patch.object(launch_agents, "connect", return_value=fake_ssh):
                with patch.object(
                    launch_agents.logging,
                    "info",
                    side_effect=lambda message, *args, **kwargs: captured.append(message),
                ):
                    argv = [
                        "launch_agents.py",
                        "--devices",
                        devices_file,
                        "--prompts-dir",
                        str(prompts_dir),
                        "--logs-dir",
                        str(logs_dir),
                        "--repo-path",
                        str(tmp_path),
                        "--collect-results",
                    ]
                    with patch("sys.argv", argv):
                        launch_agents.main()

            entries = [json.loads(line) for line in captured if line.startswith("{")]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["status"], "started")
            self.assertEqual(entries[0]["host"], "localhost")
            self.assertEqual(entries[0]["role"], "Planner")
            self.assertEqual(entries[0]["modified_files"], ["changed.py", "new.txt"])
            self.assertIn("log", entries[0])

    def test_collect_summary_and_metadata_are_included_with_summarize_results(self) -> None:
        payload = """
        - host: localhost
          user: ao
          role: Planner
          profile: safe-explore
        """
        devices_file = self._make_temp(".yaml", payload)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            prompts_dir = tmp_path / "role_prompts"
            prompts_dir.mkdir()
            (prompts_dir / "planner.md").write_text("test prompt", encoding="utf-8")

            fake_ssh = self._make_fake_ssh(
                [
                    (lambda c: "git status --porcelain" in c, " M changed.py\n"),
                    (
                        lambda c: "git diff --name-status" in c,
                        "A\tadded.py\nM\tmodified.py\nR100\told.txt\trenamed.txt\n",
                    ),
                    (lambda c: "git rev-parse HEAD" in c and "--short" not in c, "11223344556677889900"),
                    (lambda c: "git rev-parse --short HEAD" in c, "1122334"),
                    (lambda c: "git branch --show-current" in c, "main"),
                    (lambda c: "rev-parse --abbrev-ref --symbolic-full-name" in c, "origin/main"),
                    (lambda c: "rev-list --count origin/main..HEAD" in c, "2"),
                    (lambda c: "rev-list --count HEAD..origin/main" in c, "0"),
                ]
            )
            captured = []
            with patch.object(launch_agents, "connect", return_value=fake_ssh):
                with patch.object(
                    launch_agents.logging,
                    "info",
                    side_effect=lambda message, *args, **kwargs: captured.append(message),
                ):
                    argv = [
                        "launch_agents.py",
                        "--devices",
                        devices_file,
                        "--prompts-dir",
                        str(prompts_dir),
                        "--logs-dir",
                        str(tmp_path / "agent_logs"),
                        "--repo-path",
                        str(tmp_path),
                        "--collect-results",
                        "--summarize-results",
                        "--summary-base",
                        "origin/main",
                    ]
                    with patch("sys.argv", argv):
                        launch_agents.main()

            entries = [json.loads(line) for line in captured if line.startswith("{")]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["status"], "started")
            self.assertIn("diff_summary", entries[0])
            self.assertIn("commit", entries[0])
            self.assertEqual(entries[0]["commit"]["head_short"], "1122334")
            self.assertEqual(entries[0]["diff_summary"]["counts"]["added"], 1)
            self.assertEqual(entries[0]["diff_summary"]["counts"]["renamed"], 1)
            self.assertEqual(entries[0]["modified_files"], ["changed.py"])

    def test_failure_result_includes_stage(self) -> None:
        payload = """
        - host: localhost
          user: ao
          role: Planner
          profile: safe-explore
        """
        devices_file = self._make_temp(".yaml", payload)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            prompts_dir = tmp_path / "role_prompts"
            prompts_dir.mkdir()
            logs_dir = tmp_path / "agent_logs"

            fake_ssh = self._make_fake_ssh([])
            captured = []
            with patch.object(launch_agents, "connect", return_value=fake_ssh):
                with patch.object(
                    launch_agents.logging,
                    "info",
                    side_effect=lambda message, *args, **kwargs: captured.append(message),
                ):
                    argv = [
                        "launch_agents.py",
                        "--devices",
                        devices_file,
                        "--prompts-dir",
                        str(prompts_dir),
                        "--logs-dir",
                        str(logs_dir),
                        "--repo-path",
                        str(tmp_path),
                    ]
                    with patch("sys.argv", argv):
                        launch_agents.main()

            entries = [json.loads(line) for line in captured if line.startswith("{")]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["status"], "failed")
            self.assertEqual(entries[0]["failure_stage"], "launch_agent")
            self.assertIn("error", entries[0])

    def test_collect_diff_summary_parse(self) -> None:
        with patch.object(
            launch_agents,
            "run_remote",
            return_value="A\tadded.py\nM\tmodified.py\nR100\told.txt\tnew.txt\n",
        ):
            summary = launch_agents.collect_diff_summary(object(), "/tmp/repo", "origin/main")
            self.assertEqual(summary["counts"]["added"], 1)
            self.assertEqual(summary["counts"]["renamed"], 1)
            self.assertIn("new.txt", summary["files"]["renamed"])
            self.assertEqual(summary["files"]["renamed"], ["new.txt"])

    def test_collect_commit_metadata_handles_missing_upstream(self) -> None:
        def fake_run_remote(_ssh, command: str) -> str:
            if "git rev-parse --short HEAD" in command:
                return "1122334"
            if "git rev-parse HEAD" in command:
                return "11223344556677889900"
            if "git branch --show-current" in command:
                return "main"
            if "@{u}" in command:
                raise RuntimeError("no upstream")
            return "0"

        with patch.object(launch_agents, "run_remote", side_effect=fake_run_remote):
            metadata = launch_agents.collect_commit_metadata(object(), "/tmp/repo")
            self.assertEqual(metadata["head"], "11223344556677889900")
            self.assertEqual(metadata["head_short"], "1122334")
            self.assertEqual(metadata["branch"], "main")
            self.assertIsNone(metadata["upstream"])
            self.assertEqual(metadata["ahead"], 0)


class LaunchAgentsEntrypointTests(unittest.TestCase):
    def test_codex_launch_agents_delegates_to_script(self) -> None:
        with patch.object(codex_launch_agents.runpy, "run_path") as run_path:
            codex_launch_agents.main()
            expected_script = Path(codex_launch_agents.__file__).resolve().parent / "scripts" / "launch_agents.py"
            self.assertEqual(run_path.call_count, 1)
            self.assertEqual(run_path.call_args.args[0], str(expected_script))
            self.assertEqual(run_path.call_args.kwargs["run_name"], "__main__")


if __name__ == "__main__":
    unittest.main()
