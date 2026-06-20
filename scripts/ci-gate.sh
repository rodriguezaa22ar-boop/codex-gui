#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$(pwd)}"
cd "$PROJECT_ROOT"

echo "::group::Python compile"
python_files=()
while IFS= read -r -d '' path; do
  python_files+=("$path")
done < <(find . -name '*.py' -type f -print0 | sort -z)

if [ "${#python_files[@]}" -gt 0 ]; then
  python3 -m py_compile "${python_files[@]}"
fi
echo "::endgroup::"

echo "::group::Unittest"
python3 -m unittest discover -s tests
echo "::endgroup::"

echo "::group::Pytest"
if command -v pytest >/dev/null 2>&1; then
  python3 -m pytest -q
else
  echo "pytest is not available; skipping."
fi
echo "::endgroup::"

if command -v codex >/dev/null 2>&1; then
  echo "::group::Codex doctor (optional)"
  codex doctor --summary --ascii || true
  echo "::endgroup::"
else
  echo "Codex CLI not installed; skipping codex doctor."
fi

if command -v desktop-file-validate >/dev/null 2>&1 && [ -x scripts/install-codex-gui-desktop-entry.sh ]; then
  echo "::group::Desktop entry"
  bash scripts/install-codex-gui-desktop-entry.sh >/dev/null
  desktop-file-validate "$HOME/.local/share/applications/codex-gui.desktop" || true
  echo "::endgroup::"
fi
