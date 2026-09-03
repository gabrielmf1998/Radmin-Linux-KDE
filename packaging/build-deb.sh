#!/usr/bin/env bash
# Builds the radmin-linux .deb (code only; the VM image is shipped separately,
# from the GitHub Release). Mirrors the .rpm layout. Needs: dpkg-deb.
set -euo pipefail
SELF="$(cd "$(dirname "$0")/.." && pwd)"
VER="${VER:-0.1.0}"
OUT="${1:-$SELF/packaging/dist}"
command -v dpkg-deb >/dev/null || { echo "need dpkg-deb (install dpkg)"; exit 1; }

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/radmin-linux"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/share/radmin-linux/vm" \
         "$PKG/usr/bin" "$PKG/usr/share/applications"

# ---- code ----
cp -r "$SELF/app" "$SELF/shim" "$SELF/agent" "$PKG/usr/share/radmin-linux/"
find "$PKG/usr/share/radmin-linux" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
install -m644 "$SELF/env.sh" "$PKG/usr/share/radmin-linux/"
install -m755 "$SELF/preflight.sh" "$SELF/radmin-linux.sh" "$SELF/deploy-shim.sh" \
        "$SELF/deploy-agent.sh" "$SELF/install.sh" "$SELF/build-vm.sh" \
        "$PKG/usr/share/radmin-linux/"
install -m755 "$SELF/vm/"*.sh "$PKG/usr/share/radmin-linux/vm/"
ln -s /usr/share/radmin-linux/radmin-linux.sh "$PKG/usr/bin/radmin-linux"
install -m644 "$SELF/packaging/radmin-linux.desktop" "$PKG/usr/share/applications/"
for sz in 16 22 24 32 48 64 128 256; do
  install -Dm644 "$SELF/assets/radmin-linux-$sz.png" \
    "$PKG/usr/share/icons/hicolor/${sz}x${sz}/apps/radmin-linux.png"
done

# ---- control ----
cat > "$PKG/DEBIAN/control" <<CTRL
Package: radmin-linux
Version: $VER
Section: net
Priority: optional
Architecture: all
Depends: qemu-system-x86, qemu-utils, dnsmasq-base, network-manager, socat, python3, python3-venv, python3-pip, policykit-1
Recommends: tigervnc-viewer
Maintainer: gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com>
Homepage: https://github.com/gabrielmf1998/Radmin-Linux-KDE
Description: Run Radmin VPN (Windows-only) on Linux via a headless VM
 Radmin VPN (Linux) drives the real Radmin VPN running inside a tiny headless
 Windows VM (512 MB RAM / 1 CPU), from a native Qt front-end. The user never
 opens the VM: the app powers it on/off, shows the mesh, connects/disconnects
 and self-heals. The VM image is provided separately (it is large and carries state).
CTRL

# ---- postinst ----
cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
echo "Radmin-Linux installed. Finish the per-user setup with:"
echo "  /usr/share/radmin-linux/install.sh /path/to/radmin-linux-base.qcow2.zst"
echo "then launch it from the menu, or run: radmin-linux"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
exit 0
POST
chmod 755 "$PKG/DEBIAN/postinst"

mkdir -p "$OUT"
DEB="$OUT/radmin-linux_${VER}_all.deb"
dpkg-deb --build --root-owner-group "$PKG" "$DEB"
echo "DEB: $DEB"
ls -la "$DEB"
