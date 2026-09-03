#!/usr/bin/env bash
# ============================================================
#  bootstrap.sh - one-command install:
#
#    curl -fsSL https://raw.githubusercontent.com/gabrielmf1998/Radmin-Linux-KDE/main/bootstrap.sh | bash
#
#  Downloads the code, downloads the VM base image (from the release) and runs install.sh.
#  Works on Fedora/Nobara, Debian/Ubuntu, Arch/Manjaro, openSUSE.
# ============================================================
set -euo pipefail

REPO="${RADMIN_REPO:-gabrielmf1998/Radmin-Linux-KDE}"
BRANCH="${RADMIN_BRANCH:-main}"
# the VM image (large) comes from a release; override with RADMIN_VM_URL
VM_URL="${RADMIN_VM_URL:-https://github.com/$REPO/releases/latest/download/radmin-linux-base.qcow2.zst}"
DEST="${RADMIN_HOME:-$HOME/.local/share/radmin-linux}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say(){ printf '\033[1;36m>>\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || command -v wget >/dev/null || die "need curl or wget"
get(){ if command -v curl >/dev/null; then curl -fsSL "$1" -o "$2"; else wget -qO "$2" "$1"; fi; }

say "Downloading the Radmin-Linux code ($REPO@$BRANCH)"
get "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" "$WORK/src.tgz" \
  || die "failed to download the code"
mkdir -p "$WORK/src"
tar xzf "$WORK/src.tgz" -C "$WORK/src" --strip-components=1

IMG_ARG=""
if [[ -n "${RADMIN_VM_IMAGE:-}" && -f "${RADMIN_VM_IMAGE:-}" ]]; then
  IMG_ARG="$RADMIN_VM_IMAGE"                    # local image already provided
elif [[ -f "$DEST/vm/bench.qcow2" ]]; then
  say "VM image already installed; reusing"
else
  say "Downloading the VM base image (large, may take a while)"
  if get "$VM_URL" "$WORK/vm.qcow2.zst"; then
    IMG_ARG="$WORK/vm.qcow2.zst"
  else
    say "Could not download the image automatically."
    say "Run later: $DEST/install.sh /path/to/radmin-linux-base.qcow2.zst"
  fi
fi

say "Running the installer"
bash "$WORK/src/install.sh" $IMG_ARG

say "Done. Open 'Radmin VPN' from the menu (or run: radmin-linux)."
