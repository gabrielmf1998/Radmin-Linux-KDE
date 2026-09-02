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
    # provisiona a VM do ZERO: POSReady7 desatendido -> Radmin -> ICS -> agente.
    WINISO="${1:-${RADMIN_WIN_ISO:-}}"
    [[ -f "$WINISO" ]] || die "passe a ISO do Windows: ./build-vm.sh --from-scratch POSReady7.iso"
    command -v qemu-img >/dev/null || die "qemu-img ausente"
    command -v xorriso  >/dev/null || die "xorriso ausente (instale xorriso)"
    for t in mkfs.vfat mcopy; do command -v $t >/dev/null || die "$t ausente (instale mtools/dosfstools)"; done

    BDIR="${RADMIN_BUILD:-$SELF/build}"
    # PROTECAO CRITICA: o disco da VM cresce ate ~10GB durante a instalacao.
    # Se BDIR estiver em tmpfs (/tmp e RAM na maioria das distros), isso ESGOTA
    # a RAM e TRAVA a maquina. Recusar tmpfs.
    mkdir -p "$BDIR"
    FSTYPE=$(stat -f -c %T "$BDIR" 2>/dev/null)
    if [[ "$FSTYPE" == "tmpfs" || "$FSTYPE" == "ramfs" ]]; then
      die "BDIR ($BDIR) esta em $FSTYPE (RAM). Isso travaria a maquina.
    Use um disco real: RADMIN_BUILD=/caminho/em/disco ./build-vm.sh --from-scratch ..."
    fi
    AVAIL_GB=$(df -BG --output=avail "$BDIR" 2>/dev/null | tail -1 | tr -dc '0-9')
    [[ -n "$AVAIL_GB" && "$AVAIL_GB" -lt 15 ]] && die "pouco espaco em $BDIR (${AVAIL_GB}G); precisa de ~15G"
    rm -rf "$BDIR"; mkdir -p "$BDIR/media/agent"
    say "1/6  Baixando o Radmin VPN (na midia de provisionamento)"
    RURL="https://download.radmin-vpn.com/download/files/Radmin_VPN_2.0.4899.9.exe"
    curl -fsSL "$RURL" -o "$BDIR/media/Radmin_VPN.exe" || die "falha ao baixar o Radmin"

    say "2/6  Montando a midia (setup-guest + agente)"
    cp "$SELF/provision/setup-guest.ps1" "$BDIR/media/"
    cp "$SELF/agent/"*.ps1 "$BDIR/media/agent/"
    xorriso -as mkisofs -J -r -V PROVISION -o "$BDIR/provision.iso" "$BDIR/media" 2>/dev/null || die "falha na ISO"

    say "3/6  Floppy de resposta (autounattend)"
    dd if=/dev/zero of="$BDIR/unattend.img" bs=1024 count=1440 status=none
    mkfs.vfat -n UNATTEND "$BDIR/unattend.img" >/dev/null
    MTOOLS_SKIP_CHECK=1 mcopy -i "$BDIR/unattend.img" "$SELF/provision/autounattend.xml" ::autounattend.xml

    say "4/6  Criando o disco (24G esparso)"
    DISK="$BDIR/bench.qcow2"
    qemu-img create -f qcow2 "$DISK" 24G >/dev/null

    say "5/6  Instalando + provisionando (headless, ~15 min). Acompanhe: vncviewer 127.0.0.1:5905"
    # 2 NICs: NAT (internet p/ o Radmin) + a isolada com o MAC que o ICS espera
    # prioridade baixa de CPU e I/O: o build nunca deve travar o desktop
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

    # espera o QEMU criar o pidfile (o & inicia async)
    for i in $(seq 1 15); do [[ -s "$BDIR/build.pid" ]] && break; sleep 1; done
    BPID="$(cat "$BDIR/build.pid" 2>/dev/null)"
    [[ -n "$BPID" ]] && kill -0 "$BPID" 2>/dev/null || die "a VM de build nao subiu (ver VNC 5905)"
    # o setup-guest desliga a VM ao terminar -> esperamos o processo morrer.
    say "   aguardando (o convidado se desliga ao concluir; ate ~35 min)…"
    for i in $(seq 1 105); do   # 105*20s = 35 min
      sleep 20
      kill -0 "$BPID" 2>/dev/null || { say "   convidado concluiu e desligou"; break; }
      [[ $((i % 15)) -eq 0 ]] && say "   ... ainda instalando ($((i*20/60)) min)"
    done

    say "6/6  Finalizando a imagem"
    # desliga graciosamente
    printf 'system_powerdown\n' | timeout 10 socat -,ignoreeof UNIX-CONNECT:"$BDIR/mon.sock" >/dev/null 2>&1
    for i in $(seq 1 30); do kill -0 "$(cat "$BDIR/build.pid" 2>/dev/null)" 2>/dev/null || break; sleep 2; done
    kill "$(cat "$BDIR/build.pid" 2>/dev/null)" 2>/dev/null || true

    OUT="${RADMIN_DIST:-$SELF/dist}/radmin-linux-base.qcow2"
    mkdir -p "$(dirname "$OUT")"
    qemu-img convert -O qcow2 -c "$DISK" "$OUT" && ok "imagem-base: $OUT ($(du -h "$OUT"|cut -f1))"
    command -v zstd >/dev/null && zstd -q -19 -f "$OUT" -o "$OUT.zst" && ok "comprimida: $OUT.zst ($(du -h "$OUT.zst"|cut -f1))"
    say "Instale com: ./install.sh $OUT.zst"
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
