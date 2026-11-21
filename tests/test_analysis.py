import json

import numpy as np
import pytest

from frameforge.core.analyzer import AnalysisOptions, analyze_file, analyze_session, sample_indices
from frameforge.core.export import export_best_frames, export_csv, export_frame_list, export_json
from frameforge.core.io import open_source
from frameforge.core.scoring import VERDICT_ERROR, VERDICT_REJECT, recommend_selection
from synthetic import planet, planet_video, write_ser


@pytest.fixture(scope="module")
def session_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("session")
    planet_video(d / "1_good.ser", base_blur=0.3, blur_spread=1.0, seed=1)
    planet_video(d / "2_medium.ser", base_blur=1.5, blur_spread=1.5, seed=2)
    planet_video(d / "3_bad.ser", base_blur=3.0, blur_spread=2.0, noise=0.03, jitter=6, seed=3)
    (d / "4_broken.ser").write_bytes(b"LUCAM-RECORDER" + b"\0" * 200)
    return d


def test_session_ranking(session_dir):
    s = analyze_session([session_dir], AnalysisOptions())
    ranked = [f.path.name for f in s.ranked()]
    assert ranked[:3] == ["1_good.ser", "2_medium.ser", "3_bad.ser"]
    broken = [f for f in s.files if f.path.name == "4_broken.ser"][0]
    assert broken.verdict == VERDICT_ERROR and broken.error
    bad = [f for f in s.files if f.path.name == "3_bad.ser"][0]
    assert bad.verdict == VERDICT_REJECT
    assert any("Bildunruhe" in r.text for r in bad.reasons)
    assert s.recommendations and "1_good.ser" in s.recommendations[0]
    good = s.ranked()[0]
    assert good.rank == 1 and good.reasons and good.recommendations


def test_single_file_has_no_relative_sharpness(tmp_path):
    p = planet_video(tmp_path / "only.ser", n=20)
    s = analyze_session([p], AnalysisOptions())
    f = s.files[0]
    assert f.components["sharpness"] is None
    assert any("ohne Vergleichsaufnahmen" in r.text for r in f.reasons)


def test_frame_quality_tracks_blur(tmp_path):
    blurs = [0.3, 3.0, 0.5, 4.0, 0.4, 3.5]
    write_ser(tmp_path / "v.ser", [planet(blur=b) for b in blurs])
    r = analyze_file(tmp_path / "v.ser", AnalysisOptions())
    sharp_frames = {0, 2, 4}
    assert set(np.argsort(-r.quality)[:3].tolist()) == sharp_frames
    assert r.best_index in sharp_frames


def test_sampling_and_cancel(tmp_path):
    import threading
    assert sample_indices(10, None).size == 10
    idx = sample_indices(5000, 200)
    assert idx.size == 200 and idx[0] == 0 and idx[-1] == 4999
    p = planet_video(tmp_path / "v.ser", n=30)
    ev = threading.Event()
    ev.set()
    with pytest.raises(InterruptedError):
        analyze_file(p, AnalysisOptions(), cancel=ev)


def test_recommend_selection_bounds():
    q = np.linspace(100, 10, 1000)
    frac, reason = recommend_selection(q, 1000)
    assert 0.05 <= frac <= 0.6 and reason
    frac_small, _ = recommend_selection(np.array([100, 20, 10, 5.0]), 4)
    assert frac_small == 1.0  # at least 50 frames → all of them
    assert recommend_selection(np.array([50.0]), 1)[0] == 1.0


def test_exports(tmp_path, session_dir):
    s = analyze_session([session_dir], AnalysisOptions())
    export_json(s, tmp_path / "r.json", include_frames=True)
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["files"][0]["name"] == "1_good.ser" and data["files"][0]["frames"]
    export_csv(s, tmp_path / "r.csv")
    text = (tmp_path / "r.csv").read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Rang;Datei")
    best = s.ranked()[0]
    export_frame_list(best, tmp_path / "f.csv", 0.5)
    assert (tmp_path / "f.csv").read_text(encoding="utf-8-sig").count("ja") == 20


def test_export_best_frames_ser(tmp_path):
    blurs = [0.3, 3.0, 0.5, 4.0, 0.4, 3.5, 0.6, 5.0]
    src_path = write_ser(tmp_path / "v.ser", [planet(blur=b) for b in blurs])
    r = analyze_file(src_path, AnalysisOptions())
    dest, n = export_best_frames(r, tmp_path / "best.ser", fraction=0.5)
    assert n == 4
    with open_source(src_path) as src, open_source(dest) as out:
        assert out.info.frame_count == 4
        for k, orig in enumerate([0, 2, 4, 6]):
            assert np.array_equal(out.raw_frame(k), src.raw_frame(orig))
        assert np.array_equal(out.raw_timestamps(), src.raw_timestamps()[[0, 2, 4, 6]])


def test_export_from_sampled_analysis_runs_full_analysis(tmp_path):
    p = planet_video(tmp_path / "long.ser", n=260)
    r = analyze_file(p, AnalysisOptions(mode="schnell"))
    assert r.sampled and r.analyzed_frames == 200
    dest, n = export_best_frames(r, tmp_path / "best.ser", fraction=0.1)
    assert n == 26


def test_project_roundtrip(tmp_path, session_dir):
    from frameforge.core.project import load_project, save_project

    s = analyze_session([session_dir], AnalysisOptions())
    p = save_project(s, tmp_path / "session")
    assert p.suffix == ".ffproj"
    loaded, queue = load_project(p)
    assert [f.path.name for f in loaded.ranked()] == [f.path.name for f in s.ranked()]
    a, b = s.ranked()[0], loaded.ranked()[0]
    assert np.array_equal(a.quality, b.quality) and np.array_equal(a.preview, b.preview)
    assert a.summary == b.summary and a.reasons[0].text == b.reasons[0].text
    assert b.best_frame_indices().size == a.best_frame_indices().size
    assert loaded.elapsed_s == pytest.approx(s.elapsed_s)
