#!/usr/bin/env bash
# Runs the headless VM (production). Low I/O priority so it never stalls the desktop.
# Parameterized by the central config (env.sh). RDP and VNC via localhost.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# find env.sh (at the install root)
for c in "$HERE/../env.sh" "$HERE/env.sh"; do [[ -f "$c" ]] && source "$c" && break; done
: "${RADMIN_VMDIR:=$HERE}"
: "${RADMIN_TAP:=tapradmin}"
: "${RADMIN_HOST:=192.168.137.1}"
DISK="$RADMIN_VMDIR/bench.qcow2"
# Small footprint on purpose (1 GB / 1 CPU) so the VM never hogs the host.
# Override with RADMIN_VM_RAM / RADMIN_VM_SMP if a peer's Windows needs more.
RAM="${VM_RAM:-${RADMIN_VM_RAM:-1024}}"; SMP="${VM_SMP:-${RADMIN_VM_SMP:-1}}"
VNC_PORT="${VM_VNC:-3}"; RDP_PORT="${VM_RDP:-13391}"; RADMIN_PORT="${VM_RADMIN:-14899}"
[[ -f "$DISK" ]] || { echo "image not found: $DISK"; exit 1; }

# 2nd NIC on the isolated tap, if it exists (host<->VM)
TAPARGS=()
if ip link show "$RADMIN_TAP" >/dev/null 2>&1; then
  TAPARGS=(-netdev tap,id=n1,ifname="$RADMIN_TAP",script=no,downscript=no \
           -device e1000e,netdev=n1,mac=52:54:00:26:00:02)
fi
echo ">> VM headless: ${RAM}MB / ${SMP} cores | RDP $RDP_PORT | VNC 590$VNC_PORT"

exec nice -n 5 ionice -c2 -n6 qemu-system-x86_64 \
  -name radmin-vm -machine q35,accel=kvm -cpu host -smp "$SMP" -m "$RAM" \
  -drive file="$DISK",if=none,id=hd0,format=qcow2,cache=writeback \
  -device ich9-ahci,id=ahci -device ide-hd,drive=hd0,bus=ahci.0 \
  -boot order=c -device VGA,vgamem_mb=32 \
  -netdev user,id=n0,hostfwd=tcp:127.0.0.1:"$RDP_PORT"-:3389,hostfwd=tcp:127.0.0.1:"$RADMIN_PORT"-:4899 \
  -device e1000e,netdev=n0 \
  "${TAPARGS[@]}" \
  -rtc base=localtime -usb -device usb-tablet \
  -display none -vnc 127.0.0.1:"$VNC_PORT" \
  -pidfile "$RADMIN_VMDIR/qemu.pid" -monitor unix:"$RADMIN_VMDIR/monitor.sock",server,nowait
