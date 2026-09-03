#!/usr/bin/env bash
# Opens the Radmin VPN (Linux) clone, auto-repairing the stack first.
SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
VENV="$RADMIN_VENV"

echo "Preparing the Radmin stack…"
if ! "$SELF/preflight.sh" --light -q; then
  # graphical error UI if preflight fails and there is a display
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    "$VENV/bin/python" - <<'PY' 2>/dev/null || true
from PySide6.QtWidgets import QApplication, QMessageBox
import sys
app=QApplication(sys.argv)
QMessageBox.critical(None,"Radmin VPN (Linux)",
  "Could not prepare the stack.\n\nRun it in a terminal to see which step failed:\n  ~/Documents/radmin-linux/preflight.sh")
PY
  fi
  exit 1
fi
# runs at low I/O priority: even the heavy dump (~200MB) never stalls the
# desktop. nice/ionice if available; otherwise runs normally.
NICE=""; command -v nice >/dev/null && NICE="nice -n 5"
IONICE=""; command -v ionice >/dev/null && IONICE="ionice -c2 -n6"
exec $NICE $IONICE "$VENV/bin/python" "$SELF/app/main.py" "$@"
