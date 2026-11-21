"""Settings dialog including the update section."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, UPDATE_REPOSITORY, __version__, updater
from ..core.analyzer import MODE_LABELS
from ..core.profiles import PROFILES
from .settings import Settings
from .workers import DownloadWorker, UpdateCheckWorker


class SettingsDialog(QDialog):
    updateAvailable = Signal(object)

    def __init__(self, settings: Settings, parent=None, open_updates: bool = False, release=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumSize(560, 520)
        self.settings = settings
        self._release = release
        self._check_worker = None
        self._download_worker = None

        tabs = QTabWidget()
        tabs.addTab(self._analysis_tab(), "Analyse")
        tabs.addTab(self._updates_tab(), "Updates")
        if open_updates:
            tabs.setCurrentIndex(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Speichern")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        if release is not None:
            self._show_release(release)

    # ------------------------------------------------------------------
    def _analysis_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.profile = QComboBox()
        for key, prof in PROFILES.items():
            self.profile.addItem(prof.name, key)
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.settings.get("analysis/profile"))))
        self.mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.settings.get("analysis/mode"))))
        self.threads = QSpinBox()
        self.threads.setRange(1, max(1, os.cpu_count() or 1))
        self.threads.setValue(self.settings.get("analysis/threads"))
        self.recursive = QCheckBox("Unterordner einbeziehen")
        self.recursive.setChecked(self.settings.get("analysis/recursive"))
        form.addRow("Standardprofil:", self.profile)
        form.addRow("Standard-Analysemodus:", self.mode)
        form.addRow("Rechen-Threads:", self.threads)
        form.addRow("", self.recursive)
        hint = QLabel(
            "<b>Schnell</b>: bis zu 200 Frames je Video, reduzierte Auflösung – für einen ersten Überblick.<br>"
            "<b>Standard</b>: bis zu 1000 Frames je Video.<br>"
            "<b>Vollständig</b>: jeder Frame in voller Auflösung – exakte Frame-Selektion.<br><br>"
            "Alle Analysen laufen lokal auf diesem Computer. Es werden keine Bilddaten hochgeladen."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow(hint)
        return w

    def _updates_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        info = QGroupBox("Installierte Version")
        fl = QFormLayout(info)
        fl.addRow("Version:", QLabel(f"{APP_NAME} {__version__}"))
        last = self.settings.get("updates/last_check") or "noch nie"
        self.last_check = QLabel(last)
        fl.addRow("Zuletzt geprüft:", self.last_check)
        v.addWidget(info)

        self.check_on_start = QCheckBox("Beim Programmstart automatisch nach Updates suchen")
        self.check_on_start.setChecked(self.settings.get("updates/check_on_start"))
        self.prerelease = QCheckBox("Auch Vorabversionen (Beta) anbieten")
        self.prerelease.setChecked(self.settings.get("updates/include_prerelease"))
        v.addWidget(self.check_on_start)
        v.addWidget(self.prerelease)

        row = QHBoxLayout()
        self.check_btn = QPushButton("Nach Updates suchen")
        self.check_btn.clicked.connect(self.check_updates)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row.addWidget(self.check_btn)
        row.addWidget(self.status, 1)
        v.addLayout(row)

        self.release_box = QGroupBox("Verfügbares Update")
        rb = QVBoxLayout(self.release_box)
        self.release_title = QLabel()
        self.release_title.setObjectName("h1")
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.progress = QProgressBar()
        self.progress.hide()
        btns = QHBoxLayout()
        self.install_btn = QPushButton("Update herunterladen und installieren")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.install_update)
        self.cancel_dl_btn = QPushButton("Abbrechen")
        self.cancel_dl_btn.hide()
        self.cancel_dl_btn.clicked.connect(self._cancel_download)
        btns.addWidget(self.install_btn)
        btns.addWidget(self.cancel_dl_btn)
        btns.addStretch(1)
        rb.addWidget(self.release_title)
        rb.addWidget(self.notes, 1)
        rb.addWidget(self.progress)
        rb.addLayout(btns)
        self.release_box.hide()
        v.addWidget(self.release_box, 1)
        src = QLabel(f"Updates werden aus den GitHub-Releases von <i>{UPDATE_REPOSITORY}</i> geladen "
                     "und vor der Installation per SHA-256-Prüfsumme verifiziert.")
        src.setWordWrap(True)
        src.setObjectName("muted")
        v.addWidget(src)
        v.addStretch(0)
        return w

    # ------------------------------------------------------------------
    def check_updates(self):
        if self._check_worker and self._check_worker.isRunning():
            return
        self.check_btn.setEnabled(False)
        self.status.setText("Suche nach Updates …")
        self._check_worker = UpdateCheckWorker(self.prerelease.isChecked(), self)
        self._check_worker.result.connect(self._on_check_result)
        self._check_worker.failed.connect(self._on_check_failed)
        self._check_worker.finished.connect(lambda: self.check_btn.setEnabled(True))
        self._check_worker.start()

    def _on_check_result(self, release):
        stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.settings.set("updates/last_check", stamp)
        self.last_check.setText(stamp)
        if release is None:
            self.status.setText(f"✓ {APP_NAME} ist auf dem neuesten Stand.")
            self.release_box.hide()
            return
        self.status.setText("Ein Update ist verfügbar.")
        self._show_release(release)
        self.updateAvailable.emit(release)

    def _on_check_failed(self, msg):
        self.status.setText(f"⚠ {msg}")

    def _show_release(self, release):
        self._release = release
        pre = " (Vorabversion)" if release.prerelease else ""
        self.release_title.setText(f"Version {release.version}{pre}")
        date = f"<p style='color:#8b93a7'>Veröffentlicht am {release.published}</p>" if release.published else ""
        notes = release.notes.strip() or "Keine Versionshinweise vorhanden."
        self.notes.setMarkdown(notes)
        if date:
            self.notes.setHtml(date + self.notes.toHtml())
        asset = release.asset_for()
        _, why = updater.can_self_install()
        if asset is None:
            self.install_btn.setEnabled(False)
            self.install_btn.setText("Kein Paket für dieses System")
        elif not updater.is_frozen():
            self.install_btn.setEnabled(False)
            self.install_btn.setToolTip(why)
            self.install_btn.setText("Nur in der installierten Version verfügbar")
        else:
            self.install_btn.setEnabled(True)
            size = f" ({asset.size / 1e6:.0f} MB)" if asset.size else ""
            self.install_btn.setText(f"Update herunterladen und installieren{size}")
        self.release_box.show()

    def install_update(self):
        if self._release is None:
            return
        answer = QMessageBox.question(
            self, "Update installieren",
            f"{APP_NAME} {self._release.version} wird heruntergeladen und installiert.\n"
            f"{APP_NAME} wird dafür beendet und anschließend neu gestartet.\n\nFortfahren?",
        )
        if answer != QMessageBox.Yes:
            return
        self.install_btn.setEnabled(False)
        self.cancel_dl_btn.show()
        self.progress.setValue(0)
        self.progress.show()
        self._download_worker = DownloadWorker(self._release, self)
        self._download_worker.progress.connect(self._on_dl_progress)
        self._download_worker.done.connect(self._on_downloaded)
        self._download_worker.failed.connect(self._on_dl_failed)
        self._download_worker.start()

    def _on_dl_progress(self, done, total):
        if total:
            self.progress.setMaximum(100)
            self.progress.setValue(int(done / total * 100))
            self.progress.setFormat(f"{done / 1e6:.1f} / {total / 1e6:.1f} MB")
        else:
            self.progress.setMaximum(0)

    def _on_dl_failed(self, msg):
        self.progress.hide()
        self.cancel_dl_btn.hide()
        self.install_btn.setEnabled(True)
        QMessageBox.warning(self, "Update", msg)

    def _cancel_download(self):
        if self._download_worker:
            self._download_worker.cancel()

    def _on_downloaded(self, path):
        from pathlib import Path

        self.cancel_dl_btn.hide()
        self.progress.setFormat("Download abgeschlossen – Installation startet …")
        try:
            updater.launch_installer(Path(path))
        except updater.UpdateError as exc:
            QMessageBox.warning(self, "Update", str(exc))
            return
        self._save()
        QApplication.instance().quit()

    def _cancel_download_on_close(self):  # noqa: D401
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.cancel()
            self._download_worker.wait(3000)

    def reject(self):
        self._cancel_download_on_close()
        super().reject()

    def _save(self):
        s = self.settings
        s.set("analysis/profile", self.profile.currentData())
        s.set("analysis/mode", self.mode.currentData())
        s.set("analysis/threads", self.threads.value())
        s.set("analysis/recursive", self.recursive.isChecked())
        s.set("updates/check_on_start", self.check_on_start.isChecked())
        s.set("updates/include_prerelease", self.prerelease.isChecked())
        s.sync()
        if self.isVisible():
            self.accept()
