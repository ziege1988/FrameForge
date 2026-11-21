"""Slide-in side panel that shows the live computation trace ("Rechenprotokoll")."""

from __future__ import annotations

import re

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
)

from ..core.trace import Tracer
from . import icons
from . import theme
from .theme import BAD, CARD_BORDER, GOOD, MUTED, WARN

PANEL_WIDTH = 640  # maximum; limited to 42 % of the window width
MAX_LINES = 4000  # lines kept in the view
DRAIN_MS = 80     # refresh interval
MAX_PER_TICK = 300


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    return f


class TraceHighlighter(QSyntaxHighlighter):
    """Python-like colouring: prompts, function calls, keys, numbers, comments, verdicts."""

    RULES = [
        (re.compile(r"\b[a-z_]+(?==)"), _fmt("#8fb4ff")),                       # key=
        (re.compile(r"[a-z_]+(?=\()"), _fmt("#ffb86c")),                         # function(
        (re.compile(r"\bframe\[\d+\]"), _fmt("#c3a6ff")),                        # frame[00042]
        (re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?(?:e-?\d+)?"), _fmt("#f1fa8c")),  # numbers
        (re.compile(r"'[^']*'"), _fmt("#7ee0a8")),                               # 'strings'
        (re.compile(r"\bEmpfohlen\b|✓"), _fmt(GOOD, bold=True)),
        (re.compile(r"\bBedingt geeignet\b|⚠[^·]*"), _fmt(WARN, bold=True)),
        (re.compile(r"\bAbgelehnt\b|!!!.*$|\bFehler\b"), _fmt(BAD, bold=True)),
    ]

    def highlightBlock(self, text: str):
        if text.startswith("# ") or text.startswith("# ──"):
            self.setFormat(0, len(text), _fmt("#6ea8ff", bold=True))
            return
        if text.startswith(">>>"):
            self.setFormat(0, 3, _fmt(theme.accent(), bold=True))
        for rx, fmt in self.RULES:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        idx = text.find("# ")
        if idx > 0:  # trailing comment
            self.setFormat(idx, len(text) - idx, _fmt(MUTED, italic=True))


class TracePanel(QFrame):
    """Drawer on the right side of the main window."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tracePanel")
        self.setStyleSheet(f"QFrame#tracePanel {{ background: #070b16; border-left: 1px solid {CARD_BORDER}; }}")
        self._panel_width = 0
        self.setFixedWidth(0)
        self._open = False
        self._tracer: Tracer | None = None
        self._lines_total = 0
        self._skipped_total = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("analysis", 18, theme.accent()))
        self._title_icon = ic
        head.addWidget(ic)
        title = QLabel("Rechenprotokoll")
        title.setObjectName("h2")
        head.addWidget(title)
        self.live = QLabel()
        head.addWidget(self.live)
        head.addStretch(1)
        self.follow_btn = self._tool("play", "Automatisch mitlaufen", checkable=True)
        self.follow_btn.setChecked(True)
        self.copy_btn = self._tool("report", "Protokoll kopieren")
        self.copy_btn.clicked.connect(self.copy)
        self.clear_btn = self._tool("stop", "Leeren")
        self.clear_btn.clicked.connect(self.clear)
        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Schließen")
        close.clicked.connect(self.hide_panel)
        for b in (self.follow_btn, self.copy_btn, self.clear_btn, close):
            head.addWidget(b)
        lay.addLayout(head)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(MAX_LINES)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        if mono.pointSizeF() > 0:
            mono.setPointSizeF(8.5)
        else:
            mono.setPixelSize(12)
        self.view.setFont(mono)
        self.view.setStyleSheet("QPlainTextEdit { background: #050810; color: #d7deee; border: none; }")
        self.view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.highlighter = TraceHighlighter(self.view.document())
        lay.addWidget(self.view, 1)

        self.stats = QLabel()
        self.stats.setObjectName("muted")
        lay.addWidget(self.stats)

        self._timer = QTimer(self)
        self._timer.setInterval(DRAIN_MS)
        self._timer.timeout.connect(self._drain)
        self._anim = QPropertyAnimation(self, b"panelWidth", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._set_live(False)
        theme.bus.changed.connect(self._on_theme)

    def _on_theme(self, p):
        self._title_icon.setPixmap(icons.pixmap("analysis", 18, p.accent))
        for b in (self.follow_btn, self.copy_btn, self.clear_btn):
            b.setIcon(icons.icon(b.property("iconName"), "#c9d2e6", p.accent))
        self.highlighter.rehighlight()

    def _tool(self, icon_name, tip, checkable=False) -> QToolButton:
        b = QToolButton()
        b.setIcon(icons.icon(icon_name, "#c9d2e6", theme.accent()))
        b.setProperty("iconName", icon_name)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        return b

    # ------------------------------------------------------------ open/close
    def _get_width(self) -> int:
        return self._panel_width

    def _set_width(self, w: int) -> None:
        self._panel_width = int(w)
        self.setFixedWidth(self._panel_width)

    panelWidth = Property(int, _get_width, _set_width)

    def is_open(self) -> bool:
        return self._open

    def show_panel(self):
        if self._open:
            return
        self._open = True
        self._anim.stop()
        self._anim.setStartValue(self._panel_width)
        self._anim.setEndValue(self.target_width())
        self._anim.start()

    def target_width(self) -> int:
        win = self.window().width() if self.window() else 1400
        return int(max(420, min(PANEL_WIDTH, win * 0.42)))

    def sync_width(self):
        """Adapt to a resized main window while open."""
        if self._open and self._anim.state() != QPropertyAnimation.Running:
            self._set_width(self.target_width())

    def hide_panel(self):
        if not self._open:
            return
        self._open = False
        self._anim.stop()
        self._anim.setStartValue(self._panel_width)
        self._anim.setEndValue(0)
        self._anim.start()
        self.closed.emit()

    def toggle(self):
        self.hide_panel() if self._open else self.show_panel()

    # ---------------------------------------------------------------- data
    def attach(self, tracer: Tracer):
        """Start showing a new analysis."""
        self._tracer = tracer
        self.clear()
        self._set_live(True)
        self._timer.start()

    def finish(self):
        self._drain()
        self._timer.stop()
        self._set_live(False)
        theme.bus.changed.connect(self._on_theme)

    def _on_theme(self, p):
        self._title_icon.setPixmap(icons.pixmap("analysis", 18, p.accent))
        for b in (self.follow_btn, self.copy_btn, self.clear_btn):
            b.setIcon(icons.icon(b.property("iconName"), "#c9d2e6", p.accent))
        self.highlighter.rehighlight()
        self._update_stats()

    def clear(self):
        self.view.clear()
        self._lines_total = 0
        self._skipped_total = 0
        self._update_stats()

    def copy(self):
        QApplication.clipboard().setText(self.view.toPlainText())

    def text(self) -> str:
        return self.view.toPlainText()

    def _drain(self):
        if self._tracer is None:
            return
        lines, skipped = self._tracer.drain(MAX_PER_TICK)
        if not lines and not skipped:
            return
        out = []
        if skipped:
            self._skipped_total += skipped
            out.append(f"    # … {skipped} Zeilen übersprungen (Anzeige zu schnell) …")
        out.extend(lines)
        self._lines_total += len(lines)
        bar = self.view.verticalScrollBar()
        follow = self.follow_btn.isChecked()
        cursor = QTextCursor(self.view.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(("\n" if not self.view.document().isEmpty() else "") + "\n".join(out))
        if follow:
            bar.setValue(bar.maximum())
        self._update_stats()

    def _on_scroll(self, value):
        bar = self.view.verticalScrollBar()
        # Scrolling up pauses auto-follow, scrolling to the end resumes it
        if self._timer.isActive():
            self.follow_btn.setChecked(value >= bar.maximum() - 2)

    def _update_stats(self):
        t = self._tracer.elapsed() if self._tracer else 0.0
        extra = f" · {self._skipped_total} übersprungen" if self._skipped_total else ""
        self.stats.setText(f"{self._lines_total} Zeilen · {t:.1f} s{extra}")

    def _set_live(self, on: bool):
        self.live.setText("● läuft" if on else "")
        self.live.setStyleSheet(f"color: {GOOD}; font-weight: 600;")
