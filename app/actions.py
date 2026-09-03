"""
actions.py - write actions (phase 3/4) and active liveness.
- connect/disconnect: stops/starts RvControlSvc (the mesh's real power switch).
- leave_network: removes the network association (Networks {GUID} key).
- ping_sweep: measures online/offline straight from Linux (we have a route to 26.0.0.0/8).
Short commands go via -EncodedCommand; the heavy status stays in the shim.
"""
from __future__ import annotations
import base64, concurrent.futures, ipaddress
import socket, struct, os, select, time, threading
import backend  # reuses TARGET/WMIEXEC + the killable-subprocess registry

REGBASE = r"HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0"

# Liveness (ping sweep) safety limits. The sweep runs every 30s and must NEVER
# turn into a storm of processes that freezes the user's machine:
#  - Primary path is PROCESS-FREE: unprivileged ICMP sockets (no `ping` process at
#    all), so a storm is physically impossible -- there are zero ping processes.
#  - MAX_PING: hard cap on targets per sweep, whatever the roster holds.
#  - Fallback (only where ICMP sockets are denied) uses `ping -n` (no reverse DNS:
#    26.x has no PTR and would hang the resolver) bounded by a GLOBAL semaphore so
#    at most PING_WORKERS ping processes can ever exist system-wide.
MAX_PING = 300
PING_WORKERS = 16
_ICMP_ECHO = 8


def _run_ps(script: str, timeout: int = 60) -> tuple[bool, str]:
    """Run a PowerShell block on the VM via EncodedCommand (no escaping)."""
    b64 = base64.b64encode(script.encode("utf-16-le")).decode()
    cmd = (
        f"{backend.WMIEXEC} -shell-type powershell {backend.TARGET} "
        f'"powershell -EncodedCommand {b64}"'
    )
    rc, blob = backend.run_capture(cmd, timeout, shell=True)
    if rc == 124:
        return False, "timeout"
    if rc == 255:
        return False, blob or "cancelado"
    return ("<<<ACTOK>>>" in blob), blob


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
    """Change the node's name (Alias) that other peers see. Persists in the registry
    and restarts the service to re-announce to the mesh."""
    safe = new_name.replace('"', "").replace("'", "").strip()[:63]
    ps = (
        f'Set-ItemProperty "{REGBASE}" -Name Alias -Value "{safe}" -Type String;'
        'Restart-Service RvControlSvc -Force;'
        'Start-Sleep 3;'
        f'if((Get-ItemProperty "{REGBASE}").Alias -eq "{safe}"){{Write-Output "<<<ACTOK>>>"}}'
    )
    return _run_ps(ps, timeout)


def leave_network(guid: str, timeout: int = 60) -> tuple[bool, str]:
    """Remove the network association (leave the network). guid includes the {} braces."""
    ps = (
        f'$k="{REGBASE}\\Networks\\{guid}";'
        'if(Test-Path $k){Remove-Item $k -Recurse -Force;'
        'Restart-Service RvControlSvc -Force;'
        'Write-Output "<<<ACTOK>>>"}else{Write-Output "nao-existe"}'
    )
    return _run_ps(ps, timeout)


def _valid_targets(ips: list[str]) -> list[str]:
    """Keep valid IPv4, dedupe, and CAP at MAX_PING. Shield against a poisoned
    roster (bad dump) that would otherwise make the sweep ping thousands of IPs."""
    out: list[str] = []
    seen: set[str] = set()
    for ip in ips:
        if ip in seen:
            continue
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        seen.add(ip)
        out.append(ip)
        if len(out) >= MAX_PING:
            break
    return out


# ---- primary path: unprivileged ICMP, ZERO processes ----------------------
def _icmp_packet(seq: int) -> bytes:
    # ICMP echo request. On a SOCK_DGRAM/IPPROTO_ICMP socket the kernel fills in
    # the id and the checksum, so we send type=8, code=0, checksum=0, id=0.
    return struct.pack("!BBHHH", _ICMP_ECHO, 0, 0, 0, seq & 0xFFFF) + b"radmin-linux"


def _ping_sweep_icmp(ips: list[str], timeout: float = 1.0) -> dict[str, bool] | None:
    """Ping every IP through ONE non-blocking ICMP socket -- no `ping` process at
    all, so it can never storm. Returns ip->online, or None if the kernel denies
    unprivileged ICMP (then the caller falls back to the bounded subprocess path)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    except (PermissionError, OSError):
        return None
    res = {ip: False for ip in ips}
    try:
        s.setblocking(False)
        for i, ip in enumerate(ips):               # fire all echo requests (cheap)
            if backend._CANCEL.is_set():
                return res
            try:
                s.sendto(_icmp_packet(i), (ip, 0))
            except OSError:
                pass
        pending = set(ips)
        deadline = time.monotonic() + timeout
        while pending and time.monotonic() < deadline:
            if backend._CANCEL.is_set():
                break
            rem = deadline - time.monotonic()
            r, _, _ = select.select([s], [], [], min(0.2, max(0.0, rem)))
            if not r:
                continue
            try:
                data, addr = s.recvfrom(2048)
            except OSError:
                continue
            src = addr[0]
            if data and data[0] == 0 and src in res:   # type 0 = echo reply
                res[src] = True
                pending.discard(src)
        return res
    finally:
        s.close()


# ---- fallback: `ping` subprocess, capped by a GLOBAL semaphore -------------
# Only used where ICMP sockets are denied. The semaphore caps concurrent ping
# processes system-wide (belt-and-suspenders on top of the thread pool), so even
# this path can never storm.
_PING_GATE = threading.BoundedSemaphore(PING_WORKERS)


def _ping1(ip: str) -> tuple[str, bool]:
    if backend._CANCEL.is_set():
        return ip, False
    with _PING_GATE:                               # global ceiling on ping procs
        if backend._CANCEL.is_set():
            return ip, False
        # -n = no reverse DNS (26.x has no PTR and would hang the resolver).
        rc, _ = backend.run_capture(["ping", "-n", "-c1", "-W1", ip], timeout=3)
    return ip, (rc == 0)


def _ping_sweep_subprocess(ips: list[str]) -> dict[str, bool]:
    res: dict[str, bool] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PING_WORKERS) as ex:
        futs = [ex.submit(_ping1, ip) for ip in ips]
        for fut in concurrent.futures.as_completed(futs):
            if backend._CANCEL.is_set():
                for f in futs:
                    f.cancel()
                break
            ip, up = fut.result()
            res[ip] = up
    return res


def ping_sweep(ips: list[str], workers: int = PING_WORKERS) -> dict[str, bool]:
    """Return ip->online for the given IPs. Process-free ICMP when allowed,
    otherwise a bounded `ping` subprocess sweep. Both are capped and cancellable."""
    ips = _valid_targets(ips)
    if not ips:
        return {}
    res = _ping_sweep_icmp(ips)          # preferred: zero processes
    if res is None:
        res = _ping_sweep_subprocess(ips)  # fallback: hard-capped subprocess sweep
    return res


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        print(ping_sweep(sys.argv[2:]))
    else:
        print("usage: actions.py sweep <ip> [ip...]")
