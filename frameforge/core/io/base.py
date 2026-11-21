"""Common interface for all frame sources (single images and videos)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np


class UnsupportedFormatError(Exception):
    """Raised when a file cannot be read by any FrameForge reader."""


@dataclass
class SourceInfo:
    path: Path
    format: str  # e.g. "SER", "AVI", "FITS", "TIFF", "RAW"
    width: int
    height: int
    frame_count: int
    bit_depth: int
    color: str  # "mono", "rgb", "bgr" or "bayer_RGGB" / "bayer_GRBG" / ...
    is_video: bool
    fps: float | None = None
    duration_s: float | None = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_bayer(self) -> bool:
        return self.color.startswith("bayer")

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "bit_depth": self.bit_depth,
            "color": self.color,
            "is_video": self.is_video,
            "fps": self.fps,
            "duration_s": self.duration_s,
            "metadata": {k: _jsonable(v) for k, v in self.metadata.items()},
            "warnings": list(self.warnings),
        }


def _jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class FrameSource(ABC):
    """A readable sequence of frames.

    ``read_frame`` returns a 2-D float32 luminance image normalised to 0..1.
    Bayer data is binned 2x2 (no debayering) which halves the resolution but
    is fast, artefact free and sufficient for quality metrics.
    """

    info: SourceInfo
    #: True if frames can be read in any order cheaply.
    random_access: bool = True

    @abstractmethod
    def read_frame(self, index: int) -> np.ndarray: ...

    def iter_frames(self, indices: Iterable[int] | None = None) -> Iterator[tuple[int, np.ndarray]]:
        if indices is None:
            indices = range(self.info.frame_count)
        for i in indices:
            yield i, self.read_frame(i)

    def timestamps(self) -> np.ndarray | None:
        """Per-frame timestamps in seconds (relative to first frame) if known."""
        return None

    def close(self) -> None:  # pragma: no cover - trivial
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# Helpers shared by the readers
# ---------------------------------------------------------------------------

def bin2x2(arr: np.ndarray) -> np.ndarray:
    """Average 2x2 blocks (used to turn a Bayer mosaic into luminance)."""
    h, w = arr.shape[:2]
    h2, w2 = h - h % 2, w - w % 2
    a = arr[:h2, :w2].astype(np.float32, copy=False)
    return (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) * 0.25


def to_luminance(arr: np.ndarray, color: str, max_value: float, offset: float = 0.0) -> np.ndarray:
    """Convert raw frame data into a float32 luminance image in 0..1."""
    if color.startswith("bayer"):
        lum = bin2x2(arr)
    elif arr.ndim == 3 and arr.shape[2] >= 3:
        a = arr[..., :3].astype(np.float32, copy=False)
        if color == "bgr":
            lum = 0.114 * a[..., 0] + 0.587 * a[..., 1] + 0.299 * a[..., 2]
        else:
            lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    else:
        lum = arr.astype(np.float32, copy=True) if arr.ndim == 2 else arr[..., 0].astype(np.float32)
    if offset:
        lum = lum - np.float32(offset)
    scale = np.float32(1.0 / max(float(max_value) - offset, 1e-12))
    lum = lum * scale
    np.clip(lum, 0.0, 1.0, out=lum)
    return np.ascontiguousarray(lum, dtype=np.float32)


def float_max_value(sample: np.ndarray) -> float:
    """Guess the full-scale value of floating point data (FITS/TIFF)."""
    finite = sample[np.isfinite(sample)]
    if finite.size == 0:
        return 1.0
    peak = float(finite.max())
    if peak <= 1.0 + 1e-6:
        return 1.0
    if peak <= 255.0:
        return 255.0
    if peak <= 65535.0:
        return 65535.0
    return peak
