"""Dark theme – easier on night-adapted eyes at the telescope."""

from PySide6.QtGui import QColor, QPalette

ACCENT = "#ff9a3c"
GOOD = "#4cc38a"
WARN = "#e8b339"
BAD = "#e5534b"
MUTED = "#8b93a7"

STYLESHEET = f"""
QWidget {{ font-size: 13px; }}
QMainWindow, QDialog {{ background: #11151f; }}
QToolBar {{ background: #161b28; border: none; padding: 4px; spacing: 6px; }}
QToolButton {{ padding: 5px 9px; border-radius: 6px; color: #e6e9f2; }}
QToolButton:hover {{ background: #232a3d; }}
QToolButton:disabled {{ color: #5b6275; }}
QPushButton {{ background: #232a3d; color: #e6e9f2; border: 1px solid #2f3850; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: #2c3550; }}
QPushButton:disabled {{ color: #5b6275; }}
QPushButton#primary {{ background: {ACCENT}; color: #1a1206; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #ffae5f; }}
QPushButton#primary:disabled {{ background: #5a4330; color: #a08a74; }}
QTableView, QTreeView, QListWidget, QTextBrowser, QPlainTextEdit {{
    background: #0d1018; alternate-background-color: #131826; color: #e6e9f2;
    border: 1px solid #232a3d; border-radius: 6px; gridline-color: #1d2333;
    selection-background-color: #3a2c1c; selection-color: #ffffff;
}}
QHeaderView::section {{ background: #161b28; color: {MUTED}; border: none; border-bottom: 1px solid #232a3d; padding: 5px; }}
QTabWidget::pane {{ border: 1px solid #232a3d; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: #ffffff; border-bottom: 2px solid {ACCENT}; }}
QComboBox, QSpinBox, QLineEdit {{ background: #0d1018; color: #e6e9f2; border: 1px solid #2f3850; border-radius: 5px; padding: 4px 6px; }}
QProgressBar {{ background: #0d1018; border: 1px solid #232a3d; border-radius: 5px; text-align: center; color: #e6e9f2; height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QGroupBox {{ border: 1px solid #232a3d; border-radius: 6px; margin-top: 14px; padding-top: 8px; color: #e6e9f2; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#h1 {{ font-size: 18px; font-weight: 600; color: #ffffff; }}
QLabel#badge {{ border-radius: 4px; padding: 2px 8px; font-weight: 600; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #4a5470; border-radius: 3px; background: #0d1018; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QSplitter::handle {{ background: #161b28; }}
QStatusBar {{ background: #161b28; color: {MUTED}; }}
"""


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.Window, "#11151f"), (QPalette.WindowText, "#e6e9f2"), (QPalette.Base, "#0d1018"),
        (QPalette.AlternateBase, "#131826"), (QPalette.Text, "#e6e9f2"), (QPalette.Button, "#232a3d"),
        (QPalette.ButtonText, "#e6e9f2"), (QPalette.Highlight, "#3a2c1c"), (QPalette.HighlightedText, "#ffffff"),
        (QPalette.ToolTipBase, "#232a3d"), (QPalette.ToolTipText, "#e6e9f2"), (QPalette.Link, ACCENT),
        (QPalette.PlaceholderText, "#5b6275"),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


def verdict_color(verdict: str) -> str:
    return {"Empfohlen": GOOD, "Bedingt geeignet": WARN, "Nicht empfohlen": BAD, "Fehler": BAD}.get(verdict, MUTED)


def score_color(score: float) -> str:
    return GOOD if score >= 65 else WARN if score >= 45 else BAD
