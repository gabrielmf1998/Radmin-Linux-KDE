#!/usr/bin/env bash
# ============================================================
#  build-vm.sh - produz a imagem-base distribuivel do Radmin-Linux.
#
#  Dois modos:
#   --clean IMG.qcow2   parte de uma imagem JA pronta (com Windows+Radmin+agente)
#                       e a LIMPA para distribuir: sai da rede atual, zera o
#                       Alias, apaga logs/roster/dump, compacta. (rapido)
#   --from-scratch      provisiona do zero: instala POSReady7 desatendido,
#                       Radmin, ICS e o agente. (longo; requer as ISOs)
#
#  O objetivo do --clean: a VM aqui esta logada na rede dos seus amigos.
#  Antes de copiar/distribuir, ESTA e a etapa que tira voce da rede deles.
# ============================================================
set -uo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
say(){ printf '\033[1;36m>>\033[0m %s\n' "$*"; }
ok(){  printf '   \033[1;32m[ok]\033[0m %s\n' "$*"; }
die(){ printf '   \033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; exit 1; }

MODE="${1:-}"; shift || true

clean_running_vm() {
  # roda os passos de limpeza DENTRO da VM (ligada), via WMI
  say "Limpando o estado do Radmin na VM (saindo da rede, zerando identidade)"
  local ps
  ps=$(cat <<'PSEOF'
$ErrorActionPreference="SilentlyContinue"
# 1. sai de TODAS as redes (remove as associacoes)
$net="HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0\Networks"
if(Test-Path $net){ Get-ChildItem $net | ForEach-Object { Remove-Item $_.PSPath -Recurse -Force } }
# 2. zera identidade (Alias, RID cache) para o proximo dono definir a sua
$b="HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0"
Set-ItemProperty $b -Name Alias -Value "RADMIN-LINUX" -Type String
Set-ItemProperty $b -Name PowerOn -Value 1 -Type DWord
# 3. limpa logs/dumps do agente e chat
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
    && ok "rede removida e identidade zerada" || die "falha ao limpar via WMI"
}

case "$MODE" in
  --clean)
    IMG="${1:-$RADMIN_VMDIR/bench.qcow2}"
    [[ -f "$IMG" ]] || die "imagem nao encontrada: $IMG"
    # a VM precisa estar LIGADA para limpar via WMI
    if ! "$RADMIN_VENV/bin/python" "$SELF/app/vmctl.py" status 2>/dev/null | grep -q running; then
      die "ligue a VM antes (--clean opera na VM em execucao)"
    fi
    clean_running_vm
    say "Desligando a VM para congelar a imagem limpa"
    "$RADMIN_VENV/bin/python" "$SELF/app/vmctl.py" off >/dev/null
    sleep 3
    OUT="${RADMIN_DIST:-$SELF/dist}/radmin-linux-base.qcow2"
    mkdir -p "$(dirname "$OUT")"
    say "Compactando a imagem (qemu-img -c) para distribuicao"
    qemu-img convert -O qcow2 -c "$IMG" "$OUT" || die "falha ao compactar"
    SZ=$(du -h "$OUT" | cut -f1)
    ok "imagem-base limpa: $OUT ($SZ)"
    if command -v zstd >/dev/null; then
      zstd -q -19 --long=27 -f "$OUT" -o "$OUT.zst" && ok "comprimida: $OUT.zst ($(du -h "$OUT.zst"|cut -f1))"
    fi
    say "Pronta para distribuir. Instale com: ./install.sh $OUT.zst"
    ;;
  --from-scratch)
    die "modo --from-scratch ainda nao implementado neste script.
    Requer as ISOs (POSReady7) e reproduz: install desatendido -> Radmin ->
    ICS -> agente. Por ora use --clean sobre a imagem atual."
    ;;
  *)
    cat <<USAGE
uso:
  ./build-vm.sh --clean [IMG.qcow2]   limpa a VM (sai da rede, zera identidade,
                                      compacta) -> dist/radmin-linux-base.qcow2[.zst]
  ./build-vm.sh --from-scratch        (futuro) provisiona do zero

IMPORTANTE: --clean e a etapa que tira voce da rede dos amigos antes de copiar.
USAGE
    ;;
esac
