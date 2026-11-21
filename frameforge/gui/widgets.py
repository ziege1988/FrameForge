"""Custom painted widgets: quality timeline, preview with local quality map, score bars."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..core.scoring import COMPONENT_LABELS, component_label
from . import theme
from .theme import MUTED, score_color

SERIES_COLORS = ["#3d8bff", "#ff9a3c", "#4cc38a", "#c77dff", "#e5534b", "#e8b339", "#3fd0c9", "#ff6fa5"]


class QualityPlot(QWidget):
    """Frame quality over time for one or several files (session comparison)."""

    frameClicked = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._series: list[dict] = []
        self._threshold: float | None = None
        self._normalize_time = False

    def set_series(self, series: list[dict], threshold: float | None = None) -> None:
        """series: [{"name", "x" (np.ndarray), "y" (np.ndarray), "frames" (np.ndarray), "xlabel"}]"""
        self._series = [s for s in series if s["y"].size]
        self._threshold = threshold
        self._normalize_time = len(self._series) > 1
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(52, 16, max(10, self.width() - 68), max(10, self.height() - 52))

    def _x_values(self, s: dict) -> np.ndarray:
        x = s["x"].astype(float)
        if self._normalize_time and x.size > 1 and x[-1] > x[0]:
            return (x - x[0]) / (x[-1] - x[0]) * 100.0
        return x

    def _x_range(self) -> tuple[float, float]:
        xs = [self._x_values(s) for s in self._series]
        lo = min(float(x.min()) for x in xs)
        hi = max(float(x.max()) for x in xs)
        return (lo, hi if hi > lo else lo + 1)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0c1324"))
        r = self._plot_rect()
        p.setPen(QColor(MUTED))
        if not self._series:
            p.drawText(self.rect(), Qt.AlignCenter, "Keine Verlaufsdaten – Datei(en) in der Tabelle auswählen.")
            return
        x0, x1 = self._x_range()
        grid = QPen(QColor("#1d2333"))
        font = QFont(self.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(max(7.5, font.pointSizeF() - 2))
        else:
            font.setPixelSize(max(10, font.pixelSize() - 2))
        p.setFont(font)
        for q in (0, 25, 50, 75, 100):
            y = r.bottom() - q / 100 * r.height()
            p.setPen(grid)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y - 8, 46, 16), Qt.AlignRight | Qt.AlignVCenter, str(q))
        for k in range(6):
            xv = x0 + (x1 - x0) * k / 5
            x = r.left() + r.width() * k / 5
            p.drawText(QRectF(x - 40, r.bottom() + 4, 80, 16), Qt.AlignHCenter, f"{xv:.0f}")
        xlabel = "Aufnahmeverlauf in %" if self._normalize_time else self._series[0].get("xlabel", "Frame")
        p.drawText(QRectF(r.left(), r.bottom() + 20, r.width(), 16), Qt.AlignHCenter, xlabel)
        p.save()
        p.translate(12, r.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-60, -10, 120, 20), Qt.AlignCenter, "Qualität")
        p.restore()

        if self._threshold is not None and len(self._series) == 1:
            y = r.bottom() - self._threshold / 100 * r.height()
            pen = QPen(QColor(theme.accent()), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.drawText(QRectF(r.right() - 220, y - 18, 216, 16), Qt.AlignRight, "Auswahlschwelle")

        for n, s in enumerate(self._series):
            color = QColor(theme.accent() if n == 0 else SERIES_COLORS[n % len(SERIES_COLORS)])
            xs = self._x_values(s)
            ys = s["y"]
            if xs.size > 1:
                # Thin raw line + smoothed line for readability
                raw = QPainterPath()
                for i, (xv, yv) in enumerate(zip(xs, ys)):
                    pt = QPointF(r.left() + (xv - x0) / (x1 - x0) * r.width(), r.bottom() - yv / 100 * r.height())
                    raw.moveTo(pt) if i == 0 else raw.lineTo(pt)
                c = QColor(color)
                c.setAlpha(70 if len(self._series) == 1 else 40)
                p.setPen(QPen(c, 1))
                p.drawPath(raw)
                win = max(1, xs.size // 40)
                sm = np.convolve(ys, np.ones(win) / win, mode="same") if win > 1 else ys
                path = QPainterPath()
                for i, (xv, yv) in enumerate(zip(xs, sm)):
                    pt = QPointF(r.left() + (xv - x0) / (x1 - x0) * r.width(), r.bottom() - yv / 100 * r.height())
                    path.moveTo(pt) if i == 0 else path.lineTo(pt)
                p.setPen(QPen(color, 2))
                p.drawPath(path)
            else:
                pt = QPointF(r.center().x(), r.bottom() - ys[0] / 100 * r.height())
                p.setBrush(color)
                p.setPen(Qt.NoPen)
                p.drawEllipse(pt, 4, 4)
        if len(self._series) > 1:
            lx, ly = r.left() + 8, r.top() + 4
            for n, s in enumerate(self._series[:8]):
                p.setPen(QPen(QColor(theme.accent() if n == 0 else SERIES_COLORS[n % len(SERIES_COLORS)]), 3))
                p.drawLine(QPointF(lx, ly + 8 + n * 16), QPointF(lx + 16, ly + 8 + n * 16))
                p.setPen(QColor("#e6e9f2"))
                p.drawText(QPointF(lx + 22, ly + 12 + n * 16), s["name"])

    def _hit(self, pos) -> tuple[dict, int] | None:
        if not self._series:
            return None
        r = self._plot_rect()
        if not r.contains(pos):
            return None
        x0, x1 = self._x_range()
        xv = x0 + (pos.x() - r.left()) / r.width() * (x1 - x0)
        best = None
        for s in self._series:
            xs = self._x_values(s)
            i = int(np.argmin(np.abs(xs - xv)))
            py = r.bottom() - s["y"][i] / 100 * r.height()
            d = abs(py - pos.y())
            if best is None or d < best[2]:
                best = (s, i, d)
        return (best[0], best[1]) if best else None

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        if hit:
            s, i = hit
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{s['name']}\nFrame {int(s['frames'][i])}: Qualität {s['y'][i]:.0f}", self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        hit = self._hit(event.position())
        if hit:
            s, i = hit
            self.frameClicked.emit(s["name"], int(s["frames"][i]))


class PreviewWidget(QWidget):
    """Frame preview with ROI rectangle and local quality map.

    ``zoom`` None = fit into the widget; otherwise the image is drawn at
    ``zoom`` × its pixel size and the widget takes that size (for use inside
    a QScrollArea).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(160, 120)
        self._pixmap: QPixmap | None = None
        self._roi = None
        self._local = None
        self.show_map = True
        self._caption = ""
        self.zoom: float | None = None

    def set_frame(self, img: np.ndarray | None, roi=None, local=None, caption: str = "") -> None:
        if img is None:
            self._pixmap = None
        else:
            h, w = img.shape
            qimg = QImage(np.ascontiguousarray(img).data, w, h, w, QImage.Format_Grayscale8).copy()
            self._pixmap = QPixmap.fromImage(qimg)
        self._roi, self._local, self._caption = roi, local, caption
        self._apply_size()
        self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None

    def image_size(self) -> tuple[int, int]:
        return (self._pixmap.width(), self._pixmap.height()) if self._pixmap else (0, 0)

    def set_zoom(self, zoom: float | None) -> None:
        self.zoom = zoom
        self._apply_size()
        self.update()

    def _apply_size(self):
        if self.zoom is None or self._pixmap is None:
            self.setMinimumSize(160, 120)
            self.setMaximumSize(16777215, 16777215)
        else:
            w, h = int(self._pixmap.width() * self.zoom), int(self._pixmap.height() * self.zoom)
            self.setFixedSize(max(w, 1), max(h, 1))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom is None or self.zoom < 1)
        p.fillRect(self.rect(), QColor("#03060d"))
        if self._pixmap is None:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Keine Vorschau")
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if self.zoom is None:
            caption_h = 22 if self._caption else 0
            area = self.rect().adjusted(4, 4, -4, -4 - caption_h)
            f = min(area.width() / pw, area.height() / ph)
            tw, th = pw * f, ph * f
            target = QRectF(area.left() + (area.width() - tw) / 2, area.top() + (area.height() - th) / 2, tw, th)
        else:
            f = self.zoom
            target = QRectF(0, 0, pw * f, ph * f)
        p.drawPixmap(target, self._pixmap, QRectF(0, 0, pw, ph))
        if self._roi and self.show_map:
            x, y, w, h = self._roi
            rr = QRectF(target.left() + x * f, target.top() + y * f, w * f, h * f)
            if self._local is not None and np.isfinite(self._local).any():
                loc = self._local
                n = loc.shape[0]
                hi = float(np.nanmax(loc))
                for r_ in range(n):
                    for c_ in range(n):
                        v = loc[r_, c_]
                        if not np.isfinite(v):
                            continue
                        t = v / hi if hi > 0 else 1.0  # relative to the sharpest tile
                        col = QColor(score_color(100 * t))
                        col.setAlpha(60)
                        cell = QRectF(rr.left() + c_ * rr.width() / n, rr.top() + r_ * rr.height() / n,
                                      rr.width() / n, rr.height() / n)
                        p.fillRect(cell, col)
                        p.setPen(QColor(255, 255, 255, 170))
                        p.drawText(cell, Qt.AlignCenter, f"{t * 100:.0f}")
            p.setPen(QPen(QColor(theme.accent()), 1.5, Qt.DashLine))
            p.drawRect(rr)
        if self.zoom is None and self._caption:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, self.height() - 22, self.width(), 20), Qt.AlignCenter, self._caption)


class ComponentBars(QWidget):
    """Horizontal bars for the score components (labels depend on the profile)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._components: dict = {}
        self._profile = None
        self.setMinimumHeight(len(COMPONENT_LABELS) * 26 + 8)

    def set_components(self, components: dict, profile=None) -> None:
        self._components = components or {}
        self._profile = profile
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        label_w = 170
        bar_w = max(40, self.width() - label_w - 50)
        for i, key in enumerate(COMPONENT_LABELS):
            label = component_label(key, self._profile)
            y = 4 + i * 26
            p.setPen(QColor("#c9d2e6"))
            p.drawText(QRectF(0, y, label_w - 10, 20), Qt.AlignRight | Qt.AlignVCenter, label)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#1a2440"))
            p.drawRoundedRect(QRectF(label_w, y + 5, bar_w, 10), 5, 5)
            v = self._components.get(key)
            if v is None:
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(label_w + bar_w + 8, y, 44, 20), Qt.AlignVCenter, "n. b.")
                continue
            p.setBrush(QColor(score_color(v)))
            p.drawRoundedRect(QRectF(label_w, y + 5, bar_w * max(0.0, min(v, 100.0)) / 100, 10), 5, 5)
            p.setPen(QColor("#e8ecf6"))
            p.drawText(QRectF(label_w + bar_w + 8, y, 44, 20), Qt.AlignVCenter, f"{v:.0f}")
