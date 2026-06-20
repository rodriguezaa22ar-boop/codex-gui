#!/usr/bin/env python3
"""Compatibility wrapper for the multi-device launch agents script."""

from __future__ import annotations

from pathlib import Path
import runpy


def main() -> None:
    script_path = Path(__file__).resolve().parent / "scripts" / "launch_agents.py"
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
