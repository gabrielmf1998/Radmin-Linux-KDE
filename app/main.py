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
import icons
from roster import Roster

POLL_MS = 30000   # refresh completo (shim) a cada 30s
PING_MS = 30000   # liveness (ping sweep) a cada 30s

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
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)
        self.pingtimer = QTimer(self)
        self.pingtimer.timeout.connect(self.ping_now)
        self.pingtimer.start(PING_MS)
        self.refresh()

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
                a = QAction("Atualizar agora", self); a.triggered.connect(self.refresh); m.addAction(a)
                m.addSeparator()
                q = QAction("Sair", self); q.triggered.connect(QApplication.quit); m.addAction(q)
            elif name == "Network":
                self.actConnect = QAction("Conectar", self)
                self.actConnect.triggered.connect(self.do_connect); m.addAction(self.actConnect)
                self.actDisconnect = QAction("Desconectar", self)
                self.actDisconnect.triggered.connect(self.do_disconnect); m.addAction(self.actDisconnect)
                m.addSeparator()
                self.actLeave = QAction("Sair da rede…", self)
                self.actLeave.triggered.connect(self.do_leave); m.addAction(self.actLeave)
                self.actJoin = QAction("Entrar em uma rede…", self)
                self.actJoin.triggered.connect(self.do_join); m.addAction(self.actJoin)
                self.actCreate = QAction("Criar rede…", self)
                self.actCreate.triggered.connect(self.do_create); m.addAction(self.actCreate)
            elif name == "Help":
                a = QAction("Sobre", self); a.triggered.connect(self._about); m.addAction(a)
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
        self.power.setToolTip("Clique para conectar / desconectar")
        self.power.mousePressEvent = lambda e: self.toggle_power()
        cl.addWidget(self.power)
        box = QVBoxLayout(); box.setSpacing(2)
        self.nodeName = QLabel("—"); self.nodeName.setObjectName("nodeName")
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
        show = QAction("Mostrar", self); show.triggered.connect(self._show_raise); menu.addAction(show)
        ref = QAction("Atualizar", self); ref.triggered.connect(self.refresh); menu.addAction(ref)
        menu.addSeparator()
        quit_ = QAction("Sair", self); quit_.triggered.connect(QApplication.quit); menu.addAction(quit_)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    # ---------- data ----------
    def refresh(self):
        if self._closing:
            return
        if self._fetcher and self._fetcher.isRunning():
            return
        self.status.setText("consultando a VM…")
        self._fetcher = Fetcher()
        self._fetcher.got.connect(self._apply)
        self._fetcher.start()

    def _apply(self, st: backend.State):
        if self._closing:
            return
        if not st.ok:
            self.status.setText(f"● {st.error}")
            self.badge.setText("Offline"); self.badge.setObjectName("badgeOff")
            self.badge.setStyleSheet(QSS)
            self.power.setPixmap(icons.power_pixmap(False, 48))
            self._relayout([])
            return

        self._last_service = st.service
        self.nodeName.setText(st.hostname or "—")
        self.nodeIp.setText(st.node_ip or "—")
        on = (st.service == "Running")
        self.power.setPixmap(icons.power_pixmap(on, 48))
        self.badge.setText("Online" if on else "Offline")
        self.badge.setObjectName("badge" if on else "badgeOff")
        self.badge.setStyleSheet(QSS)
        self._sync_actions(on)

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
            rows.append((ip, ip in online_set))
        rows.sort(key=lambda r: (not r[1], self.roster.label_of(r[0]).lower()))
        self._relayout(rows)
        nact = sum(1 for _, o in rows if o)
        node = self.nodeIp.text()
        self.status.setText(f"● {nact} online · {len(rows)} conhecidos · nó {node}")

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

    # ---------- acoes (fase 3/4) ----------
    def _sync_actions(self, on: bool):
        if hasattr(self, "actConnect"):
            self.actConnect.setEnabled(not on and not self._busy)
            self.actDisconnect.setEnabled(on and not self._busy)
            self.actLeave.setEnabled(not self._busy)

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
            self.status.setText(f"● {label}: falhou")
        QTimer.singleShot(1500, self.refresh)

    def toggle_power(self):
        if self._busy:
            return
        if self._last_service == "Running":
            self.do_disconnect()
        else:
            self.do_connect()

    def do_connect(self):
        self._run_action(actions.connect, "Conectando")

    def do_disconnect(self):
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(self, "Desconectar",
            "Desconectar do Radmin VPN?\nOs peers ficarão inacessíveis até reconectar.")
        if r == QMessageBox.Yes:
            self._run_action(actions.disconnect, "Desconectando")

    def do_leave(self):
        from PySide6.QtWidgets import QMessageBox
        guids = backend.list_networks()
        if not guids:
            QMessageBox.information(self, "Sair da rede", "Nenhuma rede associada encontrada.")
            return
        # se houver mais de uma, pergunta qual
        if len(guids) == 1:
            guid = guids[0]
        else:
            guid, ok = QInputDialog.getItem(self, "Sair da rede",
                "Qual rede remover?", guids, 0, False)
            if not ok:
                return
        r = QMessageBox.question(self, "Sair da rede",
            f"Remover a associação de rede\n{guid}?\n\nVocê precisará entrar de novo com nome e senha.")
        if r == QMessageBox.Yes:
            self._run_action(lambda: actions.leave_network(guid), "Saindo da rede")

    def do_join(self):
        self._open_gui_for("entrar em uma rede")

    def do_create(self):
        self._open_gui_for("criar uma rede")

    def _open_gui_for(self, acao):
        from PySide6.QtWidgets import QMessageBox
        m = QMessageBox(self)
        m.setWindowTitle("Radmin VPN")
        m.setIcon(QMessageBox.Information)
        m.setText(f"Para {acao} é preciso a janela real do Radmin.")
        m.setInformativeText(
            "Essa ação faz um handshake com o servidor Radmin (nome + senha da rede) "
            "que só a GUI oficial executa — não dá para fazer pelo registro.\n\n"
            "Posso abrir a janela do Radmin da VM aqui (VNC). Você faz a ação lá e "
            "esta lista atualiza sozinha em seguida.")
        b_open = m.addButton("Abrir janela do Radmin (VNC)", QMessageBox.AcceptRole)
        m.addButton("Cancelar", QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b_open:
            self._open_vnc()

    def _open_vnc(self):
        import subprocess
        view = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "..", "..", "VMs", "ntlite-bench", "bench-view.sh")
        # caminho absoluto conhecido da bancada
        candidates = ["/mnt/samsung-980pro/VMs/ntlite-bench/bench-view.sh",
                      os.path.abspath(view)]
        for c in candidates:
            if os.path.exists(c):
                subprocess.Popen(["bash", c])
                self.status.setText("● abrindo VNC da VM…")
                # apos o usuario mexer na GUI, atualiza em 20s
                QTimer.singleShot(20000, self.refresh)
                return
        self.status.setText("● bench-view.sh não encontrado")

    # ---------- misc ----------
    def _about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(self, "Sobre",
            "Radmin VPN (Linux) — clone só-leitura.\n\n"
            "Lê o Radmin VPN real rodando na VM Windows via WMI.\n"
            "Peers ativos vêm da tabela ARP; apelidos são locais.\n"
            "Fase 2 — nada aqui altera o Radmin.")

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
