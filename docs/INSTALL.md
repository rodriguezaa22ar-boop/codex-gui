# Install Codex Control

Codex Control is a local Linux workstation for the Codex CLI. It is designed
for a real terminal-backed Codex workflow, not a hosted chat replacement.

## Requirements

- Python 3.11 or newer
- GTK 4 and PyGObject
- Codex CLI available as `codex`
- A terminal fallback such as Konsole, GNOME Console, GNOME Terminal, or xterm
- Git, if you want project intelligence, mesh sync, and public repo workflows
- Python packaging build tooling for local installs: `setuptools>=68` and
  `wheel`

On Fedora/KDE-style systems, the GTK/PyGObject package names are typically in
the `gtk4` and `python3-gobject` family. On Debian/Ubuntu-style systems, look
for `gir1.2-gtk-4.0`, `python3-gi`, and `python3-gi-cairo`.

On NixOS or other Nix-enabled machines:

```bash
nix-shell
python3 -m pytest
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-build-isolation .
```

The bundled shell includes `pip`, `pytest`, `setuptools`, and `wheel`, so it
can validate tests and local installs even when a worker cannot fetch Python
build dependencies from PyPI. Use a venv inside the shell; Nix Python itself is
externally managed and should not be modified directly with `pip install --user`.

## Install From GitHub

```bash
git clone git@github.com:rodriguezaa22ar-boop/codex-gui.git
cd codex-gui
python3 -m pip install --user .
codex-gui
```

`pip install .` uses the PEP 517 build requirements from `pyproject.toml`.
On a networked host, pip can download `setuptools>=68` and `wheel` if they are
missing. On an offline, restricted, or freshly provisioned worker, install those
packages first through the system package manager, Nix shell, or a local wheel
cache before running the install command.

If `pip` is missing but Python has `ensurepip`:

```bash
python3 -m ensurepip --upgrade --user
python3 -m pip install --user .
```

## Verify

From the clone:

```bash
python3 -m py_compile *.py
python3 -m unittest discover -s tests
codex doctor --summary --ascii
```

The app's Quality Gate also runs a setup readiness check that reports missing
runtime pieces before you rely on the workstation.

## Device Mesh

For other trusted machines, first make each machine a clean clone of the same
repo, then add it on the Mesh page. SSH access, GitHub access, Codex CLI, and
the same project path should all be working before launching team lanes.
