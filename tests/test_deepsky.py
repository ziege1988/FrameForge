
import numpy as np
import pytest
from astropy.io import fits

from frameforge.core.analyzer import AnalysisOptions, analyze_session
from frameforge.core.deepsky import compute_star_metrics
from frameforge.core.profiles import PROFILES
from frameforge.core.scoring import VERDICT_RECOMMENDED, VERDICT_REJECT
from synthetic_stars import star_field

P = PROFILES["deepsky"]


@pytest.mark.parametrize("fwhm", [2.5, 3.0, 5.0, 8.0])
def test_fwhm_is_measured_accurately(fwhm):
    m = compute_star_metrics(star_field(fwhm=fwhm), P)
    assert m.fwhm == pytest.approx(fwhm, rel=0.08)
    assert m.star_count > 100


def test_eccentricity_and_direction():
    round_ = compute_star_metrics(star_field(fwhm=3.5), P)
    long_ = compute_star_metrics(star_field(fwhm=3.5, ecc=0.7, angle=30), P)
    assert round_.eccentricity < 0.45
    assert long_.eccentricity == pytest.approx(0.7, abs=0.07)
    assert long_.blur_angle == pytest.approx(30, abs=8)


def test_nebula_does_not_break_measurement():
    m = compute_star_metrics(star_field(fwhm=3.0, nebula=0.3), P)
    assert m.fwhm == pytest.approx(3.0, rel=0.1)


def test_empty_sky_is_low_signal():
    m = compute_star_metrics(star_field(n_stars=0), P)
    assert m.low_signal and m.star_count == 0


def test_downscaled_fwhm_reported_in_original_pixels():
    m = compute_star_metrics(star_field(size=(600, 900), fwhm=6.0), P, scale=0.5)
    assert m.fwhm == pytest.approx(6.0, rel=0.1)


def test_deepsky_session(tmp_path):
    specs = {"L1": dict(fwhm=3.0), "L2": dict(fwhm=3.1), "L3": dict(fwhm=3.05),
             "L_trail": dict(fwhm=3.1, ecc=0.75, angle=60), "L_blur": dict(fwhm=4.6)}
    for i, (name, kw) in enumerate(specs.items()):
        img = (star_field(seed=i, **kw) * 65535).astype(np.uint16)
        fits.PrimaryHDU(img).writeto(tmp_path / f"{name}.fit")
    s = analyze_session([tmp_path], AnalysisOptions(profile="deepsky"))
    by = {f.path.stem: f for f in s.files}
    assert by["L_trail"].verdict == VERDICT_REJECT and "Gestreckte" in by["L_trail"].summary
    assert by["L_blur"].verdict == VERDICT_REJECT
    assert by["L1"].verdict == VERDICT_RECOMMENDED
    assert {f.path.stem for f in s.ranked()[:3]} == {"L1", "L2", "L3"}


def test_clouded_sub_is_rejected(tmp_path):
    for i in range(4):
        fits.PrimaryHDU((star_field(seed=i, fwhm=3.0) * 65535).astype(np.uint16)).writeto(tmp_path / f"ok{i}.fit")
    cloud = star_field(seed=9, fwhm=3.0, transparency=0.12, background=0.22)
    fits.PrimaryHDU((cloud * 65535).astype(np.uint16)).writeto(tmp_path / "cloud.fit")
    s = analyze_session([tmp_path], AnalysisOptions(profile="deepsky"))
    cloud_res = [f for f in s.files if f.path.stem == "cloud"][0]
    assert cloud_res.verdict == VERDICT_REJECT
    assert s.ranked()[-1].path.stem == "cloud"
