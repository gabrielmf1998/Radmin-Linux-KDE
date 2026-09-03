#!/usr/bin/env bash
# ============================================================
#  build-vm.sh - produces the distributable base image of Radmin-Linux.
#
#  Two modes:
#   --clean IMG.qcow2   starts from an ALREADY-ready image (with Windows+Radmin+agent)
#                       and CLEANS it for distribution: leaves the current network,
#                       resets the Alias, deletes logs/roster/dump, compresses. (fast)
#   --from-scratch      provisions from zero: installs unattended POSReady7,
#                       Radmin, ICS and the agent. (long; requires the ISOs)
#
#  The point of --clean: the VM here is logged into your friends' network.
#  Before copying/distributing, THIS is the step that takes you out of their network.
# ============================================================
set -uo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
say(){ printf '\033[1;36m>>\033[0m %s\n' "$*"; }
ok(){  printf '   \033[1;32m[ok]\033[0m %s\n' "$*"; }
die(){ printf '   \033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

MODE="${1:-}"; shift || true

clean_running_vm() {
  # run the cleanup steps INSIDE the VM (powered on), via WMI
  say "Cleaning the Radmin state in the VM (leaving the network, resetting identity)"
  local ps
  ps=$(cat <<'PSEOF'
$ErrorActionPreference="SilentlyContinue"
# 1. leave ALL networks (remove the associations)
$net="HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0\Networks"
if(Test-Path $net){ Get-ChildItem $net | ForEach-Object { Remove-Item $_.PSPath -Recurse -Force } }
# 2. reset identity (Alias, RID cache) for the next owner to set their own
$b="HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0"
Set-ItemProperty $b -Name Alias -Value "RADMIN-LINUX" -Type String
Set-ItemProperty $b -Name PowerOn -Value 1 -Type DWord
# 3. clean agent logs/dumps and chat
Remove-Item C:\radmin-agent\*.log -Force -EA SilentlyContinue
Remove-Item C:\radmin-agent\*.dmp -Force -EA SilentlyContinue
Remove-Item "C:\Program Files (x86)\Radmin VPN\CHATLOGS\*" -Recurse -Force -EA SilentlyContinue
Restart-Service RvControlSvc -Force
Write-Output "<<<CLEANOK>>>"
PSEOF
)
  local b64; b64=$(printf '%s' "$ps" | iconv -t UTF-16LE | base64 -w0)
  "$RADMIN_VENV/bin/python" "$RADMIN_VENV/bin/wmiexec.py" -shell-type powershell \
    "$RADMIN_TARGET" "powershell -EncodedCommand $b64" 2>&1 | grep -q CLEANOK \
    && ok "network removed and identity reset" || die "failed to clean via WMI"
}

case "$MODE" in
  --clean)
    IMG="${1:-$RADMIN_VMDIR/bench.qcow2}"
    [[ -f "$IMG" ]] || die "image not found: $IMG"
    # the VM must be POWERED ON to clean via WMI
    if ! "$RADMIN_VENV/bin/python" "$SELF/app/vmctl.py" status 2>/dev/null | grep -q running; then
      die "turn the VM on first (--clean operates on the running VM)"
    fi
    clean_running_vm
    say "Powering the VM off to freeze the clean image"
    "$RADMIN_VENV/bin/python" "$SELF/app/vmctl.py" off >/dev/null
    sleep 3
    OUT="${RADMIN_DIST:-$SELF/dist}/radmin-linux-base.qcow2"
    mkdir -p "$(dirname "$OUT")"
    say "Compressing the image (qemu-img -c) for distribution"
    qemu-img convert -O qcow2 -c "$IMG" "$OUT" || die "failed to compress"
    SZ=$(du -h "$OUT" | cut -f1)
    ok "clean base image: $OUT ($SZ)"
    if command -v zstd >/dev/null; then
      zstd -q -19 --long=27 -f "$OUT" -o "$OUT.zst" && ok "compressed: $OUT.zst ($(du -h "$OUT.zst"|cut -f1))"
    fi
    say "Ready to distribute. Install with: ./install.sh $OUT.zst"
    ;;
  --from-scratch)
    # provision the VM from ZERO: unattended POSReady7 -> Radmin -> ICS -> agent.
    WINISO="${1:-${RADMIN_WIN_ISO:-}}"
    [[ -f "$WINISO" ]] || die "pass the Windows ISO: ./build-vm.sh --from-scratch POSReady7.iso"
    command -v qemu-img >/dev/null || die "qemu-img missing"
    command -v xorriso  >/dev/null || die "xorriso missing (install xorriso)"
    for t in mkfs.vfat mcopy; do command -v $t >/dev/null || die "$t missing (install mtools/dosfstools)"; done

    BDIR="${RADMIN_BUILD:-$SELF/build}"
    # CRITICAL PROTECTION: the VM disk grows to ~10GB during install.
    # If BDIR is on tmpfs (/tmp is RAM on most distros), that EXHAUSTS the RAM
    # and FREEZES the machine. Refuse tmpfs.
    mkdir -p "$BDIR"
    FSTYPE=$(stat -f -c %T "$BDIR" 2>/dev/null)
    if [[ "$FSTYPE" == "tmpfs" || "$FSTYPE" == "ramfs" ]]; then
      die "BDIR ($BDIR) is on $FSTYPE (RAM). That would freeze the machine.
    Use a real disk: RADMIN_BUILD=/path/on/disk ./build-vm.sh --from-scratch ..."
    fi
    AVAIL_GB=$(df -BG --output=avail "$BDIR" 2>/dev/null | tail -1 | tr -dc '0-9')
    [[ -n "$AVAIL_GB" && "$AVAIL_GB" -lt 15 ]] && die "low space in $BDIR (${AVAIL_GB}G); needs ~15G"
    rm -rf "$BDIR"; mkdir -p "$BDIR/media/agent"
    say "1/6  Downloading Radmin VPN (onto the provisioning media)"
    RURL="https://download.radmin-vpn.com/download/files/Radmin_VPN_2.0.4899.9.exe"
    curl -fsSL "$RURL" -o "$BDIR/media/Radmin_VPN.exe" || die "failed to download Radmin"

    say "2/6  Building the media (setup-guest + agent)"
    cp "$SELF/provision/setup-guest.ps1" "$BDIR/media/"
    cp "$SELF/provision/SetupComplete.cmd" "$BDIR/media/"
    cp "$SELF/agent/"*.ps1 "$BDIR/media/agent/"
    xorriso -as mkisofs -J -r -V PROVISION -o "$BDIR/provision.iso" "$BDIR/media" 2>/dev/null || die "ISO failed"

    say "3/6  Answer floppy (autounattend)"
    dd if=/dev/zero of="$BDIR/unattend.img" bs=1024 count=1440 status=none
    mkfs.vfat -n UNATTEND "$BDIR/unattend.img" >/dev/null
    MTOOLS_SKIP_CHECK=1 mcopy -i "$BDIR/unattend.img" "$SELF/provision/autounattend.xml" ::autounattend.xml

    say "4/6  Creating the disk (24G sparse)"
    DISK="$BDIR/bench.qcow2"
    qemu-img create -f qcow2 "$DISK" 24G >/dev/null

    say "5/6  Installing + provisioning (headless, ~15 min). Watch: vncviewer 127.0.0.1:5905"
    # 2 NICs: NAT (internet for Radmin) + the isolated one with the MAC ICS expects
    # low CPU and I/O priority: the build must never stall the desktop
    nice -n 15 ionice -c2 -n7 \
    qemu-system-x86_64 -name radmin-build -machine q35,accel=kvm -cpu host -smp 2 -m 3072 \
      -drive file="$DISK",if=none,id=hd0,format=qcow2,cache=writeback \
      -device ich9-ahci,id=ahci -device ide-hd,drive=hd0,bus=ahci.0 \
      -drive file="$WINISO",if=none,id=cd0,media=cdrom,readonly=on -device ide-cd,drive=cd0,bus=ahci.1 \
      -drive file="$BDIR/provision.iso",if=none,id=cd1,media=cdrom,readonly=on -device ide-cd,drive=cd1,bus=ahci.2 \
      -drive file="$BDIR/unattend.img",if=floppy,format=raw \
      -boot order=dc,menu=off -device VGA,vgamem_mb=32 \
      -netdev user,id=n0 -device e1000e,netdev=n0 \
      -netdev user,id=n1 -device e1000e,netdev=n1,mac=52:54:00:26:00:02 \
      -rtc base=localtime -usb -device usb-tablet \
      -display none -vnc 127.0.0.1:5 \
      -pidfile "$BDIR/build.pid" -monitor unix:"$BDIR/mon.sock",server,nowait &

    # wait for QEMU to create the pidfile (the & starts it async)
    for i in $(seq 1 15); do [[ -s "$BDIR/build.pid" ]] && break; sleep 1; done
    BPID="$(cat "$BDIR/build.pid" 2>/dev/null)"
    [[ -n "$BPID" ]] && kill -0 "$BPID" 2>/dev/null || die "the build VM did not come up (see VNC 5905)"
    # setup-guest powers the VM off when done -> we wait for the process to die.
    say "   waiting (the guest powers itself off when finished; up to ~35 min)…"
    for i in $(seq 1 105); do   # 105*20s = 35 min
      sleep 20
      kill -0 "$BPID" 2>/dev/null || { say "   guest finished and powered off"; break; }
      [[ $((i % 15)) -eq 0 ]] && say "   ... still installing ($((i*20/60)) min)"
    done

    say "6/6  Finalizing the image"
    # shut down gracefully
    printf 'system_powerdown\n' | timeout 10 socat -,ignoreeof UNIX-CONNECT:"$BDIR/mon.sock" >/dev/null 2>&1
    for i in $(seq 1 30); do kill -0 "$(cat "$BDIR/build.pid" 2>/dev/null)" 2>/dev/null || break; sleep 2; done
    kill "$(cat "$BDIR/build.pid" 2>/dev/null)" 2>/dev/null || true

    OUT="${RADMIN_DIST:-$SELF/dist}/radmin-linux-base.qcow2"
    mkdir -p "$(dirname "$OUT")"
    qemu-img convert -O qcow2 -c "$DISK" "$OUT" && ok "base image: $OUT ($(du -h "$OUT"|cut -f1))"
    command -v zstd >/dev/null && zstd -q -19 -f "$OUT" -o "$OUT.zst" && ok "compressed: $OUT.zst ($(du -h "$OUT.zst"|cut -f1))"
    say "Install with: ./install.sh $OUT.zst"
    ;;
  *)
    cat <<USAGE
usage:
  ./build-vm.sh --clean [IMG.qcow2]   cleans the VM (leaves the network, resets identity,
                                      compresses) -> dist/radmin-linux-base.qcow2[.zst]
  ./build-vm.sh --from-scratch        provisions from zero

IMPORTANT: --clean is the step that takes you out of your friends' network before copying.
USAGE
    ;;
esac
