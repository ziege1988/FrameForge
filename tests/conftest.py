import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    """One QApplication for the whole test session, torn down in a defined order.

    Leaving windows/threads to the garbage collector at interpreter exit can
    crash Qt on Windows (exit code ≠ 0 although all tests passed).
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from frameforge.gui.theme import apply_theme

    qapp = QApplication.instance() or QApplication([])
    apply_theme(qapp)
    yield qapp
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    qapp.processEvents()
    qapp.processEvents()


@pytest.fixture
def window_factory(app):
    """Create MainWindows that are closed and deleted after the test."""
    created = []

    def make(settings):
        from frameforge.gui.main_window import MainWindow

        w = MainWindow(settings)
        created.append(w)
        return w

    yield make
    for w in created:
        if w.worker is not None:
            w.worker.wait(30000)
        w.close()
        w.deleteLater()
    app.processEvents()
