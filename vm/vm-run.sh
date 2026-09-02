#!/usr/bin/env bash
# Roda a VM headless (produção). Prioridade de I/O baixa p/ nunca travar o desktop.
# Parametrizado pelo config central (env.sh). RDP e VNC via localhost.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# acha o env.sh (na raiz da instalacao)
for c in "$HERE/../env.sh" "$HERE/env.sh"; do [[ -f "$c" ]] && source "$c" && break; done
: "${RADMIN_VMDIR:=$HERE}"
: "${RADMIN_TAP:=tapradmin}"
: "${RADMIN_HOST:=192.168.137.1}"
DISK="$RADMIN_VMDIR/bench.qcow2"
RAM="${VM_RAM:-1024}"; SMP="${VM_SMP:-2}"
VNC_PORT="${VM_VNC:-3}"; RDP_PORT="${VM_RDP:-13391}"; RADMIN_PORT="${VM_RADMIN:-14899}"
[[ -f "$DISK" ]] || { echo "imagem nao encontrada: $DISK"; exit 1; }

# 2a NIC na tap isolada, se existir (host<->VM)
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
