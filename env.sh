#!/usr/bin/env bash
# env.sh - central configuration for Radmin-Linux (shell side).
# Priority: environment variables > ~/.config/radmin-linux/config.env > defaults.
# Do `source env.sh` at the start of each script.

_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/radmin-linux/config.env"
[[ -f "$_CFG" ]] && source "$_CFG"

# install root (dev: the bench; installed: ~/.local/share/radmin-linux)
export RADMIN_HOME="${RADMIN_HOME:-/mnt/samsung-980pro/VMs/ntlite-bench}"
export RADMIN_VMDIR="${RADMIN_VMDIR:-$RADMIN_HOME}"
export RADMIN_VENV="${RADMIN_VENV:-$RADMIN_HOME/.recon-venv}"

# network / VM access
export RADMIN_HOST="${RADMIN_HOST:-192.168.137.1}"
export RADMIN_CRED="${RADMIN_CRED:-bench:bench}"
export RADMIN_TARGET="${RADMIN_TARGET:-$RADMIN_CRED@$RADMIN_HOST}"

# isolated host<->VM interface
export RADMIN_TAP="${RADMIN_TAP:-tapradmin}"
export RADMIN_NMCON="${RADMIN_NMCON:-radmin-bridge}"
export RADMIN_ISO_MAC="${RADMIN_ISO_MAC:-52:54:00:26:00:02}"
export RADMIN_TAP_IP="${RADMIN_TAP_IP:-192.168.137.2/24}"

# where the app code lives (this file's directory)
export RADMIN_APP="${RADMIN_APP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# VM footprint — intentionally tiny so it never hurts the host: 512 MB RAM / 1 CPU
export RADMIN_VM_RAM="${RADMIN_VM_RAM:-512}"
export RADMIN_VM_SMP="${RADMIN_VM_SMP:-1}"

# derived
export RADMIN_PY="$RADMIN_VENV/bin/python"
export RADMIN_DHCP_SVC="${RADMIN_DHCP_SVC:-dnsmasq-tapradmin.service}"
