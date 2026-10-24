"""REEZ sound bars: a small live display under the floating icon that shows whether REEZ is listening."""

import math

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

BARS = 19
BAR_W = 5
GAP = 3
W = BARS * (BAR_W + GAP) + 16
H = 58
TOP = 40

COLORS = {
    "listening": ("#6d28d9", "#c084fc"),
    "hearing": ("#6d28d9", "#c084fc"),
    "awake": ("#a855f7", "#f5e9ff"),
    "speaking": ("#7c3aed", "#e9d5ff"),
    "thinking": ("#4c1d95", "#a78bfa"),
    "off": ("#2a2440", "#4a4560"),
}
LABELS = {
    "listening": "LISTENING",
    "hearing": "HEARING",
    "awake": "LISTENING",
    "speaking": "SPEAKING",
    "thinking": "THINKING",
    "off": "NOT LISTENING",
}


class Bars(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        self.state = "off"
        self.opacity = 0.0
        self.show_target = False
        self.level = 0.0
        self.phase = 0.0
        self.heights = [0.06] * BARS
        self.envelope = [0.35 + 0.65 * math.sin(math.pi * (i + 0.5) / BARS) ** 1.4 for i in range(BARS)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(33)

    def update_state(self, state, level, show=True):
        self.state = state
        self.level = level
        self.show_target = show
    def follow(self, floater):
        geo = floater.frameGeometry()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = geo.center().x() - W // 2
        y = geo.bottom() - 8
        if y + H > screen.bottom():
            y = geo.top() + 8 - H
        x = max(screen.left() + 4, min(x, screen.right() - W - 4))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def _step(self):
        self.phase += 0.22
        goal = 1.0 if self.show_target else 0.0
        self.opacity += (goal - self.opacity) * 0.25
        if self.show_target and not self.isVisible():
            self.show()
        elif not self.show_target and self.opacity < 0.02 and self.isVisible():
            self.hide()
            self.opacity = 0.0
        if not self.isVisible():
            return
        s = self.state
        loud = min(1.0, self.level * 16.0)
        for i in range(BARS):
            e = self.envelope[i]
            wob = 0.5 + 0.5 * math.sin(self.phase * (1.3 + (i % 5) * 0.37) + i * 1.7)
            if s == "off":
                target = 0.05
            elif s in ("thinking", "hearing"):
                target = e * (0.25 + 0.45 * (0.5 + 0.5 * math.sin(self.phase * 1.4 - i * 0.55)))
            elif s == "speaking":
                target = e * (0.3 + 0.65 * wob)
            elif s == "awake":
                target = e * (0.22 + 0.2 * wob + 0.6 * loud * wob)
            else:
                target = e * (0.10 + 0.9 * loud * (0.35 + 0.65 * wob))
            rate = 0.35 if target > self.heights[i] else 0.2
            self.heights[i] = max(0.0, min(1.0, self.heights[i] + (target - self.heights[i]) * rate))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.opacity)
        p.setPen(QPen(QColor(76, 29, 149, 170), 1))
        p.setBrush(QColor(5, 2, 14, 165))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 16, 16)
        low, high = COLORS.get(self.state, COLORS["off"])
        cy = 6 + TOP / 2
        x0 = (W - (BARS * (BAR_W + GAP) - GAP)) / 2
        p.setPen(Qt.NoPen)
        for i, frac in enumerate(self.heights):
            h = max(3.0, frac * TOP)
            x = x0 + i * (BAR_W + GAP)
            top = cy - h / 2
            glow = QColor(high)
            glow.setAlpha(0 if self.state == "off" else 55)
            p.setBrush(glow)
            p.drawRoundedRect(QRectF(x - 2, top - 2, BAR_W + 4, h + 4), 4, 4)
            grad = QLinearGradient(0, top + h, 0, top)
            grad.setColorAt(0, QColor(low))
            grad.setColorAt(1, QColor(high))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(x, top, BAR_W, h), 2.5, 2.5)
        font = QFont("Segoe UI", 7)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(font)
        label = QColor(high)
        label.setAlpha(210)
        p.setPen(label)
        p.drawText(QRectF(0, TOP + 7, W, H - TOP - 8), Qt.AlignCenter, LABELS.get(self.state, ""))
        p.end()

