#!/usr/bin/env bash
# ============================================================
#  install.sh - plug-and-play installer for Radmin-Linux.
#  Sets up the whole stack on a clean target:
#    1. checks KVM (every kernel has it)
#    2. checks/installs system dependencies (qemu, dnsmasq, ...)
#    3. creates the venv (impacket + PySide6)
#    4. installs the code into ~/.local/share/radmin-linux
#    5. imports the VM image
#    6. creates the isolated interface (NM) + DHCP (systemd)
#    7. writes config.env
#    8. creates the .desktop shortcut (the UI does the rest)
#  After this the user just opens "Radmin VPN" from the menu. No VM to touch.
# ============================================================
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
say(){ printf '\033[1;36m>>\033[0m %s\n' "$*"; }
ok(){  printf '   \033[1;32m[ok]\033[0m %s\n' "$*"; }
warn(){ printf '   \033[1;33m[!]\033[0m %s\n' "$*"; }
die(){ printf '   \033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# install target
HOME_DIR="${RADMIN_HOME:-$HOME/.local/share/radmin-linux}"
VMDIR="$HOME_DIR/vm"
VENV="$HOME_DIR/venv"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/radmin-linux"
CONF="$CONF_DIR/config.env"
TAP="${RADMIN_TAP:-tapradmin}"
NMCON="${RADMIN_NMCON:-radmin-bridge}"
TAP_IP="${RADMIN_TAP_IP:-192.168.137.2/24}"
DHCP_SVC="dnsmasq-tapradmin.service"

# the VM image: 1st arg, or a variable, or look next to this script
VM_IMAGE="${1:-${RADMIN_VM_IMAGE:-}}"

# ---------- 1. KVM ----------
say "1/8  Checking KVM"
if [[ ! -e /dev/kvm ]]; then
  warn "/dev/kvm missing. Trying to load the module…"
  if grep -qi 'vmx' /proc/cpuinfo; then MOD=kvm_intel; else MOD=kvm_amd; fi
  pkexec modprobe kvm "$MOD" 2>/dev/null || warn "could not load $MOD (enable VT-x/AMD-V in the BIOS)"
fi
[[ -e /dev/kvm ]] || die "KVM unavailable. Enable virtualization in the BIOS."
if [[ -r /dev/kvm && -w /dev/kvm ]]; then ok "/dev/kvm accessible"
else
  warn "/dev/kvm not permitted; adding you to the kvm group"
  pkexec usermod -aG kvm "$USER" && warn "log out/in for the kvm group to take effect"
fi

# ---------- 2. system dependencies ----------
say "2/8  System dependencies"
# detect the distro family and map package names (they vary a lot)
PM=""; PKG_QEMU=""; PKG_IMG=""; PKG_DNS=""; PKG_NM=""; PKG_SOCAT=""; PKG_VNC=""; PKG_PY=""
if command -v dnf >/dev/null; then
  # Fedora, Nobara, RHEL, ...
  PM="pkexec dnf install -y"
  PKG_QEMU=qemu-system-x86-core; PKG_IMG=qemu-img; PKG_DNS=dnsmasq
  PKG_NM=NetworkManager; PKG_SOCAT=socat; PKG_VNC=tigervnc; PKG_PY="python3 python3-pip"
elif command -v pacman >/dev/null; then
  # Arch, Manjaro, EndeavourOS
  PM="pkexec pacman -S --needed --noconfirm"
  PKG_QEMU=qemu-desktop; PKG_IMG=qemu-img; PKG_DNS=dnsmasq
  PKG_NM=networkmanager; PKG_SOCAT=socat; PKG_VNC=tigervnc; PKG_PY=python
elif command -v apt-get >/dev/null; then
  # Debian, Ubuntu, Mint, Pop!_OS
  PM="pkexec apt-get install -y"
  pkexec apt-get update -qq 2>/dev/null || true
  PKG_QEMU=qemu-system-x86; PKG_IMG=qemu-utils; PKG_DNS=dnsmasq-base
  PKG_NM=network-manager; PKG_SOCAT=socat; PKG_VNC=tigervnc-viewer; PKG_PY="python3 python3-venv python3-pip"
elif command -v zypper >/dev/null; then
  # openSUSE
  PM="pkexec zypper install -y"
  PKG_QEMU=qemu-x86; PKG_IMG=qemu-tools; PKG_DNS=dnsmasq
  PKG_NM=NetworkManager; PKG_SOCAT=socat; PKG_VNC=tigervnc; PKG_PY="python3 python3-pip"
else
  die "package manager not recognized. Install manually: qemu, qemu-img, dnsmasq, NetworkManager, socat, python3"
fi

need=()
command -v qemu-system-x86_64 >/dev/null || need+=($PKG_QEMU)
command -v qemu-img >/dev/null || need+=($PKG_IMG)
command -v dnsmasq  >/dev/null || need+=($PKG_DNS)
command -v nmcli    >/dev/null || need+=($PKG_NM)
command -v socat    >/dev/null || need+=($PKG_SOCAT)
command -v python3  >/dev/null || need+=($PKG_PY)
command -v uv       >/dev/null || warn "uv not found (will use python -m venv)"
if [[ ${#need[@]} -gt 0 ]]; then
  say "   installing (${PM%% *}...): ${need[*]}"
  $PM "${need[@]}" || die "failed to install dependencies"
fi
ok "qemu, dnsmasq, NetworkManager, socat present"

# ---------- 3. venv ----------
say "3/8  Python environment (impacket + PySide6)"
mkdir -p "$HOME_DIR"
if command -v uv >/dev/null; then
  uv venv --python 3.12 "$VENV" >/dev/null 2>&1 || uv venv "$VENV" >/dev/null 2>&1
  VIRTUAL_ENV="$VENV" uv pip install -q impacket PySide6 >/dev/null 2>&1
else
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q impacket PySide6 >/dev/null 2>&1
fi
"$VENV/bin/python" -c "import impacket, PySide6" 2>/dev/null && ok "venv ready" || die "failed to set up the venv"
# make sure wmiexec.py is accessible
if [[ ! -f "$VENV/bin/wmiexec.py" ]]; then
  WM=$("$VENV/bin/python" - <<'PY'
import impacket, os, glob
base=os.path.dirname(os.path.dirname(impacket.__file__))
for p in glob.glob(os.path.join(base,'**','wmiexec.py'),recursive=True):
    print(p); break
PY
)
  [[ -n "$WM" ]] && ln -sf "$WM" "$VENV/bin/wmiexec.py"
fi

# ---------- 4. code ----------
say "4/8  Installing the code"
mkdir -p "$HOME_DIR/app"
cp -r "$SELF/app/"*.py "$HOME_DIR/app/"
cp -r "$SELF/shim" "$SELF/agent" "$HOME_DIR/"
cp "$SELF/env.sh" "$SELF/preflight.sh" "$SELF/radmin-linux.sh" \
   "$SELF/deploy-shim.sh" "$SELF/deploy-agent.sh" "$HOME_DIR/"
chmod +x "$HOME_DIR"/*.sh
ok "code in $HOME_DIR"

# ---------- 5. VM image ----------
say "5/8  VM image"
mkdir -p "$VMDIR"
if [[ -n "$VM_IMAGE" && -f "$VM_IMAGE" ]]; then
  say "   importing $VM_IMAGE (may take a while)…"
  case "$VM_IMAGE" in
    *.qcow2) cp "$VM_IMAGE" "$VMDIR/bench.qcow2" ;;
    *.qcow2.zst) zstd -d -o "$VMDIR/bench.qcow2" "$VM_IMAGE" ;;
    *.qcow2.gz)  gunzip -c "$VM_IMAGE" > "$VMDIR/bench.qcow2" ;;
    *) die "image format not recognized: $VM_IMAGE" ;;
  esac
  ok "image imported"
elif [[ -f "$VMDIR/bench.qcow2" ]]; then
  ok "image already present in $VMDIR"
else
  warn "no VM image. Pass the path: ./install.sh path/bench.qcow2[.zst]"
  warn "or run ./build-vm.sh to build a clean one from scratch."
fi
# VM run scripts (parameterized by the config; run with nice/ionice)
cp "$SELF/vm/vm-run.sh"  "$VMDIR/bench-run.sh"
cp "$SELF/vm/vm-view.sh" "$VMDIR/bench-view.sh"
cp "$SELF/vm/vm-stop.sh" "$VMDIR/bench-stop.sh"
chmod +x "$VMDIR"/bench-*.sh
# env.sh must be reachable from VMDIR (the scripts source ../env.sh)
cp "$SELF/env.sh" "$HOME_DIR/env.sh" 2>/dev/null || true

# ---------- 6. isolated network + DHCP ----------
say "6/8  Isolated interface + DHCP"
if ! nmcli con show "$NMCON" >/dev/null 2>&1; then
  pkexec nmcli con add type tun con-name "$NMCON" ifname "$TAP" mode tap owner "$(id -u)" \
    ipv4.method manual ipv4.addresses "$TAP_IP" ipv4.never-default yes ipv6.method disabled \
    connection.zone trusted connection.autoconnect yes >/dev/null 2>&1
fi
pkexec nmcli con up "$NMCON" >/dev/null 2>&1 || true
ok "interface $TAP ($TAP_IP)"

pkexec bash -c "cat > /etc/systemd/system/$DHCP_SVC <<UNIT
[Unit]
Description=DHCP on $TAP (Radmin-Linux)
After=network.target
[Service]
ExecStart=/usr/sbin/dnsmasq --keep-in-foreground --interface=$TAP --bind-dynamic \\
  --except-interface=lo --no-resolv --no-hosts --port=0 \\
  --dhcp-range=192.168.137.10,192.168.137.20,255.255.255.0,12h \\
  --dhcp-option=3 --dhcp-option=6 --dhcp-authoritative --log-dhcp
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now $DHCP_SVC" 2>/dev/null || warn "DHCP via the VM's ICS (fine if you use ICS)"
ok "DHCP configured"

# ---------- 7. config.env ----------
say "7/8  Config"
mkdir -p "$CONF_DIR"
cat > "$CONF" <<CFG
# Radmin-Linux - generated by install.sh at $(date -Iseconds)
RADMIN_HOME=$HOME_DIR
RADMIN_VMDIR=$VMDIR
RADMIN_VENV=$VENV
RADMIN_APP=$HOME_DIR/app
RADMIN_TAP=$TAP
RADMIN_NMCON=$NMCON
RADMIN_TAP_IP=$TAP_IP
RADMIN_HOST=192.168.137.1
RADMIN_CRED=bench:bench
RADMIN_RUN=$VMDIR/bench-run.sh
RADMIN_VIEW=$VMDIR/bench-view.sh
CFG
ok "config in $CONF"

# ---------- 8. icons + .desktop shortcut ----------
say "8/8  Icon and menu shortcut"
ICONS="$HOME/.local/share/icons/hicolor"
# install the icon in each size (WITHOUT creating index.theme; the system's one handles that)
for sz in 16 22 24 32 48 64 128 256; do
  if [[ -f "$SELF/assets/radmin-linux-$sz.png" ]]; then
    mkdir -p "$ICONS/${sz}x${sz}/apps"
    cp "$SELF/assets/radmin-linux-$sz.png" "$ICONS/${sz}x${sz}/apps/radmin-linux.png"
  fi
done
gtk-update-icon-cache -q "$ICONS" 2>/dev/null || true
ok "icon installed in hicolor"

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
sed "s|^Exec=radmin-linux$|Exec=$HOME_DIR/radmin-linux.sh|" \
    "$SELF/packaging/radmin-linux.desktop" > "$APPS/radmin-linux.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
ok "shortcut created (look for 'Radmin VPN' in the menu)"

echo
say "Installed. Open 'Radmin VPN' from the menu — the UI does the rest."
say "Or run it now: $HOME_DIR/radmin-linux.sh"
