import datetime
import os
import re
import threading
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
import shutil
import sys
import traceback
import warnings

import cv2
import numpy as np
from PySide6.QtCore import (
    QItemSelection, QItemSelectionModel, QObject, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal, Slot, QUrl,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QIconEngine, QImage, QImageReader, QKeySequence, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QPixmapCache, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QSplitter,
    QPlainTextEdit, QStackedWidget, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import (
    __version__, catalog as lrcat, cull, features, looks, model, prefs, preview, project as proj, support, sync, tools,
)
from .paths import (
    IS_MAC, OLD_PLUGIN_FOLDER, PLUGIN_FOLDER, camera_raw_presets_dir, data_dir, lightroom_modules_dir,
    log_file, open_with_system, plugin_source_dir, resource_dir,
)

ACCENT = "#8b6cff"
FONT_PT = 13 if sys.platform == "darwin" else 10


def _pt(size):
    return round(size * FONT_PT / 10, 1)


STYLE = f"""
* {{ font-family: 'Segoe UI', '.AppleSystemUIFont', 'Helvetica Neue'; font-size: {FONT_PT}pt; color: #e8e8ee; }}
QMainWindow, QDialog, #Page {{ background: #0f1014; }}
#Sidebar {{ background: #090a0d; border-right: 1px solid #1e2028; }}
#Logo {{ font-size: {_pt(16.5)}pt; font-weight: 700; color: white; padding: 22px 18px 6px 18px; }}
#LogoSub {{ font-size: {_pt(8.5)}pt; color: #6e7180; padding: 0px 18px 16px 18px; font-weight: 600; letter-spacing: 0.5px; }}
#NavButton {{ text-align: left; padding: 10px 16px; border: none; border-radius: 8px; margin: 2px 10px;
              background: transparent; color: #9ea1b0; font-size: {_pt(10)}pt; font-weight: 500; }}
#NavButton:hover {{ background: #171920; color: white; }}
#NavButton:checked {{ background: #211d33; color: white; font-weight: 600; border-left: 3px solid {ACCENT}; }}
#H1 {{ font-size: {_pt(19)}pt; font-weight: 700; color: white; }}
#H2 {{ font-size: {_pt(12)}pt; font-weight: 600; color: white; }}
#SectionHeader {{ font-size: {_pt(9)}pt; font-weight: 700; color: #8b8e9e; letter-spacing: 0.8px; text-transform: uppercase; }}
#Muted {{ color: #888b99; }}
#Card {{ background: #16181f; border: 1px solid #242731; border-radius: 10px; }}
#Card:hover {{ border-color: #383c4c; }}
#InspectorCard {{ background: #14161c; border: 1px solid #22252f; border-radius: 10px; }}
#Banner {{ background: #181528; border: 1px solid #352b63; border-radius: 10px; }}
#Chip {{ background: #25203b; color: #cdc2ff; border-radius: 8px; padding: 3px 10px; font-size: {_pt(8.5)}pt; font-weight: 600; }}
#ChipDone {{ background: #132e24; color: #7ce8b5; border-radius: 8px; padding: 3px 10px; font-size: {_pt(8.5)}pt; font-weight: 600; }}
#ChipWarn {{ background: #332712; color: #fcd34d; border-radius: 8px; padding: 3px 10px; font-size: {_pt(8.5)}pt; font-weight: 600; }}
QPushButton {{ background: #1e2029; border: 1px solid #2c2f3c; border-radius: 7px; padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ background: #272a36; border-color: #3d4152; }}
QPushButton:disabled {{ color: #52545e; background: #16171d; border-color: #20222a; }}
QPushButton#Primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #9c82ff; }}
QPushButton#Primary:disabled {{ background: #312c47; color: #7c7696; }}
QPushButton#AccentOutline {{ background: #1e1a30; border: 1px solid {ACCENT}; color: #d6ccff; font-weight: 600; }}
QPushButton#AccentOutline:hover {{ background: #2a2444; color: white; }}
QPushButton#Danger {{ color: #ff8a8a; background: #21181c; border-color: #3d242b; }}
QPushButton#Danger:hover {{ background: #2e1d23; }}
QPushButton#PillToggle {{ padding: 5px 12px; border-radius: 6px; font-size: {_pt(9)}pt; }}
QPushButton#PillToggle:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; font-weight: 600; }}
QPushButton#Nudge {{ padding: 4px 8px; border-radius: 6px; font-size: {_pt(8.5)}pt; min-width: 0px; }}
#coffeeBtn {{ text-align: left; padding: 6px 16px; border: none; border-radius: 8px; margin: 0px 10px 2px 10px;
              background: transparent; color: #b9a27a; font-size: {_pt(9)}pt; }}
#coffeeBtn:hover {{ background: #1c1912; color: #f2d49b; }}
#LegalText {{ color: #9ea1b0; font-size: {_pt(8.5)}pt; }}
QPlainTextEdit#LicenseView {{ background: #101217; border: 1px solid #232630; border-radius: 8px;
    font-family: 'Cascadia Mono', 'Consolas', 'Menlo', monospace; font-size: {_pt(9)}pt; }}
#JobPanel {{ background: #15131f; border: 1px solid #352b63; border-radius: 10px; }}
#JobTitle {{ color: white; font-weight: 600; font-size: {_pt(9)}pt; }}
#QDLabel {{ color: #9ea1b0; font-size: {_pt(8.5)}pt; font-weight: 600; }}
QLineEdit, QDoubleSpinBox, QComboBox {{ background: #15171e; border: 1px solid #2b2e3b; border-radius: 7px; padding: 7px; }}
QComboBox QAbstractItemView {{ background: #16181f; selection-background-color: #2a2540; }}
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QProgressBar {{ background: #171920; border: 1px solid #252833; border-radius: 6px; height: 12px; text-align: center; font-size: {_pt(8)}pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QTableWidget, QListWidget {{ background: #13151b; border: 1px solid #232630; border-radius: 9px; gridline-color: #20222b; }}
QHeaderView::section {{ background: #181a22; border: none; padding: 6px 8px; color: #8d8f9c; font-weight: 600; }}
QListWidget::item {{ border-radius: 7px; padding: 5px; }}
QListWidget::item:selected {{ background: #282342; border: 1px solid {ACCENT}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QSlider::groove:horizontal {{ height: 4px; background: #2b2e3b; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:disabled {{ background: #555763; }}
QSlider::sub-page:horizontal:disabled {{ background: #35304d; }}
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: #181528; color: #e8e8ee; border-top: 1px solid #352b63; }}
QSplitter::handle {{ background: #1c1e26; width: 2px; height: 2px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; }}
QScrollBar::handle:vertical {{ background: #2c2f3c; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; }}
QScrollBar::handle:horizontal {{ background: #2c2f3c; border-radius: 4px; min-width: 30px; }}
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget, #InspectorInner {{ background: #14161c; }}
#EdgeToggle {{ background: #0c0d11; border: none; border-right: 1px solid #1e2028; border-radius: 0px; padding: 0px;
               color: #6e7180; font-size: {_pt(7)}pt; }}
#EdgeToggle:hover {{ background: #1a1c24; color: white; }}
QSplitter#MainSplit::handle {{ background: #15161c; border-radius: 2px; }}
QSplitter#MainSplit::handle:hover {{ background: {ACCENT}; }}
#Grid {{ background: #101116; }}
#FilmstripPanel {{ background: #101116; border: 1px solid #1e2028; border-radius: 8px; }}
#FilmInfoBar {{ background: #16181f; border: none; border-bottom: 1px solid #0b0c10; border-top-left-radius: 8px;
                border-top-right-radius: 8px; }}
#Crumb {{ color: #9ea1b0; font-size: {_pt(8.5)}pt; background: transparent; }}
QPushButton#BarBtn {{ padding: 1px 9px; border-radius: 5px; font-size: {_pt(8.5)}pt; background: #1c1e26;
                      border: 1px solid #2a2d39; }}
QPushButton#BarBtn:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; font-weight: 600; }}
#Filmstrip {{ background: #101116; border: none; border-radius: 0px; }}
#Filmstrip::item {{ padding: 2px; margin: 0px; border-radius: 4px; }}
#Filmstrip::item:selected {{ background: #282342; border: 1px solid {ACCENT}; }}
QPushButton#StepBtn, QPushButton#PillBtn, QPushButton#ScopeBtn {{ padding: 1px 8px; min-width: 0px; border-radius: 0px;
    background: #1c1e26; border: 1px solid #2c2f3c; border-left-width: 0px; font-size: {_pt(8)}pt; color: #c9cbd6; }}
QPushButton#StepBtn {{ padding: 0px; font-size: {_pt(7)}pt; min-width: 30px; max-width: 30px; min-height: 22px;
                      max-height: 22px; }}
QPushButton#ScopeBtn {{ padding: 4px 6px; }}
QPushButton#StepBtn[edge="first"], QPushButton#PillBtn[edge="first"], QPushButton#ScopeBtn[edge="first"] {{
    border-left-width: 1px; border-top-left-radius: 5px; border-bottom-left-radius: 5px; }}
QPushButton#StepBtn[edge="last"], QPushButton#PillBtn[edge="last"], QPushButton#ScopeBtn[edge="last"] {{
    border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}
QPushButton#StepBtn:hover, QPushButton#PillBtn:hover, QPushButton#ScopeBtn:hover {{ background: #2a2540; color: white; }}
QPushButton#StepBtn:disabled {{ color: #4a4c56; background: #16171d; }}
QPushButton#PillBtn:checked, QPushButton#ScopeBtn:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT};
    font-weight: 600; }}
#Accordion {{ border: none; }}
#RightPanel {{ background: #0f1014; }}
#AccSection {{ background: #14161c; }}
QPushButton#AccHeader {{ background: #22242c; border: none; border-radius: 0px; padding: 0px; text-align: left; }}
QPushButton#AccHeader:hover {{ background: #2a2c36; }}
#AccTitle {{ background: transparent; color: #e8e8ee; font-weight: 600; font-size: {_pt(9)}pt; }}
#AccArrow {{ background: transparent; color: #8b8e9e; font-size: {_pt(8)}pt; }}
#AccBody {{ background: #14161c; }}
#ExifStrip {{ background: #181a20; color: #c9cbd6; border-radius: 6px; padding: 5px 8px; font-size: {_pt(8.5)}pt;
              margin-top: 4px; }}
#QDValue {{ color: white; font-weight: 600; font-size: {_pt(8.5)}pt; }}
#SubHeader {{ color: #8b8e9e; font-weight: 700; font-size: {_pt(8)}pt; letter-spacing: 0.6px; padding-top: 6px; }}
#MetaKey {{ color: #7d8090; font-size: {_pt(8.5)}pt; }}
#MetaVal {{ color: #e8e8ee; font-size: {_pt(8.5)}pt; }}
"""


# ---------------------------------------------------------------- legal & privacy text (Settings ▸ About)

APP_TAGLINE = "Companion Workflow for Adobe® Lightroom® Classic Catalogs"
TRADEMARK_NOTICE = (
    "Adobe and Lightroom are either registered trademarks or trademarks of Adobe Inc. in the United States and/or "
    "other countries. Virten Studio is an independent product and is not affiliated with, sponsored by, or endorsed "
    "by Adobe Inc.")
PRIVACY_NOTE = (
    "Privacy: your photos, catalogs, profiles and projects stay on this computer (and in the sync folder you choose). "
    "No telemetry or analytics. Update checks send one request to GitHub (api.github.com, the latest release of this "
    "app) with no IDs, file names or hardware data: at startup and after a sync when “Check for updates automatically "
    "at startup” is on (Settings ▸ Updates), otherwise only when you click Check for updates. Buy Me a Coffee opens in "
    "your browser only when you click it.")
OPEN_SOURCE_NOTE = (
    "Virten Studio includes open-source software and AI models under their own licences: Qt for Python (LGPL-3.0, "
    "dynamically linked; you can replace its libraries), LibRaw and FFmpeg (LGPL-2.1), MediaPipe and its face and "
    "segmentation models (Apache-2.0), OpenAI CLIP ViT-B/32 (MIT), ONNX Runtime and DirectML (MIT), scikit-learn, "
    "SciPy and NumPy (BSD) and more. Their notices and full licence texts are below.")


def auto_update_check():
    """Settings ▸ Updates ▸ Check for updates automatically at startup (on by default)."""
    return prefs.load().get("auto_update_check", True) is not False


# ---------------------------------------------------------------- helpers

def label(text, name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


class ElidedLabel(QLabel):
    """One-line label that shrinks with the window instead of forcing it wider: long text is shortened with "…"
    (full text in the tooltip)."""

    def __init__(self, text="", name=None, mode=Qt.ElideRight):
        super().__init__()
        if name:
            self.setObjectName(name)
        self._full, self._mode = "", mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._refit()

    def text(self):
        return self._full

    def _refit(self):
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, max(20, self.width())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refit()

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())


def button(text, name=None, slot=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def hbox(*widgets, spacing=10):
    l = QHBoxLayout()
    l.setSpacing(spacing)
    for w in widgets:
        if w is None:
            l.addStretch(1)
        elif isinstance(w, QWidget):
            l.addWidget(w)
        else:
            l.addLayout(w)
    return l


def clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            clear_layout(it.layout())


def fmt_metric(key, mae):
    if key == "Exposure2012":
        return f"±{mae:.2f} EV"
    if key == "Temperature":
        return f"±{mae:.0f} K"
    return f"±{mae:.1f}"


MASK_SHORT = {
    "subject": "Subject", "background": "Background", "sky": "Sky",
    "skin": "Skin", "teeth": "Teeth", "gradient": "Gradient",
}


def summary_line(settings):
    parts = []
    if "Exposure2012" in settings:
        parts.append(f"{settings['Exposure2012']:+.2f} EV")
    if "Temperature" in settings:
        parts.append(f"{settings['Temperature']} K")
    if "Tint" in settings:
        parts.append(f"Tint {settings['Tint']:+d}" if isinstance(settings["Tint"], int) else f"Tint {settings['Tint']:+.0f}")
    line = " · ".join(parts)
    extras = []
    if settings.get("CropAngle"):
        extras.append(f"⟲ {settings['CropAngle']:+.1f}°")
    for g in settings.get("MaskGroupBasedCorrections") or []:
        extras.append(MASK_SHORT.get(tools.mask_kind(g), "Mask"))
    return line + ("\n" + "  ".join(extras) if extras else "")


THUMB_MATTE, THUMB_BORDER = "#101217", "#262934"


def square_thumb_pixmap(src, side):
    """A photo thumbnail on a square side x side matte: the whole picture at its true aspect ratio (portrait frames
    pillarboxed, landscape ones letterboxed; never stretched or cropped), centred, with a hairline border round the
    picture. src: an image file path or a QImage."""
    side = max(4, int(side))
    canvas = QPixmap(side, side)
    canvas.fill(QColor(THUMB_MATTE))
    if isinstance(src, QImage):
        img = src
    else:
        reader = QImageReader(src or "")
        reader.setAutoTransform(True)
        full = reader.size()
        if full.isValid() and full.width() > 0 and full.height() > 0:  # decode straight at the needed size (fast)
            k = min((side - 2) / full.width(), (side - 2) / full.height(), 1.0)
            reader.setScaledSize(QSize(max(1, round(full.width() * k)), max(1, round(full.height() * k))))
        img = reader.read()
    if img.isNull():
        return canvas
    img = img.scaled(side - 2, side - 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    x, y = (side - img.width()) // 2, (side - img.height()) // 2
    p = QPainter(canvas)
    p.drawImage(x, y, img)
    p.setPen(QPen(QColor(THUMB_BORDER), 1))
    p.drawRect(x - 1, y - 1, img.width() + 1, img.height() + 1)
    p.end()
    return canvas


_ENGINE_CLONES = []  # PySide: a cloned engine's Python object must stay alive while Qt uses it


class ThumbIconEngine(QIconEngine):
    """Icon for a photo thumbnail, drawn at whatever square size the view asks for (so the Thumb Size slider stays
    sharp at any size) and cached in QPixmapCache; the file is only read when a size isn't cached."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    def clone(self):
        e = ThumbIconEngine(self.path)
        _ENGINE_CLONES.append(e)
        return e

    def actualSize(self, size, mode, state):
        s = min(size.width(), size.height())
        return QSize(s, s)

    def pixmap(self, size, mode, state):
        s = max(4, min(size.width(), size.height()))
        key = f"vs-thumb|{s}|{self.path}"
        pm = QPixmapCache.find(key)
        if pm is None or pm.isNull():
            pm = square_thumb_pixmap(self.path, s)
            QPixmapCache.insert(key, pm)
        return pm

    def paint(self, painter, rect, mode, state):
        dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
        pm = QPixmap(self.pixmap(QSize(round(rect.width() * dpr), round(rect.height() * dpr)), mode, state))
        pm.setDevicePixelRatio(dpr)
        w, h = pm.width() / dpr, pm.height() / dpr
        painter.drawPixmap(QRectF(rect.x() + (rect.width() - w) / 2, rect.y() + (rect.height() - h) / 2, w, h),
                           pm, QRectF(pm.rect()))


def thumb_icon(path):
    """Square, aspect-correct icon for a photo thumbnail (an empty icon when the thumbnail is missing)."""
    if QPixmapCache.cacheLimit() < 65536:
        QPixmapCache.setCacheLimit(65536)  # KB: room for a screenful of large grid thumbnails
    return QIcon(ThumbIconEngine(path)) if path and os.path.exists(path) else QIcon()


def numpy_to_qpixmap(rgb_uint8):
    if rgb_uint8 is None or rgb_uint8.size == 0:
        return QPixmap()
    rgb = np.ascontiguousarray(rgb_uint8)
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def plugin_installed():
    return os.path.exists(os.path.join(lightroom_modules_dir(), PLUGIN_FOLDER, "Info.lua"))


def plugin_outdated():
    import filecmp
    src, dst = plugin_source_dir(), os.path.join(lightroom_modules_dir(), PLUGIN_FOLDER)
    if not plugin_installed() or not os.path.isdir(src):
        return False
    for fn in os.listdir(src):
        a, b = os.path.join(src, fn), os.path.join(dst, fn)
        if os.path.isfile(a) and (not os.path.exists(b) or not filecmp.cmp(a, b, shallow=False)):
            return True
    return False


def install_plugin(parent, quiet=False):
    dst = os.path.join(lightroom_modules_dir(), PLUGIN_FOLDER)
    old = os.path.join(lightroom_modules_dir(), OLD_PLUGIN_FOLDER)
    try:
        os.makedirs(lightroom_modules_dir(), exist_ok=True)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(plugin_source_dir(), dst)
        if os.path.exists(old):
            shutil.rmtree(old)
    except OSError as e:
        QMessageBox.critical(parent, "Virten Studio", f"Couldn't install the plugin:\n{e}")
        return False
    if quiet:
        return True
    QMessageBox.information(
        parent, "Virten Studio",
        "The Lightroom plugin is installed.\n\nRestart Lightroom Classic if it's open. Then use "
        "Library ▸ Plug-in Extras ▸ Apply Virten Studio Edits… to apply a project's edits.",
    )
    return True


# ---------------------------------------------------------------- worker threads

class Worker(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args, self._cancel = fn, args, False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = self.fn(
                *self.args,
                progress=lambda a, b, s: self.progress.emit(a, b, s),
                cancelled=lambda: self._cancel,
            )
            self.done.emit(result)
        except InterruptedError:
            self.failed.emit("Cancelled.")
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)


class _Relay(QObject):
    """Delivers a worker's progress / done / failed callbacks on the UI thread. Qt only queues a cross-thread signal
    to a QObject's own method: connected straight to a lambda or plain function, the callback runs in the worker
    thread, where building or changing widgets silently fails or crashes."""

    def __init__(self, on_progress, on_done, on_failed):
        super().__init__()
        app = QApplication.instance()
        if self.thread() is not app.thread():
            self.moveToThread(app.thread())
        self.cbs = (on_progress, on_done, on_failed)

    @Slot(int, int, str)
    def progress(self, a, b, s):
        if self.cbs[0]:
            self.cbs[0](a, b, s)

    @Slot(object)
    def done(self, result):
        if self.cbs[1]:
            self.cbs[1](result)

    @Slot(str)
    def failed(self, msg):
        if self.cbs[2]:
            self.cbs[2](msg)


_RUNNING = set()


def stop_workers(workers, timeout_s=30):
    for thread, worker in workers:
        worker.cancel()
        for sig in (worker.progress, worker.done, worker.failed):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout_s)
    for thread, _ in workers:
        while thread.isRunning() and datetime.datetime.now() < deadline:
            thread.wait(100)
            QApplication.processEvents()


def start_worker(owner, fn, *args, on_progress=None, on_done=None, on_failed=None):
    thread, worker = QThread(QApplication.instance()), Worker(fn, *args)
    pair = (thread, worker)
    _RUNNING.add(pair)
    thread.finished.connect(lambda: _RUNNING.discard(pair))
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.relay = relay = _Relay(on_progress, on_done, on_failed)  # callbacks always run on the UI thread
    if on_progress:
        worker.progress.connect(relay.progress)
    worker.done.connect(relay.done)
    worker.failed.connect(relay.failed)
    worker.done.connect(thread.quit)
    worker.failed.connect(thread.quit)
    owner._workers = getattr(owner, "_workers", []) + [(thread, worker)]
    thread.start()
    return worker


def _plain(fn):
    def wrapped(*args, progress=None, cancelled=None):
        return fn(*args)
    return wrapped


# ---------------------------------------------------------------- custom pro UI widgets

class StrengthSlider(QWidget):
    def __init__(self, value=100, maximum=200):
        super().__init__()
        l = QHBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, maximum)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setValue(value)
        self.readout = QLabel()
        self.readout.setMinimumWidth(44)
        self.slider.valueChanged.connect(lambda v: self.readout.setText(f"{v}%"))
        self.readout.setText(f"{value}%")
        l.addWidget(self.slider, 1)
        l.addWidget(self.readout)

    def value(self):
        return self.slider.value()


class ProgressPanel(QWidget):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        self.status = label("", "Muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        l.addWidget(self.status)
        l.addWidget(self.bar)

    def update(self, a, b, text):
        self.bar.setRange(0, max(b, 1))
        self.bar.setValue(a)
        self.status.setText(f"{text}…  {a} / {b}" if b > 1 else text)


class HistogramWidget(QWidget):
    """Lightroom-style translucent RGB + Luminance histogram display."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(84)
        self.hists = None

    def set_image(self, rgb_uint8):
        self.hists = preview.compute_histogram(rgb_uint8, bins=64) if rgb_uint8 is not None else None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor("#232632"), 1))
        p.setBrush(QColor("#101217"))
        p.drawRoundedRect(rect, 7, 7)

        p.setPen(QPen(QColor("#1c1f29"), 1))
        for frac in (0.25, 0.5, 0.75):
            x = rect.left() + int(rect.width() * frac)
            p.drawLine(x, rect.top() + 2, x, rect.bottom() - 2)

        if not self.hists:
            p.setPen(QColor("#555866"))
            p.drawText(rect, Qt.AlignCenter, "Histogram")
            return

        w, h = rect.width() - 8, rect.height() - 10
        ox, oy = rect.left() + 4, rect.bottom() - 4
        colors = [
            (self.hists[0], QColor(248, 113, 113, 110), QColor(248, 113, 113, 200)),
            (self.hists[1], QColor(52, 211, 153, 100), QColor(52, 211, 153, 190)),
            (self.hists[2], QColor(96, 165, 250, 110), QColor(96, 165, 250, 200)),
            (self.hists[3], QColor(225, 228, 240, 65), QColor(225, 228, 240, 160)),
        ]
        for arr, fill_col, stroke_col in colors:
            n = len(arr)
            if n < 2:
                continue
            path = QPainterPath()
            path.moveTo(ox, oy)
            for i, v in enumerate(arr):
                px = ox + (i / (n - 1)) * w
                py = oy - float(np.clip(v, 0.0, 1.0)) * h
                path.lineTo(px, py)
            path.lineTo(ox + w, oy)
            path.closeSubpath()
            p.fillPath(path, fill_col)
            p.setPen(QPen(stroke_col, 1.2))
            p.drawPath(path)


_PREVIEW_CACHE = OrderedDict()  # raw path -> 960 px embedded preview (RGB), most recently used last
_PREVIEW_CACHE_SIZE = 16
_PREVIEW_LOCK = threading.Lock()
_PREVIEW_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")


def _cached_preview(path):
    """(rgb, ai_masks) for a recently viewed photo, or None."""
    with _PREVIEW_LOCK:
        hit = _PREVIEW_CACHE.get(path)
        if hit is not None:
            _PREVIEW_CACHE.move_to_end(path)
        return hit


def _decode_preview(path):
    """Background thread: the 960 px embedded preview and its simulated AI masks (computed once per photo, so slider
    and nudge changes never re-run segmentation)."""
    rgb = features.load_preview(path, max_side=960)[0]
    try:
        masks = preview.compute_ai_masks(rgb)
    except Exception as e:  # segmentation unavailable: preview without AI-mask corrections
        print("AI mask preview failed", path, e)
        masks = None
    with _PREVIEW_LOCK:
        _PREVIEW_CACHE[path] = (rgb, masks)
        _PREVIEW_CACHE.move_to_end(path)
        while len(_PREVIEW_CACHE) > _PREVIEW_CACHE_SIZE:
            _PREVIEW_CACHE.popitem(last=False)
    return rgb, masks


_FACE_CACHE = OrderedDict()  # raw path -> faces.extract_face_crops() result
_FACE_CACHE_SIZE = 16
_FACE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="faces")


def _cached_faces(path):
    with _PREVIEW_LOCK:
        hit = _FACE_CACHE.get(path)
        if hit is not None:
            _FACE_CACHE.move_to_end(path)
        return hit


def _extract_faces(path):
    from . import faces as facemod
    crops = facemod.extract_face_crops(path)
    with _PREVIEW_LOCK:
        _FACE_CACHE[path] = crops
        while len(_FACE_CACHE) > _FACE_CACHE_SIZE:
            _FACE_CACHE.popitem(last=False)
    return crops


class BeforeAfterView(QWidget):
    """Interactive split-screen Before/After photo loupe with draggable divider.

    Selecting a photo shows its cached 360 px thumbnail at once; the camera's 960 px embedded preview is decoded on a
    background thread (the 16 most recent are kept in memory) and swapped in if that photo is still selected."""

    photo_ready = Signal()  # the displayed image changed (thumbnail or full preview): refresh the histogram
    _loaded = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._current = None
        self._settings = {}
        self.full_res = False
        self.ai_masks = None
        self.show_overlay = False
        self._overlay = None  # (key, QImage) cache of the ruby overlay
        self._loaded.connect(self._on_loaded)
        self.setMinimumSize(320, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.before_rgb = None
        self.after_rgb = None
        self.before_pix = QPixmap()
        self.after_pix = QPixmap()
        self.split_pos = 0.5
        self.mode = "split"
        self._dragging = False
        self.setCursor(Qt.SplitHCursor)

    def set_mode(self, mode):
        self.mode = mode
        self.setCursor(Qt.SplitHCursor if mode == "split" else Qt.ArrowCursor)
        self.update()

    def set_overlay(self, on):
        self.show_overlay = bool(on)
        self.update()

    def overlay_kinds(self):
        """The AI masks the ruby overlay shows: those used by this photo's corrections, else the subject."""
        kinds = preview.active_ai_kinds(self._settings)
        return kinds or ["subject"]

    def _overlay_image(self):
        if not self.ai_masks or self.before_rgb is None:
            return None
        kinds = [k for k in self.overlay_kinds() if k in self.ai_masks]
        if not kinds:
            return None
        key = (id(self.ai_masks), tuple(kinds))
        if self._overlay is None or self._overlay[0] != key:
            union = np.maximum.reduce([self.ai_masks[k] for k in kinds])
            h, w = union.shape
            rgba = np.empty((h, w, 4), np.uint8)
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = 0xFF, 0x3B, 0x5C  # ruby #ff3b5c
            rgba[..., 3] = np.clip(union * (0.45 * 255), 0, 255).astype(np.uint8)
            img = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
            self._overlay = (key, img)
        return self._overlay[1]

    def load_photo(self, raw_path, thumb_path, settings):
        self._current = raw_path
        self._settings = settings or {}
        hit = _cached_preview(raw_path) if raw_path else None
        rgb, masks = hit if hit is not None else (None, None)
        self.full_res = rgb is not None
        if rgb is None and thumb_path and os.path.exists(thumb_path):
            bgr = cv2.imread(thumb_path, cv2.IMREAD_COLOR)  # ~1 ms: show something right away
            if bgr is not None:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self._show(rgb, masks)
        if not self.full_res and raw_path and os.path.exists(raw_path):
            fut = _PREVIEW_POOL.submit(_decode_preview, raw_path)
            fut.add_done_callback(lambda f, p=raw_path: self._deliver(p, f))

    def _deliver(self, path, fut):
        """Runs on the decoding thread: hand the result to the UI thread (queued signal)."""
        try:
            rgb = fut.result()
        except Exception as e:  # unreadable RAW: keep the thumbnail
            print("preview decode failed", path, e)
            return
        try:
            self._loaded.emit(path, rgb)
        except RuntimeError:  # the view was deleted meanwhile
            pass

    def _on_loaded(self, path, data):
        if path == self._current and not self.full_res:
            self.full_res = True
            self._show(*data)

    def _show(self, rgb, masks=None):
        self.ai_masks = masks
        self._overlay = None
        self.before_rgb = rgb
        self.before_pix = numpy_to_qpixmap(rgb) if rgb is not None else QPixmap()
        self.update_settings(self._settings)
        self.photo_ready.emit()

    def update_settings(self, settings):
        self._settings = settings or {}
        if self.before_rgb is not None:
            masks = self.ai_masks if self.ai_masks and next(iter(self.ai_masks.values())).shape == \
                self.before_rgb.shape[:2] else None
            self.after_rgb = preview.render_preview(self.before_rgb, settings or {}, ai_masks=masks)
            self.after_pix = numpy_to_qpixmap(self.after_rgb)
        else:
            self.after_rgb = None
            self.after_pix = QPixmap()
        self.update()

    def mousePressEvent(self, e):
        if self.mode == "split" and e.button() == Qt.LeftButton:
            self._dragging = True
            self._update_split(e.position().x())

    def mouseMoveEvent(self, e):
        if self._dragging and self.mode == "split":
            self._update_split(e.position().x())

    def mouseReleaseEvent(self, _):
        self._dragging = False

    def _update_split(self, x):
        rect = self._image_rect()
        if rect.width() > 10:
            self.split_pos = float(np.clip((x - rect.left()) / rect.width(), 0.02, 0.98))
            self.update()

    def _image_rect(self):
        r = self.rect().adjusted(10, 10, -10, -10)
        if self.before_pix.isNull():
            return QRectF(r)
        pw, ph = self.before_pix.width(), self.before_pix.height()
        if pw <= 0 or ph <= 0:
            return QRectF(r)
        scale = min(r.width() / pw, r.height() / ph)
        w, h = int(pw * scale), int(ph * scale)
        x = r.left() + (r.width() - w) // 2
        y = r.top() + (r.height() - h) // 2
        return QRectF(x, y, w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        outer = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor("#222530"), 1))
        p.setBrush(QColor("#0b0c10"))
        p.drawRoundedRect(outer, 10, 10)

        if self.before_pix.isNull():
            p.setPen(QColor("#686b7a"))
            p.drawText(outer, Qt.AlignCenter, "Select a photo to preview Before / After edits")
            return

        img_rect = self._image_rect()
        if self.mode == "before":
            p.drawPixmap(img_rect.toRect(), self.before_pix)
            self._draw_badge(p, img_rect.left() + 12, img_rect.top() + 12, "BEFORE (AS SHOT)", "#222530")
        elif self.mode == "after" or self.after_pix.isNull():
            p.drawPixmap(img_rect.toRect(), self.after_pix if not self.after_pix.isNull() else self.before_pix)
            self._draw_badge(p, img_rect.right() - 132, img_rect.top() + 12, "VIRTEN STUDIO", ACCENT)
        else:
            split_x = img_rect.left() + img_rect.width() * self.split_pos
            p.save()
            p.setClipRect(QRectF(img_rect.left(), img_rect.top(), split_x - img_rect.left(), img_rect.height()))
            p.drawPixmap(img_rect.toRect(), self.before_pix)
            p.restore()

            p.save()
            p.setClipRect(QRectF(split_x, img_rect.top(), img_rect.right() - split_x, img_rect.height()))
            p.drawPixmap(img_rect.toRect(), self.after_pix)
            p.restore()

            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
            p.drawLine(QPointF(split_x, img_rect.top()), QPointF(split_x, img_rect.bottom()))
            cy = img_rect.center().y()
            p.setBrush(QColor("#181528"))
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawEllipse(QPointF(split_x, cy), 14, 14)
            p.setPen(QColor("white"))
            p.drawText(QRectF(split_x - 14, cy - 14, 28, 28), Qt.AlignCenter, "↔")

            if split_x - img_rect.left() > 95:
                self._draw_badge(p, img_rect.left() + 10, img_rect.top() + 10, "BEFORE", "#20232d")
            if img_rect.right() - split_x > 110:
                self._draw_badge(p, img_rect.right() - 96, img_rect.top() + 10, "EDITED", ACCENT)
        if self.show_overlay:
            ov = self._overlay_image()
            if ov is not None:
                p.drawImage(img_rect, ov)
                self._draw_badge(p, img_rect.left() + 10, img_rect.bottom() - 32,
                                 "MASK: " + " + ".join(k.upper() for k in self.overlay_kinds()), "#5a1628")
            else:
                self._draw_badge(p, img_rect.left() + 10, img_rect.bottom() - 32, "MASKS LOADING…", "#5a1628")

    def _draw_badge(self, p, x, y, text, bg_hex):
        f = p.font()
        f.setPointSizeF(_pt(8))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        h = 22
        r = QRectF(x, y, w, h)
        p.setPen(Qt.NoPen)
        c = QColor(bg_hex)
        c.setAlpha(215)
        p.setBrush(c)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignCenter, text)


_LOOK_THUMB = (160, 106)
_LOOK_PIXMAPS = {}


def _look_sample():
    """160x106 sample for Look previews: a cached photo thumbnail if there is one, else a synthetic scene
    (blue sky, green field, a warm skin-tone face, a white dress) so every colour a Look touches is visible."""
    if "_sample" in _LOOK_PIXMAPS:
        return _LOOK_PIXMAPS["_sample"]
    w, h = _LOOK_THUMB
    img = None
    d = os.path.join(features.cache_dir(), "thumbs")
    names = sorted(f for f in os.listdir(d) if f.lower().endswith(".jpg")) if os.path.isdir(d) else []
    for fn in names[:20]:
        bgr = cv2.imread(os.path.join(d, fn), cv2.IMREAD_COLOR)
        if bgr is None or bgr.shape[1] < bgr.shape[0]:  # prefer a landscape-format photo
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        s = max(w / rgb.shape[1], h / rgb.shape[0])
        rgb = cv2.resize(rgb, (max(w, round(rgb.shape[1] * s)), max(h, round(rgb.shape[0] * s))),
                         interpolation=cv2.INTER_AREA)
        y0, x0 = (rgb.shape[0] - h) // 2, (rgb.shape[1] - w) // 2
        img = np.ascontiguousarray(rgb[y0:y0 + h, x0:x0 + w])
        break
    if img is None:
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        sky = np.array([110, 160, 220], np.float32) * (1 - yy) + np.array([200, 220, 235], np.float32) * yy
        img = np.repeat(sky, w, axis=1)
        img[int(h * 0.62):] = np.array([70, 120, 60], np.float32)
        cv2.ellipse(img, (int(w * 0.38), int(h * 0.42)), (14, 18), 0, 0, 360, (225, 175, 145), -1)
        cv2.rectangle(img, (int(w * 0.30), int(h * 0.55)), (int(w * 0.46), h), (240, 238, 232), -1)
        img = np.clip(img, 0, 255).astype(np.uint8)
    _LOOK_PIXMAPS["_sample"] = img
    return img


def look_preview_pixmap(look):
    """Small rendered preview of a Look (None = profile only) on the sample photo; cached per Look."""
    key = (look or {}).get("name") or "_none"
    if key not in _LOOK_PIXMAPS:
        base = {"Exposure2012": 0.0, "Temperature": 5400, "Tint": 6}
        s = looks.apply_look(base, look, 1.0) if look else base
        _LOOK_PIXMAPS[key] = numpy_to_qpixmap(preview.render_preview(_look_sample(), s))
    return _LOOK_PIXMAPS[key]


class SliderBarWidget(QWidget):
    """Visual bi-directional Lightroom-style slider bar for the Develop Inspector."""

    def __init__(self, name, val_text, norm_val, is_temp=False):
        super().__init__()
        self.name = name
        self.val_text = val_text
        self.norm_val = float(np.clip(norm_val, -1.0, 1.0))
        self.is_temp = is_temp
        self.setFixedHeight(24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        label_w = int(min(132, max(96, w * 0.4)))
        val_w = 64
        track_x = label_w + 6
        track_w = max(40, w - label_w - val_w - 12)
        track_y = h // 2 - 2

        p.setPen(QColor("#b8bac7"))
        p.drawText(QRectF(0, 0, label_w, h), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.name, Qt.ElideRight, label_w))

        p.setPen(QColor("white"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(w - val_w, 0, val_w, h), Qt.AlignVCenter | Qt.AlignRight, self.val_text)

        track_rect = QRectF(track_x, track_y, track_w, 5)
        if self.is_temp:
            grad = QLinearGradient(track_rect.left(), 0, track_rect.right(), 0)
            grad.setColorAt(0.0, QColor("#3b82f6"))
            grad.setColorAt(0.5, QColor("#323644"))
            grad.setColorAt(1.0, QColor("#f59e0b"))
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(track_rect, 2.5, 2.5)
            pos_x = track_x + float(np.clip((self.norm_val + 1.0) / 2.0, 0.0, 1.0)) * track_w
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(pos_x, track_y + 2.5), 4.5, 4.5)
        else:
            p.setBrush(QColor("#252834"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(track_rect, 2.5, 2.5)
            mid_x = track_x + track_w / 2.0
            fill_w = self.norm_val * (track_w / 2.0)
            if abs(fill_w) > 1.0:
                fill_rect = QRectF(min(mid_x, mid_x + fill_w), track_y, abs(fill_w), 5)
                p.setBrush(QColor(ACCENT if fill_w > 0 else "#60a5fa"))
                p.drawRoundedRect(fill_rect, 2.5, 2.5)
            p.setPen(QPen(QColor("#525668"), 1))
            p.drawLine(QPointF(mid_x, track_y - 2), QPointF(mid_x, track_y + 7))


class DevelopInspector(QWidget):
    """Lightroom-inspired right-hand Develop Inspector showing visual slider bars and AI mask pills."""

    def __init__(self, scroll=True):
        super().__init__()
        self.setObjectName("InspectorCard" if scroll else "InspectorInner")
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        self.inner = QWidget()
        self.inner.setObjectName("InspectorInner")  # deep dark, never the system's light grey
        self.body = QVBoxLayout(self.inner)
        self.body.setContentsMargins(2, 2, 6, 2)
        self.body.setSpacing(4)
        if scroll:
            outer.setContentsMargins(12, 12, 12, 12)
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(self.inner)
            outer.addWidget(self.scroll, 1)
        else:  # inside the right-hand accordion, which scrolls
            outer.setContentsMargins(0, 0, 0, 0)
            self.scroll = None
            outer.addWidget(self.inner)

    def _add_section(self, title):
        if self.body.count() > 0:
            self.body.addSpacing(6)
        self.body.addWidget(label(title, "SectionHeader"))

    def show_develop(self, settings):
        clear_layout(self.body)
        if not settings:
            self.body.addWidget(label("No develop adjustments on this photo.", "Muted"))
            self.body.addStretch(1)
            return

        if "Temperature" in settings or "Tint" in settings:
            self._add_section("White Balance")
            if "Temperature" in settings:
                t = float(settings["Temperature"])
                norm = np.clip((t - 5400.0) / 3000.0, -1.0, 1.0)
                self.body.addWidget(SliderBarWidget("Temperature", f"{int(round(t))} K", norm, is_temp=True))
            if "Tint" in settings:
                ti = float(settings["Tint"])
                self.body.addWidget(SliderBarWidget("Tint", f"{int(round(ti)):+d}", ti / 100.0))

        tone_keys = [k for k in model.GROUPS["tone"]["keys"] if k in settings]
        if tone_keys:
            self._add_section("Light & Tone")
            for k in tone_keys:
                v = float(settings[k])
                if k == "Exposure2012":
                    self.body.addWidget(SliderBarWidget("Exposure", f"{v:+.2f} EV", v / 2.5))
                else:
                    self.body.addWidget(SliderBarWidget(model.display_name(k), f"{int(round(v)):+d}", v / 100.0))

        pres_keys = [k for k in model.GROUPS["presence"]["keys"] if k in settings]
        if pres_keys:
            self._add_section("Presence")
            for k in pres_keys:
                v = float(settings[k])
                self.body.addWidget(SliderBarWidget(model.display_name(k), f"{int(round(v)):+d}", v / 100.0))

        masks = settings.get("MaskGroupBasedCorrections") or []
        if settings.get("CropAngle") or masks:
            self._add_section("AI Masks & Geometry")
            if settings.get("CropAngle"):
                ang = float(settings["CropAngle"])
                self.body.addWidget(SliderBarWidget("Straighten", f"{ang:+.2f}°", ang / 4.0))
            for g in masks:
                kind = MASK_SHORT.get(tools.mask_kind(g), "Mask")
                vals = [
                    f"{k.replace('Local', '').replace('2012', '')} {v * 100:+.0f}"
                    for k, v in g.items()
                    if k.startswith("Local") and k != "LocalCurveRefineSaturation" and isinstance(v, (int, float)) and abs(v) > 1e-3
                ]
                pill = QFrame()
                pill.setObjectName("Card")
                pl = QVBoxLayout(pill)
                pl.setContentsMargins(10, 6, 10, 6)
                pl.setSpacing(2)
                pl.addLayout(hbox(label(f"● {kind} Mask", "H2"), None))
                pl.addWidget(label(", ".join(vals) if vals else "Active selection", "Muted", wrap=True))
                self.body.addWidget(pill)

        extra_keys = [
            k for k in model.GROUPS["color"]["keys"] + model.GROUPS["curve"]["keys"] + model.GROUPS["detail"]["keys"]
            if k in settings and not isinstance(settings[k], list) and settings[k] != 0
        ]
        if any(k in settings for k in looks.CURVE_KEYS) or extra_keys:
            self._add_section("Tone Curve, Color & Effects")
            if any(k in settings for k in looks.CURVE_KEYS):
                self.body.addWidget(label("Custom Point Tone Curve applied", "Chip"))
            for k in extra_keys[:40]:
                v = settings[k]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    self.body.addWidget(SliderBarWidget(model.display_name(k), str(v), float(v) / 100.0))
                else:
                    self.body.addLayout(hbox(label(model.display_name(k), "Muted"), None, label(str(v))))

        self.body.addStretch(1)

    def show_cull(self, r):
        clear_layout(self.body)
        self._add_section("Assisted Cull Analysis")
        if r.get("timelapse"):
            self.body.addWidget(label("⏱ Timelapse Sequence Frame", "Chip"))
        for k in r.get("reasons") or []:
            self.body.addWidget(label(f"✗ Likely Reject: {cull.REASONS[k]}", "ChipWarn"))
        if r.get("best"):
            self.body.addWidget(label(f"◆ Likely Best Frame of Burst #{r.get('group')}", "ChipDone"))
        elif r.get("group"):
            self.body.addWidget(label(f"Burst #{r['group']} ({r['burst_size']} frames)", "Chip"))
        if r.get("score") is not None:
            self.body.addWidget(SliderBarWidget("Keeper Score", f"{r['score']:.2f}", (r["score"] - 0.5) * 2.0))
        if r.get("capture"):
            self.body.addLayout(hbox(label("Captured", "Muted"), None, label(r["capture"][:19].replace("T", " "))))
        kws = cull.keywords_for(r)
        if kws:
            self._add_section("Lightroom Keywords to Add")
            for k in kws:
                self.body.addWidget(label(f"{cull.KW_ROOT} ▸ {k.replace('|', ' ▸ ')}", "Muted", wrap=True))
        self.body.addStretch(1)


# ---------------------------------------------------------------- Interactive "Learn from My Tweaks" Dialog

class LearnTweaksDialog(QDialog):
    """Scans the project's Lightroom catalog for user tweaks after Virten Studio's edit,
    displays a full summary of what the user changed, and lets them configure how to train."""

    def __init__(self, parent, project):
        super().__init__(parent)
        self.project = project
        self.report = None
        self.chosen_config = None
        self.setWindowTitle(f"Learn from Lightroom Tweaks — {project['name']}")
        self.resize(820, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(14)

        root.addWidget(label("Learn from Your Lightroom Tweaks", "H1"))
        self.sub = label(
            "Scanning the Lightroom catalog to compare your current edits against Virten Studio's predictions…",
            "Muted", wrap=True,
        )
        root.addWidget(self.sub)

        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(12)
        root.addLayout(self.stats_row)

        self.avg_card = QFrame()
        self.avg_card.setObjectName("Card")
        self.avg_layout = QVBoxLayout(self.avg_card)
        self.avg_layout.setContentsMargins(16, 12, 16, 12)
        self.avg_card.hide()
        root.addWidget(self.avg_card)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Tweaked Photo", "Latest LR Step", "Your Tweaks vs. Virten Studio"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        opts = QFrame()
        opts.setObjectName("Card")
        ol = QVBoxLayout(opts)
        ol.setContentsMargins(16, 14, 16, 14)
        ol.setSpacing(10)

        ol.addWidget(label("Training Options", "H2"))

        metas = model.list_profiles()
        self.profile_combo = QComboBox()
        for m in metas:
            self.profile_combo.addItem(f"{m['name']} ({m['n_photos']:,} photos)", m)
        # Exact name match: "My Style" must not pick "My Style (all D: shoots)", which sorts first.
        idx = next((i for i, m in enumerate(metas) if m["name"] == project.get("profile")), 0)
        self.profile_combo.setCurrentIndex(idx)
        ol.addLayout(hbox(label("Target profile to update:"), self.profile_combo, None))

        self.mode_tweaks_only = QRadioButton(
            "Learn from my tweaked photos only (plus this profile's existing base catalogs)"
        )
        self.mode_include_approved = QRadioButton(
            "Learn from both my tweaked photos AND the untouched photos I approved in this shoot"
        )
        self.mode_tweaks_only.setChecked(True)
        ol.addWidget(self.mode_tweaks_only)
        ol.addWidget(self.mode_include_approved)

        self.boost_combo = QComboBox()
        self.boost_combo.addItem("2× Standard emphasis (balanced refinement)", 2.0)
        self.boost_combo.addItem("4× Strong emphasis (adapt faster to these tweaks)", 4.0)
        self.boost_combo.addItem("8× Aggressive emphasis (heavily weight these corrections)", 8.0)
        self.boost_combo.setCurrentIndex(1)
        ol.addLayout(hbox(label("Tweak emphasis weight:"), self.boost_combo, None))

        self.strip_look_cb = QCheckBox(
            f"Subtract Look (“{project.get('look')}”) offsets so my base profile stays clean"
            if project.get("look")
            else "Subtract Look offsets (no Look was used on this project)"
        )
        self.strip_look_cb.setChecked(bool(project.get("look")))
        self.strip_look_cb.setVisible(bool(project.get("look")))
        ol.addWidget(self.strip_look_cb)

        root.addWidget(opts)

        self.train_btn = button("Continue to Train Profile →", "Primary", self.accept_config)
        self.train_btn.setEnabled(False)
        root.addLayout(hbox(button("Cancel", slot=self.reject), None, self.train_btn))

        start_worker(self, _plain(proj.analyze_project_tweaks), project, on_done=self.loaded, on_failed=self.failed)

    def done(self, result):
        running = [(t, w) for t, w in getattr(self, "_workers", []) if t.isRunning()]
        if running:  # closed while the catalog scan is still running: stop it cleanly first
            stop_workers(running)
        super().done(result)

    def _stat_pill(self, title, value, chip_style="Chip"):
        c = QFrame()
        c.setObjectName("Card")
        l = QVBoxLayout(c)
        l.setContentsMargins(14, 10, 14, 10)
        l.setSpacing(2)
        l.addWidget(label(title, "Muted"))
        l.addWidget(label(str(value), chip_style))
        return c

    def loaded(self, rep):
        self.report = rep
        tw = rep["tweaked_count"]
        ap = rep["approved_count"]
        un = rep["unapplied_count"]

        self.sub.setText(
            f"Scanned {rep['total_project_photos']:,} project photos in “{os.path.basename(self.project['catalog'])}”."
        )
        self.stats_row.addWidget(self._stat_pill("Tweaked in Lightroom", f"{tw:,} photos", "ChipWarn" if tw else "Chip"))
        self.stats_row.addWidget(self._stat_pill("Approved As-Is (Untouched)", f"{ap:,} photos", "ChipDone"))
        if un:
            self.stats_row.addWidget(self._stat_pill("Unedited in Catalog", f"{un:,} photos", "Chip"))

        avg = rep.get("avg_deltas") or {}
        if avg:
            self.avg_card.show()
            self.avg_layout.addWidget(label("Your Average Direction of Tweaks on This Shoot", "SectionHeader"))
            parts = []
            for k, d in avg.items():
                unit = " EV" if k == "Exposure2012" else (" K" if k == "Temperature" else "")
                sign = "+" if d["mean"] > 0 else ""
                parts.append(f"<b>{d['label']}</b>: {sign}{d['mean']}{unit} <i>({d['count']} photos)</i>")
            summary_lbl = label("   ·   ".join(parts), wrap=True)
            summary_lbl.setTextFormat(Qt.RichText)
            self.avg_layout.addWidget(summary_lbl)

        tweaked_list = rep.get("tweaked_photos") or []
        self.table.setRowCount(len(tweaked_list))
        for r, item in enumerate(tweaked_list):
            self.table.setItem(r, 0, QTableWidgetItem(item["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(item.get("last_step") or "Tweaked"))
            d_strs = []
            for k, dv in item["deltas"].items():
                unit = " EV" if k == "Exposure2012" else (" K" if k == "Temperature" else "")
                d_strs.append(f"{model.display_name(k)} {dv:+}{unit}")
            self.table.setItem(r, 2, QTableWidgetItem("  ·  ".join(d_strs)))

        if tw == 0 and ap == 0:
            self.sub.setText(
                "No applied edits or tweaks were found in the Lightroom catalog yet. Apply the project's edits in "
                "Lightroom Classic first, make any tweaks you want, and then come back here."
            )
        else:
            self.train_btn.setEnabled(self.profile_combo.count() > 0)
            if tw == 0:
                self.mode_include_approved.setChecked(True)
                self.mode_tweaks_only.setEnabled(False)

    def failed(self, msg):
        self.sub.setText(f"Couldn't scan catalog tweaks: {msg}")

    def accept_config(self):
        meta = self.profile_combo.currentData()
        if not meta:
            return
        cat = os.path.normpath(self.project["catalog"])
        self.chosen_config = {
            "meta": meta,
            "catalog": cat,
            "tweak_boost": float(self.boost_combo.currentData()),
            "only_tweaked_catalogs": {cat} if self.mode_tweaks_only.isChecked() else set(),
            "include_approved_catalogs": {cat} if self.mode_include_approved.isChecked() else set(),
            "strip_look_catalogs": (
                {cat: (self.project.get("look"), self.project.get("look_strength", 1.0))}
                if self.strip_look_cb.isChecked() and self.project.get("look")
                else {}
            ),
        }
        self.accept()


# ---------------------------------------------------------------- wizards

class Wizard(QDialog):
    def __init__(self, parent, title, steps):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 660)
        self.steps = steps
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)
        root.addWidget(label(title, "H1"))
        self.crumbs = QHBoxLayout()
        self.crumb_labels = []
        for i, s in enumerate(steps):
            c = label(f"{i + 1}  {s}")
            self.crumb_labels.append(c)
            self.crumbs.addWidget(c)
            if i < len(steps) - 1:
                self.crumbs.addWidget(label("›", "Muted"))
        self.crumbs.addStretch(1)
        root.addLayout(self.crumbs)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.back_btn = button("Back", slot=self.back)
        self.next_btn = button("Next", "Primary", slot=self.next)
        self.cancel_btn = button("Cancel", slot=self.reject)
        self.bg_btn = button("Run in Background", slot=self.run_in_background)
        self.bg_btn.setToolTip("Close this window and run it in the background (see the sidebar). You can keep "
                               "working and queue more catalogs.")
        self.bg_btn.hide()
        root.addLayout(hbox(self.cancel_btn, None, self.back_btn, self.bg_btn, self.next_btn))

    def _main_window(self):
        """The app window this wizard was opened from (None when there isn't one, e.g. in tests)."""
        w = self.parentWidget()
        while w is not None and not isinstance(w, MainWindow):
            w = w.parentWidget()
        return w

    def _update_bg(self, launch_step):
        show = bool(launch_step and self._main_window() is not None)
        self.bg_btn.setVisible(show)
        self.bg_btn.setEnabled(show and self.next_btn.isEnabled())

    def run_in_background(self):
        pass

    def add_page(self, w):
        self.stack.addWidget(w)

    def done(self, result):
        running = [(t, w) for t, w in getattr(self, "_workers", []) if t.isRunning()]
        if running:
            self.setEnabled(False)
            self.setCursor(Qt.WaitCursor)
            stop_workers(running)
        super().done(result)

    def go(self, i):
        self.stack.setCurrentIndex(i)
        for j, c in enumerate(self.crumb_labels):
            c.setStyleSheet(f"color: {'white; font-weight:600' if j == i else '#6d6f7a'};")
        self.back_btn.setVisible(0 < i < len(self.steps) - 1)
        self.refresh()

    def back(self):
        self.go(self.stack.currentIndex() - 1)

    def next(self):
        self.go(self.stack.currentIndex() + 1)

    def refresh(self):
        pass


class NewProfileWizard(Wizard):
    COL_CHECK, COL_MAIN, COL_NAME, COL_PHOTOS, COL_PATH = range(5)

    def __init__(self, parent, update_name=None, catalogs=(), new_catalogs=(), catalog_weights=None,
                 tweak_boost=2.0, only_tweaked_catalogs=None, include_approved_catalogs=None, strip_look_catalogs=None):
        self.update_name = update_name
        self.supporting = {os.path.normpath(c) for c, w in (catalog_weights or {}).items() if w < 1}
        self.tweak_boost = tweak_boost
        self.only_tweaked_catalogs = only_tweaked_catalogs or set()
        self.include_approved_catalogs = include_approved_catalogs or set()
        self.strip_look_catalogs = strip_look_catalogs or {}
        super().__init__(
            parent,
            f"Update “{update_name}”" if update_name else "Create a Personal AI Profile",
            ["Choose catalogs", "Train"],
        )
        self.counts = {}
        self.keep_checked = set()

        p1 = QWidget()
        l = QVBoxLayout(p1)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        l.addWidget(label("Profile name", "H2"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Weddings – Warm & Bright")
        self.name.textChanged.connect(self.refresh)
        l.addWidget(self.name)
        l.addWidget(label("Learn from these Lightroom catalogs", "H2"))
        self.intro = label(
            "Virten Studio learns from RAW photos you've already edited in color. Keep Main style checked for shoots "
            "edited exactly the way you want; uncheck it for supporting examples (they count 1/3 as much).",
            "Muted", wrap=True,
        )
        l.addWidget(self.intro)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Main style", "Catalog", "Edited photos", "Location"])
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_CHECK, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_MAIN, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_PHOTOS, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_PATH, QHeaderView.Stretch)
        self.table.itemChanged.connect(lambda *_: self.refresh())
        l.addWidget(self.table, 1)
        self.learn_from = QComboBox()
        self.learn_from.addItem("Your final edits (recommended)", None)
        l.addLayout(hbox(label("Learn from"), self.learn_from, None))
        self.total = label("", "Muted")
        self.scan_status = label("", "Muted")
        l.addLayout(hbox(
            button("Add catalog…", slot=self.add_catalog),
            button("Scan a drive or folder…", slot=self.scan),
            self.scan_status, None, self.total,
        ))
        self.add_page(p1)

        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 30, 0, 0)
        l2.setSpacing(14)
        self.train_title = label("Training your profile", "H2")
        l2.addWidget(self.train_title)
        l2.addWidget(label(
            "The first run analyzes every photo (about 1–2 minutes per 1,000 photos). "
            "Later runs reuse the cached analysis and finish in seconds.", "Muted", wrap=True,
        ))
        self.train_progress = ProgressPanel()
        l2.addWidget(self.train_progress)
        self.result_box = QVBoxLayout()
        l2.addLayout(self.result_box)
        l2.addStretch(1)
        self.add_page(p2)
        self.go(0)
        self.next_btn.setText("Update Profile" if update_name else "Train Profile")
        learning_tweaks = bool(self.only_tweaked_catalogs or self.include_approved_catalogs
                               or self.strip_look_catalogs or tweak_boost != 2.0)
        if update_name:
            self.name.setText(update_name)
            self.name.setReadOnly(True)
        if update_name and learning_tweaks:
            note_txt = (
                f"Learning with {self.tweak_boost:g}× emphasis on your Lightroom tweaks. "
                "Keep your foundation catalogs checked so your tweaks refine your profile smoothly."
            )
            self.update_note = label(note_txt, "Chip")
            p1.layout().insertWidget(2, self.update_note)
        paths = [os.path.normpath(p) for p in dict.fromkeys(list(catalogs) + list(new_catalogs))]
        self.keep_checked = set(paths)
        for p in paths:
            self._add_row(p)
        if paths:
            self._count(paths)

    min_photos = 30

    def refresh(self):
        if self.stack.currentIndex() == 0:
            total = sum(
                self.counts.get(self.table.item(r, self.COL_PATH).text(), 0)
                for r in range(self.table.rowCount())
                if self.table.item(r, self.COL_CHECK).checkState() == Qt.Checked
            )
            self.total.setText(f"{total:,} photos selected")
            self.next_btn.setEnabled(total >= self.min_photos and bool(self.name.text().strip()))

    def count_for(self, catalog_path):
        return lrcat.summarize(catalog_path)["trainable"]

    def make_train(self, name, cats, weights=None):
        step = self.learn_from.currentData()
        return lambda progress=None, cancelled=None: model.train_profile(
            name, cats, progress, cancelled,
            feedback=None if step else proj.feedback_for(cats),
            catalog_weights=weights,
            snapshot_step=step,
            tweak_boost=self.tweak_boost,
            only_tweaked_catalogs=self.only_tweaked_catalogs,
            include_approved_catalogs=self.include_approved_catalogs,
            strip_look_catalogs=self.strip_look_catalogs,
        )

    def _add_row(self, path):
        for r in range(self.table.rowCount()):
            if self.table.item(r, self.COL_PATH).text() == path:
                return
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        chk.setCheckState(Qt.Checked if path in self.keep_checked else Qt.Unchecked)
        self.table.setItem(r, self.COL_CHECK, chk)
        main = QTableWidgetItem()
        main.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        main.setCheckState(Qt.Unchecked if path in self.supporting else Qt.Checked)
        self.table.setItem(r, self.COL_MAIN, main)
        self.table.setItem(r, self.COL_NAME, QTableWidgetItem(os.path.splitext(os.path.basename(path))[0]))
        self.table.setItem(r, self.COL_PHOTOS, QTableWidgetItem("counting…"))
        self.table.setItem(r, self.COL_PATH, QTableWidgetItem(path))
        self.table.blockSignals(False)

    def _count(self, paths):
        snap = model.snapshot_counts(self.update_name) if self.update_name else {}
        cached = set()

        def work(progress=None, cancelled=None):
            out = {}
            for i, p in enumerate(paths):
                n_snap = snap.get(os.path.normpath(p), 0)
                try:
                    n = self.count_for(p) if os.path.exists(p) else -1
                except Exception:
                    n = -1
                if n <= 0 and n_snap:  # offline (or its RAW files moved): the profile's snapshot still has it
                    n = n_snap
                    cached.add(p)
                out[p] = n
                if progress:
                    progress(i + 1, len(paths), "Counting")
            return out

        def done(res):
            self.counts.update({k: max(v, 0) for k, v in res.items()})
            self.table.blockSignals(True)
            for r in range(self.table.rowCount()):
                p = self.table.item(r, self.COL_PATH).text()
                if p in res:
                    n = res[p]
                    text = "unreadable" if n < 0 else f"{n:,}" + (" (cached snapshot)" if p in cached else "")
                    self.table.item(r, self.COL_PHOTOS).setText(text)
                    if p in cached:
                        self.table.item(r, self.COL_PHOTOS).setToolTip(
                            "This shoot is offline. Virten Studio keeps the photo analysis and settings it learned "
                            "from, so a retrain still includes it.")
                    keep = p in self.keep_checked
                    self.table.item(r, self.COL_CHECK).setCheckState(
                        Qt.Checked if n >= 20 or (keep and n > 0) else Qt.Unchecked
                    )
            self.table.blockSignals(False)
            self.scan_status.setText("")
            self.refresh()
            self.update_steps()

        start_worker(
            self, work,
            on_progress=lambda a, b, s: self.scan_status.setText(f"Counting photos {a}/{b}…"),
            on_done=done,
        )

    def update_steps(self):
        paths = [self.table.item(r, self.COL_PATH).text() for r in range(self.table.rowCount())]
        current = self.learn_from.currentData()

        def done(counts):
            self.learn_from.blockSignals(True)
            while self.learn_from.count() > 1:
                self.learn_from.removeItem(1)
            for name, n in list(counts.items())[:8]:
                self.learn_from.addItem(f"Settings right after “{name}” ({n:,} photos)", name)
            idx = self.learn_from.findData(current)
            self.learn_from.setCurrentIndex(max(0, idx))
            self.learn_from.blockSignals(False)

        start_worker(self, _plain(lrcat.history_step_counts), paths, on_done=done)

    def add_catalog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose Lightroom catalogs", "", "Lightroom catalog (*.lrcat)")
        for f in files:
            self._add_row(os.path.normpath(f))
        if files:
            self._count([os.path.normpath(f) for f in files])

    def scan(self):
        d = QFileDialog.getExistingDirectory(self, "Scan for Lightroom catalogs")
        if not d:
            return
        self.scan_status.setText("Scanning for catalogs…")

        def found(paths):
            for p in paths:
                self._add_row(os.path.normpath(p))
            if paths:
                self._count([os.path.normpath(p) for p in paths])
            else:
                self.scan_status.setText("No catalogs found there.")

        start_worker(self, _plain(lrcat.find_catalogs), d, on_done=found)

    def next(self):
        if self.stack.currentIndex() != 0:
            return self.accept()
        name = self.name.text().strip()
        if not self.update_name and os.path.exists(model.profile_path(name)) and QMessageBox.question(
            self, "Virten Studio", f'A profile named "{name}" already exists. Replace it?'
        ) != QMessageBox.Yes:
            return
        rows = [r for r in range(self.table.rowCount()) if self.table.item(r, self.COL_CHECK).checkState() == Qt.Checked]
        cats = [self.table.item(r, self.COL_PATH).text() for r in rows]
        weights = {
            self.table.item(r, self.COL_PATH).text():
            1.0 if self.table.item(r, self.COL_MAIN).checkState() == Qt.Checked else model.SUPPORTING_WEIGHT
            for r in rows
        }
        self.go(1)
        self.next_btn.setEnabled(False)
        self.next_btn.setText("Finish")
        self.cancel_btn.setText("Stop")
        train = self.make_train(name, cats, weights)
        self.worker = start_worker(
            self, train,
            on_progress=self.train_progress.update,
            on_done=self.trained,
            on_failed=self.train_failed,
        )
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.worker.cancel)

    def trained(self, profile):
        self.train_title.setText(f"“{profile['name']}” is ready")
        corr = profile.get("n_corrected") or 0
        extra = f" (including {corr:,} tweaked photos)" if corr else ""
        self.train_progress.update(1, 1, f"Learned from {profile['n_photos']:,} photos{extra}")
        self.result_box.addWidget(MetricsTable(profile["metrics"]))
        self.next_btn.setEnabled(True)
        self.cancel_btn.hide()

    def train_failed(self, msg):
        self.train_title.setText("Training stopped")
        self.train_progress.status.setText(msg)
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.reject)


class MetricsTable(QTableWidget):
    def __init__(self, metrics):
        rows = sorted(
            metrics.items(),
            key=lambda kv: (
                model.KEY_GROUP[kv[0]] != "tone",
                model.KEY_GROUP[kv[0]] != "wb",
                model.ALL_KEYS.index(kv[0]),
            ),
        )
        super().__init__(len(rows), 3)
        self.setHorizontalHeaderLabels(["Setting", "Typical error (Virten Studio AI)", "Typical error (one preset for all)"])
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, (k, m) in enumerate(rows):
            self.setItem(r, 0, QTableWidgetItem(model.display_name(k)))
            self.setItem(r, 1, QTableWidgetItem(fmt_metric(k, m["mae"])))
            self.setItem(r, 2, QTableWidgetItem(fmt_metric(k, m["baseline_mae"])))


class DropZone(QFrame):
    dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        l = QVBoxLayout(self)
        l.setAlignment(Qt.AlignCenter)
        self.title = label("Drop a Lightroom catalog (.lrcat) here", "H2")
        self.title.setAlignment(Qt.AlignCenter)
        l.addWidget(self.title)
        b = button("Browse Catalog…", slot=self.browse)
        l.addLayout(hbox(None, b, None))

    def browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose Lightroom catalog", "", "Lightroom catalog (*.lrcat)")
        if f:
            self.dropped.emit(os.path.normpath(f))

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".lrcat") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".lrcat"):
                self.dropped.emit(os.path.normpath(u.toLocalFile()))
                break


class PhotoPickerWizard(Wizard):
    verb = "edited"

    def build_photo_page(self, prefs_key, defaults):
        self.photos = []
        self.catalog_path = None
        p1 = QWidget()
        l = QVBoxLayout(p1)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        self.drop = DropZone()
        self.drop.dropped.connect(self.load_catalog)
        l.addWidget(self.drop)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Project name")
        self.name.textChanged.connect(self.refresh)
        l.addWidget(self.name)
        remembered = {k: v for k, v in prefs.load().get(prefs_key, {}).items() if k not in ("ratings", "labels")}
        saved_filters = {**defaults, **remembered}
        cols = QHBoxLayout()
        cols.setSpacing(20)

        where = QVBoxLayout()
        where.addWidget(label("Folders", "H2"))
        self.folders = QListWidget()
        self.folders.itemChanged.connect(lambda *_: self.refresh())
        where.addWidget(self.folders, 3)
        where.addWidget(label("Collections", "H2"))
        where.addWidget(label("Leave all unchecked to include all collections.", "Muted"))
        self.collections = QListWidget()
        self.collections.itemChanged.connect(lambda *_: self.refresh())
        where.addWidget(self.collections, 2)
        cols.addLayout(where, 3)

        which = QVBoxLayout()
        which.setSpacing(8)
        which.addWidget(label("Flags", "H2"))
        self.flag = QComboBox()
        for k, v in proj.FLAG_FILTERS.items():
            self.flag.addItem(v, k)
        self.flag.setCurrentIndex(max(0, self.flag.findData(saved_filters.get("flag", "not_rejected"))))
        self.flag.currentIndexChanged.connect(self.refresh)
        which.addWidget(self.flag)
        which.addSpacing(6)
        which.addWidget(label("Star rating", "H2"))
        self.star_boxes = {}
        star_row = QGridLayout()
        saved_ratings = saved_filters.get("ratings")
        for i, r in enumerate(range(6)):
            cb = QCheckBox("No stars" if r == 0 else "★" * r)
            cb.setChecked(saved_ratings is None or r in saved_ratings)
            cb.toggled.connect(self.refresh)
            self.star_boxes[r] = cb
            star_row.addWidget(cb, i // 2, i % 2)
        which.addLayout(star_row)
        which.addWidget(button(
            "Only rated photos (★ and up)",
            slot=lambda: [cb.setChecked(r > 0) for r, cb in self.star_boxes.items()],
        ))
        which.addSpacing(6)
        which.addWidget(label("Color label", "H2"))
        self.label_boxes = {}
        label_row = QGridLayout()
        saved_labels = saved_filters.get("labels")
        for i, name in enumerate(proj.LABELS):
            cb = QCheckBox(name or "No label")
            cb.setChecked(saved_labels is None or name in saved_labels)
            cb.toggled.connect(self.refresh)
            self.label_boxes[name] = cb
            label_row.addWidget(cb, i // 3, i % 3)
        which.addLayout(label_row)
        which.addSpacing(6)
        self.only_unedited = QCheckBox("Only photos that haven't been edited yet")
        self.only_unedited.setChecked(saved_filters.get("only_unedited", True))
        self.only_unedited.toggled.connect(self.refresh)
        which.addWidget(self.only_unedited)
        which.addStretch(1)
        cols.addLayout(which, 2)
        l.addLayout(cols, 1)
        self.count = label("", "H2")
        l.addWidget(self.count)
        self.add_page(p1)
        return p1

    def load_catalog(self, path):
        self.catalog_path = path
        self.drop.title.setText(os.path.basename(path))
        if not self.name.text():
            self.name.setText(os.path.splitext(os.path.basename(path))[0])
        self.count.setText("Reading catalog…")
        start_worker(
            self, _plain(lambda p: (lrcat.list_photos(p), lrcat.list_collections(p))), path,
            on_done=self.catalog_loaded,
            on_failed=lambda m: self.count.setText(f"Couldn't read catalog: {m}"),
        )

    def catalog_loaded(self, result):
        photos, collections = result
        self.collections.blockSignals(True)
        self.collections.clear()
        for cid, name, n in collections:
            it = QListWidgetItem(f"{name}    ({n:,})")
            it.setData(Qt.UserRole, cid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.collections.addItem(it)
        self.collections.blockSignals(False)
        self.photos = [p for p in photos if p.is_raw]
        by_folder = {}
        for p in self.photos:
            by_folder[p.folder] = by_folder.get(p.folder, 0) + 1
        self.folders.blockSignals(True)
        self.folders.clear()
        for f, n in sorted(by_folder.items()):
            it = QListWidgetItem(f"{f}    ({n:,} RAW)")
            it.setData(Qt.UserRole, f)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.folders.addItem(it)
        self.folders.blockSignals(False)
        self.refresh()

    def chosen_folders(self):
        return [
            self.folders.item(i).data(Qt.UserRole)
            for i in range(self.folders.count())
            if self.folders.item(i).checkState() == Qt.Checked
        ]

    def filters(self):
        folders = self.chosen_folders()
        ratings = [r for r, cb in self.star_boxes.items() if cb.isChecked()]
        labels = [n for n, cb in self.label_boxes.items() if cb.isChecked()]
        return {
            "folders": None if len(folders) == self.folders.count() else folders,
            "collections": [
                self.collections.item(i).data(Qt.UserRole)
                for i in range(self.collections.count())
                if self.collections.item(i).checkState() == Qt.Checked
            ],
            "flag": self.flag.currentData(),
            "ratings": None if len(ratings) == len(self.star_boxes) else ratings,
            "labels": None if len(labels) == len(self.label_boxes) else labels,
            "only_unedited": self.only_unedited.isChecked(),
        }

    def selected_count(self):
        f = self.filters()
        return sum(1 for p in self.photos if proj.matches(p, f))

    def why_zero(self):
        f = self.filters()
        relax = {
            "Folders": {"folders": None},
            "Collections": {"collections": []},
            "Flags": {"flag": "any"},
            "Star rating": {"ratings": None},
            "Color label": {"labels": None},
            "“Only photos that haven't been edited yet”": {"only_unedited": False},
        }
        hints = []
        for name, change in relax.items():
            n = sum(1 for p in self.photos if proj.matches(p, {**f, **change}))
            if n:
                hints.append(f"{name} is hiding {n:,} photo{'s' if n != 1 else ''}")
        if not hints:
            return "No photos match. Try relaxing several filters."
        return "No photos match: " + "; ".join(hints) + "."


class NewProjectWizard(PhotoPickerWizard):
    def __init__(self, parent, catalog_path=None):
        super().__init__(parent, "New Editing Project", ["Photos", "Profile & Look", "Tools", "Edit"])
        self.resize(1040, 800)
        self.result = None

        self.build_photo_page(
            "last_filters",
            {"flag": "not_rejected", "only_unedited": True, "ratings": [1], "labels": [""]},
        )

        saved_choices = prefs.load().get("last_choices", {})
        p2 = QWidget()
        cols2 = QHBoxLayout(p2)
        cols2.setContentsMargins(0, 0, 0, 0)
        cols2.setSpacing(24)
        l2 = QVBoxLayout()
        cols2.addLayout(l2, 1)
        l2.addWidget(label("Personal profile", "H2"))
        l2.addWidget(label("Sets exposure, white balance and your learned adjustments per photo.", "Muted", wrap=True))
        self.profiles = QListWidget()
        self.profiles.setIconSize(QSize(1, 48))
        for meta in model.list_profiles():
            it = QListWidgetItem(
                f"{meta['name']}\n{meta['n_photos']:,} photos · {len(meta['catalogs'])} catalogs · "
                f"created {meta['created'][:10]}"
            )
            it.setData(Qt.UserRole, meta["name"])
            self.profiles.addItem(it)
        no_profile = QListWidgetItem("No profile: Look only\nApplies the chosen Look as-is; no per-photo AI corrections.")
        no_profile.setData(Qt.UserRole, None)
        self.profiles.addItem(no_profile)
        self.profiles.setCurrentRow(0)
        self.profiles.currentRowChanged.connect(self.refresh)
        l2.addWidget(self.profiles, 1)

        l2b = QVBoxLayout()
        cols2.addLayout(l2b, 1)
        l2b.addWidget(label("Look", "H2"))
        l2b.addWidget(label("An optional stylistic grade layered on top of your profile.", "Muted", wrap=True))
        self.looks = QListWidget()
        self.looks.setIconSize(QSize(*_LOOK_THUMB))
        none = QListWidgetItem(QIcon(look_preview_pixmap(None)), "None: just my profile\nYour own natural style, as learned.")
        none.setData(Qt.UserRole, None)
        self.looks.addItem(none)
        for lk in looks.list_looks():
            it = QListWidgetItem(QIcon(look_preview_pixmap(lk)), f"{lk['name']}\n{lk.get('description', '')}")
            it.setData(Qt.UserRole, lk["name"])
            self.looks.addItem(it)
        self.looks.setWordWrap(True)
        self.looks.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.looks.setCurrentRow(0)
        for i in range(self.looks.count()):
            if self.looks.item(i).data(Qt.UserRole) == looks.canonical_name(saved_choices.get("look")):
                self.looks.setCurrentRow(i)
        if self.looks.currentRow() == 0 and self.looks.count() > 1 and self.look_only():
            self.looks.setCurrentRow(1)
        self.look_strength = StrengthSlider(int(saved_choices.get("look_strength", 1.0) * 100), maximum=150)
        self.looks.currentRowChanged.connect(lambda *_: self.look_strength.setEnabled(self.looks.currentRow() > 0))
        self.looks.currentRowChanged.connect(self.refresh)
        self.look_strength.setEnabled(self.looks.currentRow() > 0)
        l2b.addWidget(self.looks, 1)
        l2b.addLayout(hbox(label("Look strength"), self.look_strength))
        self.add_page(p2)

        saved = prefs.load().get("last_choices", {})
        p3 = QWidget()
        cols = QHBoxLayout(p3)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(label("AI tools", "H2"))
        left.addWidget(label(
            "Lightroom computes the AI masks when edits are applied. Strength 100% = your learned baseline.",
            "Muted", wrap=True,
        ))
        self.tool_boxes, self.tool_notes, self.tool_strength = {}, {}, {}
        for key, title in tools.TOOLS.items():
            card = QFrame()
            card.setObjectName("Card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            cb = QCheckBox(title)
            cb.setChecked(saved.get(key, key in ("crop", "subject")))
            cb.setStyleSheet("font-weight:600;")
            note = label("", "Muted", wrap=True)
            cl.addWidget(cb)
            cl.addWidget(note)
            if key != "crop":
                sl = StrengthSlider(int(saved.get(f"{key}_strength", 1.0) * 100))
                cl.addLayout(hbox(label("Strength", "Muted"), sl))
                self.tool_strength[key] = sl
                cb.toggled.connect(sl.setEnabled)
                sl.setEnabled(cb.isChecked())
            self.tool_boxes[key], self.tool_notes[key] = cb, note
            left.addWidget(card)
        left.addStretch(1)
        cols.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(label("Develop Panels", "H2"))
        right.addWidget(label("Unchecked panels are left untouched in Lightroom.", "Muted"))
        self.group_boxes = {}
        for g, d in model.GROUPS.items():
            cb = QCheckBox(d["label"])
            cb.setChecked(saved.get(g, True))
            self.group_boxes[g] = cb
            right.addWidget(cb)
        right.addSpacing(16)
        right.addWidget(label("Exposure bias", "H2"))
        self.bias = QDoubleSpinBox()
        self.bias.setRange(-2, 2)
        self.bias.setSingleStep(0.05)
        self.bias.setDecimals(2)
        self.bias.setSuffix(" EV")
        self.bias.setMaximumWidth(140)
        self.bias.setValue(float(saved.get("exposure_bias", 0.0)))
        right.addWidget(self.bias)
        right.addWidget(label("Shift every photo brighter or darker than the profile's baseline.", "Muted", wrap=True))
        right.addSpacing(12)
        self.burst_cb = QCheckBox("Smooth exposure & white balance across bursts")
        self.burst_cb.setChecked(bool(saved.get("burst_consistency", True)))
        self.burst_cb.setToolTip("Frames shot seconds apart of the same scene get matching white balance and, when "
                                 "lit alike, matching exposure, so a burst doesn't flicker.")
        right.addWidget(self.burst_cb)
        right.addSpacing(16)
        right.addLayout(hbox(
            button("Select all", slot=lambda: self.set_all(True)),
            button("Clear all", slot=lambda: self.set_all(False)),
            None,
        ))
        right.addStretch(1)
        cols.addLayout(right, 1)
        for cb in list(self.tool_boxes.values()) + list(self.group_boxes.values()):
            cb.toggled.connect(self.refresh)
        self.add_page(p3)

        p4 = QWidget()
        l4 = QVBoxLayout(p4)
        l4.setContentsMargins(0, 30, 0, 0)
        l4.setSpacing(14)
        self.run_title = label("Editing your photos", "H2")
        l4.addWidget(self.run_title)
        self.run_progress = ProgressPanel()
        l4.addWidget(self.run_progress)
        l4.addStretch(1)
        self.add_page(p4)

        self.go(0)
        if catalog_path:
            self.load_catalog(catalog_path)

    def refresh(self):
        i = self.stack.currentIndex()
        self.next_btn.setText("Start Editing" if i == 2 else "Next")
        if i == 0:
            n = self.selected_count() if self.photos else 0
            if self.photos:
                self.count.setText(f"{n:,} photos will be {self.verb}" if n else self.why_zero())
            self.next_btn.setEnabled(n > 0 and bool(self.name.text().strip()))
        elif i == 1:
            self.next_btn.setEnabled(
                self.profiles.currentItem() is not None and (not self.look_only() or self.looks.currentRow() > 0)
            )
        elif i == 2:
            self.update_tool_availability()
            self.next_btn.setEnabled(self.look_only() or bool(self.chosen_options()))
        self._update_bg(i == 2)

    def look_only(self):
        it = self.profiles.currentItem()
        return it is not None and it.data(Qt.UserRole) is None

    def profile_meta(self):
        it = self.profiles.currentItem()
        name = it.data(Qt.UserRole) if it else None
        return next((m for m in model.list_profiles() if m["name"] == name), {})

    def update_tool_availability(self):
        meta = self.profile_meta()
        look_only = self.look_only()
        for cb in self.group_boxes.values():
            cb.setEnabled(not look_only)
        for key, cb in self.tool_boxes.items():
            available = key in (meta.get("available_tools") or [])
            cb.setEnabled(available)
            note = self.tool_notes[key]
            if look_only:
                note.setText("Needs a personal profile (Look only applies just the Look).")
            elif not available:
                note.setText("Not learned by this profile (too few examples in its catalogs).")
            else:
                shoots = (meta.get("tool_shoots") or {}).get(key, 0)
                learned = f"Learned from {shoots} shoot{'s' if shoots != 1 else ''} where you used it. "
                tm = meta.get("tool_metrics") or {}
                if key == "crop":
                    acc = tm.get("Straighten angle")
                    note.setText(
                        learned + "Levels each photo and crops to fit"
                        + (f" (typically within ±{acc['mae']:.1f}°)." if acc else ".")
                    )
                elif key in ("skin", "teeth"):
                    note.setText(learned + "Added to every photo; Lightroom only changes photos with people.")
                elif key == "sky":
                    note.setText(learned + "Added to every photo; Lightroom only changes photos with sky.")
                else:
                    note.setText(learned + "Strength is set per photo.")

    def set_all(self, on):
        for cb in list(self.tool_boxes.values()) + list(self.group_boxes.values()):
            if cb.isEnabled():
                cb.setChecked(on)

    def chosen_options(self):
        return (
            [g for g, c in self.group_boxes.items() if c.isChecked() and c.isEnabled()]
            + [k for k, c in self.tool_boxes.items() if c.isChecked() and c.isEnabled()]
        )

    def run_in_background(self):
        main = self._main_window()
        if main is None:
            return
        p = self._make_project()
        main.enqueue_job(f"Editing “{p['name']}”", proj.run_project, p, on_done=main.project_finished,
                         on_failed=lambda m, n=p["name"]: main.flash(f"“{n}” stopped: {m}"))
        self.accept()

    def next(self):
        i = self.stack.currentIndex()
        if i < 2:
            return self.go(i + 1)
        if i == 3:
            return self.accept()
        p = self._make_project()
        self.go(3)
        self.next_btn.setEnabled(False)
        self.next_btn.setText("View Results")
        self.cancel_btn.setText("Stop")
        self.worker = start_worker(
            self, proj.run_project, p,
            on_progress=self.run_progress.update,
            on_done=self.finished_run,
            on_failed=self.run_failed,
        )
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.worker.cancel)

    def _make_project(self):
        """Saves the wizard's choices for next time and returns the new (not yet run) project."""
        filters = self.filters()
        choices = {k: c.isChecked() for k, c in list(self.tool_boxes.items()) + list(self.group_boxes.items())}
        strengths = {k: s.value() / 100 for k, s in self.tool_strength.items()}
        look_name = self.looks.currentItem().data(Qt.UserRole) if self.looks.currentItem() else None
        choices.update({f"{k}_strength": v for k, v in strengths.items()})
        choices.update(look=look_name, look_strength=self.look_strength.value() / 100,
                       burst_consistency=self.burst_cb.isChecked())
        prefs.save(
            last_choices={**choices, "exposure_bias": self.bias.value()},
            last_filters={k: filters[k] for k in ("flag", "only_unedited")},
        )
        return proj.new_project(
            self.name.text().strip(), self.catalog_path, self.profiles.currentItem().data(Qt.UserRole),
            filters=filters, groups=self.chosen_options(), exposure_bias=self.bias.value(),
            tool_strength=strengths, look=look_name, look_strength=self.look_strength.value() / 100,
            burst_consistency=self.burst_cb.isChecked(),
        )

    def finished_run(self, project):
        self.result = project
        self.run_title.setText("Your edits are ready")
        self.run_progress.update(1, 1, f"Edited {project['count']:,} photos")
        self.cancel_btn.hide()
        self.next_btn.setEnabled(True)

    def run_failed(self, msg):
        self.run_title.setText("Editing stopped")
        self.run_progress.status.setText(msg)
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.reject)


class NewCullWizard(PhotoPickerWizard):
    verb = "checked"

    def __init__(self, parent, catalog_path=None):
        super().__init__(parent, "New Assisted Cull", ["Photos", "Options", "Cull"])
        self.resize(1040, 800)
        self.result = None
        self.build_photo_page(
            "last_cull_filters",
            {"flag": "any", "only_unedited": False, "ratings": [0], "labels": None},
        )

        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(10)
        l2.addWidget(label("What you'll get in Lightroom", "H2"))
        m = cull.load_model()
        best = (
            f"◆ <b>Likely best frame</b> in bursts of people: learned from {m.get('n_bursts', 0):,} bursts you "
            "culled. Treat it as a pointer, not a decision."
            if m else
            "◆ <b>Likely best frame</b> in bursts of people needs training first: Profiles ▸ Assisted culling ▸ "
            "Learn from your culls. Everything else works without it."
        )
        info = label(
            "All suggestions go under the <b>Virten Cull</b> keyword (left out when you export) and a "
            "<b>Virten Cull</b> collection set. Your star ratings, flags, color labels and edits aren't changed."
            "<br><br>• <b>Burst</b>: near-identical frames shot within seconds, so you can compare them."
            "<br>• <b>Timelapse</b>: intervalometer sequences, left out of everything else."
            "<br>• <b>Likely reject</b>, with the reason: blurry, eyes closed, exposure way off, flash didn't fire.<br>• "
            + best, wrap=True,
        )
        info.setTextFormat(Qt.RichText)
        l2.addWidget(info)
        l2.addSpacing(10)
        l2.addWidget(label("How strict", "H2"))
        self.strict = QComboBox()
        for k, text in (
            ("relaxed", "Relaxed: only obvious rejects"),
            ("normal", "Normal"),
            ("strict", "Strict: flag anything doubtful"),
        ):
            self.strict.addItem(text, k)
        self.strict.setCurrentIndex(max(0, self.strict.findData(prefs.load().get("cull_strictness", "normal"))))
        self.strict.setMaximumWidth(360)
        l2.addWidget(self.strict)
        l2.addStretch(1)
        self.add_page(p2)

        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(0, 30, 0, 0)
        l3.setSpacing(14)
        self.run_title = label("Looking through your photos", "H2")
        l3.addWidget(self.run_title)
        self.run_progress = ProgressPanel()
        l3.addWidget(self.run_progress)
        l3.addStretch(1)
        self.add_page(p3)
        self.go(0)
        if catalog_path:
            self.load_catalog(catalog_path)

    def refresh(self):
        i = self.stack.currentIndex()
        self.next_btn.setText("Start Cull" if i == 1 else "Next")
        if i == 0:
            n = self.selected_count() if self.photos else 0
            if self.photos:
                self.count.setText(f"{n:,} photos will be {self.verb}" if n else self.why_zero())
            self.next_btn.setEnabled(n > 1 and bool(self.name.text().strip()))
        elif i == 1:
            self.next_btn.setEnabled(True)
        self._update_bg(i == 1)

    def _make_project(self):
        filters = self.filters()
        prefs.save(
            cull_strictness=self.strict.currentData(),
            last_cull_filters={k: filters[k] for k in ("flag", "ratings", "labels", "only_unedited")},
        )
        return proj.new_project(
            self.name.text().strip(), self.catalog_path, None,
            kind="cull", filters=filters, strictness=self.strict.currentData(),
        )

    def run_in_background(self):
        main = self._main_window()
        if main is None:
            return
        p = self._make_project()
        main.enqueue_job(f"Culling “{p['name']}”", proj.run_cull, p, on_done=main.project_finished,
                         on_failed=lambda m, n=p["name"]: main.flash(f"“{n}” stopped: {m}"))
        self.accept()

    def next(self):
        i = self.stack.currentIndex()
        if i == 0:
            return self.go(1)
        if i == 2:
            return self.accept()
        p = self._make_project()
        self.go(2)
        self.next_btn.setEnabled(False)
        self.next_btn.setText("View Results")
        self.cancel_btn.setText("Stop")
        self.worker = start_worker(
            self, proj.run_cull, p,
            on_progress=self.run_progress.update,
            on_done=self.finished_run,
            on_failed=self.run_failed,
        )
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.worker.cancel)

    def finished_run(self, project):
        self.result = project
        s = project.get("summary") or {}
        self.run_title.setText("Your cull suggestions are ready")
        self.run_progress.update(
            1, 1,
            f"{s.get('photos', 0):,} photos · {s.get('likely_rejects', 0):,} likely rejects · "
            f"{s.get('bursts', 0):,} bursts · {s.get('best_hints', 0):,} likely best frames",
        )
        self.cancel_btn.hide()
        self.next_btn.setEnabled(True)

    def run_failed(self, msg):
        self.run_title.setText("Cull stopped")
        self.run_progress.status.setText(msg)
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.reject)


# ---------------------------------------------------------------- main pages

class Page(QWidget):
    def __init__(self, title, action_text=None, action=None):
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 26, 32, 22)
        outer.setSpacing(16)
        self.header = hbox(label(title, "H1"), None)
        if action_text:
            self.header.addWidget(button(action_text, "Primary", action))
        outer.addLayout(self.header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("Page")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

    def empty_state(self, title, text, action_text, action):
        box = QFrame()
        box.setObjectName("Card")
        l = QVBoxLayout(box)
        l.setContentsMargins(40, 50, 40, 50)
        l.setAlignment(Qt.AlignCenter)
        t = label(title, "H2")
        t.setAlignment(Qt.AlignCenter)
        d = label(text, "Muted", wrap=True)
        d.setAlignment(Qt.AlignCenter)
        l.addWidget(t)
        l.addWidget(d)
        l.addLayout(hbox(None, button(action_text, "Primary", action), None))
        self.body.addWidget(box)
        self.body.addStretch(1)


class ProfilesPage(Page):
    def __init__(self, main):
        super().__init__("Personal AI Profiles", "+  New Profile", self.new_profile)
        self.header.insertWidget(2, button("Import profile…", slot=self.import_profile))
        self.main = main
        self.reload()

    def new_profile(self, *_):
        NewProfileWizard(self).exec()
        self.reload()

    def learn(self, meta, extra=(), tweak_boost=2.0, only_tweaked_catalogs=None,
              include_approved_catalogs=None, strip_look_catalogs=None):
        # Learning from a specific shoot (Learn from Lightroom Tweaks…) adds only that shoot; the Profiles page's
        # "Learn from new edits" (no extra) offers every applied project the profile hasn't learned from yet.
        candidates = list(extra) if extra else proj.learning_candidates(meta)
        known = {os.path.normpath(c) for c in meta["catalogs"]}
        new = [c for c in candidates if os.path.normpath(c) not in known]
        NewProfileWizard(
            self,
            update_name=meta["name"],
            catalogs=meta["catalogs"],
            new_catalogs=list(dict.fromkeys(new)),
            catalog_weights=meta.get("catalog_weights"),
            tweak_boost=tweak_boost,
            only_tweaked_catalogs=only_tweaked_catalogs,
            include_approved_catalogs=include_approved_catalogs,
            strip_look_catalogs=strip_look_catalogs,
        ).exec()
        self.reload()

    def export(self, meta):
        dst, _ = QFileDialog.getSaveFileName(
            self, "Export profile", model.safe_filename(meta["name"]) + ".virten-profile",
            "Virten Studio profile (*.virten-profile)",
        )
        if dst:
            shutil.copyfile(model.profile_path(meta["name"]), dst)
            QMessageBox.information(
                self, "Virten Studio",
                "Exported. On your other computer, use Profiles ▸ Import profile… to add it.",
            )

    def import_profile(self, *_):
        src, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "Virten Studio profile (*.virten-profile)")
        if not src:
            return
        try:
            profile = model.import_profile(src)
        except Exception as e:
            QMessageBox.critical(self, "Virten Studio", f"Couldn't import that profile:\n{e}")
            return
        QMessageBox.information(self, "Virten Studio", f"Imported “{profile['name']}”.")
        self.reload()

    def reload(self):
        clear_layout(self.body)
        profiles = model.list_profiles()
        if profiles:
            grid = QGridLayout()
            grid.setSpacing(14)
            for i, meta in enumerate(profiles):
                grid.addWidget(self.card(meta), i // 2, i % 2)
            self.body.addLayout(grid)
        else:
            self.body.addWidget(self.simple_card(
                "Teach Virten Studio your editing style",
                "Point it at Lightroom catalogs you've already edited. It learns how you set exposure, white "
                "balance, tone and color for different kinds of photos.",
                [button("Create your first profile", "Primary", self.new_profile)],
            ))
        self.body.addSpacing(10)
        self.body.addWidget(self.cull_card())
        self.body.addStretch(1)

    def cull_card(self):
        m = cull.load_model()
        cats = proj.cull_learning_catalogs()
        new = [c for c in cats if c not in ((m or {}).get("catalogs") or [])]
        if m:
            text = (
                f"Picks the likely best frame in bursts of people, from {m.get('n_bursts', 0):,} bursts you culled "
                f"in {len(m.get('catalogs') or [])} shoots · {m.get('created', '')[:10]}."
            )
        else:
            text = (
                "Learns which frame you keep in bursts of people (expression, gaze, eye focus) from shoots you've "
                f"already culled (any star = kept). {len(cats)} shoot(s) available to learn from."
            )
        card = self.simple_card("Assisted culling", text, [button(
            "Learn from your culls" if not m else "Update from new culls",
            "Primary" if (new or not m) else None,
            self.train_cull,
        )])
        if m and new:
            card.layout().insertWidget(2, label(f"● {len(new)} shoot(s) not learned from yet", "Chip"))
        return card

    def train_cull(self, *_):
        cats = proj.cull_learning_catalogs()
        if not cats:
            QMessageBox.information(
                self, "Virten Studio",
                "No finished shoots to learn from yet. Profiles learn from your edited catalogs; "
                "culls you mark as finished are added too.",
            )
            return
        d = QDialog(self)
        d.setWindowTitle("Assisted culling")
        d.resize(560, 220)
        l = QVBoxLayout(d)
        l.setContentsMargins(24, 20, 24, 20)
        l.addWidget(label("Learning from your culls", "H2"))
        l.addWidget(label(
            f"{len(cats)} shoot(s). The first time, faces in every burst of people are analysed at high resolution.",
            "Muted", wrap=True,
        ))
        bar = ProgressPanel()
        l.addWidget(bar)
        close = button("Stop", slot=d.reject)
        l.addLayout(hbox(None, close))

        def done(model_):
            bar.update(1, 1, f"Learned from {model_['n_bursts']:,} bursts of people in {len(model_['catalogs'])} shoots.")
            close.setText("Close")

        def failed(msg):
            bar.status.setText(msg)
            close.setText("Close")

        start_worker(d, cull.train, cats, on_progress=bar.update, on_done=done, on_failed=failed)
        d.finished.connect(lambda *_: stop_workers([(t, wk) for t, wk in getattr(d, "_workers", []) if t.isRunning()]))
        d.exec()
        self.reload()

    def simple_card(self, title, text, buttons):
        c = QFrame()
        c.setObjectName("Card")
        l = QVBoxLayout(c)
        l.setContentsMargins(20, 18, 20, 16)
        l.setSpacing(6)
        l.addWidget(label(title, "H2"))
        l.addWidget(label(text, "Muted", wrap=True))
        l.addSpacing(6)
        l.addLayout(hbox(*buttons, None))
        return c

    def card(self, meta):
        c = QFrame()
        c.setObjectName("Card")
        l = QVBoxLayout(c)
        l.setContentsMargins(20, 18, 20, 16)
        l.setSpacing(6)
        corr = meta.get("n_corrected") or 0
        corr_tag = f" · {corr:,} user tweaks learned" if corr else ""
        l.addWidget(label(meta["name"], "H2"))
        l.addWidget(label(
            f"Learned from {meta['n_photos']:,} photos in {len(meta['catalogs'])} catalogs{corr_tag} · "
            f"{meta['created'][:10]}", "Muted",
        ))
        m = meta.get("metrics", {})
        acc = [
            f"{model.display_name(k)} {fmt_metric(k, m[k]['mae'])}"
            for k in ("Exposure2012", "Temperature", "Tint") if k in m
        ]
        if acc:
            l.addWidget(label("Typical error on new shoots:  " + "  ·  ".join(acc), "Muted"))
        learned = [tools.TOOLS[k].split(" (")[0] for k in meta.get("available_tools") or []]
        l.addWidget(label(
            "AI tools: " + (", ".join(learned) if learned else "none (retrain to learn crop and masks)"),
            "Muted", wrap=True,
        ))
        pending = proj.learning_candidates(meta)
        if pending:
            l.addWidget(label(f"● {len(pending)} finished shoot(s) ready to learn from", "Chip"))
        l.addSpacing(6)
        l.addLayout(hbox(
            button("Learn from new edits", "Primary" if pending else None, slot=lambda: self.learn(meta)),
            button("Details", slot=lambda: self.details(meta)),
            button("Export…", slot=lambda: self.export(meta)),
            button("Delete", "Danger", slot=lambda: self.delete(meta)),
            None,
        ))
        return c

    def details(self, meta):
        d = QDialog(self)
        d.setWindowTitle(meta["name"])
        d.resize(720, 760)
        l = QVBoxLayout(d)
        l.setContentsMargins(24, 20, 24, 20)
        l.addWidget(label(meta["name"], "H1"))
        l.addWidget(label(
            "How close the profile got on shoots it didn't train on, compared with using one fixed "
            "preset for every photo. Lower is better.", "Muted", wrap=True,
        ))
        l.addWidget(MetricsTable(meta.get("metrics", {})), 1)
        tm = meta.get("tool_metrics") or {}
        if tm:
            t = QTableWidget(len(tm), 3)
            t.setHorizontalHeaderLabels(["AI tool", "Virten Studio", "Without AI"])
            t.verticalHeader().hide()
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            for r, (k, m) in enumerate(tm.items()):
                t.setItem(r, 0, QTableWidgetItem(k))
                if "accuracy" in m:
                    t.setItem(r, 1, QTableWidgetItem(f"{m['accuracy']:.0%} right"))
                    t.setItem(r, 2, QTableWidgetItem(f"{m['baseline_accuracy']:.0%} (always the same)"))
                else:
                    unit = m.get("unit", "")
                    scale = 1 if unit else 100
                    t.setItem(r, 1, QTableWidgetItem(f"±{m['mae'] * scale:.2f}{unit}"))
                    t.setItem(r, 2, QTableWidgetItem(f"±{m['baseline_mae'] * scale:.2f}{unit}"))
            l.addWidget(t, 1)
        l.addWidget(label("Catalogs:\n" + "\n".join(meta["catalogs"]), "Muted", wrap=True))
        d.exec()

    def delete(self, meta):
        if QMessageBox.question(self, "Virten Studio", f'Delete the profile "{meta["name"]}"?') == QMessageBox.Yes:
            model.delete_profile(meta["name"])
            self.reload()


class ProjectsPage(Page):
    def __init__(self, main):
        super().__init__("Projects", "+  New Project", self.new_project)
        self.main = main
        self.show_archived = False
        self.tabs = QHBoxLayout()
        self.tabs.setSpacing(6)
        self.active_tab = button("Active", "NavButton", slot=lambda: self.set_tab(False))
        self.archived_tab = button("Archived", "NavButton", slot=lambda: self.set_tab(True))
        for b in (self.active_tab, self.archived_tab):
            b.setCheckable(True)
            self.tabs.addWidget(b)
        self.tabs.addStretch(1)
        self.cull_btn = button("+  New Cull", slot=self.new_cull)
        self.tabs.addWidget(self.cull_btn)
        self.import_btn = button("Import backup…", slot=self.import_backup)
        self.tabs.addWidget(self.import_btn)
        self.layout().insertLayout(1, self.tabs)
        self.reload()

    def set_tab(self, archived):
        self.show_archived = archived
        self.reload()

    def new_project(self, catalog_path=None):
        catalog_path = catalog_path if isinstance(catalog_path, str) else None
        w = NewProjectWizard(self, catalog_path)
        w.exec()
        self.set_tab(False)
        if w.result:
            self.main.open_project(w.result)

    def new_cull(self, *_):
        w = NewCullWizard(self)
        w.exec()
        self.set_tab(False)
        if w.result:
            self.main.open_project(w.result)

    def reload(self):
        clear_layout(self.body)
        archived = proj.archived_projects()
        self.active_tab.setChecked(not self.show_archived)
        self.archived_tab.setChecked(self.show_archived)
        self.archived_tab.setText(f"Archived ({len(archived)})" if archived else "Archived")
        self.import_btn.setVisible(self.show_archived)
        if self.show_archived:
            self.body.addWidget(label(
                f"Archived projects stay here for {proj.ARCHIVE_DAYS} days, then they're removed from "
                "Virten Studio. With sync on, each one is also backed up to your cloud folder.", "Muted", wrap=True,
            ))
            for p in archived:
                self.body.addWidget(self.row(p))
            if not archived:
                self.body.addWidget(label("No archived projects.", "Muted"))
            self.body.addStretch(1)
            return
        projects = proj.load_projects()
        if not projects:
            return self.empty_state(
                "Edit a shoot in minutes",
                "Pick a Lightroom catalog and a profile. Virten Studio predicts your edits, lets you preview "
                "Before / After live, and applies them in Lightroom with one click.",
                "Start a project", self.new_project,
            )
        for p in projects:
            self.body.addWidget(self.row(p))
        self.body.addStretch(1)

    def row(self, p):
        c = QFrame()
        c.setObjectName("Card")
        c.setCursor(Qt.PointingHandCursor)
        c.mouseReleaseEvent = lambda e, p=p: self.main.open_project(p)
        l = QHBoxLayout(c)
        l.setContentsMargins(16, 12, 16, 12)
        l.setSpacing(16)
        thumb = QLabel()
        thumb.setFixedSize(96, 64)
        cover = p.get("cover") or ""
        if cover and os.path.exists(cover):
            thumb.setPixmap(QPixmap(cover).scaled(96, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        thumb.setStyleSheet("background:#0e0f12; border-radius:6px;")
        l.addWidget(thumb)
        info = QVBoxLayout()
        info.addWidget(label(p["name"], "H2"))
        look = f" + {looks.canonical_name(p['look'])}" if p.get("look") else ""
        if p.get("kind") == "cull":
            s = p.get("summary") or {}
            what = (
                f"{p.get('count', 0):,} photos · Assisted cull: {s.get('likely_rejects', 0):,} likely rejects, "
                f"{s.get('bursts', 0):,} bursts, {s.get('best_hints', 0):,} likely best frames"
            )
        else:
            what = f"{p.get('count', 0):,} photos · " + (
                f"{p['profile']}{look}" if p.get("profile") else f"Look only: {p.get('look')}"
            )
        info.addWidget(label(f"{what} · {p['created'][:16].replace('T', ' ')}", "Muted"))
        l.addLayout(info, 1)
        if p.get("archived_at"):
            l.addWidget(label(f"Removed on {proj.removal_date(p):%b %d, %Y}", "Muted"), 0, Qt.AlignVCenter)
            l.addWidget(button("Restore", slot=lambda _=False, pid=p["id"]: self.restore(pid)), 0, Qt.AlignVCenter)
            l.addWidget(button("Delete now", "Danger", slot=lambda _=False, pp=p: self.delete_now(pp)), 0, Qt.AlignVCenter)
        else:
            applied = proj.edits_applied(p)
            if p.get("kind") == "cull":
                state = "Learned from" if p.get("learned") else ("Suggestions in Lightroom" if applied else "Ready to add")
            else:
                state = "Applied in Lightroom" if applied else "Ready to apply"
            l.addWidget(label(state, "ChipDone" if applied else "Chip"), 0, Qt.AlignVCenter)
            l.addWidget(button("Archive", slot=lambda _=False, pid=p["id"]: self.archive(pid)), 0, Qt.AlignVCenter)
        return c

    def archive(self, pid):
        when = proj.mark_archived(pid)
        self.reload()
        if not proj.backup_dir():
            start_worker(self.main, _plain(proj.finish_archive), pid, when)
            self.main.flash("Archived. Turn on sync in Settings to also back projects up to the cloud.")
            return
        self.main.flash("Archived. Backing up to the cloud in the background…", 60000)

        def done(path):
            self.main.flash(
                f"Backed up to {os.path.basename(os.path.dirname(os.path.dirname(path)))} ▸ projects"
                if path else "Archived, but the cloud backup couldn't be written."
            )

        start_worker(
            self.main, _plain(proj.finish_archive), pid, when,
            on_done=done, on_failed=lambda m: self.main.flash(f"Archived, but the backup failed: {m}"),
        )

    def restore(self, pid):
        proj.restore_project(pid)
        self.reload()

    def delete_now(self, p):
        if QMessageBox.question(
            self, "Virten Studio",
            f'Remove "{p["name"]}" from Virten Studio now? Any cloud backup is kept, and your catalog isn\'t touched.',
        ) == QMessageBox.Yes:
            proj.delete_project(p["id"])
            self.reload()

    def import_backup(self, *_):
        start = proj.backup_dir() or ""
        f, _ = QFileDialog.getOpenFileName(self, "Import project backup", start, "Virten Studio project backup (*.zip)")
        if not f:
            return
        try:
            p = proj.import_backup(f)
        except Exception as e:
            QMessageBox.critical(self, "Virten Studio", f"Couldn't import that backup:\n{e}")
            return
        self.main.flash(f"Imported “{p['name']}” into Archived.")
        self.reload()


class LooksPage(Page):
    def __init__(self, main):
        super().__init__("Looks", "+  Import Lightroom preset…", self.import_preset)
        self.main = main
        self.reload()

    def reload(self):
        clear_layout(self.body)
        self.body.addWidget(label(
            "A Look adds a stylistic grade on top of your personal profile: your profile sets exposure and white "
            "balance per photo, while the Look adds the tone curve, color grade, grain and vignette.",
            "Muted", wrap=True,
        ))
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, lk in enumerate(looks.list_looks()):
            grid.addWidget(self.card(lk), i // 2, i % 2)
        self.body.addLayout(grid)
        self.body.addStretch(1)

    def card(self, lk):
        c = QFrame()
        c.setObjectName("Card")
        l = QVBoxLayout(c)
        l.setContentsMargins(20, 16, 20, 14)
        l.setSpacing(6)
        thumb = QLabel()
        thumb.setFixedSize(*_LOOK_THUMB)
        thumb.setPixmap(look_preview_pixmap(lk))
        thumb.setStyleSheet("border-radius: 6px;")
        text = QVBoxLayout()
        text.setSpacing(6)
        text.addLayout(hbox(label(lk["name"], "H2"), None, label("Built-in" if lk["builtin"] else "Imported", "Chip")))
        text.addWidget(label(lk.get("description", ""), "Muted", wrap=True))
        l.addLayout(hbox(thumb, text, spacing=14))
        parts = []
        s, o = lk.get("set", {}), lk.get("offset", {})
        if any(k.startswith("ToneCurve") for k in s):
            parts.append("tone curve")
        if any(k.startswith(("SplitToning", "ColorGrade")) for k in s):
            parts.append("color grading")
        if any("Adjustment" in k for k in s):
            parts.append("color mixer")
        if s.get("ConvertToGrayscale"):
            parts.append("black & white")
        if s.get("GrainAmount"):
            parts.append("grain")
        if s.get("PostCropVignetteAmount"):
            parts.append("vignette")
        if o:
            parts.append("tone shifts")
        if parts:
            l.addWidget(label("Includes " + ", ".join(parts), "Muted", wrap=True))
        if not lk["builtin"]:
            l.addLayout(hbox(button("Delete", "Danger", slot=lambda: self.delete(lk)), None))
        return c

    def import_preset(self, *_):
        start = camera_raw_presets_dir()
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import Lightroom presets", start if os.path.isdir(start) else "",
            "Lightroom develop preset (*.xmp)",
        )
        done, errors = [], []
        for f in files:
            try:
                done.append(looks.import_preset(f)["name"])
            except Exception as e:
                errors.append(f"{os.path.basename(f)}: {e}")
        if done or errors:
            QMessageBox.information(
                self, "Virten Studio",
                (f"Imported {len(done)} look(s)." if done else "")
                + ("\n\nSkipped:\n" + "\n".join(errors) if errors else ""),
            )
        self.reload()

    def delete(self, lk):
        if QMessageBox.question(self, "Virten Studio", f'Delete the look "{lk["name"]}"?') == QMessageBox.Yes:
            looks.delete_user_look(lk)
            self.reload()


class SettingsPage(Page):
    def __init__(self, main):
        super().__init__("Settings")
        self.main = main
        self.reload()

    def section(self, title, text):
        box = QFrame()
        box.setObjectName("Card")
        l = QVBoxLayout(box)
        l.setContentsMargins(20, 16, 20, 16)
        l.setSpacing(8)
        l.addWidget(label(title, "H2"))
        if text:
            l.addWidget(label(text, "Muted", wrap=True))
        self.body.addWidget(box)
        return l

    def reload(self):
        clear_layout(self.body)
        d = sync.sync_dir()
        l = self.section(
            "Sync between computers",
            "Keep your profiles and imported Looks in a cloud folder (Google Drive or OneDrive). "
            "Whenever you train or update a profile it's copied there automatically.",
        )
        l.addWidget(label(f"Syncing with:  {d}" if d else "Sync is off.", None, wrap=True))
        row = []
        for name, path in sync.cloud_folders():
            if d != path:
                row.append(button(
                    f"Switch to {name}" if d else f"Use {name}",
                    "Primary" if not row and not d else None,
                    slot=lambda _=False, p=path: self.set_dir(p),
                ))
        row.append(button("Choose folder…", slot=self.choose))
        if d:
            row += [button("Sync now", slot=self.sync_now), button("Turn off", slot=lambda: self.set_dir(None))]
        self.sync_status = label("", "Muted")
        l.addLayout(hbox(*row, self.sync_status, None))

        l = self.section(
            "Lightroom plugin",
            "The plugin applies a project's edits inside Lightroom Classic "
            "(Library ▸ Plug-in Extras ▸ Apply Virten Studio Edits…).",
        )
        l.addLayout(hbox(
            label("Installed ✓" if plugin_installed() else "Not installed"),
            button("Reinstall" if plugin_installed() else "Install", slot=self.install),
            None,
        ))

        l = self.section(
            "Updates",
            "New versions come from your sync folder and from the project's GitHub Releases (a .exe for Windows, a "
            ".dmg for Mac). A private repository needs a read-only access token.",
        )
        self.repo_edit = QLineEdit(prefs.load().get("github_repo") or "")
        self.repo_edit.setPlaceholderText(sync.github_repo())
        self.token_edit = QLineEdit(prefs.load().get("github_token") or "")
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("Only for a private repository")
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.addWidget(label("GitHub repository", "Muted"), 0, 0)
        form.addWidget(self.repo_edit, 0, 1)
        form.addWidget(label("Access token", "Muted"), 1, 0)
        form.addWidget(self.token_edit, 1, 1)
        form.setColumnStretch(1, 1)
        l.addLayout(form)
        self.auto_update = QCheckBox("Check for updates automatically at startup")
        self.auto_update.setChecked(auto_update_check())
        self.auto_update.setToolTip("When off, Virten Studio contacts GitHub only when you click Check for updates.")
        self.auto_update.toggled.connect(lambda on: prefs.save(auto_update_check=bool(on)))
        l.addWidget(self.auto_update)
        self.update_status = label("", "Muted")
        l.addLayout(hbox(button("Save", slot=self.save_update_source),
                         button("Check for updates", slot=self.check_updates), self.update_status, None))

        upd = getattr(self.main, "_update", None)
        try:
            from . import vision
            device = vision.accelerator()[1]
        except Exception:
            device = "CPU"
        l = self.section(
            "Version & Diagnostics",
            f"Virten Studio {__version__}\nScene AI runs on: {device}  ·  Photo analysis uses "
            f"{features.worker_count()} parallel workers on this computer's CPU",
        )
        if upd:
            l.addLayout(hbox(
                label(f"Version {upd[0]} is available."),
                button("Install update", "Primary", slot=self.main.install_update),
                None,
            ))
        l.addLayout(hbox(
            button("Open data folder", slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir()))),
            button("Open diagnostic log", slot=self.open_log),
            button("Clean up orphaned cache files", slot=self.clean_cache),
            None,
        ))

        l = self.section("Support Virten Studio", "Free, local-first, no tracking. If it saves you time:")
        l.addLayout(hbox(button("☕  Buy Me a Coffee", "Primary", slot=lambda: support.open_support_page()), None))

        l = self.section("About & Open-Source Licenses", None)
        l.addWidget(label(f"Virten Studio {__version__} — {APP_TAGLINE}", "H2", wrap=True))
        for text in (TRADEMARK_NOTICE, PRIVACY_NOTE, OPEN_SOURCE_NOTE):
            l.addWidget(label(text, "LegalText", wrap=True))
        l.addLayout(hbox(
            button("License (EULA)", slot=lambda: self.show_text_file("LICENSE.txt", "Virten Studio License")),
            button("Third-Party Notices", slot=lambda: self.show_text_file("THIRD-PARTY-NOTICES.txt",
                                                                          "Open-Source Licenses")),
            button("Open licenses folder", slot=lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.join(resource_dir(), "licenses")))),
            None,
        ))
        self.body.addStretch(1)

    def show_text_file(self, name, title):
        """Read-only viewer for a bundled text file (the EULA or the third-party notices)."""
        path = os.path.join(resource_dir(), name)
        try:
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
        except OSError:
            QMessageBox.warning(self, "Virten Studio", f"{name} wasn't found next to the app ({path}).")
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{title} — Virten Studio {__version__}")
        dlg.resize(820, 640)
        v = QVBoxLayout(dlg)
        view = QPlainTextEdit(text)
        view.setObjectName("LicenseView")
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        v.addWidget(view, 1)
        v.addLayout(hbox(None, button("Close", "Primary", slot=dlg.accept)))
        dlg.viewer = view
        dlg.open()
        return dlg

    def save_update_source(self):
        repo = self.repo_edit.text().strip().removeprefix("https://github.com/").strip("/").removesuffix(".git")
        if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            self.update_status.setText("Use the form owner/repository, e.g. angelitojusay/virten-studio.")
            return
        prefs.save(github_repo=repo, github_token=self.token_edit.text().strip())
        self.repo_edit.setText(repo)
        self.update_status.setText("Saved.")

    def check_updates(self):
        self.save_update_source()
        self.update_status.setText("Checking…")
        sync.github_latest_release(force=True)  # fresh answer, not the 15-minute cache

        def done(upd):
            self.update_status.setText(f"Version {upd[0]} is available: use the Update button on the left."
                                       if upd else f"Virten Studio {__version__} is up to date.")
        self.main.check_update(on_done=done)

    def clean_cache(self):
        btn = self.sender() if isinstance(self.sender(), QPushButton) else None
        if btn:
            btn.setEnabled(False)

        def done(res):
            if btn:
                btn.setEnabled(True)
            mb = res.get("bytes_freed", 0) / (1024 * 1024)
            self.main.flash(f"Cleaned up {res.get('thumbs_removed', 0):,} orphaned thumbnail(s), {mb:.1f} MB freed, "
                            "and compacted the analysis caches.")

        def failed(msg):
            if btn:
                btn.setEnabled(True)
            self.main.flash(f"Cache clean-up failed: {msg}")

        self.main.flash("Cleaning up the cache…", 60000)
        start_worker(self, _plain(features.prune_caches), on_done=done, on_failed=failed)

    def open_log(self):
        path = log_file()
        if not os.path.exists(path):
            QMessageBox.information(self, "Virten Studio", "No diagnostic log yet: it's created the next time Virten "
                                                           "Studio starts.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def set_dir(self, path):
        if path:
            os.makedirs(path, exist_ok=True)
        sync.set_sync_dir(path)
        self.reload()
        if path:
            self.sync_now()

    def choose(self):
        start = next((p for _, p in sync.cloud_folders()), "")
        d = QFileDialog.getExistingDirectory(self, "Choose a cloud-synced folder", start)
        if d:
            self.set_dir(os.path.normpath(d))

    def sync_now(self):
        self.sync_status.setText("Syncing…")
        self.main.run_sync(lambda changed: self.sync_status.setText(
            f"Up to date. {len(changed)} profile(s) updated from the cloud." if changed else "Up to date."
        ))

    def install(self):
        install_plugin(self)
        self.main.update_plugin_status()
        self.reload()


# ---------------------------------------------------------------- Pro 3-Pane Project Studio

class AccordionSection(QFrame):
    """Lightroom-style collapsible right-panel section: a dark header bar (title on the left, ▼ open / ◀ closed on
    the right) over its content."""

    def __init__(self, title, open_=True):
        super().__init__()
        self.setObjectName("AccSection")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = QPushButton()
        self.header.setObjectName("AccHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setFixedHeight(28)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(10, 0, 10, 0)
        self.title_lbl = label(title, "AccTitle")
        self.arrow = label("", "AccArrow")
        hl.addWidget(self.title_lbl)
        hl.addStretch(1)
        hl.addWidget(self.arrow)
        self.header.clicked.connect(self.toggle)
        v.addWidget(self.header)
        self.body = QWidget()
        self.body.setObjectName("AccBody")
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(10, 8, 10, 10)
        self.content.setSpacing(5)
        v.addWidget(self.body)
        self.set_open(open_)

    def set_title(self, text):
        self.title_lbl.setText(text)

    def set_open(self, on):
        self.body.setVisible(bool(on))
        self.arrow.setText("▼" if on else "◀")

    def is_open(self):
        return not self.body.isHidden()

    def toggle(self):
        self.set_open(not self.is_open())


def _joined_buttons(texts, name="StepBtn", checkable=False):
    """A row of buttons drawn as one joined control (only the outer corners rounded)."""
    box = QFrame()
    box.setObjectName("Joined")
    bl = QHBoxLayout(box)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(0)
    out = []
    for i, text in enumerate(texts):
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.setProperty("edge", "first" if i == 0 else ("last" if i == len(texts) - 1 else "mid"))
        b.setCheckable(checkable)
        bl.addWidget(b)
        out.append(b)
    return box, out


class StepperRow(QWidget):
    """Quick Develop row: slider name, the target photo's live value, and a joined [ ◀◀ | ◀ | ▶ | ▶▶ ] stepper
    (big step down, small step down, small step up, big step up)."""

    GLYPHS = ("◀◀", "◀", "▶", "▶▶")

    def __init__(self, title, key, steps, on_step):
        super().__init__()
        self.key, self.steps = key, steps
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.name = label(title, "QDLabel")
        self.name.setMinimumWidth(70)
        self.value = label("—", "QDValue")
        self.value.setFixedWidth(56)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.name, 1)
        h.addWidget(self.value)
        box, self.buttons = _joined_buttons(self.GLYPHS)
        for b, step in zip(self.buttons, steps):
            b.setFixedSize(30, 22)
            b.setToolTip(f"{title} {self.fmt(step, signed=True)}")
            b.clicked.connect(lambda _=False, s=step: on_step({key: s}))
        h.addWidget(box)

    def fmt(self, v, signed=False):
        if v is None:
            return "—"
        if self.key == "Exposure2012":
            return f"{float(v):+.2f}" + (" EV" if signed else "")
        if self.key == "Temperature":
            return f"{int(round(v)):+d} K" if signed else f"{int(round(v))} K"
        return f"{int(round(v)):+d}"

    def set_value(self, v):
        self.value.setText(self.fmt(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else "—")


class FilmstripDelegate(QStyledItemDelegate):
    """Filmstrip cell: the thumbnail with its sequence number in a small badge on the top-left corner."""

    def paint(self, p, opt, idx):
        super().paint(p, opt, idx)
        n = idx.data(Qt.UserRole)
        if n is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        f = p.font()
        f.setPointSizeF(_pt(7.5))
        f.setBold(True)
        p.setFont(f)
        text = str(n)
        r = QRectF(opt.rect.left() + 5, opt.rect.top() + 4, p.fontMetrics().horizontalAdvance(text) + 10, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 175))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignCenter, text)
        p.restore()


def exif_line(exif):
    """'ISO 800   55 mm   f / 2.8   1/200 sec' from a result's exif (blank parts left out)."""
    e = exif or {}
    parts = []
    if e.get("iso"):
        parts.append(f"ISO {int(round(e['iso']))}")
    if e.get("focal"):
        parts.append(f"{int(round(e['focal']))} mm")
    if e.get("aperture"):
        parts.append(f"f / {e['aperture']:g}")
    t = e.get("shutter")
    if t:
        parts.append(f"1/{int(round(1 / t))} sec" if t < 0.4 else f"{t:.1f} sec")
    return "   ".join(parts) if parts else "No shooting info in the catalog"


def cull_badge(r):
    """Short grid badge for a cull result: best frame, likely reject reasons, or nothing."""
    if r.get("best"):
        return "◆ Best"
    if r.get("reasons"):
        return "✗ " + ", ".join(cull.REASONS[k] for k in r["reasons"])
    if r.get("timelapse"):
        return "⏱ Timelapse"
    return ""


QD_TONE = (("Exposure", "Exposure2012", (-0.33, -0.10, 0.10, 0.33)),
           ("Contrast", "Contrast2012", (-15, -5, 5, 15)), ("Highlights", "Highlights2012", (-15, -5, 5, 15)),
           ("Shadows", "Shadows2012", (-15, -5, 5, 15)), ("Whites", "Whites2012", (-15, -5, 5, 15)),
           ("Blacks", "Blacks2012", (-15, -5, 5, 15)), ("Clarity", "Clarity2012", (-15, -5, 5, 15)),
           ("Vibrance", "Vibrance", (-15, -5, 5, 15)), ("Saturation", "Saturation", (-15, -5, 5, 15)))
QD_WB = (("Temperature", "Temperature", (-250, -75, 75, 250)), ("Tint", "Tint", (-15, -5, 5, 15)))
THUMB_MIN, THUMB_MAX, THUMB_DEFAULT = 100, 340, 160
WORKSPACES = ("grid", "loupe", "split")


class ProjectDetail(QWidget):
    """A project in a Lightroom Classic-style workspace: thumbnail grid and Before/After loupe (three view modes),
    a bottom filmstrip, and a right-hand panel with the histogram and Quick Develop / Develop / Metadata sections."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("Page")
        self.project = None
        self.view = []
        self._syncing = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 12, 8, 8)  # tight edges, like Lightroom: the 1150 px window still fits
        outer.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        top_bar.addWidget(button("‹ Projects", slot=lambda: main.nav(0)))
        self.title = ElidedLabel("", "H1")  # long names shorten with "…" instead of widening the window
        top_bar.addSpacing(4)
        top_bar.addWidget(self.title, 1)
        self.plugin_btn = button("Install Plugin", "Primary", self.install)
        self.plugin_btn.setToolTip("Install the Lightroom Classic plugin that applies the edits")
        self.teach_btn = button("✦ Learn Tweaks…", "AccentOutline", self.teach)
        self.show_file_btn = button("Show File", slot=self.show_file)
        self.show_file_btn.setToolTip("Show this project's .virten edits file in Explorer / Finder")
        self.archive_btn = button("Archive", slot=self.toggle_archive)
        self.delete_btn = button("Delete", "Danger", self.delete)
        for b in (self.plugin_btn, self.teach_btn, self.show_file_btn, self.archive_btn, self.delete_btn):
            top_bar.addWidget(b)
        outer.addLayout(top_bar)

        self.meta = ElidedLabel("", "Muted", Qt.ElideMiddle)  # catalog paths shorten in the middle
        outer.addWidget(self.meta)

        banner = QFrame()
        banner.setObjectName("Banner")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 8, 16, 8)
        bl_text = QVBoxLayout()
        bl_text.setSpacing(2)
        self.banner_title = label("", "H2")
        self.banner_text = label("", "Muted", wrap=True)
        bl_text.addWidget(self.banner_title)
        bl_text.addWidget(self.banner_text)
        bl.addLayout(bl_text, 1)
        outer.addWidget(banner)

        # ---- center workspace: grid | loupe | right panel, freely resizable
        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.setObjectName("MainSplit")
        self.main_split.setHandleWidth(6)
        self.main_split.setChildrenCollapsible(False)

        self.grid = QListWidget()
        self.grid.setObjectName("Grid")
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideMiddle)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.currentRowChanged.connect(self.show_settings)
        self.grid.currentRowChanged.connect(lambda _: self._sync_from(self.grid))
        self.grid.itemSelectionChanged.connect(lambda: self._sync_from(self.grid))
        self.grid_pane = QWidget()
        self.grid_pane.setMinimumWidth(220)
        gl = QVBoxLayout(self.grid_pane)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(self.grid, 1)
        self.main_split.addWidget(self.grid_pane)

        self.center_pane = QWidget()
        self.center_pane.setMinimumWidth(340)
        cl = QVBoxLayout(self.center_pane)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        self.loupe = BeforeAfterView()
        self.loupe.photo_ready.connect(self._loupe_changed)
        cl.addWidget(self.loupe, 1)
        cl.addWidget(self._build_cull_strip())
        self.main_split.addWidget(self.center_pane)

        self.right_pane = self._build_right_panel()
        self.main_split.addWidget(self.right_pane)
        for i, stretch in enumerate((1, 2, 0)):
            self.main_split.setStretchFactor(i, stretch)
        self.main_split.setSizes([380, 520, 340])
        outer.addWidget(self.main_split, 1)

        outer.addWidget(self._build_filmstrip())

        # Lightroom-style shortcuts. \ flips Before/After, S = split loupe, O = mask overlay; G = grid, E / D = loupe
        # with filmstrip; F6 = filmstrip; Tab (here) or F5 (anywhere) = left navigation panel.
        self.shortcuts = []
        for keys, slot in (("\\", self.toggle_before_after), ("S", lambda: self.set_view_mode("split")),
                           ("O", self.toggle_overlay), ("G", lambda: self.set_workspace("grid")),
                           ("E", lambda: self.set_workspace("loupe")), ("D", lambda: self.set_workspace("loupe")),
                           ("F6", self.toggle_filmstrip), ("Tab", lambda: self.main.toggle_sidebar())):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self.shortcuts.append(sc)

        self._pending = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load_some)
        self._suppress_tune = False
        saved = prefs.load()
        self._strip_on = {"grid": False, "loupe": True, "split": False}
        self.thumb_slider.setValue(int(saved.get("thumb_size") or THUMB_DEFAULT))
        self.set_thumb_size(self.thumb_slider.value())
        self.set_workspace(saved.get("workspace") if saved.get("workspace") in WORKSPACES else "split", save=False)

    # ------------------------------------------------ bottom filmstrip + its info bar
    def _build_filmstrip(self):
        self.filmstrip_panel = QFrame()
        self.filmstrip_panel.setObjectName("FilmstripPanel")
        v = QVBoxLayout(self.filmstrip_panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("FilmInfoBar")
        bar.setFixedHeight(26)
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(6, 2, 6, 2)
        hb.setSpacing(4)
        self.ws_group = QButtonGroup(self)
        self.ws_buttons = {}
        for key, text, tip in (("grid", "▦ Grid", "Grid only (G)"), ("loupe", "▣ Loupe", "Loupe + filmstrip (E)"),
                               ("split", "◫ Split", "Grid and loupe side by side")):
            b = button(text, "BarBtn", slot=lambda _=False, k=key: self.set_workspace(k))
            b.setCheckable(True)
            b.setToolTip(tip)
            self.ws_group.addButton(b)
            self.ws_buttons[key] = b
            hb.addWidget(b)
        hb.addSpacing(6)
        hb.addWidget(button("Select All", "BarBtn", slot=self.grid.selectAll))
        hb.addWidget(button("Select None", "BarBtn", slot=self.grid.clearSelection))
        hb.addSpacing(6)
        self.sel_label = ElidedLabel("", "Crumb")  # "N photos / M selected / #idx · filename"
        hb.addWidget(self.sel_label, 1)

        self.thumb_box = QWidget()
        tl = QHBoxLayout(self.thumb_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        tl.addWidget(label("Thumb Size", "Crumb"))
        self.thumb_slider = QSlider(Qt.Horizontal)
        self.thumb_slider.setRange(THUMB_MIN, THUMB_MAX)
        self.thumb_slider.setSingleStep(10)
        self.thumb_slider.setPageStep(40)
        self.thumb_slider.setFixedWidth(110)
        self.thumb_slider.setToolTip("Grid thumbnail size")
        self.thumb_slider.valueChanged.connect(self.set_thumb_size)
        self.thumb_slider.sliderReleased.connect(lambda: prefs.save(thumb_size=self.thumb_slider.value()))
        tl.addWidget(self.thumb_slider)
        hb.addWidget(self.thumb_box)

        self.loupe_tools = QWidget()
        ll = QHBoxLayout(self.loupe_tools)
        ll.setContentsMargins(8, 0, 0, 0)
        ll.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        box, pills = _joined_buttons(["Before", "Split", "After", "Mask (O)"], "PillBtn", checkable=True)
        self.mode_buttons = dict(zip(("before", "split", "after"), pills[:3]))
        for (mk, b), tip in zip(self.mode_buttons.items(), ("Shortcut: \\", "Shortcut: S", "Shortcut: \\")):
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=mk: self.set_view_mode(m))
            self.mode_group.addButton(b)
        self.mode_buttons["split"].setChecked(True)
        self.overlay_btn = pills[3]
        self.overlay_btn.setToolTip("Ruby overlay of the AI masks this photo's corrections use (else the subject). "
                                    "The masks are simulated for the preview; Lightroom computes its own.")
        self.overlay_btn.clicked.connect(lambda: self.loupe.set_overlay(self.overlay_btn.isChecked()))
        ll.addWidget(box)
        hb.addWidget(self.loupe_tools)
        self.strip_toggle = button("▼", "BarBtn", slot=self.toggle_filmstrip)
        self.strip_toggle.setToolTip("Show / hide the filmstrip (F6)")
        hb.addSpacing(4)
        hb.addWidget(self.strip_toggle)
        v.addWidget(bar)

        self.filmstrip = QListWidget()
        self.filmstrip.setObjectName("Filmstrip")
        self.filmstrip.setViewMode(QListWidget.IconMode)
        self.filmstrip.setFlow(QListWidget.LeftToRight)
        self.filmstrip.setWrapping(False)
        self.filmstrip.setMovement(QListWidget.Static)
        self.filmstrip.setUniformItemSizes(True)
        self.filmstrip.setIconSize(QSize(88, 88))  # square cells: portrait and landscape frames keep their shape
        self.filmstrip.setGridSize(QSize(96, 96))
        self.filmstrip.setFixedHeight(118)
        self.filmstrip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filmstrip.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.filmstrip.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.filmstrip.setItemDelegate(FilmstripDelegate(self.filmstrip))
        self.filmstrip.currentRowChanged.connect(lambda _: self._sync_from(self.filmstrip))
        self.filmstrip.itemSelectionChanged.connect(lambda: self._sync_from(self.filmstrip))
        v.addWidget(self.filmstrip)
        return self.filmstrip_panel

    def set_workspace(self, mode, save=True):
        """Grid only (G), Loupe + filmstrip (E) or Split grid + loupe."""
        self.workspace = mode
        grid_on, loupe_on = mode in ("grid", "split"), mode in ("loupe", "split")
        self.grid_pane.setVisible(grid_on)
        self.center_pane.setVisible(loupe_on)
        self.thumb_box.setVisible(grid_on)
        self.loupe_tools.setVisible(loupe_on)
        self._show_strip(self._strip_on[mode])
        self.ws_buttons[mode].setChecked(True)
        row = self.grid.currentRow()
        if row >= 0:
            self.grid.scrollToItem(self.grid.item(row))
        if save:
            prefs.save(workspace=mode)

    def toggle_filmstrip(self):
        self._strip_on[self.workspace] = self.filmstrip.isHidden()
        self._show_strip(self._strip_on[self.workspace])

    def _show_strip(self, on):
        self.filmstrip.setVisible(on)
        self.strip_toggle.setText("▼" if on else "▲")
        row = self.filmstrip.currentRow()
        if on and row >= 0:
            self.filmstrip.scrollToItem(self.filmstrip.item(row))

    def _cell_size(self, s):
        """Grid cell for s px square thumbnails (one caption line; cull projects have a second, for the badge)."""
        extra = 16 if (self.project or {}).get("kind") == "cull" else 0
        return QSize(s + 24, s + 34 + extra)

    def set_thumb_size(self, s):
        """Square thumbnails (the photo at its own aspect ratio on a matte), so portrait and landscape frames scale
        alike without distortion."""
        self.grid.setIconSize(QSize(s, s))
        cell = self._cell_size(s)
        self.grid.setGridSize(cell)
        for i in range(self.grid.count()):
            self.grid.item(i).setSizeHint(cell - QSize(6, 4))

    def _sync_from(self, src):
        """Mirrors the current photo and selection between the grid and the filmstrip (both ways, no loops)."""
        if not self._syncing:
            dst = self.filmstrip if src is self.grid else self.grid
            self._syncing = True
            try:
                cur = src.currentRow()
                if cur >= 0 and dst.currentRow() != cur and cur < dst.count():
                    dst.setCurrentRow(cur, QItemSelectionModel.NoUpdate)
                sel = QItemSelection()
                for ix in src.selectionModel().selectedIndexes():
                    if ix.row() < dst.count():
                        d = dst.model().index(ix.row(), 0)
                        sel.select(d, d)
                dst.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect)
                if 0 <= cur < dst.count():
                    dst.scrollToItem(dst.item(cur))
            finally:
                self._syncing = False
        self._selection_changed()

    # ------------------------------------------------ right panel: histogram + accordion
    def _build_right_panel(self):
        pane = QWidget()
        pane.setObjectName("RightPanel")
        pane.setAttribute(Qt.WA_StyledBackground, True)  # paint our dark background, never the system grey
        pane.setMinimumWidth(330)
        pane.setMaximumWidth(350)
        rl = QVBoxLayout(pane)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.hist_widget = HistogramWidget()
        rl.addWidget(self.hist_widget)
        self.exif_strip = label("", "ExifStrip")
        self.exif_strip.setAlignment(Qt.AlignCenter)
        rl.addWidget(self.exif_strip)
        rl.addSpacing(6)
        self.accordion = QScrollArea()
        self.accordion.setObjectName("Accordion")
        self.accordion.setWidgetResizable(True)
        self.accordion.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("InspectorInner")
        acc = QVBoxLayout(inner)
        acc.setContentsMargins(0, 0, 4, 0)
        acc.setSpacing(2)
        self.qd_section = self._build_quick_develop()
        self.dev_section = AccordionSection("Develop Sliders & AI Masks")
        self.inspector = DevelopInspector(scroll=False)
        self.dev_section.content.addWidget(self.inspector)
        self.meta_section = AccordionSection("Metadata")
        self.meta_rows = {}
        mg = QGridLayout()
        mg.setHorizontalSpacing(10)
        mg.setVerticalSpacing(4)
        for i, key in enumerate(("Photo #", "File Name", "Folder", "Capture Date", "Dimensions", "Camera")):
            k = label(key, "MetaKey")
            k.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val = ElidedLabel("", "MetaVal", Qt.ElideMiddle)
            mg.addWidget(k, i, 0)
            mg.addWidget(val, i, 1)
            self.meta_rows[key] = val
        mg.setColumnStretch(1, 1)
        self.meta_section.content.addLayout(mg)
        for s in (self.qd_section, self.dev_section, self.meta_section):
            acc.addWidget(s)
        acc.addStretch(1)
        self.accordion.setWidget(inner)
        rl.addWidget(self.accordion, 1)
        return pane

    def _build_quick_develop(self):
        sec = AccordionSection("Quick Develop")
        c = sec.content
        box, (self.scope_one, self.scope_sel, self.scope_all) = _joined_buttons(
            ["Target Photo", "Selected (0)", "All Photos"], "ScopeBtn", checkable=True)
        self.scope_group = QButtonGroup(self)
        for b, tip in zip((self.scope_one, self.scope_sel, self.scope_all),
                          ("Only the photo in the loupe", "The photos selected in the grid / filmstrip",
                           "Every photo in this project")):
            b.setToolTip(tip)
            self.scope_group.addButton(b)
        self.scope_sel.setChecked(True)
        c.addWidget(box)

        self.live_look = QComboBox()
        self.live_look.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.live_look.setMinimumContentsLength(12)
        self.live_look.currentIndexChanged.connect(self.on_live_tune_changed)
        self.live_look_str = StrengthSlider(100, maximum=150)
        self.live_look_str.slider.valueChanged.connect(self.on_live_tune_changed)
        self.live_bias = QDoubleSpinBox()
        self.live_bias.setRange(-2.0, 2.0)
        self.live_bias.setSingleStep(0.05)
        self.live_bias.setDecimals(2)
        self.live_bias.setSuffix(" EV")
        self.live_bias.setToolTip("Exposure bias for the whole project")
        self.live_bias.valueChanged.connect(self.on_live_tune_changed)
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        for i, (text, w) in enumerate((("Look", self.live_look), ("Strength", self.live_look_str),
                                       ("Bias", self.live_bias))):
            form.addWidget(label(text, "QDLabel"), i, 0)
            form.addWidget(w, i, 1)
        form.setColumnStretch(1, 1)
        c.addLayout(form)
        self.tune_note = ElidedLabel("", "ChipWarn")  # shrinks instead of widening the window
        self.tune_note.hide()
        c.addWidget(self.tune_note)
        self.reexport_btn = button("Apply Look && Update .virten File", "Primary", self.apply_live_reexport)
        self.reexport_btn.setEnabled(False)
        c.addWidget(self.reexport_btn)

        self.qd_rows, self.qd_buttons = [], []
        for title, rows in (("WHITE BALANCE", QD_WB), ("TONE CONTROL", QD_TONE)):
            c.addWidget(label(title, "SubHeader"))
            for name, key, steps in rows:
                row = StepperRow(name, key, steps, self.quick_nudge)
                self.qd_rows.append(row)
                self.qd_buttons += row.buttons
                c.addWidget(row)
        self.reset_btn = button("Reset All", "Nudge", slot=lambda: self.quick_nudge(None, reset=True))
        self.reset_btn.setToolTip("Back to Virten Studio's own prediction for the target photos")
        self.qd_buttons.append(self.reset_btn)
        c.addLayout(hbox(None, self.reset_btn))
        return sec

    def _update_readouts(self, s):
        for row in self.qd_rows:
            row.set_value((s or {}).get(row.key))

    def _update_info(self, row):
        """EXIF strip and the Metadata section for the photo in the loupe."""
        res = (self.project or {}).get("results") or []
        if not 0 <= row < len(self.view):
            self.exif_strip.setText("")
            for v in self.meta_rows.values():
                v.setText("")
            return
        r = res[self.view[row]]
        exif = r.get("exif")
        self.exif_strip.setText(exif_line(exif) if exif is not None else "Reading shooting info…")
        cap = r.get("capture") or ""
        try:
            cap = datetime.datetime.fromisoformat(cap[:19]).strftime("%b %d, %Y  %I:%M:%S %p") if cap else "—"
        except ValueError:
            pass
        dims = r.get("dims") or (0, 0)
        vals = {"Photo #": f"{self.view[row] + 1} of {len(res)}", "File Name": os.path.basename(r["path"]),
                "Folder": os.path.dirname(r["path"]), "Capture Date": cap,
                "Dimensions": f"{int(dims[0])} × {int(dims[1])}" if dims and dims[0] else "—",
                "Camera": (exif or {}).get("camera") or "—"}
        for k, v in vals.items():
            self.meta_rows[k].setText(v)

    def _fetch_exif(self, p):
        """Projects from before 1.6 didn't save shooting info: read it from the catalog in the background, once."""
        res = p.get("results") or []
        if not res or all("exif" in r for r in res) or not os.path.exists(p.get("catalog") or ""):
            return
        start_worker(self, _plain(proj.exif_for_results), p["catalog"], res,
                     on_done=lambda found, pid=p["id"]: self._exif_loaded(pid, found),
                     on_failed=lambda m: print("couldn't read shooting info:", m))

    def _exif_loaded(self, pid, found):
        fresh = proj.load_project(pid)
        for p in (fresh, self.project if (self.project or {}).get("id") == pid else None):
            for r in (p or {}).get("results") or []:
                if r["path"] in found:
                    r["exif"], cap = found[r["path"]]
                    r.setdefault("capture", cap)
                else:
                    r.setdefault("exif", {})
        if fresh:
            proj.upsert_project(fresh)
        if (self.project or {}).get("id") == pid:
            self._update_info(self.grid.currentRow())

    def set_view_mode(self, mode):
        self.loupe.set_mode(mode)
        self.mode_buttons[mode].setChecked(True)

    # ------------------------------------------------ Assisted cull: burst survey + 1:1 faces
    _faces_loaded = Signal(str, object)

    def _build_cull_strip(self):
        self.cull_strip = QFrame()
        self.cull_strip.setObjectName("Card")
        cs = QHBoxLayout(self.cull_strip)
        cs.setContentsMargins(10, 6, 10, 6)
        cs.setSpacing(12)

        def scroller():
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setMinimumWidth(80)
            inner = QWidget()
            row = QHBoxLayout(inner)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            sc.setWidget(inner)
            return sc, row

        box = QVBoxLayout()
        self.burst_title = label("BURST", "SectionHeader")
        box.addWidget(self.burst_title)
        self.burst_scroll, self.burst_row = scroller()
        self.burst_scroll.setFixedHeight(176)
        box.addWidget(self.burst_scroll)
        cs.addLayout(box, 3)
        box = QVBoxLayout()
        self.faces_title = label("1:1 FACES & EYES", "SectionHeader")
        self.faces_title.setToolTip("Close-ups around the eyes from the camera's full-size preview (100 % when the "
                                    "eyes fit), to check blinks and focus")
        box.addWidget(self.faces_title)
        self.faces_scroll, self.faces_row = scroller()
        self.faces_scroll.setFixedHeight(176)
        box.addWidget(self.faces_scroll)
        cs.addLayout(box, 2)
        self.cull_strip.hide()
        self._face_current = None
        self._faces_loaded.connect(self._on_faces)
        return self.cull_strip

    def _update_cull_strip(self, r):
        clear_layout(self.burst_row)
        results = self.project.get("results") or []
        g = r.get("group") or 0
        if g > 0:
            members = [i for i, x in enumerate(results) if x.get("group") == g]
            self.burst_title.setText(f"BURST {g} · {len(members)} FRAMES")
            for i in members:
                self.burst_row.addWidget(self._burst_card(i, results[i], results[i] is r))
        else:
            self.burst_title.setText("BURST")
            self.burst_row.addWidget(label("Not part of a burst", "Muted"))
        self.burst_row.addStretch(1)
        path = r["path"]
        self._face_current = path
        hit = _cached_faces(path)
        if hit is not None:
            self._show_faces(hit)
            return
        clear_layout(self.faces_row)
        self.faces_row.addWidget(label("Finding faces…", "Muted"))
        self.faces_row.addStretch(1)
        if os.path.exists(path):
            fut = _FACE_POOL.submit(_extract_faces, path)
            fut.add_done_callback(lambda f, p=path: self._deliver_faces(p, f))
        else:
            self._show_faces(None)

    def _burst_card(self, idx, x, current):
        from PySide6.QtWidgets import QToolButton
        b = QToolButton()
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIcon(thumb_icon(x.get("thumb")))
        b.setIconSize(QSize(104, 104))  # square: portrait frames of a burst keep their shape
        tag = "◆ Likely best" if x.get("best") else (
            "✗ " + ", ".join(cull.REASONS[k] for k in x.get("reasons") or []) if x.get("reasons") else "")
        b.setText((tag + "\n" if tag else "") + os.path.splitext(os.path.basename(x["path"]))[0])
        border = "#10b981" if x.get("best") else ("#f59e0b" if x.get("reasons") else (ACCENT if current else "#2c2f3c"))
        b.setStyleSheet(f"QToolButton {{ border: {3 if current else 2}px solid {border}; border-radius: 7px; "
                        f"background: {'#211d33' if current else '#16181f'}; padding: 3px; font-size: {_pt(8)}pt; }}")
        b.setToolTip("Click to view this frame")
        b.clicked.connect(lambda _=False, row=idx: self.grid.setCurrentRow(row))
        return b

    def _deliver_faces(self, path, fut):
        try:
            crops = fut.result()
        except Exception as e:  # unreadable preview: say so instead of spinning forever
            print("face crops failed", path, e)
            crops = None
        try:
            self._faces_loaded.emit(path, crops)
        except RuntimeError:
            pass

    def _on_faces(self, path, crops):
        if path == self._face_current:  # still the selected photo
            self._show_faces(crops)

    def _show_faces(self, crops):
        clear_layout(self.faces_row)
        if crops is None:
            self.faces_row.addWidget(label("Couldn't read this photo's preview", "Muted"))
        elif not crops:
            self.faces_row.addWidget(label("No faces found", "Muted"))
        for f in crops or []:
            card = QFrame()
            v = QVBoxLayout(card)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            pic = QLabel()
            pic.setPixmap(numpy_to_qpixmap(f["crop"]))
            pic.setFixedSize(f["crop"].shape[1], f["crop"].shape[0])
            v.addWidget(pic)
            info = label(f"Blink {f['blink']:.0%} · Smile {f['smile']:.0%}\nEyes {f['eye_sharp']:.1f} · "
                         f"{f['zoom']:.0%}", "ChipWarn" if f["blink"] > 0.5 else "Muted")
            info.setToolTip("Blink / Smile: how closed the eyes are and how big the smile is. Eyes: sharpness of the "
                            "eye area (higher is crisper; compare frames of a burst). %: zoom (100 % = 1:1).")
            v.addWidget(info)
            self.faces_row.addWidget(card)
        self.faces_row.addStretch(1)

    def toggle_overlay(self):
        self.overlay_btn.setChecked(not self.overlay_btn.isChecked())
        self.loupe.set_overlay(self.overlay_btn.isChecked())

    # ------------------------------------------------ Quick Develop
    def selected_indices(self):
        """Result indices of the selected grid photos."""
        rows = sorted({i.row() for i in self.grid.selectedIndexes()})
        return [self.view[r] for r in rows if r < len(getattr(self, "view", []))]

    def _selection_changed(self):
        n, total = len(self.selected_indices()), self.grid.count()
        self.scope_sel.setText(f"Selected ({n})")
        row = self.grid.currentRow()
        res = (self.project or {}).get("results") or []
        cur = ""
        if 0 <= row < len(self.view) and self.view[row] < len(res):
            cur = f"   /   #{self.view[row] + 1} · {os.path.basename(res[self.view[row]]['path'])}"
        self.sel_label.setText(f"{total} photos   /   {n} selected{cur}")

    def _caption(self, i, r):
        """Grid cell text: '12 · AJ201831.ARW' (cull projects add a short badge on a second line)."""
        text = f"{i + 1} · {os.path.basename(r['path'])}"
        badge = cull_badge(r) if self.project.get("kind") == "cull" else ""
        return text + ("\n" + badge if badge else "")

    def _tooltip(self, r):
        """Hover text for a grid cell: the file and its edit summary (EV / WB) or cull verdict."""
        info = cull.describe(r) if self.project.get("kind") == "cull" else summary_line(r["settings"])
        return os.path.basename(r["path"]) + ("\n" + info if info else "")

    def _refresh_captions(self):
        results = (self.project or {}).get("results") or []
        for i in range(self.grid.count()):
            if i < len(self.view):
                r = results[self.view[i]]
                self.grid.item(i).setText(self._caption(self.view[i], r))
                self.grid.item(i).setToolTip(self._tooltip(r))

    def _refresh_current(self):
        row = self.grid.currentRow()
        res = (self.project or {}).get("results") or []
        if not 0 <= row < len(getattr(self, "view", [])):
            return
        r = res[self.view[row]]
        s = self._preview_settings_for_item(r) if self.reexport_btn.isEnabled() else r["settings"]
        self.loupe.update_settings(s)
        self.hist_widget.set_image(self.loupe.after_rgb)
        self.inspector.show_develop(s)
        self._update_readouts(s)

    def quick_nudge(self, deltas, reset=False):
        """Applies a Quick Develop nudge (or Reset) to the target photos and rewrites the .virten file."""
        if not self.project or self.project.get("kind") == "cull":
            return
        if self.scope_all.isChecked():
            idx = None
        elif self.scope_one.isChecked():
            row = self.grid.currentRow()
            idx = [self.view[row]] if 0 <= row < len(self.view) else []
        else:
            idx = self.selected_indices()
        if idx is not None and not idx:
            self.main.flash("Select one or more photos first (or switch the target to All Photos).")
            return
        try:
            updated = proj.apply_quick_develop(self.project, idx, deltas, reset=reset)
        except ValueError as e:
            QMessageBox.warning(self, "Virten Studio", str(e))
            return
        self.project = updated
        self._refresh_captions()
        self._refresh_current()
        self.update_banner()
        n = len(updated.get("results") or []) if idx is None else len(idx)
        what = "Reset to the AI prediction" if reset else ", ".join(
            f"{model.display_name(k)} {v:+.2f} EV" if k == "Exposure2012" else
            f"{model.display_name(k)} {v:+d}{' K' if k == 'Temperature' else ''}" for k, v in (deltas or {}).items())
        msg = f"{what} on {n} photo{'s' if n != 1 else ''}. The .virten file is updated."
        skipped = updated.get("quick_develop_skipped") or 0
        if skipped and any(k in (deltas or {}) for k in proj.WB_KEYS):
            msg += (f" White balance wasn't changed on {skipped} photo{'s' if skipped != 1 else ''}: this project has "
                    "no white balance of its own for them (White Balance panel off, or Look only).")
        self.main.flash(msg)

    def toggle_before_after(self):
        self.set_view_mode("after" if self.loupe.mode == "before" else "before")

    def _loupe_changed(self):
        """New image in the loupe (thumbnail, then the full preview): the histogram shows what's on screen."""
        is_cull = (self.project or {}).get("kind") == "cull"
        self.hist_widget.set_image(self.loupe.before_rgb if is_cull else self.loupe.after_rgb)

    @staticmethod
    def _can_reexport(p):
        """Projects from before 1.4 only kept the final settings, which already include their Look: re-applying a
        Look to those would double it (proj.reexport_project_edits refuses them too)."""
        res = p.get("results") or []
        return bool(res) and (not p.get("look") or all("base_settings" in r for r in res))

    @staticmethod
    def _bias_applies(p):
        """Exposure bias only moves exposure where the original run set it: the Light panel was on, or Look only."""
        return not p.get("profile") or "tone" in (p.get("groups") or model.GROUPS)

    def load(self, p):
        self.project = p
        self.title.setText(p["name"])
        is_cull = p.get("kind") == "cull"
        self.qd_section.setVisible(not is_cull)
        self.dev_section.set_title("Assisted Cull Analysis" if is_cull else "Develop Sliders & AI Masks")
        self.cull_strip.setVisible(is_cull)

        if is_cull:
            s = p.get("summary") or {}
            by = s.get("by_reason") or {}
            reasons = ", ".join(f"{n} {cull.REASONS[k].lower()}" for k, n in by.items() if n)
            self.meta.setText(
                f"{p['catalog']}   ·   Assisted cull ({p.get('strictness', 'normal')})   ·   "
                f"{s.get('photos', 0):,} photos: {s.get('likely_rejects', 0):,} likely rejects"
                f"{' (' + reasons + ')' if reasons else ''}, {s.get('bursts', 0):,} bursts, "
                f"{s.get('best_hints', 0):,} likely best frames"
            )
            self.teach_btn.setText("✦ Learn Cull")
            self.teach_btn.setToolTip("Done culling? Teach the assisted-culling model your picks in this shoot")
        else:
            look = (f"   ·   look “{looks.canonical_name(p['look'])}” {p.get('look_strength', 1):.0%}"
                    if p.get("look") else "")
            profile = f"profile “{p['profile']}”" if p.get("profile") else "no profile"
            self.meta.setText(f"{p['catalog']}   ·   {profile}{look}   ·   {p.get('count', 0):,} photos")
            self.teach_btn.setText("✦ Learn Tweaks…")
            self.teach_btn.setToolTip("Compare your Lightroom tweaks with Virten Studio's edits and teach a profile")
            self._populate_tune_bar(p)

        self.archive_btn.setText("Restore" if p.get("archived_at") else "Archive")
        self.update_banner()
        self.fill_grid()
        self._fetch_exif(p)

    def _populate_tune_bar(self, p):
        self._suppress_tune = True
        can_re = self._can_reexport(p)
        tone_on = self._bias_applies(p)
        self.live_bias.setValue(float(p.get("exposure_bias") or 0.0))
        self.live_bias.setEnabled(can_re and tone_on)
        self.live_look.clear()
        self.live_look.addItem("None (Profile only)", None)
        for lk in looks.list_looks():
            self.live_look.addItem(lk["name"], lk["name"])
        idx = max(0, self.live_look.findData(looks.canonical_name(p.get("look"))))
        self.live_look.setCurrentIndex(idx)
        self.live_look.setEnabled(can_re)
        self.live_look_str.slider.setValue(int(round(float(p.get("look_strength", 1.0)) * 100)))
        self.live_look_str.setEnabled(can_re and idx > 0)
        self.reexport_btn.setEnabled(False)
        for b in self.qd_buttons + [self.scope_one, self.scope_sel, self.scope_all]:
            b.setEnabled(can_re)
        self.tune_note.setText("Older project: re-run it to fine-tune")
        self.tune_note.setToolTip("Made with an earlier version of Virten Studio: run it again as a new project to use "
                                  "Quick Develop and change its Look here.")
        self.tune_note.setVisible(not can_re)
        self.qd_section.setToolTip(
            "" if can_re else "This project was created with an earlier version; re-run it to enable live Look re-export."
        )
        if can_re and not tone_on:
            self.live_bias.setToolTip("The Light panel was off for this project, so exposure isn't changed.")
        self._suppress_tune = False

    def on_live_tune_changed(self, *_):
        if self._suppress_tune or not self.project or self.project.get("kind") == "cull":
            return
        self.live_look_str.setEnabled(self.live_look.isEnabled() and self.live_look.currentIndex() > 0)
        self.reexport_btn.setEnabled(self._can_reexport(self.project))
        row = self.grid.currentRow()
        res = (self.project or {}).get("results") or []
        if not (0 <= row < len(getattr(self, "view", []))):
            return
        r = res[self.view[row]]
        preview_s = self._preview_settings_for_item(r)
        self.loupe.update_settings(preview_s)
        self.hist_widget.set_image(self.loupe.after_rgb)
        self.inspector.show_develop(preview_s)
        self._update_readouts(preview_s)

    def _preview_settings_for_item(self, r):
        p = self.project
        if not self._can_reexport(p):  # older project with a Look baked in: show what was exported, unchanged
            return dict(r.get("settings") or {})
        base = proj.effective_base_settings(r)  # prediction + any Quick Develop nudges
        old_bias = float(p.get("exposure_bias") or 0.0)
        bias_delta = self.live_bias.value() - old_bias
        if abs(bias_delta) > 1e-6 and (self._bias_applies(p) or "Exposure2012" in base):
            v = min(max(float(base.get("Exposure2012", 0.0)) + bias_delta, -5.0), 5.0)
            base["Exposure2012"] = round(v, 2)
        lk_name = self.live_look.currentData()
        lk = looks.get_look(lk_name) if lk_name else None
        dims = tuple(r.get("dims") or (0, 0))
        return looks.apply_look(base, lk, self.live_look_str.value() / 100.0, dims=dims) if lk else base

    def apply_live_reexport(self):
        if not self.project:
            return
        try:
            updated = proj.reexport_project_edits(
                self.project,
                exposure_bias=self.live_bias.value(),
                look_name=self.live_look.currentData(),
                look_strength=self.live_look_str.value() / 100.0,
            )
        except ValueError as e:
            QMessageBox.warning(self, "Virten Studio", str(e))
            return
        self.project = updated
        self.reexport_btn.setEnabled(False)
        self.update_banner()
        self._refresh_captions()
        self.main.flash("Updated .virten edits file with your new Exposure Bias & Look settings.")
        self.show_settings(self.grid.currentRow())

    def fill_grid(self):
        results = (self.project or {}).get("results") or []
        self.view = list(range(len(results)))
        self._syncing = True  # clearing both lists fires selection signals
        self.grid.clear()
        self.filmstrip.clear()
        self._syncing = False
        self.set_thumb_size(self.thumb_slider.value())  # cell height depends on the project kind
        self._pending = [(i, results[i]) for i in self.view]
        self._timer.start(0)

    def _load_some(self):
        for _ in range(40):
            if not self._pending:
                self._timer.stop()
                if self.grid.count():
                    self.grid.setCurrentRow(0)
                self._selection_changed()
                return
            i, r = self._pending.pop(0)
            it = QListWidgetItem(thumb_icon(r.get("thumb")), self._caption(i, r))
            it.setSizeHint(self.grid.gridSize() - QSize(6, 4))
            it.setToolTip(self._tooltip(r))
            self.grid.addItem(it)
            fs = QListWidgetItem(thumb_icon(r.get("thumb")), "")
            fs.setData(Qt.UserRole, i + 1)
            fs.setToolTip(f"{i + 1} · {os.path.basename(r['path'])}")
            self.filmstrip.addItem(fs)

    def show_settings(self, row):
        res = (self.project or {}).get("results") or []
        if not 0 <= row < len(getattr(self, "view", [])):
            return
        r = res[self.view[row]]
        self._update_info(row)
        if self.project.get("kind") == "cull":
            self.loupe.load_photo(r["path"], r.get("thumb"), {})
            self.hist_widget.set_image(self.loupe.before_rgb)
            self.inspector.show_cull(r)
            self._update_cull_strip(r)
        else:
            s = self._preview_settings_for_item(r) if self.reexport_btn.isEnabled() else r["settings"]
            self.loupe.load_photo(r["path"], r.get("thumb"), s)
            self.hist_widget.set_image(self.loupe.after_rgb)
            self.inspector.show_develop(s)
            self._update_readouts(s)

    def update_banner(self):
        p = self.project
        if p.get("kind") == "cull":
            if p.get("learned"):
                self.banner_title.setText("Learned from ✓")
                self.banner_text.setText("Your picks in this shoot are part of the assisted-culling model.")
            elif proj.edits_applied(p):
                self.banner_title.setText("Suggestions are in Lightroom ✓")
                self.banner_text.setText(
                    f"Filter by Virten Cull keywords or open the Virten Cull ▸ {p['name']} collections in Lightroom. "
                    "When done rating keepers, click Learn from This Cull."
                )
            else:
                self.banner_title.setText("Next: add the suggestions in Lightroom Classic")
                self.banner_text.setText(
                    f"Open “{os.path.basename(p['catalog'])}” in Lightroom Classic and choose "
                    "Library ▸ Plug-in Extras ▸ Apply Virten Studio Edits…"
                )
            self.plugin_btn.setVisible(not plugin_installed())
            return

        if proj.edits_applied(p):
            self.banner_title.setText("Applied in Lightroom ✓  —  Ready to Learn from Your Tweaks")
            self.banner_text.setText(
                "Edits are in your catalog under a “Virten Studio” history step. After you tweak any photos in "
                "Lightroom, click “✦ Learn from Lightroom Tweaks…” above to inspect your adjustments and train your profile."
            )
        else:
            self.banner_title.setText("Next: apply the edits in Lightroom Classic")
            self.banner_text.setText(
                f"Open “{os.path.basename(p['catalog'])}” in Lightroom Classic ▸ Library ▸ Plug-in Extras ▸ "
                "Apply Virten Studio Edits… (or fine-tune it first with Quick Develop on the right)."
            )
        self.plugin_btn.setVisible(not plugin_installed())

    def install(self):
        install_plugin(self)
        self.update_banner()
        self.main.update_plugin_status()

    def teach(self):
        if self.project.get("kind") == "cull":
            if QMessageBox.question(
                self, "Virten Studio",
                "Done culling this shoot? Your star ratings in this catalog (any star = kept) "
                "will teach the assisted-culling model.",
            ) != QMessageBox.Yes:
                return
            self.project["learned"] = True
            proj.upsert_project(self.project)
            self.update_banner()
            self.main.profiles.train_cull()
            return

        if not model.list_profiles():
            QMessageBox.information(
                self, "Virten Studio",
                "Create a personal profile under Profiles first so Virten Studio has a profile to update.",
            )
            return

        dlg = LearnTweaksDialog(self, self.project)
        if dlg.exec() and dlg.chosen_config:
            cfg = dlg.chosen_config
            self.main.profiles.learn(
                cfg["meta"],
                extra=[cfg["catalog"]],
                tweak_boost=cfg["tweak_boost"],
                only_tweaked_catalogs=cfg["only_tweaked_catalogs"],
                include_approved_catalogs=cfg["include_approved_catalogs"],
                strip_look_catalogs=cfg["strip_look_catalogs"],
            )

    def toggle_archive(self):
        if self.project.get("archived_at"):
            proj.restore_project(self.project["id"])
            self.main.flash("Restored to Active projects.")
            self.main.open_project(self.project)
        else:
            self.main.projects.archive(self.project["id"])
            self.main.nav(0)

    def show_file(self):
        f = self.project.get("edits_file") or ""
        if not os.path.exists(f) and os.path.exists(f + ".applied"):
            f += ".applied"
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(f)))

    def delete(self):
        if QMessageBox.question(
            self, "Virten Studio",
            "Remove this project from Virten Studio? Your catalog and photos aren't touched.",
        ) == QMessageBox.Yes:
            proj.delete_project(self.project["id"])
            self.main.nav(0)


# ---------------------------------------------------------------- main window

class JobQueuePanel(QFrame):
    """Sidebar drawer for background jobs: the running job's name, progress and a Stop button, plus how many are
    queued. Hidden when nothing is running."""

    def __init__(self, main):
        super().__init__()
        self.setObjectName("JobPanel")
        l = QVBoxLayout(self)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(4)
        self.title = label("", "JobTitle", wrap=True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.status = label("", "Muted", wrap=True)
        self.queued = label("", "Chip")
        self.stop_btn = button("Stop", "Nudge", slot=main.stop_job)
        l.addWidget(self.title)
        l.addWidget(self.bar)
        l.addWidget(self.status)
        l.addLayout(hbox(self.queued, None, self.stop_btn, spacing=6))
        self.hide()

    def start(self, title, queued):
        self.title.setText(title)
        self.bar.setRange(0, 0)  # busy until the first progress report
        self.status.setText("Starting…")
        self.stop_btn.setEnabled(True)
        self.set_queued(queued)
        self.show()

    def update_progress(self, a, b, text):
        self.bar.setRange(0, max(b, 1))
        self.bar.setValue(a)
        self.status.setText(f"{text} {a:,} / {b:,}" if b > 1 else text)

    def set_queued(self, n):
        self.queued.setText(f"+{n} queued")
        self.queued.setVisible(n > 0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Virten Studio")
        self.resize(1380, 860)
        root = QWidget()
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 16)
        logo = QLabel(f"Virten <span style='color:{ACCENT}'>Studio</span>")
        logo.setObjectName("Logo")
        sl.addWidget(logo)
        sub = QLabel("AI PHOTOGRAPHERS WORKFLOW")
        sub.setObjectName("LogoSub")
        sl.addWidget(sub)

        self.nav_buttons = []
        for i, text in enumerate(["Projects", "Profiles", "Looks", "Settings"]):
            b = button(text, "NavButton", slot=lambda _=False, i=i: self.nav(i))
            b.setCheckable(True)
            self.nav_buttons.append(b)
            sl.addWidget(b)
        sl.addStretch(1)
        self.update_btn = button("", "Primary", slot=self.install_update)
        self.update_btn.hide()
        sl.addWidget(self.update_btn)
        self._jobs, self._job = deque(), None
        self.job_panel = JobQueuePanel(self)
        jw = QWidget()
        jl = QVBoxLayout(jw)
        jl.setContentsMargins(10, 4, 10, 6)
        jl.addWidget(self.job_panel)
        sl.addWidget(jw)
        self.sync_label = label("", "Muted", wrap=True)
        self.sync_label.setContentsMargins(18, 0, 12, 4)
        sl.addWidget(self.sync_label)
        self.plugin_status = button("", "NavButton", slot=self.plugin_clicked)
        sl.addWidget(self.plugin_status)
        self.coffee_btn = button("☕  Buy Me a Coffee", "coffeeBtn", slot=lambda: support.open_support_page())
        self.coffee_btn.setToolTip("Optional: support Virten Studio (opens buymeacoffee.com in your browser)")
        sl.addWidget(self.coffee_btn)
        rl.addWidget(side)
        self.sidebar = side
        self.sidebar_collapsed = False
        self.edge_btn = QPushButton("◀")  # Lightroom-style edge strip: hides / shows the navigation panel
        self.edge_btn.setObjectName("EdgeToggle")
        self.edge_btn.setFixedWidth(12)
        self.edge_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.edge_btn.setCursor(Qt.PointingHandCursor)
        self.edge_btn.setFocusPolicy(Qt.NoFocus)
        self.edge_btn.setToolTip("Hide / show the navigation panel (F5, or Tab in a project)")
        self.edge_btn.clicked.connect(lambda: self.toggle_sidebar())
        rl.addWidget(self.edge_btn)
        sc = QShortcut(QKeySequence("F5"), self)
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(lambda: self.toggle_sidebar())

        self.stack = QStackedWidget()
        self.projects = ProjectsPage(self)
        self.profiles = ProfilesPage(self)
        self.looks = LooksPage(self)
        self.settings = SettingsPage(self)
        self.detail = ProjectDetail(self)
        for w in (self.projects, self.profiles, self.looks, self.settings, self.detail):
            self.stack.addWidget(w)
        rl.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.setAcceptDrops(True)

        plugin_updated = False
        try:
            if plugin_outdated():
                plugin_updated = bool(install_plugin(self, quiet=True))
        except OSError:
            pass
        self.update_plugin_status()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().hide()
        removed = proj.purge_archived()
        self.nav(0 if model.list_profiles() else 1)
        if removed:
            self.flash(f"Removed {removed} project(s) archived more than {proj.ARCHIVE_DAYS} days ago.")
        if plugin_updated:
            QTimer.singleShot(800, lambda: QMessageBox.information(
                self, "Virten Studio",
                "The Lightroom plugin was updated for this version of Virten Studio.\n\n"
                "If Lightroom Classic is open, restart it so it uses the new plugin.",
            ))
        QTimer.singleShot(500, lambda: self.run_sync())

    def run_sync(self, on_done=None):
        if not sync.sync_dir():
            self.sync_label.setText("")
            if auto_update_check():  # GitHub Releases still offer updates without a sync folder
                self.check_update()
            return on_done([]) if on_done else None
        self.sync_label.setText("Syncing…")

        def done(changed):
            self.sync_label.setText("☁  Synced " + datetime.datetime.now().strftime("%H:%M"))
            if changed and self.stack.currentWidget() in (self.profiles, self.projects):
                self.stack.currentWidget().reload()
            if auto_update_check():
                self.check_update()
            if on_done:
                on_done(changed)

        start_worker(
            self, _plain(sync.sync_all),
            on_done=done,
            on_failed=lambda m: self.sync_label.setText("☁  Sync folder unavailable"),
        )

    def check_update(self, on_done=None):
        """Looks for a newer version (sync folder and GitHub Releases) in the background: GitHub may be slow or the
        computer offline, and the window must never wait for it."""
        def done(upd):
            self._update = upd
            self.update_btn.setEnabled(True)
            self.update_btn.setVisible(bool(upd))
            if upd:
                self.update_btn.setText(f"⬆  Update to {upd[0]}")
            if on_done:
                on_done(upd)

        start_worker(self, _plain(sync.available_update), on_done=done,
                     on_failed=lambda m: on_done(None) if on_done else None)

    def install_update(self):
        upd = getattr(self, "_update", None)
        if not upd:
            return
        ver, src = upd
        remote = src.startswith("https://")
        if QMessageBox.question(
            self, "Virten Studio",
            f"Install Virten Studio {ver} now? " + (
                "It downloads from GitHub first (you can keep working meanwhile); then Virten Studio closes and the "
                "installer opens." if remote else "Virten Studio will close and the installer will open."),
        ) != QMessageBox.Yes:
            return
        if not remote:
            open_with_system(src)
            self.close()
            return

        def download(progress=None, cancelled=lambda: False):  # progress in MB for the job drawer
            return sync.download_update(
                src, progress=lambda a, b, text: progress(a // 1048576, b // 1048576, text + " (MB)"),
                cancelled=cancelled)

        self.update_btn.setEnabled(False)
        self.update_btn.setText(f"⬇  Downloading {ver}…")
        self.enqueue_job(f"Downloading Virten Studio {ver}", download,
                         on_done=lambda path, v=ver: self._installer_ready(v, path),
                         on_failed=lambda m, v=ver: self._download_failed(v, m))

    def _installer_ready(self, ver, path):
        self._update = (ver, path)  # downloaded: the next click installs at once
        self.update_btn.setEnabled(True)
        self.update_btn.setText(f"⬆  Install {ver}")
        if self._jobs and QMessageBox.question(
            self, "Virten Studio",
            f"Virten Studio {ver} is downloaded. Install it now? Your {len(self._jobs)} queued job(s) won't run; "
            "choose No to install later from the Update button.",
        ) != QMessageBox.Yes:
            return
        open_with_system(path)
        self.close()

    def _download_failed(self, ver, msg):
        self.update_btn.setEnabled(True)
        self.update_btn.setText(f"⬆  Update to {ver}")
        self.flash(f"Couldn't download Virten Studio {ver}: {msg}")

    def toggle_sidebar(self, show=None):
        """Collapses the left navigation panel to 0 px (or brings it back) for more workspace."""
        show = self.sidebar_collapsed if show is None else bool(show)
        self.sidebar_collapsed = not show
        self.sidebar.setFixedWidth(220 if show else 0)
        self.sidebar.setVisible(show)
        self.edge_btn.setText("◀" if show else "▶")

    def nav(self, i):
        for j, b in enumerate(self.nav_buttons):
            b.setChecked(j == i)
        if i == 0:
            self.projects.reload()
        elif i == 1:
            self.profiles.reload()
        elif i == 2:
            self.looks.reload()
        elif i == 3:
            self.settings.reload()
        self.stack.setCurrentIndex(i)

    def open_project(self, p):
        for b in self.nav_buttons:
            b.setChecked(False)
        self.nav_buttons[0].setChecked(True)
        self.detail.load(proj.load_project(p["id"]) or p)
        self.stack.setCurrentWidget(self.detail)

    def flash(self, message, ms=7000):
        bar = self.statusBar()
        bar.show()
        bar.showMessage(message, ms)
        QTimer.singleShot(ms, lambda: bar.hide() if not bar.currentMessage() else None)

    def update_plugin_status(self):
        self.plugin_status.setText("✓  Plugin installed" if plugin_installed() else "⚠  Install LR plugin")

    def plugin_clicked(self):
        if not plugin_installed() or QMessageBox.question(
            self, "Virten Studio", "The Lightroom plugin is already installed. Reinstall it?"
        ) == QMessageBox.Yes:
            install_plugin(self)
            self.update_plugin_status()

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".lrcat") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".lrcat"):
                self.projects.new_project(os.path.normpath(u.toLocalFile()))
                break

    # ------------------------------------------------ background jobs (one at a time, first in first out)
    def enqueue_job(self, title, fn, *args, on_done=None, on_failed=None):
        """Runs fn(*args, progress=..., cancelled=...) in the background after any jobs already waiting, with its
        progress in the sidebar. on_done(result) / on_failed(message) run on the UI thread."""
        self._jobs.append({"title": title, "fn": fn, "args": args, "on_done": on_done, "on_failed": on_failed})
        if self._job is None:
            self._next_job()
        else:
            self.job_panel.set_queued(len(self._jobs))
            self.flash(f"Queued “{title}”: it starts when the current job finishes.")

    def queued_jobs(self):
        return len(self._jobs) + (1 if self._job else 0)

    def _next_job(self):
        self._job = None
        if not self._jobs:
            self.job_panel.hide()
            return
        job = self._jobs.popleft()
        self._job = job
        self.job_panel.start(job["title"], len(self._jobs))
        job["worker"] = start_worker(self, job["fn"], *job["args"], on_progress=self.job_panel.update_progress,
                                     on_done=lambda r, j=job: self._job_finished(j, r, None),
                                     on_failed=lambda m, j=job: self._job_finished(j, None, m))

    def _job_finished(self, job, result, error):
        cb = job["on_failed"] if error is not None else job["on_done"]
        try:
            if cb:
                cb(error if error is not None else result)
            elif error is not None:
                self.flash(f"“{job['title']}” stopped: {error}")
        except Exception:
            traceback.print_exc()
        QTimer.singleShot(0, self._next_job)

    def stop_job(self):
        if self._job and self._job.get("worker"):
            self._job["worker"].cancel()
            self.job_panel.status.setText("Stopping…")
            self.job_panel.stop_btn.setEnabled(False)

    def project_finished(self, p):
        if self.stack.currentWidget() is self.projects:
            self.projects.reload()
        self.flash(f"Finished “{p['name']}” — click Projects to view")

    def closeEvent(self, e):
        self._jobs.clear()
        if _RUNNING:
            stop_workers(list(_RUNNING), timeout_s=10)
        super().closeEvent(e)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AngelitoJusay.VirtenStudio")
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Virten Studio")
    app.setStyleSheet(STYLE)
    icon = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from . import migrate
    try:
        notes = migrate.run()
    except Exception as e:
        traceback.print_exc()
        notes = [f"Couldn't finish moving data from AutoStyle: {e}"]
    w = MainWindow()
    w.show()
    if notes:
        w.flash("  ".join(notes), 15000)
    code = app.exec()
    for pool in (_PREVIEW_POOL, _FACE_POOL):  # quit promptly: drop queued previews/faces, finish only the running ones
        pool.shutdown(wait=True, cancel_futures=True)
    sys.exit(code)
