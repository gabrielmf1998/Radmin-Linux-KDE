#!/usr/bin/env bash
# ============================================================
#  preflight.sh - checks and auto-repairs the stack before opening the UI.
#  Layers, bottom to top:
#    1. venv (impacket + PySide6)
#    2. tapradmin interface (NetworkManager)          -> nmcli con up
#    3. DHCP on the tap (only when NOT in ICS mode)    -> systemctl
#    4. ntlite-bench VM up                             -> bench-run.sh
#    5. VM reachable on the network (ping)
#    6. WMI answers (SMB/credential)
#    7. shim present at C:\radmin-shim.ps1            -> deploy-shim.sh
#  Exits 0 if everything is ready; prints each step. Use -q for errors only.
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
  [[ "$a" == "--light" ]] && LIGHT=1   # only prepares venv+tap+DHCP; does NOT start the VM
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
  ok "$TAP exists"
else
  fix "bringing up connection $NMCON"
  nmcli con up "$NMCON" >/dev/null 2>&1
  sleep 2
  if ip link show "$TAP" >/dev/null 2>&1; then ok "$TAP up"; else err "could not create $TAP"; FAIL=1; fi
fi

# 3. DHCP (only if the tap is in /8 mode, i.e. L2 bridge; in ICS the VM serves it) --
step "3/7 tap DHCP"
TAP_IP="$(ip -4 -o addr show "$TAP" 2>/dev/null | awk '{print $4}')"
if [[ "$TAP_IP" == 26.* ]]; then
  if systemctl is-active --quiet "$DHCP_SVC"; then ok "$DHCP_SVC active (bridge mode)"
  else fix "starting $DHCP_SVC"; systemctl start "$DHCP_SVC" 2>/dev/null || pkexec systemctl start "$DHCP_SVC"; fi
else
  ok "ICS/NAT mode ($TAP_IP) — DHCP stays in the VM, nothing to do"
fi

# --light mode: stop here. Prepares the stack (venv+tap+DHCP) but does NOT start the
# VM nor wait for boot/WMI. The UI opens immediately; the VM only starts on request.
if [[ $LIGHT -eq 1 ]]; then
  [[ $FAIL -eq 0 ]] && { [[ $QUIET -eq 0 ]] && echo ">> stack prepared (light mode; VM not started)."; exit 0; }
  err "light preparation incomplete"; exit 1
fi

# 4. VM up ------------------------------------------------------------
# Nuance: if the tap was recreated (NO-CARRIER) with the VM alive, QEMU stayed pinned
# to the old tun device -> the VM must restart to reattach to the new tap.
step "4/7 ntlite-bench VM"
vm_alive(){ [[ -f "$VMDIR/qemu.pid" ]] && kill -0 "$(cat "$VMDIR/qemu.pid")" 2>/dev/null; }
tap_carrier(){ ip link show "$TAP" 2>/dev/null | grep -q 'LOWER_UP'; }
start_vm(){ ( cd "$VMDIR" && setsid nohup ./bench-run.sh >/dev/null 2>&1 < /dev/null & ); }

if vm_alive && ! tap_carrier; then
  fix "VM alive but $TAP has no carrier — restarting the VM to reattach"
  ( cd "$VMDIR" && ./bench-stop.sh >/dev/null 2>&1 )
  sleep 2; start_vm; ok "VM restarted — waiting for boot"
elif vm_alive; then
  ok "VM running (pid $(cat "$VMDIR/qemu.pid"))"
else
  fix "starting the VM (headless)"; start_vm; ok "VM started — waiting for boot"
fi

# 5. VM reachable -----------------------------------------------------
step "5/7 network ($TARGET_HOST)"
REACH=0
for i in $(seq 1 30); do
  if ping -n -c1 -W1 "$TARGET_HOST" >/dev/null 2>&1; then REACH=1; break; fi
  sleep 3
done
if [[ $REACH -eq 1 ]]; then ok "$TARGET_HOST responds"; else err "VM unreachable after 90s"; FAIL=1; fi

# 6. WMI + 7. shim ----------------------------------------------------
if [[ $FAIL -eq 0 ]]; then
  step "6/7 WMI"
  WOK=0
  for i in $(seq 1 20); do
    if "$VENV/bin/python" "$VENV/bin/wmiexec.py" -shell-type powershell "$USER_PASS@$TARGET_HOST" \
         "powershell -Command exit" >/dev/null 2>&1; then WOK=1; break; fi
    sleep 6
  done
  if [[ $WOK -eq 1 ]]; then ok "WMI authenticates and runs"; else err "WMI did not answer (VM still booting? UAC?)"; FAIL=1; fi

  step "7/7 shim in the VM"
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
  if [[ "$HAS" == "yes" ]]; then ok "C:\\radmin-shim.ps1 present"
  else fix "sending the shim"; "$SELF/deploy-shim.sh" >/dev/null 2>&1 && ok "shim sent" || { err "failed to send the shim"; FAIL=1; }
  fi
fi

if [[ $FAIL -eq 0 ]]; then
  [[ $QUIET -eq 0 ]] && echo ">> stack ready."
  exit 0
else
  err "preflight incomplete — see above."
  exit 1
fi
