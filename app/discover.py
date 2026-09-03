"""
discover.py - discovers the COMPLETE peer list of the network (online + offline),
the same one the Radmin GUI shows. It minidumps the GUI process in the VM,
downloads it and extracts the 26.x IPs (reliable) and the names (best-effort) from memory.

Heavy operation (~200MB): runs on demand / occasionally, not in the loop.
The result feeds the roster; the ping sweep then keeps online/offline.
"""
from __future__ import annotations
import os, re, base64, ipaddress
import backend

DUMP_VM = r"C:\radmin-agent\gui.dmp"
_BAD = {"AddressWidget", "StatusWidget", "NodeName", "CNodeWidget",
        "MS Shell Dlg 2", "Firewall", "width", "height"}

# Dump hardening: the GUI memory (~200MB) has LOTS of loose fragments that decode
# as "26.x". Without a cap that poisons the roster and turns into a ping storm
# (freezes the host). Real peers RECUR (list model + route + widget); heap garbage
# shows up once. If the cap is exceeded, filter by recurrence and truncate.
MAX_MEMBERS = 300   # a real Radmin network is small; above this it is noise
MIN_HITS = 2        # only applied when there is noise (distinct > MAX_MEMBERS)
# Memory guards for the extraction: a 200MB dump can hold millions of ASCII runs;
# building an unbounded list of them balloons RAM to GBs and FREEZES the host. Cap
# both the bytes read and the number of strings kept so RAM stays a few hundred MB.
MAX_DUMP_BYTES = 160 * 1024 * 1024
MAX_STRINGS = 400_000


def _is_mesh_ip(s: str) -> bool:
    """Valid IPv4 (octets 0-255) inside the Radmin mesh 26.0.0.0/8."""
    if not s.startswith("26."):
        return False
    try:
        return ipaddress.IPv4Address(s).packed[0] == 26
    except ValueError:
        return False


def _is_bad_name(cand: str) -> bool:
    if cand in _BAD:
        return True
    # Qt class/widget names: end in Widget/Item/Layout/Model, or C<Upper>
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
    rc, blob = backend.run_capture(cmd, timeout, shell=True)
    return "DUMPOK" in blob


def _download_dump(local_path: str, timeout: int = 60) -> bool:
    if backend._CANCEL.is_set():
        return False
    host = backend.TARGET.split("@")[-1]
    user, pw = backend.TARGET.split("@")[0].split(":", 1)
    try:
        from impacket.smbconnection import SMBConnection
        # socket timeout: otherwise a stalled download pins the worker at shutdown
        c = SMBConnection(host, host, timeout=timeout)
        c.login(user, pw)
        with open(local_path, "wb") as f:
            c.getFile("C$", "\\radmin-agent\\gui.dmp", f.write)
        # clean up the dump in the VM
        try:
            c.deleteFile("C$", "\\radmin-agent\\gui.dmp")
        except Exception:  # noqa
            pass
        c.close()
        return os.path.getsize(local_path) > 1_000_000
    except Exception:  # noqa
        return False


def _extract(dump_path: str) -> dict[str, str]:
    """Return {ip: name}. Name is empty when not correlated."""
    with open(dump_path, "rb") as f:
        data = f.read(MAX_DUMP_BYTES)      # cap the bytes read (bounds RAM)
    # UTF-16 strings in position order, but CAPPED (never build an unbounded list)
    strings = []
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){2,}', data):
        strings.append((m.start(), m.group().decode("utf-16-le")))
        if len(strings) >= MAX_STRINGS:
            break
    del data                                # free the big buffer before correlating
    ips: dict[str, str] = {}
    hits: dict[str, int] = {}   # how often each IP recurs in the dump
    for i, (pos, s) in enumerate(strings):
        if not _is_mesh_ip(s):
            continue
        hits[s] = hits.get(s, 0) + 1
        if s not in ips:
            ips[s] = ""
        if ips[s]:
            continue
        # name = the nearest preceding string that looks like a hostname
        for j in range(i - 1, max(0, i - 6), -1):
            cand = strings[j][1].strip()
            if _is_bad_name(cand) or _is_mesh_ip(cand):
                continue
            if re.match(r"^[A-Za-z][\w\-. ]{2,39}$", cand) and not cand.replace(".", "").isdigit():
                ips[s] = cand
                break
    # Heap noise: if the cap was exceeded, real peers are the ones that RECUR.
    # Keep only hits >= MIN_HITS and truncate to MAX_MEMBERS by most frequent.
    # (A small network passes intact; this only filters when the dump came dirty.)
    if len(ips) > MAX_MEMBERS:
        keep = [ip for ip in ips if hits[ip] >= MIN_HITS]
        keep.sort(key=lambda ip: hits[ip], reverse=True)
        keep = keep[:MAX_MEMBERS]
        ips = {ip: ips[ip] for ip in keep}
    return ips


def _scratch_dir() -> str:
    """Directory for the dump (~200MB). NEVER on tmpfs (RAM) - use a real disk.
    Prefers the user cache; falls back to /var/tmp; refuses tmpfs."""
    import shutil
    candidates = [
        os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "radmin-linux"),
        "/var/tmp/radmin-linux",
    ]
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            # /var/tmp and ~/.cache are normally real disk; tmpfs would be RAM
            st = os.statvfs(d)
            if st.f_blocks * st.f_frsize > 300 * 1024 * 1024:  # has space
                return d
        except OSError:
            continue
    return candidates[-1]


def discover_peers(scratch: str | None = None) -> dict[str, str]:
    """Complete {ip: name} list of the network. {} on failure. The dump goes to a
    real disk (never tmpfs), at low I/O priority so it never stalls the desktop."""
    if scratch is None:
        scratch = os.path.join(_scratch_dir(), "radmin-gui.dmp")
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
    # drop our own node and the gateway
    peers.pop("26.0.0.1", None)
    return peers


if __name__ == "__main__":
    import backend as _b
    p = discover_peers()
    print(f"peers discovered: {len(p)}")
    for ip, nm in sorted(p.items(), key=lambda x: tuple(int(o) for o in x[0].split('.'))):
        print(f"  {nm or '(no name)':24} {ip}")
