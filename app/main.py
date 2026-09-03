#!/usr/bin/env python3
"""
Radmin VPN (Linux) - a read-only clone of the GUI, fed by the shim in the Windows VM.
Phase 2: shows the local node, service status and peers (online via ARP, offline via
roster). Peer nickname is local. Nothing here changes the real Radmin.
"""
from __future__ import annotations
import sys, os, time
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QMenuBar, QMenu, QSystemTrayIcon, QInputDialog,
    QStyle, QSizePolicy, QPushButton,
)
from PySide6.QtGui import QAction, QColor, QFont, QCursor
from PySide6.QtCore import Qt, QThread, Signal, QTimer

sys.path.insert(0, os.path.dirname(__file__))
import backend
import actions
import agent
import vmctl
import icons
import config
from roster import Roster

POLL_MS = 30000    # full refresh (shim) every 30s
PING_MS = 30000    # liveness (ping sweep) every 30s
HEALTH_MS = 120000 # diagnostics + auto-heal every 2 min
MAX_ROWS = 300     # cap on peer rows (never create thousands of widgets)
# Watchdog (auto-restart a wedged VM) must NEVER fire during a normal boot:
#  - grace: no watchdog action for this long after a power-on (Windows boots ~1-2 min)
#  - strikes: only recover after this many CONSECUTIVE unresponsive health cycles,
#    i.e. a real hang, not a slow boot or a transient blip.
WATCHDOG_GRACE_S = 240
WATCHDOG_STRIKES = 3

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
#badgeWarn { background: #6b5a30; color: #f5ecd6; border-radius: 8px;
             padding: 1px 10px; font-size: 11px; font-weight: 600; }
QScrollArea { border: none; background: #1a1d20; }
#list { background: #1a1d20; }
.peer { background: #1a1d20; }
.peerName { font-size: 13px; color: #e2e6e9; }
.peerIp   { font-size: 12px; color: #8a99a2; }
#netbar { background: #182028; border-bottom: 1px solid #10151a; }
.netchip { background: #22323d; color: #cfe6ef; border-radius: 9px;
           padding: 2px 10px; font-size: 11px; }
.netchipSel { background: #2f6f8c; color: #ffffff; border-radius: 9px;
              padding: 2px 10px; font-size: 11px; font-weight: 600; }
#nettools { background: #182028; border-bottom: 1px solid #10151a; }
#netAddBtn { background: #22323d; color: #cfe6ef; border: none; border-radius: 4px;
             padding: 3px 10px; font-size: 12px; font-weight: 600; }
#netAddBtn:hover { background: #2f6f8c; color: #ffffff; }
.netHeader { background: #1f2a33; border-top: 1px solid #10151a;
             border-bottom: 1px solid #10151a; }
.netHeaderName { color: #cfe6ef; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
.netHeaderCount { color: #7f8c93; font-size: 11px; }
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
    """Discovers the complete peer list (GUI dump) - heavy, occasional."""
    done = Signal(object)

    def run(self):
        import discover
        self.done.emit(discover.discover_peers())


class NetHeader(QFrame):
    """Collapsible network-section header: click toggles, right-click manages."""
    def __init__(self, gid, name, count, collapsed, on_toggle, on_menu):
        super().__init__()
        self.gid = gid
        self.setProperty("class", "netHeader")
        self.setObjectName("netHeader")
        self.setFixedHeight(28)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        lay = QHBoxLayout(self); lay.setContentsMargins(10, 2, 10, 2); lay.setSpacing(6)
        self.arrow = QLabel("▶" if collapsed else "▼")
        self.arrow.setStyleSheet("color:#7f8c93; font-size:10px;")
        lay.addWidget(self.arrow)
        nm = QLabel(name); nm.setProperty("class", "netHeaderName")
        lay.addWidget(nm)
        cnt = QLabel(f"· {count}"); cnt.setProperty("class", "netHeaderCount")
        lay.addWidget(cnt)
        lay.addStretch(1)
        self._on_toggle = on_toggle
        self._on_menu = on_menu

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton and self._on_menu:
            self._on_menu(self.gid, e.globalPosition().toPoint())
        else:
            self._on_toggle(self.gid)


class PeerRow(QFrame):
    def __init__(self, ip, name, online, on_rename, on_menu=None):
        super().__init__()
        self.ip = ip
        self._on_menu = on_menu
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

    def contextMenuEvent(self, e):
        if self._on_menu:
            self._on_menu(self.ip, e.globalPos())

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
        self._threads = set()   # all live QThreads, for shutdown to wait on
        self._busy = False
        self._booting = False   # VM on but WMI not answering yet (booting)
        self._closing = False
        self._last_service = "Unknown"
        self._vm_running = False
        self._vm_started_at = 0.0        # monotonic time of the last power-on (watchdog grace)
        self._unresponsive_strikes = 0   # consecutive unresponsive health cycles
        self._node_ip = ""
        self._networks = []       # GUIDs of the networks the node is in
        self._selected_net = None  # network selected in the filter (None = all)
        # Querying the VM (WMI/wmiexec) is OFF by default. An automatic query can
        # spike CPU/I-O and stutter the whole desktop while the VM is busy, so the
        # user opts in via System > "Auto-refresh", or queries once with "Refresh now".
        self._auto = bool(self.roster.get_setting("auto_refresh", False))
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.pingtimer = QTimer(self)
        self.pingtimer.timeout.connect(self.ping_now)
        self._health = None
        self._last_health = None
        self._discover = None
        self.healthtimer = QTimer(self)
        self.healthtimer.timeout.connect(self.health_now)
        # heavy discovery (~200MB dump) only on first run with an empty roster AND
        # only in auto mode; in manual mode nothing queries until the user asks.
        self._want_discover = self._auto and not self.roster.all_ips()
        if self._auto:
            self._start_auto_timers()
            self.refresh()
        else:
            self._show_manual_idle()

    # ---------- auto vs manual querying ----------
    def _start_auto_timers(self):
        self.timer.start(POLL_MS)
        self.pingtimer.start(PING_MS)
        self.healthtimer.start(HEALTH_MS)

    def _stop_auto_timers(self):
        self.timer.stop()
        self.pingtimer.stop()
        self.healthtimer.stop()

    def _show_manual_idle(self):
        """Manual mode on open: show the VM power state from the pidfile ONLY
        (vmctl.is_running reads a file — no WMI, no wmiexec, nothing heavy). The
        app stays idle until the user clicks Refresh or enables Auto-refresh."""
        try:
            running = vmctl.is_running()
        except Exception:  # noqa
            running = False
        self._vm_running = running
        self._booting = False
        self.nodeName.setText("Radmin VPN" if running else "VM is off")
        self.nodeIp.setText("Refresh to query the VM" if running else "click power to turn on")
        self.badge.setText("Manual" if running else "Off")
        self.badge.setObjectName("badgeWarn" if running else "badgeOff")
        self.badge.setStyleSheet(QSS)
        self.power.setPixmap(icons.power_pixmap(running, 48))
        self._sync_actions(False)
        self._update_tray()
        # show the known peers (as offline) so you can organize them into networks
        # without querying; a Refresh will light up who is actually online.
        self._render_peers(set())
        self.status.setText("● manual mode — Refresh to query"
                            + ("" if running else " · VM off"))

    def _toggle_auto(self, on: bool):
        self._auto = bool(on)
        self.roster.set_setting("auto_refresh", self._auto)
        if self._auto:
            self.status.setText("● auto-refresh ON — querying the VM every 30s")
            self._start_auto_timers()
            self.refresh()
        else:
            self._stop_auto_timers()
            self._show_manual_idle()
            self.status.setText("● auto-refresh OFF — manual (Refresh to query)")

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
                self.actAuto = QAction("Auto-refresh (query VM)", self)
                self.actAuto.setCheckable(True); self.actAuto.setChecked(self._auto)
                self.actAuto.setToolTip("Off by default so nothing queries the VM in the "
                                        "background. Turn on to refresh every 30s.")
                self.actAuto.toggled.connect(self._toggle_auto); m.addAction(self.actAuto)
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
                self.actOnlineOnly = QAction("Show online only", self)
                self.actOnlineOnly.setCheckable(True)
                self.actOnlineOnly.setChecked(bool(self.roster.get_setting("online_only", False)))
                self.actOnlineOnly.setToolTip("Hide offline peers from the list")
                self.actOnlineOnly.toggled.connect(self._toggle_online_only)
                m.addAction(self.actOnlineOnly)
                m.addSeparator()
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
        # declared footprint: the VM is intentionally tiny so it never hogs the host
        foot = QLabel(f"{config.VM_RAM} MB · {config.VM_SMP} CPU")
        foot.setStyleSheet("color:#6f8290; font-size:10px; font-weight:600;")
        foot.setToolTip("The Windows VM uses only this much RAM/CPU — it won't hog your machine")
        hl.addWidget(foot)
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

        # networks toolbar (dedicated control up top): create/manage network groups.
        # Peers are shown in collapsible per-network sections; assignment is MANUAL
        # (right-click a peer -> Move to). Grouping is local, stored in the roster.
        self.nettools = QWidget(); self.nettools.setObjectName("nettools")
        ntl = QHBoxLayout(self.nettools); ntl.setContentsMargins(8, 4, 8, 4); ntl.setSpacing(6)
        lbl = QLabel("Networks"); lbl.setStyleSheet("color:#8fa0aa; font-size:11px; font-weight:600;")
        ntl.addWidget(lbl); ntl.addStretch(1)
        self.addNetBtn = QPushButton("＋ Network"); self.addNetBtn.setObjectName("netAddBtn")
        self.addNetBtn.setCursor(QCursor(Qt.PointingHandCursor))
        self.addNetBtn.setToolTip("Create a network group, then right-click a peer to move it in")
        self.addNetBtn.clicked.connect(self._add_group)
        ntl.addWidget(self.addNetBtn)
        v.addWidget(self.nettools)

        # peer list
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.listw = QWidget(); self.listw.setObjectName("list")
        self.listv = QVBoxLayout(self.listw)
        self.listv.setContentsMargins(0, 4, 0, 4); self.listv.setSpacing(0)
        self.listv.addStretch(1)
        self.scroll.setWidget(self.listw)
        v.addWidget(self.scroll, 1)

        # status bar
        self.status = QLabel("starting…"); self.status.setObjectName("status")
        v.addWidget(self.status)

        self.setStyleSheet(QSS)
        self._build_tray()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(icons.logo_icon(64), self)
        self.tray.setToolTip("Radmin VPN (Linux)")
        menu = QMenu()
        show = QAction("Show", self); show.triggered.connect(self._show_raise); menu.addAction(show)
        menu.addSeparator()
        # full control from the tray — the user never touches the VM
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
        """Reflect the state in the tooltip and the tray menu."""
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

    # ---------- worker threads ----------
    def _start(self, t):
        """Register the QThread and start it. Shutdown waits on all registered ones
        (the QThreads are not Qt children of the window, so findChildren missed them
        -> that is why the app aborted with a worker still running on close)."""
        self._threads.add(t)
        t.finished.connect(lambda: self._threads.discard(t))
        t.start()

    # ---------- data ----------
    def refresh(self):
        if self._closing:
            return
        if self._fetcher and self._fetcher.isRunning():
            return
        self.status.setText("querying the VM…")
        self._fetcher = Fetcher()
        self._fetcher.got.connect(self._apply)
        self._start(self._fetcher)

    def _apply(self, st: backend.State):
        if self._closing:
            return
        was_running = self._vm_running
        self._vm_running = st.vm_running
        if st.vm_running and not was_running:
            # VM just came up (or app opened while it was already booting): start the
            # watchdog grace so a slow boot is never mistaken for a hang.
            self._vm_started_at = time.monotonic()
        if not st.ok:
            self._last_service = "Stopped"
            self.status.setText(f"● {st.error}")
            # qemu alive but WMI still not answering = VM BOOTING (not off)
            self._booting = bool(st.vm_running)
            if not st.vm_running:
                self.nodeName.setText("VM is off")
                self.nodeIp.setText("click power to turn on")
                self.badge.setText("Off")
                self.badge.setObjectName("badgeOff")
                self.power.setPixmap(icons.power_pixmap(False, 48))
            else:
                self.nodeName.setText("Starting…")
                self.nodeIp.setText("VM is booting, please wait")
                self.badge.setText("Starting")
                self.badge.setObjectName("badgeWarn")
                self.power.setPixmap(icons.power_pixmap(True, 48))
            self.badge.setStyleSheet(QSS)
            self._sync_actions(False)
            self._update_tray()
            self._clear_list()
            # while booting, re-check faster so the switch to online feels live
            # (auto mode only; in manual mode the user refreshes when they want)
            if self._booting and not self._closing and self._auto:
                QTimer.singleShot(5000, self.refresh)
            return

        self._last_service = st.service
        # the name peers see is Radmin's Alias, not the Windows hostname
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

        # discover new peers via ARP (the shim already filters 26.0.0.1)
        for p in st.peers:
            if p.ip == "26.0.0.1":
                continue
            self.roster.seen(p.ip, p.mac, p.host)
        self.roster.save()

        self._networks = list(st.networks)   # GUIDs the node is in (info only)

        # initial liveness = ARP; the ping_sweep refines it right after
        active = {p.ip for p in st.peers if p.ip != "26.0.0.1"}
        self._render_peers(active)
        self.ping_now()   # kicks off active liveness

        # first discovery only now, with the VM confirmed on and the service up
        if getattr(self, "_want_discover", False) and on:
            self._want_discover = False
            QTimer.singleShot(3000, self.discover_now)

    def _render_peers(self, online_set):
        self._online = set(online_set)
        self._rebuild_list()

    def _clear_list(self):
        while self.listv.count() > 1:
            it = self.listv.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()

    def _rebuild_list(self):
        """Render peers in collapsible per-network sections (manual grouping).
        No user groups yet -> a plain flat list. Otherwise: one section per group
        (in order) + an 'Unassigned' section, each collapsible. Honors the
        Network > 'Show online only' filter."""
        online = getattr(self, "_online", set())
        online_only = bool(self.roster.get_setting("online_only", False))
        peers = [ip for ip in self.roster.all_ips()
                 if ip != self._node_ip and ip != "26.0.0.1"]
        buckets: dict = {}
        for ip in peers:
            buckets.setdefault(self.roster.group_of(ip), []).append(ip)

        def visible(ips):
            ips = sorted(ips, key=lambda ip: (ip not in online, self.roster.label_of(ip).lower()))
            if online_only:
                ips = [ip for ip in ips if ip in online]
            return ips

        self._clear_list()
        groups = self.roster.groups()
        total = sum(len(visible(b)) for b in buckets.values())
        shown = 0

        if not groups:
            # no groups: flat list (headers would be noise); create groups via ＋
            for ip in visible(buckets.get(None, [])):
                if shown >= MAX_ROWS:
                    break
                self._add_peer_row(ip, ip in online); shown += 1
        else:
            sections = [(g["id"], g["name"]) for g in groups]
            if buckets.get(None):
                sections.append((None, "Unassigned"))
            for gid, gname in sections:
                ips = visible(buckets.get(gid, []))
                if online_only and not ips:
                    continue   # when filtering, don't show empty network headers
                key = gid or "__unassigned__"
                collapsed = self.roster.is_collapsed(key)
                hdr = NetHeader(gid, gname, len(ips), collapsed,
                                self._toggle_group, self._group_menu)
                self.listv.insertWidget(self.listv.count() - 1, hdr)
                if collapsed:
                    continue
                for ip in ips:
                    if shown >= MAX_ROWS:
                        break
                    self._add_peer_row(ip, ip in online); shown += 1

        nact = sum(1 for ip in peers if ip in online)
        node = self.nodeIp.text()
        hidden = f" (+{total - shown} hidden)" if total > shown else ""
        flt = " · online only" if online_only else ""
        self.status.setText(f"● {nact} online · {len(peers)} known{flt}{hidden} · node {node}")

    def _add_peer_row(self, ip, online):
        label = self.roster.label_of(ip)
        self.listv.insertWidget(self.listv.count() - 1,
                                PeerRow(ip, label, online, self._rename, self._peer_menu))

    # ---------- network groups (manual assignment) ----------
    def _add_group(self):
        text, ok = QInputDialog.getText(self, "New network", "Network name:")
        if ok and text.strip():
            self.roster.add_group(text.strip())
            self._rebuild_list()

    def _toggle_online_only(self, on: bool):
        self.roster.set_setting("online_only", bool(on))
        self._rebuild_list()

    def _toggle_group(self, gid):
        key = gid or "__unassigned__"
        self.roster.set_collapsed(key, not self.roster.is_collapsed(key))
        self._rebuild_list()

    def _group_menu(self, gid, pos):
        if gid is None:
            return   # the Unassigned section has nothing to rename/delete
        m = QMenu(self)
        m.addAction("Rename…", lambda: self._rename_group(gid))
        m.addAction("Delete network", lambda: self._delete_group(gid))
        m.exec(pos)

    def _rename_group(self, gid):
        text, ok = QInputDialog.getText(self, "Rename network", "Network name:",
                                        text=self.roster.group_name(gid))
        if ok and text.strip():
            self.roster.rename_group(gid, text.strip())
            self._rebuild_list()

    def _delete_group(self, gid):
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(self, "Delete network",
            f"Delete '{self.roster.group_name(gid)}'?\n"
            "Its peers become Unassigned (they are not removed).")
        if r == QMessageBox.Yes:
            self.roster.remove_group(gid)
            self._rebuild_list()

    def _peer_menu(self, ip, pos):
        m = QMenu(self)
        m.addAction("Rename…", lambda: self._rename(ip))
        move = m.addMenu("Move to network")
        cur = self.roster.group_of(ip)
        for g in self.roster.groups():
            act = move.addAction(g["name"], lambda gid=g["id"]: self._move_peer(ip, gid))
            act.setCheckable(True); act.setChecked(cur == g["id"])
        move.addSeparator()
        move.addAction("＋ New network…", lambda: self._move_to_new(ip))
        if cur is not None:
            m.addAction("Unassign", lambda: self._move_peer(ip, None))
        m.exec(pos)

    def _move_peer(self, ip, gid):
        self.roster.assign(ip, gid)
        self._rebuild_list()

    def _move_to_new(self, ip):
        text, ok = QInputDialog.getText(self, "New network", "Network name:")
        if ok and text.strip():
            gid = self.roster.add_group(text.strip())
            self.roster.assign(ip, gid)
            self._rebuild_list()

    def _rename(self, ip):
        cur = self.roster.name_of(ip)
        text, ok = QInputDialog.getText(self, "Peer nickname",
                                        f"Name for {ip}:", text=cur)
        if ok:
            self.roster.set_name(ip, text.strip())
            self._rebuild_list()
            self.ping_now()

    # ---------- liveness (ping sweep from Linux) ----------
    def ping_now(self):
        # with no VM on there is no mesh to ping: avoids the pointless sweep (and the
        # background ping-process churn when the VM is off).
        if self._closing or not self._vm_running:
            return
        if self._pinger and self._pinger.isRunning():
            return
        ips = [ip for ip in self.roster.all_ips() if ip != "26.0.0.1"]
        if not ips:
            return
        self._pinger = Pinger(ips)
        self._pinger.done.connect(self._apply_ping)
        self._start(self._pinger)

    def _apply_ping(self, result: dict):
        if self._closing:
            return
        online = {ip for ip, up in result.items() if up}
        self._render_peers(online)

    # ---------- full-list discovery (GUI dump) ----------
    def discover_now(self):
        if self._closing or not self._vm_running:
            return
        if self._discover and self._discover.isRunning():
            return
        self.status.setText("● discovering network members…")
        self._discover = DiscoverWorker()
        self._discover.done.connect(self._apply_discover)
        self._start(self._discover)

    def _apply_discover(self, peers: dict):
        if self._closing:
            return
        if not peers:
            self.status.setText("● member sync failed (VM/dump)")
            return
        novos = self.roster.ingest(peers)
        self._rebuild_list()
        self.ping_now()
        self.status.setText(f"● {len(peers)} members synced ({novos} new)")

    # ---------- health / auto-heal (silent, in the background) ----------
    def health_now(self):
        if self._closing or self._busy:
            return
        # --- watchdog: restart ONLY a genuinely wedged VM, never during boot ---
        # A slow Windows boot looks "unresponsive" too, so guard hard: skip while
        # booting, skip during the post-power-on grace, and require several
        # consecutive unresponsive cycles before touching the VM. Otherwise the
        # watchdog kept force-restarting the booting VM in a loop (spurious reboots
        # + a pile of preflight/wmiexec python + a kill -9 freeze).
        if vmctl.is_running():
            in_grace = (time.monotonic() - self._vm_started_at) < WATCHDOG_GRACE_S
            if not self._booting and not in_grace and not vmctl.is_responsive():
                self._unresponsive_strikes += 1
            else:
                self._unresponsive_strikes = 0
            if self._unresponsive_strikes >= WATCHDOG_STRIKES:
                self._unresponsive_strikes = 0
                self.status.setText("● VM unresponsive — recovering…")
                self._busy = True
                self._action = ActionWorker(lambda: (vmctl.recover() != "ok", "watchdog"))
                self._action.done.connect(lambda ok, log: self._vm_action_done("Recovering VM"))
                self._start(self._action)
                return
        else:
            self._unresponsive_strikes = 0
        # normal auto-heal: only when the VM is really up (WMI answering), not booting
        if not self._vm_running or self._booting:
            return
        if self._health and self._health.isRunning():
            return
        self._health = HealthWorker(heal=True)   # always heal in the automatic cycle
        self._health.done.connect(self._apply_health)
        self._start(self._health)

    def _apply_health(self, res: dict):
        if self._closing:
            return
        self._last_health = res
        if res.get("error"):
            return
        # if something was healed, note it discreetly in the status bar
        if res.get("healed"):
            healed = [c["name"] for c in res.get("checks", []) if c.get("healed")]
            self.status.setText("● auto-repaired: " + ", ".join(healed))
            QTimer.singleShot(1000, self.refresh)

    def do_health(self):
        # manual diagnostics with a visible report
        if self._busy:
            return
        self._busy = True
        self.status.setText("● full diagnostics…")
        self._sync_actions(self._last_service == "Running")
        self._health = HealthWorker(heal=True)
        self._health.done.connect(self._health_report)
        self._start(self._health)

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
        self._start(self._action)

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
        # the UI power button turns the WHOLE VM on/off (Radmin Linux = the VM)
        if self._busy:
            return
        if self._vm_running:
            self.do_vm_off()
        else:
            self.do_vm_on()

    # ---------- whole-VM control ----------
    def do_vm_on(self):
        if self._busy or self._vm_running:
            return
        self._busy = True
        self._vm_started_at = time.monotonic()   # start the watchdog grace now
        self.status.setText("● turning VM on…")
        self.nodeName.setText("starting…")
        self._sync_actions(False)
        self._action = ActionWorker(lambda: (vmctl.power_on(), "on"))
        self._action.done.connect(lambda ok, log: self._vm_action_done("Turning on"))
        self._start(self._action)

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
        self._action = ActionWorker(lambda: (vmctl.power_off(), "off"))
        self._action.done.connect(lambda ok, log: self._vm_action_done("Turning off"))
        self._start(self._action)

    def _vm_action_done(self, label):
        if self._closing:
            return
        self._busy = False
        self.status.setText(f"● {label}: ok")
        self._sync_actions(False)
        # powering on takes ~90s for WMI to answer; the normal 30s refresh recovers,
        # but fire one early to update the VM state (on/off)
        QTimer.singleShot(4000, self.refresh)

    # ---------- agent / automation ----------
    def do_check_update(self):
        if self._busy:
            return
        self._busy = True
        self.status.setText("● checking for update…")
        self._sync_actions(self._last_service == "Running")
        self._action = ActionWorker(lambda: (agent.check_update(install=False), ""))
        self._action.done.connect(self._update_checked)
        self._start(self._action)

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
                                 "Updating Radmin")
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
        self._run_action(_go, "Installing agent")

    def do_connect(self):
        self._run_action(actions.connect, "Connecting")

    def do_disconnect(self):
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(self, "Disconnect",
            "Disconnect from Radmin VPN?\nPeers will be unreachable until you reconnect.")
        if r == QMessageBox.Yes:
            self._run_action(actions.disconnect, "Disconnecting")

    def do_leave(self):
        from PySide6.QtWidgets import QMessageBox
        guids = backend.list_networks()
        if not guids:
            QMessageBox.information(self, "Leave network", "No associated network found.")
            return
        # if more than one, ask which
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
            self._run_action(lambda: actions.leave_network(guid), "Leaving network")

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
            "Active peers via ARP/ping; nicknames are local.\n\n"
            f"Tiny footprint: the VM uses only {config.VM_RAM} MB RAM · {config.VM_SMP} CPU, "
            "so it never hogs your machine.")

    def _show_raise(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_raise()

    def closeEvent(self, e):
        # close to tray instead of quitting
        if self.tray.isVisible():
            e.ignore(); self.hide()

    def shutdown(self):
        self._closing = True
        self.timer.stop()
        self.pingtimer.stop()
        self.healthtimer.stop()
        # 1) cancel and KILL every tracked subprocess (wmiexec/ping/dump/agent):
        #    this immediately unblocks the worker threads stuck in communicate()/ping,
        #    which then return on their own.
        import backend
        backend.cancel_all()
        # 2) wait for each worker to finish. With the children killed, wait() returns
        #    quickly. NO terminate(): killing a QThread mid-Python is what made Qt
        #    abort (qFatal) during finalize. The QThreads are not Qt children of the
        #    window; that is why we track them in self._threads (findChildren missed them).
        for t in list(self._threads):
            try:
                if t.isRunning():
                    t.wait(5000)
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
