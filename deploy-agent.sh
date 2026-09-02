#!/usr/bin/env bash
# Cria C:\radmin-agent na VM e envia todos os scripts do agente.
SELF="$(cd "$(dirname "$0")" && pwd)"
source "$SELF/env.sh"
"$RADMIN_PY" - <<PY
from impacket.smbconnection import SMBConnection
import io, os, glob
host="$RADMIN_HOST"; user,pw="$RADMIN_CRED".split(":",1)
c=SMBConnection(host,host); c.login(user,pw)
try: c.createDirectory("C\$","radmin-agent")
except Exception: pass
for f in sorted(glob.glob("$SELF/agent/*.ps1")):
    name=os.path.basename(f)
    d=open(f,"rb").read()
    c.putFile("C\$","\\\\radmin-agent\\\\"+name, io.BytesIO(d).read)
    print("enviado:", name, len(d))
c.close()
PY
