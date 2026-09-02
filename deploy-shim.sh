#!/usr/bin/env bash
# Envia radmin-shim.ps1 para C:\radmin-shim.ps1 na VM via SMB.
VENV=/mnt/samsung-980pro/VMs/ntlite-bench/.recon-venv
TARGET_HOST=192.168.137.1; USER=bench; PASS=bench
"$VENV/bin/python" - "$@" <<PY
from impacket.smbconnection import SMBConnection
import io
c=SMBConnection("$TARGET_HOST","$TARGET_HOST"); c.login("$USER","$PASS")
d=open("$(dirname "$0")/shim/radmin-shim.ps1","rb").read()
c.putFile("C\$","\\\\radmin-shim.ps1", io.BytesIO(d).read)
print("shim enviada:", len(d), "bytes"); c.close()
PY
