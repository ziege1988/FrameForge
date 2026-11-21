"""Dark blue theme (easier on night-adapted eyes at the telescope)."""

from PySide6.QtGui import QColor, QPalette

ACCENT = "#3d8bff"
ACCENT_HOVER = "#5a9dff"
GOOD = "#3ccf72"
WARN = "#f0b429"
BAD = "#ef4b4b"
MUTED = "#8a94ad"
TEXT = "#e8ecf6"
BG = "#0a0f1d"
SIDEBAR = "#0d1428"
CARD = "#111a2e"
CARD_BORDER = "#1e2a46"
INPUT = "#0c1324"

STYLESHEET = f"""
QWidget {{ font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QMenuBar {{ background: {BG}; color: {TEXT}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: #1a2540; }}
QMenu {{ background: {CARD}; border: 1px solid {CARD_BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: #1c2b4d; }}
QMenu::separator {{ height: 1px; background: {CARD_BORDER}; margin: 4px 8px; }}
QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {CARD_BORDER}; }}
QToolButton#nav {{ text-align: left; padding: 9px 12px; border-radius: 7px; color: #c9d2e6; background: transparent; border: none; }}
QToolButton#nav:hover {{ background: #16213b; }}
QToolButton#nav:checked {{ background: {ACCENT}; color: #ffffff; font-weight: 600; }}
QFrame#card {{ background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#option {{ background: #101a33; border: 1px solid #24345a; border-radius: 8px; }}
QFrame#option:hover {{ border-color: {ACCENT}; background: #132143; }}
QFrame#optionPrimary {{ background: #12306a; border: 1px solid {ACCENT}; border-radius: 8px; }}
QFrame#optionPrimary:hover {{ background: #173a80; }}
QToolButton {{ padding: 5px 9px; border-radius: 6px; color: {TEXT}; }}
QToolButton:hover {{ background: #1a2540; }}
QToolButton:disabled {{ color: #4c5670; }}
QToolButton#chip {{ border: 1px solid {CARD_BORDER}; border-radius: 8px; padding: 8px 12px; background: {CARD}; }}
QToolButton#chip:checked {{ border: 1px solid {ACCENT}; background: #132143; color: #ffffff; }}
QPushButton {{ background: #18233d; color: {TEXT}; border: 1px solid #2a3858; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: #1f2d4e; }}
QPushButton:disabled {{ color: #4c5670; border-color: #1e2a46; }}
QPushButton#primary {{ background: {ACCENT}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #1d3566; color: #7d8db0; }}
QTableView, QTreeView, QListWidget, QTextBrowser, QPlainTextEdit {{
    background: {INPUT}; alternate-background-color: #0f182c; color: {TEXT};
    border: 1px solid {CARD_BORDER}; border-radius: 6px; gridline-color: #18223a;
    selection-background-color: #1c3466; selection-color: #ffffff;
}}
QFrame#card QTableView, QFrame#card QTextBrowser {{ border: none; background: transparent; alternate-background-color: #0f182c; }}
QHeaderView::section {{ background: transparent; color: {MUTED}; border: none; border-bottom: 1px solid {CARD_BORDER}; padding: 6px; font-weight: 600; }}
QTabWidget::pane {{ border: none; top: 0px; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 9px 16px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: #ffffff; border-bottom: 2px solid {ACCENT}; background: #15213d; }}
QTabBar::tab:hover {{ color: #ffffff; }}
QComboBox, QSpinBox, QLineEdit {{ background: {INPUT}; color: {TEXT}; border: 1px solid #2a3858; border-radius: 6px; padding: 4px 8px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {CARD_BORDER}; selection-background-color: #1c3466; }}
QProgressBar {{ background: {INPUT}; border: 1px solid {CARD_BORDER}; border-radius: 5px; text-align: center; color: {TEXT}; height: 14px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QGroupBox {{ border: 1px solid {CARD_BORDER}; border-radius: 8px; margin-top: 14px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #4a5878; border-radius: 3px; background: {INPUT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; color: #ffffff; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; color: #ffffff; }}
QLabel#big {{ font-size: 34px; font-weight: 700; color: #ffffff; }}
QLabel#badge {{ border-radius: 4px; padding: 2px 8px; font-weight: 600; }}
QSplitter::handle {{ background: {BG}; }}
QStatusBar {{ background: {SIDEBAR}; color: {MUTED}; border-top: 1px solid {CARD_BORDER}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #26324f; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #26324f; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {CARD_BORDER}; padding: 4px; }}
"""


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, INPUT),
        (QPalette.AlternateBase, "#0f182c"), (QPalette.Text, TEXT), (QPalette.Button, "#18233d"),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, "#1c3466"), (QPalette.HighlightedText, "#ffffff"),
        (QPalette.ToolTipBase, CARD), (QPalette.ToolTipText, TEXT), (QPalette.Link, ACCENT),
        (QPalette.PlaceholderText, "#4c5670"),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


def verdict_color(verdict: str) -> str:
    return {"Empfohlen": GOOD, "Bedingt geeignet": WARN, "Abgelehnt": BAD, "Fehler": BAD}.get(verdict, MUTED)


def verdict_bg(verdict: str) -> str:
    return {"Empfohlen": "#123d27", "Bedingt geeignet": "#3d3012", "Abgelehnt": "#4a1717", "Fehler": "#4a1717"}.get(
        verdict, "#1e2a46")


def score_color(score: float) -> str:
    return GOOD if score >= 65 else WARN if score >= 45 else BAD


def de_number(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")
