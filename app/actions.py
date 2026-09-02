"""
actions.py - acoes de escrita (fase 3/4) e liveness ativo.
- connect/disconnect: para/inicia o RvControlSvc (o botao power real da mesh).
- leave_network: remove a associacao de rede (chave Networks {GUID}).
- ping_sweep: mede online/offline direto do Linux (temos rota p/ 26.0.0.0/8).
Comandos curtos vao por -EncodedCommand; o status pesado fica na shim.
"""
from __future__ import annotations
import base64, subprocess, concurrent.futures, os
import backend  # reusa TARGET/WMIEXEC

REGBASE = r"HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0"


def _run_ps(script: str, timeout: int = 60) -> tuple[bool, str]:
    """Roda um bloco PowerShell na VM via EncodedCommand (sem escaping)."""
    b64 = base64.b64encode(script.encode("utf-16-le")).decode()
    cmd = (
        f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
        f'"powershell -EncodedCommand {b64}"'
    )
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        blob = out.stdout + out.stderr
        ok = "<<<ACTOK>>>" in blob
        return ok, blob
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:  # noqa
        return False, str(e)


def connect(timeout: int = 60) -> tuple[bool, str]:
    ps = (
        f'Set-ItemProperty "{REGBASE}" -Name PowerOn -Value 1 -Type DWord;'
        'net start RvControlSvc 2>&1 | Out-Null;'
        'Start-Sleep 3;'
        'if((Get-Service RvControlSvc).Status -eq "Running"){Write-Output "<<<ACTOK>>>"}'
    )
    return _run_ps(ps, timeout)


def disconnect(timeout: int = 60) -> tuple[bool, str]:
    ps = (
        f'Set-ItemProperty "{REGBASE}" -Name PowerOn -Value 0 -Type DWord;'
        'net stop RvControlSvc 2>&1 | Out-Null;'
        'Start-Sleep 2;'
        'if((Get-Service RvControlSvc).Status -eq "Stopped"){Write-Output "<<<ACTOK>>>"}'
    )
    return _run_ps(ps, timeout)


def rename_node(new_name: str, timeout: int = 60) -> tuple[bool, str]:
    """Muda o nome (Alias) do no que os outros peers veem. Persiste no registro
    e reinicia o servico p/ re-anunciar a mesh."""
    safe = new_name.replace('"', "").replace("'", "").strip()[:63]
    ps = (
        f'Set-ItemProperty "{REGBASE}" -Name Alias -Value "{safe}" -Type String;'
        'Restart-Service RvControlSvc -Force;'
        'Start-Sleep 3;'
        f'if((Get-ItemProperty "{REGBASE}").Alias -eq "{safe}"){{Write-Output "<<<ACTOK>>>"}}'
    )
    return _run_ps(ps, timeout)


def leave_network(guid: str, timeout: int = 60) -> tuple[bool, str]:
    """Remove a associacao de rede (sai da rede). guid inclui as chaves {}."""
    ps = (
        f'$k="{REGBASE}\\Networks\\{guid}";'
        'if(Test-Path $k){Remove-Item $k -Recurse -Force;'
        'Restart-Service RvControlSvc -Force;'
        'Write-Output "<<<ACTOK>>>"}else{Write-Output "nao-existe"}'
    )
    return _run_ps(ps, timeout)


def _ping1(ip: str) -> tuple[str, bool]:
    try:
        r = subprocess.run(["ping", "-c1", "-W1", ip],
                           capture_output=True, timeout=3)
        return ip, (r.returncode == 0)
    except Exception:  # noqa
        return ip, False


def ping_sweep(ips: list[str], workers: int = 32) -> dict[str, bool]:
    """Pinga todos os IPs em paralelo do Linux. Retorna ip->online."""
    if not ips:
        return {}
    res: dict[str, bool] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for ip, up in ex.map(_ping1, ips):
            res[ip] = up
    return res


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        print(ping_sweep(sys.argv[2:]))
    else:
        print("uso: actions.py sweep <ip> [ip...]")
