import numpy as np

from frameforge.core.metrics import compute_metrics, detect_object, estimate_noise
from frameforge.core.profiles import PROFILES
from synthetic import planet

P = PROFILES["planet"]


def test_sharpness_decreases_with_blur():
    values = [compute_metrics(planet(blur=b), P).sharpness for b in (0.3, 1.0, 2.0, 3.0, 5.0)]
    assert all(a > b for a, b in zip(values, values[1:]))


def test_sharpness_is_robust_against_noise():
    clean = compute_metrics(planet(blur=3.0), P).sharpness
    noisy = compute_metrics(planet(blur=3.0, noise=0.03), P).sharpness
    sharp_clean = compute_metrics(planet(blur=1.0), P).sharpness
    # Noise must not make a blurred frame look as sharp as a sharper one
    assert noisy < sharp_clean
    assert abs(noisy - clean) / clean < 0.25


def test_noise_estimate():
    rng = np.random.default_rng(0)
    img = np.clip(0.5 + rng.normal(0, 0.02, (256, 256)), 0, 1).astype(np.float32)
    assert abs(estimate_noise(img) - 0.02) < 0.003
    m = compute_metrics(planet(noise=0.01), P)
    assert abs(m.noise_sigma - 0.01) < 0.002


def test_sharpness_is_brightness_invariant():
    a = compute_metrics(planet(brightness=0.8, blur=1.0), P).sharpness
    b = compute_metrics(planet(brightness=0.4, blur=1.0), P).sharpness
    assert abs(a - b) / a < 0.05


def test_detection_and_edge_contact():
    det = detect_object(planet(), P)
    x, y, w, h = det.roi
    assert 40 < x < 100 and 40 < y < 100 and not det.touches_edge
    cut = detect_object(planet(shift=(110, 0)), P)
    assert cut.touches_edge


def test_exposure_and_clipping():
    m = compute_metrics(np.clip(planet(brightness=1.6), 0, 1), P)
    assert m.clip_high > 0.05
    dim = compute_metrics(planet(brightness=0.2), P)
    assert dim.peak < 0.25 and dim.clip_high == 0


def test_directional_blur_raises_coherence():
    import cv2
    base = planet(blur=0.5)
    kernel = np.zeros((1, 15), np.float32)
    kernel[0, :] = 1 / 15
    smeared = cv2.filter2D(base, -1, kernel)
    assert compute_metrics(smeared, P).coherence > compute_metrics(base, P).coherence + 0.1


def test_empty_frame_is_low_signal():
    m = compute_metrics(np.zeros((128, 128), np.float32), P)
    assert m.low_signal
