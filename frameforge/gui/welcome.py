"""Start popup: quick start with analysis options (shown after the splash screen)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from .. import APP_NAME
from ..core.profiles import PROFILES
from . import icons
from .components import OptionButton
from .resources import app_icon, logo_pixmap
from .settings import Settings
from .theme import ACCENT

PROFILE_ORDER = ["sun", "moon", "planet", "deepsky", "general"]


def profile_chips(current: str, parent=None) -> tuple[QHBoxLayout, QButtonGroup]:
    """Row of checkable profile buttons (icon + name)."""
    row = QHBoxLayout()
    row.setSpacing(8)
    group = QButtonGroup(parent)
    group.setExclusive(True)
    for key in PROFILE_ORDER:
        prof = PROFILES[key]
        b = QToolButton()
        b.setObjectName("chip")
        b.setCheckable(True)
        b.setText(prof.name)
        b.setIcon(icons.icon(icons.PROFILE_ICONS[key], "#c9d2e6", ACCENT, size=26))
        b.setIconSize(b.iconSize() * 1.4)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setToolTip(prof.description)
        b.setMinimumWidth(78)
        b.setProperty("profile", key)
        b.setChecked(key == current)
        group.addButton(b)
        row.addWidget(b)
    row.addStretch(1)
    return row, group


class WelcomeDialog(QDialog):
    """Returns the chosen action in ``self.choice`` ("folder", "video", "project" or None)."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.choice: str | None = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setMinimumWidth(720)

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 18)
        root.setSpacing(26)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(190, self.devicePixelRatioF()))
        logo.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        root.addWidget(logo)

        col = QVBoxLayout()
        col.setSpacing(10)
        title = QLabel(f"Willkommen bei {APP_NAME}!")
        title.setObjectName("h1")
        sub = QLabel("Wähle das Aufnahmeobjekt und eine Analyse-Option oder öffne ein Projekt.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        col.addWidget(title)
        col.addWidget(sub)
        chips, self.profile_group = profile_chips(settings.get("analysis/profile"), self)
        col.addSpacing(4)
        col.addLayout(chips)
        col.addSpacing(6)
        for key, icon_name, text, subtitle, primary in (
            ("folder", "folder", "Ordner analysieren", "Fotos & Videos (z. B. SER, RAW, FITS)", True),
            ("video", "play", "Video analysieren", "z. B. SER, AVI, MP4", False),
            ("project", "folder-open", "Projekt öffnen", "Gespeichertes Projekt laden", False),
        ):
            btn = OptionButton(icon_name, text, subtitle, primary)
            btn.clicked.connect(lambda k=key: self._choose(k))
            col.addWidget(btn)
        col.addStretch(1)
        bottom = QHBoxLayout()
        self.dont_show = QCheckBox("Nicht mehr anzeigen")
        self.dont_show.setChecked(not settings.get("ui/show_welcome"))
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(self.dont_show)
        bottom.addStretch(1)
        bottom.addWidget(cancel)
        col.addLayout(bottom)
        root.addLayout(col, 1)

    def paintEvent(self, event):
        if self.settings.get("ui/starfield"):
            from PySide6.QtGui import QPainter

            from .starfield import render_starfield

            if getattr(self, "_sky", None) is None or self._sky.deviceIndependentSize().toSize() != self.size():
                self._sky = render_starfield(self.width(), self.height(), self.devicePixelRatioF(), density=1.6)
            QPainter(self).drawPixmap(0, 0, self._sky)
        else:
            super().paintEvent(event)

    def selected_profile(self) -> str:
        b = self.profile_group.checkedButton()
        return b.property("profile") if b else self.settings.get("analysis/profile")

    def _choose(self, key: str):
        self.choice = key
        self.accept()

    def done(self, result):
        self.settings.set("ui/show_welcome", not self.dont_show.isChecked())
        self.settings.set("analysis/profile", self.selected_profile())
        self.settings.sync()
        super().done(result)
