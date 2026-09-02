#!/usr/bin/env bash
# ============================================================
#  preflight.sh - verifica e auto-repara a pilha antes de abrir a UI.
#  Camadas, de baixo pra cima:
#    1. venv (impacket + PySide6)
#    2. interface tapradmin (NetworkManager)          -> nmcli con up
#    3. DHCP na tap (so quando NAO em modo ICS)        -> systemctl
#    4. VM ntlite-bench ligada                         -> bench-run.sh
#    5. VM alcancavel na rede (ping)
#    6. WMI responde (SMB/credencial)
#    7. shim presente em C:\radmin-shim.ps1           -> deploy-shim.sh
#  Sai 0 se tudo pronto; imprime cada passo. Use -q p/ so erros.
# ============================================================
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
VENV="$RADMIN_VENV"; VMDIR="$RADMIN_VMDIR"; TAP="$RADMIN_TAP"
NMCON="$RADMIN_NMCON"; TARGET_HOST="$RADMIN_HOST"; USER_PASS="$RADMIN_CRED"
DHCP_SVC="$RADMIN_DHCP_SVC"

QUIET=0; LIGHT=0
for a in "$@"; do
  [[ "$a" == "-q" ]] && QUIET=1
  [[ "$a" == "--light" ]] && LIGHT=1   # so prepara venv+tap+DHCP; NAO liga a VM
done
ok(){ [[ $QUIET -eq 0 ]] && echo "  [ok] $*"; }
fix(){ echo "  [fix] $*"; }
err(){ echo "  [ERRO] $*" >&2; }
step(){ [[ $QUIET -eq 0 ]] && echo "== $* =="; }

FAIL=0

# 1. venv -------------------------------------------------------------
step "1/7 venv"
if [[ -x "$VENV/bin/python" ]] && "$VENV/bin/python" -c "import impacket,PySide6" 2>/dev/null; then
  ok "impacket + PySide6"
else
  err "venv incompleto em $VENV (rode: VIRTUAL_ENV=$VENV uv pip install impacket PySide6)"
  FAIL=1
fi

# 2. interface tap ----------------------------------------------------
step "2/7 interface $TAP"
if ip link show "$TAP" >/dev/null 2>&1; then
  ok "$TAP existe"
else
  fix "subindo conexao $NMCON"
  nmcli con up "$NMCON" >/dev/null 2>&1
  sleep 2
  if ip link show "$TAP" >/dev/null 2>&1; then ok "$TAP no ar"; else err "nao consegui criar $TAP"; FAIL=1; fi
fi

# 3. DHCP (so se a tap estiver em modo /8, i.e. bridge L2; em ICS a VM serve) --
step "3/7 DHCP da tap"
TAP_IP="$(ip -4 -o addr show "$TAP" 2>/dev/null | awk '{print $4}')"
if [[ "$TAP_IP" == 26.* ]]; then
  if systemctl is-active --quiet "$DHCP_SVC"; then ok "$DHCP_SVC ativo (modo bridge)"
  else fix "iniciando $DHCP_SVC"; systemctl start "$DHCP_SVC" 2>/dev/null || pkexec systemctl start "$DHCP_SVC"; fi
else
  ok "modo ICS/NAT ($TAP_IP) — DHCP fica na VM, nada a fazer"
fi

# modo --light: para aqui. Prepara a pilha (venv+tap+DHCP) mas NAO liga a VM
# nem espera boot/WMI. A UI abre na hora; a VM so liga quando o usuario mandar.
if [[ $LIGHT -eq 1 ]]; then
  [[ $FAIL -eq 0 ]] && { [[ $QUIET -eq 0 ]] && echo ">> pilha preparada (modo leve; VM nao ligada)."; exit 0; }
  err "preparo leve incompleto"; exit 1
fi

# 4. VM ligada --------------------------------------------------------
# Nuance: se a tap foi recriada (NO-CARRIER) com a VM viva, o QEMU ficou preso
# no device tun antigo -> a VM precisa reiniciar p/ reatar na nova tap.
step "4/7 VM ntlite-bench"
vm_alive(){ [[ -f "$VMDIR/qemu.pid" ]] && kill -0 "$(cat "$VMDIR/qemu.pid")" 2>/dev/null; }
tap_carrier(){ ip link show "$TAP" 2>/dev/null | grep -q 'LOWER_UP'; }
start_vm(){ ( cd "$VMDIR" && setsid nohup ./bench-run.sh >/dev/null 2>&1 < /dev/null & ); }

if vm_alive && ! tap_carrier; then
  fix "VM viva mas $TAP sem carrier — reiniciando a VM p/ reatar"
  ( cd "$VMDIR" && ./bench-stop.sh >/dev/null 2>&1 )
  sleep 2; start_vm; ok "VM reiniciada — aguardando boot"
elif vm_alive; then
  ok "VM rodando (pid $(cat "$VMDIR/qemu.pid"))"
else
  fix "ligando a VM (headless)"; start_vm; ok "VM iniciada — aguardando boot"
fi

# 5. VM alcancavel ----------------------------------------------------
step "5/7 rede ($TARGET_HOST)"
REACH=0
for i in $(seq 1 30); do
  if ping -c1 -W1 "$TARGET_HOST" >/dev/null 2>&1; then REACH=1; break; fi
  sleep 3
done
if [[ $REACH -eq 1 ]]; then ok "$TARGET_HOST responde"; else err "VM inalcancavel apos 90s"; FAIL=1; fi

# 6. WMI + 7. shim ----------------------------------------------------
if [[ $FAIL -eq 0 ]]; then
  step "6/7 WMI"
  WOK=0
  for i in $(seq 1 20); do
    if "$VENV/bin/python" "$VENV/bin/wmiexec.py" -shell-type powershell "$USER_PASS@$TARGET_HOST" \
         "powershell -Command exit" >/dev/null 2>&1; then WOK=1; break; fi
    sleep 6
  done
  if [[ $WOK -eq 1 ]]; then ok "WMI autentica e executa"; else err "WMI nao respondeu (VM ainda bootando? UAC?)"; FAIL=1; fi

  step "7/7 shim na VM"
  HAS=$("$VENV/bin/python" - <<PY 2>/dev/null
from impacket.smbconnection import SMBConnection
try:
    c=SMBConnection("$TARGET_HOST","$TARGET_HOST"); c.login(*"$USER_PASS".split(":",1))
    try:
        c.listPath("C\$","\\\\radmin-shim.ps1"); print("yes")
    except Exception: print("no")
    c.close()
except Exception: print("err")
PY
)
  if [[ "$HAS" == "yes" ]]; then ok "C:\\radmin-shim.ps1 presente"
  else fix "enviando a shim"; "$SELF/deploy-shim.sh" >/dev/null 2>&1 && ok "shim enviada" || { err "falha ao enviar a shim"; FAIL=1; }
  fi
fi

if [[ $FAIL -eq 0 ]]; then
  [[ $QUIET -eq 0 ]] && echo ">> pilha pronta."
  exit 0
else
  err "preflight incompleto — ver acima."
  exit 1
fi
