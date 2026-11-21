"""Synthetic test data: planet-like discs with controllable blur, noise and drift."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from frameforge.core.io.ser import build_header


def planet(size: int = 256, radius: int = 70, blur: float = 0.0, noise: float = 0.0, shift=(0.0, 0.0),
           brightness: float = 0.7, seed: int = 0) -> np.ndarray:
    """Return a float image (0..1) of a banded planet disc on black sky."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx, cy = size / 2 + shift[0], size / 2 + shift[1]
    r = np.hypot(xx - cx, yy - cy)
    disc = (r < radius).astype(np.float32)
    limb = np.sqrt(np.clip(1 - (r / radius) ** 2, 0, 1))
    bands = 0.75 + 0.15 * np.sin((yy - cy) / 5.0) + 0.08 * np.sin((xx - cx) / 3.0 + (yy - cy) / 7.0)
    tex_rng = np.random.default_rng(1234)  # identical surface details in all frames
    detail = cv2.GaussianBlur(tex_rng.random((size, size)).astype(np.float32), (0, 0), 1.2)
    img = disc * limb * (bands + 0.25 * (detail - 0.5)) * brightness
    if blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    if noise > 0:
        img = img + rng.normal(0, noise, img.shape).astype(np.float32)
    return np.clip(img, 0, 1).astype(np.float32)


def write_ser(path: Path, frames: list[np.ndarray], depth: int = 8, flag: int = 0,
              byteorder: str = "<", timestamps: bool = True) -> Path:
    h, w = frames[0].shape
    with open(path, "wb") as fh:
        fh.write(build_header(width=w, height=h, depth=depth, frame_count=len(frames), little_endian_flag=flag))
        for f in frames:
            if depth <= 8:
                fh.write((f * 255).round().astype(np.uint8).tobytes())
            else:
                fh.write((f * (2**depth - 1)).round().astype(np.dtype(byteorder + "u2")).tobytes())
        if timestamps:
            ts = 638_000_000_000_000_000 + np.arange(len(frames), dtype=np.int64) * 200_000  # 20 ms
            fh.write(ts.astype("<i8").tobytes())
    return path


def planet_video(path: Path, n: int = 40, base_blur: float = 0.5, blur_spread: float = 2.0,
                 noise: float = 0.01, jitter: float = 1.0, seed: int = 0, depth: int = 8, **kw) -> Path:
    """Video where the blur varies frame by frame (simulated seeing)."""
    rng = np.random.default_rng(seed)
    blurs = base_blur + blur_spread * rng.random(n)
    frames = [
        planet(blur=float(b), noise=noise, shift=tuple(rng.normal(0, jitter, 2)), seed=seed * 1000 + i)
        for i, b in enumerate(blurs)
    ]
    write_ser(path, frames, depth=depth, **kw)
    return path
