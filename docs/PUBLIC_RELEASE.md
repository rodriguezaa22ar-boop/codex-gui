# Public Release Checklist

Use this before tagging or sharing Codex Control with other users.

- `README.md` explains what the app is, how to install it, and how to run it.
- `LICENSE` is present.
- `pyproject.toml` installs the `codex-gui` launcher.
- `python3 -m unittest discover -s tests` passes.
- `python3 -m py_compile *.py` passes.
- `codex doctor --summary --ascii` passes on the release machine.
- The app launches with `codex-gui` from a graphical desktop session.
- Headless SSH verification does not treat a missing display / GTK init failure
  as an app regression.
- The first Workbench screen renders without overlapping text.
- Mesh devices are documented as trusted-user SSH targets only.
- No passwords, tokens, API keys, sudo codes, raw prompts, or terminal logs are
  committed.
