"""Settings page (analysis defaults, start dialog, updates). Changes are saved immediately."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, UPDATE_REPOSITORY, __version__, updater
from ..core.analyzer import MODE_LABELS
from ..core.profiles import PROFILES
from .components import Card
from .settings import Settings
from .workers import DownloadWorker, UpdateCheckWorker


class SettingsPage(QWidget):
    updateAvailable = Signal(object)
    settingsChanged = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._release = None
        self._check_worker = None
        self._download_worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        title = QLabel("Einstellungen")
        title.setObjectName("h1")
        lay.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self._analysis_card())
        left.addWidget(self._general_card())
        left.addStretch(1)
        grid.addLayout(left, 0, 0)
        grid.addWidget(self._updates_card(), 0, 1, Qt.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    # ------------------------------------------------------------------ cards
    def _analysis_card(self) -> Card:
        card = Card("Analyse", "analysis")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.profile = QComboBox()
        for key, prof in PROFILES.items():
            self.profile.addItem(prof.name, key)
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.settings.get("analysis/profile"))))
        self.profile.currentIndexChanged.connect(lambda: self._store("analysis/profile", self.profile.currentData()))
        self.mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.settings.get("analysis/mode"))))
        self.mode.currentIndexChanged.connect(lambda: self._store("analysis/mode", self.mode.currentData()))
        self.threads = QSpinBox()
        self.threads.setRange(1, max(1, os.cpu_count() or 1))
        self.threads.setValue(self.settings.get("analysis/threads"))
        self.threads.valueChanged.connect(lambda v: self._store("analysis/threads", v))
        self.recursive = QCheckBox("Unterordner einbeziehen")
        self.recursive.setChecked(self.settings.get("analysis/recursive"))
        self.recursive.toggled.connect(lambda v: self._store("analysis/recursive", v))
        form.addRow("Standardprofil:", self.profile)
        form.addRow("Analysemodus:", self.mode)
        form.addRow("Rechen-Threads:", self.threads)
        form.addRow("", self.recursive)
        card.body.addLayout(form)
        hint = QLabel(
            "<b>Schnell</b>: bis zu 200 Frames je Video, reduzierte Auflösung – erster Überblick.<br>"
            "<b>Standard</b>: bis zu 1000 Frames je Video.<br>"
            "<b>Vollständig</b>: jeder Frame in voller Auflösung – exakte Frame-Selektion."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        card.body.addWidget(hint)
        return card

    def _general_card(self) -> Card:
        card = Card("Allgemein", "settings")
        self.show_welcome = QCheckBox("Willkommensdialog beim Start anzeigen")
        self.show_welcome.setChecked(self.settings.get("ui/show_welcome"))
        self.show_welcome.toggled.connect(lambda v: self._store("ui/show_welcome", v))
        card.body.addWidget(self.show_welcome)
        self.trace_auto = QCheckBox("Rechenprotokoll bei jeder Analyse seitlich einblenden")
        self.trace_auto.setChecked(self.settings.get("ui/trace_auto_open"))
        self.trace_auto.toggled.connect(lambda v: self._store("ui/trace_auto_open", v))
        card.body.addWidget(self.trace_auto)
        self.starfield = QCheckBox("Sternenhimmel als Hintergrund")
        self.starfield.setChecked(self.settings.get("ui/starfield"))
        self.starfield.toggled.connect(lambda v: self._store("ui/starfield", v))
        card.body.addWidget(self.starfield)
        note = QLabel("Alle Analysen laufen lokal auf diesem Computer. Es werden keine Bilddaten hochgeladen; "
                      "eine Internetverbindung wird nur für die Update-Prüfung verwendet.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)
        return card

    def _updates_card(self) -> Card:
        card = Card("Updates", "update")
        form = QFormLayout()
        form.addRow("Installierte Version:", QLabel(f"{APP_NAME} {__version__}"))
        self.last_check = QLabel(self.settings.get("updates/last_check") or "noch nie")
        form.addRow("Zuletzt geprüft:", self.last_check)
        card.body.addLayout(form)
        self.check_on_start = QCheckBox("Beim Programmstart automatisch nach Updates suchen")
        self.check_on_start.setChecked(self.settings.get("updates/check_on_start"))
        self.check_on_start.toggled.connect(lambda v: self._store("updates/check_on_start", v))
        self.prerelease = QCheckBox("Auch Vorabversionen (Beta) anbieten")
        self.prerelease.setChecked(self.settings.get("updates/include_prerelease"))
        self.prerelease.toggled.connect(lambda v: self._store("updates/include_prerelease", v))
        card.body.addWidget(self.check_on_start)
        card.body.addWidget(self.prerelease)
        row = QHBoxLayout()
        self.check_btn = QPushButton("Nach Updates suchen")
        self.check_btn.clicked.connect(self.check_updates)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row.addWidget(self.check_btn)
        row.addWidget(self.status, 1)
        card.body.addLayout(row)

        self.release_box = QWidget()
        rb = QVBoxLayout(self.release_box)
        rb.setContentsMargins(0, 6, 0, 0)
        self.release_title = QLabel()
        self.release_title.setObjectName("h2")
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(140)
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
        card.body.addWidget(self.release_box, 1)
        src = QLabel(f"Updates werden aus den GitHub-Releases von <i>{UPDATE_REPOSITORY}</i> geladen und vor der "
                     "Installation per SHA-256-Prüfsumme verifiziert.")
        src.setWordWrap(True)
        src.setObjectName("muted")
        card.body.addWidget(src)
        card.body.addStretch(1)
        return card

    def _store(self, key, value):
        self.settings.set(key, value)
        self.settings.sync()
        self.settingsChanged.emit()

    def sync_from_settings(self):
        for box, key in ((self.profile, "analysis/profile"), (self.mode, "analysis/mode")):
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(self.settings.get(key))))
            box.blockSignals(False)

    # ---------------------------------------------------------------- updates
    def check_updates(self):
        if self._check_worker and self._check_worker.isRunning():
            return
        self.check_btn.setEnabled(False)
        self.status.setText("Suche nach Updates …")
        self._check_worker = UpdateCheckWorker(self.prerelease.isChecked(), self)
        self._check_worker.result.connect(self._on_check_result)
        self._check_worker.failed.connect(lambda msg: self.status.setText(f"⚠ {msg}"))
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
        self.show_release(release)
        self.updateAvailable.emit(release)

    def show_release(self, release):
        self._release = release
        pre = " (Vorabversion)" if release.prerelease else ""
        self.release_title.setText(f"Version {release.version}{pre} verfügbar")
        self.notes.setMarkdown(release.notes.strip() or "Keine Versionshinweise vorhanden.")
        if release.published:
            self.notes.setHtml(f"<p style='color:#8a94ad'>Veröffentlicht am {release.published}</p>" + self.notes.toHtml())
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
        self.cancel_dl_btn.hide()
        self.progress.setFormat("Download abgeschlossen – Installation startet …")
        try:
            updater.launch_installer(Path(path))
        except updater.UpdateError as exc:
            QMessageBox.warning(self, "Update", str(exc))
            return
        self.settings.sync()
        QApplication.instance().quit()

    def shutdown(self):
        for w in (self._download_worker, self._check_worker):
            if w and w.isRunning():
                if hasattr(w, "cancel"):
                    w.cancel()
                w.wait(3000)
