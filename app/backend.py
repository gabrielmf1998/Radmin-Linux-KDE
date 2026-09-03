"""
backend.py - talks to the shim in the Windows VM over WMI (impacket) and returns the state.
Read-only in this phase.
"""
from __future__ import annotations
import json, re, subprocess, time, os, shutil, threading
from dataclasses import dataclass, field

import config
VENV = config.VENV
WMIEXEC = config.WMIEXEC
TARGET = config.TARGET
SHIM_PATH = config.SHIM_PATH

_MARK_RE = re.compile(r"<<<RADMINJSON>>>\s*(.*?)\s*<<<END>>>", re.S)


@dataclass
class Peer:
    ip: str
    mac: str = ""
    type: str = "dynamic"
    host: str = ""          # NetBIOS hostname (the machine's real name)
    name: str = ""          # nickname set by the user (local override)
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


# cache of the last state, for list_networks without a new round-trip
_last: "State | None" = None

# live external subprocesses (wmiexec, ping, dump...), so shutdown can kill them and
# free the worker threads. _CANCEL is raised at shutdown: no new subprocess starts
# after that, and the live ones are killed -> the threads unblock and exit cleanly
# (otherwise Qt aborts with qFatal "QThread destroyed while running" during finalize).
_LIVE_PROCS: set = set()
_CANCEL = threading.Event()


def run_capture(cmd, timeout: int, shell: bool = False) -> tuple[int, str]:
    """Tracked and KILLABLE Popen. Returns (rc, combined_output). Honors _CANCEL
    (shutdown) and kills the child on timeout. cmd may be a list (shell=False) or a
    string (shell=True). rc conventions: 124=timeout, 255=cancelled/spawn error."""
    if _CANCEL.is_set():
        return 255, ""
    try:
        p = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    except OSError as e:
        return 255, str(e)
    _LIVE_PROCS.add(p)
    try:
        out, err = p.communicate(timeout=timeout)
        return (p.returncode if p.returncode is not None else 255), (out or "") + (err or "")
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            out, err = p.communicate(timeout=5)
        except Exception:  # noqa
            out, err = "", ""
        return 124, (out or "") + (err or "")
    finally:
        _LIVE_PROCS.discard(p)


def cancel_all() -> None:
    """Shutdown: prevent new subprocesses and kill all live ones, so worker
    threads blocked in communicate()/ping unblock and the app closes cleanly."""
    _CANCEL.set()
    for p in list(_LIVE_PROCS):
        try:
            p.kill()
        except Exception:  # noqa
            pass


def run_tracked(cmd: str, timeout: int) -> str:
    """Tracked subprocess.run: registers the process so it can be killed at shutdown."""
    if _CANCEL.is_set():
        return ""
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    _LIVE_PROCS.add(p)
    try:
        out, err = p.communicate(timeout=timeout)
        return (out or "") + "\n" + (err or "")
    except subprocess.TimeoutExpired:
        p.kill()
        try: p.communicate(timeout=5)
        except Exception: pass  # noqa
        raise
    finally:
        _LIVE_PROCS.discard(p)


def _run_shim(timeout: int = 40) -> str:
    cmd = (
        f"{WMIEXEC} -shell-type powershell {TARGET} "
        f'"powershell -ExecutionPolicy Bypass -File {SHIM_PATH}"'
    )
    return run_tracked(cmd, timeout)


def fetch_state(timeout: int = 40) -> State:
    # check the VM before spending the WMI timeout
    try:
        import vmctl
        if not vmctl.is_running():
            return State(ok=False, vm_running=False, error="VM is off")
    except Exception:  # noqa
        pass
    try:
        raw = _run_shim(timeout=timeout)
    except subprocess.TimeoutExpired:
        return State(ok=False, vm_running=True, error="timed out talking to the VM")
    except Exception as e:  # noqa
        return State(ok=False, vm_running=True, error=f"transport: {e}")

    # From here the VM PROCESS is alive (it passed the is_running check above). If
    # WMI/shim still does not answer, the VM is BOOTING (Windows startup) -- it is
    # NOT off. Hence vm_running=True: the UI shows "Starting..." instead of
    # "VM is off" (otherwise the user thinks the VM failed to come up).
    m = _MARK_RE.search(raw)
    if not m:
        if "rpc_s_access_denied" in raw:
            return State(ok=False, vm_running=True, error="access denied (UAC/credentials)")
        if "No route to host" in raw or "Connection error" in raw:
            return State(ok=False, vm_running=True, error="VM starting (network coming up)")
        return State(ok=False, vm_running=True, error="VM starting (waiting for Windows)")

    # WMI wraps long lines; join everything before parsing
    blob = re.sub(r"\s+", "", m.group(1))
    try:
        d = json.loads(blob)
    except json.JSONDecodeError as e:
        return State(ok=False, vm_running=True, error=f"invalid JSON: {e}")

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
    print("ok:", s.ok, "| error:", s.error or "-")
    print("node:", s.hostname, s.node_ip, "| service:", s.service)
    for p in s.peers:
        print(f"  peer {p.ip:16} {p.mac}")
