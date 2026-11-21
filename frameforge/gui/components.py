"""Dashboard building blocks: cards, option buttons, badges, donut and sparkline charts, zoomable preview."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from . import theme
from .theme import CARD_BORDER, GOOD, verdict_bg, verdict_color
from .widgets import PreviewWidget


class Card(QFrame):
    """Rounded panel with optional title row (icon + title)."""

    def __init__(self, title: str = "", icon_name: str | None = None, icon_color: str = "#c9d2e6", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 14, 18, 14)
        self.body.setSpacing(10)
        if title:
            row = QHBoxLayout()
            row.setSpacing(8)
            if icon_name:
                ic = QLabel()
                ic.setPixmap(icons.pixmap(icon_name, 20, icon_color))
                row.addWidget(ic)
            lbl = QLabel(title)
            lbl.setObjectName("h2")
            row.addWidget(lbl)
            row.addStretch(1)
            self.header = row
            self.body.addLayout(row)


class OptionButton(QFrame):
    """Large clickable option (icon, title, subtitle) as in the welcome dialog."""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, subtitle: str, primary: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("optionPrimary" if primary else "option")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(16)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 30, "#dfe8ff" if primary else "#c9d2e6"))
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        if primary:
            t.setObjectName("optTitle")
        else:
            t.setStyleSheet("font-size: 14px; color: #ffffff; background: transparent;")
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setStyleSheet("background: transparent;")
        col.addWidget(t)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        self.setMinimumHeight(58)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


class Badge(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignCenter)
        self.set_verdict(text)

    def set_verdict(self, verdict: str, text: str | None = None):
        self.setText(text if text is not None else verdict)
        self.setStyleSheet(f"background: {verdict_bg(verdict)}; color: {verdict_color(verdict)}; "
                           f"border: 1px solid {verdict_color(verdict)}55; border-radius: 4px; padding: 2px 8px;"
                           "font-weight: 600;")


class DonutChart(QWidget):
    """Share of recommended files (green ring with grey remainder)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(130, 130)
        self._parts: list[tuple[float, str]] = []
        self._text = "–"

    def set_parts(self, parts: list[tuple[float, str]], text: str):
        self._parts, self._text = parts, text
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(9, 9, self.width() - 18, self.height() - 18)
        p.setPen(QPen(QColor("#26314d"), 13, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(r, 0, 360 * 16)
        total = sum(v for v, _ in self._parts) or 1.0
        start = 90 * 16
        for v, color in self._parts:
            span = -int(round(360 * 16 * v / total))
            if span:
                p.setPen(QPen(QColor(color), 13, Qt.SolidLine, Qt.RoundCap if len(self._parts) == 1 else Qt.FlatCap))
                p.drawArc(r, start, span)
            start += span
        f = QFont(self.font())
        f.setPixelSize(21)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class Sparkline(QWidget):
    """Small area chart of values (e.g. session scores in chronological order)."""

    def __init__(self, color: str = GOOD, parent=None):
        super().__init__(parent)
        self.color = color
        self.values: list[float] = []
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, values):
        self.values = [float(v) for v in values]
        self.update()

    def paintEvent(self, _e):
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        vals = np.array(self.values)
        win = max(1, len(vals) // 12)
        if win > 1:
            vals = np.convolve(np.pad(vals, win, mode="edge"), np.ones(win) / win, mode="same")[win:-win]
        lo, hi = float(vals.min()), float(vals.max())
        if hi - lo < 1e-6:
            lo, hi = lo - 1, hi + 1
        w, h = self.width() - 4, self.height() - 6
        pts = [QPointF(2 + w * i / (len(vals) - 1), 3 + h - (v - lo) / (hi - lo) * h) for i, v in enumerate(vals)]
        path = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mid = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
        area = QPainterPath(path)
        area.lineTo(pts[-1].x(), self.height())
        area.lineTo(pts[0].x(), self.height())
        area.closeSubpath()
        grad = QLinearGradient(0, 0, 0, self.height())
        c = QColor(self.color)
        c.setAlpha(90)
        grad.setColorAt(0, c)
        c.setAlpha(0)
        grad.setColorAt(1, c)
        p.fillPath(area, grad)
        p.setPen(QPen(QColor(self.color), 2))
        p.drawPath(path)


class ZoomPreview(QWidget):
    """Preview card content: image in a scroll area, zoom selector, fit and overlay buttons.

    ``full_loader`` is called once when a zoom > "Einpassen" is chosen and may
    return a full resolution uint8 image (otherwise the preview image is used).
    """

    ZOOMS = [("Einpassen", None), ("25 %", 0.25), ("50 %", 0.5), ("100 %", 1.0), ("200 %", 2.0), ("400 %", 4.0)]

    def __init__(self, parent=None, show_caption: bool = True, show_map: bool = True):
        super().__init__(parent)
        self.full_loader = None
        self._base = None  # (img, roi, local, caption)
        self._full_scale = 1.0  # full image pixels per preview pixel
        self._full_loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.view = PreviewWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.view)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: #03060d; border: 1px solid {CARD_BORDER}; border-radius: 6px; }}")
        lay.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        lbl = QLabel("Zoom:")
        lbl.setObjectName("muted")
        row.addWidget(lbl)
        self.zoom_box = QComboBox()
        for text, _ in self.ZOOMS:
            self.zoom_box.addItem(text)
        self.zoom_box.currentIndexChanged.connect(self._on_zoom)
        row.addWidget(self.zoom_box)
        self.caption = QLabel()
        self.caption.setObjectName("muted")
        row.addWidget(self.caption, 1)
        self.fit_btn = QToolButton()
        self.fit_btn.setIcon(icons.icon("expand"))
        self.fit_btn.setToolTip("Ins Fenster einpassen")
        self.fit_btn.clicked.connect(lambda: self.zoom_box.setCurrentIndex(0))
        self.map_btn = QToolButton()
        self.map_btn.setIcon(icons.icon("crop", active_color=theme.accent()))
        theme.bus.changed.connect(self._on_theme)
        self.map_btn.setCheckable(True)
        self.map_btn.setChecked(show_map)
        self.map_btn.setToolTip("Analysebereich und lokale Qualitätskarte ein-/ausblenden")
        self.map_btn.toggled.connect(self._on_map)
        row.addWidget(self.fit_btn)
        row.addWidget(self.map_btn)
        lay.addLayout(row)
        self.caption.setVisible(show_caption)
        self.view.show_map = show_map

    def _on_theme(self, p):
        self.map_btn.setIcon(icons.icon("crop", active_color=p.accent))
        self.view.update()

    def set_frame(self, img, roi=None, local=None, caption: str = "", full_loader=None):
        self._base = (img, roi, local, caption)
        self.full_loader = full_loader
        self._full_loaded = False
        self._full_scale = 1.0
        self.caption.setText(caption)
        self.zoom_box.blockSignals(True)
        self.zoom_box.setCurrentIndex(0)
        self.zoom_box.blockSignals(False)
        self.view.set_frame(img, roi, local, "")
        self._apply_zoom(None)

    def _on_map(self, on):
        self.view.show_map = on
        self.view.update()

    def _on_zoom(self, index):
        zoom = self.ZOOMS[index][1]
        if zoom is not None and not self._full_loaded and self.full_loader and self._base and self._base[0] is not None:
            self._full_loaded = True
            try:
                full = self.full_loader()
            except Exception:
                full = None
            if full is not None:
                img, roi, local, cap = self._base
                self._full_scale = full.shape[1] / img.shape[1]
                fs = self._full_scale
                roi_full = tuple(int(v * fs) for v in roi) if roi else None
                self.view.set_frame(full, roi_full, local, "")
        self._apply_zoom(zoom)

    def _apply_zoom(self, zoom):
        if zoom is None:
            self.scroll.setWidgetResizable(True)
            self.view.set_zoom(None)
        else:
            self.scroll.setWidgetResizable(False)
            # With the full resolution image loaded, zoom refers to original pixels
            self.view.set_zoom(zoom)

    def sizeHint(self):
        return QSize(380, 300)


def status_icon(verdict: str, size: int = 18):
    name = {"Empfohlen": "check", "Abgelehnt": "alert", "Fehler": "alert", "Bedingt geeignet": "warn"}.get(verdict, "info")
    return icons.pixmap(name, size, verdict_color(verdict))


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f} s".replace(".", ",")
    m, s = divmod(int(round(seconds)), 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"

