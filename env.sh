#!/usr/bin/env bash
# env.sh - configuracao central do Radmin-Linux (lado shell).
# Prioridade: variaveis de ambiente > ~/.config/radmin-linux/config.env > defaults.
# Faca `source env.sh` no inicio de cada script.

_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/radmin-linux/config.env"
[[ -f "$_CFG" ]] && source "$_CFG"

# raiz da instalacao (dev: a bancada; instalado: ~/.local/share/radmin-linux)
export RADMIN_HOME="${RADMIN_HOME:-/mnt/samsung-980pro/VMs/ntlite-bench}"
export RADMIN_VMDIR="${RADMIN_VMDIR:-$RADMIN_HOME}"
export RADMIN_VENV="${RADMIN_VENV:-$RADMIN_HOME/.recon-venv}"

# rede / acesso a VM
export RADMIN_HOST="${RADMIN_HOST:-192.168.137.1}"
export RADMIN_CRED="${RADMIN_CRED:-bench:bench}"
export RADMIN_TARGET="${RADMIN_TARGET:-$RADMIN_CRED@$RADMIN_HOST}"

# interface isolada host<->VM
export RADMIN_TAP="${RADMIN_TAP:-tapradmin}"
export RADMIN_NMCON="${RADMIN_NMCON:-radmin-bridge}"
export RADMIN_ISO_MAC="${RADMIN_ISO_MAC:-52:54:00:26:00:02}"
export RADMIN_TAP_IP="${RADMIN_TAP_IP:-192.168.137.2/24}"

# onde fica o codigo da app (o dir deste arquivo)
export RADMIN_APP="${RADMIN_APP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# derivados
export RADMIN_PY="$RADMIN_VENV/bin/python"
export RADMIN_DHCP_SVC="${RADMIN_DHCP_SVC:-dnsmasq-tapradmin.service}"
