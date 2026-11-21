"""Live computation trace ("Rechenprotokoll").

The analysis core writes short, code-like lines describing every step with the
real values (``>>> compute_metrics(frame[0412]) …``). The GUI drains the buffer
periodically; when no tracer is set, nothing is formatted (zero overhead).

The buffer is thread safe and bounded: if the GUI cannot keep up (thousands of
frames per second), the oldest lines are dropped and counted.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class Tracer:
    def __init__(self, maxlen: int = 20000):
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._dropped = 0
        self.t0 = time.perf_counter()

    def __call__(self, text: str) -> None:
        with self._lock:
            if len(self._lines) == self._lines.maxlen:
                self._dropped += 1
            self._lines.append(text)

    def drain(self, limit: int = 1000) -> tuple[list[str], int]:
        """Return up to ``limit`` lines (oldest first) and the number of skipped lines."""
        with self._lock:
            skipped = self._dropped
            self._dropped = 0
            if len(self._lines) > limit:
                skipped += len(self._lines) - limit
                for _ in range(len(self._lines) - limit):
                    self._lines.popleft()
            lines = list(self._lines)
            self._lines.clear()
        return lines, skipped

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0


def fmt(value, digits: int = 4) -> str:
    """Compact number formatting for trace lines."""
    if value is None:
        return "None"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v != v:  # NaN
        return "nan"
    if abs(v) >= 1000 or (abs(v) < 1e-3 and v != 0):
        return f"{v:.3e}"
    return f"{v:.{digits}f}".rstrip("0").rstrip(".") if "." in f"{v:.{digits}f}" else f"{v:.{digits}f}"
