"""Overview page ("Übersicht"): welcome state, progress and result dashboard."""

from __future__ import annotations

import html
from collections import Counter

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core.profiles import PROFILES
from ..core.scoring import VERDICT_CONDITIONAL, VERDICT_RECOMMENDED, VERDICT_REJECT
from . import icons
from .components import Badge, Card, DonutChart, OptionButton, Sparkline, ZoomPreview, format_duration, status_icon
from .resources import logo_pixmap
from .theme import ACCENT, BAD, GOOD, MUTED, WARN, de_number, score_color
from .welcome import profile_chips


def wordmark(size: int = 30) -> QLabel:
    lbl = QLabel(f"<span style='font-size:{size}px; font-weight:800; font-style:italic; color:#ffffff'>Frame</span>"
                 f"<span style='font-size:{size}px; font-weight:800; font-style:italic; color:#4f95ff'>Forge</span>")
    lbl.setTextFormat(Qt.RichText)
    return lbl


def slogan_label() -> QLabel:
    lbl = QLabel("<i>Analyse. <b>Entscheide.</b> Perfektioniere.</i>")
    lbl.setStyleSheet("font-size: 16px; color: #dfe7f7;")
    return lbl


class OverviewPage(QWidget):
    requestFolder = Signal()
    requestVideo = Signal()
    requestProject = Signal()
    profileChosen = Signal(str)
    fileActivated = Signal(str)  # path → open in analysis page

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files = []
        self._loader_factory = None
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_running())
        self.stack.addWidget(self._build_results())

    # ------------------------------------------------------------- welcome
    def _build_empty(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(220, self.devicePixelRatioF()))
        row.addWidget(logo)
        row.addSpacing(30)
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(wordmark(44))
        col.addWidget(slogan_label())
        desc = QLabel("Die intelligente Qualitätsprüfung für deine Astrofotos und -Videos.")
        desc.setObjectName("muted")
        desc.setStyleSheet("font-size: 14px;")
        col.addWidget(desc)
        col.addSpacing(10)
        chips, self.profile_group = profile_chips("planet", self)
        self.profile_group.buttonClicked.connect(lambda b: self.profileChosen.emit(b.property("profile")))
        col.addLayout(chips)
        col.addSpacing(8)
        for sig, icon_name, text, sub, primary in (
            (self.requestFolder, "folder", "Ordner analysieren", "Fotos & Videos (z. B. SER, RAW, FITS)", True),
            (self.requestVideo, "play", "Video analysieren", "z. B. SER, AVI, MP4", False),
            (self.requestProject, "folder-open", "Projekt öffnen", "Gespeichertes Projekt laden", False),
        ):
            b = OptionButton(icon_name, text, sub, primary)
            b.setMaximumWidth(520)
            b.clicked.connect(sig.emit)
            col.addWidget(b)
        hint = QLabel("Tipp: Ordner oder Dateien einfach ins Fenster ziehen.")
        hint.setObjectName("muted")
        col.addWidget(hint)
        row.addLayout(col)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        return w

    def set_profile(self, key: str):
        for b in self.profile_group.buttons():
            b.setChecked(b.property("profile") == key)

    # ------------------------------------------------------------- running
    def _build_running(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(64, self.devicePixelRatioF()))
        head.addWidget(logo)
        col = QVBoxLayout()
        t = QLabel("Analyse läuft …")
        t.setObjectName("h1")
        self.run_msg = QLabel()
        self.run_msg.setObjectName("muted")
        col.addWidget(t)
        col.addWidget(self.run_msg)
        head.addLayout(col, 1)
        lay.addLayout(head)
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 1000)
        lay.addWidget(self.run_progress)
        card = Card("Bereits analysiert", "check", GOOD)
        self.run_list = QTextBrowser()
        card.body.addWidget(self.run_list)
        lay.addWidget(card, 1)
        return w

    def show_running(self, total: int):
        self.run_list.clear()
        self.run_progress.setValue(0)
        self.run_msg.setText(f"{total} Datei(en) in der Warteschlange")
        self.stack.setCurrentIndex(1)

    def update_running(self, msg: str, frac: float):
        self.run_msg.setText(msg)
        self.run_progress.setValue(int(frac * 1000))

    def add_running_file(self, result):
        state = "Fehler: " + result.error if result.error else f"{result.analyzed_frames} Frame(s) in {result.elapsed_s:.1f} s"
        color = BAD if result.error else MUTED
        self.run_list.append(f"<span style='color:{GOOD}'>✓</span> {html.escape(result.path.name)} "
                             f"<span style='color:{color}'>– {html.escape(state)}</span>")

    def show_empty(self):
        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------- results
    def _build_results(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        head = QHBoxLayout()
        self.head_icon = QLabel()
        head.addWidget(self.head_icon)
        head.addSpacing(6)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.head_title = QLabel()
        self.head_title.setObjectName("h1")
        self.head_sub = QLabel()
        self.head_sub.setStyleSheet("font-size: 14px;")
        col.addWidget(self.head_title)
        col.addWidget(self.head_sub)
        head.addLayout(col, 1)
        time_card = Card()
        time_card.body.setContentsMargins(16, 10, 22, 10)
        tr = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("clock", 28, "#c9d2e6"))
        tr.addWidget(ic)
        tc = QVBoxLayout()
        tc.setSpacing(0)
        lbl = QLabel("Gesamtzeit")
        lbl.setObjectName("muted")
        self.time_value = QLabel()
        self.time_value.setObjectName("h2")
        tc.addWidget(lbl)
        tc.addWidget(self.time_value)
        tr.addLayout(tc)
        time_card.body.addLayout(tr)
        head.addWidget(time_card)
        lay.addLayout(head)

        cards = QGridLayout()
        cards.setSpacing(14)
        # Donut ---------------------------------------------------------
        dc = Card()
        drow = QHBoxLayout()
        self.donut = DonutChart()
        drow.addWidget(self.donut)
        drow.addSpacing(12)
        legend = QGridLayout()
        legend.setVerticalSpacing(8)
        self.legend_values = {}
        for i, (name, color) in enumerate(((VERDICT_RECOMMENDED, GOOD), (VERDICT_CONDITIONAL, WARN),
                                           (VERDICT_REJECT, BAD), ("Gesamt", None))):
            dot = QLabel("●" if color else "")
            dot.setStyleSheet(f"color: {color or MUTED}; font-size: 14px;")
            name_lbl = QLabel(name)
            if not color:
                name_lbl.setObjectName("muted")
            val = QLabel("0")
            val.setAlignment(Qt.AlignRight)
            legend.addWidget(dot, i, 0)
            legend.addWidget(name_lbl, i, 1)
            legend.addWidget(val, i, 2)
            self.legend_values[name] = val
        legend.setColumnMinimumWidth(2, 36)
        drow.addLayout(legend)
        drow.addStretch(1)
        dc.body.addLayout(drow)
        cards.addWidget(dc, 0, 0)
        # Score -----------------------------------------------------------
        sc = Card("Qualitäts-Score (Ø)")
        srow = QHBoxLayout()
        self.score_value = QLabel()
        self.score_value.setObjectName("big")
        self.score_trend = QLabel()
        self.score_trend.setStyleSheet("font-size: 15px; font-weight: 600;")
        srow.addWidget(self.score_value)
        srow.addSpacing(10)
        srow.addWidget(self.score_trend, 0, Qt.AlignVCenter)
        srow.addStretch(1)
        sc.body.addLayout(srow)
        self.spark = Sparkline(GOOD)
        sc.body.addWidget(self.spark)
        cards.addWidget(sc, 0, 1)
        # Top -------------------------------------------------------------
        topc = Card("Top-Ergebnisse", "trophy", WARN)
        self.top_grid = QGridLayout()
        self.top_grid.setVerticalSpacing(10)
        topc.body.addLayout(self.top_grid)
        topc.body.addStretch(1)
        cards.addWidget(topc, 0, 2)
        for c in range(3):
            cards.setColumnStretch(c, 1)
        lay.addLayout(cards)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        tabs_card = Card()
        tabs_card.body.setContentsMargins(0, 0, 0, 8)
        self.tabs = QTabWidget()
        self.details = QTableWidget(0, 5)
        self.details.setHorizontalHeaderLabels(["Dateiname", "Typ", "Qualität", "Status", "Begründung"])
        self.details.verticalHeader().hide()
        self.details.setShowGrid(False)
        self.details.setAlternatingRowColors(True)
        self.details.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.details.setSelectionMode(QAbstractItemView.SingleSelection)
        self.details.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.details.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.details.verticalHeader().setDefaultSectionSize(34)
        self.details.itemSelectionChanged.connect(self._on_detail_selected)
        self.details.cellDoubleClicked.connect(self._on_detail_activated)
        self.rejections = QTextBrowser()
        self.recommendations = QTextBrowser()
        self.tabs.addTab(self.details, "Details")
        self.tabs.addTab(self.rejections, "Ausschluss-Gründe")
        self.tabs.addTab(self.recommendations, "Empfehlungen")
        tabs_card.body.addWidget(self.tabs)
        bottom.addWidget(tabs_card, 3)
        pc = Card("Vorschau")
        self.preview = ZoomPreview(show_map=False)
        pc.body.addWidget(self.preview, 1)
        bottom.addWidget(pc, 2)
        lay.addLayout(bottom, 1)
        return w

    def show_session(self, session, loader_factory=None):
        """loader_factory(result) → callable that loads the full resolution best frame."""
        self._loader_factory = loader_factory
        files = session.ranked()
        self._files = files
        ok = [f for f in files if f.error is None]
        n_total = len(files)
        counts = Counter(f.verdict for f in ok)
        n_rec, n_cond, n_rej = (counts.get(VERDICT_RECOMMENDED, 0), counts.get(VERDICT_CONDITIONAL, 0),
                                counts.get(VERDICT_REJECT, 0))
        n_err = n_total - len(ok)
        share = n_rec / n_total if n_total else 0.0

        if session.cancelled:
            self.head_icon.setPixmap(icons.pixmap("warn", 44, WARN))
            self.head_title.setText("Analyse abgebrochen")
        else:
            self.head_icon.setPixmap(icons.pixmap("check", 44, GOOD))
            self.head_title.setText("Analyse abgeschlossen!")
        prof = PROFILES.get(session.profile)
        extra = f" · {n_err} nicht lesbar" if n_err else ""
        self.head_sub.setText(f"{n_rec} von {n_total} Dateien empfohlen ({de_number(share * 100)} %){extra}"
                              f"  ·  Profil: {prof.name if prof else session.profile}")
        self.time_value.setText(format_duration(session.elapsed_s))

        self.donut.set_parts([(n_rec, GOOD), (n_cond, WARN), (n_rej + n_err, BAD)], f"{de_number(share * 100)} %")
        self.legend_values[VERDICT_RECOMMENDED].setText(str(n_rec))
        self.legend_values[VERDICT_CONDITIONAL].setText(str(n_cond))
        self.legend_values[VERDICT_REJECT].setText(str(n_rej + n_err))
        self.legend_values["Gesamt"].setText(str(n_total))

        scores = [f.score for f in ok]
        self.score_value.setText(f"{de_number(float(np.mean(scores)))} %" if scores else "–")
        chrono = sorted(ok, key=lambda f: (f.timeline_start or 0, f.path.name))
        values = [f.score for f in chrono]
        self.spark.set_values(values)
        if len(values) >= 4:
            half = len(values) // 2
            delta = float(np.mean(values[half:]) - np.mean(values[:half]))
            arrow = "↑" if delta >= 0 else "↓"
            sign = "+" if delta >= 0 else "−"
            color = GOOD if delta >= 0 else BAD
            self.score_trend.setText(f"{arrow} {sign}{de_number(abs(delta))} %")
            self.score_trend.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color};")
            self.score_trend.setToolTip("Veränderung des Ø-Scores zwischen erster und zweiter Hälfte der Session "
                                        "(chronologisch)")
            self.spark.color = color
        else:
            self.score_trend.setText("")
            self.spark.color = ACCENT

        while self.top_grid.count():
            item = self.top_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, f in enumerate(ok[:3]):
            ic = QLabel()
            ic.setPixmap(status_icon(f.verdict, 20))
            name = QLabel(f.path.name)
            name.setToolTip(str(f.path))
            val = QLabel(f"{de_number(f.score)} %")
            val.setAlignment(Qt.AlignRight)
            val.setStyleSheet(f"color: {score_color(f.score)}; font-weight: 600;")
            self.top_grid.addWidget(ic, i, 0)
            self.top_grid.addWidget(name, i, 1)
            self.top_grid.addWidget(val, i, 2)
        self.top_grid.setColumnStretch(1, 1)

        self._fill_details(files)
        self._fill_rejections(files)
        self._fill_recommendations(session, ok)
        self.stack.setCurrentIndex(2)
        if files:
            self.details.selectRow(0)

    def _fill_details(self, files):
        self.details.setRowCount(len(files))
        for row, f in enumerate(files):
            name = QTableWidgetItem(f.path.name)
            name.setIcon(status_icon(f.verdict or "Fehler", 18))
            name.setData(Qt.UserRole, str(f.path))
            name.setToolTip(str(f.path))
            self.details.setItem(row, 0, name)
            self.details.setItem(row, 1, QTableWidgetItem(f.info.format if f.info else f.path.suffix.upper()[1:]))
            q = QTableWidgetItem(f"{de_number(f.score)} %" if f.error is None else "–")
            q.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.details.setItem(row, 2, q)
            badge = Badge(f.verdict or "Fehler")
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(4, 3, 4, 3)
            hl.addWidget(badge)
            hl.addStretch(1)
            self.details.setCellWidget(row, 3, holder)
            reason = f.summary if f.error is None else f.error
            item = QTableWidgetItem(reason)
            item.setToolTip(reason)
            self.details.setItem(row, 4, item)

    def _fill_rejections(self, files):
        rejected = [f for f in files if f.verdict in (VERDICT_REJECT, "Fehler")]
        if not rejected:
            self.rejections.setHtml(f"<p style='color:{GOOD}'>✓ Keine Datei abgelehnt.</p>")
            return
        counter = Counter()
        parts = []
        for f in rejected:
            minus = [r.text for r in f.reasons if r.kind == "minus"] or [f.error or "Geringes Verarbeitungspotenzial"]
            counter.update({f.summary or "Fehler": 1})
            parts.append(f"<p><b>{html.escape(f.path.name)}</b> "
                         f"<span style='color:{MUTED}'>({de_number(f.score)} %)</span><br>"
                         + "<br>".join(f"<span style='color:{BAD}'>✗</span> {html.escape(t)}" for t in minus) + "</p>")
        summary = "".join(f"<li>{html.escape(k)}: {v}×</li>" for k, v in counter.most_common())
        self.rejections.setHtml(f"<h3>Häufigste Gründe</h3><ul>{summary}</ul><h3>Abgelehnte Dateien</h3>" + "".join(parts))

    def _fill_recommendations(self, session, ok):
        parts = ["<h3>Session</h3><ul>"]
        parts += [f"<li>{html.escape(r)}</li>" for r in session.recommendations]
        parts.append("</ul>")
        if ok and ok[0].recommendations:
            parts.append(f"<h3>Beste Aufnahme: {html.escape(ok[0].path.name)}</h3><ul>")
            parts += [f"<li>{html.escape(r)}</li>" for r in ok[0].recommendations]
            parts.append("</ul>")
        self.recommendations.setHtml("".join(parts))

    def _on_detail_selected(self):
        rows = self.details.selectionModel().selectedRows()
        if not rows:
            return
        f = self._files[rows[0].row()]
        if f.preview is None:
            self.preview.set_frame(None)
            return
        cap = f"#{f.best_index}" if f.info and f.info.is_video else ""
        loader = self._loader_factory(f) if self._loader_factory else None
        self.preview.set_frame(f.preview, f.preview_roi, f.preview_local, cap, loader)

    def _on_detail_activated(self, row, _col):
        self.fileActivated.emit(str(self._files[row].path))

