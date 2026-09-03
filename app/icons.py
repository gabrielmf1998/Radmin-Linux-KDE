"""
icons.py - draws the clone's icons (logo/tray, signal, power) with QPainter,
without relying on external files. Colors based on the real Radmin VPN GUI.
"""
from __future__ import annotations
from PySide6.QtGui import QPixmap, QPainter, QColor, QBrush, QPen, QPainterPath, QLinearGradient, QIcon
from PySide6.QtCore import Qt, QRectF, QPointF

CYAN = QColor("#39b6d8")
CYAN_DK = QColor("#2b8fab")
GREEN = QColor("#54c15a")
RED = QColor("#c0504d")
GREY = QColor("#6b7378")


def _aa(p: QPainter) -> None:
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)


def logo_pixmap(size: int = 64) -> QPixmap:
    """Escudo/triangulo ciano estilo Radmin VPN."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    _aa(p)
    s = size
    # escudo arredondado
    path = QPainterPath()
    path.moveTo(s * 0.5, s * 0.08)
    path.lineTo(s * 0.90, s * 0.24)
    path.lineTo(s * 0.90, s * 0.55)
    path.quadTo(s * 0.90, s * 0.86, s * 0.5, s * 0.96)
    path.quadTo(s * 0.10, s * 0.86, s * 0.10, s * 0.55)
    path.lineTo(s * 0.10, s * 0.24)
    path.closeSubpath()
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0, CYAN)
    g.setColorAt(1, CYAN_DK)
    p.setBrush(QBrush(g))
    p.setPen(Qt.NoPen)
    p.drawPath(path)
    # "V" branco central
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(s * 0.08)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPolyline([QPointF(s*0.32, s*0.36), QPointF(s*0.5, s*0.66), QPointF(s*0.68, s*0.36)])
    p.end()
    return pm


def logo_icon(size: int = 64) -> QIcon:
    return QIcon(logo_pixmap(size))


def signal_pixmap(online: bool, size: int = 18) -> QPixmap:
    """Barras de sinal (online) ou X (offline)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    _aa(p)
    if online:
        p.setPen(Qt.NoPen)
        p.setBrush(GREEN)
        n = 4
        bw = size / (n * 1.8)
        gap = bw * 0.8
        x = 1.0
        for i in range(n):
            h = size * (0.30 + 0.18 * i)
            p.drawRoundedRect(QRectF(x, size - h - 1, bw, h), 1, 1)
            x += bw + gap
    else:
        pen = QPen(GREY)
        pen.setWidthF(size * 0.14)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = size * 0.28
        p.drawLine(QPointF(m, m), QPointF(size - m, size - m))
        p.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    p.end()
    return pm


def power_pixmap(on: bool, size: int = 56) -> QPixmap:
    """Botao circular de power do card do no."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    _aa(p)
    ring = GREEN if on else GREY
    pen = QPen(ring)
    pen.setWidthF(size * 0.08)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    m = size * 0.16
    p.drawArc(QRectF(m, m, size - 2*m, size - 2*m), int(-120*16), int(300*16))
    # haste
    p.drawLine(QPointF(size/2, size*0.20), QPointF(size/2, size*0.46))
    p.end()
    return pm
