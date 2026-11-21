import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from synthetic import planet_video  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from frameforge.gui.theme import apply_theme
    a = QApplication.instance() or QApplication([])
    apply_theme(a)
    return a


def test_main_window_analysis(app, tmp_path):
    from frameforge.gui.main_window import MainWindow
    from frameforge.gui.settings import Settings

    planet_video(tmp_path / "a.ser", n=15, base_blur=0.3, seed=1)
    planet_video(tmp_path / "b.ser", n=15, base_blur=2.5, seed=2)
    settings = Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    w = MainWindow(settings)
    w.add_paths([tmp_path])
    assert len(w.queue) == 2
    w.start_analysis()
    w.worker.wait(60000)
    app.processEvents()
    app.processEvents()
    assert w.session is not None and w.session.ranked()[0].path.name == "a.ser"
    w.table.selectAll()
    app.processEvents()
    assert len(w.plot._series) == 2
    w.close()


def test_splash_and_settings_dialog(app, tmp_path):
    from frameforge.gui.app import _splash_pixmap
    from frameforge.gui.settings import Settings
    from frameforge.gui.settings_dialog import SettingsDialog
    from frameforge.updater import Asset, ReleaseInfo

    assert not _splash_pixmap(1.0).isNull()
    rel = ReleaseInfo("9.0.0", "v9.0.0", "", "Notes", "2026-01-01", "", False,
                      [Asset("FrameForge-9.0.0-windows-x64-setup.exe", "u", 1)])
    s = Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    d = SettingsDialog(s, open_updates=True, release=rel)
    assert d.release_box.isVisibleTo(d)
    d._save()
    assert s.get("updates/check_on_start") is True
