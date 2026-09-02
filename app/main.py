#!/usr/bin/env python3
"""
Radmin VPN (Linux) - clone so-leitura da GUI, alimentado pela shim na VM Windows.
Fase 2: mostra no local, status do servico e peers (online via ARP, offline via
roster). Apelido de peer e local. Nada aqui altera o Radmin real.
"""
from __future__ import annotations
import sys, os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QMenuBar, QMenu, QSystemTrayIcon, QInputDialog,
    QStyle, QSizePolicy,
)
from PySide6.QtGui import QAction, QColor, QFont, QCursor
from PySide6.QtCore import Qt, QThread, Signal, QTimer

sys.path.insert(0, os.path.dirname(__file__))
import backend
import actions
import agent
import vmctl
import icons
from roster import Roster

POLL_MS = 30000    # refresh completo (shim) a cada 30s
PING_MS = 30000    # liveness (ping sweep) a cada 30s
HEALTH_MS = 120000 # diagnostico + auto-heal a cada 2 min

QSS = """
* { color: #d9dde0; font-family: 'Segoe UI','Noto Sans',sans-serif; }
#root { background: #1d2023; }
#header { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
          stop:0 #163243, stop:1 #0d1c27); }
#logoText { color: #eaf6fa; font-size: 15px; font-weight: 700;
            letter-spacing: 2px; }
#menubar { background: #12262f; color: #c3ccd1; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected { background: #1f4a5f; }
QMenu { background: #22282c; border: 1px solid #333c42; }
QMenu::item:selected { background: #1f4a5f; }
#card { background: #232a2f; border-bottom: 1px solid #10151a; }
#nodeName { font-size: 14px; font-weight: 700; color: #f0f3f5; }
#nodeIp   { font-size: 13px; color: #8fa0aa; }
#badge { background: #2f6b33; color: #d6f5d8; border-radius: 8px;
         padding: 1px 10px; font-size: 11px; font-weight: 600; }
#badgeOff { background: #5a3030; color: #f2d6d6; border-radius: 8px;
            padding: 1px 10px; font-size: 11px; font-weight: 600; }
QScrollArea { border: none; background: #1a1d20; }
#list { background: #1a1d20; }
.peer { background: #1a1d20; }
.peerName { font-size: 13px; color: #e2e6e9; }
.peerIp   { font-size: 12px; color: #8a99a2; }
#status { background: #12262f; color: #7f8c93; font-size: 11px; padding: 3px 8px; }
QScrollBar:vertical { background: #16191c; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a444b; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


class Fetcher(QThread):
    got = Signal(object)

    def run(self):
        self.got.emit(backend.fetch_state())


class Pinger(QThread):
    """Liveness ativo: pinga a lista de IPs conhecidos direto do Linux."""
    done = Signal(object)

    def __init__(self, ips):
        super().__init__()
        self.ips = ips

    def run(self):
        self.done.emit(actions.ping_sweep(self.ips))


class ActionWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        ok, log = self.fn()
        self.done.emit(ok, log)


class HealthWorker(QThread):
    """Diagnostico + auto-heal em background."""
    done = Signal(object)

    def __init__(self, heal):
        super().__init__()
        self.heal = heal

    def run(self):
        self.done.emit(agent.health(heal=self.heal))


class DiscoverWorker(QThread):
    """Descobre a lista completa de peers (dump da GUI) - pesado, ocasional."""
    done = Signal(object)

    def run(self):
        import discover
        self.done.emit(discover.discover_peers())


class PeerRow(QFrame):
    def __init__(self, ip, name, online, on_rename):
        super().__init__()
        self.ip = ip
        self.setProperty("class", "peer")
        self.setObjectName("peerRow")
        self.setFixedHeight(34)
        self._online = online
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)

        self.sig = QLabel()
        self.sig.setPixmap(icons.signal_pixmap(online, 18))
        self.sig.setFixedWidth(20)
        lay.addWidget(self.sig)

        self.nameLbl = QLabel(name or ip)
        self.nameLbl.setProperty("class", "peerName")
        if not online:
            self.nameLbl.setStyleSheet("color:#6b7378;")
        lay.addWidget(self.nameLbl, 1)

        self.ipLbl = QLabel(ip)
        self.ipLbl.setProperty("class", "peerIp")
        self.ipLbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.ipLbl)

        self._on_rename = on_rename

    def mouseDoubleClickEvent(self, e):
        self._on_rename(self.ip)

    def enterEvent(self, e):
        self.setStyleSheet(".peer{background:#243139;} #peerRow{background:#243139;}")

    def leaveEvent(self, e):
        self.setStyleSheet("")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.roster = Roster()
        self.setWindowTitle("Radmin VPN")
        self.setWindowIcon(icons.logo_icon(64))
        self.resize(300, 480)
        self._fetcher = None
        self._pinger = None
        self._action = None
        self._busy = False
        self._closing = False
        self._last_service = "Unknown"
        self._vm_running = False
        self._node_ip = ""
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)
        self.pingtimer = QTimer(self)
        self.pingtimer.timeout.connect(self.ping_now)
        self.pingtimer.start(PING_MS)
        self._health = None
        self._last_health = None
        self._discover = None
        self.healthtimer = QTimer(self)
        self.healthtimer.timeout.connect(self.health_now)
        self.healthtimer.start(HEALTH_MS)
        self.refresh()
        # descobre a lista completa de peers logo apos abrir (uma vez)
        QTimer.singleShot(8000, self.discover_now)

    # ---------- layout ----------
    def _build(self):
        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        # menubar
        mb = QMenuBar(); mb.setObjectName("menubar")
        for name in ("System", "Network", "Help"):
            m = QMenu(name, mb)
            if name == "System":
                a = QAction("Refresh now", self); a.triggered.connect(self.refresh); m.addAction(a)
                m.addSeparator()
                self.actVmOn = QAction("Turn VM on", self)
                self.actVmOn.triggered.connect(self.do_vm_on); m.addAction(self.actVmOn)
                self.actVmOff = QAction("Turn VM off", self)
                self.actVmOff.triggered.connect(self.do_vm_off); m.addAction(self.actVmOff)
                m.addSeparator()
                ah = QAction("Full diagnostics (auto-repair)", self)
                ah.triggered.connect(self.do_health); m.addAction(ah)
                au = QAction("Check for Radmin update…", self)
                au.triggered.connect(self.do_check_update); m.addAction(au)
                ao = QAction("Repair network (orchestrator)", self)
                ao.triggered.connect(self.do_orchestrate); m.addAction(ao)
                ai = QAction("Install/repair agent on VM", self)
                ai.triggered.connect(self.do_install_agent); m.addAction(ai)
                m.addSeparator()
                q = QAction("Quit", self); q.triggered.connect(QApplication.quit); m.addAction(q)
            elif name == "Network":
                self.actConnect = QAction("Connect", self)
                self.actConnect.triggered.connect(self.do_connect); m.addAction(self.actConnect)
                self.actDisconnect = QAction("Disconnect", self)
                self.actDisconnect.triggered.connect(self.do_disconnect); m.addAction(self.actDisconnect)
                m.addSeparator()
                self.actRename = QAction("Rename this node…", self)
                self.actRename.triggered.connect(self.do_rename_node); m.addAction(self.actRename)
                self.actSync = QAction("Sync network members", self)
                self.actSync.triggered.connect(self.discover_now); m.addAction(self.actSync)
                m.addSeparator()
                self.actLeave = QAction("Leave network…", self)
                self.actLeave.triggered.connect(self.do_leave); m.addAction(self.actLeave)
                self.actJoin = QAction("Join a network…", self)
                self.actJoin.triggered.connect(self.do_join); m.addAction(self.actJoin)
                self.actCreate = QAction("Create network…", self)
                self.actCreate.triggered.connect(self.do_create); m.addAction(self.actCreate)
            elif name == "Help":
                a = QAction("About", self); a.triggered.connect(self._about); m.addAction(a)
            mb.addMenu(m)
        v.addWidget(mb)

        # header com logo
        header = QWidget(); header.setObjectName("header"); header.setFixedHeight(46)
        hl = QHBoxLayout(header); hl.setContentsMargins(12, 0, 12, 0); hl.setSpacing(8)
        logo = QLabel(); logo.setPixmap(icons.logo_pixmap(26)); hl.addWidget(logo)
        t = QLabel("RADMIN VPN"); t.setObjectName("logoText"); hl.addWidget(t)
        hl.addStretch(1)
        v.addWidget(header)

        # card do no
        card = QWidget(); card.setObjectName("card"); card.setFixedHeight(72)
        cl = QHBoxLayout(card); cl.setContentsMargins(14, 8, 14, 8); cl.setSpacing(12)
        self.power = QLabel(); self.power.setPixmap(icons.power_pixmap(False, 48))
        self.power.setCursor(QCursor(Qt.PointingHandCursor))
        self.power.setToolTip("Click to turn the VM on / off")
        self.power.mousePressEvent = lambda e: self.toggle_power()
        cl.addWidget(self.power)
        box = QVBoxLayout(); box.setSpacing(2)
        self.nodeName = QLabel("—"); self.nodeName.setObjectName("nodeName")
        self.nodeName.setCursor(QCursor(Qt.PointingHandCursor))
        self.nodeName.setToolTip("Double-click to rename this node")
        self.nodeName.mouseDoubleClickEvent = lambda e: self.do_rename_node()
        self.nodeIp = QLabel("—"); self.nodeIp.setObjectName("nodeIp")
        rowb = QHBoxLayout(); rowb.setSpacing(6)
        self.badge = QLabel("Offline"); self.badge.setObjectName("badgeOff")
        self.badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        rowb.addWidget(self.badge); rowb.addStretch(1)
        box.addWidget(self.nodeName); box.addWidget(self.nodeIp); box.addLayout(rowb)
        cl.addLayout(box, 1)
        v.addWidget(card)

        # lista de peers
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.listw = QWidget(); self.listw.setObjectName("list")
        self.listv = QVBoxLayout(self.listw)
        self.listv.setContentsMargins(0, 4, 0, 4); self.listv.setSpacing(0)
        self.listv.addStretch(1)
        self.scroll.setWidget(self.listw)
        v.addWidget(self.scroll, 1)

        # barra de status
        self.status = QLabel("iniciando…"); self.status.setObjectName("status")
        v.addWidget(self.status)

        self.setStyleSheet(QSS)
        self._build_tray()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(icons.logo_icon(64), self)
        self.tray.setToolTip("Radmin VPN (Linux)")
        menu = QMenu()
        show = QAction("Show", self); show.triggered.connect(self._show_raise); menu.addAction(show)
        menu.addSeparator()
        # controle total pela bandeja — o usuario nunca toca na VM
        self.trayPower = QAction("Turn VM on/off", self)
        self.trayPower.triggered.connect(self.toggle_power); menu.addAction(self.trayPower)
        self.trayConn = QAction("Connect / Disconnect", self)
        self.trayConn.triggered.connect(self._tray_toggle_conn); menu.addAction(self.trayConn)
        menu.addSeparator()
        d = QAction("Full diagnostics (repair)", self); d.triggered.connect(self.do_health); menu.addAction(d)
        u = QAction("Check for update", self); u.triggered.connect(self.do_check_update); menu.addAction(u)
        s = QAction("Sync members", self); s.triggered.connect(self.discover_now); menu.addAction(s)
        r = QAction("Refresh", self); r.triggered.connect(self.refresh); menu.addAction(r)
        menu.addSeparator()
        quit_ = QAction("Quit", self); quit_.triggered.connect(QApplication.quit); menu.addAction(quit_)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_toggle_conn(self):
        if self._last_service == "Running":
            self.do_disconnect()
        else:
            self.do_connect()

    def _update_tray(self):
        """Reflete o estado no tooltip e no menu da bandeja."""
        if not self._vm_running:
            tip = "Radmin VPN — VM off"
        elif self._last_service == "Running":
            n = sum(1 for i in range(self.listv.count())
                    if isinstance(self.listv.itemAt(i).widget(), PeerRow)
                    and self.listv.itemAt(i).widget()._online)
            tip = f"Radmin VPN — online ({self._node_ip})"
        else:
            tip = "Radmin VPN — disconnected"
        self.tray.setToolTip(tip)
        if hasattr(self, "trayConn"):
            self.trayConn.setText("Disconnect" if self._last_service == "Running" else "Connect")

    # ---------- data ----------
    def refresh(self):
        if self._closing:
            return
        if self._fetcher and self._fetcher.isRunning():
            return
        self.status.setText("querying the VM…")
        self._fetcher = Fetcher()
        self._fetcher.got.connect(self._apply)
        self._fetcher.start()

    def _apply(self, st: backend.State):
        if self._closing:
            return
        self._vm_running = st.vm_running
        if not st.ok:
            self._last_service = "Stopped"
            self.status.setText(f"● {st.error}")
            if not st.vm_running:
                self.nodeName.setText("VM is off")
                self.nodeIp.setText("click power to turn on")
                self.badge.setText("Off")
            else:
                self.badge.setText("Offline")
            self.badge.setObjectName("badgeOff")
            self.badge.setStyleSheet(QSS)
            self.power.setPixmap(icons.power_pixmap(False, 48))
            self._sync_actions(False)
            self._update_tray()
            self._relayout([])
            return

        self._last_service = st.service
        # o nome que os peers veem e o Alias do Radmin, nao o hostname do Windows
        self.nodeName.setText(st.alias or st.hostname or "—")
        self.nodeIp.setText(st.node_ip or "—")
        self._node_ip = st.node_ip
        on = (st.service == "Running")
        self.power.setPixmap(icons.power_pixmap(on, 48))
        self.badge.setText("Online" if on else "Offline")
        self.badge.setObjectName("badge" if on else "badgeOff")
        self.badge.setStyleSheet(QSS)
        self._sync_actions(on)
        self._update_tray()

        # descobre novos peers pelo ARP (a shim ja filtra 26.0.0.1)
        for p in st.peers:
            if p.ip == "26.0.0.1":
                continue
            self.roster.seen(p.ip, p.mac, p.host)
        self.roster.save()

        # liveness inicial = ARP; o ping_sweep refina logo em seguida
        active = {p.ip for p in st.peers if p.ip != "26.0.0.1"}
        self._render_peers(active)
        self.ping_now()   # dispara liveness ativo

    def _render_peers(self, online_set):
        rows = []
        for ip in self.roster.all_ips():
            if ip == self._node_ip or ip == "26.0.0.1":
                continue   # nao lista o proprio no nem o gateway
            rows.append((ip, ip in online_set))
        rows.sort(key=lambda r: (not r[1], self.roster.label_of(r[0]).lower()))
        self._relayout(rows)
        nact = sum(1 for _, o in rows if o)
        node = self.nodeIp.text()
        self.status.setText(f"● {nact} online · {len(rows)} known · node {node}")

    def _relayout(self, rows):
        # limpa
        while self.listv.count() > 1:
            item = self.listv.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for ip, online in rows:
            label = self.roster.label_of(ip)
            self.listv.insertWidget(self.listv.count() - 1,
                                    PeerRow(ip, label, online, self._rename))

    def _rename(self, ip):
        cur = self.roster.name_of(ip)
        text, ok = QInputDialog.getText(self, "Apelido do peer",
                                        f"Nome para {ip}:", text=cur)
        if ok:
            self.roster.set_name(ip, text.strip())
            self._render_peers(set())
            self.ping_now()

    # ---------- liveness (ping sweep do Linux) ----------
    def ping_now(self):
        if self._closing:
            return
        if self._pinger and self._pinger.isRunning():
            return
        ips = [ip for ip in self.roster.all_ips() if ip != "26.0.0.1"]
        if not ips:
            return
        self._pinger = Pinger(ips)
        self._pinger.done.connect(self._apply_ping)
        self._pinger.start()

    def _apply_ping(self, result: dict):
        if self._closing:
            return
        online = {ip for ip, up in result.items() if up}
        self._render_peers(online)

    # ---------- descoberta da lista completa (dump da GUI) ----------
    def discover_now(self):
        if self._closing or not self._vm_running:
            return
        if self._discover and self._discover.isRunning():
            return
        self.status.setText("● discovering network members…")
        self._discover = DiscoverWorker()
        self._discover.done.connect(self._apply_discover)
        self._discover.start()

    def _apply_discover(self, peers: dict):
        if self._closing:
            return
        if not peers:
            self.status.setText("● member sync failed (VM/dump)")
            return
        novos = self.roster.ingest(peers)
        self._render_peers(set())
        self.ping_now()
        self.status.setText(f"● {len(peers)} members synced ({novos} new)")

    # ---------- health / auto-heal (silencioso, em background) ----------
    def health_now(self):
        if self._closing or self._busy:
            return
        # watchdog: processo vivo mas VM travada (nao responde) -> recupera
        if vmctl.is_running() and not vmctl.is_responsive():
            self.status.setText("● VM unresponsive — recovering…")
            self._busy = True
            self._action = ActionWorker(lambda: (vmctl.recover() != "ok", "watchdog"))
            self._action.done.connect(lambda ok, log: self._vm_action_done("Recovering VM"))
            self._action.start()
            return
        if not self._vm_running:
            return
        if self._health and self._health.isRunning():
            return
        self._health = HealthWorker(heal=True)   # sempre cura no ciclo automatico
        self._health.done.connect(self._apply_health)
        self._health.start()

    def _apply_health(self, res: dict):
        if self._closing:
            return
        self._last_health = res
        if res.get("error"):
            return
        # se algo foi curado, avisa discretamente na barra
        if res.get("healed"):
            healed = [c["name"] for c in res.get("checks", []) if c.get("healed")]
            self.status.setText("● auto-repaired: " + ", ".join(healed))
            QTimer.singleShot(1000, self.refresh)

    def do_health(self):
        # diagnostico manual com relatorio visivel
        if self._busy:
            return
        self._busy = True
        self.status.setText("● full diagnostics…")
        self._sync_actions(self._last_service == "Running")
        self._health = HealthWorker(heal=True)
        self._health.done.connect(self._health_report)
        self._health.start()

    def _health_report(self, res: dict):
        from PySide6.QtWidgets import QMessageBox
        self._busy = False
        self._sync_actions(self._last_service == "Running")
        if res.get("error"):
            QMessageBox.warning(self, "Diagnostics", f"Error: {res['error']}")
            return
        nomes = {
            "radmin_service": "Radmin service",
            "mesh_ip": "Mesh IP (26.x)",
            "ics": "Sharing (ICS)",
            "isolated_ip": "Bridge to Linux",
            "power_guard": "Power locked",
            "agent_tasks": "Boot agent",
        }
        linhas = []
        for c in res.get("checks", []):
            mark = "✓" if c.get("ok") else "✗"
            extra = "  (reparado)" if c.get("healed") else ""
            linhas.append(f"{mark}  {nomes.get(c['name'], c['name'])}{extra}")
        titulo = "All systems OK" if res.get("all_ok") else "Problems found"
        m = QMessageBox(self)
        m.setWindowTitle("VM diagnostics")
        m.setIcon(QMessageBox.Information if res.get("all_ok") else QMessageBox.Warning)
        m.setText(titulo + (" — auto-repaired" if res.get("healed") else ""))
        m.setInformativeText("\n".join(linhas))
        m.exec()
        self.status.setText("● diagnostics: " + ("all ok" if res.get("all_ok") else "see details"))
        self.refresh()

    # ---------- acoes (fase 3/4) ----------
    def _sync_actions(self, on: bool):
        vm = self._vm_running
        if hasattr(self, "actConnect"):
            self.actConnect.setEnabled(vm and not on and not self._busy)
            self.actDisconnect.setEnabled(vm and on and not self._busy)
            self.actLeave.setEnabled(vm and not self._busy)
        if hasattr(self, "actVmOn"):
            self.actVmOn.setEnabled(not vm and not self._busy)
            self.actVmOff.setEnabled(vm and not self._busy)

    def _run_action(self, fn, label):
        if self._busy:
            return
        self._busy = True
        self.status.setText(f"● {label}…")
        self._sync_actions(self._last_service == "Running")
        self._action = ActionWorker(fn)
        self._action.done.connect(lambda ok, log: self._action_done(ok, log, label))
        self._action.start()

    def _action_done(self, ok, log, label):
        if self._closing:
            return
        self._busy = False
        if ok:
            self.status.setText(f"● {label}: ok")
        else:
            self.status.setText(f"● {label}: failed")
        QTimer.singleShot(1500, self.refresh)

    def toggle_power(self):
        # o power da UI liga/desliga a VM INTEIRA (Radmin Linux = a VM)
        if self._busy:
            return
        if self._vm_running:
            self.do_vm_off()
        else:
            self.do_vm_on()

    # ---------- controle da VM inteira ----------
    def do_vm_on(self):
        if self._busy or self._vm_running:
            return
        self._busy = True
        self.status.setText("● turning VM on…")
        self.nodeName.setText("starting…")
        self._sync_actions(False)
        self._action = ActionWorker(lambda: (vmctl.power_on(), "ligada"))
        self._action.done.connect(lambda ok, log: self._vm_action_done("Ligando"))
        self._action.start()

    def do_vm_off(self):
        from PySide6.QtWidgets import QMessageBox
        if self._busy or not self._vm_running:
            return
        r = QMessageBox.question(self, "Turn off Radmin VPN",
            "This fully shuts down the VM.\nRadmin and all peers will be unavailable until you turn it back on.\n\nTurn off?")
        if r != QMessageBox.Yes:
            return
        self._busy = True
        self.status.setText("● turning VM off…")
        self._sync_actions(True)
        self._action = ActionWorker(lambda: (vmctl.power_off(), "desligada"))
        self._action.done.connect(lambda ok, log: self._vm_action_done("Desligando"))
        self._action.start()

    def _vm_action_done(self, label):
        if self._closing:
            return
        self._busy = False
        self.status.setText(f"● {label}: ok")
        self._sync_actions(False)
        # ligar demora ~90s p/ o WMI responder; o refresh normal (30s) recupera,
        # mas dispara um cedo p/ atualizar o estado da VM (on/off)
        QTimer.singleShot(4000, self.refresh)

    # ---------- agente / automacao ----------
    def do_check_update(self):
        if self._busy:
            return
        self._busy = True
        self.status.setText("● checking for update…")
        self._sync_actions(self._last_service == "Running")
        self._action = ActionWorker(lambda: (agent.check_update(install=False), ""))
        self._action.done.connect(self._update_checked)
        self._action.start()

    def _update_checked(self, res, _log):
        from PySide6.QtWidgets import QMessageBox
        self._busy = False
        self._sync_actions(self._last_service == "Running")
        if isinstance(res, tuple):
            res = res[0]
        if not isinstance(res, dict) or res.get("error"):
            self.status.setText("● update: error")
            QMessageBox.warning(self, "Update", f"Could not check:\n{res}")
            return
        cur = res.get("installed_version", "?")
        lat = res.get("latest_version", "?")
        if res.get("has_update"):
            r = QMessageBox.question(self, "Update available",
                f"Installed: {cur}\nAvailable: {lat}\n\nInstall now on the VM?")
            if r == QMessageBox.Yes:
                self._run_action(lambda: (agent.check_update(install=True).get("did_install", False), ""),
                                 "Atualizando Radmin")
            else:
                self.status.setText(f"● {cur} ({lat} available)")
        else:
            self.status.setText(f"● Radmin up to date ({cur})")
            QMessageBox.information(self, "Update", f"Already on the latest version ({cur}).")

    def do_rename_node(self):
        from PySide6.QtWidgets import QInputDialog
        if self._busy or not self._vm_running:
            return
        cur = self.nodeName.text()
        new, ok = QInputDialog.getText(self, "Rename node",
            "New name for this node (what other peers see):", text=cur)
        new = (new or "").strip()
        if ok and new and new != cur:
            self._run_action(lambda: actions.rename_node(new), "Renaming node")

    def do_orchestrate(self):
        self._run_action(lambda: agent.orchestrate_net(), "Repairing network")

    def do_install_agent(self):
        from PySide6.QtWidgets import QMessageBox
        def _go():
            import subprocess, os
            deploy = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deploy-agent.sh")
            subprocess.run(["bash", deploy], capture_output=True, timeout=120)
            out = agent._run_file(r"C:\radmin-agent\agent-install.ps1", 90)
            return ("<<<AGENTOK>>>" in out), out
        self._run_action(_go, "Instalando agente")

    def do_connect(self):
        self._run_action(actions.connect, "Conectando")

    def do_disconnect(self):
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(self, "Disconnect",
            "Disconnect from Radmin VPN?\nPeers will be unreachable until you reconnect.")
        if r == QMessageBox.Yes:
            self._run_action(actions.disconnect, "Desconectando")

    def do_leave(self):
        from PySide6.QtWidgets import QMessageBox
        guids = backend.list_networks()
        if not guids:
            QMessageBox.information(self, "Leave network", "No associated network found.")
            return
        # se houver mais de uma, pergunta qual
        if len(guids) == 1:
            guid = guids[0]
        else:
            guid, ok = QInputDialog.getItem(self, "Leave network",
                "Which network to remove?", guids, 0, False)
            if not ok:
                return
        r = QMessageBox.question(self, "Leave network",
            f"Remove the network association\n{guid}?\n\nYou will need to join again with name and password.")
        if r == QMessageBox.Yes:
            self._run_action(lambda: actions.leave_network(guid), "Saindo da rede")

    def do_join(self):
        self._open_gui_for("join a network")

    def do_create(self):
        self._open_gui_for("create a network")

    def _open_gui_for(self, action):
        from PySide6.QtWidgets import QMessageBox
        m = QMessageBox(self)
        m.setWindowTitle("Radmin VPN")
        m.setIcon(QMessageBox.Information)
        m.setText(f"To {action} you need the real Radmin window.")
        m.setInformativeText(
            "This does a handshake with the Radmin server (network name + password) "
            "that only the official GUI performs — it cannot be done via the registry.\n\n"
            "I can open the VM's Radmin window here (VNC). Do it there and "
            "this list updates on its own afterwards.")
        b_open = m.addButton("Open Radmin window (VNC)", QMessageBox.AcceptRole)
        m.addButton("Cancel", QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b_open:
            self._open_vnc()

    def _open_vnc(self):
        import subprocess, config
        view = config.VIEW_SCRIPT
        if os.path.exists(view):
            subprocess.Popen(["bash", view])
            self.status.setText("● opening VM VNC…")
            QTimer.singleShot(20000, self.refresh)
            return
        self.status.setText("● bench-view.sh not found")

    # ---------- misc ----------
    def _about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(self, "About",
            "Radmin VPN (Linux).\n\n"
            "Front-end that drives the real Radmin VPN running headless on a\n"
            "Windows 7 VM, over WMI. The power button turns the whole VM on/off;\n"
            "peers come live from the mesh; the VM self-heals in the background.\n"
            "Active peers via ARP/ping; nicknames are local.")

    def _show_raise(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_raise()

    def closeEvent(self, e):
        # fecha p/ tray em vez de sair
        if self.tray.isVisible():
            e.ignore(); self.hide()

    def shutdown(self):
        self._closing = True
        self.timer.stop()
        self.pingtimer.stop()
        # espera qualquer QThread filho vivo (fetcher/pinger/action, mesmo recriado)
        from PySide6.QtCore import QThread as _QT
        for t in self.findChildren(_QT):
            try:
                if t.isRunning():
                    t.wait(20000)
            except RuntimeError:
                pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Radmin VPN (Linux)")
    app.setQuitOnLastWindowClosed(False)
    w = MainWindow(); w.show()
    app.aboutToQuit.connect(w.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
