"""Persistent user settings (QSettings: registry on Windows, plist on macOS)."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from .. import APP_NAME, ORGANIZATION

DEFAULTS = {
    "analysis/profile": "planet",
    "analysis/mode": "standard",
    "analysis/threads": max(1, (os.cpu_count() or 2) - 1),
    "analysis/recursive": True,
    "updates/check_on_start": True,
    "updates/include_prerelease": False,
    "updates/last_check": "",
    "updates/skipped_version": "",
    "ui/last_dir": "",
    "ui/geometry": None,
    "ui/state": None,
}


class Settings:
    def __init__(self, qsettings: QSettings | None = None):
        self._s = qsettings or QSettings(ORGANIZATION, APP_NAME)

    def get(self, key: str):
        default = DEFAULTS.get(key)
        value = self._s.value(key, default)
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)

    def sync(self) -> None:
        self._s.sync()
