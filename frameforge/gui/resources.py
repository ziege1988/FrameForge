"""Access to bundled resources (works in source checkouts and PyInstaller builds)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "frameforge" / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def license_path() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "LICENSE" if base else Path(__file__).resolve().parents[2] / "LICENSE"


def logo_path() -> Path:
    return resource_dir() / "logo.svg"


def logo_pixmap(size: int, device_ratio: float = 1.0) -> QPixmap:
    px = int(size * device_ratio)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(str(logo_path()))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm.setDevicePixelRatio(device_ratio)
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        icon.addPixmap(logo_pixmap(s))
    return icon
