"""Procedural night-sky background (stars, Milky Way band, faint nebulae).

Rendered once per size into a cached pixmap, so painting costs nothing during
analysis. A fixed seed keeps the sky identical between starts and resizes
(stars are placed in normalised coordinates).
"""

from __future__ import annotations

import os
import random
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import BG

SEED = 20261121
STAR_COLORS = [QColor("#ffffff"), QColor("#cfe0ff"), QColor("#a9c6ff"), QColor("#fff1d6"), QColor("#ffd7b0")]


def _sky_catalog(seed: int = SEED, n: int = 2600):
    """Stars as (x, y, magnitude 0..1, colour index) in normalised coordinates."""
    rnd = random.Random(seed)
    stars = []
    for _ in range(n):
        # 45 % of the stars concentrate along a diagonal Milky Way band
        if rnd.random() < 0.45:
            t = rnd.random()
            off = rnd.gauss(0, 0.07)
            x, y = t, 0.95 - 0.8 * t + off
        else:
            x, y = rnd.random(), rnd.random()
        if not (0 <= x <= 1 and 0 <= y <= 1):
            continue
        mag = rnd.random() ** 3.2  # many faint, few bright stars
        col = rnd.choices(range(len(STAR_COLORS)), weights=[50, 22, 10, 12, 6])[0]
        stars.append((x, y, mag, col))
    return stars


_CATALOG = _sky_catalog()


def render_starfield(width: int, height: int, ratio: float = 1.0, density: float = 1.0) -> QPixmap:
    w, h = max(1, width), max(1, height)
    pm = QPixmap(int(w * ratio), int(h * ratio))
    pm.setDevicePixelRatio(ratio)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    grad = QLinearGradient(0, 0, w * 0.3, h)
    grad.setColorAt(0, QColor("#070c1c"))
    grad.setColorAt(0.55, QColor(BG))
    grad.setColorAt(1, QColor("#05070f"))
    p.fillRect(QRectF(0, 0, w, h), grad)

    # Milky Way glow: soft overlapping blobs along the band (no hard edges)
    p.setPen(Qt.NoPen)
    rnd = random.Random(SEED + 1)
    for i in range(46):
        t = i / 45
        bx, by = t * w, (0.95 - 0.8 * t) * h + rnd.gauss(0, 0.03) * h
        r = (0.10 + 0.07 * rnd.random()) * max(w, h)
        g = QRadialGradient(QPointF(bx, by), r)
        g.setColorAt(0, QColor(125, 150, 225, 10 + rnd.randint(0, 6)))
        g.setColorAt(1, QColor(125, 150, 225, 0))
        p.setBrush(g)
        p.drawEllipse(QPointF(bx, by), r, r)

    # Faint nebulae
    p.setPen(Qt.NoPen)
    for cx, cy, r, col in ((0.82, 0.18, 0.35, QColor(60, 90, 220, 34)),
                           (0.15, 0.85, 0.30, QColor(140, 70, 200, 24)),
                           (0.55, 0.45, 0.22, QColor(40, 140, 200, 14))):
        rg = QRadialGradient(QPointF(cx * w, cy * h), r * max(w, h))
        rg.setColorAt(0, col)
        c2 = QColor(col)
        c2.setAlpha(0)
        rg.setColorAt(1, c2)
        p.setBrush(rg)
        p.drawEllipse(QPointF(cx * w, cy * h), r * max(w, h), r * max(w, h))

    # Stars: number scales with the area so small windows are not crowded
    area_factor = min(1.0, (w * h) / (1600 * 900)) * density
    limit = int(len(_CATALOG) * max(area_factor, 0.25))
    p.setPen(Qt.NoPen)
    for x, y, mag, ci in _CATALOG[:limit]:
        px, py = x * w, y * h
        c = QColor(STAR_COLORS[ci])
        if mag > 0.9:  # bright star with glow
            glow = QRadialGradient(QPointF(px, py), 5 + 7 * mag)
            gc = QColor(c)
            gc.setAlpha(60)
            glow.setColorAt(0, gc)
            gc.setAlpha(0)
            glow.setColorAt(1, gc)
            p.setBrush(glow)
            p.drawEllipse(QPointF(px, py), 5 + 7 * mag, 5 + 7 * mag)
            if mag > 0.985:  # diffraction spikes for the very brightest
                sc = QColor(c)
                sc.setAlpha(55)
                p.setPen(QPen(sc, 0.8))
                s = 10 + 8 * mag
                p.drawLine(QPointF(px - s, py), QPointF(px + s, py))
                p.drawLine(QPointF(px, py - s), QPointF(px, py + s))
                p.setPen(Qt.NoPen)
            c.setAlpha(255)
            p.setBrush(c)
            p.drawEllipse(QPointF(px, py), 1.1 + 0.6 * mag, 1.1 + 0.6 * mag)
        else:
            c.setAlpha(int(40 + 190 * mag))
            p.setBrush(c)
            r = 0.45 + 1.1 * mag
            p.drawEllipse(QPointF(px, py), r, r)
    p.end()
    return pm


def render_image_background(image: QImage, width: int, height: int, ratio: float, dim: int, tint: str) -> QPixmap:
    """Photo scaled to cover the area (centre crop), darkened for readable text."""
    w, h = max(1, width), max(1, height)
    pm = QPixmap(int(w * ratio), int(h * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(QColor(tint))
    p = QPainter(pm)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    iw, ih = image.width(), image.height()
    if iw and ih:
        scale = max(w / iw, h / ih)
        sw, sh = w / scale, h / scale
        src = QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh)
        p.drawImage(QRectF(0, 0, w, h), image, src)
    overlay = QColor(tint)
    overlay.setAlpha(int(255 * max(0, min(dim, 95)) / 100))
    p.fillRect(QRectF(0, 0, w, h), overlay)
    # Vignette: slightly darker edges keep the focus on the content
    vg = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
    edge = QColor(tint)
    edge.setAlpha(0)
    vg.setColorAt(0.55, edge)
    edge.setAlpha(110)
    vg.setColorAt(1.0, edge)
    p.fillRect(QRectF(0, 0, w, h), vg)
    p.end()
    return pm


@lru_cache(maxsize=4)
def _load_image(path: str, mtime: float) -> QImage:
    img = QImage(path)
    if img.isNull():
        return img
    # Large images are reduced once; the background never needs more than ~2.5k px
    if img.width() > 2600:
        img = img.scaledToWidth(2600, Qt.SmoothTransformation)
    return img


class StarfieldWidget(QWidget):
    """Container widget that paints the chosen background behind its children.

    Modes: ``"sky"`` (procedural star field), ``"image"`` (photo) or ``"none"``.
    """

    def __init__(self, parent=None, enabled: bool = True):
        super().__init__(parent)
        self._cache: QPixmap | None = None
        self._mode = "sky" if enabled else "none"
        self._path: str | None = None
        self._dim = 45
        self._tint = BG
        self.setAttribute(Qt.WA_StyledBackground, False)

    @property
    def _enabled(self) -> bool:  # kept for compatibility
        return self._mode != "none"

    def set_enabled_sky(self, on: bool):
        self.set_background("sky" if on else "none")

    def set_background(self, mode: str, path=None, dim: int = 45, tint: str | None = None):
        self._mode, self._path, self._dim = mode, (str(path) if path else None), dim
        self._tint = tint or BG
        self._cache = None
        self.update()

    def resizeEvent(self, event):
        self._cache = None
        super().resizeEvent(event)

    def _render(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        if self._mode == "image" and self._path and os.path.isfile(self._path):
            img = _load_image(self._path, os.path.getmtime(self._path))
            if not img.isNull():
                return render_image_background(img, self.width(), self.height(), ratio, self._dim, self._tint)
        return render_starfield(self.width(), self.height(), ratio)

    def paintEvent(self, _event):
        p = QPainter(self)
        if self._mode == "none":
            p.fillRect(self.rect(), QColor(self._tint))
            return
        if self._cache is None or self._cache.deviceIndependentSize().toSize() != self.size():
            self._cache = self._render()
        p.drawPixmap(0, 0, self._cache)
