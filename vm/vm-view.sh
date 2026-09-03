#!/usr/bin/env bash
# VM VNC console (debugging only; the normal user uses the UI).
HERE="$(cd "$(dirname "$0")" && pwd)"
for c in "$HERE/../env.sh" "$HERE/env.sh"; do [[ -f "$c" ]] && source "$c" && break; done
exec vncviewer 127.0.0.1:"590${VM_VNC:-3}"
