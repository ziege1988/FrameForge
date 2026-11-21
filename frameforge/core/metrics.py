"""Per-frame technical quality metrics.

All metrics are computed on a float32 luminance image (0..1). Wherever
possible they are normalised by the signal level so that frames with
different brightness (e.g. thin clouds) remain comparable.

Metrics
-------
sharpness       Standard deviation of the Laplacian of a lightly denoised
                image, divided by the mean signal (relative fine detail).
tenengrad       RMS Sobel gradient magnitude divided by the mean signal.
contrast        RMS contrast (std / mean) inside the object.
noise_sigma     Estimated Gaussian noise (Immerkaer 1996, edge pixels excluded).
snr             (object signal - background) / noise_sigma.
peak            99.5th percentile of the object (exposure level).
clip_high/low   Fraction of saturated / black object pixels.
coherence       Anisotropy of the structure tensor (0 = isotropic,
                1 = all gradients in one direction → directional blur).
blur_angle      Probable smear direction in degrees.
local_map       Sharpness per tile (NaN = tile without signal).
uniformity      1 - coefficient of variation of the local map.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .profiles import Profile

_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
_DETECT_SIZE = 256
THUMB_SIZE = 192


@dataclass
class Detection:
    roi: tuple[int, int, int, int]  # x, y, w, h (full resolution)
    threshold: float
    background: float
    object_fraction: float
    touches_edge: bool
    centroid: tuple[float, float]
    low_signal: bool
    surface: bool  # True if the object fills the frame (surface shot)


@dataclass
class FrameMetrics:
    index: int
    sharpness: float
    tenengrad: float
    contrast: float
    noise_sigma: float
    snr: float
    signal: float
    peak: float
    clip_high: float
    clip_low: float
    coherence: float
    blur_angle: float
    uniformity: float
    local_map: np.ndarray
    centroid_x: float
    centroid_y: float
    object_fraction: float
    touches_edge: bool
    low_signal: bool
    roi: tuple[int, int, int, int]
    thumb: np.ndarray | None = None
    # Deep-sky (star) metrics – NaN/0 for other profiles
    fwhm: float = float("nan")
    eccentricity: float = float("nan")
    star_count: int = 0
    background: float = float("nan")


SCALAR_FIELDS = (
    "sharpness", "tenengrad", "contrast", "noise_sigma", "snr", "signal", "peak", "clip_high",
    "clip_low", "coherence", "blur_angle", "uniformity", "centroid_x", "centroid_y",
    "object_fraction", "touches_edge", "low_signal", "fwhm", "eccentricity", "star_count", "background",
)


_KERNEL_ENERGY: dict[float, tuple[float, float]] = {}


def _noise_gain(sigma: float) -> tuple[float, float]:
    """Energy of the Gaussian+Laplacian and Gaussian+Sobel kernels.

    White noise with standard deviation s contributes s²·gain to the variance
    of the filtered image; this is subtracted so that noisy frames do not
    appear artificially sharp.
    """
    key = round(sigma, 3)
    if key not in _KERNEL_ENERGY:
        size = int(8 * sigma + 9) | 1
        delta = np.zeros((size, size), np.float32)
        delta[size // 2, size // 2] = 1.0
        g = cv2.GaussianBlur(delta, (0, 0), sigma)
        lap = cv2.Laplacian(g, cv2.CV_32F, ksize=3)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        _KERNEL_ENERGY[key] = (float(np.sum(lap * lap)), float(np.sum(gx * gx) + np.sum(gy * gy)))
    return _KERNEL_ENERGY[key]


def detect_object(frame: np.ndarray, profile: Profile) -> Detection:
    """Locate the main object (planet/moon/sun disc) or decide it fills the frame."""
    h, w = frame.shape
    f = min(1.0, _DETECT_SIZE / max(h, w))
    small = cv2.resize(frame, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else frame
    small = cv2.GaussianBlur(small, (3, 3), 0)
    lo, hi = np.percentile(small, (5, 99.5))
    lo, hi = float(lo), float(hi)
    sh, sw = small.shape
    if hi - lo < 0.02:
        return Detection((0, 0, w, h), lo, lo, 1.0, False, (w / 2, h / 2), True, True)

    thr = lo + 0.3 * (hi - lo)
    mask = (small > thr).astype(np.uint8)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return Detection((0, 0, w, h), thr, lo, 1.0, False, (w / 2, h / 2), True, True)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, area = (int(v) for v in stats[largest])
    fraction = area / float(sw * sh)
    cx, cy = centroids[largest]
    touches = x <= 1 or y <= 1 or x + bw >= sw - 1 or y + bh >= sh - 1
    bbox_fraction = (bw * bh) / float(sw * sh)
    surface = profile.roi_mode != "object" and (fraction > 0.35 or bbox_fraction > 0.6)

    if surface:
        bx, by = int(w * 0.02), int(h * 0.02)
        roi = (bx, by, w - 2 * bx, h - 2 * by)
        background = 0.0
    else:
        inv = 1.0 / f
        mx, my = max(8, int(bw * 0.15)), max(8, int(bh * 0.15))
        x0, y0 = max(0, x - mx), max(0, y - my)
        x1, y1 = min(sw, x + bw + mx), min(sh, y + bh + my)
        roi = (int(x0 * inv), int(y0 * inv), int(min(w, (x1 - x0) * inv)), int(min(h, (y1 - y0) * inv)))
        bg_pixels = small[labels == 0]
        background = float(np.median(bg_pixels)) if bg_pixels.size else lo
    return Detection(
        roi=roi,
        threshold=thr,
        background=background,
        object_fraction=fraction,
        touches_edge=bool(touches and not surface),
        centroid=(float(cx / f), float(cy / f)),
        low_signal=False,
        surface=surface,
    )


def make_thumb(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape
    f = THUMB_SIZE / max(h, w)
    t = cv2.resize(frame, (max(8, int(w * f)), max(8, int(h * f))), interpolation=cv2.INTER_AREA)
    return t.astype(np.float32)


def estimate_noise(img: np.ndarray, mask: np.ndarray | None = None, exclude_edges: float = 0.9) -> float:
    """Immerkaer's fast noise estimation with the strongest edges excluded.

    If ``mask`` is given only those pixels are used (the object: black sky is
    clipped at zero and would underestimate the noise).
    """
    if img.shape[0] < 8 or img.shape[1] < 8:
        return float(np.std(img)) or 1e-6
    conv = np.abs(cv2.filter2D(img, cv2.CV_32F, _IMMERKAER))[1:-1, 1:-1]
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)[1:-1, 1:-1]
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)[1:-1, 1:-1]
    grad = gx * gx + gy * gy
    if mask is not None:
        inner = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8))[1:-1, 1:-1].astype(bool)
        if inner.sum() >= 256:
            conv, grad = conv[inner], grad[inner]
    limit = np.quantile(grad, exclude_edges)
    sel = conv[grad <= limit]
    if sel.size < 16:
        sel = conv.ravel()
    sigma = np.sqrt(np.pi / 2.0) * float(np.mean(sel)) / 6.0
    return max(sigma, 1e-6)


def compute_metrics(frame: np.ndarray, profile: Profile, index: int = 0, scale: float = 1.0,
                    detection: Detection | None = None, with_thumb: bool = True) -> FrameMetrics:
    """Compute all quality metrics of one luminance frame."""
    if profile.key == "deepsky":
        from .deepsky import compute_star_metrics

        return compute_star_metrics(frame, profile, index, scale, with_thumb)
    det = detection or detect_object(frame, profile)
    x, y, w, h = det.roi
    roi = frame[y:y + h, x:x + w]
    if roi.size < 64:
        roi = frame
    if scale < 1.0:
        roi = cv2.resize(roi, (max(8, int(roi.shape[1] * scale)), max(8, int(roi.shape[0] * scale))),
                         interpolation=cv2.INTER_AREA)

    # Object mask inside the ROI
    if det.surface or det.low_signal:
        mask_thr = det.background + 0.1 * max(float(np.percentile(roi, 99.5)) - det.background, 0.0)
    else:
        mask_thr = det.threshold
    mask = roi > mask_thr
    if mask.sum() < 32:
        mask = np.ones_like(roi, dtype=bool)

    obj = roi[mask]
    signal = float(obj.mean())
    peak = float(np.percentile(obj, 99.5))
    clip_high = float(np.mean(obj >= 0.995))
    clip_low = float(np.mean(roi <= 0.002)) if det.surface else float(np.mean(obj <= 0.002))
    rel = max(signal, 1e-4)
    contrast = float(obj.std()) / rel

    noise = estimate_noise(roi, mask)
    sigma = profile.denoise_sigma * max(scale, 0.5)
    lap_gain, grad_gain = _noise_gain(sigma)
    noise_var = noise * noise
    g = cv2.GaussianBlur(roi, (0, 0), sigma)
    lap = cv2.Laplacian(g, cv2.CV_32F, ksize=3)
    lap_var = float(lap[mask].var()) - noise_var * lap_gain
    sharpness = float(np.sqrt(max(lap_var, 0.0))) / rel
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    gxm, gym = gx[mask], gy[mask]
    jxx, jyy, jxy = float(np.mean(gxm * gxm)), float(np.mean(gym * gym)), float(np.mean(gxm * gym))
    tenengrad = float(np.sqrt(max(jxx + jyy - noise_var * grad_gain, 0.0))) / rel
    # Remove the isotropic noise part before measuring anisotropy
    jxx_c = max(jxx - 0.5 * noise_var * grad_gain, 0.0)
    jyy_c = max(jyy - 0.5 * noise_var * grad_gain, 0.0)
    jxx, jyy = jxx_c, jyy_c
    tr = jxx + jyy
    disc = np.sqrt(max((jxx - jyy) ** 2 + 4 * jxy * jxy, 0.0))
    coherence = float(disc / tr) if tr > 1e-12 else 0.0
    grad_angle = 0.5 * np.degrees(np.arctan2(2 * jxy, jxx - jyy))
    blur_angle = float((grad_angle + 90.0) % 180.0)

    background = 0.0 if det.surface else det.background
    snr = max(signal - background, 0.0) / noise

    # Local quality map. For discs the limb edge is excluded, otherwise the
    # strong limb contrast would dominate the outer tiles.
    local_mask = mask
    if not det.surface:
        k = max(3, int(min(roi.shape) * 0.04) | 1)
        eroded = cv2.erode(mask.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
        if eroded.sum() > 0.3 * mask.sum():
            local_mask = eroded
    n = profile.grid
    local = np.full((n, n), np.nan, dtype=np.float32)
    th, tw = roi.shape[0] // n, roi.shape[1] // n
    if th >= 8 and tw >= 8:
        for r in range(n):
            for c in range(n):
                sl = (slice(r * th, (r + 1) * th), slice(c * tw, (c + 1) * tw))
                tm = local_mask[sl]
                if tm.mean() < 0.3:
                    continue
                tile_signal = float(g[sl][tm].mean())
                if tile_signal < 0.2 * signal:
                    continue
                tile_var = float(lap[sl][tm].var()) - noise_var * lap_gain
                local[r, c] = float(np.sqrt(max(tile_var, 0.0))) / max(tile_signal, 1e-4)
    valid = local[np.isfinite(local)]
    if valid.size >= 2 and valid.mean() > 0:
        uniformity = float(np.clip(1.0 - valid.std() / valid.mean(), 0.0, 1.0))
    else:
        uniformity = 1.0

    return FrameMetrics(
        index=index,
        sharpness=sharpness,
        tenengrad=tenengrad,
        contrast=contrast,
        noise_sigma=noise,
        snr=float(snr),
        signal=signal,
        peak=peak,
        clip_high=clip_high,
        clip_low=clip_low,
        coherence=coherence,
        blur_angle=blur_angle,
        uniformity=uniformity,
        local_map=local,
        centroid_x=det.centroid[0],
        centroid_y=det.centroid[1],
        object_fraction=det.object_fraction,
        touches_edge=det.touches_edge,
        low_signal=det.low_signal,
        roi=det.roi,
        thumb=make_thumb(frame) if with_thumb else None,
    )


def phase_shift(prev: np.ndarray, cur: np.ndarray) -> tuple[float, float]:
    """Sub-pixel translation between two thumbnails (in thumbnail pixels)."""
    if prev.shape != cur.shape:
        return 0.0, 0.0
    win = cv2.createHanningWindow((cur.shape[1], cur.shape[0]), cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(prev, cur, win)
    return float(dx), float(dy)
