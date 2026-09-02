#!/usr/bin/env bash
# Abre o clone Radmin VPN (Linux), auto-reparando a pilha antes.
SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
VENV="$RADMIN_VENV"

echo "Preparando a pilha Radmin…"
if ! "$SELF/preflight.sh"; then
  # UI grafica de erro se o preflight falhar e houver display
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    "$VENV/bin/python" - <<'PY' 2>/dev/null || true
from PySide6.QtWidgets import QApplication, QMessageBox
import sys
app=QApplication(sys.argv)
QMessageBox.critical(None,"Radmin VPN (Linux)",
  "Não consegui preparar a pilha.\n\nRode no terminal para ver o passo que falhou:\n  ~/Documents/radmin-linux/preflight.sh")
PY
  fi
  exit 1
fi
exec "$VENV/bin/python" "$SELF/app/main.py" "$@"
