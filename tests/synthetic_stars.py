"""Synthetic deep-sky frames: Gaussian stars on a noisy sky background."""

from __future__ import annotations

import numpy as np


def star_field(size=(400, 600), n_stars=150, fwhm=3.0, ecc=0.0, angle=0.0, background=0.08, noise=0.004,
               nebula=0.0, transparency=1.0, seed=0, star_seed=42) -> np.ndarray:
    h, w = size
    rng = np.random.default_rng(star_seed)  # identical star positions in every frame
    xs = rng.uniform(15, w - 15, n_stars)
    ys = rng.uniform(15, h - 15, n_stars)
    amps = rng.uniform(0.05, 0.6, n_stars) * transparency
    sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))
    # Eccentricity e: b/a = sqrt(1 - e²); keep the geometric mean of the axes = sigma
    ratio = np.sqrt(1 - ecc ** 2)
    sa, sb = sigma / ratio ** 0.5, sigma * ratio ** 0.5
    ca, sa_ = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.full((h, w), background, np.float32)
    if nebula:
        img += nebula * np.exp(-((xx - w * 0.4) ** 2 + (yy - h * 0.5) ** 2) / (2 * (w * 0.15) ** 2))
    for x, y, a in zip(xs, ys, amps):
        x0, x1, y0, y1 = int(x) - 12, int(x) + 13, int(y) - 12, int(y) + 13
        dx, dy = xx[y0:y1, x0:x1] - x, yy[y0:y1, x0:x1] - y
        u = dx * ca + dy * sa_
        v = -dx * sa_ + dy * ca
        img[y0:y1, x0:x1] += a * np.exp(-0.5 * ((u / sa) ** 2 + (v / sb) ** 2))
    img += np.random.default_rng(seed).normal(0, noise, img.shape).astype(np.float32)
    return np.clip(img, 0, 1)
