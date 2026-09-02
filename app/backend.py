"""
backend.py - fala com a shim na VM Windows via WMI (impacket) e devolve o estado.
So-leitura nesta fase.
"""
from __future__ import annotations
import json, re, subprocess, time, os, shutil
from dataclasses import dataclass, field

VENV = "/mnt/samsung-980pro/VMs/ntlite-bench/.recon-venv"
WMIEXEC = f"{VENV}/bin/python {VENV}/bin/wmiexec.py"
TARGET = os.environ.get("RADMIN_TARGET", "bench:bench@192.168.137.1")
SHIM_PATH = os.environ.get("RADMIN_SHIM", r"C:\radmin-shim.ps1")

_MARK_RE = re.compile(r"<<<RADMINJSON>>>\s*(.*?)\s*<<<END>>>", re.S)


@dataclass
class Peer:
    ip: str
    mac: str = ""
    type: str = "dynamic"
    host: str = ""          # hostname NetBIOS (nome real da maquina)
    name: str = ""          # apelido definido pelo usuario (override local)
    online: bool = True     # presenca no ARP = ativo


@dataclass
class State:
    ok: bool = False
    vm_running: bool = False
    node_ip: str = ""
    hostname: str = ""
    alias: str = ""
    service: str = "Unknown"
    peers: list[Peer] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    ts: int = 0
    error: str = ""


# cache do ultimo estado, p/ list_networks sem novo round-trip
_last: "State | None" = None


def _run_shim(timeout: int = 40) -> str:
    cmd = (
        f"{WMIEXEC} -shell-type powershell {TARGET} "
        f'"powershell -ExecutionPolicy Bypass -File {SHIM_PATH}"'
    )
    out = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return out.stdout + "\n" + out.stderr


def fetch_state(timeout: int = 40) -> State:
    # checa a VM antes de gastar o timeout do WMI
    try:
        import vmctl
        if not vmctl.is_running():
            return State(ok=False, vm_running=False, error="VM desligada")
    except Exception:  # noqa
        pass
    try:
        raw = _run_shim(timeout=timeout)
    except subprocess.TimeoutExpired:
        return State(ok=False, vm_running=True, error="timeout ao falar com a VM")
    except Exception as e:  # noqa
        return State(ok=False, vm_running=True, error=f"transporte: {e}")

    m = _MARK_RE.search(raw)
    if not m:
        if "rpc_s_access_denied" in raw:
            return State(ok=False, error="acesso negado (UAC/credencial)")
        if "No route to host" in raw or "Connection error" in raw:
            return State(ok=False, error="VM inalcançável (rede/tap)")
        return State(ok=False, error="shim não respondeu")

    # o WMI quebra linhas longas; junta tudo antes de parsear
    blob = re.sub(r"\s+", "", m.group(1))
    try:
        d = json.loads(blob)
    except json.JSONDecodeError as e:
        return State(ok=False, error=f"JSON inválido: {e}")

    st = State(
        ok=bool(d.get("ok")),
        vm_running=True,
        node_ip=d.get("node_ip") or "",
        hostname=d.get("hostname") or "",
        alias=d.get("alias") or "",
        service=d.get("service") or "Unknown",
        networks=list(d.get("networks", [])),
        ts=int(d.get("ts") or 0),
    )
    for p in d.get("peers", []):
        st.peers.append(Peer(ip=p.get("ip",""), mac=p.get("mac",""),
                             type=p.get("type","dynamic"), host=p.get("host","")))
    global _last
    _last = st
    return st


def list_networks() -> list[str]:
    """GUIDs das redes associadas, do ultimo estado obtido."""
    return list(_last.networks) if _last else []


if __name__ == "__main__":
    s = fetch_state()
    print("ok:", s.ok, "| erro:", s.error or "-")
    print("no:", s.hostname, s.node_ip, "| servico:", s.service)
    for p in s.peers:
        print(f"  peer {p.ip:16} {p.mac}")
