"""Application start: splash screen with logo, then the main window."""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .. import APP_NAME, APP_SUBTITLE, ORGANIZATION, __version__

SPLASH_MIN_SECONDS = 1.5


def _splash_pixmap(ratio: float) -> QPixmap:
    from .resources import logo_pixmap

    w, h = 640, 360
    pm = QPixmap(int(w * ratio), int(h * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor("#0d1a3d"))
    grad.setColorAt(1, QColor("#050914"))
    p.setBrush(grad)
    p.setPen(QColor("#1e2a46"))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
    p.drawPixmap(QRectF(28, 62, 230, 230), logo_pixmap(230, ratio), QRectF(0, 0, 230 * ratio, 230 * ratio))

    title = QFont()
    title.setPointSize(38)
    title.setBold(True)
    title.setItalic(True)
    p.setFont(title)
    fm = p.fontMetrics()
    x, base = 282, 168
    p.setPen(QColor("#ffffff"))
    p.drawText(x, base, "Frame")
    fx = x + fm.horizontalAdvance("Frame")
    blue = QLinearGradient(fx, 0, fx + fm.horizontalAdvance("Forge"), 0)
    blue.setColorAt(0, QColor("#5aa0ff"))
    blue.setColorAt(1, QColor("#2f6bff"))
    p.setPen(QPen(blue, 1))
    p.drawText(fx, base, "Forge")

    slogan = QFont()
    slogan.setPointSize(14)
    slogan.setItalic(True)
    p.setFont(slogan)
    sx = x + 2
    for word, bold in (("Analyse. ", False), ("Entscheide. ", True), ("Perfektioniere.", False)):
        slogan.setBold(bold)
        p.setFont(slogan)
        p.setPen(QColor("#dfe7f7"))
        p.drawText(sx, base + 36, word)
        sx += p.fontMetrics().horizontalAdvance(word)
    small = QFont()
    small.setPointSize(10)
    p.setFont(small)
    p.setPen(QColor("#8a94ad"))
    p.drawText(QRectF(x + 2, base + 52, 330, 20), Qt.AlignLeft | Qt.AlignVCenter,
               f"{APP_SUBTITLE} · Version {__version__}")
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
        splash.showMessage(text + "   ", Qt.AlignBottom | Qt.AlignRight, QColor("#8a94ad"))
        app.processEvents()

    status("Lade Analysemodule …")
    import cv2  # noqa: F401  (heavy imports happen while the splash is visible)
    import numpy  # noqa: F401

    status("Lade Formate (SER, AVI, MP4, FITS, TIFF, RAW) …")
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
        # Files passed on the command line / dropped on the app icon are queued directly
        paths = [a for a in argv[1:] if not a.startswith("-")]
        if paths:
            from pathlib import Path
            window.open_paths([Path(p) for p in paths])
        elif window.settings.get("ui/show_welcome"):
            QTimer.singleShot(150, window.show_welcome)
        QTimer.singleShot(2500, window.check_updates_silently)

    QTimer.singleShot(int(remaining * 1000), show_main)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
