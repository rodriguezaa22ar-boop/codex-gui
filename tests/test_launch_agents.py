import importlib.util
import json
import socket
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import ModuleType

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
                def put(self, source: str, destination: str) -> None:
                    self.last_put_source = source
                    self.last_put_destination = destination

                def close(self) -> None:
                    return None

            class FakeSSH:
                def __init__(self) -> None:
                    self.sftp = FakeSFTP()

                def open_sftp(self) -> FakeSFTP:
                    return self.sftp

                def exec_command(self, command: str) -> tuple[None, FakeStream, FakeStream]:
                    if "git status --porcelain" in command:
                        status = " M changed.py\n?? new.txt\n"
                    else:
                        status = "1234"
                    return None, FakeStream(status), FakeStream("")

                def close(self) -> None:
                    return None

            fake_ssh = FakeSSH()
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


if __name__ == "__main__":
    unittest.main()
