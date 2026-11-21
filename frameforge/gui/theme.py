"""Colour themes.

The interface uses one palette at a time. Palettes are derived from a single
hue (e.g. the dominant colour of a nebula background), so that buttons,
navigation, tabs, cards and menus match the chosen background. Semantic colours
(good / warning / bad) never change.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette

GOOD = "#3ccf72"
WARN = "#f0b429"
BAD = "#ef4b4b"
TEXT = "#e8ecf6"


def _hsv(h: float, s: float, v: float, a: int | None = None) -> str:
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, max(0.0, min(s, 1.0)), max(0.0, min(v, 1.0)))
    r, g, b = int(r * 255), int(g * 255), int(b * 255)
    return f"rgba({r}, {g}, {b}, {a})" if a is not None else f"#{r:02x}{g:02x}{b:02x}"


def _luminance(hex_color: str) -> float:
    c = QColor(hex_color)
    def lin(x):
        x /= 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


@dataclass(frozen=True)
class Palette:
    name: str
    hue: float
    accent: str
    accent_hover: str
    accent_light: str  # accent for text on dark backgrounds
    on_accent: str  # text colour on accent buttons
    bg: str
    sidebar: str
    card: str
    card_border: str
    input: str
    alt_row: str
    selection: str
    hover: str
    button: str
    button_border: str
    muted: str

    @classmethod
    def from_hue(cls, hue: float, name: str = "", vivid: float = 0.72) -> "Palette":
        accent = _hsv(hue, vivid, 0.96)
        return cls(
            name=name,
            hue=hue,
            accent=accent,
            accent_hover=_hsv(hue, vivid * 0.78, 1.0),
            accent_light=_hsv(hue, 0.42, 1.0),
            on_accent="#16100a" if _luminance(accent) > 0.32 else "#ffffff",
            bg=_hsv(hue, 0.55, 0.065),
            sidebar=_hsv(hue, 0.50, 0.08, 205),
            card=_hsv(hue, 0.45, 0.11, 200),
            card_border=_hsv(hue, 0.40, 0.42, 105),
            input=_hsv(hue, 0.50, 0.075),
            alt_row=_hsv(hue, 0.45, 0.105),
            selection=_hsv(hue, 0.60, 0.38),
            hover=_hsv(hue, 0.45, 0.22),
            button=_hsv(hue, 0.40, 0.17),
            button_border=_hsv(hue, 0.35, 0.32),
            muted=_hsv(hue, 0.13, 0.70),
        )


def _default_palette() -> Palette:
    p = Palette.from_hue(217, "Blau")
    # keep the original FrameForge blue exactly
    return Palette(**{**p.__dict__, "accent": "#3d8bff", "accent_hover": "#5a9dff", "accent_light": "#8fbaff",
                      "on_accent": "#ffffff"})


DEFAULT_PALETTE = _default_palette()
_current: Palette = DEFAULT_PALETTE

# Backwards compatible names (values of the default palette; use the functions
# below for colours that must follow the active theme)
ACCENT = DEFAULT_PALETTE.accent
MUTED = "#8a94ad"
BG = DEFAULT_PALETTE.bg
CARD_BORDER = "#1e2a46"


class _ThemeBus(QObject):
    changed = Signal(object)  # Palette


bus = _ThemeBus()


def current() -> Palette:
    return _current


def accent() -> str:
    return _current.accent


def build_stylesheet(p: Palette) -> str:
    return f"""
QWidget {{ font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {p.bg}; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget, QSplitter, QTabWidget > QStackedWidget {{ background: transparent; }}
QMenuBar {{ background: {p.sidebar}; color: {TEXT}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {p.hover}; }}
QMenu {{ background: {p.input}; border: 1px solid {p.card_border}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {p.selection}; }}
QMenu::separator {{ height: 1px; background: {p.card_border}; margin: 4px 8px; }}
QFrame#sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.card_border}; }}
QToolButton#nav {{ text-align: left; padding: 9px 12px; border-radius: 7px; color: #d5dbe8; background: transparent; border: none; }}
QToolButton#nav:hover {{ background: {p.hover}; }}
QToolButton#nav:checked {{ background: {p.accent}; color: {p.on_accent}; font-weight: 600; }}
QFrame#card {{ background: {p.card}; border: 1px solid {p.card_border}; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#option {{ background: {p.card}; border: 1px solid {p.card_border}; border-radius: 8px; }}
QFrame#option:hover {{ border-color: {p.accent}; background: {p.hover}; }}
QFrame#optionPrimary {{ background: {p.selection}; border: 1px solid {p.accent}; border-radius: 8px; }}
QFrame#optionPrimary:hover {{ background: {p.hover}; }}
QLabel#optTitle {{ color: {p.accent_light}; font-size: 14px; background: transparent; }}
QToolButton {{ padding: 5px 9px; border-radius: 6px; color: {TEXT}; }}
QToolButton:hover {{ background: {p.hover}; }}
QToolButton:disabled {{ color: #4c5670; }}
QToolButton#chip {{ border: 1px solid {p.card_border}; border-radius: 8px; padding: 8px 12px; background: {p.card}; }}
QToolButton#chip:checked {{ border: 1px solid {p.accent}; background: {p.selection}; color: #ffffff; }}
QToolButton#bgTile {{ border: 2px solid transparent; border-radius: 9px; padding: 4px; background: {p.card}; }}
QToolButton#bgTile:hover {{ border-color: {p.card_border}; }}
QToolButton#bgTile:checked {{ border-color: {p.accent}; background: {p.selection}; }}
QPushButton {{ background: {p.button}; color: {TEXT}; border: 1px solid {p.button_border}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: {p.hover}; }}
QPushButton:disabled {{ color: #5a6275; border-color: {p.card_border}; }}
QPushButton#primary {{ background: {p.accent}; color: {p.on_accent}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {p.accent_hover}; }}
QPushButton#primary:disabled {{ background: {p.selection}; color: #8a8f9d; }}
QTableView, QTreeView, QListWidget, QTextBrowser, QPlainTextEdit {{
    background: {p.input}; alternate-background-color: {p.alt_row}; color: {TEXT};
    border: 1px solid {p.card_border}; border-radius: 6px; gridline-color: {p.alt_row};
    selection-background-color: {p.selection}; selection-color: #ffffff;
}}
QFrame#card QTableView, QFrame#card QTextBrowser {{ border: none; background: transparent; alternate-background-color: {p.alt_row}; }}
QHeaderView::section {{ background: transparent; color: {p.muted}; border: none; border-bottom: 1px solid {p.card_border}; padding: 6px; font-weight: 600; }}
QTabWidget::pane {{ border: none; top: 0px; }}
QTabBar::tab {{ background: transparent; color: {p.muted}; padding: 9px 16px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: #ffffff; border-bottom: 2px solid {p.accent}; background: {p.hover}; }}
QTabBar::tab:hover {{ color: #ffffff; }}
QComboBox, QSpinBox, QLineEdit {{ background: {p.input}; color: {TEXT}; border: 1px solid {p.button_border}; border-radius: 6px; padding: 4px 8px; }}
QComboBox QAbstractItemView {{ background: {p.input}; border: 1px solid {p.card_border}; selection-background-color: {p.selection}; }}
QProgressBar {{ background: {p.input}; border: 1px solid {p.card_border}; border-radius: 5px; text-align: center; color: {TEXT}; height: 14px; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.button_border}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.accent}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QGroupBox {{ border: 1px solid {p.card_border}; border-radius: 8px; margin-top: 14px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p.muted}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {p.button_border}; border-radius: 3px; background: {p.input}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
QLabel#muted {{ color: {p.muted}; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; color: #ffffff; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; color: #ffffff; }}
QLabel#big {{ font-size: 34px; font-weight: 700; color: #ffffff; }}
QLabel#badge {{ border-radius: 4px; padding: 2px 8px; font-weight: 600; }}
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: {p.sidebar}; color: {p.muted}; border-top: 1px solid {p.card_border}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p.button_border}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {p.button_border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {p.input}; color: {TEXT}; border: 1px solid {p.card_border}; padding: 4px; }}
"""


def apply_theme(app, palette: Palette | None = None) -> None:
    global _current, ACCENT
    p = palette or _current
    _current = p
    ACCENT = p.accent
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.Window, p.bg), (QPalette.WindowText, TEXT), (QPalette.Base, p.input),
        (QPalette.AlternateBase, p.alt_row), (QPalette.Text, TEXT), (QPalette.Button, p.button),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, p.selection), (QPalette.HighlightedText, "#ffffff"),
        (QPalette.ToolTipBase, p.input), (QPalette.ToolTipText, TEXT), (QPalette.Link, p.accent_light),
        (QPalette.PlaceholderText, "#4c5670"),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet(p))
    bus.changed.emit(p)


def verdict_color(verdict: str) -> str:
    return {"Empfohlen": GOOD, "Bedingt geeignet": WARN, "Abgelehnt": BAD, "Fehler": BAD}.get(verdict, MUTED)


def verdict_bg(verdict: str) -> str:
    return {"Empfohlen": "#123d27", "Bedingt geeignet": "#3d3012", "Abgelehnt": "#4a1717", "Fehler": "#4a1717"}.get(
        verdict, "#1e2a46")


def score_color(score: float) -> str:
    return GOOD if score >= 65 else WARN if score >= 45 else BAD


def de_number(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")
