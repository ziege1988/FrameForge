"""Background threads so the UI stays responsive during long operations."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QThread, Signal

from .. import UPDATE_REPOSITORY, __version__
from ..core.analyzer import AnalysisOptions, FileResult, analyze_session
from ..core.export import export_best_frames
from .. import updater
from ..logs import log


class AnalysisWorker(QThread):
    progress = Signal(str, float)
    fileDone = Signal(object)
    finishedSession = Signal(object)
    failed = Signal(str)

    def __init__(self, paths, options: AnalysisOptions, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.options = options
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            session = analyze_session(self.paths, self.options, self.progress.emit, self.cancel_event,
                                      self.fileDone.emit)
            self.finishedSession.emit(session)
        except Exception:  # pragma: no cover - safety net
            log.exception("Analyse fehlgeschlagen")
            self.failed.emit(traceback.format_exc())


class ExportWorker(QThread):
    progress = Signal(str, float)
    done = Signal(str, int)
    failed = Signal(str)

    def __init__(self, result: FileResult, destination, fraction, options, parent=None):
        super().__init__(parent)
        self.result, self.destination, self.fraction, self.options = result, destination, fraction, options
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            path, n = export_best_frames(self.result, self.destination, self.fraction, self.options,
                                         self.progress.emit, self.cancel_event)
            self.done.emit(str(path), n)
        except InterruptedError:
            self.failed.emit("Export abgebrochen.")
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateCheckWorker(QThread):
    result = Signal(object)  # ReleaseInfo | None
    failed = Signal(str)

    def __init__(self, include_prerelease: bool, parent=None):
        super().__init__(parent)
        self.include_prerelease = include_prerelease

    def run(self):
        try:
            self.result.emit(updater.check_for_update(__version__, UPDATE_REPOSITORY, self.include_prerelease))
        except updater.UpdateError as exc:
            log.info("Update-Prüfung: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            log.exception("Update-Prüfung fehlgeschlagen")
            self.failed.emit(f"Unerwarteter Fehler: {exc}")


class DownloadWorker(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            path = updater.download_update(self.release, progress=self.progress.emit, cancel=self.cancel_event)
            self.done.emit(str(path))
        except updater.UpdateError as exc:
            log.warning("Update-Download: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            log.exception("Update-Download fehlgeschlagen")
            self.failed.emit(f"Unerwarteter Fehler: {exc}")
