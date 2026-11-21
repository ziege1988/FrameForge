"""AVI (and other container) video reader based on OpenCV.

Compressed videos cannot be seeked reliably, therefore this source reads
sequentially. Frames that are not requested are skipped with ``grab()``
(no decoding to user space), which keeps sampled analyses fast.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator

import cv2
import numpy as np

from .base import FrameSource, SourceInfo, UnsupportedFormatError, to_luminance


class VideoSource(FrameSource):
    random_access = False

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise UnsupportedFormatError(f"Video konnte nicht geöffnet werden: {self.path.name}")
        ok, first = cap.read()
        if not ok or first is None:
            cap.release()
            raise UnsupportedFormatError(f"Video enthält keine lesbaren Frames: {self.path.name}")
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
        cap.release()

        warnings: list[str] = []
        if count <= 0:
            count = self._count_frames()
            warnings.append("Frameanzahl war nicht im Container gespeichert und wurde gezählt.")

        self._is_mono = first.ndim == 2 or (
            np.array_equal(first[..., 0], first[..., 1]) and np.array_equal(first[..., 1], first[..., 2])
        )
        depth = 16 if first.dtype == np.uint16 else 8
        self.max_value = float(2**depth - 1)
        h, w = first.shape[:2]
        self.info = SourceInfo(
            path=self.path,
            format=self.path.suffix.upper().lstrip(".") or "VIDEO",
            width=w,
            height=h,
            frame_count=count,
            bit_depth=depth,
            color="mono" if self._is_mono else "bgr",
            is_video=True,
            fps=fps,
            duration_s=(count / fps) if fps else None,
            metadata={"codec": self._fourcc()},
            warnings=warnings,
        )

    def _fourcc(self) -> str:
        cap = cv2.VideoCapture(str(self.path))
        code = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        cap.release()
        text = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
        return text if text.isprintable() and text.strip("\x00") else "unbekannt"

    def _count_frames(self) -> int:
        cap = cv2.VideoCapture(str(self.path))
        n = 0
        while cap.grab():
            n += 1
        cap.release()
        return n

    def _convert(self, frame: np.ndarray) -> np.ndarray:
        if self._is_mono and frame.ndim == 3:
            frame = frame[..., 0]
        return to_luminance(frame, self.info.color, self.max_value)

    def raw_frames(self, indices: Iterable[int]) -> Iterator[tuple[int, np.ndarray]]:
        """Yield decoded frames (uint8, BGR or mono) for the given ascending indices."""
        wanted = sorted(set(int(i) for i in indices))
        if not wanted:
            return
        cap = cv2.VideoCapture(str(self.path))
        try:
            pos = 0
            for target in wanted:
                while pos < target:
                    if not cap.grab():
                        return
                    pos += 1
                ok, frame = cap.read()
                pos += 1
                if not ok or frame is None:
                    return
                if self._is_mono and frame.ndim == 3:
                    frame = frame[..., 0]
                yield target, frame
        finally:
            cap.release()

    def iter_frames(self, indices: Iterable[int] | None = None) -> Iterator[tuple[int, np.ndarray]]:
        if indices is None:
            indices = range(self.info.frame_count)
        for i, frame in self.raw_frames(indices):
            yield i, to_luminance(frame, self.info.color, self.max_value)

    def read_frame(self, index: int) -> np.ndarray:
        for _, frame in self.iter_frames([index]):
            return frame
        raise IndexError(index)

    def timestamps(self) -> np.ndarray | None:
        if self.info.fps:
            return np.arange(self.info.frame_count, dtype=np.float64) / self.info.fps
        return None
