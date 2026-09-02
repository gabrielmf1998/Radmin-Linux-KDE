"""
config.py - configuracao central do Radmin-Linux (lado Python).
Fonte de verdade: variaveis de ambiente > ~/.config/radmin-linux/config.env > defaults.
O instalador escreve o config.env; sem ele, os defaults reproduzem o setup de dev.
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
    # env var tem prioridade, depois o arquivo, depois o default
    return os.environ.get(key) or _FILE.get(key) or default


# raiz da instalacao (dev: a bancada; instalado: ~/.local/share/radmin-linux)
HOME = _get("RADMIN_HOME", "/mnt/samsung-980pro/VMs/ntlite-bench")
VMDIR = _get("RADMIN_VMDIR", HOME)
VENV = _get("RADMIN_VENV", f"{HOME}/.recon-venv")

# rede / acesso a VM
HOST = _get("RADMIN_HOST", "192.168.137.1")
CRED = _get("RADMIN_CRED", "bench:bench")
TARGET = _get("RADMIN_TARGET", f"{CRED}@{HOST}")

# interface isolada host<->VM
TAP = _get("RADMIN_TAP", "tapradmin")
NMCON = _get("RADMIN_NMCON", "radmin-bridge")
ISO_MAC = _get("RADMIN_ISO_MAC", "52:54:00:26:00:02")

# caminhos derivados
PYTHON = f"{VENV}/bin/python"
WMIEXEC = f"{PYTHON} {VENV}/bin/wmiexec.py"
RUN_SCRIPT = _get("RADMIN_RUN", f"{VMDIR}/bench-run.sh")
VIEW_SCRIPT = _get("RADMIN_VIEW", f"{VMDIR}/bench-view.sh")

# caminhos na VM (Windows)
SHIM_PATH = _get("RADMIN_SHIM", r"C:\radmin-shim.ps1")
AGENT_DIR = _get("RADMIN_AGENT_DIR", r"C:\radmin-agent")


if __name__ == "__main__":
    for k in ("HOME", "VMDIR", "VENV", "HOST", "CRED", "TARGET", "TAP",
              "NMCON", "ISO_MAC", "WMIEXEC", "RUN_SCRIPT"):
        print(f"{k:12} = {globals()[k]}")
