"""Star based metrics for deep-sky exposures (subs/lights).

For deep-sky images the classic sharpness measures are dominated by noise and
nebulosity. The established criteria (as used by subframe selectors) are:

FWHM          Star size in pixels (seeing, focus) – smaller is better.
Eccentricity  0 = round stars, → 1 = elongated (tracking, wind, tilt).
Star count    Number of detected stars (transparency, clouds, dew).
Background    Sky brightness (moon, light pollution, twilight).
Noise / SNR   Background noise and median star signal-to-noise ratio.

Star shapes are measured with intensity weighted second moments of all
pixels above 20 % of the peak. For a Gaussian profile the per-axis moment of
that truncated region is ``k(t)·σ²`` with
``k(t) = (1 - t·(1 - ln t)) / (1 - t)`` (t = 0.2 → k ≈ 0.598), so the
estimate is unbiased without a costly profile fit.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .metrics import FrameMetrics, make_thumb
from .profiles import Profile

_LEVEL = 0.2
_MOMENT_FACTOR = (1.0 - _LEVEL * (1.0 - math.log(_LEVEL))) / (1.0 - _LEVEL)
_FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))
_WINDOW = 10
_MAX_STARS = 400


def sky_background(img: np.ndarray) -> tuple[float, float]:
    """Sigma-clipped median and standard deviation of the sky background."""
    step = max(1, int(np.sqrt(img.size / 250_000)))
    sample = img[::step, ::step].ravel()
    med, sigma = float(np.median(sample)), float(np.std(sample))
    for _ in range(4):
        sel = sample[np.abs(sample - med) < 3 * max(sigma, 1e-6)]
        if sel.size < 100:
            break
        med = float(np.median(sel))
        sigma = 1.4826 * float(np.median(np.abs(sel - med)))
    return med, max(sigma, 1e-6)


def background_map(img: np.ndarray, cell: int = 32) -> np.ndarray:
    """Smooth large-scale background (gradients, nebulosity) for local subtraction."""
    h, w = img.shape
    small = cv2.resize(img, (max(4, w // cell), max(4, h // cell)), interpolation=cv2.INTER_AREA)
    small = cv2.medianBlur(small.astype(np.float32), 5)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def measure_star(cut: np.ndarray) -> tuple[float, float, float] | None:
    """FWHM (px), eccentricity and orientation (deg) of a star centred in ``cut``."""
    r = cut.shape[0] // 2
    peak = float(cut[r, r])
    if peak <= 0:
        return None
    mask = (cut >= _LEVEL * peak).astype(np.uint8)
    n, labels = cv2.connectedComponents(mask, connectivity=8)
    lab = labels[r, r]
    region = labels == lab
    ys, xs = np.nonzero(region)
    if xs.size < 3 or xs.min() == 0 or ys.min() == 0 or xs.max() == cut.shape[1] - 1 or ys.max() == cut.shape[0] - 1:
        return None  # hot pixel or too large / blended
    wgt = cut[region].astype(np.float64)
    tot = wgt.sum()
    cx, cy = float((wgt * xs).sum() / tot), float((wgt * ys).sum() / tot)
    dx, dy = xs - cx, ys - cy
    mxx = float((wgt * dx * dx).sum() / tot) / _MOMENT_FACTOR
    myy = float((wgt * dy * dy).sum() / tot) / _MOMENT_FACTOR
    mxy = float((wgt * dx * dy).sum() / tot) / _MOMENT_FACTOR
    # Pixel discretisation adds 1/12 px² per axis
    mxx, myy = max(mxx - 1 / 12, 1e-3), max(myy - 1 / 12, 1e-3)
    tr, det = mxx + myy, mxx * myy - mxy * mxy
    disc = math.sqrt(max(tr * tr / 4 - det, 0.0))
    l1, l2 = tr / 2 + disc, max(tr / 2 - disc, 1e-6)
    fwhm = _FWHM_PER_SIGMA * (l1 * l2) ** 0.25
    ecc = math.sqrt(max(0.0, 1.0 - l2 / l1))
    angle = math.degrees(0.5 * math.atan2(2 * mxy, mxx - myy)) % 180.0
    return fwhm, ecc, angle


def find_stars(img: np.ndarray, sigma: float, threshold: float = 5.0):
    """Return (x, y, peak) of isolated local maxima above ``threshold·sigma``."""
    sm = cv2.GaussianBlur(img, (0, 0), 1.0)
    dil = cv2.dilate(sm, np.ones((7, 7), np.uint8))
    peaks = (sm >= dil) & (sm > threshold * sigma)
    r = _WINDOW
    peaks[:r + 1, :] = peaks[-r - 1:, :] = False
    peaks[:, :r + 1] = peaks[:, -r - 1:] = False
    ys, xs = np.nonzero(peaks)
    if xs.size == 0:
        return []
    order = np.argsort(-sm[ys, xs])[: _MAX_STARS * 2]
    taken: list[tuple[int, int, float]] = []
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        if any(abs(x - tx) <= r and abs(y - ty) <= r for tx, ty, _ in taken):
            continue
        taken.append((x, y, float(sm[y, x])))
        if len(taken) >= _MAX_STARS:
            break
    return taken


def compute_star_metrics(frame: np.ndarray, profile: Profile, index: int = 0, scale: float = 1.0,
                         with_thumb: bool = True) -> FrameMetrics:
    img = frame
    if scale < 1.0:
        img = cv2.resize(frame, (max(16, int(frame.shape[1] * scale)), max(16, int(frame.shape[0] * scale))),
                         interpolation=cv2.INTER_AREA)
    h, w = img.shape
    bg, sigma = sky_background(img)
    resid = img - background_map(img)
    stars = find_stars(resid, sigma)

    measured = []
    r = _WINDOW
    for x, y, _ in stars:
        if img[y, x] >= 0.98:  # saturated core → shape not measurable
            continue
        m = measure_star(resid[y - r:y + r + 1, x - r:x + r + 1])
        if m is None or m[0] < 1.0:
            continue
        measured.append((x, y, *m, float(resid[y, x])))
    if measured:
        arr = np.array(measured)
        med_fwhm = float(np.median(arr[:, 2]))
        arr = arr[arr[:, 2] < 2.5 * med_fwhm]  # drop nebula knots / galaxies
    else:
        arr = np.zeros((0, 6))

    n_stars = int(arr.shape[0])
    if n_stars:
        fwhm = float(np.median(arr[:, 2]))
        # Shape of faint stars is dominated by noise → use the brighter half
        bright = arr[arr[:, 5] >= np.median(arr[:, 5])]
        ecc = float(np.median(bright[:, 3]))
        ang = np.radians(bright[:, 4] * 2)
        angle = float(np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) / 2 % 180)
        star_snr = float(np.median(arr[:, 5])) / sigma
    else:
        fwhm, ecc, angle, star_snr = float("nan"), float("nan"), 0.0, 0.0

    # FWHM across the field (tilt, field curvature, coma)
    n = 3
    local = np.full((n, n), np.nan, dtype=np.float32)
    if n_stars >= 9:
        tx = np.clip((arr[:, 0] / w * n).astype(int), 0, n - 1)
        ty = np.clip((arr[:, 1] / h * n).astype(int), 0, n - 1)
        for rr in range(n):
            for cc in range(n):
                sel = arr[(ty == rr) & (tx == cc), 2]
                if sel.size >= 2:
                    local[rr, cc] = 1.0 / float(np.median(sel))  # higher = sharper
    valid = local[np.isfinite(local)]
    uniformity = float(np.clip(1.0 - valid.std() / valid.mean(), 0, 1)) if valid.size >= 3 else 1.0

    inv = (1.0 / fwhm) if n_stars else 0.0
    return FrameMetrics(
        index=index,
        sharpness=inv,
        tenengrad=inv,
        contrast=float(n_stars),
        noise_sigma=sigma,
        snr=star_snr,
        signal=bg,
        peak=float(np.percentile(img, 99.9)),
        clip_high=float(np.mean(img >= 0.995)),
        clip_low=float(np.mean(img <= 0.001)),
        coherence=ecc if n_stars else 0.0,
        blur_angle=angle,
        uniformity=uniformity,
        local_map=local,
        centroid_x=frame.shape[1] / 2,
        centroid_y=frame.shape[0] / 2,
        object_fraction=1.0,
        touches_edge=False,
        low_signal=n_stars < 3,
        roi=(0, 0, frame.shape[1], frame.shape[0]),
        thumb=make_thumb(frame) if with_thumb else None,
        fwhm=fwhm / scale if n_stars else float("nan"),  # in original pixels
        eccentricity=ecc,
        star_count=n_stars,
        background=bg,
    )
