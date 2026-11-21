"""Render the SVG logo into PNG/ICO/ICNS icons for the installers.

Usage: python packaging/make_icons.py  → packaging/icons/
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "frameforge" / "resources" / "logo.svg"
OUT = ROOT / "packaging" / "icons"


def render(size: int) -> Image.Image:
    img = QImage(size, size, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(SVG)).render(p, QRectF(0, 0, size, size))
    p.end()
    return Image.frombuffer("RGBA", (size, size), bytes(img.constBits()), "raw", "RGBA", 0, 1).copy()


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841
    OUT.mkdir(parents=True, exist_ok=True)
    big = render(1024)
    big.save(OUT / "frameforge.png")
    render(256).save(OUT / "frameforge.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    big.save(OUT / "frameforge.icns")
    print(f"Icons geschrieben nach {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
