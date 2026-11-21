"""Export of reports (CSV/JSON) and of selected frames (SER)."""

from __future__ import annotations

import csv
import json
import os
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from .analyzer import AnalysisOptions, FileResult, SessionResult, analyze_file
from .io import open_source
from .scoring import COMPONENT_LABELS

CSV_COLUMNS = [
    ("rank", "Rang"), ("name", "Datei"), ("format", "Format"), ("frames", "Frames"),
    ("score", "Score"), ("verdict", "Urteil"), ("potential", "Verarbeitungspotenzial"),
] + [(k, COMPONENT_LABELS[k]) for k in COMPONENT_LABELS] + [
    ("recommended_frames", "Empfohlene Frames"), ("peak", "Belichtung Spitze"),
    ("clip_high", "Überbelichtet"), ("snr", "SNR"), ("jitter_px", "Bildbewegung px"),
    ("reasons", "Begründung"), ("recommendations", "Empfehlungen"), ("path", "Pfad"),
]


def export_json(session: SessionResult, destination: str | os.PathLike, include_frames: bool = False) -> Path:
    dest = Path(destination)
    dest.write_text(json.dumps(session.to_dict(include_frames), ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def export_csv(session: SessionResult, destination: str | os.PathLike) -> Path:
    """CSV with ';' separator and UTF-8 BOM so that Excel (DE) opens it directly."""
    dest = Path(destination)
    with open(dest, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow([label for _, label in CSV_COLUMNS])
        for f in session.ranked():
            agg = f.aggregate or {}
            row = {
                "rank": f.rank or "", "name": f.path.name, "format": f.info.format if f.info else "",
                "frames": f.info.frame_count if f.info else "", "score": _de(f.score),
                "verdict": f.verdict, "potential": f.potential,
                "recommended_frames": agg.get("recommended_frames", ""),
                "peak": _de(agg.get("peak")), "clip_high": _de(agg.get("clip_high"), 4),
                "snr": _de(agg.get("snr")), "jitter_px": _de(agg.get("jitter_px")),
                "reasons": " | ".join(r.text for r in f.reasons),
                "recommendations": " | ".join(f.recommendations), "path": str(f.path),
            }
            for k in COMPONENT_LABELS:
                row[k] = _de(f.components.get(k))
            writer.writerow([row[key] for key, _ in CSV_COLUMNS])
    return dest


def export_frame_list(result: FileResult, destination: str | os.PathLike, fraction: float | None = None) -> Path:
    dest = Path(destination)
    selected = set(result.best_frame_indices(fraction).tolist())
    with open(dest, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Frame", "Qualität", "Ausgewählt", "Zeit s"])
        for n, idx in enumerate(result.indices):
            t = "" if result.times is None else _de(result.times[n], 3)
            writer.writerow([int(idx), _de(result.quality[n]), "ja" if int(idx) in selected else "nein", t])
    return dest


def _de(value, digits: int = 2) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(v):
        return ""
    return f"{v:.{digits}f}".replace(".", ",")


def export_best_frames(result: FileResult, destination: str | os.PathLike, fraction: float | None = None,
                       options: AnalysisOptions | None = None,
                       progress: Callable[[str, float], None] | None = None,
                       cancel: threading.Event | None = None) -> tuple[Path, int]:
    """Write the best frames of a video into a new SER file.

    If the original analysis was only a sample, all frames are analysed first
    so that the selection is exact.
    """
    if result.info is None or not result.info.is_video:
        raise ValueError("Frame-Export ist nur für Videos bzw. Frame-Folgen möglich.")
    source_result = result
    if result.sampled:
        opts = AnalysisOptions(profile=result.profile, mode="vollstaendig",
                               threads=(options.threads if options else AnalysisOptions().threads))
        source_result = analyze_file(result.path, opts,
                                     (lambda f: progress("Vollanalyse aller Frames …", 0.8 * f)) if progress else None,
                                     cancel)
        if source_result.error:
            raise RuntimeError(source_result.error)
        if fraction is None:
            fraction = (result.aggregate or {}).get("recommended_fraction")
    indices = source_result.best_frame_indices(fraction)
    dest = Path(destination)
    base = 0.8 if result.sampled else 0.0

    def cb(done, total):
        if progress:
            progress(f"Schreibe {done}/{total} Frames …", base + (1 - base) * done / max(total, 1))

    cancel_fn = (lambda: cancel.is_set()) if cancel is not None else None
    with open_source(result.path) as src:
        from .io.ser import SerSource, write_ser_frames, write_ser_subset
        if isinstance(src, SerSource):
            n = write_ser_subset(src, indices, dest, cb, cancel_fn)
        elif hasattr(src, "raw_frames"):
            info = src.info
            n = write_ser_frames((f for _, f in src.raw_frames(indices)), dest, width=info.width,
                                 height=info.height, color=info.color, depth=8, count=len(indices),
                                 progress=cb, cancel=cancel_fn)
        else:
            def frames():
                for i in indices:
                    yield (src.read_frame(int(i)) * 65535).astype(np.uint16)
            first = src.read_frame(int(indices[0]))
            n = write_ser_frames(frames(), dest, width=first.shape[1], height=first.shape[0], color="mono",
                                 depth=16, count=len(indices), progress=cb, cancel=cancel_fn)
    return dest, n
