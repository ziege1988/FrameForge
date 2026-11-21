"""FITS reader (single images, RGB images and frame cubes).

A small native parser is used: FITS images consist of 2880-byte header blocks
with 80-character cards followed by big-endian pixel data. The data is memory
mapped and scaled (BZERO/BSCALE) frame by frame, so large cubes are never
loaded completely. Tile-compressed FITS (fpack, ``.fz``) is read via astropy
if it is installed.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .base import FrameSource, SourceInfo, UnsupportedFormatError, float_max_value, to_luminance

BLOCK = 2880
CARD = 80
_DTYPES = {8: ">u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}
_BAYER_KEYS = ("BAYERPAT", "COLORTYP", "CFA-PAT")


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("'"):
        # String: '' is an escaped quote, the value ends at the next single quote
        out, i = [], 1
        while i < len(raw):
            if raw[i] == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(raw[i])
            i += 1
        return "".join(out).rstrip()
    value = raw.split("/", 1)[0].strip()
    if value == "T":
        return True
    if value == "F":
        return False
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value.replace("D", "E"))
    except ValueError:
        return value


def read_header(fh) -> tuple[dict, int] | None:
    """Read one header unit from the current position. Returns (cards, data offset)."""
    header: dict = {}
    while True:
        block = fh.read(BLOCK)
        if len(block) < BLOCK:
            return None
        text = block.decode("ascii", errors="replace")
        for i in range(0, BLOCK, CARD):
            card = text[i:i + CARD]
            key = card[:8].strip()
            if key == "END":
                return header, fh.tell()
            if card[8:10] == "= " and key and key not in header:
                header[key] = _parse_value(card[10:])


def data_size(h: dict) -> int:
    naxis = int(h.get("NAXIS", 0))
    if naxis == 0:
        return 0
    n = 1
    for i in range(1, naxis + 1):
        n *= int(h.get(f"NAXIS{i}", 0))
    n = (n + int(h.get("PCOUNT", 0))) * int(h.get("GCOUNT", 1))
    return n * abs(int(h.get("BITPIX", 8))) // 8


def find_image_hdu(path: Path) -> tuple[dict, int] | tuple[None, str]:
    """Locate the first HDU with image data. Returns (header, offset) or (None, reason)."""
    size = path.stat().st_size
    with open(path, "rb") as fh:
        first = True
        while fh.tell() < size:
            res = read_header(fh)
            if res is None:
                break
            h, offset = res
            if first and h.get("SIMPLE") is not True:
                return None, "Keine gültige FITS-Datei (SIMPLE fehlt)."
            first = False
            xt = str(h.get("XTENSION", "")).strip().upper()
            if (xt in ("", "IMAGE")) and int(h.get("NAXIS", 0)) >= 2:
                return h, offset
            if xt == "BINTABLE" and h.get("ZIMAGE") is True:
                return None, "compressed"
            nbytes = data_size(h)
            fh.seek(offset + ((nbytes + BLOCK - 1) // BLOCK) * BLOCK)
    return None, "FITS-Datei enthält keine Bilddaten."


class FitsSource(FrameSource):
    random_access = True

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        try:
            hdr, where = find_image_hdu(self.path)
        except OSError as exc:
            raise UnsupportedFormatError(f"FITS-Datei konnte nicht gelesen werden: {exc}") from exc
        self._hdul = None
        if hdr is None:
            if where == "compressed":
                hdr, data = self._open_compressed()
            else:
                raise UnsupportedFormatError(f"{where} ({self.path.name})")
        else:
            bitpix = int(hdr["BITPIX"])
            if bitpix not in _DTYPES:
                raise UnsupportedFormatError(f"Nicht unterstütztes BITPIX {bitpix}: {self.path.name}")
            naxis = int(hdr["NAXIS"])
            shape = tuple(int(hdr[f"NAXIS{i}"]) for i in range(naxis, 0, -1))
            if np.prod(shape) * abs(bitpix) // 8 + where > self.path.stat().st_size:
                raise UnsupportedFormatError(f"FITS-Datei ist unvollständig: {self.path.name}")
            data = np.memmap(self.path, dtype=_DTYPES[bitpix], mode="r", offset=where, shape=shape)
        self.bzero = float(hdr.get("BZERO", 0.0) or 0.0)
        self.bscale = float(hdr.get("BSCALE", 1.0) or 1.0)
        warnings: list[str] = []

        # Drop leading singleton axes
        while data.ndim > 2 and data.shape[0] == 1:
            data = data[0]
        if data.ndim == 2:
            self._layout = "single"
            n, h, w = 1, data.shape[0], data.shape[1]
        elif data.ndim == 3 and data.shape[0] == 3:
            self._layout = "rgb_planar"
            n, h, w = 1, data.shape[1], data.shape[2]
        else:
            self._layout = "cube"
            if data.ndim > 3:
                data = data.reshape((-1,) + data.shape[-2:])
                warnings.append("Mehrdimensionale FITS-Daten wurden als Frame-Folge interpretiert.")
            n, h, w = data.shape
        self._data = data

        bayer = None
        for key in _BAYER_KEYS:
            val = str(hdr.get(key, "") or "").strip().upper()
            if val in ("RGGB", "GRBG", "GBRG", "BGGR"):
                bayer = val
                break
        color = "rgb" if self._layout == "rgb_planar" else (f"bayer_{bayer}" if bayer else "mono")

        bitpix = int(hdr.get("BITPIX", 16))
        if bitpix == 8:
            self.max_value, depth = 255.0, 8
        elif bitpix == 16:
            # Unsigned 16 bit is stored as signed + BZERO 32768
            self.max_value, depth = (65535.0 if self.bzero >= 32768 else 32767.0), 16
        elif bitpix == 32:
            self.max_value, depth = (4294967295.0 if self.bzero >= 2**31 else 2147483647.0), 32
        else:
            self.max_value, depth = float_max_value(self._scaled(0 if n == 1 else n // 2)), 32

        exptime = hdr.get("EXPTIME", hdr.get("EXPOSURE"))
        self.info = SourceInfo(
            path=self.path,
            format="FITS",
            width=int(w),
            height=int(h),
            frame_count=int(n),
            bit_depth=depth,
            color=color,
            is_video=n > 1,
            metadata={
                "object": hdr.get("OBJECT"),
                "date_obs": hdr.get("DATE-OBS"),
                "exptime": exptime,
                "gain": hdr.get("GAIN"),
                "instrument": hdr.get("INSTRUME"),
                "telescope": hdr.get("TELESCOP"),
                "filter": hdr.get("FILTER"),
            },
            warnings=warnings,
        )
        if isinstance(exptime, (int, float)) and n > 1:
            self.info.duration_s = float(exptime) * n

    def _open_compressed(self):
        try:
            from astropy.io import fits  # optional dependency
        except ImportError as exc:
            raise UnsupportedFormatError(
                "Komprimierte FITS-Datei (fpack) – bitte unkomprimiert speichern oder astropy installieren."
            ) from exc
        self._hdul = fits.open(self.path)  # compressed tiles must be decompressed anyway
        for hdu in self._hdul:
            if hdu.is_image and hdu.data is not None and hdu.data.ndim >= 2:
                hdr = dict(hdu.header)
                hdr["BZERO"], hdr["BSCALE"] = 0.0, 1.0  # astropy already scaled the data
                hdr["BITPIX"] = -32
                return hdr, hdu.data
        raise UnsupportedFormatError(f"FITS-Datei enthält keine Bilddaten: {self.path.name}")

    def _scaled(self, index: int) -> np.ndarray:
        if self._layout == "single":
            raw = np.asarray(self._data)
        elif self._layout == "rgb_planar":
            raw = np.moveaxis(np.asarray(self._data), 0, -1)
        else:
            raw = np.asarray(self._data[index])
        arr = raw.astype(np.float32)
        if self.bscale != 1.0:
            arr *= np.float32(self.bscale)
        if self.bzero:
            arr += np.float32(self.bzero)
        return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    def read_frame(self, index: int) -> np.ndarray:
        if index < 0 or index >= self.info.frame_count:
            raise IndexError(index)
        return to_luminance(self._scaled(index), self.info.color, self.max_value)

    def close(self) -> None:
        self._data = None
        if self._hdul is not None:
            try:
                self._hdul.close()
            except Exception:  # pragma: no cover
                pass
