"""Generic 8/16 bit images (PNG, JPEG, BMP) via OpenCV."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from .base import FrameSource, SourceInfo, UnsupportedFormatError, to_luminance


class ImageSource(FrameSource):
    random_access = True

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        data = np.fromfile(self.path, dtype=np.uint8)  # supports non-ASCII paths on Windows
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise UnsupportedFormatError(f"Bild konnte nicht gelesen werden: {self.path.name}")
        if img.ndim == 3 and img.shape[2] == 4:
            img = img[..., :3]
        mono = img.ndim == 2
        self._img = img
        self.max_value = float(np.iinfo(img.dtype).max) if np.issubdtype(img.dtype, np.integer) else 1.0
        self.info = SourceInfo(
            path=self.path,
            format=self.path.suffix.upper().lstrip("."),
            width=int(img.shape[1]),
            height=int(img.shape[0]),
            frame_count=1,
            bit_depth=int(img.dtype.itemsize * 8),
            color="mono" if mono else "bgr",
            is_video=False,
        )

    def read_frame(self, index: int) -> np.ndarray:
        if index != 0:
            raise IndexError(index)
        return to_luminance(self._img, self.info.color, self.max_value)
