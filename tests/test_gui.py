import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from synthetic import planet_video  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    from frameforge.gui.settings import Settings
    return Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))


def _run(app, w):
    w.worker.wait(60000)
    for _ in range(3):
        app.processEvents()


def test_main_window_analysis_dashboard_and_project(app, tmp_path, settings, window_factory):
    from frameforge.gui.main_window import PAGE_OVERVIEW

    planet_video(tmp_path / "a.ser", n=15, base_blur=0.3, seed=1)
    planet_video(tmp_path / "b.ser", n=15, base_blur=2.5, seed=2)
    w = window_factory(settings)
    w.open_paths([tmp_path], replace=True)
    assert w.pages.currentIndex() == PAGE_OVERVIEW
    _run(app, w)
    assert w.session is not None and w.session.ranked()[0].path.name == "a.ser"
    # Dashboard filled
    assert w.overview.stack.currentIndex() == 2
    assert w.overview.details.rowCount() == 2
    assert "von 2 Dateien empfohlen" in w.overview.head_sub.text()
    # Session comparison in the analysis page
    w.table.selectAll()
    app.processEvents()
    assert len(w.plot._series) == 2
    # Project roundtrip through the GUI
    from frameforge.core.project import save_project
    proj = save_project(w.session, tmp_path / "p.ffproj", w.queue)
    w.clear_queue()
    assert w.overview.stack.currentIndex() == 0
    w.load_project_file(proj)
    assert w.session is not None and len(w.queue) == 2


def test_profile_sync_and_update_badge(app, settings, window_factory):
    from frameforge.gui.main_window import PAGE_SETTINGS
    from frameforge.updater import Asset, ReleaseInfo

    w = window_factory(settings)
    w._set_profile("deepsky")
    assert settings.get("analysis/profile") == "deepsky"
    assert w.profile_box.currentData() == "deepsky"
    assert w.settings_page.profile.currentData() == "deepsky"
    rel = ReleaseInfo("9.0.0", "v9.0.0", "", "Notes", "2026-01-01", "", False,
                      [Asset("FrameForge-9.0.0-windows-x64-setup.exe", "u", 1)])
    w._on_update_result(rel)
    assert "●" in w.nav_buttons[PAGE_SETTINGS].text()
    assert w.settings_page.release_box.isVisibleTo(w.settings_page)


def test_splash_and_welcome(app, settings):
    from frameforge.gui.app import _splash_pixmap
    from frameforge.gui.welcome import WelcomeDialog

    assert not _splash_pixmap(1.0).isNull()
    d = WelcomeDialog(settings)
    d.dont_show.setChecked(True)
    d._choose("folder")
    d.deleteLater()
    assert d.choice == "folder"
    assert settings.get("ui/show_welcome") is False


def test_open_external_project_and_crash_reporter(app, tmp_path, settings, window_factory):
    from frameforge.core.analyzer import AnalysisOptions, analyze_session
    from frameforge.core.project import save_project
    from frameforge.gui.crash import CrashReporter
    planet_video(tmp_path / "a.ser", n=10)
    proj = save_project(analyze_session([tmp_path], AnalysisOptions()), tmp_path / "x.ffproj")
    w = window_factory(settings)
    w.open_external([str(proj)])
    assert w.session is not None and w.worker is None
    assert CrashReporter() is not None


def test_trace_panel_shows_live_computation(app, tmp_path, settings, window_factory):
    import time

    planet_video(tmp_path / "a.ser", n=8)
    w = window_factory(settings)
    w.show()
    w.open_paths([tmp_path], replace=True)
    assert w.trace_panel.is_open()
    w.worker.wait(60000)
    end = time.time() + 2
    while time.time() < end:  # let the slide-in animation and the drain timer run
        app.processEvents()
    text = w.trace_panel.text()
    assert ">>> source = open_source('a.ser')" in text
    assert "frame[00007]" in text and "score = (" in text
    assert w.trace_panel.width() > 300
    w.toggle_trace()
    assert not w.trace_panel.is_open()


def test_backgrounds_and_matching_palettes(app, settings, window_factory):
    from frameforge.gui import theme
    from frameforge.gui.appearance import BACKGROUNDS, palette_for
    from frameforge.gui.starfield import render_starfield

    img = render_starfield(400, 300).toImage()
    assert sum(1 for x in range(0, 400, 2) for y in range(0, 300, 2) if img.pixelColor(x, y).lightness() > 150) > 5
    hues = {b.key: palette_for(b.key).hue for b in BACKGROUNDS if b.file}
    assert 5 <= hues["ngc7000"] <= 45          # orange H-alpha
    assert hues["orion"] >= 320 or hues["orion"] <= 10  # pink/red
    assert 180 <= hues["plejaden_m45"] <= 235  # blue reflection nebula
    w = window_factory(settings)
    for key in ("ngc7000", "none", "sky"):
        settings.set("ui/background", key)
        w.apply_appearance()
        assert theme.current().accent == palette_for(key).accent
    assert w.sky._mode == "sky"
    tiles = w.settings_page.bg_group.buttons()
    assert len(tiles) == len(BACKGROUNDS) + 1  # + custom image


def test_custom_background_image(app, settings, window_factory, tmp_path):
    import numpy as np
    from PIL import Image

    from frameforge.gui import theme

    rgb = np.zeros((120, 200, 3), np.uint8)
    rgb[..., 1] = 180  # green nebula
    rgb[::7, ::9] = 255
    path = tmp_path / "grün.png"
    Image.fromarray(rgb).save(path)
    settings.set("ui/background", "custom")
    settings.set("ui/background_custom", str(path))
    w = window_factory(settings)
    assert w.sky._mode == "image"
    assert 90 <= theme.current().hue <= 150
