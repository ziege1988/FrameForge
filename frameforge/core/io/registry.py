"""Maps file extensions to readers."""

from __future__ import annotations

import os
from pathlib import Path

from .base import FrameSource, UnsupportedFormatError

RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf",
    ".orf", ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".kdc", ".mrw",
}
FORMAT_GROUPS = {
    "SER": {".ser"},
    "Video": {".avi", ".mp4", ".mov", ".mkv", ".m4v"},
    "FITS": {".fits", ".fit", ".fts"},
    "TIFF": {".tif", ".tiff"},
    "RAW": RAW_EXTENSIONS,
    "Bild": {".png", ".jpg", ".jpeg", ".bmp"},
}
SUPPORTED_EXTENSIONS = frozenset().union(*FORMAT_GROUPS.values())


def is_supported(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def open_source(path: str | os.PathLike) -> FrameSource:
    """Open a file with the matching reader."""
    p = Path(path)
    ext = p.suffix.lower()
    if not p.is_file():
        raise UnsupportedFormatError(f"Datei nicht gefunden: {p}")
    if ext == ".ser":
        from .ser import SerSource
        return SerSource(p)
    if ext in FORMAT_GROUPS["Video"]:
        from .video import VideoSource
        return VideoSource(p)
    if ext in FORMAT_GROUPS["FITS"]:
        from .fits import FitsSource
        return FitsSource(p)
    if ext in FORMAT_GROUPS["TIFF"]:
        from .tiff import TiffSource
        return TiffSource(p)
    if ext in RAW_EXTENSIONS:
        from .raw import RawSource
        return RawSource(p)
    if ext in FORMAT_GROUPS["Bild"]:
        from .image import ImageSource
        return ImageSource(p)
    raise UnsupportedFormatError(f"Nicht unterstütztes Format: {ext or p.name}")


def collect_files(paths, recursive: bool = True) -> list[Path]:
    """Expand folders into supported files (sorted, without duplicates)."""
    result: list[Path] = []
    seen: set[Path] = set()
    for item in paths:
        p = Path(item)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            candidates = sorted(c for c in it if c.is_file() and is_supported(c))
        elif p.is_file() and is_supported(p):
            candidates = [p]
        else:
            candidates = []
        for c in candidates:
            if c.name.startswith("._"):  # macOS resource forks
                continue
            key = c.resolve()
            if key not in seen:
                seen.add(key)
                result.append(c)
    return result
