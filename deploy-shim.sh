#!/usr/bin/env bash
# Envia radmin-shim.ps1 para C:\radmin-shim.ps1 na VM via SMB.
SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
"$RADMIN_PY" - <<PY
from impacket.smbconnection import SMBConnection
import io
host="$RADMIN_HOST"; user,pw="$RADMIN_CRED".split(":",1)
c=SMBConnection(host,host); c.login(user,pw)
d=open("$SELF/shim/radmin-shim.ps1","rb").read()
c.putFile("C\$","\\\\radmin-shim.ps1", io.BytesIO(d).read)
print("shim enviada:", len(d), "bytes"); c.close()
PY
