"""Log file and crash handling.

The bundled app has no console window, so errors would otherwise disappear.
Everything is written to a rotating log file in the user's log folder:

* Windows: %LOCALAPPDATA%\\FrameForge\\logs
* macOS:   ~/Library/Logs/FrameForge
* Linux:   ~/.local/state/frameforge/logs

Nothing is sent anywhere automatically.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import traceback
import urllib.parse
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, UPDATE_REPOSITORY, __version__

log = logging.getLogger("frameforge")
_crash_callback = None


def log_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME / "logs"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "frameforge" / "logs"
    return base


def log_file() -> Path:
    return log_dir() / "frameforge.log"


def system_summary() -> str:
    return (f"{APP_NAME} {__version__} · {platform.system()} {platform.release()} ({platform.machine()}) · "
            f"Python {platform.python_version()}" + (" · installiert" if getattr(sys, "frozen", False) else ""))


def setup_logging(level: int = logging.INFO) -> Path | None:
    """Configure the log file. Returns its path (None if not writable)."""
    # Windowed (frozen) apps on Windows have no stdout/stderr → avoid crashes on print()
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    log.setLevel(level)
    path = None
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        path = log_file()
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
            log.addHandler(handler)
    except OSError:
        path = None
    log.info("Start: %s", system_summary())
    return path


def install_excepthooks(callback=None) -> None:
    """Log uncaught exceptions (main and worker threads) and notify ``callback(text)``."""
    global _crash_callback
    _crash_callback = callback

    def handle(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.critical("Unbehandelter Fehler:\n%s", text)
        if _crash_callback:
            try:
                _crash_callback(text)
            except Exception:  # pragma: no cover - never fail in the handler
                pass

    sys.excepthook = handle
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback)


def issue_url(error_text: str = "") -> str:
    """Pre-filled GitHub issue (the user reviews it in the browser before sending)."""
    body = (f"**Version / System:** {system_summary()}\n\n"
            "**Was wurde gemacht?**\n\n\n**Was ist passiert / was wurde erwartet?**\n\n\n"
            "**Dateiformat (z. B. SER 16 bit, FITS, CR3):**\n\n")
    if error_text:
        body += "**Fehlermeldung:**\n```\n" + error_text[-3000:] + "\n```\n"
    query = urllib.parse.urlencode({"title": "Fehler: ", "body": body, "labels": "bug"})
    return f"https://github.com/{UPDATE_REPOSITORY}/issues/new?{query}"
