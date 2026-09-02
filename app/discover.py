"""
discover.py - descobre a lista COMPLETA de peers da rede (online + offline),
a mesma que a GUI do Radmin mostra. Faz um minidump do processo da GUI na VM,
baixa e extrai os IPs 26.x (confiavel) e os nomes (best-effort) da memoria.

Operacao pesada (~200MB): roda sob demanda / ocasionalmente, nao no loop.
O resultado alimenta o roster; o ping sweep depois mantem online/offline.
"""
from __future__ import annotations
import io, os, re, subprocess, base64
import backend

DUMP_VM = r"C:\radmin-agent\gui.dmp"
_IP_RE = re.compile(r"^26\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_BAD = {"AddressWidget", "StatusWidget", "NodeName", "CNodeWidget",
        "MS Shell Dlg 2", "Firewall", "width", "height"}


def _is_bad_name(cand: str) -> bool:
    if cand in _BAD:
        return True
    # nomes de classe/widget Qt: terminam em Widget/Item/Layout/Model, ou C<Maius>
    if re.search(r"(Widget|Item|Layout|Model|Object|Frame|Label|Button)$", cand):
        return True
    if re.match(r"^C[A-Z]", cand):   # CNetworkWidget, CNodeWidget...
        return True
    return False


def _make_dump_on_vm(timeout: int = 90) -> bool:
    ps = (
        '$p=(Get-Process RvRvpnGui).Id;'
        f'Remove-Item "{DUMP_VM}" -Force -EA SilentlyContinue;'
        f'rundll32.exe C:\\Windows\\System32\\comsvcs.dll, MiniDump $p "{DUMP_VM}" full;'
        'Start-Sleep 3;'
        f'if(Test-Path "{DUMP_VM}"){{Write-Output "DUMPOK"}}'
    )
    b64 = base64.b64encode(ps.encode("utf-16-le")).decode()
    cmd = (f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
           f'"powershell -EncodedCommand {b64}"')
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return "DUMPOK" in (out.stdout + out.stderr)
    except Exception:  # noqa
        return False


def _download_dump(local_path: str, timeout: int = 60) -> bool:
    host = backend.TARGET.split("@")[-1]
    user, pw = backend.TARGET.split("@")[0].split(":", 1)
    try:
        from impacket.smbconnection import SMBConnection
        c = SMBConnection(host, host)
        c.login(user, pw)
        with open(local_path, "wb") as f:
            c.getFile("C$", "\\radmin-agent\\gui.dmp", f.write)
        # limpa o dump na VM
        try:
            c.deleteFile("C$", "\\radmin-agent\\gui.dmp")
        except Exception:  # noqa
            pass
        c.close()
        return os.path.getsize(local_path) > 1_000_000
    except Exception:  # noqa
        return False


def _extract(dump_path: str) -> dict[str, str]:
    """Retorna {ip: nome}. Nome vazio quando nao correlacionado."""
    data = open(dump_path, "rb").read()
    # todas as strings UTF-16 em ordem de posicao
    strings = [(m.start(), m.group().decode("utf-16-le"))
               for m in re.finditer(rb'(?:[\x20-\x7e]\x00){2,}', data)]
    ips: dict[str, str] = {}
    for i, (pos, s) in enumerate(strings):
        if not _IP_RE.match(s):
            continue
        if s not in ips:
            ips[s] = ""
        if ips[s]:
            continue
        # nome = string anterior plausivel de hostname
        for j in range(i - 1, max(0, i - 6), -1):
            cand = strings[j][1].strip()
            if _is_bad_name(cand) or _IP_RE.match(cand):
                continue
            if re.match(r"^[A-Za-z][\w\-. ]{2,39}$", cand) and not cand.replace(".", "").isdigit():
                ips[s] = cand
                break
    return ips


def discover_peers(scratch: str = "/tmp/radmin-gui.dmp") -> dict[str, str]:
    """Lista completa {ip: nome} da rede. {} se falhar."""
    if not _make_dump_on_vm():
        return {}
    if not _download_dump(scratch):
        return {}
    try:
        peers = _extract(scratch)
    finally:
        try:
            os.remove(scratch)
        except OSError:
            pass
    # remove o proprio no e o gateway
    peers.pop("26.0.0.1", None)
    return peers


if __name__ == "__main__":
    import backend as _b
    p = discover_peers()
    print(f"peers descobertos: {len(p)}")
    for ip, nm in sorted(p.items(), key=lambda x: tuple(int(o) for o in x[0].split('.'))):
        print(f"  {nm or '(sem nome)':24} {ip}")
