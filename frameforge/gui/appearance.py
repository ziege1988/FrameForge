"""Background images and matching colour palettes.

Built-in backgrounds are astrophotos bundled in ``resources/backgrounds``.
Users can also pick their own image. For every image the dominant nebula hue
is determined (saturation-weighted hue histogram of the coloured pixels) and
the whole interface palette is derived from it, so menus and buttons always
match the background.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .resources import resource_dir
from .theme import DEFAULT_PALETTE, Palette


@dataclass(frozen=True)
class Background:
    key: str
    name: str
    file: str | None  # None = procedural star field / plain
    description: str = ""


BACKGROUNDS: list[Background] = [
    Background("sky", "Sternenhimmel", None, "Erzeugter Nachthimmel mit Milchstraße (blau)"),
    Background("orion", "Orion-Region", "orion.jpg", "Barnards Loop, Pferdekopf- und Orionnebel"),
    Background("ngc7000", "Nordamerikanebel", "ngc7000.jpg", "NGC 7000 in H-Alpha"),
    Background("plejaden_m45", "Plejaden (M45)", "plejaden_m45.jpg", "Reflexionsnebel mit Beugungsstrahlen"),
    Background("plejaden_weitfeld", "Plejaden Weitfeld", "plejaden_weitfeld.jpg", "M45 mit umgebendem Staub"),
    Background("polaris", "Polaris-Region", "polaris.jpg", "Integrated Flux Nebula um den Polarstern"),
    Background("none", "Schlicht", None, "Einfarbig dunkel, ohne Motiv"),
]
BY_KEY = {b.key: b for b in BACKGROUNDS}
CUSTOM = "custom"
DEFAULT_DIM = 35


def background_path(bg: Background) -> Path | None:
    return resource_dir() / "backgrounds" / bg.file if bg.file else None


def read_image(path: str | os.PathLike) -> np.ndarray | None:
    """BGR image (also for non-ASCII paths on Windows)."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def dominant_hue(img: np.ndarray) -> tuple[float, float]:
    """(hue in degrees, colourfulness 0..1) of the coloured parts of an image."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (240, max(1, int(240 * h / w))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV_FULL).reshape(-1, 3).astype(np.float64)
    hue, sat, val = hsv[:, 0] * 360 / 256, hsv[:, 1] / 255, hsv[:, 2] / 255
    mask = (sat > 0.15) & (val > 0.12) & (val < 0.97)
    if mask.sum() < 50:
        return 217.0, 0.0
    weights = (sat * val)[mask] ** 2
    hist, _ = np.histogram(hue[mask], bins=36, range=(0, 360), weights=weights)
    smooth = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, "valid")
    colourfulness = float(np.clip(sat[mask].mean() * mask.mean() * 4, 0, 1))
    return float((np.argmax(smooth) + 0.5) * 10), colourfulness


@lru_cache(maxsize=16)
def _palette_for_file(path: str, mtime: float) -> Palette:
    img = read_image(path)
    if img is None:
        return DEFAULT_PALETTE
    hue, colourful = dominant_hue(img)
    return Palette.from_hue(hue, Path(path).stem, vivid=0.55 + 0.2 * colourful)


def palette_for(key: str, custom_path: str = "") -> Palette:
    if key == CUSTOM:
        p = Path(custom_path)
        return _palette_for_file(str(p), p.stat().st_mtime) if p.is_file() else DEFAULT_PALETTE
    bg = BY_KEY.get(key)
    path = background_path(bg) if bg else None
    if path is None or not path.is_file():
        return DEFAULT_PALETTE
    return _palette_for_file(str(path), path.stat().st_mtime)


def image_path_for(key: str, custom_path: str = "") -> Path | None:
    if key == CUSTOM:
        p = Path(custom_path)
        return p if p.is_file() else None
    bg = BY_KEY.get(key)
    return background_path(bg) if bg else None


def resolve(settings) -> tuple[str, Path | None, int, Palette]:
    """(mode, image path, dim %, palette) from the user settings."""
    key = settings.get("ui/background")
    custom = settings.get("ui/background_custom") or ""
    dim = int(settings.get("ui/background_dim"))
    if key == CUSTOM and not Path(custom).is_file():
        key = "sky"
    if key not in BY_KEY and key != CUSTOM:
        key = "sky"
    path = image_path_for(key, custom)
    mode = "image" if path is not None else key  # "sky" or "none"
    return mode, path, dim, palette_for(key, custom)
