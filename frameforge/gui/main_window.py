"""Main application window: menu bar, sidebar navigation and pages."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, UPDATE_REPOSITORY, __version__
from ..logs import log
from ..core.analyzer import MODE_LABELS, AnalysisOptions, FileResult, SessionResult, stretch_to_uint8
from ..core.export import export_csv, export_frame_list, export_json
from ..core.io import open_source
from ..core.io.registry import FORMAT_GROUPS, collect_files
from ..core.profiles import PROFILES, get_profile
from ..core.project import PROJECT_EXTENSION, load_project, save_project
from ..core.trace import Tracer
from . import icons
from .components import Card, ZoomPreview, status_icon
from .crash import open_log_folder, report_problem
from .dashboard import OverviewPage
from .pages import InfoPage, ReportsPage
from .resources import app_icon
from .settings import Settings
from .settings_page import SettingsPage
from .trace_panel import TracePanel
from .theme import BAD, GOOD, MUTED, de_number, score_color, verdict_color
from .welcome import PROFILE_ORDER, WelcomeDialog
from .widgets import ComponentBars, QualityPlot
from .workers import AnalysisWorker, ExportWorker, UpdateCheckWorker

COLUMNS = ["Rang", "Datei", "Qualität", "Status", "Begründung", "Format", "Frames",
           "Schärfe", "Kontrast", "Rauschen", "Belichtung", "Stabilität"]
COL_RANK, COL_NAME, COL_SCORE, COL_STATUS, COL_REASON, COL_FORMAT, COL_FRAMES = range(7)
COMP_COLUMNS = {7: "sharpness", 8: "contrast", 9: "noise", 10: "exposure", 11: "stability"}
PAGE_OVERVIEW, PAGE_ANALYSIS, PAGE_REPORTS, PAGE_SETTINGS, PAGE_INFO = range(5)
VIDEO_EXTENSIONS = sorted(FORMAT_GROUPS["Video"] | {".ser"})


class NumericItem(QTableWidgetItem):
    """Table item that sorts numerically (None/empty sorts last)."""

    def __init__(self, value, text: str | None = None):
        super().__init__(text if text is not None else ("–" if value is None else f"{value:.0f}"))
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        a = self.value if self.value is not None else float("-inf")
        b = getattr(other, "value", None)
        b = b if b is not None else float("-inf")
        return a < b


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        self.queue: list[Path] = []
        self.session: SessionResult | None = None
        self.results: dict[str, FileResult] = {}
        self.worker: AnalysisWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.update_worker: UpdateCheckWorker | None = None
        self.available_update = None
        self._current: FileResult | None = None

        self._build_menu()
        self._build_ui()
        self._build_statusbar()
        geo = self.settings.get("ui/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._set_profile(self.settings.get("analysis/profile"))
        self._refresh_table()
        self._update_actions()

    # ================================================================ layout
    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("Datei")
        self.act_open_dir = m.addAction(icons.icon("folder"), "Ordner analysieren …", QKeySequence.Open,
                                        self.analyze_folder)
        self.act_open_video = m.addAction(icons.icon("play"), "Video analysieren …", self.analyze_video)
        self.act_add_files = m.addAction("Dateien hinzufügen …", self.add_files)
        m.addSeparator()
        self.act_open_project = m.addAction(icons.icon("folder-open"), "Projekt öffnen …", self.open_project)
        self.act_save_project = m.addAction(icons.icon("save"), "Projekt speichern …", QKeySequence.Save,
                                            self.save_project)
        m.addSeparator()
        self.act_export = m.addAction(icons.icon("export"), "Bericht exportieren …", lambda: self.export_report())
        m.addSeparator()
        m.addAction("Beenden", QKeySequence.Quit, self.close)

        a = mb.addMenu("Analyse")
        self.act_start = a.addAction(icons.icon("play"), "Analyse starten", QKeySequence("Ctrl+R"),
                                     self.start_analysis)
        self.act_cancel = a.addAction(icons.icon("stop"), "Abbrechen", self.cancel_analysis)
        self.act_clear = a.addAction("Liste leeren", self.clear_queue)
        a.addSeparator()
        self.act_trace = a.addAction(icons.icon("analysis"), "Rechenprotokoll anzeigen", QKeySequence("Ctrl+L"),
                                     self.toggle_trace)
        self.act_trace.setCheckable(True)
        a.addSeparator()
        pm = a.addMenu("Objekt")
        self.profile_actions = QActionGroup(self)
        for key in PROFILE_ORDER:
            act = pm.addAction(icons.icon(icons.PROFILE_ICONS[key]), PROFILES[key].name)
            act.setCheckable(True)
            act.setData(key)
            act.triggered.connect(lambda _=False, k=key: self._set_profile(k))
            self.profile_actions.addAction(act)
        mm = a.addMenu("Modus")
        self.mode_actions = QActionGroup(self)
        for key, label in MODE_LABELS.items():
            act = mm.addAction(label)
            act.setCheckable(True)
            act.setData(key)
            act.setChecked(key == self.settings.get("analysis/mode"))
            act.triggered.connect(lambda _=False, k=key: self._set_mode(k))
            self.mode_actions.addAction(act)

        s = mb.addMenu("Einstellungen")
        s.addAction(icons.icon("settings"), "Einstellungen …", QKeySequence.Preferences,
                    lambda: self.goto(PAGE_SETTINGS))
        s.addAction(icons.icon("update"), "Nach Updates suchen", self.check_updates_now)

        h = mb.addMenu("Hilfe")
        h.addAction("Willkommensdialog anzeigen", self.show_welcome)
        h.addSeparator()
        h.addAction("Anleitung und Projektseite (GitHub)",
                    lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{UPDATE_REPOSITORY}#readme")))
        h.addAction("Problem melden …", lambda: report_problem())
        h.addAction("Protokollordner öffnen", open_log_folder)
        h.addSeparator()
        h.addAction(icons.icon("info"), f"Über {APP_NAME}", lambda: self.goto(PAGE_INFO))

    def _build_ui(self):
        root = QWidget()
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(180)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 14, 10, 12)
        sl.setSpacing(4)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: list[QToolButton] = []
        for idx, (icon_name, text) in enumerate((("home", "Übersicht"), ("analysis", "Analyse"),
                                                 ("report", "Berichte"), ("settings", "Einstellungen"),
                                                 ("info", "Info"))):
            b = QToolButton()
            b.setObjectName("nav")
            b.setText(text)
            b.setIcon(icons.icon(icon_name, "#c9d2e6", "#ffffff"))
            b.setIconSize(QSize(20, 20))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.nav.addButton(b, idx)
            self.nav_buttons.append(b)
            sl.addWidget(b)
        self.nav.idClicked.connect(self.goto)
        sl.addStretch(1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("muted")
        ver.setAlignment(Qt.AlignCenter)
        sl.addWidget(ver)
        rl.addWidget(side)

        self.pages = QStackedWidget()
        self.overview = OverviewPage()
        self.overview.requestFolder.connect(self.analyze_folder)
        self.overview.requestVideo.connect(self.analyze_video)
        self.overview.requestProject.connect(self.open_project)
        self.overview.profileChosen.connect(self._set_profile)
        self.overview.fileActivated.connect(self.show_file)
        self.pages.addWidget(self.overview)
        self.pages.addWidget(self._build_analysis_page())
        self.reports = ReportsPage()
        self.reports.exportCsv.connect(lambda: self.export_report("csv"))
        self.reports.exportJson.connect(lambda: self.export_report("json"))
        self.reports.saveProject.connect(self.save_project)
        self.reports.openProject.connect(self.open_project)
        self.reports.openFrameSelection.connect(self._goto_frame_selection)
        self.pages.addWidget(self.reports)
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.updateAvailable.connect(self._on_update_result)
        self.settings_page.settingsChanged.connect(self._on_settings_changed)
        self.pages.addWidget(self.settings_page)
        self.info_page = InfoPage()
        self.info_page.checkUpdates.connect(self.check_updates_now)
        self.pages.addWidget(self.info_page)
        rl.addWidget(self.pages, 1)
        self.trace_panel = TracePanel()
        self.trace_panel.closed.connect(lambda: self.act_trace.setChecked(False))
        rl.addWidget(self.trace_panel)
        self.setCentralWidget(root)
        self.goto(PAGE_OVERVIEW)

    def _build_analysis_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        for text, icon_name, slot in (("Ordner …", "folder", self.analyze_folder_no_start),
                                      ("Dateien …", "general", self.add_files)):
            b = QPushButton(icons.icon(icon_name), text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        self.clear_btn = QPushButton("Liste leeren")
        self.clear_btn.clicked.connect(self.clear_queue)
        bar.addWidget(self.clear_btn)
        bar.addSpacing(14)
        lbl = QLabel("Objekt:")
        lbl.setObjectName("muted")
        bar.addWidget(lbl)
        self.profile_box = QComboBox()
        for key in PROFILE_ORDER:
            self.profile_box.addItem(icons.icon(icons.PROFILE_ICONS[key]), PROFILES[key].name, key)
            self.profile_box.setItemData(self.profile_box.count() - 1, PROFILES[key].description, Qt.ToolTipRole)
        self.profile_box.currentIndexChanged.connect(lambda: self._set_profile(self.profile_box.currentData()))
        bar.addWidget(self.profile_box)
        lbl = QLabel("Modus:")
        lbl.setObjectName("muted")
        bar.addWidget(lbl)
        self.mode_box = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode_box.addItem(label, key)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(self.settings.get("analysis/mode"))))
        self.mode_box.currentIndexChanged.connect(lambda: self._set_mode(self.mode_box.currentData()))
        bar.addWidget(self.mode_box)
        bar.addStretch(1)
        self.trace_btn = QPushButton(icons.icon("analysis"), "Rechenprotokoll")
        self.trace_btn.setToolTip("Live anzeigen, wie die Analyse rechnet (Strg+L)")
        self.trace_btn.clicked.connect(self.toggle_trace)
        bar.addWidget(self.trace_btn)
        self.start_btn = QPushButton(icons.icon("play", "#ffffff"), "Analyse starten")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_analysis)
        self.cancel_btn = QPushButton(icons.icon("stop"), "Abbrechen")
        self.cancel_btn.clicked.connect(self.cancel_analysis)
        bar.addWidget(self.start_btn)
        bar.addWidget(self.cancel_btn)
        v.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        left = Card()
        left.body.setContentsMargins(10, 10, 10, 10)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("muted")
        left.body.addWidget(self.summary_label)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSortingEnabled(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_REASON, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_NAME, 200)
        self.table.setColumnWidth(COL_REASON, 280)
        self.table.itemSelectionChanged.connect(self._on_selection)
        left.body.addWidget(self.table, 1)
        self.empty_hint = QLabel("Ordner oder Dateien per Drag & Drop hierher ziehen oder über „Ordner …“ auswählen.<br>"
                                 "Unterstützt: SER, AVI, MP4, FITS, TIFF, RAW (CR2, CR3, NEF, ARW, DNG …), PNG, JPEG.")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        left.body.addWidget(self.empty_hint)
        splitter.addWidget(left)

        right = Card()
        right.body.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_assessment_tab(), "Bewertung")
        self.tabs.addTab(self._build_timeline_tab(), "Qualitätsverlauf")
        self.tabs.addTab(self._build_preview_tab(), "Vorschau")
        self.tabs.addTab(self._build_selection_tab(), "Frame-Selektion")
        right.body.addWidget(self.tabs)
        splitter.addWidget(right)
        splitter.setSizes([820, 600])
        v.addWidget(splitter, 1)
        return page

    def _build_assessment_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        self.detail_title = QLabel("Keine Datei ausgewählt")
        self.detail_title.setObjectName("h2")
        self.detail_title.setWordWrap(True)
        self.detail_badge = QLabel()
        self.detail_badge.setObjectName("badge")
        head.addWidget(self.detail_title, 1)
        head.addWidget(self.detail_badge)
        v.addLayout(head)
        self.detail_meta = QLabel()
        self.detail_meta.setObjectName("muted")
        self.detail_meta.setWordWrap(True)
        v.addWidget(self.detail_meta)
        self.bars = ComponentBars()
        v.addWidget(self.bars)
        self.reasons = QTextBrowser()
        v.addWidget(self.reasons, 1)
        return w

    def _build_timeline_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        hint = QLabel("Frame-Qualität im Verlauf der Aufnahme (100 = beste Frames der Datei). "
                      "Mehrere Dateien in der Tabelle markieren, um Aufnahmen zu vergleichen.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.plot = QualityPlot()
        v.addWidget(self.plot, 1)
        self.timeline_stats = QLabel()
        self.timeline_stats.setObjectName("muted")
        self.timeline_stats.setWordWrap(True)
        v.addWidget(self.timeline_stats)
        return w

    def _build_preview_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        self.preview = ZoomPreview()
        v.addWidget(self.preview, 1)
        hint = QLabel("Gestrichelt: Analysebereich · Zahlen: relative Schärfe je Bildbereich (100 = schärfster Bereich).")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        return w

    def _build_selection_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        self.sel_info = QLabel("Ein Video in der Tabelle auswählen.")
        self.sel_info.setWordWrap(True)
        v.addWidget(self.sel_info)
        row = QHBoxLayout()
        row.addWidget(QLabel("Anteil der besten Frames:"))
        self.sel_percent = QSpinBox()
        self.sel_percent.setRange(1, 100)
        self.sel_percent.setSuffix(" %")
        self.sel_percent.valueChanged.connect(self._update_selection_preview)
        row.addWidget(self.sel_percent)
        self.sel_reset = QPushButton("Empfehlung übernehmen")
        self.sel_reset.clicked.connect(self._reset_selection)
        row.addWidget(self.sel_reset)
        row.addStretch(1)
        v.addLayout(row)
        self.sel_count = QLabel()
        self.sel_count.setObjectName("muted")
        v.addWidget(self.sel_count)
        btns = QHBoxLayout()
        self.export_ser_btn = QPushButton(icons.icon("export", "#ffffff"), "Beste Frames als SER exportieren …")
        self.export_ser_btn.setObjectName("primary")
        self.export_ser_btn.clicked.connect(self.export_best_frames)
        self.export_list_btn = QPushButton("Frame-Liste als CSV …")
        self.export_list_btn.clicked.connect(self.export_frame_list)
        btns.addWidget(self.export_ser_btn)
        btns.addWidget(self.export_list_btn)
        btns.addStretch(1)
        v.addLayout(btns)
        note = QLabel("Die exportierte SER-Datei enthält die ausgewählten Frames unverändert (Originaldaten, "
                      "chronologische Reihenfolge) und kann direkt in AutoStakkert!, Siril, PIPP oder PSS "
                      "weiterverarbeitet werden. Bei einer Stichprobenanalyse werden vor dem Export alle Frames "
                      "analysiert, damit die Auswahl exakt ist.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        return w

    def _build_statusbar(self):
        sb = self.statusBar()
        self.status_label = QLabel("Bereit")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(320)
        self.progress.setRange(0, 1000)
        self.progress.hide()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.progress)

    # ============================================================ navigation
    def goto(self, index: int):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    def show_file(self, path: str):
        self.goto(PAGE_ANALYSIS)
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1).data(Qt.UserRole) == path:
                self.table.selectRow(row)
                break

    def _goto_frame_selection(self):
        self.goto(PAGE_ANALYSIS)
        self.tabs.setCurrentIndex(3)

    def _set_profile(self, key: str):
        if key not in PROFILES:
            key = "planet"
        self.settings.set("analysis/profile", key)
        self.profile_box.blockSignals(True)
        self.profile_box.setCurrentIndex(max(0, self.profile_box.findData(key)))
        self.profile_box.blockSignals(False)
        for act in self.profile_actions.actions():
            act.setChecked(act.data() == key)
        self.overview.set_profile(key)
        if hasattr(self, "settings_page"):
            self.settings_page.sync_from_settings()
        self._refresh_summary()

    def _set_mode(self, key: str):
        self.settings.set("analysis/mode", key)
        self.mode_box.blockSignals(True)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(key)))
        self.mode_box.blockSignals(False)
        for act in self.mode_actions.actions():
            act.setChecked(act.data() == key)
        if hasattr(self, "settings_page"):
            self.settings_page.sync_from_settings()

    def _on_settings_changed(self):
        self._set_profile(self.settings.get("analysis/profile"))
        self._set_mode(self.settings.get("analysis/mode"))

    def show_welcome(self):
        dlg = WelcomeDialog(self.settings, self)
        dlg.exec()
        self._set_profile(dlg.selected_profile())
        self.settings_page.show_welcome.blockSignals(True)
        self.settings_page.show_welcome.setChecked(self.settings.get("ui/show_welcome"))
        self.settings_page.show_welcome.blockSignals(False)
        action = {"folder": self.analyze_folder, "video": self.analyze_video, "project": self.open_project}
        if dlg.choice in action:
            action[dlg.choice]()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "trace_panel"):
            self.trace_panel.sync_width()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.export_worker.wait(5000)
        self.settings_page.shutdown()
        self.settings.set("ui/geometry", self.saveGeometry())
        self.settings.sync()
        super().closeEvent(event)

    # ================================================================= queue
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        projects = [p for p in paths if p.suffix.lower() == PROJECT_EXTENSION]
        if projects:
            self.load_project_file(projects[0])
            return
        self.add_paths(paths)
        self.goto(PAGE_ANALYSIS)

    def _start_dir(self) -> str:
        return self.settings.get("ui/last_dir") or str(Path.home())

    def analyze_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Aufnahmeordner wählen", self._start_dir())
        if folder:
            self.settings.set("ui/last_dir", folder)
            self.open_paths([Path(folder)], replace=True)

    def analyze_folder_no_start(self):
        folder = QFileDialog.getExistingDirectory(self, "Aufnahmeordner wählen", self._start_dir())
        if folder:
            self.settings.set("ui/last_dir", folder)
            self.add_paths([Path(folder)])

    def analyze_video(self):
        patterns = " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(self, "Video(s) wählen", self._start_dir(),
                                                f"Videos ({patterns});;Alle Dateien (*)")
        if files:
            self.settings.set("ui/last_dir", str(Path(files[0]).parent))
            self.open_paths([Path(f) for f in files], replace=True)

    def add_files(self):
        patterns = " ".join(f"*{e}" for g in FORMAT_GROUPS.values() for e in sorted(g))
        files, _ = QFileDialog.getOpenFileNames(self, "Dateien auswählen", self._start_dir(),
                                                f"Astro-Aufnahmen ({patterns});;Alle Dateien (*)")
        if files:
            self.settings.set("ui/last_dir", str(Path(files[0]).parent))
            self.add_paths([Path(f) for f in files])

    def open_external(self, paths):
        """Files from the command line, Finder/Explorer ("Öffnen mit") or the Dock icon."""
        paths = [Path(p) for p in paths]
        projects = [p for p in paths if p.suffix.lower() == PROJECT_EXTENSION]
        if projects:
            self.load_project_file(projects[0])
        else:
            self.open_paths(paths, replace=True)
        self.raise_()
        self.activateWindow()

    def open_paths(self, paths, replace: bool = False):
        """Queue files/folders and start the analysis right away (quick start)."""
        if self.worker and self.worker.isRunning():
            return
        if replace:
            self.queue.clear()
            self.results.clear()
            self.session = None
        self.add_paths(paths)
        if self.queue:
            self.start_analysis()

    def add_paths(self, paths):
        found = collect_files(paths, recursive=self.settings.get("analysis/recursive"))
        known = {p.resolve() for p in self.queue}
        added = [p for p in found if p.resolve() not in known]
        self.queue.extend(added)
        self.status_label.setText(f"{len(added)} Datei(en) hinzugefügt." if added
                                  else "Keine (neuen) unterstützten Dateien gefunden.")
        self._refresh_table()
        self._update_actions()

    def clear_queue(self):
        if self.worker and self.worker.isRunning():
            return
        self.queue.clear()
        self.results.clear()
        self.session = None
        self._refresh_table()
        self._show_details([])
        self.overview.show_empty()
        self.reports.set_session(None)
        self._update_actions()

    # ============================================================== analysis
    def _options(self, trace=None) -> AnalysisOptions:
        return AnalysisOptions(profile=self.settings.get("analysis/profile"), mode=self.settings.get("analysis/mode"),
                               threads=self.settings.get("analysis/threads"), recursive=False, trace=trace)

    def toggle_trace(self):
        self.trace_panel.toggle()
        self.act_trace.setChecked(self.trace_panel.is_open())

    def start_analysis(self):
        if not self.queue or (self.worker and self.worker.isRunning()):
            return
        self.results.clear()
        self.session = None
        self._refresh_table()
        tracer = Tracer()
        self.trace_panel.attach(tracer)
        if self.settings.get("ui/trace_auto_open"):
            self.trace_panel.show_panel()
            self.act_trace.setChecked(True)
        self.worker = AnalysisWorker(self.queue, self._options(tracer), self)
        self.worker.progress.connect(self._on_progress)
        self.worker.fileDone.connect(self._on_file_done)
        self.worker.finishedSession.connect(self._on_session_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._update_actions)
        self.progress.setValue(0)
        self.progress.show()
        opts = self._options()
        log.info("Analyse gestartet: %d Dateien, Profil %s, Modus %s", len(self.queue), opts.profile, opts.mode)
        self.overview.show_running(len(self.queue))
        self.goto(PAGE_OVERVIEW)
        self.worker.start()
        self._update_actions()

    def cancel_analysis(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Breche ab …")
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()

    def _on_progress(self, msg, frac):
        self.status_label.setText(msg)
        self.progress.setValue(int(frac * 1000))
        if self.worker and self.worker.isRunning():
            self.overview.update_running(msg, frac)

    def _on_file_done(self, result: FileResult):
        self.results[str(result.path)] = result
        self.overview.add_running_file(result)
        self._refresh_table()

    def _on_session_done(self, session: SessionResult):
        self.progress.hide()
        self.trace_panel.finish()
        for f in session.files:
            if f.error:
                log.warning("Datei nicht auswertbar: %s – %s", f.path, f.error)
        log.info("Analyse beendet in %.1f s (%s)", session.elapsed_s, "abgebrochen" if session.cancelled else "ok")
        n_ok = sum(1 for f in session.files if f.error is None)
        self.status_label.setText(("Analyse abgebrochen – " if session.cancelled else "Analyse abgeschlossen – ")
                                  + f"{n_ok} von {len(self.queue)} Dateien ausgewertet.")
        self._apply_session(session)

    def _apply_session(self, session: SessionResult):
        self.session = session
        self.results = {str(f.path): f for f in session.files}
        self._refresh_table()
        self.table.sortItems(0, Qt.AscendingOrder)
        if self.table.rowCount():
            self.table.selectRow(0)
        if session.files:
            self.overview.show_session(session, self._full_loader)
        else:
            self.overview.show_empty()
        self.reports.set_session(session)
        self._update_actions()

    @staticmethod
    def _full_loader(res: FileResult):
        """Loader for the full resolution best frame (used when zooming in)."""
        if not res.path.exists():
            return None

        def load():
            with open_source(res.path) as src:
                frame = src.read_frame(res.best_index)
            return stretch_to_uint8(frame, max_dim=100_000)[0]
        return load

    def _on_failed(self, msg):
        self.progress.hide()
        self.trace_panel.finish()
        log.error("Analyse fehlgeschlagen:\n%s", msg)
        QMessageBox.critical(self, "Fehler", f"Die Analyse ist fehlgeschlagen:\n\n{msg[-1500:]}")

    def _update_actions(self):
        running = bool(self.worker and self.worker.isRunning())
        exporting = bool(self.export_worker and self.export_worker.isRunning())
        can_start = bool(self.queue) and not running and not exporting
        self.start_btn.setEnabled(can_start)
        self.act_start.setEnabled(can_start)
        self.cancel_btn.setEnabled(running or exporting)
        self.act_cancel.setEnabled(running or exporting)
        for a in (self.act_open_dir, self.act_open_video, self.act_add_files, self.act_clear, self.act_open_project):
            a.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.profile_box.setEnabled(not running)
        self.mode_box.setEnabled(not running)
        has = self.session is not None and not running
        self.act_export.setEnabled(has)
        self.act_save_project.setEnabled(has)
        self.empty_hint.setVisible(not self.queue)

    # ================================================================= table
    def _refresh_summary(self):
        if not hasattr(self, "summary_label"):
            return
        n_done = sum(1 for p in self.queue if str(p) in self.results)
        prof = PROFILES[self.settings.get("analysis/profile")].name
        self.summary_label.setText(
            f"{len(self.queue)} Datei(en) · {n_done} analysiert · Profil: {prof}" if self.queue else "")

    def _refresh_table(self):
        selected = {self.table.item(i.row(), 1).data(Qt.UserRole)
                    for i in self.table.selectionModel().selectedRows()} if self.table.rowCount() else set()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.queue))
        for row, path in enumerate(self.queue):
            res = self.results.get(str(path))
            name = QTableWidgetItem(path.name)
            name.setData(Qt.UserRole, str(path))
            name.setToolTip(str(path))
            self.table.setItem(row, 1, name)
            if res is None:
                for c in range(len(COLUMNS)):
                    if c != COL_NAME:
                        self.table.setItem(row, c, NumericItem(None, ""))
                self.table.item(row, COL_STATUS).setText("wartet")
                self.table.setItem(row, COL_FORMAT, QTableWidgetItem(path.suffix.upper().lstrip(".")))
                continue
            info = res.info
            scored = bool(res.verdict) and res.error is None
            name.setIcon(status_icon(res.verdict, 16) if res.verdict else icons.pixmap("clock", 16, MUTED))
            self.table.setItem(row, COL_RANK, NumericItem(res.rank or None, str(res.rank) if res.rank else "–"))
            self.table.setItem(row, COL_FORMAT, QTableWidgetItem(info.format if info else path.suffix.upper().lstrip(".")))
            self.table.setItem(row, COL_FRAMES, NumericItem(info.frame_count if info else None))
            score = NumericItem(res.score if scored else None,
                                f"{de_number(res.score)} %" if scored else ("–" if res.error else "…"))
            if scored:
                score.setForeground(QColor(score_color(res.score)))
            self.table.setItem(row, COL_SCORE, score)
            verdict = QTableWidgetItem(res.verdict or "analysiert")
            verdict.setForeground(QColor(verdict_color(res.verdict)))
            self.table.setItem(row, COL_STATUS, verdict)
            summary = QTableWidgetItem(res.summary if res.error is None else res.error)
            summary.setToolTip(summary.text())
            self.table.setItem(row, COL_REASON, summary)
            for col, key in COMP_COLUMNS.items():
                v = res.components.get(key) if res.components else None
                item = NumericItem(v)
                if v is not None:
                    item.setForeground(QColor(score_color(v)))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        if selected:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 1).data(Qt.UserRole) in selected:
                    self.table.selectRow(row)
        prof = get_profile(self.settings.get("analysis/profile"))
        for col, key in COMP_COLUMNS.items():
            self.table.horizontalHeaderItem(col).setText(prof.labels.get(key, COLUMNS[col]))
        self._refresh_summary()

    def _selected_results(self) -> list[FileResult]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        out = []
        for r in rows:
            item = self.table.item(r, 1)
            res = self.results.get(item.data(Qt.UserRole)) if item else None
            if res is not None:
                out.append(res)
        return out

    def _on_selection(self):
        self._show_details(self._selected_results())

    # =============================================================== details
    def _show_details(self, results: list[FileResult]):
        res = results[0] if results else None
        self._current = res
        self._show_assessment(res)
        self._show_timeline(results)
        self._show_preview(res)
        self._show_selection(res)

    def _show_assessment(self, res: FileResult | None):
        if res is None:
            self.detail_title.setText("Keine Datei ausgewählt")
            self.detail_badge.setText("")
            self.detail_badge.setStyleSheet("")
            self.detail_meta.setText("")
            self.bars.set_components({})
            self.reasons.setHtml("")
            return
        self.detail_title.setText(res.path.name)
        if res.verdict:
            color = verdict_color(res.verdict)
            self.detail_badge.setText(f"{res.verdict} · {de_number(res.score)} %" if res.error is None else res.verdict)
            self.detail_badge.setStyleSheet(f"background:{color}; color:#0b0e14; border-radius: 4px; padding: 2px 8px;")
        info = res.info
        meta = []
        if info:
            meta.append(f"{info.format} · {info.width}×{info.height} px · {info.bit_depth} bit · {_color_name(info.color)}")
            if info.is_video:
                dur = f" · {info.duration_s:.1f} s" if info.duration_s else ""
                fps = f" · {info.fps:.1f} fps" if info.fps else ""
                meta.append(f"{info.frame_count} Frames{dur}{fps} · analysiert: {res.analyzed_frames}")
            md = {k: v for k, v in (info.metadata or {}).items() if v and k in
                  ("telescope", "instrument", "observer", "start_utc", "date_obs", "object", "exptime", "gain", "filter")}
            for k in ("start_utc", "date_obs"):
                if md.get(k):
                    md[k] = str(md[k])[:19].replace("T", " ")
            if isinstance(md.get("exptime"), (int, float)):
                md["exptime"] = f"{de_number(md['exptime'], 3).rstrip('0').rstrip(',')} s"
            if md:
                meta.append(" · ".join(f"{_meta_label(k)}: {v}" for k, v in md.items()))
        if res.error is None and res.rank:
            meta.append(f"Rang {res.rank} · Verarbeitungspotenzial: {res.potential} · Analysezeit {res.elapsed_s:.1f} s")
        self.detail_meta.setText("<br>".join(html.escape(m) for m in meta))
        self.bars.set_components(res.components, PROFILES.get(res.profile))
        styles = {"plus": ("✓", GOOD), "minus": ("✗", BAD), "info": ("•", MUTED)}
        parts = ["<h3>Begründung</h3><table cellspacing='3'>"]
        for r in res.reasons:
            sym, col = styles.get(r.kind, ("•", MUTED))
            parts.append(f"<tr><td style='color:{col}; padding-right:6px'>{sym}</td><td>{html.escape(r.text)}</td></tr>")
        parts.append("</table>")
        if res.recommendations:
            parts.append("<h3>Empfehlungen</h3><ul>")
            parts.extend(f"<li>{html.escape(t)}</li>" for t in res.recommendations)
            parts.append("</ul>")
        self.reasons.setHtml("".join(parts))

    def _show_timeline(self, results: list[FileResult]):
        series = []
        for res in results[:8]:
            if res.error or res.quality.size == 0:
                continue
            if res.times is not None:
                x, xl = res.times, "Zeit in s"
            else:
                x, xl = res.indices.astype(float), "Frame"
            series.append({"name": res.path.name, "x": x, "y": res.quality, "frames": res.indices, "xlabel": xl})
        thr = None
        if len(series) == 1:
            res = results[0]
            frac = self.sel_percent.value() / 100 if res is self._current and self.sel_percent.value() else None
            frac = frac or (res.aggregate or {}).get("recommended_fraction", 1.0)
            k = max(1, int(round(res.quality.size * frac)))
            thr = float(np.sort(res.quality)[::-1][k - 1])
        self.plot.set_series(series, thr)
        stats = []
        for res in results[:8]:
            if res.error or not res.aggregate or res.quality.size < 2:
                continue
            a = res.aggregate
            stats.append(f"{res.path.name}: Ø Qualität {a['quality_mean']:.0f}, Schwankung {a['quality_cv'] * 100:.0f} %, "
                         f"Bildunruhe {a['jitter_px']:.1f} px")
        self.timeline_stats.setText("<br>".join(html.escape(s) for s in stats))

    def _show_preview(self, res: FileResult | None):
        if res is None or res.preview is None:
            self.preview.set_frame(None)
            return
        cap = f"Bester Frame: #{res.best_index}" if res.info and res.info.is_video else "Luminanz"
        self.preview.set_frame(res.preview, res.preview_roi, res.preview_local, cap, self._full_loader(res))

    def _show_selection(self, res: FileResult | None):
        is_video = bool(res and res.error is None and res.info and res.info.is_video and res.quality.size > 1)
        for w in (self.sel_percent, self.sel_reset, self.export_ser_btn, self.export_list_btn):
            w.setEnabled(is_video)
        if not is_video:
            self.sel_info.setText("Ein Video bzw. eine Frame-Folge in der Tabelle auswählen."
                                  if res is None or res.error is None else res.error)
            self.sel_count.setText("")
            return
        a = res.aggregate
        self.sel_info.setText(
            f"<b>{html.escape(res.path.name)}</b><br>Empfehlung: die besten <b>{a['recommended_fraction'] * 100:.0f} %</b> "
            f"(≈ {a['recommended_frames']} Frames). {html.escape(a['selection_reason'])}")
        self.sel_percent.blockSignals(True)
        self.sel_percent.setValue(max(1, int(round(a["recommended_fraction"] * 100))))
        self.sel_percent.blockSignals(False)
        self._update_selection_preview()

    def _reset_selection(self):
        if self._current and self._current.aggregate:
            self.sel_percent.setValue(max(1, int(round(self._current.aggregate["recommended_fraction"] * 100))))

    def _update_selection_preview(self):
        res = self._current
        if not res or not res.info or not res.info.is_video:
            return
        total = res.info.frame_count
        self.sel_count.setText(f"→ {max(1, int(round(total * self.sel_percent.value() / 100)))} von {total} Frames "
                               "werden exportiert.")
        self._show_timeline(self._selected_results() or [res])

    # ================================================================ export
    def export_report(self, kind: str | None = None):
        if not self.session:
            return
        ext = "json" if kind == "json" else "csv"
        start = str(Path(self._start_dir()) / f"FrameForge-Bericht.{ext}")
        filters = {"json": "JSON-Bericht (*.json)", "csv": "CSV-Tabelle (*.csv)"}.get(
            kind, "CSV-Tabelle (*.csv);;JSON-Bericht (*.json)")
        path, flt = QFileDialog.getSaveFileName(self, "Bericht exportieren", start, filters)
        if not path:
            return
        try:
            if path.lower().endswith(".json") or "JSON" in flt:
                path = path if path.lower().endswith(".json") else path + ".json"
                export_json(self.session, path, include_frames=True)
            else:
                path = path if path.lower().endswith(".csv") else path + ".csv"
                export_csv(self.session, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export", f"Bericht konnte nicht gespeichert werden:\n{exc}")
            return
        self._saved(f"Bericht gespeichert: {path}")

    def _saved(self, text: str):
        self.status_label.setText(text)
        self.reports.set_last_saved(f"{datetime.now():%d.%m.%Y %H:%M} – {text}")

    def save_project(self):
        if not self.session:
            return
        start = str(Path(self._start_dir()) / f"FrameForge-Projekt{PROJECT_EXTENSION}")
        path, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", start,
                                              f"FrameForge-Projekt (*{PROJECT_EXTENSION})")
        if not path:
            return
        try:
            dest = save_project(self.session, path, self.queue)
        except OSError as exc:
            QMessageBox.warning(self, "Projekt", f"Projekt konnte nicht gespeichert werden:\n{exc}")
            return
        self._saved(f"Projekt gespeichert: {dest}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Projekt öffnen", self._start_dir(),
                                              f"FrameForge-Projekt (*{PROJECT_EXTENSION});;Alle Dateien (*)")
        if path:
            self.load_project_file(Path(path))

    def load_project_file(self, path: Path):
        if self.worker and self.worker.isRunning():
            return
        try:
            session, queue = load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "Projekt", f"Projekt konnte nicht geöffnet werden:\n{exc}")
            return
        self.settings.set("ui/last_dir", str(path.parent))
        self.queue = queue
        self._set_profile(session.profile)
        self._set_mode(session.mode)
        self._apply_session(session)
        missing = sum(1 for p in queue if not p.exists())
        note = f" – {missing} Originaldatei(en) nicht gefunden (Zoom/Export eingeschränkt)" if missing else ""
        self.status_label.setText(f"Projekt geöffnet: {path.name}{note}")
        self.goto(PAGE_OVERVIEW)

    def export_frame_list(self):
        res = self._current
        if not res:
            return
        start = str(res.path.with_name(res.path.stem + "_frames.csv"))
        path, _ = QFileDialog.getSaveFileName(self, "Frame-Liste speichern", start, "CSV-Tabelle (*.csv)")
        if path:
            export_frame_list(res, path, self.sel_percent.value() / 100)
            self._saved(f"Frame-Liste gespeichert: {path}")

    def export_best_frames(self):
        res = self._current
        if not res or (self.export_worker and self.export_worker.isRunning()):
            return
        if not res.path.exists():
            QMessageBox.warning(self, "Export", f"Originaldatei nicht gefunden:\n{res.path}")
            return
        pct = self.sel_percent.value()
        start = str(res.path.with_name(f"{res.path.stem}_best{pct}.ser"))
        path, _ = QFileDialog.getSaveFileName(self, "Beste Frames speichern", start, "SER-Video (*.ser)")
        if not path:
            return
        if not path.lower().endswith(".ser"):
            path += ".ser"
        if Path(path).resolve() == res.path.resolve():
            QMessageBox.warning(self, "Export", "Die Originaldatei kann nicht überschrieben werden.")
            return
        self.export_worker = ExportWorker(res, path, pct / 100, self._options(), self)
        self.export_worker.progress.connect(self._on_progress)
        self.export_worker.done.connect(self._on_export_done)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.finished.connect(self._update_actions)
        self.progress.setValue(0)
        self.progress.show()
        self.export_worker.start()
        self._update_actions()

    def _on_export_done(self, path, n):
        self.progress.hide()
        self._saved(f"{n} Frames exportiert: {path}")

    def _on_export_failed(self, msg):
        self.progress.hide()
        self.status_label.setText(msg)
        if msg != "Export abgebrochen.":
            QMessageBox.warning(self, "Export", msg)

    # =============================================================== updates
    def check_updates_silently(self):
        if not self.settings.get("updates/check_on_start"):
            return
        self.update_worker = UpdateCheckWorker(self.settings.get("updates/include_prerelease"), self)
        self.update_worker.result.connect(self._on_update_result)
        self.update_worker.failed.connect(lambda _msg: None)  # silent on start
        self.update_worker.start()

    def check_updates_now(self):
        self.goto(PAGE_SETTINGS)
        self.settings_page.check_updates()

    def _on_update_result(self, release):
        self.settings.set("updates/last_check", datetime.now().strftime("%d.%m.%Y %H:%M"))
        if release is None:
            return
        self.available_update = release
        self.settings_page.show_release(release)
        btn = self.nav_buttons[PAGE_SETTINGS]
        btn.setText("Einstellungen  ●")
        btn.setToolTip(f"Update auf Version {release.version} verfügbar")
        self.status_label.setText(f"Update auf Version {release.version} verfügbar – siehe Einstellungen.")


def _color_name(color: str) -> str:
    if color.startswith("bayer"):
        return f"Farbe (Bayer {color.split('_', 1)[1]})"
    return {"mono": "Mono", "rgb": "Farbe (RGB)", "bgr": "Farbe (RGB)"}.get(color, color)


def _meta_label(key: str) -> str:
    return {"telescope": "Teleskop", "instrument": "Kamera", "observer": "Beobachter", "start_utc": "Start (UTC)",
            "date_obs": "Aufnahme", "object": "Objekt", "exptime": "Belichtung", "gain": "Gain",
            "filter": "Filter"}.get(key, key)
