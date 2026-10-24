"""REEZ floating icon: a round, always-on-top badge with a sound ring that shows and speaks what REEZ is doing."""

import math
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient, QTextDocument)
from PySide6.QtWidgets import QLabel, QMenu, QWidget

SIZE = 150
ICON_R = 37
BARS_N = 44
BAR_MAX = 22
POS_FILE = Path(__file__).parent / "data" / "floater.txt"
MENU_STYLE = (
    "QMenu { background-color: #0a0614; color: #e9d5ff; border: 1px solid #7c3aed; padding: 6px; }"
    "QMenu::item { padding: 8px 22px; border-radius: 6px; }"
    "QMenu::item:selected { background-color: #4c1d95; }"
    "QMenu::separator { height: 1px; background: #2a1650; margin: 4px 8px; }")
COLORS = {
    "listening": ("#6d28d9", "#c084fc"),
    "hearing": ("#6d28d9", "#c084fc"),
    "awake": ("#a855f7", "#f5e9ff"),
    "speaking": ("#7c3aed", "#e9d5ff"),
    "thinking": ("#4c1d95", "#a78bfa"),
    "off": ("#2a2440", "#4a4560"),
}


def _load_logo():
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
        path = Path(__file__).parent / "theme" / name
        if path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                return pix
    return None


class Bubble(QWidget):
    """A small caption next to the icon, so the icon visibly speaks."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setStyleSheet(
            "QLabel { background-color: rgba(10,6,20,235); border: 1px solid #a855f7; "
            "border-radius: 14px; padding: 10px 14px; color: #e9d5ff; font-size: 13px; }")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text, near, seconds):
        text = " ".join(text.split())[:300]
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setPlainText(text)
        doc.setTextWidth(300)
        width = int(min(300, doc.idealWidth())) + 4
        doc.setTextWidth(width)
        height = int(doc.size().height())
        box_w, box_h = width + 32, height + 24
        self.label.setText(text)
        self.label.setFixedSize(box_w, box_h)
        self.label.move(0, 0)
        self.resize(box_w, box_h)
        geo = near.frameGeometry()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = geo.left() - box_w - 4
        if x < screen.left() + 8:
            x = geo.right() + 4
        y = geo.center().y() - box_h // 2
        y = max(screen.top() + 8, min(y, screen.bottom() - box_h - 8))
        self.move(x, y)
        self.show()
        self._timer.start(int(seconds * 1000))


class Floater(QWidget):
    open_requested = Signal()
    chat_requested = Signal()
    mic_requested = Signal()
    lock_requested = Signal()
    quit_requested = Signal()
    listen_toggled = Signal(bool)
    gesture_toggled = Signal(bool)
    view_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(SIZE, SIZE)
        self.setToolTip("REEZ - click to open or hide, double-click for quick chat, right-click for the menu")
        self.logo = _load_logo()
        self.mode = "idle"
        self.listening_on = True
        self.gestures_on = False
        self.bubble = Bubble()
        self.bar_state = "off"
        self.bar_level = 0.0
        self.bar_show = False
        self.bar_opacity = 0.0
        self.heights = [0.05] * BARS_N
        self._bar_phase = 0.0
        self._phase = 0.0
        self._press = None
        self._offset = QPoint()
        self._moved = False
        self._dbl = False
        self._place()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(40)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(260)
        self._click_timer.timeout.connect(self.open_requested)

    def set_mode(self, mode):
        self.mode = mode

    def set_bars(self, state, level, show):
        self.bar_state = state
        self.bar_level = level
        self.bar_show = show

    def say(self, text, seconds=None):
        if seconds is None:
            seconds = max(3.0, min(16.0, len(text) * 0.06 + 2.0))
        self.bubble.show_text(text, self, seconds)

    def _place(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        x, y = geo.right() - SIZE - 24, geo.bottom() - SIZE - 24
        try:
            sx, sy = (int(v) for v in POS_FILE.read_text().split(","))
            centre = QPoint(sx + SIZE // 2, sy + SIZE // 2)
            if any(s.availableGeometry().contains(centre) for s in QGuiApplication.screens()):
                x, y = sx, sy
        except Exception:
            pass
        self.move(x, y)

    def _save_pos(self):
        try:
            POS_FILE.parent.mkdir(exist_ok=True)
            POS_FILE.write_text(str(self.x()) + "," + str(self.y()))
        except Exception:
            pass

    def _step(self):
        self._phase += 0.04 if self.mode == "idle" else 0.16
        goal = 1.0 if self.bar_show else 0.0
        self.bar_opacity += (goal - self.bar_opacity) * 0.25
        if self.bar_opacity > 0.02 or self.bar_show:
            self._bar_phase += 0.22
            loud = min(1.0, self.bar_level * 16.0)
            s = self.bar_state
            for i in range(BARS_N):
                wob = 0.5 + 0.5 * math.sin(self._bar_phase * (1.3 + (i % 5) * 0.37) + i * 1.7)
                if s == "off":
                    target = 0.05
                elif s in ("thinking", "hearing"):
                    target = 0.25 + 0.45 * (0.5 + 0.5 * math.sin(self._bar_phase * 1.4 - i * 0.4))
                elif s == "speaking":
                    target = 0.3 + 0.65 * wob
                elif s == "awake":
                    target = 0.22 + 0.2 * wob + 0.6 * loud * wob
                else:
                    target = 0.10 + 0.9 * loud * (0.35 + 0.65 * wob)
                rate = 0.35 if target > self.heights[i] else 0.2
                self.heights[i] = max(0.0, min(1.0, self.heights[i] + (target - self.heights[i]) * rate))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = SIZE / 2.0
        r = float(ICON_R)
        pulse = (math.sin(self._phase) + 1) / 2
        strength = {
            "idle": 0.30 + 0.15 * pulse,
            "listening": 0.60 + 0.40 * pulse,
            "thinking": 0.65,
            "speaking": 0.45 + 0.40 * pulse,
        }.get(self.mode, 0.3)

        if self.bar_opacity > 0.02:
            low, high = COLORS.get(self.bar_state, COLORS["off"])
            lo, hi = QColor(low), QColor(high)
            inner = r + 8
            for i, frac in enumerate(self.heights):
                angle = 2 * math.pi * i / BARS_N - math.pi / 2
                length = 3 + frac * BAR_MAX
                a = QPointF(c + math.cos(angle) * inner, c + math.sin(angle) * inner)
                b = QPointF(c + math.cos(angle) * (inner + length), c + math.sin(angle) * (inner + length))
                mix = min(1.0, frac * 1.3)
                col = QColor(int(lo.red() + (hi.red() - lo.red()) * mix),
                             int(lo.green() + (hi.green() - lo.green()) * mix),
                             int(lo.blue() + (hi.blue() - lo.blue()) * mix))
                glow = QColor(col)
                glow.setAlpha(int(70 * self.bar_opacity))
                p.setPen(QPen(glow, 6.0, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(a, b)
                col.setAlpha(int(235 * self.bar_opacity))
                p.setPen(QPen(col, 3.0, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(a, b)

        halo = QRadialGradient(c, c, r + 16)
        halo.setColorAt(0.6, QColor(168, 85, 247, int(160 * strength)))
        halo.setColorAt(1.0, QColor(168, 85, 247, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QRectF(c - r - 16, c - r - 16, 2 * (r + 16), 2 * (r + 16)))

        body = QRadialGradient(c, c, r)
        body.setColorAt(0, QColor(30, 12, 64))
        body.setColorAt(1, QColor(5, 2, 14))
        p.setBrush(QBrush(body))
        p.drawEllipse(QRectF(c - r, c - r, 2 * r, 2 * r))

        clip = QPainterPath()
        clip.addEllipse(QRectF(c - r + 2, c - r + 2, 2 * r - 4, 2 * r - 4))
        p.save()
        p.setClipPath(clip)
        if self.logo is not None:
            scaled = self.logo.scaledToWidth(int(2 * r * 0.98), Qt.SmoothTransformation)
            p.drawPixmap(int(c - scaled.width() / 2), int(c - scaled.height() / 2), scaled)
        else:
            p.setPen(QColor(233, 213, 255))
            p.setFont(QFont("Impact", 20))
            p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignCenter, "REEZ")
        p.restore()

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(192, 132, 252, int(110 + 145 * strength)), 2.5))
        p.drawEllipse(QRectF(c - r, c - r, 2 * r, 2 * r))
        if self.mode == "thinking":
            p.setPen(QPen(QColor(233, 213, 255), 3))
            start = int((-self._phase * 400) % 360 * 16)
            p.drawArc(QRectF(c - r - 4, c - r - 4, 2 * r + 8, 2 * r + 8), start, 80 * 16)
        if self.listening_on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(233, 213, 255, int(150 + 105 * pulse)))
            p.drawEllipse(QRectF(c + r * 0.72 - 6, c + r * 0.72 - 6, 11, 11))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._offset = self._press - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, event):
        if self._press is not None and event.buttons() & Qt.LeftButton:
            pos = event.globalPosition().toPoint()
            if (pos - self._press).manhattanLength() > 5:
                self._moved = True
            if self._moved:
                self.move(pos - self._offset)

    def mouseReleaseEvent(self, event):
        if self._dbl:
            self._dbl = False
            self._press = None
            return
        if event.button() == Qt.LeftButton and self._press is not None:
            if self._moved:
                self._save_pos()
            else:
                self._click_timer.start()
            self._press = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._dbl = True
            self.chat_requested.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        a_open = menu.addAction("Open / hide REEZ")
        a_chat = menu.addAction("Quick chat window")
        a_mic = menu.addAction("Speak to REEZ")
        a_listen = menu.addAction("Always listening")
        a_listen.setCheckable(True)
        a_listen.setChecked(self.listening_on)
        a_gest = menu.addAction("Hand gestures")
        a_gest.setCheckable(True)
        a_gest.setChecked(self.gestures_on)
        a_view = menu.addAction("Camera view")
        a_lock = menu.addAction("Lock locker")
        menu.addSeparator()
        a_quit = menu.addAction("Quit REEZ")
        chosen = menu.exec(event.globalPos())
        if chosen == a_open:
            self.open_requested.emit()
        elif chosen == a_chat:
            self.chat_requested.emit()
        elif chosen == a_mic:
            self.mic_requested.emit()
        elif chosen == a_listen:
            self.listen_toggled.emit(not self.listening_on)
        elif chosen == a_gest:
            self.gesture_toggled.emit(not self.gestures_on)
        elif chosen == a_view:
            self.view_requested.emit()
        elif chosen == a_lock:
            self.lock_requested.emit()
        elif chosen == a_quit:
            self.quit_requested.emit()

    def closeEvent(self, event):
        self.bubble.close()
        super().closeEvent(event)
