#!/usr/bin/env bash
# Console VNC da VM (só pra depuração; o usuário normal usa a UI).
HERE="$(cd "$(dirname "$0")" && pwd)"
for c in "$HERE/../env.sh" "$HERE/env.sh"; do [[ -f "$c" ]] && source "$c" && break; done
exec vncviewer 127.0.0.1:"590${VM_VNC:-3}"
