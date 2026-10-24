"""REEZ desktop window."""

import html
import os
import re
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QGuiApplication, QIcon, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QGraphicsDropShadowEffect, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

import brain
import understanding
from bars import Bars
from floater import Floater
from locker import Locker, normalize

bridge = None
speak_lock = threading.Lock()
transcribe_lock = threading.Lock()


# ---------- helpers that keep the window responsive ----------
class Bridge(QObject):
    """Carries results from background threads back to the window."""
    result = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.result.connect(self._run)

    @Slot(object, object)
    def _run(self, callback, value):
        callback(value)


def background(fn, callback, *args):
    """Run fn in a thread, then call callback(("ok", result) or ("error", message))."""
    def job():
        try:
            value = ("ok", fn(*args))
        except Exception as error:
            value = ("error", str(error))
        bridge.result.emit(callback, value)
    threading.Thread(target=job, daemon=True).start()


def transcribe_locked(audio, accurate=False):
    import voice
    with transcribe_lock:
        return voice.transcribe_accurate(audio) if accurate else voice.transcribe(audio)


def speak_text(text, rate):
    with speak_lock:
        try:
            import tts
            tts.speak(text)
        except Exception:
            pass


def preload_voice():
    try:
        import tts
        tts.load()
    except Exception:
        pass


def warm_up():
    """Load the models and documents in the background so the first answer is fast."""
    try:
        brain.prepare()
    except Exception:
        pass
    try:
        import voice
    except Exception:
        pass


def listen_once():
    import voice
    audio = voice.record()
    if audio is None:
        return ""
    return transcribe_locked(audio, True)


# ---------- theme ----------
STYLE = """
* { font-family: Segoe UI; font-size: 13px; }
QWidget { color: #e4dcff; }
QDialog { background-color: #06030f; }
QToolTip { background-color: #1a0f33; color: #f3e8ff; border: 1px solid #7c3aed; }
QLabel { background: transparent; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: transparent; }
QTabBar::tab { background: rgba(10,6,24,200); color: #a78bfa; padding: 9px 26px; border: 1px solid #3b1a78; border-bottom: none; border-top-left-radius: 12px; border-top-right-radius: 12px; margin-right: 4px; }
QTabBar::tab:selected { background: rgba(30,12,64,230); color: #f3e8ff; border: 1px solid #a855f7; border-bottom: none; }
QTextEdit { background-color: rgba(4,2,12,165); border: 1px solid rgba(168,85,247,170); border-radius: 12px; padding: 10px; selection-background-color: #7c3aed; selection-color: #ffffff; }
QLineEdit { background-color: rgba(4,2,12,200); border: 1px solid #7c3aed; border-radius: 14px; padding: 10px 14px; selection-background-color: #7c3aed; }
QLineEdit:focus { border: 1px solid #c084fc; }
QListWidget { background-color: rgba(4,2,12,165); border: 1px solid rgba(168,85,247,170); border-radius: 12px; padding: 6px; }
QListWidget::item { padding: 8px; border-radius: 8px; }
QListWidget::item:selected { background-color: rgba(124,58,237,150); color: #ffffff; }
QPushButton { background-color: rgba(20,8,48,220); color: #e9d5ff; border: 1px solid #a855f7; border-radius: 12px; padding: 9px 18px; }
QPushButton:hover { background-color: rgba(109,40,217,230); color: #ffffff; border: 1px solid #e9d5ff; }
QPushButton:pressed { background-color: #4c1d95; }
QPushButton:disabled { background-color: rgba(18,16,28,200); color: #4a4560; border: 1px solid #2a2440; }
QPushButton#icon { font-size: 20px; padding: 6px 20px; }
QGroupBox { border: 1px solid rgba(168,85,247,150); border-radius: 12px; margin-top: 14px; padding-top: 12px; color: #c084fc; background: transparent; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #a855f7; border-radius: 5px; background: rgba(4,2,12,200); }
QCheckBox::indicator:checked { background: #7c3aed; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #6d28d9; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLabel#pill { background-color: rgba(20,8,48,215); border: 1px solid #4c1d95; border-radius: 13px; padding: 5px 18px; color: #d8c8ff; }
QLabel#offline { background-color: rgba(10,40,30,200); border: 1px solid #14684b; border-radius: 13px; padding: 5px 14px; color: #6ee7b7; font-weight: 600; }
QLabel#heading { color: #8b7fc9; font-size: 11px; font-weight: 600; }
QLabel#chip { background-color: rgba(30,12,64,220); border: 1px solid #7c3aed; border-radius: 11px; padding: 3px 12px; color: #d8c8ff; font-size: 12px; }
QPushButton#chip { background-color: rgba(30,12,64,220); border: 1px solid #7c3aed; border-radius: 11px; padding: 3px 12px; color: #d8c8ff; font-size: 12px; }
QPushButton#chip:hover { background-color: rgba(109,40,217,230); color: #ffffff; }
QWidget#sidebar { background-color: rgba(6,3,16,205); border: 1px solid rgba(168,85,247,120); border-radius: 14px; }
QFrame#mine { background-color: #5b3fe0; border-radius: 16px; }
QFrame#reez { background-color: rgba(10,6,26,225); border: 1px solid rgba(168,85,247,140); border-radius: 16px; }
"""


def glow(radius=22, color="#a855f7"):
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(radius)
    effect.setOffset(0, 0)
    effect.setColor(QColor(color))
    return effect


def crest_pixmap(size):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 48.0
    pts = [(24, 1), (31, 17), (47, 24), (31, 31), (24, 47), (17, 31), (1, 24), (17, 17)]
    poly = QPolygonF([QPointF(x * s, y * s) for x, y in pts])
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#e9d5ff"))
    grad.setColorAt(1, QColor("#6d28d9"))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor("#c084fc"), 1))
    p.drawPolygon(poly)
    p.end()
    return pix


def logo_pixmap(size):
    """The REEZ logo (theme/logo.png), scaled to fit, or the crest if there is none."""
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
        path = Path(__file__).parent / "theme" / name
        if path.exists():
            src = QPixmap(str(path))
            if not src.isNull():
                return src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return crest_pixmap(size)

def load_bg():
    """Optional artwork in theme/bg.png. Only the middle scene is used."""
    for name in ("bg.png", "bg.jpg", "bg.jpeg", "bg.webp"):
        path = Path(__file__).parent / "theme" / name
        if path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                w, h = pix.width(), pix.height()
                return pix.copy(int(w * 0.12), int(h * 0.16), int(w * 0.82), int(h * 0.64))
    return None


def draw_background(widget, pix=None, watermark=True):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    w, h = widget.width(), widget.height()
    painter.fillRect(0, 0, w, h, QColor("#04020a"))
    for cx, cy in ((0, h), (w, h), (w, 0), (0, 0)):
        halo = QRadialGradient(cx, cy, max(w, h) * 0.5)
        halo.setColorAt(0, QColor(124, 58, 237, 150))
        halo.setColorAt(1, QColor(124, 58, 237, 0))
        painter.fillRect(0, 0, w, h, QBrush(halo))
    painter.setBrush(Qt.NoBrush)
    for i in range(8, 0, -1):
        pen = QPen(QColor(168, 85, 247, 14 * i))
        pen.setWidth(i)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(6, 6, w - 12, h - 12), 14, 14)
    painter.setPen(QPen(QColor(192, 132, 252, 220), 1.5))
    painter.drawRoundedRect(QRectF(6, 6, w - 12, h - 12), 14, 14)
    if watermark:
        font = QFont("Impact", max(24, int(h * 0.15)))
        font.setLetterSpacing(QFont.AbsoluteSpacing, 8)
        painter.setFont(font)
        area = QRectF(0, h * 0.28, w, h * 0.3)
        for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4), (-3, -3), (3, 3), (-3, 3), (3, -3)):
            painter.setPen(QColor(168, 85, 247, 38))
            painter.drawText(area.translated(dx, dy), Qt.AlignCenter, "REEZ")
        painter.setPen(QColor(233, 213, 255, 70))
        painter.drawText(area, Qt.AlignCenter, "REEZ")
    painter.end()


# ---------- chat: bubbles ----------
class MessageBubble(QFrame):
    def __init__(self, who, text):
        super().__init__()
        self.setObjectName("mine" if who == "You" else "reez")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setText(text)
        self.label.setMaximumWidth(560)
        layout.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)


class ChatView(QScrollArea):
    """The conversation: bubbles, source chips, typing dots and code boxes."""

    sources_requested = Signal(list)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: 1px solid rgba(168,85,247,170); border-radius: 14px; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            "QWidget#chatinner { background: transparent; }")
        self.viewport().setAutoFillBackground(False)
        self.inner = QWidget()
        self.inner.setObjectName("chatinner")
        self.inner.setAutoFillBackground(False)
        self.box = QVBoxLayout(self.inner)
        self.box.setContentsMargins(18, 16, 18, 16)
        self.box.setSpacing(8)
        self.box.addStretch(1)
        self.setWidget(self.inner)
        self.typing = None
        self._typing_row = None
        self._dot = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._tick_dots)

    def _row(self, widget, mine):
        row = QHBoxLayout()
        if mine:
            row.addStretch(1)
            row.addWidget(widget)
        else:
            row.addWidget(widget)
            row.addStretch(1)
        self.box.insertLayout(self.box.count() - 1, row)
        return row

    def _scroll(self):
        def go():
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(40, go)

    def add_message(self, who, text, sources=None):
        self.hide_typing()
        self._row(MessageBubble(who, text), who == "You")
        if sources and who != "You":
            n = len(sources)
            chip = QPushButton(str(n) + (" source found" if n == 1 else " sources found"))
            chip.setObjectName("chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip("Click to see which files this came from")
            chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            chip.clicked.connect(lambda _checked=False, s=list(sources): self.sources_requested.emit(s))
            self._row(chip, False)
        self._scroll()

    def add_code(self, text):
        self.hide_typing()
        box = QTextEdit()
        box.setReadOnly(True)
        box.setAcceptDrops(False)
        box.setLineWrapMode(QTextEdit.NoWrap)
        box.setFont(QFont("Consolas", 10))
        box.setPlainText(text)
        box.setFixedHeight(340)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box.setStyleSheet(
            "QTextEdit { background-color: rgba(4,2,12,235); border: 1px solid rgba(168,85,247,150); "
            "border-radius: 12px; padding: 8px; color: #d9d3ee; }")
        self._row(box, False)
        self._scroll()

    def show_typing(self):
        if self.typing is None:
            self.typing = QLabel()
            self.typing.setObjectName("chip")
            self.typing.setTextFormat(Qt.RichText)
            self._typing_row = self._row(self.typing, False)
            self._tick_dots()
            self._dot_timer.start(350)
            self._scroll()

    def hide_typing(self):
        if self.typing is not None:
            self._dot_timer.stop()
            self.box.removeItem(self._typing_row)
            self.typing.setParent(None)
            self.typing.deleteLater()
            self._typing_row.deleteLater()
            self.typing = None
            self._typing_row = None

    def _tick_dots(self):
        if self.typing is None:
            return
        self._dot = (self._dot + 1) % 3
        colors = ["#5b4a99"] * 3
        colors[self._dot] = "#e9d5ff"
        self.typing.setText("".join('<span style="color:%s;">&#9679;</span>&nbsp;&nbsp;' % c for c in colors))


# ---------- drag and drop box (locker) ----------
class DropZone(QLabel):
    dropped = Signal(list)

    def __init__(self):
        super().__init__("Drag and drop files or photos here")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(90)
        self.setStyleSheet("border: 2px dashed #a855f7; border-radius: 14px; padding: 12px; color: #c084fc; background-color: rgba(4,2,12,165);")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)
        event.acceptProposedAction()


# ---------- viewer: shows decrypted items from memory only ----------
class Viewer(QDialog):
    def __init__(self, parent, item, data):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(item["name"])
        self.resize(780, 660)
        self._pix = None
        self._doc = None
        self._page = 0
        layout = QVBoxLayout(self)
        kind = item["kind"]
        if kind == "note":
            box = QTextEdit()
            box.setReadOnly(True)
            box.setPlainText(data.decode("utf-8", errors="replace"))
            layout.addWidget(box)
            return
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.label, 1)
        if kind == "image":
            pix = QPixmap()
            pix.loadFromData(data)
            self._pix = pix
        elif kind == "pdf":
            import pymupdf
            self._doc = pymupdf.open(stream=data, filetype="pdf")
            bar = QHBoxLayout()
            prev_btn, next_btn = QPushButton("Previous"), QPushButton("Next")
            self.count = QLabel()
            bar.addWidget(prev_btn)
            bar.addWidget(self.count, 1, Qt.AlignCenter)
            bar.addWidget(next_btn)
            layout.addLayout(bar)
            prev_btn.clicked.connect(lambda: self._go(-1))
            next_btn.clicked.connect(lambda: self._go(1))
            self._show_page()
        QTimer.singleShot(0, self._fit)

    def _show_page(self):
        pix = self._doc[self._page].get_pixmap(dpi=110)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(image)
        self.count.setText("Page " + str(self._page + 1) + " of " + str(len(self._doc)))
        self._fit()

    def _go(self, step):
        self._page = max(0, min(len(self._doc) - 1, self._page + step))
        self._show_page()

    def _fit(self):
        if self._pix is not None and not self._pix.isNull() and hasattr(self, "label"):
            self.label.setPixmap(self._pix.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def closeEvent(self, event):
        self._pix = None
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        super().closeEvent(event)


# ---------- dialogs ----------
class SetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set up your locker")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.folder = QLineEdit()
        self.code, self.code2 = QLineEdit(), QLineEdit()
        self.master, self.master2 = QLineEdit(), QLineEdit()
        for box in (self.code, self.code2, self.master, self.master2):
            box.setEchoMode(QLineEdit.Password)
        form.addRow("Folder name (you say this to open the locker, 1 to 4 words)", self.folder)
        form.addRow("Code word (6+ letters or digits)", self.code)
        form.addRow("Repeat code word", self.code2)
        form.addRow("Master word (12+ characters, typed only)", self.master)
        form.addRow("Repeat master word", self.master2)
        form.addRow(QLabel("Never say the master word out loud. If you forget both words, the locker cannot be recovered."))
        row = QHBoxLayout()
        ok, cancel = QPushButton("Create locker"), QPushButton("Skip for now")
        row.addWidget(ok)
        row.addWidget(cancel)
        form.addRow(row)
        ok.clicked.connect(self._check)
        cancel.clicked.connect(self.reject)

    def _check(self):
        if normalize(self.code.text()) != normalize(self.code2.text()):
            QMessageBox.warning(self, "REEZ", "The code words do not match.")
            return
        if self.master.text().strip() != self.master2.text().strip():
            QMessageBox.warning(self, "REEZ", "The master words do not match.")
            return
        self.accept()


class CodeDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("REEZ")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Code word please:"))
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.field)
        self.status = QLabel("")
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.say_btn = QPushButton("Say it")
        ok, cancel = QPushButton("Unlock"), QPushButton("Cancel")
        ok.setDefault(True)
        for b in (self.say_btn, ok, cancel):
            row.addWidget(b)
        layout.addLayout(row)
        self.say_btn.clicked.connect(self._listen)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

    def _listen(self):
        self.status.setText("Listening... (the first time takes a while)")
        self.say_btn.setEnabled(False)
        background(listen_once, self._heard)

    def _heard(self, value):
        try:
            self.say_btn.setEnabled(True)
            kind, text = value
            if kind == "ok" and text:
                self.field.setText(text)
                self.status.setText("Heard it. Press Unlock.")
            else:
                self.status.setText("I did not catch that. Try again or type it.")
        except RuntimeError:
            pass


# ---------- the locker tab ----------
class LockerPanel(QWidget):
    def __init__(self, locker, window):
        super().__init__()
        self.lk = locker
        self.win = window
        self.viewer = None
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.status = QLabel()
        lock_btn = QPushButton("Lock")
        top.addWidget(self.status, 1)
        top.addWidget(lock_btn)
        layout.addLayout(top)

        self.drop = DropZone()
        layout.addWidget(self.drop)
        row = QHBoxLayout()
        browse_btn, note_btn = QPushButton("Browse files..."), QPushButton("New note")
        row.addWidget(browse_btn)
        row.addWidget(note_btn)
        layout.addLayout(row)

        self.items = QListWidget()
        layout.addWidget(self.items, 1)
        row2 = QHBoxLayout()
        show_btn, export_btn, delete_btn = QPushButton("Show"), QPushButton("Export"), QPushButton("Delete")
        for b in (show_btn, export_btn, delete_btn):
            row2.addWidget(b)
        layout.addLayout(row2)

        ask_row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("Ask about your private notes and PDFs (the answer shows on screen only)")
        ask_btn = QPushButton("Ask")
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(ask_btn)
        layout.addLayout(ask_row)
        self.answer = QTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setMaximumHeight(90)
        layout.addWidget(self.answer)

        self.master_box = QGroupBox("Master controls")
        mrow = QHBoxLayout(self.master_box)
        for text, fn in (("Change code word", self.change_code),
                         ("Change master word", self.change_master),
                         ("Rename folder", self.rename),
                         ("Erase locker", self.erase)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            mrow.addWidget(b)
        layout.addWidget(self.master_box)

        lock_btn.clicked.connect(self.win.lock_locker)
        self.drop.dropped.connect(self.add_paths)
        browse_btn.clicked.connect(self.browse)
        note_btn.clicked.connect(self.new_note)
        show_btn.clicked.connect(self.show_item)
        export_btn.clicked.connect(self.export_item)
        delete_btn.clicked.connect(self.delete_item)
        ask_btn.clicked.connect(self.ask)
        self.question.returnPressed.connect(self.ask)
        self.refresh()

    def _try(self, fn, *args):
        try:
            return fn(*args)
        except PermissionError as error:
            QMessageBox.warning(self, "REEZ", str(error))
            self.win.check_locked()
        except KeyError:
            QMessageBox.warning(self, "REEZ", "I cannot find that item.")
        except (ValueError, FileNotFoundError, FileExistsError) as error:
            QMessageBox.warning(self, "REEZ", str(error))
        return None

    def refresh(self):
        self.items.clear()
        try:
            for item in self.lk.list_items():
                row = QListWidgetItem(item["name"] + "   (" + item["kind"] + ")")
                row.setData(Qt.UserRole, item["name"])
                self.items.addItem(row)
        except PermissionError:
            return
        self.status.setText("Locker open" + (" (master mode)" if self.lk.is_master else ""))
        self.master_box.setVisible(self.lk.is_master)

    def _selected(self):
        row = self.items.currentItem()
        if row is None:
            QMessageBox.information(self, "REEZ", "Pick an item from the list first.")
            return None
        return row.data(Qt.UserRole)

    def add_paths(self, paths):
        saved = False
        for path in paths:
            name, ok = QInputDialog.getText(self, "Name it", "Name for " + Path(path).name + ":", text=Path(path).stem)
            if ok and name.strip() and self._try(self.lk.add_file, path, name.strip()) is None:
                saved = saved or any(i["name"] == name.strip() for i in self.lk.list_items())
        self.refresh()
        if saved:
            QMessageBox.information(self, "REEZ", "Saved. Delete the original copy yourself so the locker holds the only copy.")

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files for the locker")
        if paths:
            self.add_paths(paths)

    def new_note(self):
        name, ok = QInputDialog.getText(self, "New note", "Name:")
        if not ok or not name.strip():
            return
        text, ok = QInputDialog.getMultiLineText(self, "New note", "Text:")
        if ok:
            self._try(self.lk.add_note, name.strip(), text)
            self.refresh()

    def show_item(self):
        name = self._selected()
        if not name:
            return
        got = self._try(self.lk.get_bytes, name)
        if not got:
            return
        item, data = got
        if item["kind"] in ("note", "image", "pdf"):
            self.viewer = Viewer(self, item, data)
            self.viewer.show()
        else:
            QMessageBox.information(self, "REEZ", "REEZ cannot open this type here. Use Export, then open it yourself.")

    def export_item(self):
        name = self._selected()
        if not name:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the decrypted copy in...")
        if folder:
            target = self._try(self.lk.export, name, folder)
            if target:
                QMessageBox.information(self, "REEZ", "Saved to " + str(target) + ". This copy is NOT encrypted.")

    def delete_item(self):
        name = self._selected()
        if name and QMessageBox.question(self, "REEZ", "Delete " + name + " from the locker?") == QMessageBox.Yes:
            self._try(self.lk.delete, name)
            self.refresh()

    def ask(self):
        q = self.question.text().strip()
        if not q:
            return
        self.answer.setPlainText("Thinking...")
        background(self.lk.ask, self._answered, q)

    def _answered(self, value):
        kind, text = value
        try:
            self.answer.setPlainText(text if kind == "ok" else "Sorry: " + text)
        except RuntimeError:
            pass

    def _password(self, title, label):
        text, ok = QInputDialog.getText(self, title, label, QLineEdit.Password)
        return text if ok and text else None

    def change_code(self):
        word = self._password("Change code word", "New code word:")
        if word and self._try(self.lk.change_code, word) is None:
            QMessageBox.information(self, "REEZ", "If no error appeared, the code word is changed.")

    def change_master(self):
        word = self._password("Change master word", "New master word (12+ characters):")
        if word and self._try(self.lk.change_master, word) is None:
            QMessageBox.information(self, "REEZ", "If no error appeared, the master word is changed.")

    def rename(self):
        name, ok = QInputDialog.getText(self, "Rename folder", "New folder name (1 to 4 words):")
        if ok and name.strip():
            self._try(self.lk.rename_folder, name.strip())

    def erase(self):
        text, ok = QInputDialog.getText(self, "Erase locker", "Type DELETE to erase everything in the locker:")
        if ok and text == "DELETE":
            self._try(self.lk.reset)
            self.win.after_erase()


# ---------- quick chat window ----------
class MiniChat(QWidget):
    """A compact chat window that shows the live conversation and context."""

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.setWindowTitle("REEZ - quick chat")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("MiniChat { background-color: #06030f; }")
        self.resize(430, 580)
        layout = QVBoxLayout(self)
        self.context = QLabel()
        self.context.setWordWrap(True)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask REEZ anything...")
        send_btn = QPushButton("\u27a4")
        send_btn.setObjectName("icon")
        mic_btn = QPushButton("\U0001F3A4")
        mic_btn.setObjectName("icon")
        row.addWidget(self.input, 1)
        row.addWidget(send_btn)
        row.addWidget(mic_btn)
        layout.addWidget(self.context)
        layout.addWidget(self.view, 1)
        layout.addLayout(row)
        send_btn.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)
        mic_btn.clicked.connect(window.listen)

    def _label(self):
        last = self.win.last_file
        self.context.setText(
            "Context: " + (last.name if last else "no file yet")
            + "   |   remembers " + str(len(self.win.history)) + " messages"
            + "   |   locker " + ("open" if self.win.lk.is_open else "locked"))

    def refresh(self):
        self.view.setHtml("<br>".join(self.win.lines[-60:]))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._label()

    def append(self, line):
        self.view.append(line)
        self._label()

    def send(self):
        text = self.input.text()
        self.input.clear()
        self.win.handle_text(text)


# ---------- the main window ----------
class CameraView(QWidget):
    """A small window showing the camera and the hand skeleton, so you can see what REEZ sees."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("REEZ - camera view")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("CameraView { background-color: #06030f; }")
        layout = QVBoxLayout(self)
        self.picture = QLabel("Starting the camera...")
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumSize(320, 240)
        self.note = QLabel("Open palm: wake REEZ    Fist: stop    Peace: repeat    One finger: next control    Thumbs up: open or hide")
        self.note.setWordWrap(True)
        layout.addWidget(self.picture)
        layout.addWidget(self.note)
        self.engine = None

    def show_frame(self, data, w, h):
        image = QImage(data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.picture.setPixmap(QPixmap.fromImage(image))

    def closeEvent(self, event):
        if self.engine is not None:
            self.engine.preview = False
        super().closeEvent(event)


class ReezWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("REEZ")
        self.resize(1060, 740)
        self.lk = Locker()
        self.history = []
        self.lines = []
        self.mini = None
        self.speak_rate = 175
        self.speaking = False
        self.always_listening = True
        self.listener = None
        self._voice_turn = False
        self.busy = False
        self.panel = None
        self.last_file = None
        self.last_reply = ""
        self.gestures = None
        self.camera_view = None
        self.adjust = None
        self.adjust_until = 0.0
        self._quitting = False
        self._started = False
        self._docs_names = ()
        self.bg = load_bg()
        self.art = self.bg
        self._art_size = None
        self._art_scaled = None
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        chat = QWidget()
        outer = QVBoxLayout(chat)
        outer.setContentsMargins(14, 12, 14, 10)
        outer.setSpacing(10)

        top = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(logo_pixmap(36))
        title = QLabel("reez \u00b7 local")
        title.setObjectName("pill")
        offline = QLabel('<span style="color:#34d399;">&#9679;</span>&nbsp; OFFLINE')
        offline.setObjectName("offline")
        offline.setTextFormat(Qt.RichText)
        top.addWidget(mark)
        top.addStretch(1)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(offline)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(12)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(224)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 14, 14, 12)
        heading = QLabel("DOCUMENTS")
        heading.setObjectName("heading")
        self.docs_list = QListWidget()
        self.docs_list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        add_files = QPushButton("+  Add files")
        sl.addWidget(heading)
        sl.addWidget(self.docs_list, 1)
        sl.addWidget(add_files)
        body.addWidget(side)

        column = QVBoxLayout()
        self.log = ChatView()
        self.log.sources_requested.connect(self.show_sources)
        column.addWidget(self.log, 1)
        self.state = QLabel("")
        column.addWidget(self.state)
        row = QHBoxLayout()
        plus_btn = QPushButton("+")
        plus_btn.setObjectName("icon")
        plus_btn.setToolTip("Add files from this computer")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask REEZ anything...")
        self.input.setAcceptDrops(False)
        send_btn = QPushButton("\u27a4")
        send_btn.setObjectName("icon")
        send_btn.setToolTip("Send")
        self.mic = QPushButton("\U0001F3A4")
        self.mic.setObjectName("icon")
        self.mic.setToolTip("Speak to REEZ")
        row.addWidget(plus_btn)
        row.addWidget(self.input, 1)
        row.addWidget(send_btn)
        row.addWidget(self.mic)
        column.addLayout(row)
        for widget in (self.input, send_btn, self.mic):
            widget.setGraphicsEffect(glow())
        bottom = QHBoxLayout()
        self.speak_box = QCheckBox("Speak answers")
        self.speak_box.setChecked(True)
        self.setup_btn = QPushButton("Set up locker")
        self.setup_btn.setVisible(not self.lk.exists())
        bottom.addWidget(self.speak_box)
        bottom.addStretch(1)
        bottom.addWidget(self.setup_btn)
        column.addLayout(bottom)
        body.addLayout(column, 1)
        outer.addLayout(body, 1)
        self.tabs.addTab(chat, "Chat")
        self.tabs.tabBar().setVisible(False)

        send_btn.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)
        self.mic.clicked.connect(self.listen)
        plus_btn.clicked.connect(self.plus_menu)
        add_files.clicked.connect(self.plus_menu)
        self.setup_btn.clicked.connect(self.setup_locker)
        self.docs_list.itemClicked.connect(self._doc_clicked)
        self.docs_list.itemDoubleClicked.connect(self._doc_opened)
        self.refresh_docs()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(5000)
        self.add("REEZ", "Hello, I am REEZ. How can I help you?")

        threading.Thread(target=warm_up, daemon=True).start()
        threading.Thread(target=preload_voice, daemon=True).start()
        self.floater = Floater()
        self.floater.open_requested.connect(self.toggle_window)
        self.floater.mic_requested.connect(self.listen)
        self.floater.lock_requested.connect(self.lock_if_open)
        self.floater.quit_requested.connect(self.quit_app)
        self.floater.show()
        self.floater.chat_requested.connect(self.open_mini)
        self.floater.listen_toggled.connect(self.set_listening)
        self.floater.gesture_toggled.connect(self.set_gestures)
        self.floater.view_requested.connect(self.open_camera_view)
        try:
            if GESTURE_FILE.exists() and GESTURE_FILE.read_text().strip() == "on":
                QTimer.singleShot(2500, lambda: self.set_gestures(True))
        except Exception:
            pass
        QTimer.singleShot(1500, self.start_listener)
        self.bars = None
        pass
        self._bars_timer = QTimer(self)
        self._bars_timer.timeout.connect(self._bars_tick)
        self._bars_timer.start(50)
        self._started = True

    # ----- documents sidebar -----
    def refresh_docs(self):
        files = brain._all_files()
        self._docs_names = tuple(str(p.relative_to(brain.DOCS_DIR)) for p in files)
        current = self.last_file.name if self.last_file else None
        self.docs_list.clear()
        for p, name in zip(files, self._docs_names):
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, str(p))
            if p.suffix.lower() not in brain.READABLE:
                item.setForeground(QColor("#6b6490"))
                item.setToolTip("Stored, but REEZ cannot read inside this type of file")
            self.docs_list.addItem(item)
            if current and p.name == current:
                self.docs_list.setCurrentItem(item)

    def _doc_clicked(self, item):
        self.last_file = Path(item.data(Qt.UserRole))
        self.state.setText("Context: " + self.last_file.name)

    def _doc_opened(self, item):
        try:
            os.startfile(item.data(Qt.UserRole))
        except Exception:
            pass

    # ----- chat -----
    def add(self, who, text, sources=None):
        self.log.add_message(who, text, sources)
        line = ('<span style="color:' + ("#c084fc" if who == "REEZ" else "#94a3b8") + ';"><b>'
                + ("\u25c6 " if who == "REEZ" else "") + who + ":</b></span> " + html.escape(text))
        self.lines.append(line)
        if len(self.lines) > 300:
            del self.lines[:100]
        if self.mini is not None:
            self.mini.append(line)
        if (who == "REEZ" and self._started and not self.isVisible()
                and (self.mini is None or not self.mini.isVisible())):
            self.floater.say(text)

    def set_mode(self, mode):
        if hasattr(self, "floater"):
            self.floater.set_mode(mode)

    def speak(self, text):
        if self.speak_box.isChecked():
            self.speaking = True
            self.set_mode("speaking")

            def job():
                speak_text(text, self.speak_rate)
                bridge.result.emit(self._speech_done, None)

            threading.Thread(target=job, daemon=True).start()

    def _speech_done(self, _value):
        self.speaking = False
        self.set_mode("idle")
        if self._voice_turn and self.listener is not None:
            self.listener.awake_until = max(self.listener.awake_until, time.time() + 6)
            self._voice_turn = False

    def send(self):
        text = self.input.text()
        self.input.clear()
        self.handle_text(text)

    def handle_text(self, text, voice=False):
        text = brain.tanglish_commands(text.strip())
        if not text or self.busy:
            return
        if self.lk.exists() and self.lk.is_trigger(text):
            self.add("You", "(locker request)")
            self.open_locker_flow()
            return
        self.add("You", text)
        if self.lk.is_open and normalize(text) in ("lock", "lock it", "lock the locker", "lock locker"):
            self.lock_locker()
            return
        self._voice_turn = voice
        if self._control_command(text):
            return
        named = brain.named_file(text)
        if named is not None:
            self.last_file = named
        command = brain.file_command(text, self.last_file)
        if command:
            self._file_action(command)
            return
        question = text
        if self.last_file is not None and named is None and brain.refers_to_last(text):
            question = text + " (file: " + self.last_file.stem + ")"
        self.busy = True
        self.state.setText("")
        self.log.show_typing()
        self.set_mode("thinking")
        background(self._think, self._replied, question, list(self.history), voice)

    def _think(self, text, history, voice=False):
        result = understanding.process(text, history, tanglish_ok=not voice)
        if result["intent"] == "exit":
            return "Goodbye! Close the window when you are done.", result["question"], False, []
        if result["intent"] == "chat":
            return understanding.small_talk(text, history), result["question"], True, []
        if result["intent"] == "general":
            return brain.general(result["question"], history), result["question"], True, []
        reply, sources = brain.answer(result["question"], spoken=True)
        if reply.strip().lower().startswith(("i don't know", "i could not find")):
            sources = []
        return reply, result["question"], True, sources

    def _replied(self, value):
        self.set_mode("idle")
        self.busy = False
        self.state.setText("")
        self.log.hide_typing()
        kind, data = value
        if kind == "error":
            self.add("REEZ", "Something went wrong: " + data)
            return
        reply, question, remember, sources = data
        self.add("REEZ", reply, sources)
        self.last_reply = reply
        if remember:
            understanding.remember(self.history, question, reply)
        self.speak(spoken_text(reply))

    def listen(self):
        if self.busy:
            return
        self.busy = True
        self.mic.setEnabled(False)
        self.state.setText("Listening... speak now (the first time takes a while to load)")
        self.set_mode("listening")
        background(listen_once, self._heard)

    def _heard(self, value):
        self.set_mode("idle")
        self.busy = False
        self.mic.setEnabled(True)
        self.state.setText("")
        kind, text = value
        if kind == "error":
            self.add("REEZ", "I could not use the microphone: " + text)
        elif text:
            self.handle_text(text, voice=True)
        else:
            self.state.setText("I did not hear anything.")

    # ----- files -----
    def plus_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #0a0614; color: #e9d5ff; border: 1px solid #7c3aed; padding: 6px; }"
            "QMenu::item { padding: 8px 22px; border-radius: 6px; }"
            "QMenu::item:selected { background-color: #4c1d95; }")
        a_add = menu.addAction("Add files from this computer...")
        a_open = menu.addAction("Open the documents folder")
        chosen = menu.exec(QCursor.pos())
        if chosen == a_add:
            paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to store in REEZ", str(Path.home()), "All files (*)")
            if paths:
                self.add_docs(paths)
        elif chosen == a_open:
            brain.DOCS_DIR.mkdir(exist_ok=True)
            os.startfile(str(brain.DOCS_DIR))

    def add_docs(self, paths):
        import shutil
        stored, unread, failed = [], [], []
        brain.DOCS_DIR.mkdir(exist_ok=True)
        for src in paths:
            p = Path(src)
            if not p.exists():
                failed.append(p.name)
                continue
            target = brain.DOCS_DIR / p.name
            n = 1
            while target.exists():
                target = brain.DOCS_DIR / (p.stem + "_" + str(n) + p.suffix)
                n += 1
            try:
                if p.is_dir():
                    shutil.copytree(p, target)
                else:
                    shutil.copy2(p, target)
            except Exception:
                failed.append(p.name)
                continue
            stored.append(target.name)
            self.last_file = target
            if p.is_file() and p.suffix.lower() not in brain.READABLE:
                unread.append(target.name)
        if stored:
            self.add("REEZ", "Stored: " + ", ".join(stored) + ".")
            self.refresh_docs()
            if len(unread) < len(stored):
                self.add("REEZ", "Reading what I can. One moment.")
                background(self._reindex, self._docs_ready)
        if unread:
            self.add("REEZ", "I stored these but cannot read inside them: " + ", ".join(unread) + ".")
        if failed:
            self.add("REEZ", "I could not store: " + ", ".join(failed) + ".")

    def _reindex(self):
        brain._load()
        brain._ensure_db()
        return True

    def _docs_ready(self, value):
        self.add("REEZ", "Ready. You can ask about them now.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.tabs.currentIndex() == 0:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.tabs.currentIndex() != 0:
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_docs(paths)
        event.acceptProposedAction()

    def _file_action(self, command):
        kind, path = command
        self.last_file = path
        if kind == "open":
            try:
                os.startfile(str(path))
                self.add("REEZ", "Opening " + path.name + ".")
            except Exception:
                self.add("REEZ", "I could not open " + path.name + ".")
            return
        try:
            data = path.read_bytes()[:500000]
        except Exception:
            self.add("REEZ", "I could not read " + path.name + ".")
            return
        if b"\x00" in data[:2000]:
            self.add("REEZ", path.name + " is not a text file, so it has no code to show. Say open it to open it.")
            return
        self.add("REEZ", "Here is the code of " + path.name + ":")
        self.log.add_code(data.decode("utf-8", "replace"))
        if path.stat().st_size > 500000:
            self.add("REEZ", "That file is very large, so I showed the first 500000 characters. Say open it to see the whole file.")

    # ----- window, icon and voice assistant -----
    # ----- hand gestures and controls -----
    def set_gestures(self, on):
        self.floater.gestures_on = on
        try:
            GESTURE_FILE.parent.mkdir(exist_ok=True)
            GESTURE_FILE.write_text("on" if on else "off")
        except Exception:
            pass
        if on and self.gestures is None:
            try:
                from gestures import GestureEngine
            except Exception as error:
                self.floater.say("Gestures could not start: " + str(error)[:60], 5)
                self.floater.gestures_on = False
                return

            def event(kind, value):
                bridge.result.emit(self._gesture_event, (kind, value))

            def frame(data, w, h):
                bridge.result.emit(self._camera_frame, (data, w, h))

            self.gestures = GestureEngine(event, frame)
            self.gestures.adjusting = self.adjust is not None
            self.gestures.preview = self.camera_view is not None and self.camera_view.isVisible()
            self.gestures.start()
        elif not on and self.gestures is not None:
            self.gestures.running = False
            self.gestures = None
            self._end_adjust(silent=True)
            self.floater.say("Hand gestures are off.", 2)

    def open_camera_view(self):
        if self.camera_view is None:
            self.camera_view = CameraView()
        if self.gestures is None:
            self.set_gestures(True)
        self.camera_view.show()
        self.camera_view.raise_()
        if self.gestures is not None:
            self.camera_view.engine = self.gestures
            self.gestures.preview = True

    def _camera_frame(self, value):
        if self.camera_view is not None and self.camera_view.isVisible():
            self.camera_view.show_frame(*value)

    def _gesture_event(self, value):
        kind, data = value
        if kind == "status":
            self.floater.say(data, 4)
            low = data.lower()
            if "cannot" in low or "missing" in low or "need" in low or "could not" in low:
                self.floater.gestures_on = False
                self.gestures = None
            return
        if kind == "adjust":
            self._adjust_step(data)
            return
        if data == "open":
            self._wake_heard(("", True))
        elif data == "fist":
            if self.adjust:
                self._end_adjust()
            else:
                try:
                    import tts
                    tts.stop()
                except Exception:
                    pass
                self.floater.say("Stopped.", 1.5)
        elif data == "peace":
            if self.last_reply:
                self.floater.say("Repeating.", 1.5)
                self.speak(spoken_text(self.last_reply))
        elif data == "point":
            order = ["volume", "speed", "scroll"]
            nxt = order[(order.index(self.adjust) + 1) % 3] if self.adjust in order else "volume"
            self._set_adjust(nxt)
        elif data == "thumbs_up":
            self.toggle_window()

    def _control_command(self, text):
        """Voice controls: volume, speed, scroll, louder, quieter, faster, slower, done."""
        t = re.sub(r"[^a-z ]", "", text.lower()).strip()
        words = t.split()
        if not words or len(words) > 4:
            return False
        if t in ("done", "stop adjusting", "thats enough", "enough", "okay done"):
            if self.adjust:
                self._end_adjust()
                return True
            return False
        name = None
        for key, label in (("volume", "volume"), ("louder", "volume"), ("quieter", "volume"),
                           ("speed", "speed"), ("faster", "speed"), ("slower", "speed"), ("scroll", "scroll")):
            if key in words:
                name = label
                break
        if name is None:
            return False
        step = 0
        if "up" in words or "louder" in words or "faster" in words:
            step = 1
        elif "down" in words or "quieter" in words or "slower" in words:
            step = -1
        if step:
            self._adjust_step(step, name)
        else:
            self._set_adjust(name)
        return True

    def _set_adjust(self, name):
        self.adjust = name
        self.adjust_until = time.time() + 15
        if self.gestures is not None:
            self.gestures.adjusting = True
            self.floater.say(name.title() + ": raise or lower your open hand. Make a fist or say done to stop.", 6)
        else:
            self.floater.say(name.title() + ": say " + name + " up or down, or turn on Hand gestures from the icon menu.", 6)

    def _end_adjust(self, silent=False):
        self.adjust = None
        if self.gestures is not None:
            self.gestures.adjusting = False
        if not silent:
            self.floater.say("Done.", 1.5)

    def _adjust_step(self, step, name=None):
        name = name or self.adjust
        if not name:
            return
        self.adjust_until = time.time() + 15
        if name == "volume":
            import tts
            tts.VOLUME = max(0.2, min(1.6, tts.VOLUME + 0.1 * step))
            self.floater.say("Volume %d%%" % round(tts.VOLUME * 100), 1.2)
        elif name == "speed":
            import tts
            tts.DEEPEN = max(0.80, min(1.15, tts.DEEPEN + 0.03 * step))
            self.floater.say("Voice speed %d%%" % round(tts.DEEPEN / 0.92 * 100), 1.2)
        elif name == "scroll":
            bar = self.log.verticalScrollBar()
            bar.setValue(bar.value() - step * 120)

    def show_sources(self, names):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #0a0614; color: #e9d5ff; border: 1px solid #7c3aed; padding: 6px; }"
            "QMenu::item { padding: 8px 22px; border-radius: 6px; }"
            "QMenu::item:selected { background-color: #4c1d95; }")
        files = {p.name: p for p in brain._all_files()}
        actions = {}
        for name in names:
            label = (brain.display_name(files[name]) + "   -   " + name) if name in files else name
            actions[menu.addAction(label)] = name
        chosen = menu.exec(QCursor.pos())
        name = actions.get(chosen)
        if name and name in files:
            self.last_file = files[name]
            self.state.setText("Context: " + name)
            try:
                os.startfile(str(files[name]))
            except Exception:
                pass

    def toggle_window(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
            if self.lk.is_open:
                self.lock_locker()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def lock_if_open(self):
        if self.lk.is_open:
            self.lock_locker()

    def quit_app(self):
        self._quitting = True
        self.lk.lock()
        if self.listener is not None:
            self.listener.running = False
        if self.gestures is not None:
            self.gestures.running = False
        pass
        self.floater.close()
        QApplication.quit()

    def start_listener(self):
        try:
            from listener import Listener
        except Exception:
            return

        def heard(command, woke_only):
            bridge.result.emit(self._wake_heard, (command, woke_only))

        def paused():
            return self.busy or self.speaking or not self.always_listening

        def status(message):
            bridge.result.emit(self._listener_status, message)

        self.listener = Listener(heard, paused, transcribe_locked, status,
                                 lambda audio: transcribe_locked(audio, True))
        self.listener.start()

    def _wake_heard(self, value):
        command, woke_only = value
        if woke_only:
            self.floater.say("Yes?", 3)
            self.set_mode("listening")
            self._voice_turn = True
            if self.listener is not None:
                self.listener.awake_until = time.time() + 8
            self.speak("Yes?")
            QTimer.singleShot(8000, self._calm)
            return
        self.handle_text(command, voice=True)

    def _listener_status(self, message):
        self.floater.say(message, 5)

    def _calm(self):
        if self.floater.mode == "listening" and not self.speaking and not self.busy:
            self.set_mode("idle")

    def set_listening(self, on):
        self.always_listening = on
        self.floater.listening_on = on
        self.floater.say(
            "Always listening is on. Say REEZ, then your question." if on else "Always listening is paused.", 3)

    def _bars_tick(self):
        lis = self.listener
        mode = self.floater.mode
        now = time.time()
        if lis is None or not lis.is_alive() or not lis.ok or not self.always_listening:
            state, show = "off", False
        elif mode == "speaking" or self.speaking:
            state, show = "speaking", False
        elif mode == "thinking" or self.busy:
            state, show = "thinking", False
        elif lis.processing:
            state, show = "hearing", True
        else:
            state = "awake" if now < lis.awake_until else "listening"
            show = now < getattr(lis, "voice_until", 0.0)
        self.floater.set_bars(state, lis.level if lis is not None else 0.0, show)
        pass

    def open_mini(self):
        if self.mini is None:
            self.mini = MiniChat(self)
        self.mini.refresh()
        geo = self.floater.frameGeometry()
        x = geo.left() - self.mini.width() - 12
        if x < 10:
            x = geo.right() + 12
        y = max(10, geo.bottom() - self.mini.height())
        self.mini.move(x, y)
        self.mini.show()
        self.mini.raise_()
        self.mini.activateWindow()
        self.mini.input.setFocus()

    # ----- locker -----
    def setup_locker(self):
        while True:
            dialog = SetupDialog(self)
            if dialog.exec() != QDialog.Accepted:
                return
            try:
                self.lk.setup(dialog.code.text(), dialog.master.text(), dialog.folder.text())
            except (ValueError, FileExistsError) as error:
                QMessageBox.warning(self, "REEZ", str(error))
                continue
            self.setup_btn.hide()
            self.add("REEZ", "Locker created. Say the folder name to open it.")
            return

    def open_locker_flow(self):
        if not self.isVisible():
            self.showNormal()
        if self.lk.is_open and self.panel is not None:
            self.tabs.setCurrentWidget(self.panel)
            return
        dialog = CodeDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        word = dialog.field.text()
        dialog.field.clear()
        self.state.setText("Checking...")
        background(self.lk.unlock, self._unlocked, word)

    def _unlocked(self, value):
        self.state.setText("")
        kind, data = value
        if kind == "error":
            self.add("REEZ", "Something went wrong: " + data)
            return
        status, info = data
        if status == "open":
            self.panel = LockerPanel(self.lk, self)
            self.tabs.addTab(self.panel, "Locker")
            self.tabs.tabBar().setVisible(True)
            self.tabs.setCurrentWidget(self.panel)
            self.add("REEZ", "Locker open." + (" Master mode." if info == "master" else ""))
        elif status == "wait":
            self.add("REEZ", "Too many wrong tries. Wait " + str(info) + " seconds.")
        else:
            self.add("REEZ", "Wrong code word.")

    def _remove_panel(self):
        if self.panel is not None:
            index = self.tabs.indexOf(self.panel)
            if index >= 0:
                self.tabs.removeTab(index)
            self.panel.deleteLater()
            self.panel = None
        self.tabs.tabBar().setVisible(self.tabs.count() > 1)

    def lock_locker(self):
        self.lk.lock()
        self._remove_panel()
        self.add("REEZ", "Locker locked.")

    def check_locked(self):
        if not self.lk.is_open:
            self._remove_panel()

    def after_erase(self):
        self._remove_panel()
        self.setup_btn.setVisible(not self.lk.exists())
        self.add("REEZ", "Locker erased.")

    def _tick(self):
        if self.adjust and time.time() > self.adjust_until:
            self._end_adjust()
        if self.lk.check_idle():
            self._remove_panel()
            self.add("REEZ", "Locker auto-locked after inactivity.")
        names = tuple(str(p.relative_to(brain.DOCS_DIR)) for p in brain._all_files())
        if names != self._docs_names:
            self.refresh_docs()

    # ----- painting and closing -----
    def paintEvent(self, event):
        draw_background(self, None, self.art is None)
        if self.art is not None and self.log.isVisible():
            top_left = self.log.mapTo(self, QPoint(0, 0))
            size = self.log.size()
            if self._art_size != size:
                scaled = self.art.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = (scaled.width() - size.width()) // 2
                y = (scaled.height() - size.height()) // 2
                self._art_scaled = scaled.copy(x, y, size.width(), size.height())
                self._art_size = size
            painter = QPainter(self)
            path = QPainterPath()
            path.addRoundedRect(QRectF(top_left.x(), top_left.y(), size.width(), size.height()), 14, 14)
            painter.setClipPath(path)
            painter.drawPixmap(top_left, self._art_scaled)
            painter.fillRect(QRect(top_left, size), QColor(0, 0, 0, 120))
            painter.end()

    def closeEvent(self, event):
        try:
            saving = QApplication.instance().isSavingSession()
        except Exception:
            saving = False
        if self._quitting or saving:
            self.lk.lock()
            event.accept()
            return
        event.ignore()
        self.hide()
        if self.lk.is_open:
            self.lock_locker()


def app_icon():
    """The REEZ chalice icon (theme/reez.ico, or theme/logo.png) for windows and the taskbar."""
    base = Path(__file__).parent / "theme"
    for name in ("reez.ico", "logo.png"):
        path = base / name
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon(crest_pixmap(64))


APP_ID = "Reez.Assistant.1"


def set_app_id():
    """Make Windows treat REEZ as its own app, so the taskbar shows the REEZ icon and not Python's."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def set_taskbar_identity(window):
    """Tell Windows the icon and the command to use when REEZ is pinned to the taskbar."""
    try:
        from win32com.propsys import propsys, pscon
        base = Path(__file__).resolve().parent
        exe = Path(sys.executable)
        if exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
            exe = exe.parent / "pythonw.exe"
        store = propsys.SHGetPropertyStoreForWindow(int(window.winId()), propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
        store.SetValue(pscon.PKEY_AppUserModel_RelaunchCommand,
                       propsys.PROPVARIANTType('"' + str(exe) + '" "' + str(base / "ui.py") + '"'))
        store.SetValue(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, propsys.PROPVARIANTType("REEZ"))
        store.SetValue(pscon.PKEY_AppUserModel_RelaunchIconResource,
                       propsys.PROPVARIANTType(str(base / "theme" / "reez.ico") + ",0"))
        store.Commit()
    except Exception:
        pass


GESTURE_FILE = Path(__file__).parent / "data" / "gestures.txt"


def spoken_text(reply):
    """Lists are long to listen to, so REEZ says a short line and the full list stays on the screen."""
    lines = [l.strip() for l in reply.splitlines() if l.strip()]
    count = sum(1 for l in lines if l.startswith("\u2022"))
    if count:
        return "I found " + str(count) + " items. The full list is on the screen."
    return reply


def main():
    global bridge
    set_app_id()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge()
    window = ReezWindow()
    app.aboutToQuit.connect(window.lk.lock)
    set_taskbar_identity(window)
    if "--background" not in sys.argv:
        window.show()
        if not window.lk.exists():
            QTimer.singleShot(400, window.setup_locker)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()





