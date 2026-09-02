#!/usr/bin/env bash
# ============================================================
#  bootstrap.sh - instalacao por um comando:
#
#    curl -fsSL https://raw.githubusercontent.com/gabrielmf1998/radmin-linux/main/bootstrap.sh | bash
#
#  Baixa o codigo, baixa a imagem-base da VM (do release) e roda o install.sh.
#  Funciona em Fedora/Nobara, Debian/Ubuntu, Arch/Manjaro, openSUSE.
# ============================================================
set -euo pipefail

REPO="${RADMIN_REPO:-gabrielmf1998/radmin-linux}"
BRANCH="${RADMIN_BRANCH:-main}"
# a imagem da VM (grande) vem de um release; sobreescreva com RADMIN_VM_URL
VM_URL="${RADMIN_VM_URL:-https://github.com/$REPO/releases/latest/download/radmin-linux-base.qcow2.zst}"
DEST="${RADMIN_HOME:-$HOME/.local/share/radmin-linux}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say(){ printf '\033[1;36m>>\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || command -v wget >/dev/null || die "preciso de curl ou wget"
get(){ if command -v curl >/dev/null; then curl -fsSL "$1" -o "$2"; else wget -qO "$2" "$1"; fi; }

say "Baixando o codigo do Radmin-Linux ($REPO@$BRANCH)"
get "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" "$WORK/src.tgz" \
  || die "falha ao baixar o codigo"
mkdir -p "$WORK/src"
tar xzf "$WORK/src.tgz" -C "$WORK/src" --strip-components=1

IMG_ARG=""
if [[ -n "${RADMIN_VM_IMAGE:-}" && -f "${RADMIN_VM_IMAGE:-}" ]]; then
  IMG_ARG="$RADMIN_VM_IMAGE"                    # imagem local ja fornecida
elif [[ -f "$DEST/vm/bench.qcow2" ]]; then
  say "Imagem da VM ja instalada; reaproveitando"
else
  say "Baixando a imagem-base da VM (grande, pode demorar)"
  if get "$VM_URL" "$WORK/vm.qcow2.zst"; then
    IMG_ARG="$WORK/vm.qcow2.zst"
  else
    say "Nao consegui baixar a imagem automaticamente."
    say "Rode depois: $DEST/install.sh /caminho/para/radmin-linux-base.qcow2.zst"
  fi
fi

say "Rodando o instalador"
bash "$WORK/src/install.sh" $IMG_ARG

say "Pronto. Abra 'Radmin VPN' no menu (ou rode: radmin-linux)."
