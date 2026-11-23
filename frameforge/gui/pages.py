"""Reports ("Berichte") and info pages."""

from __future__ import annotations

import html
import platform
import sys

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_SUBTITLE, UPDATE_REPOSITORY, __version__
from ..core.analyzer import MODE_LABELS
from ..core.profiles import PROFILES
from . import icons
from .components import Card, format_duration
from .dashboard import ThemedLabel, slogan_label, wordmark
from .resources import license_path, logo_pixmap
from .theme import GOOD, MUTED, score_color, verdict_color


def _scroll(content: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.NoFrame)
    sa.setWidget(content)
    return sa


class ReportsPage(QWidget):
    exportCsv = Signal()
    exportJson = Signal()
    saveProject = Signal()
    openProject = Signal()
    openFrameSelection = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer.addWidget(_scroll(content))
        lay = QVBoxLayout(content)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        t = QLabel("Berichte")
        t.setObjectName("h1")
        lay.addWidget(t)
        grid = QGridLayout()
        grid.setSpacing(16)

        rep = Card("Bericht exportieren", "export")
        d = QLabel("Rangliste mit Scores, Teilbewertungen, Begründungen und Empfehlungen.<br>"
                   "<b>CSV</b>: öffnet direkt in Excel/Numbers. <b>JSON</b>: inkl. Werte aller Frames.")
        d.setWordWrap(True)
        d.setObjectName("muted")
        rep.body.addWidget(d)
        row = QHBoxLayout()
        self.csv_btn = QPushButton("Als CSV …")
        self.csv_btn.setObjectName("primary")
        self.csv_btn.clicked.connect(self.exportCsv.emit)
        self.json_btn = QPushButton("Als JSON …")
        self.json_btn.clicked.connect(self.exportJson.emit)
        row.addWidget(self.csv_btn)
        row.addWidget(self.json_btn)
        row.addStretch(1)
        rep.body.addLayout(row)
        grid.addWidget(rep, 0, 0)

        proj = Card("Projekt", "save")
        d = QLabel("Speichert die komplette Analyse (inkl. Vorschauen und Frame-Werte) als <i>.ffproj</i>-Datei, "
                   "um sie später ohne erneute Analyse wieder zu öffnen.")
        d.setWordWrap(True)
        d.setObjectName("muted")
        proj.body.addWidget(d)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Projekt speichern …")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.saveProject.emit)
        open_btn = QPushButton("Projekt öffnen …")
        open_btn.clicked.connect(self.openProject.emit)
        row.addWidget(self.save_btn)
        row.addWidget(open_btn)
        row.addStretch(1)
        proj.body.addLayout(row)
        grid.addWidget(proj, 0, 1)

        frames = Card("Beste Frames exportieren", "play")
        d = QLabel("Die besten Frames eines Videos werden als neue SER-Datei (Originaldaten) gespeichert – "
                   "direkt weiterverarbeitbar in AutoStakkert!, Siril, PIPP oder PSS.")
        d.setWordWrap(True)
        d.setObjectName("muted")
        frames.body.addWidget(d)
        self.frames_btn = QPushButton("Zur Frame-Selektion")
        self.frames_btn.clicked.connect(self.openFrameSelection.emit)
        row = QHBoxLayout()
        row.addWidget(self.frames_btn)
        row.addStretch(1)
        frames.body.addLayout(row)
        grid.addWidget(frames, 1, 0)

        self.last_label = QLabel("Noch kein Export in dieser Sitzung.")
        self.last_label.setObjectName("muted")
        self.last_label.setWordWrap(True)
        last = Card("Zuletzt gespeichert", "report")
        last.body.addWidget(self.last_label)
        grid.addWidget(last, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        summary = Card("Session-Zusammenfassung", "analysis")
        self.summary = QTextBrowser()
        self.summary.setMinimumHeight(260)
        summary.body.addWidget(self.summary)
        lay.addWidget(summary, 1)
        self.set_session(None)

    def set_session(self, s):
        for b in (self.csv_btn, self.json_btn, self.save_btn):
            b.setEnabled(s is not None)
        if s is None:
            self.summary.setHtml(f"<p style='color:{MUTED}'>Noch keine Analyse durchgeführt.</p>")
            return
        ok = [f for f in s.files if f.error is None]
        prof = PROFILES.get(s.profile)
        parts = [f"<p>Profil: <b>{prof.name if prof else s.profile}</b> · Modus: {MODE_LABELS.get(s.mode, s.mode)} · "
                 f"{len(s.files)} Dateien · Analysezeit {format_duration(s.elapsed_s)}</p><ul>"]
        parts += [f"<li>{html.escape(r)}</li>" for r in s.recommendations]
        parts.append("</ul>")
        if ok:
            parts.append("<table cellspacing='6'><tr><th align='left'>Rang</th><th align='left'>Datei</th>"
                         "<th align='right'>Score</th><th align='left'>Urteil</th><th align='left'>Begründung</th></tr>")
            for f in s.ranked():
                if f.error:
                    continue
                parts.append(f"<tr><td>{f.rank}.</td><td>{html.escape(f.path.name)}</td>"
                             f"<td align='right' style='color:{score_color(f.score)}'>{f.score:.1f}</td>"
                             f"<td style='color:{verdict_color(f.verdict)}'>{f.verdict}</td>"
                             f"<td>{html.escape(f.summary)}</td></tr>")
            parts.append("</table>")
        errors = [f for f in s.files if f.error]
        if errors:
            parts.append("<h3>Nicht auswertbar</h3><ul>")
            parts += [f"<li>{html.escape(f.path.name)}: {html.escape(f.error)}</li>" for f in errors]
            parts.append("</ul>")
        self.summary.setHtml("".join(parts))

    def set_last_saved(self, text: str):
        self.last_label.setText(text)


class InfoPage(QWidget):
    checkUpdates = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer.addWidget(_scroll(content))
        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(18)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(150, self.devicePixelRatioF()))
        head.addWidget(logo)
        head.addSpacing(20)
        col = QVBoxLayout()
        col.addStretch(1)
        col.addWidget(wordmark(40))
        col.addWidget(slogan_label())
        v = QLabel(f"{APP_SUBTITLE} · Version {__version__}")
        v.setObjectName("muted")
        col.addWidget(v)
        btn = QPushButton("Nach Updates suchen")
        btn.clicked.connect(self.checkUpdates.emit)
        r = QHBoxLayout()
        r.addWidget(btn)
        r.addStretch(1)
        col.addLayout(r)
        col.addStretch(1)
        head.addLayout(col, 1)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(16)
        desc = Card("Kurzbeschreibung")
        t = QLabel(f"<b>{APP_NAME}</b> ist dein zuverlässiger Analyse-Assistent für die Qualitätsprüfung von "
                   "Astrofotos und -Videos. Die Software prüft deine Aufnahmen automatisch auf Schärfe, Rauschen, "
                   "Belichtung und weitere Qualitätsmerkmale und empfiehlt dir die besten Ergebnisse – inklusive "
                   "klarer Begründungen.")
        t.setWordWrap(True)
        desc.body.addWidget(t)
        hl = ThemedLabel("<span style='font-size:15px; font-weight:600; color:{accent}'>Highlights im Detail</span>")
        desc.body.addWidget(hl)
        for text in (
            "Automatische Analyse – erkennt die besten Bilder und Videos",
            "Transparente Begründung – warum etwas empfohlen oder abgelehnt wurde",
            "Unterstützung für gängige Formate: SER, AVI, MP4, FITS, TIFF, RAW, PNG, JPEG",
            "Profile für Sonne, Mond, Planeten und Deep-Sky",
            "Frame-Selektion mit Export der besten Frames als SER",
            "Übersichtliche Ergebnisse mit Vorschau und Qualitäts-Score",
            "Schnelle, speicherschonende Verarbeitung großer Datenmengen",
        ):
            row = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icons.pixmap("check", 18, GOOD))
            row.addWidget(ic)
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            desc.body.addLayout(row)
        grid.addWidget(desc, 0, 0)

        tech = Card("Technische Details")
        os_name = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, platform.system())
        for icon_name, text in (
            ("general", "Windows 10/11 (64-Bit) und macOS 11 oder neuer (Apple Silicon & Intel)"),
            ("analysis", "Optimiert für Rohdaten (SER, FITS, RAW) – Bayer-Daten ohne Interpolation"),
            ("settings", "Effiziente Mehrkern-Analyse, Frames werden einzeln gelesen"),
            ("check", "Skalierbar – von einzelnen Fotos bis zu Tausenden Frames"),
            ("info", "Lokale Verarbeitung – kein Cloud-Upload"),
        ):
            row = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, 24, "#c9d2e6"))
            ic.setAlignment(Qt.AlignTop)
            row.addWidget(ic)
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            tech.body.addLayout(row)
        sysinfo = QLabel(f"Dieses System: {os_name} {platform.release()} · {platform.machine()} · "
                         f"Python {platform.python_version()}")
        sysinfo.setObjectName("muted")
        sysinfo.setWordWrap(True)
        tech.body.addWidget(sysinfo)
        grid.addWidget(tech, 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        lay.addLayout(grid)

        own = Card("Lizenz")
        t = QLabel(f"{APP_NAME} ist freie Software unter der <b>GNU General Public License, Version 3 oder neuer</b> "
                   "(GPL-3.0-or-later). Du darfst das Programm kostenlos nutzen, weitergeben und verändern – "
                   "veränderte Versionen müssen ebenfalls unter der GPL mit Quellcode weitergegeben werden. "
                   "Es gibt keine Gewährleistung.<br>"
                   "Die mitgelieferten Hintergrundfotos sind davon ausgenommen: © Inhaber des Repositorys, "
                   f"Nutzung nur zusammen mit {APP_NAME}.")
        t.setWordWrap(True)
        own.body.addWidget(t)
        row = QHBoxLayout()
        show = QPushButton("Lizenztext anzeigen")
        show.clicked.connect(self._show_license)
        src = QPushButton("Quellcode auf GitHub")
        src.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{UPDATE_REPOSITORY}")))
        row.addWidget(show)
        row.addWidget(src)
        row.addStretch(1)
        own.body.addLayout(row)
        lay.addWidget(own)

        lic = Card("Verwendete Open-Source-Bibliotheken")
        t = QLabel("NumPy (BSD) · OpenCV (Apache 2.0) · Qt/PySide6 (LGPLv3) · tifffile & imagecodecs (BSD) · "
                   "rawpy (MIT) mit LibRaw (LGPL 2.1/CDDL) · certifi (MPL 2.0). Vielen Dank an alle Entwicklerinnen "
                   "und Entwickler dieser Projekte.")
        t.setWordWrap(True)
        t.setObjectName("muted")
        lic.body.addWidget(t)
        lay.addWidget(lic)
        foot = ThemedLabel(f"<i><b style='color:{{accent}}'>{APP_NAME}</b> – mehr aus deinen Daten herausholen.</i>")
        foot.setAlignment(Qt.AlignRight)
        lay.addWidget(foot)
        lay.addStretch(1)

    def _show_license(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Lizenz – GNU GPL v3")
        dlg.resize(720, 640)
        v = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        try:
            view.setPlainText(license_path().read_text(encoding="utf-8"))
        except OSError:
            view.setPlainText("Lizenztext nicht gefunden: https://www.gnu.org/licenses/gpl-3.0.txt")
        v.addWidget(view)
        close = QPushButton("Schließen")
        close.clicked.connect(dlg.accept)
        v.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()
