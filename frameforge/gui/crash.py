"""Error dialog for unexpected exceptions (with log folder and pre-filled bug report)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from ..logs import issue_url, log_dir


def open_log_folder() -> None:
    path = log_dir()
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def report_problem(error_text: str = "") -> None:
    QDesktopServices.openUrl(QUrl(issue_url(error_text)))


class CrashReporter(QObject):
    """Receives error texts from any thread and shows them in the GUI thread."""

    crashed = Signal(str)

    def __init__(self):
        super().__init__()
        self._showing = False
        self.crashed.connect(self._show, Qt.QueuedConnection)

    def _show(self, text: str):
        if self._showing:  # do not stack dialogs on repeated errors
            return
        self._showing = True
        try:
            box = QMessageBox(QApplication.activeWindow())
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("Unerwarteter Fehler")
            box.setText("In FrameForge ist ein unerwarteter Fehler aufgetreten.\n"
                        "Deine Dateien wurden nicht verändert. Details stehen im Protokoll.")
            box.setDetailedText(text[-6000:])
            report = box.addButton("Problem melden …", QMessageBox.ActionRole)
            logs = box.addButton("Protokoll öffnen", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is report:
                report_problem(text)
            elif box.clickedButton() is logs:
                open_log_folder()
        finally:
            self._showing = False
