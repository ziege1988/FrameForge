"""Simple line icons (own drawings, 24×24 SVG), coloured at runtime."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "home": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    "analysis": '<path d="M4 4v16h16"/><path d="m7 15 4-5 3 3 5-6"/>',
    "report": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 12h7M9 16h7M9 8h3"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r="0.6" fill="currentColor"/>',
    "folder": '<path d="M3 6.5V19h18V8.5h-9l-2-2.5H3z"/>',
    "folder-open": '<path d="M3 19V5h6l2 2.5h8V10"/><path d="M3 19l3-9h16l-3 9z"/>',
    "play": '<path d="M7 4.5v15L19.5 12z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "trophy": '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H4.5a3.5 3.5 0 0 0 3.8 4M16 6h3.5a3.5 3.5 0 0 1-3.8 4"/><path d="M12 13v4M8.5 20h7M10 17h4v3h-4z"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m7.8 12.3 2.8 2.8 5.6-5.8"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><circle cx="12" cy="16.3" r="0.6" fill="currentColor"/>',
    "warn": '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 9.5v4.5"/><circle cx="12" cy="17" r="0.6" fill="currentColor"/>',
    "expand": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "crop": '<path d="M6 2.5V18h15.5"/><path d="M2.5 6H18v15.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "planet": '<circle cx="12" cy="12" r="5.5"/><path d="M5.4 14.8C2.6 16.7 1.6 18.4 2.4 19.3c1.4 1.5 7.4-.9 13.3-5.4s9.4-9.5 8-11c-.8-.9-2.7-.4-5.2 1.2"/>',
    "deepsky": '<path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8zM5.5 15.5l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6z"/>',
    "general": '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 17 5-4.5 3.5 3 3-2.5 4.5 4"/>',
    "save": '<path d="M5 3.5h11l3.5 3.5V20.5H5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
    "export": '<path d="M12 15V3.5M7.5 8 12 3.5 16.5 8"/><path d="M5 13v7h14v-7"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "update": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4.5h-4.5"/>',
}


def svg(name: str, color: str = "#c9d2e6", stroke: float = 1.7) -> str:
    body = _PATHS[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=256)
def pixmap(name: str, size: int = 20, color: str = "#c9d2e6", ratio: float = 2.0) -> QPixmap:
    px = int(size * ratio)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str = "#c9d2e6", active_color: str | None = None, size: int = 20) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color), QIcon.Normal, QIcon.Off)
    if active_color:
        ic.addPixmap(pixmap(name, size, active_color), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, size, active_color), QIcon.Active, QIcon.On)
    ic.addPixmap(pixmap(name, size, "#4c5670"), QIcon.Disabled, QIcon.Off)
    return ic


PROFILE_ICONS = {"sun": "sun", "moon": "moon", "planet": "planet", "deepsky": "deepsky", "general": "general"}
