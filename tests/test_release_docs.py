import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocsTests(unittest.TestCase):
    def test_nix_shell_contains_release_validation_tools(self) -> None:
        shell = (ROOT / "shell.nix").read_text(encoding="utf-8")

        for package in (
            "python3Packages.pip",
            "python3Packages.pytest",
            "python3Packages.setuptools",
            "python3Packages.wheel",
        ):
            self.assertIn(package, shell)

    def test_install_docs_use_nix_shell_for_offline_build_validation(self) -> None:
        install = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")

        self.assertIn("python3 -m pytest", install)
        self.assertIn("python3 -m venv --system-site-packages .venv", install)
        self.assertIn(".venv/bin/python -m pip install --no-build-isolation .", install)
        self.assertIn("cannot fetch Python", install)
        self.assertIn("build dependencies from PyPI", install)
        self.assertIn("externally managed", install)


if __name__ == "__main__":
    unittest.main()
