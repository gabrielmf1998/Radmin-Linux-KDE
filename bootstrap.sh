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
# The VM image (~3 GB) is SPLIT into <2 GB parts on the release (GitHub caps release
# assets at 2 GB); we download the parts and concatenate them. Override with a single
# local file via RADMIN_VM_IMAGE, or a single URL via RADMIN_VM_URL.
BASE_URL="https://github.com/$REPO/releases/latest/download"
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
  OUT="$WORK/vm.qcow2.zst"
  if [[ -n "${RADMIN_VM_URL:-}" ]]; then
    get "$RADMIN_VM_URL" "$OUT" || OUT=""              # single-URL override
  else
    : > "$OUT"; ok=0
    for suf in aa ab ac ad ae af ag ah; do            # concatenate the split parts
      p="radmin-linux-base.qcow2.zst.part-$suf"
      if get "$BASE_URL/$p" "$WORK/$p" 2>/dev/null; then
        cat "$WORK/$p" >> "$OUT"; rm -f "$WORK/$p"; ok=1
      else
        break
      fi
    done
    # fallback: a single, non-split asset (if it ever fits under 2 GB)
    [[ $ok -eq 0 ]] && { get "$BASE_URL/radmin-linux-base.qcow2.zst" "$OUT" || OUT=""; }
  fi
  if [[ -n "$OUT" && -s "$OUT" ]]; then
    IMG_ARG="$OUT"
  else
    say "Could not download the image automatically."
    say "Run later: $DEST/install.sh /path/to/radmin-linux-base.qcow2.zst"
  fi
fi

say "Running the installer"
bash "$WORK/src/install.sh" $IMG_ARG

say "Done. Open 'Radmin VPN' from the menu (or run: radmin-linux)."
