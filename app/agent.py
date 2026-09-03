"""
agent.py - dispara os scripts do agente na VM e le status/updates.
Cada funcao roda um .ps1 de C:\\radmin-agent via WMI e devolve o resultado.
"""
from __future__ import annotations
import base64, json, re
import backend

import config
AGENT_DIR = config.AGENT_DIR
_UPD_RE = re.compile(r"<<<UPD>>>\s*(.*?)\s*<<<END>>>", re.S)
_HEALTH_RE = re.compile(r"<<<HEALTH>>>\s*(.*?)\s*<<<END>>>", re.S)


def _run_file(ps_path: str, timeout: int = 90) -> str:
    cmd = (
        f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
        f'"powershell -ExecutionPolicy Bypass -File {ps_path}"'
    )
    rc, blob = backend.run_capture(cmd, timeout, shell=True)
    if rc == 124:
        return "timeout"
    if rc == 255:
        return blob or "cancelado"
    return blob


def orchestrate_net(timeout: int = 120) -> tuple[bool, str]:
    out = _run_file(rf"{AGENT_DIR}\net-orchestrator.ps1", timeout)
    # accept the English marker, and the legacy pt-BR one until the VM agent is redeployed
    ok = ("connectivity ready" in out) or ("conectividade pronta" in out)
    return ok, out


def power_guard(timeout: int = 60) -> tuple[bool, str]:
    out = _run_file(rf"{AGENT_DIR}\power-guard.ps1", timeout)
    return ("=== OK ===" in out), out


def check_update(install: bool = False, timeout: int = 300) -> dict:
    flag = "" if install else "-CheckOnly"
    cmd = (
        f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
        f'"powershell -ExecutionPolicy Bypass -File {AGENT_DIR}\\radmin-update.ps1 {flag}"'
    )
    rc, blob = backend.run_capture(cmd, timeout, shell=True)
    if rc in (124, 255):
        return {"error": "timeout" if rc == 124 else "cancelado"}
    m = _UPD_RE.search(blob)
    if not m:
        return {"error": "sem resposta do updater"}
    try:
        return json.loads(re.sub(r"\s+", "", m.group(1)))
    except json.JSONDecodeError as e:
        return {"error": f"json: {e}"}


def health(heal: bool = False, timeout: int = 120) -> dict:
    """Diagnostico (e auto-reparo se heal=True) completo da VM. Devolve dict."""
    flag = "-Heal" if heal else ""
    cmd = (
        f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
        f'"powershell -ExecutionPolicy Bypass -File {AGENT_DIR}\\health.ps1 {flag}"'
    )
    rc, blob = backend.run_capture(cmd, timeout, shell=True)
    if rc in (124, 255):
        msg = "timeout" if rc == 124 else "cancelado"
        return {"error": msg, "all_ok": False, "checks": []}
    m = _HEALTH_RE.search(blob)
    if not m:
        return {"error": "sem resposta do health", "all_ok": False, "checks": []}
    try:
        return json.loads(re.sub(r"\s+", "", m.group(1)))
    except json.JSONDecodeError as e:
        return {"error": f"json: {e}", "all_ok": False, "checks": []}


def agent_installed(timeout: int = 40) -> bool:
    """Ha tarefas RadminAgent registradas na VM?"""
    ps = 'if(schtasks /query /tn "RadminAgent-Net"){Write-Output "SIM"}'
    b64 = base64.b64encode(ps.encode("utf-16-le")).decode()
    cmd = (
        f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
        f'"powershell -EncodedCommand {b64}"'
    )
    rc, blob = backend.run_capture(cmd, timeout, shell=True)
    return "SIM" in blob


if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "check"
    if a == "net":
        ok, log = orchestrate_net(); print("net ok:", ok)
    elif a == "power":
        ok, log = power_guard(); print("power ok:", ok)
    elif a == "installed":
        print("agent installed:", agent_installed())
    else:
        print(check_update(install=False))
