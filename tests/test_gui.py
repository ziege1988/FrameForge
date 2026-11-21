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
