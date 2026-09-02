"""
roster.py - lista persistente de peers vista ao longo do tempo.
A shim so ve peers ATIVOS (ARP). O roster acumula quem ja apareceu, guarda
apelido local (override do usuario) e last_seen, e assim mostra offline tambem.
Tudo local no Linux - nao toca no Radmin (fase 2 = so leitura).
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "radmin-linux"
ROSTER_FILE = CONF_DIR / "roster.json"


class Roster:
    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}   # ip -> {name, mac, last_seen}
        self.load()

    def load(self) -> None:
        try:
            self.entries = json.loads(ROSTER_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            self.entries = {}

    def save(self) -> None:
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            ROSTER_FILE.write_text(json.dumps(self.entries, indent=2))
        except OSError:
            pass

    def seen(self, ip: str, mac: str = "", host: str = "") -> None:
        e = self.entries.setdefault(ip, {"name": "", "host": "", "mac": "", "last_seen": 0})
        e["last_seen"] = int(time.time())
        if mac:
            e["mac"] = mac
        if host:
            e["host"] = host

    def host_of(self, ip: str) -> str:
        return self.entries.get(ip, {}).get("host", "")

    def label_of(self, ip: str) -> str:
        """apelido > hostname NetBIOS > IP"""
        e = self.entries.get(ip, {})
        return e.get("name") or e.get("host") or ip

    def set_name(self, ip: str, name: str) -> None:
        e = self.entries.setdefault(ip, {"name": "", "mac": "", "last_seen": 0})
        e["name"] = name
        self.save()

    def name_of(self, ip: str) -> str:
        return self.entries.get(ip, {}).get("name", "")

    def all_ips(self) -> list[str]:
        return list(self.entries.keys())

    def forget(self, ip: str) -> None:
        self.entries.pop(ip, None)
        self.save()
