"""
roster.py - persistent peer list seen over time.
The shim only sees ACTIVE peers (ARP). The roster accumulates whoever showed up,
keeps a local nickname (user override) and last_seen, and so shows offline too.
All local on Linux - does not touch Radmin (phase 2 = read only).
"""
from __future__ import annotations
import json, os, time, ipaddress
from pathlib import Path

CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "radmin-linux"
ROSTER_FILE = CONF_DIR / "roster.json"

# Roster cap. A bad dump may already have written thousands of fake IPs here
# (the cause of the ping storm that froze the host). Pruning on load heals that
# and keeps the list from exploding again. A real Radmin network is well below this.
MAX_ENTRIES = 512


def _valid_ip(s: str) -> bool:
    try:
        ipaddress.IPv4Address(s)
        return True
    except ValueError:
        return False


class Roster:
    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}   # ip -> {name, mac, last_seen}
        self.load()
        self.prune()

    def load(self) -> None:
        try:
            self.entries = json.loads(ROSTER_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            self.entries = {}

    def prune(self) -> None:
        """Sanitize the roster on load: drop invalid IPs and cut the excess,
        keeping the REAL peers (user nickname > seen in ARP (mac/host) > most
        recent). Heals installs already poisoned by a noisy dump."""
        internal = {k: v for k, v in self.entries.items() if k.startswith("__")}
        ips = {k: v for k, v in self.entries.items()
               if not k.startswith("__") and _valid_ip(k)}
        changed = len(ips) + len(internal) != len(self.entries)  # had junk/invalid

        if len(ips) > MAX_ENTRIES:
            def score(kv):
                _ip, e = kv
                return (
                    1 if (e.get("name") or "").strip() else 0,   # named by the user
                    1 if (e.get("mac") or e.get("host")) else 0,  # really seen (ARP)
                    int(e.get("last_seen") or 0),                 # most recent
                )
            ordered = sorted(ips.items(), key=score, reverse=True)[:MAX_ENTRIES]
            ips = dict(ordered)
            changed = True

        if changed:
            self.entries = {**internal, **ips}
            self.save()

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
        """manual nickname > NetBIOS hostname > name discovered in memory > IP"""
        e = self.entries.get(ip, {})
        return e.get("name") or e.get("host") or e.get("disc") or ip

    def set_name(self, ip: str, name: str) -> None:
        e = self.entries.setdefault(ip, {"name": "", "mac": "", "last_seen": 0})
        e["name"] = name
        self.save()

    def name_of(self, ip: str) -> str:
        return self.entries.get(ip, {}).get("name", "")

    def all_ips(self) -> list[str]:
        # ignore internal keys (e.g. __networks__)
        return [k for k in self.entries.keys() if not k.startswith("__")]

    def forget(self, ip: str) -> None:
        self.entries.pop(ip, None)
        self.save()

    # ---- network nicknames (multiple networks) ----
    def net_label(self, guid: str) -> str:
        """Network nickname, or a short GUID if there is none."""
        nets = self.entries.get("__networks__", {})
        name = nets.get(guid, "")
        if name:
            return name
        g = guid.strip("{}")
        return "Network " + g[:8]

    def set_net_label(self, guid: str, name: str) -> None:
        nets = self.entries.setdefault("__networks__", {})
        nets[guid] = name
        self.save()

    # ---- app settings (persisted under a __ key, ignored by all_ips/prune) ----
    def get_setting(self, key: str, default=None):
        return self.entries.get("__settings__", {}).get(key, default)

    def set_setting(self, key: str, value) -> None:
        s = self.entries.setdefault("__settings__", {})
        s[key] = value
        self.save()

    # ---- manual network groups (user assigns peers to networks by hand) ----
    def groups(self) -> list[dict]:
        """Ordered user-defined network groups: [{'id','name'}, ...]."""
        return list(self.entries.get("__groups__", []))

    def add_group(self, name: str) -> str:
        import uuid
        gid = "g" + uuid.uuid4().hex[:8]
        gl = self.entries.setdefault("__groups__", [])
        gl.append({"id": gid, "name": (name or "").strip() or "Network"})
        self.save()
        return gid

    def rename_group(self, gid: str, name: str) -> None:
        for g in self.entries.get("__groups__", []):
            if g["id"] == gid and (name or "").strip():
                g["name"] = name.strip()
        self.save()

    def remove_group(self, gid: str) -> None:
        self.entries["__groups__"] = [g for g in self.entries.get("__groups__", []) if g.get("id") != gid]
        for k, e in self.entries.items():          # unassign peers that were in it
            if not k.startswith("__") and isinstance(e, dict) and e.get("net") == gid:
                e.pop("net", None)
        self.entries.get("__collapsed__", {}).pop(gid, None)
        self.save()

    def group_name(self, gid: str) -> str:
        for g in self.entries.get("__groups__", []):
            if g.get("id") == gid:
                return g.get("name", "Network")
        return "Network"

    def group_of(self, ip: str) -> str | None:
        gid = self.entries.get(ip, {}).get("net")
        # ignore a stale assignment to a deleted group
        if gid and any(g.get("id") == gid for g in self.entries.get("__groups__", [])):
            return gid
        return None

    def assign(self, ip: str, gid: str | None) -> None:
        e = self.entries.setdefault(ip, {"name": "", "host": "", "mac": "", "last_seen": 0})
        if gid:
            e["net"] = gid
        else:
            e.pop("net", None)
        self.save()

    def is_collapsed(self, key: str) -> bool:
        return bool(self.entries.get("__collapsed__", {}).get(key, False))

    def set_collapsed(self, key: str, val: bool) -> None:
        c = self.entries.setdefault("__collapsed__", {})
        c[key] = bool(val)
        self.save()

    def ingest(self, discovered: dict) -> int:
        """Merge the discovered {ip: name} list into the roster. Does not overwrite
        a nickname the user already set. Stores the discovered name in 'disc'.
        Returns how many new IPs were added."""
        new_count = 0
        for ip, name in discovered.items():
            if ip not in self.entries:
                new_count += 1
            e = self.entries.setdefault(ip, {"name": "", "host": "", "mac": "", "last_seen": 0})
            if name:
                e["disc"] = name
        self.save()
        return new_count
