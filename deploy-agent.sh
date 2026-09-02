#!/usr/bin/env bash
# Cria C:\radmin-agent na VM e envia todos os scripts do agente.
VENV=/mnt/samsung-980pro/VMs/ntlite-bench/.recon-venv
HOST=192.168.137.1; CRED=bench:bench
SELF="$(cd "$(dirname "$0")" && pwd)"
"$VENV/bin/python" - <<PY
from impacket.smbconnection import SMBConnection
import io, os, glob
c=SMBConnection("$HOST","$HOST"); c.login(*"$CRED".split(":",1))
# garante a pasta
try: c.createDirectory("C\$","radmin-agent")
except Exception: pass
for f in sorted(glob.glob("$SELF/agent/*.ps1")):
    name=os.path.basename(f)
    d=open(f,"rb").read()
    c.putFile("C\$","\\\\radmin-agent\\\\"+name, io.BytesIO(d).read)
    print("enviado:", name, len(d))
c.close()
PY
