import importlib.util
import json
import socket
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
