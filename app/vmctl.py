"""
vmctl.py - controla a VM inteira do lado Linux (nao o Radmin, a maquina).
Para o usuario da UI fake, "ligar/desligar Radmin Linux" = ligar/desligar a VM.
Usa o monitor do QEMU (socket) e os scripts da bancada.
"""
from __future__ import annotations
import os, socket, subprocess, time

import config
VMDIR = config.VMDIR
MONITOR = os.path.join(VMDIR, "monitor.sock")
PIDFILE = os.path.join(VMDIR, "qemu.pid")
RUN = config.RUN_SCRIPT
PREFLIGHT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preflight.sh")


def is_running() -> bool:
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, FileNotFoundError):
        return False


def _monitor(cmd: str, timeout: float = 8) -> str:
    """Manda um comando ao monitor do QEMU e devolve a resposta."""
    if not os.path.exists(MONITOR):
        return ""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(MONITOR)
        time.sleep(0.2)
        s.recv(4096)  # banner
        s.sendall((cmd + "\n").encode())
        time.sleep(0.4)
        data = s.recv(8192)
        s.close()
        return data.decode(errors="replace")
    except OSError:
        return ""


def power_off(timeout: int = 60) -> bool:
    """Desliga a VM (ACPI). Espera ela sair de verdade."""
    if not is_running():
        return True
    _monitor("system_powerdown")
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return True
    for _ in range(timeout):
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(1)
    return False  # nao desligou no prazo


def power_off_hard() -> bool:
    """Ultimo recurso: mata o processo do QEMU."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 9)
        os.remove(PIDFILE)
        return True
    except (OSError, ValueError, FileNotFoundError):
        return True


def power_on() -> bool:
    """Liga a VM via preflight (que auto-repara a pilha)."""
    if is_running():
        return True
    try:
        subprocess.Popen(["bash", PREFLIGHT, "-q"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def is_responsive(timeout: float = 3) -> bool:
    """A VM responde na rede? (ping ao host da VM)."""
    host = HOST_IP()
    try:
        r = subprocess.run(["ping", "-c1", "-W", str(int(timeout)), host],
                           capture_output=True, timeout=timeout + 2)
        return r.returncode == 0
    except Exception:  # noqa
        return False


def HOST_IP() -> str:
    import config
    return config.HOST


def recover() -> str:
    """Watchdog: se o processo esta vivo mas a VM nao responde (travada),
    forca desligar e religar. Retorna o que fez."""
    if not is_running():
        power_on()
        return "started"
    if is_responsive():
        return "ok"
    # processo vivo mas sem resposta = travada
    if not power_off(timeout=30):
        power_off_hard()
    power_on()
    return "recovered"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        a = sys.argv[1]
        if a == "status":
            print("running" if is_running() else "stopped")
        elif a == "off":
            print("off ok" if power_off() else "off falhou")
        elif a == "on":
            print("on ok" if power_on() else "on falhou")
    else:
        print("uso: vmctl.py status|on|off")
