#!/usr/bin/env bash
set -euo pipefail

DESKTOP_FILE="${DESKTOP_FILE:-$HOME/.local/share/applications/codex-gui.desktop}"

mkdir -p "$(dirname "$DESKTOP_FILE")"

cat <<'EOF' > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Version=1.0
Name=Codex Control
Comment=Linux workstation for Codex CLI
TryExec=codex-gui
Exec=codex-gui
Terminal=false
Categories=GTK;Utility;Development;
Keywords=AI;CLI;Development;Terminal;
MimeType=x-scheme-handler/codex;
StartupNotify=true
Icon=system-run
EOF

chmod 644 "$DESKTOP_FILE"

echo "Installed desktop entry: $DESKTOP_FILE"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$(dirname "$DESKTOP_FILE")" || true
fi
