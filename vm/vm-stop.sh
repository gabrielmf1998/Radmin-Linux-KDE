#!/usr/bin/env bash
# Shuts the VM down cleanly (ACPI). Never use pkill -f qemu (it matches its own command).
HERE="$(cd "$(dirname "$0")" && pwd)"
for c in "$HERE/../env.sh" "$HERE/env.sh"; do [[ -f "$c" ]] && source "$c" && break; done
: "${RADMIN_VMDIR:=$HERE}"
P="$RADMIN_VMDIR/qemu.pid"
[[ -f "$P" ]] || { echo "VM is not running"; exit 0; }
PID=$(cat "$P")
printf 'system_powerdown\n' | timeout 10 socat -,ignoreeof UNIX-CONNECT:"$RADMIN_VMDIR/monitor.sock" >/dev/null 2>&1
for i in $(seq 1 60); do kill -0 "$PID" 2>/dev/null || break; sleep 2; done
kill -0 "$PID" 2>/dev/null && kill "$PID" 2>/dev/null
rm -f "$P" "$RADMIN_VMDIR/monitor.sock"
echo "off"
