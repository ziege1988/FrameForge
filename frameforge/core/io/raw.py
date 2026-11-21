"""Camera RAW reader (CR2, CR3, NEF, ARW, DNG, RAF, ORF, RW2, PEF …) via LibRaw/rawpy.

The Bayer mosaic is used directly (black level subtracted, 2x2 binned).
No demosaicing or colour processing is applied, so metrics reflect the
real sensor data.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .base import FrameSource, SourceInfo, UnsupportedFormatError, bin2x2


class RawSource(FrameSource):
    random_access = True

    def __init__(self, path: str | os.PathLike):
        import rawpy  # imported lazily: optional native dependency

        self.path = Path(path)
        try:
            # Pass a file object: LibRaw then reads from memory, which also works
            # for paths with umlauts/non-ASCII characters on Windows.
            with open(self.path, "rb") as fh, rawpy.imread(fh) as raw:
                mosaic = raw.raw_image_visible.astype(np.float32)
                black = float(np.mean(raw.black_level_per_channel))
                white = float(raw.white_level or mosaic.max() or 1.0)
                pattern = "".join(raw.color_desc.decode()[i] for i in raw.raw_pattern.flatten()) \
                    if raw.raw_pattern is not None else ""
                n_colors = int(raw.num_colors)
        except Exception as exc:
            raise UnsupportedFormatError(f"RAW-Datei konnte nicht gelesen werden: {exc}") from exc

        lum = bin2x2(mosaic) if mosaic.ndim == 2 else mosaic.mean(axis=2)
        lum = (lum - black) / max(white - black, 1.0)
        self._frame = np.clip(lum, 0.0, 1.0).astype(np.float32)
        depth = int(np.ceil(np.log2(max(white, 2.0))))
        pat = pattern[:4] if len(pattern) >= 4 else "RGGB"
        self.info = SourceInfo(
            path=self.path,
            format="RAW",
            width=int(mosaic.shape[1]),
            height=int(mosaic.shape[0]),
            frame_count=1,
            bit_depth=depth,
            color=f"bayer_{pat}" if n_colors >= 3 else "mono",
            is_video=False,
            metadata={"black_level": black, "white_level": white, "extension": self.path.suffix.lower()},
        )

    def read_frame(self, index: int) -> np.ndarray:
        if index != 0:
            raise IndexError(index)
        return self._frame
