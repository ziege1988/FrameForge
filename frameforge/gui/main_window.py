"""Main application window."""

from __future__ import annotations

import html
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_SUBTITLE, __version__
from ..core.analyzer import MODE_LABELS, AnalysisOptions, FileResult, SessionResult
from ..core.export import export_csv, export_frame_list, export_json
from ..core.io.registry import FORMAT_GROUPS, collect_files
from ..core.profiles import PROFILES
from .resources import app_icon, logo_pixmap
from .settings import Settings
from .settings_dialog import SettingsDialog
from .theme import BAD, GOOD, MUTED, score_color, verdict_color
from .widgets import ComponentBars, PreviewWidget, QualityPlot
from .workers import AnalysisWorker, ExportWorker, UpdateCheckWorker

COLUMNS = ["Rang", "Datei", "Format", "Frames", "Score", "Urteil", "Potenzial",
           "Schärfe", "Kontrast", "SNR", "Belichtung", "Stabilität"]
COMP_COLUMNS = {7: "sharpness", 8: "contrast", 9: "noise", 10: "exposure", 11: "stability"}


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
        self.setWindowTitle(f"{APP_NAME} – {APP_SUBTITLE}")
        self.setWindowIcon(app_icon())
        self.resize(1360, 840)
        self.setAcceptDrops(True)

        self.queue: list[Path] = []
        self.session: SessionResult | None = None
        self.results: dict[str, FileResult] = {}
        self.worker: AnalysisWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.update_worker: UpdateCheckWorker | None = None
        self.available_update = None
        self._current: FileResult | None = None

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._restore_state()
        self._refresh_table()
        self._update_actions()

    # ------------------------------------------------------------------ UI
    def _build_toolbar(self):
        tb = QToolBar("Werkzeuge")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(26, self.devicePixelRatioF()))
        logo.setContentsMargins(4, 0, 6, 0)
        tb.addWidget(logo)

        self.act_open_dir = QAction("Ordner öffnen …", self, shortcut=QKeySequence.Open)
        self.act_open_dir.triggered.connect(self.open_folder)
        self.act_add_files = QAction("Dateien hinzufügen …", self)
        self.act_add_files.triggered.connect(self.add_files)
        self.act_clear = QAction("Liste leeren", self)
        self.act_clear.triggered.connect(self.clear_queue)
        for a in (self.act_open_dir, self.act_add_files, self.act_clear):
            tb.addAction(a)
        tb.addSeparator()

        tb.addWidget(QLabel(" Objekt: "))
        self.profile_box = QComboBox()
        for key, prof in PROFILES.items():
            self.profile_box.addItem(prof.name, key)
            self.profile_box.setItemData(self.profile_box.count() - 1, prof.description, Qt.ToolTipRole)
        self.profile_box.setCurrentIndex(max(0, self.profile_box.findData(self.settings.get("analysis/profile"))))
        tb.addWidget(self.profile_box)
        tb.addWidget(QLabel("  Modus: "))
        self.mode_box = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode_box.addItem(label, key)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(self.settings.get("analysis/mode"))))
        tb.addWidget(self.mode_box)
        tb.addSeparator()

        self.start_btn = QPushButton("Analyse starten")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_analysis)
        tb.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("Abbrechen")
        self.cancel_btn.clicked.connect(self.cancel_analysis)
        tb.addWidget(self.cancel_btn)
        tb.addSeparator()

        self.act_export = QAction("Bericht exportieren …", self)
        self.act_export.triggered.connect(self.export_report)
        tb.addAction(self.act_export)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.act_settings = QAction("Einstellungen", self, shortcut=QKeySequence.Preferences)
        self.act_settings.triggered.connect(lambda: self.open_settings())
        tb.addAction(self.act_settings)

    def _build_central(self):
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("muted")
        self.summary_label.setWordWrap(True)
        lv.addWidget(self.summary_label)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setSortingEnabled(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 220)
        self.table.itemSelectionChanged.connect(self._on_selection)
        lv.addWidget(self.table, 1)
        self.empty_hint = QLabel(
            "Ordner oder Dateien per Drag & Drop hierher ziehen oder über „Ordner öffnen …“ auswählen.<br>"
            "Unterstützt: SER, AVI, FITS, TIFF, RAW (CR2, CR3, NEF, ARW, DNG …), PNG, JPEG."
        )
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        lv.addWidget(self.empty_hint)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_assessment_tab(), "Bewertung")
        self.tabs.addTab(self._build_timeline_tab(), "Qualitätsverlauf")
        self.tabs.addTab(self._build_preview_tab(), "Vorschau")
        self.tabs.addTab(self._build_selection_tab(), "Frame-Selektion")
        self.tabs.addTab(self._build_session_tab(), "Session")
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 8, 8, 8)
        rv.addWidget(self.tabs)
        splitter.addWidget(right)
        splitter.setSizes([820, 560])
        self.splitter = splitter
        self.setCentralWidget(splitter)

    def _build_assessment_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        head = QHBoxLayout()
        self.detail_title = QLabel("Keine Datei ausgewählt")
        self.detail_title.setObjectName("h1")
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
        hint = QLabel("Frame-Qualität im Verlauf der Aufnahme (100 = beste Frames der Datei). "
                      "Mehrere Dateien in der Tabelle markieren, um Videos zu vergleichen.")
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
        self.preview = PreviewWidget()
        v.addWidget(self.preview, 1)
        self.map_check = QCheckBox("Lokale Qualitätskarte einblenden (relative Schärfe je Bildbereich)")
        self.map_check.setChecked(True)
        self.map_check.toggled.connect(self._toggle_map)
        v.addWidget(self.map_check)
        return w

    def _build_selection_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
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
        self.export_ser_btn = QPushButton("Beste Frames als SER exportieren …")
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

    def _build_session_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.session_text = QTextBrowser()
        v.addWidget(self.session_text)
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
        sb.addPermanentWidget(QLabel(f"v{__version__}  "))

    def _restore_state(self):
        geo = self.settings.get("ui/geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.export_worker.wait(5000)
        self.settings.set("ui/geometry", self.saveGeometry())
        self.settings.set("analysis/profile", self.profile_box.currentData())
        self.settings.set("analysis/mode", self.mode_box.currentData())
        self.settings.sync()
        super().closeEvent(event)

    # ------------------------------------------------------------- queue
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        self.add_paths(paths)

    def open_folder(self):
        start = self.settings.get("ui/last_dir") or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Aufnahmeordner wählen", start)
        if folder:
            self.settings.set("ui/last_dir", folder)
            self.add_paths([Path(folder)])

    def add_files(self):
        start = self.settings.get("ui/last_dir") or str(Path.home())
        patterns = " ".join(f"*{e}" for g in FORMAT_GROUPS.values() for e in sorted(g))
        files, _ = QFileDialog.getOpenFileNames(self, "Dateien auswählen", start,
                                                f"Astro-Aufnahmen ({patterns});;Alle Dateien (*)")
        if files:
            self.settings.set("ui/last_dir", str(Path(files[0]).parent))
            self.add_paths([Path(f) for f in files])

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
        self._update_session_tab()
        self._update_actions()

    # ---------------------------------------------------------- analysis
    def _options(self) -> AnalysisOptions:
        return AnalysisOptions(profile=self.profile_box.currentData(), mode=self.mode_box.currentData(),
                               threads=self.settings.get("analysis/threads"), recursive=False)

    def start_analysis(self):
        if not self.queue or (self.worker and self.worker.isRunning()):
            return
        self.results.clear()
        self.session = None
        self._refresh_table()
        self.worker = AnalysisWorker(self.queue, self._options(), self)
        self.worker.progress.connect(self._on_progress)
        self.worker.fileDone.connect(self._on_file_done)
        self.worker.finishedSession.connect(self._on_session_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._update_actions)
        self.progress.setValue(0)
        self.progress.show()
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

    def _on_file_done(self, result: FileResult):
        self.results[str(result.path)] = result
        self._refresh_table()

    def _on_session_done(self, session: SessionResult):
        self.session = session
        self.results = {str(f.path): f for f in session.files}
        self.progress.hide()
        n_ok = sum(1 for f in session.files if f.error is None)
        self.status_label.setText(
            ("Analyse abgebrochen – " if session.cancelled else "Analyse abgeschlossen – ")
            + f"{n_ok} von {len(self.queue)} Dateien ausgewertet."
        )
        self._refresh_table()
        self.table.sortItems(0, Qt.AscendingOrder)
        if self.table.rowCount():
            self.table.selectRow(0)
        self._update_session_tab()

    def _on_failed(self, msg):
        self.progress.hide()
        QMessageBox.critical(self, "Fehler", f"Die Analyse ist fehlgeschlagen:\n\n{msg[-1500:]}")

    def _update_actions(self):
        running = bool(self.worker and self.worker.isRunning())
        exporting = bool(self.export_worker and self.export_worker.isRunning())
        self.start_btn.setEnabled(bool(self.queue) and not running and not exporting)
        self.cancel_btn.setEnabled(running or exporting)
        for a in (self.act_open_dir, self.act_add_files, self.act_clear):
            a.setEnabled(not running)
        self.profile_box.setEnabled(not running)
        self.mode_box.setEnabled(not running)
        self.act_export.setEnabled(self.session is not None and not running)
        self.empty_hint.setVisible(not self.queue)

    # -------------------------------------------------------------- table
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
                self.table.setItem(row, 0, NumericItem(None, ""))
                self.table.setItem(row, 2, QTableWidgetItem(path.suffix.upper().lstrip(".")))
                for c in range(3, len(COLUMNS)):
                    self.table.setItem(row, c, NumericItem(None, "" if c != 5 else "wartet"))
                continue
            info = res.info
            self.table.setItem(row, 0, NumericItem(res.rank or None, str(res.rank) if res.rank else "–"))
            self.table.setItem(row, 2, QTableWidgetItem(info.format if info else path.suffix.upper().lstrip(".")))
            self.table.setItem(row, 3, NumericItem(info.frame_count if info else None))
            has_score = bool(res.verdict) and res.error is None
            score = NumericItem(res.score if has_score else None,
                                f"{res.score:.0f}" if has_score else ("–" if res.error else "…"))
            if has_score:
                score.setForeground(QColor(score_color(res.score)))
            self.table.setItem(row, 4, score)
            verdict = QTableWidgetItem(res.verdict or "analysiert")
            verdict.setForeground(QColor(verdict_color(res.verdict)))
            if res.error:
                verdict.setToolTip(res.error)
            self.table.setItem(row, 5, verdict)
            self.table.setItem(row, 6, QTableWidgetItem(res.potential))
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
        n_done = sum(1 for p in self.queue if str(p) in self.results)
        prof = PROFILES[self.profile_box.currentData()].name
        self.summary_label.setText(
            f"{len(self.queue)} Datei(en) in der Liste · {n_done} analysiert · Profil: {prof}" if self.queue else ""
        )

    def _selected_results(self) -> list[FileResult]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        out = []
        for r in rows:
            item = self.table.item(r, 1)
            if item is None:
                continue
            res = self.results.get(item.data(Qt.UserRole))
            if res is not None:
                out.append(res)
        return out

    def _on_selection(self):
        self._show_details(self._selected_results())

    # ------------------------------------------------------------ details
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
        color = verdict_color(res.verdict)
        if res.verdict:
            self.detail_badge.setText(f"{res.verdict} · {res.score:.0f}" if res.error is None else res.verdict)
            self.detail_badge.setStyleSheet(f"background:{color}; color:#0b0e14;")
        info = res.info
        meta = []
        if info:
            meta.append(f"{info.format} · {info.width}×{info.height} px · {info.bit_depth} bit · {_color_name(info.color)}")
            if info.is_video:
                dur = f" · {info.duration_s:.1f} s" if info.duration_s else ""
                fps = f" · {info.fps:.1f} fps" if info.fps else ""
                meta.append(f"{info.frame_count} Frames{dur}{fps} · analysiert: {res.analyzed_frames}")
            md = {k: v for k, v in (info.metadata or {}).items() if v and k in
                  ("telescope", "instrument", "observer", "start_utc", "object", "exptime", "gain", "filter")}
            if md.get("start_utc"):
                md["start_utc"] = str(md["start_utc"])[:19].replace("T", " ")
            if md:
                meta.append(" · ".join(f"{_meta_label(k)}: {v}" for k, v in md.items()))
        if res.error is None and res.rank:
            meta.append(f"Rang {res.rank} · Verarbeitungspotenzial: {res.potential} · Analysezeit {res.elapsed_s:.1f} s")
        self.detail_meta.setText("<br>".join(html.escape(m) for m in meta))
        self.bars.set_components(res.components)
        icons = {"plus": ("✓", GOOD), "minus": ("✗", BAD), "info": ("•", MUTED)}
        parts = ["<h3>Begründung</h3><table cellspacing='3'>"]
        for r in res.reasons:
            sym, col = icons.get(r.kind, ("•", MUTED))
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
        cap = f"Bester Frame: #{res.best_index}" if res.info and res.info.is_video else "Vorschau (Luminanz)"
        self.preview.set_frame(res.preview, res.preview_roi, res.preview_local, cap)

    def _toggle_map(self, on):
        self.preview.show_map = on
        self.preview.update()

    def _show_selection(self, res: FileResult | None):
        is_video = bool(res and res.error is None and res.info and res.info.is_video)
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
            f"(≈ {a['recommended_frames']} Frames). {html.escape(a['selection_reason'])}"
        )
        self.sel_percent.blockSignals(True)
        self.sel_percent.setValue(max(1, int(round(a["recommended_fraction"] * 100))))
        self.sel_percent.blockSignals(False)
        self._update_selection_preview()

    def _reset_selection(self):
        if self._current and self._current.aggregate:
            self.sel_percent.setValue(max(1, int(round(self._current.aggregate["recommended_fraction"] * 100))))

    def _update_selection_preview(self):
        res = getattr(self, "_current", None)
        if not res or not res.info or not res.info.is_video:
            return
        frac = self.sel_percent.value() / 100
        total = res.info.frame_count
        self.sel_count.setText(f"→ {max(1, int(round(total * frac)))} von {total} Frames werden exportiert.")
        self._show_timeline(self._selected_results() or [res])

    # ------------------------------------------------------------- export
    def export_report(self):
        if not self.session:
            return
        start = str(Path(self.settings.get("ui/last_dir") or Path.home()) / "FrameForge-Bericht.csv")
        path, flt = QFileDialog.getSaveFileName(self, "Bericht exportieren", start,
                                                "CSV-Tabelle (*.csv);;JSON-Bericht (*.json)")
        if not path:
            return
        try:
            if path.lower().endswith(".json") or "JSON" in flt:
                if not path.lower().endswith(".json"):
                    path += ".json"
                export_json(self.session, path, include_frames=True)
            else:
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                export_csv(self.session, path)
            self.status_label.setText(f"Bericht gespeichert: {path}")
        except OSError as exc:
            QMessageBox.warning(self, "Export", f"Bericht konnte nicht gespeichert werden:\n{exc}")

    def export_frame_list(self):
        res = self._current
        if not res:
            return
        start = str(res.path.with_name(res.path.stem + "_frames.csv"))
        path, _ = QFileDialog.getSaveFileName(self, "Frame-Liste speichern", start, "CSV-Tabelle (*.csv)")
        if path:
            export_frame_list(res, path, self.sel_percent.value() / 100)
            self.status_label.setText(f"Frame-Liste gespeichert: {path}")

    def export_best_frames(self):
        res = self._current
        if not res or (self.export_worker and self.export_worker.isRunning()):
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
        self.status_label.setText(f"{n} Frames exportiert: {path}")

    def _on_export_failed(self, msg):
        self.progress.hide()
        self.status_label.setText(msg)
        if msg != "Export abgebrochen.":
            QMessageBox.warning(self, "Export", msg)

    # ----------------------------------------------------------- session
    def _update_session_tab(self):
        s = self.session
        if s is None:
            self.session_text.setHtml("<p style='color:#8b93a7'>Noch keine Analyse durchgeführt.</p>")
            return
        ok = [f for f in s.files if f.error is None]
        parts = [f"<h3>Session-Übersicht</h3><p>Profil: <b>{PROFILES[s.profile].name}</b> · "
                 f"Modus: {MODE_LABELS[s.mode]} · {len(s.files)} Dateien</p><ul>"]
        parts.extend(f"<li>{html.escape(r)}</li>" for r in s.recommendations)
        parts.append("</ul>")
        if ok:
            parts.append("<h3>Rangliste</h3><table cellspacing='4'>")
            for f in s.ranked():
                if f.error:
                    continue
                parts.append(f"<tr><td>{f.rank}.</td><td>{html.escape(f.path.name)}</td>"
                             f"<td style='color:{score_color(f.score)}'>{f.score:.0f}</td>"
                             f"<td style='color:{verdict_color(f.verdict)}'>{f.verdict}</td></tr>")
            parts.append("</table>")
        errors = [f for f in s.files if f.error]
        if errors:
            parts.append("<h3>Nicht auswertbar</h3><ul>")
            parts.extend(f"<li>{html.escape(f.path.name)}: {html.escape(f.error)}</li>" for f in errors)
            parts.append("</ul>")
        self.session_text.setHtml("".join(parts))

    # ----------------------------------------------------------- updates
    def check_updates_silently(self):
        if not self.settings.get("updates/check_on_start"):
            return
        self.update_worker = UpdateCheckWorker(self.settings.get("updates/include_prerelease"), self)
        self.update_worker.result.connect(self._on_update_result)
        self.update_worker.failed.connect(lambda _msg: None)  # silent on start
        self.update_worker.start()

    def _on_update_result(self, release):
        from datetime import datetime

        self.settings.set("updates/last_check", datetime.now().strftime("%d.%m.%Y %H:%M"))
        if release is None:
            return
        self.available_update = release
        self.act_settings.setText(f"Einstellungen  ● Update {release.version}")
        self.act_settings.setToolTip("Eine neue Version ist verfügbar – in den Einstellungen installieren.")
        self.status_label.setText(f"Update auf Version {release.version} verfügbar – siehe Einstellungen › Updates.")

    def open_settings(self, updates: bool | None = None):
        if updates is None:
            updates = self.available_update is not None
        dlg = SettingsDialog(self.settings, self, open_updates=updates, release=self.available_update)
        dlg.updateAvailable.connect(self._on_update_result)
        if dlg.exec():
            self.profile_box.setCurrentIndex(max(0, self.profile_box.findData(self.settings.get("analysis/profile"))))
            self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(self.settings.get("analysis/mode"))))


def _color_name(color: str) -> str:
    if color.startswith("bayer"):
        return f"Farbe (Bayer {color.split('_', 1)[1]})"
    return {"mono": "Mono", "rgb": "Farbe (RGB)", "bgr": "Farbe (RGB)"}.get(color, color)


def _meta_label(key: str) -> str:
    return {"telescope": "Teleskop", "instrument": "Kamera", "observer": "Beobachter", "start_utc": "Start (UTC)",
            "object": "Objekt", "exptime": "Belichtung", "gain": "Gain", "filter": "Filter"}.get(key, key)
