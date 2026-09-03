"""
config.py - central configuration for Radmin-Linux (Python side).
Source of truth: environment variables > ~/.config/radmin-linux/config.env > defaults.
The installer writes config.env; without it, the defaults reproduce the dev setup.
"""
from __future__ import annotations
import os
from pathlib import Path

CONFIG_ENV = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "radmin-linux" / "config.env"


def _load_env_file() -> dict[str, str]:
    vals: dict[str, str] = {}
    try:
        for line in CONFIG_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


_FILE = _load_env_file()


def _get(key: str, default: str) -> str:
    # env var wins, then the file, then the default
    return os.environ.get(key) or _FILE.get(key) or default


# install root (dev: the bench; installed: ~/.local/share/radmin-linux)
HOME = _get("RADMIN_HOME", "/mnt/samsung-980pro/VMs/ntlite-bench")
VMDIR = _get("RADMIN_VMDIR", HOME)
VENV = _get("RADMIN_VENV", f"{HOME}/.recon-venv")

# network / VM access
HOST = _get("RADMIN_HOST", "192.168.137.1")
CRED = _get("RADMIN_CRED", "bench:bench")
TARGET = _get("RADMIN_TARGET", f"{CRED}@{HOST}")

# interface isolada host<->VM
TAP = _get("RADMIN_TAP", "tapradmin")
NMCON = _get("RADMIN_NMCON", "radmin-bridge")
ISO_MAC = _get("RADMIN_ISO_MAC", "52:54:00:26:00:02")

# derived paths
PYTHON = f"{VENV}/bin/python"
WMIEXEC = f"{PYTHON} {VENV}/bin/wmiexec.py"
RUN_SCRIPT = _get("RADMIN_RUN", f"{VMDIR}/bench-run.sh")
VIEW_SCRIPT = _get("RADMIN_VIEW", f"{VMDIR}/bench-view.sh")

# paths in the VM (Windows)
SHIM_PATH = _get("RADMIN_SHIM", r"C:\radmin-shim.ps1")
AGENT_DIR = _get("RADMIN_AGENT_DIR", r"C:\radmin-agent")

# VM footprint — kept small so it never hurts the host (declared in the UI)
VM_RAM = _get("RADMIN_VM_RAM", "1024")   # MB
VM_SMP = _get("RADMIN_VM_SMP", "1")      # vCPUs


def vm_footprint() -> str:
    """Human label for the header/About, e.g. '1 GB · 1 CPU' or '768 MB · 1 CPU'."""
    try:
        ram = int(VM_RAM)
        r = f"{ram // 1024} GB" if ram >= 1024 and ram % 1024 == 0 else f"{ram} MB"
    except ValueError:
        r = f"{VM_RAM} MB"
    return f"{r} · {VM_SMP} CPU"


if __name__ == "__main__":
    for k in ("HOME", "VMDIR", "VENV", "HOST", "CRED", "TARGET", "TAP",
              "NMCON", "ISO_MAC", "WMIEXEC", "RUN_SCRIPT"):
        print(f"{k:12} = {globals()[k]}")
