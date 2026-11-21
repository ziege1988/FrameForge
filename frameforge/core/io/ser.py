"""SER video reader/writer (Lucam Recorder format, used by FireCapture, SharpCap & Co.).

Frames are read individually on demand, so even very large SER files (tens of
GB) are processed without loading them into RAM.

Header layout (178 bytes, little endian integers)::

    0   char[14]  FileID "LUCAM-RECORDER"
    14  int32     LuID
    18  int32     ColorID
    22  int32     LittleEndian  (pixel byte order, see note below)
    26  int32     ImageWidth
    30  int32     ImageHeight
    34  int32     PixelDepthPerPlane
    38  int32     FrameCount
    42  char[40]  Observer
    82  char[40]  Instrument
    122 char[40]  Telescope
    162 int64     DateTime     (local, 100 ns ticks since 0001-01-01)
    170 int64     DateTime_UTC
    178 ...       image data, optionally followed by FrameCount int64 timestamps

Note: the meaning of the LittleEndian flag is interpreted inconsistently by
capture programs. FrameForge therefore determines the byte order of 16-bit
data from the image content (the correct order yields a smooth image).
"""

from __future__ import annotations

import os
import struct
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

from .base import FrameSource, SourceInfo, UnsupportedFormatError, to_luminance

HEADER_SIZE = 178
FILE_ID = b"LUCAM-RECORDER"

COLOR_IDS = {
    0: "mono",
    8: "bayer_RGGB",
    9: "bayer_GRBG",
    10: "bayer_GBRG",
    11: "bayer_BGGR",
    16: "bayer_CYYM",
    17: "bayer_YCMY",
    18: "bayer_YMCY",
    19: "bayer_MYYC",
    100: "rgb",
    101: "bgr",
}
COLOR_NAME_TO_ID = {v: k for k, v in COLOR_IDS.items()}

_TICKS_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


def ticks_to_datetime(ticks: int) -> datetime | None:
    if ticks <= 0:
        return None
    try:
        return _TICKS_EPOCH + timedelta(microseconds=ticks / 10)
    except OverflowError:
        return None


def datetime_to_ticks(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - _TICKS_EPOCH
    return (delta.days * 86400 + delta.seconds) * 10_000_000 + delta.microseconds * 10


def _decode_text(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()


def _smoothness(frame: np.ndarray) -> float:
    f = frame.astype(np.float64)
    if f.ndim == 3:
        f = f[..., 0]
    return float(np.mean(np.abs(np.diff(f, axis=1)))) + float(np.mean(np.abs(np.diff(f, axis=0))))


class SerSource(FrameSource):
    random_access = True

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        file_size = self.path.stat().st_size
        with open(self.path, "rb") as fh:
            header = fh.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE or not header.startswith(FILE_ID):
            raise UnsupportedFormatError(f"Keine gültige SER-Datei: {self.path.name}")

        lu_id, color_id, little_flag, width, height, depth, count = struct.unpack_from("<7i", header, 14)
        observer = _decode_text(header[42:82])
        instrument = _decode_text(header[82:122])
        telescope = _decode_text(header[122:162])
        dt_local, dt_utc = struct.unpack_from("<qq", header, 162)

        if width <= 0 or height <= 0 or depth <= 0 or depth > 32:
            raise UnsupportedFormatError(f"Ungültiger SER-Header: {self.path.name}")
        color = COLOR_IDS.get(color_id, "mono")
        planes = 3 if color in ("rgb", "bgr") else 1
        bytes_per_sample = 1 if depth <= 8 else 2
        self.frame_bytes = width * height * planes * bytes_per_sample
        warnings: list[str] = []
        if color_id not in COLOR_IDS:
            warnings.append(f"Unbekannte ColorID {color_id}, Daten werden als Mono interpretiert.")

        available = max(0, (file_size - HEADER_SIZE) // self.frame_bytes)
        if count <= 0 or count > available:
            if count > available:
                warnings.append(
                    f"Datei ist kürzer als im Header angegeben ({available} statt {count} Frames) – "
                    "möglicherweise unvollständig gespeichert."
                )
            count = available
        if count == 0:
            raise UnsupportedFormatError(f"SER-Datei enthält keine Frames: {self.path.name}")

        shape = (count, height, width) if planes == 1 else (count, height, width, planes)
        self.header = header
        self.color_id = color_id
        self.little_endian_flag = little_flag
        self.bytes_per_sample = bytes_per_sample
        self.planes = planes

        if bytes_per_sample == 1:
            self.byteorder = "|"
            self._dtype = np.dtype(np.uint8)
        else:
            self.byteorder = self._detect_byteorder(shape, depth, little_flag)
            self._dtype = np.dtype(self.byteorder + "u2")
        self._frame_shape = shape[1:]
        # Frames are read on demand with positioned reads: only the current
        # frame is held in memory, independent of the file size.
        self._fh = open(self.path, "rb", buffering=0)
        self._lock = threading.Lock()

        self.max_value = float(2**depth - 1)

        # Optional timestamp trailer
        self._timestamps: np.ndarray | None = None
        trailer_offset = HEADER_SIZE + count * self.frame_bytes
        if file_size >= trailer_offset + 8 * count:
            ts = np.fromfile(self.path, dtype="<i8", count=count, offset=trailer_offset)
            if ts.size == count and np.all(ts > 0):
                self._timestamps = ts

        fps = duration = None
        if self._timestamps is not None and count > 1:
            span = (int(self._timestamps[-1]) - int(self._timestamps[0])) / 1e7
            if span > 0:
                duration = span
                fps = (count - 1) / span

        start = ticks_to_datetime(dt_utc) or ticks_to_datetime(dt_local)
        self.info = SourceInfo(
            path=self.path,
            format="SER",
            width=width,
            height=height,
            frame_count=count,
            bit_depth=depth,
            color=color,
            is_video=True,
            fps=fps,
            duration_s=duration,
            metadata={
                "observer": observer,
                "instrument": instrument,
                "telescope": telescope,
                "start_utc": start.isoformat() if start else None,
                "byteorder": {"<": "little", ">": "big", "|": "n/a"}[self.byteorder],
            },
            warnings=warnings,
        )

    def _detect_byteorder(self, shape, depth: int, flag: int) -> str:
        """Choose the byte order that yields a plausible, smooth image."""
        n = shape[0]
        offset = HEADER_SIZE + (n // 2) * self.frame_bytes
        frame_shape = shape[1:]
        le = np.memmap(self.path, dtype="<u2", mode="r", offset=offset, shape=frame_shape)
        be = np.memmap(self.path, dtype=">u2", mode="r", offset=offset, shape=frame_shape)
        # Subsample large frames to keep this cheap.
        step = max(1, int(np.ceil(max(frame_shape[:2]) / 512)))
        le_s, be_s = np.array(le[::step, ::step]), np.array(be[::step, ::step])
        del le, be
        if depth < 16:
            limit = 2**depth - 1
            le_over = float(np.mean(le_s > limit))
            be_over = float(np.mean(be_s > limit))
            if abs(le_over - be_over) > 0.01:
                return "<" if le_over < be_over else ">"
        s_le, s_be = _smoothness(le_s), _smoothness(be_s)
        if s_le == s_be:
            return "<" if flag != 0 else ">"
        return "<" if s_le < s_be else ">"

    # ------------------------------------------------------------------
    def raw_frame(self, index: int) -> np.ndarray:
        if index < 0 or index >= self.info.frame_count:
            raise IndexError(index)
        with self._lock:
            self._fh.seek(HEADER_SIZE + index * self.frame_bytes)
            buf = self._fh.read(self.frame_bytes)
        if len(buf) != self.frame_bytes:
            raise OSError(f"Frame {index} konnte nicht vollständig gelesen werden.")
        return np.frombuffer(buf, dtype=self._dtype).reshape(self._frame_shape)

    def read_frame(self, index: int) -> np.ndarray:
        return to_luminance(self.raw_frame(index), self.info.color, self.max_value)

    def timestamps(self) -> np.ndarray | None:
        if self._timestamps is None:
            return None
        return (self._timestamps - self._timestamps[0]).astype(np.float64) / 1e7

    def raw_timestamps(self) -> np.ndarray | None:
        return self._timestamps

    def close(self) -> None:
        fh = getattr(self, "_fh", None)
        if fh is not None:
            fh.close()
            self._fh = None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def build_header(
    *,
    width: int,
    height: int,
    depth: int,
    frame_count: int,
    color: str = "mono",
    little_endian_flag: int = 0,
    observer: str = "",
    instrument: str = "",
    telescope: str = "FrameForge",
    start: datetime | None = None,
) -> bytes:
    start = start or datetime.now(timezone.utc)
    ticks = datetime_to_ticks(start)
    hdr = bytearray(HEADER_SIZE)
    hdr[0:14] = FILE_ID
    struct.pack_into(
        "<7i", hdr, 14, 0, COLOR_NAME_TO_ID.get(color, 0), little_endian_flag, width, height, depth, frame_count
    )
    for offset, text in ((42, observer), (82, instrument), (122, telescope)):
        raw = text.encode("latin-1", errors="replace")[:40]
        hdr[offset : offset + len(raw)] = raw
    struct.pack_into("<qq", hdr, 162, ticks, ticks)
    return bytes(hdr)


def write_ser_subset(source: SerSource, indices: Iterable[int], destination: str | os.PathLike,
                     progress=None, cancel=None) -> int:
    """Copy selected frames (raw bytes, unchanged) of a SER file into a new SER file.

    Frames are written in chronological order so that stacking software can
    still use temporal information. Returns the number of frames written.
    """
    idx = sorted(set(int(i) for i in indices))
    header = bytearray(source.header)
    struct.pack_into("<i", header, 38, len(idx))
    ts = source.raw_timestamps()
    dest = Path(destination)
    with open(source.path, "rb") as src, open(dest, "wb") as out:
        out.write(header)
        for n, i in enumerate(idx):
            if cancel is not None and cancel():
                raise InterruptedError("Export abgebrochen")
            src.seek(HEADER_SIZE + i * source.frame_bytes)
            out.write(src.read(source.frame_bytes))
            if progress and n % 25 == 0:
                progress(n, len(idx))
        if ts is not None:
            out.write(np.asarray(ts[idx], dtype="<i8").tobytes())
    if progress:
        progress(len(idx), len(idx))
    return len(idx)


def write_ser_frames(frames: Iterable[np.ndarray], destination: str | os.PathLike, *, width: int, height: int,
                     color: str, depth: int = 8, count: int, progress=None, cancel=None) -> int:
    """Write already decoded frames (uint8/uint16 arrays) into a new SER file."""
    dest = Path(destination)
    written = 0
    with open(dest, "wb") as out:
        out.write(build_header(width=width, height=height, depth=depth, frame_count=count, color=color,
                               little_endian_flag=0))
        dtype = np.uint8 if depth <= 8 else np.dtype("<u2")
        for frame in frames:
            if cancel is not None and cancel():
                raise InterruptedError("Export abgebrochen")
            out.write(np.ascontiguousarray(frame, dtype=dtype).tobytes())
            written += 1
            if progress and written % 25 == 0:
                progress(written, count)
        if written != count:
            out.seek(38)
            out.write(struct.pack("<i", written))
    if progress:
        progress(written, count)
    return written
