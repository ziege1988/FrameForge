"""Application start: splash screen with logo, then the main window."""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .. import APP_NAME, APP_SUBTITLE, ORGANIZATION, __version__

SPLASH_MIN_SECONDS = 1.5


def _splash_pixmap(ratio: float) -> QPixmap:
    from .resources import logo_pixmap

    w, h = 560, 320
    pm = QPixmap(int(w * ratio), int(h * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor("#1b2440"))
    grad.setColorAt(1, QColor("#070a14"))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, w, h), 18, 18)
    p.drawPixmap(QRectF(36, 70, 150, 150), logo_pixmap(150, ratio), QRectF(0, 0, 150 * ratio, 150 * ratio))
    title = QFont()
    title.setPointSize(30)
    title.setBold(True)
    p.setFont(title)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(210, 92, 330, 50), Qt.AlignLeft | Qt.AlignVCenter, APP_NAME)
    sub = QFont()
    sub.setPointSize(12)
    p.setFont(sub)
    p.setPen(QColor("#ffb469"))
    p.drawText(QRectF(212, 140, 330, 24), Qt.AlignLeft | Qt.AlignVCenter, APP_SUBTITLE)
    p.setPen(QColor("#8b93a7"))
    p.drawText(QRectF(212, 166, 330, 24), Qt.AlignLeft | Qt.AlignVCenter, f"Version {__version__}")
    p.end()
    return pm


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(ORGANIZATION)
    QApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication(argv)

    splash = QSplashScreen(_splash_pixmap(app.devicePixelRatio()), Qt.WindowStaysOnTopHint)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.show()
    t0 = time.monotonic()

    def status(text: str):
        splash.showMessage(text, Qt.AlignBottom | Qt.AlignHCenter, QColor("#c9cedb"))
        app.processEvents()

    status("Lade Analysemodule …")
    import cv2  # noqa: F401  (heavy imports happen while the splash is visible)
    import numpy  # noqa: F401

    status("Lade Formate (SER, AVI, FITS, TIFF, RAW) …")
    from ..core import analyzer  # noqa: F401
    from ..core.io import fits, ser, tiff, video  # noqa: F401

    status("Starte Benutzeroberfläche …")
    from .main_window import MainWindow
    from .resources import app_icon
    from .theme import apply_theme

    apply_theme(app)
    app.setWindowIcon(app_icon())
    window = MainWindow()

    remaining = max(0.0, SPLASH_MIN_SECONDS - (time.monotonic() - t0))

    def show_main():
        window.show()
        splash.finish(window)
        # Command line arguments (e.g. files dropped on the app icon) are queued
        paths = [a for a in argv[1:] if not a.startswith("-")]
        if paths:
            from pathlib import Path
            window.add_paths([Path(p) for p in paths])
        QTimer.singleShot(1500, window.check_updates_silently)

    QTimer.singleShot(int(remaining * 1000), show_main)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
