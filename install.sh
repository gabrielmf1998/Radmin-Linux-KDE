#!/usr/bin/env bash
# ============================================================
#  install.sh - instalador plug-and-play do Radmin-Linux.
#  Monta a pilha inteira num alvo limpo:
#    1. checa KVM (todo kernel tem)
#    2. checa/instala dependencias do sistema (qemu, dnsmasq, ...)
#    3. cria o venv (impacket + PySide6)
#    4. instala o codigo em ~/.local/share/radmin-linux
#    5. importa a imagem da VM
#    6. cria a interface isolada (NM) + DHCP (systemd)
#    7. escreve o config.env
#    8. cria o atalho .desktop (a UI faz o resto)
#  Depois disto o usuario so abre "Radmin VPN" no menu. Nada de VM.
# ============================================================
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
say(){ printf '\033[1;36m>>\033[0m %s\n' "$*"; }
ok(){  printf '   \033[1;32m[ok]\033[0m %s\n' "$*"; }
warn(){ printf '   \033[1;33m[!]\033[0m %s\n' "$*"; }
die(){ printf '   \033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; exit 1; }

# alvo da instalacao
HOME_DIR="${RADMIN_HOME:-$HOME/.local/share/radmin-linux}"
VMDIR="$HOME_DIR/vm"
VENV="$HOME_DIR/venv"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/radmin-linux"
CONF="$CONF_DIR/config.env"
TAP="${RADMIN_TAP:-tapradmin}"
NMCON="${RADMIN_NMCON:-radmin-bridge}"
TAP_IP="${RADMIN_TAP_IP:-192.168.137.2/24}"
DHCP_SVC="dnsmasq-tapradmin.service"

# a imagem da VM: 1o arg, ou variavel, ou procura ao lado
VM_IMAGE="${1:-${RADMIN_VM_IMAGE:-}}"

# ---------- 1. KVM ----------
say "1/8  Verificando KVM"
if [[ ! -e /dev/kvm ]]; then
  warn "/dev/kvm ausente. Tentando carregar o modulo…"
  if grep -qi 'vmx' /proc/cpuinfo; then MOD=kvm_intel; else MOD=kvm_amd; fi
  pkexec modprobe kvm "$MOD" 2>/dev/null || warn "nao carreguei $MOD (habilite VT-x/AMD-V na BIOS)"
fi
[[ -e /dev/kvm ]] || die "KVM indisponivel. Habilite a virtualizacao na BIOS."
if [[ -r /dev/kvm && -w /dev/kvm ]]; then ok "/dev/kvm acessivel"
else
  warn "/dev/kvm sem permissao; adicionando voce ao grupo kvm"
  pkexec usermod -aG kvm "$USER" && warn "faca logout/login para o grupo kvm valer"
fi

# ---------- 2. dependencias do sistema ----------
say "2/8  Dependencias do sistema"
# detecta a familia da distro e mapeia os nomes de pacote (variam muito)
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
  die "gerenciador de pacotes nao reconhecido. Instale manualmente: qemu, qemu-img, dnsmasq, NetworkManager, socat, python3"
fi

need=()
command -v qemu-system-x86_64 >/dev/null || need+=($PKG_QEMU)
command -v qemu-img >/dev/null || need+=($PKG_IMG)
command -v dnsmasq  >/dev/null || need+=($PKG_DNS)
command -v nmcli    >/dev/null || need+=($PKG_NM)
command -v socat    >/dev/null || need+=($PKG_SOCAT)
command -v python3  >/dev/null || need+=($PKG_PY)
command -v uv       >/dev/null || warn "uv nao encontrado (usarei python -m venv)"
if [[ ${#need[@]} -gt 0 ]]; then
  say "   instalando (${PM%% *}...): ${need[*]}"
  $PM "${need[@]}" || die "falha ao instalar dependencias"
fi
ok "qemu, dnsmasq, NetworkManager, socat presentes"

# ---------- 3. venv ----------
say "3/8  Ambiente Python (impacket + PySide6)"
mkdir -p "$HOME_DIR"
if command -v uv >/dev/null; then
  uv venv --python 3.12 "$VENV" >/dev/null 2>&1 || uv venv "$VENV" >/dev/null 2>&1
  VIRTUAL_ENV="$VENV" uv pip install -q impacket PySide6 >/dev/null 2>&1
else
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q impacket PySide6 >/dev/null 2>&1
fi
"$VENV/bin/python" -c "import impacket, PySide6" 2>/dev/null && ok "venv pronto" || die "falha ao montar o venv"
# garante o wmiexec.py acessivel
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

# ---------- 4. codigo ----------
say "4/8  Instalando o codigo"
mkdir -p "$HOME_DIR/app"
cp -r "$SELF/app/"*.py "$HOME_DIR/app/"
cp -r "$SELF/shim" "$SELF/agent" "$HOME_DIR/"
cp "$SELF/env.sh" "$SELF/preflight.sh" "$SELF/radmin-linux.sh" \
   "$SELF/deploy-shim.sh" "$SELF/deploy-agent.sh" "$HOME_DIR/"
chmod +x "$HOME_DIR"/*.sh
ok "codigo em $HOME_DIR"

# ---------- 5. imagem da VM ----------
say "5/8  Imagem da VM"
mkdir -p "$VMDIR"
if [[ -n "$VM_IMAGE" && -f "$VM_IMAGE" ]]; then
  say "   importando $VM_IMAGE (pode demorar)…"
  case "$VM_IMAGE" in
    *.qcow2) cp "$VM_IMAGE" "$VMDIR/bench.qcow2" ;;
    *.qcow2.zst) zstd -d -o "$VMDIR/bench.qcow2" "$VM_IMAGE" ;;
    *.qcow2.gz)  gunzip -c "$VM_IMAGE" > "$VMDIR/bench.qcow2" ;;
    *) die "formato de imagem nao reconhecido: $VM_IMAGE" ;;
  esac
  ok "imagem importada"
elif [[ -f "$VMDIR/bench.qcow2" ]]; then
  ok "imagem ja presente em $VMDIR"
else
  warn "sem imagem da VM. Passe o caminho: ./install.sh caminho/bench.qcow2[.zst]"
  warn "ou rode ./build-vm.sh para construir uma limpa do zero."
fi
# copia os scripts de execucao da VM (bench-run/view/stop) se existirem ao lado da imagem
for f in bench-run.sh bench-view.sh bench-stop.sh common.sh; do
  [[ -f "$SELF/vm/$f" ]] && cp "$SELF/vm/$f" "$VMDIR/"
done

# ---------- 6. rede isolada + DHCP ----------
say "6/8  Interface isolada + DHCP"
if ! nmcli con show "$NMCON" >/dev/null 2>&1; then
  pkexec nmcli con add type tun con-name "$NMCON" ifname "$TAP" mode tap owner "$(id -u)" \
    ipv4.method manual ipv4.addresses "$TAP_IP" ipv4.never-default yes ipv6.method disabled \
    connection.zone trusted connection.autoconnect yes >/dev/null 2>&1
fi
pkexec nmcli con up "$NMCON" >/dev/null 2>&1 || true
ok "interface $TAP ($TAP_IP)"

pkexec bash -c "cat > /etc/systemd/system/$DHCP_SVC <<UNIT
[Unit]
Description=DHCP na $TAP (Radmin-Linux)
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
systemctl enable --now $DHCP_SVC" 2>/dev/null || warn "DHCP via ICS da VM (ok se usa ICS)"
ok "DHCP configurado"

# ---------- 7. config.env ----------
say "7/8  Config"
mkdir -p "$CONF_DIR"
cat > "$CONF" <<CFG
# Radmin-Linux - gerado pelo install.sh em $(date -Iseconds)
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
ok "config em $CONF"

# ---------- 8. atalho .desktop ----------
say "8/8  Atalho no menu"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
cat > "$APPS/radmin-linux.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Radmin VPN
Comment=Radmin VPN on Linux
Exec=$HOME_DIR/radmin-linux.sh
Icon=network-vpn
Terminal=false
Categories=Network;
DESK
update-desktop-database "$APPS" 2>/dev/null || true
ok "atalho criado (procure 'Radmin VPN' no menu)"

echo
say "Instalado. Abra 'Radmin VPN' no menu — a UI cuida do resto."
say "Ou rode agora: $HOME_DIR/radmin-linux.sh"
