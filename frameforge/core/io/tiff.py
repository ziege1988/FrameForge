"""TIFF reader (single and multi-page, 8/16/32 bit, mono or RGB) via tifffile."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import numpy as np
import tifffile

from .base import FrameSource, SourceInfo, UnsupportedFormatError, float_max_value, to_luminance


def _squeeze(arr: np.ndarray) -> np.ndarray:
    while arr.ndim > 2 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
        arr = np.moveaxis(arr, 0, -1)  # planar RGB
    if arr.ndim == 3 and arr.shape[-1] == 4:
        arr = arr[..., :3]
    return arr


class TiffSource(FrameSource):
    random_access = True

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        try:
            self._tif = tifffile.TiffFile(self.path)
            series = list(self._tif.series)
            first_series = series[0]
        except Exception as exc:
            raise UnsupportedFormatError(f"TIFF-Datei konnte nicht gelesen werden: {exc}") from exc

        self._readers: list[Callable[[], np.ndarray]] = []
        if len(series) > 1:
            # One series per page (typical for multi-page files written frame by frame).
            ref_shape = first_series.shape
            for s in series:
                if s.shape == ref_shape:
                    self._readers.append(s.asarray)
        elif len(first_series.pages) > 1 and first_series.pages[0] is not None \
                and len(first_series.pages[0].shape) <= 3:
            self._readers = [p.asarray for p in first_series.pages if p is not None]
        else:
            data = first_series.asarray()
            data = _squeeze(data)
            if data.ndim == 3 and data.shape[-1] not in (3,):
                self._stack = data
                self._readers = [lambda i=i: self._stack[i] for i in range(data.shape[0])]
            else:
                self._single = data
                self._readers = [lambda: self._single]

        first = _squeeze(self._readers[0]())
        if first.ndim not in (2, 3):
            raise UnsupportedFormatError(f"Nicht unterstützte TIFF-Struktur: {first_series.shape}")
        dtype = first.dtype
        if np.issubdtype(dtype, np.floating):
            self.max_value, depth = float_max_value(first), 32
        else:
            depth = int(dtype.itemsize * 8)
            self.max_value = float(np.iinfo(dtype).max)

        n = len(self._readers)
        h, w = first.shape[:2]
        self.info = SourceInfo(
            path=self.path,
            format="TIFF",
            width=int(w),
            height=int(h),
            frame_count=n,
            bit_depth=depth,
            color="rgb" if first.ndim == 3 else "mono",
            is_video=n > 1,
            metadata={"axes": first_series.axes, "pages": len(self._tif.pages)},
        )

    def read_frame(self, index: int) -> np.ndarray:
        if index < 0 or index >= self.info.frame_count:
            raise IndexError(index)
        arr = _squeeze(self._readers[index]())
        if np.issubdtype(arr.dtype, np.floating):
            arr = np.nan_to_num(arr.astype(np.float32), nan=0.0)
        return to_luminance(arr, self.info.color, self.max_value)

    def close(self) -> None:
        try:
            self._tif.close()
        except Exception:  # pragma: no cover
            pass
