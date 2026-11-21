"""Orchestrates the analysis of files and complete sessions."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np

from .io import SourceInfo, open_source
from .io.registry import collect_files
from .metrics import SCALAR_FIELDS, THUMB_SIZE, FrameMetrics, compute_metrics, detect_object, phase_shift
from .profiles import Profile, get_profile
from .scoring import (
    VERDICT_ERROR,
    Reason,
    assess_session,
    combined_sharpness,
    frame_quality,
    recommend_selection,
    session_recommendations,
)

# name: (max analysed frames per video, max analysis size in px)
MODES: dict[str, tuple[int | None, int | None]] = {
    "schnell": (200, 1024),
    "standard": (1000, 2048),
    "vollstaendig": (None, None),
}
MODE_LABELS = {"schnell": "Schnell (Stichprobe)", "standard": "Standard", "vollstaendig": "Vollständig (alle Frames)"}

ProgressCallback = Callable[[str, float], None]  # (message, overall fraction 0..1)


@dataclass
class AnalysisOptions:
    profile: str = "planet"
    mode: str = "standard"
    threads: int = max(1, (os.cpu_count() or 2) - 1)
    recursive: bool = True

    @property
    def max_frames(self) -> int | None:
        return MODES[self.mode][0]

    @property
    def max_size(self) -> int | None:
        return MODES[self.mode][1]


@dataclass
class FileResult:
    path: Path
    info: SourceInfo | None = None
    profile: str = "planet"
    indices: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    arrays: dict[str, np.ndarray] = field(default_factory=dict)
    local_maps: np.ndarray | None = None
    quality: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    times: np.ndarray | None = None
    positions: np.ndarray | None = None
    sampled: bool = False
    aggregate: dict | None = None
    components: dict = field(default_factory=dict)
    score: float = 0.0
    verdict: str = ""
    potential: str = ""
    rank: int = 0
    reasons: list[Reason] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    best_index: int = 0
    preview: np.ndarray | None = None  # uint8 luminance of best frame
    preview_roi: tuple[int, int, int, int] | None = None
    preview_local: np.ndarray | None = None
    timeline_start: float | None = None
    error: str | None = None
    elapsed_s: float = 0.0

    @property
    def analyzed_frames(self) -> int:
        return int(self.indices.size)

    def best_frame_indices(self, fraction: float | None = None) -> np.ndarray:
        """Indices of the best frames (sorted chronologically)."""
        if self.quality.size == 0:
            return np.zeros(0, dtype=np.int64)
        frac = fraction if fraction is not None else (self.aggregate or {}).get("recommended_fraction", 1.0)
        k = max(1, int(round(self.quality.size * frac)))
        order = np.argsort(-self.quality, kind="stable")[:k]
        return np.sort(self.indices[order])

    def to_dict(self, include_frames: bool = False) -> dict:
        d = {
            "file": str(self.path),
            "name": self.path.name,
            "rank": self.rank,
            "score": self.score,
            "verdict": self.verdict,
            "potential": self.potential,
            "components": {k: (None if v is None else round(v, 1)) for k, v in self.components.items()},
            "reasons": [r.to_dict() for r in self.reasons],
            "recommendations": list(self.recommendations),
            "info": self.info.to_dict() if self.info else None,
            "metrics": _jsonify(self.aggregate) if self.aggregate else None,
            "analyzed_frames": self.analyzed_frames,
            "sampled": self.sampled,
            "best_frame": int(self.best_index),
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 2),
        }
        if include_frames and self.quality.size:
            d["frames"] = [
                {"index": int(i), "quality": round(float(q), 2),
                 **{k: _jsonify(float(self.arrays[k][n])) for k in ("sharpness", "contrast", "snr", "peak")}}
                for n, (i, q) in enumerate(zip(self.indices, self.quality))
            ]
        return d


@dataclass
class SessionResult:
    files: list[FileResult]
    profile: str
    mode: str
    created: datetime
    recommendations: list[str] = field(default_factory=list)
    cancelled: bool = False

    def ranked(self) -> list[FileResult]:
        return sorted(self.files, key=lambda f: (f.error is not None, -f.score))

    def to_dict(self, include_frames: bool = False) -> dict:
        from .. import __version__

        return {
            "generator": f"FrameForge {__version__}",
            "created": self.created.isoformat(),
            "profile": self.profile,
            "mode": self.mode,
            "cancelled": self.cancelled,
            "recommendations": self.recommendations,
            "files": [f.to_dict(include_frames) for f in self.ranked()],
        }


def _jsonify(value):
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return None if not np.isfinite(v) else round(v, 6)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def sample_indices(count: int, max_frames: int | None) -> np.ndarray:
    if max_frames is None or count <= max_frames:
        return np.arange(count, dtype=np.int64)
    return np.unique(np.linspace(0, count - 1, max_frames).round().astype(np.int64))


def stretch_to_uint8(frame: np.ndarray, max_dim: int = 900) -> tuple[np.ndarray, float]:
    lo, hi = np.percentile(frame, (0.5, 99.8))
    img = np.clip((frame - lo) / max(hi - lo, 1e-6), 0, 1)
    img = np.power(img, 0.8)
    h, w = img.shape
    f = min(1.0, max_dim / max(h, w))
    if f < 1:
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return (img * 255).astype(np.uint8), f


# ---------------------------------------------------------------------------
# File analysis
# ---------------------------------------------------------------------------

def analyze_file(path: str | os.PathLike, options: AnalysisOptions, progress: Callable[[float], None] | None = None,
                 cancel: threading.Event | None = None, profile: Profile | None = None) -> FileResult:
    """Analyse one file. Errors are captured in ``FileResult.error``."""
    profile = profile or get_profile(options.profile)
    result = FileResult(path=Path(path), profile=profile.key)
    t0 = time.perf_counter()
    try:
        with open_source(path) as source:
            info = source.info
            result.info = info
            indices = sample_indices(info.frame_count, options.max_frames)
            result.sampled = indices.size < info.frame_count

            # Reference detection fixes the analysis scale for the whole file
            ref_idx = int(indices[indices.size // 2])
            ref = source.read_frame(ref_idx)
            ref_det = detect_object(ref, profile)
            scale = 1.0
            if options.max_size:
                scale = min(1.0, options.max_size / max(ref_det.roi[2], ref_det.roi[3], 1))

            metrics, positions = _process_frames(source, indices, profile, scale, options.threads, progress,
                                                 cancel, ref.shape)
            if not metrics:
                raise RuntimeError("Es konnten keine Frames gelesen werden.")
            result.indices = np.array([m.index for m in metrics], dtype=np.int64)
            result.arrays = {k: np.array([float(getattr(m, k)) for m in metrics], dtype=np.float64)
                             for k in SCALAR_FIELDS}
            result.local_maps = np.stack([m.local_map for m in metrics])
            result.positions = positions
            result.quality = frame_quality(result.arrays)

            ts = source.timestamps()
            if ts is not None and ts.size == info.frame_count:
                result.times = ts[result.indices]
            start = info.metadata.get("start_utc") if info.metadata else None
            result.timeline_start = _parse_start(start) or result.path.stat().st_mtime

            best_pos = int(np.argmax(result.quality))
            result.best_index = int(result.indices[best_pos])
            best = ref if result.best_index == ref_idx else source.read_frame(result.best_index)
            result.preview, pf = stretch_to_uint8(best)
            bx, by, bw, bh = metrics[best_pos].roi
            result.preview_roi = (int(bx * pf), int(by * pf), int(bw * pf), int(bh * pf))
            result.preview_local = metrics[best_pos].local_map
            result.aggregate = _aggregate(result, metrics, info, ref.shape)
    except InterruptedError:
        raise
    except Exception as exc:  # report and continue with the next file
        result.error = f"{type(exc).__name__}: {exc}"
        result.verdict = VERDICT_ERROR
    result.elapsed_s = time.perf_counter() - t0
    return result


def _parse_start(text) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except ValueError:
        return None


def _process_frames(source, indices, profile, scale, threads, progress, cancel,
                    frame_shape) -> tuple[list[FrameMetrics], np.ndarray]:
    """Read frames sequentially (I/O) and compute metrics in a thread pool.

    At most ``2 × threads`` frames are in flight and only the thumbnail of the
    previous frame is kept for the shift measurement, so memory usage stays
    bounded independent of the file size. Returns the metrics and the
    cumulative image shift (luminance pixels) of every analysed frame.
    """
    total = len(indices)
    out: list[FrameMetrics] = []
    positions: list[tuple[float, float]] = []
    thumb_scale = max(frame_shape) / THUMB_SIZE
    state = {"prev": None, "pos": (0.0, 0.0)}
    window = max(2, threads * 2)
    pending: deque = deque()

    def collect(m: FrameMetrics):
        # Results arrive in chronological order → incremental phase correlation
        if state["prev"] is not None:
            dx, dy = phase_shift(state["prev"], m.thumb)
            state["pos"] = (state["pos"][0] + dx * thumb_scale, state["pos"][1] + dy * thumb_scale)
        state["prev"] = m.thumb
        m.thumb = None
        positions.append(state["pos"])
        out.append(m)
        if progress and len(out) % 5 == 0:
            progress(len(out) / total)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for idx, frame in source.iter_frames(indices.tolist()):
            if cancel is not None and cancel.is_set():
                for f in pending:
                    f.cancel()
                raise InterruptedError("Analyse abgebrochen")
            pending.append(pool.submit(compute_metrics, frame, profile, int(idx), scale))
            while len(pending) >= window:
                collect(pending.popleft().result())
        while pending:
            collect(pending.popleft().result())
    if progress:
        progress(1.0)
    return out, np.array(positions, dtype=np.float64).reshape(-1, 2)


def _aggregate(result: FileResult, metrics: list[FrameMetrics], info: SourceInfo, frame_shape) -> dict:
    a = result.arrays
    q = result.quality
    frac, sel_reason = recommend_selection(q, info.frame_count)
    k = max(1, int(round(q.size * frac)))
    top = np.argsort(-q, kind="stable")[:k]
    rec_frames = max(1, int(round(info.frame_count * frac)))

    def med(key, sel=top):
        return float(np.median(a[key][sel]))

    sharp_c = combined_sharpness(a["sharpness"], a["tenengrad"])
    # Reference size: object diameter (ROI without margin) or frame diagonal for surface shots
    roi_diag = float(np.median([np.hypot(m.roi[2], m.roi[3]) for m in metrics])) / 1.3 or float(np.hypot(*frame_shape))
    pos = result.positions if result.positions is not None else np.zeros((1, 2))
    if len(pos) > 2:
        # Residual jitter after removing a linear drift (tracking) → tip/tilt, wind
        t = np.arange(len(pos), dtype=np.float64)
        resid = pos - np.column_stack([np.polyval(np.polyfit(t, pos[:, k], 1), t) for k in range(2)])
        jitter = float(np.sqrt(np.mean(np.sum(resid ** 2, axis=1))))
    else:
        jitter = 0.0
    drift = float(np.hypot(*(pos.max(axis=0) - pos.min(axis=0)))) if len(pos) > 1 else 0.0
    signal = a["signal"]
    sig_med = float(np.median(signal))
    dropouts = float(np.mean(signal < 0.6 * sig_med)) if sig_med > 0 else 0.0
    snr = med("snr")
    return {
        "is_video": bool(info.frame_count > 1),
        "frame_count": int(info.frame_count),
        "analyzed_frames": int(q.size),
        "duration_s": info.duration_s,
        "recommended_fraction": float(frac),
        "recommended_frames": int(rec_frames),
        "selection_reason": sel_reason,
        "sharpness": med("sharpness"),
        "tenengrad": med("tenengrad"),
        "sharp_combined": float(np.mean(sharp_c[top])),
        "contrast": med("contrast"),
        "uniformity": med("uniformity"),
        "snr": snr,
        "snr_stack": float(snr * np.sqrt(rec_frames)),
        "noise_sigma": med("noise_sigma"),
        "peak": float(np.median(a["peak"])),
        "clip_high": float(np.median(a["clip_high"])),
        "clip_low": float(np.median(a["clip_low"])),
        "coherence": med("coherence"),
        "blur_angle": med("blur_angle"),
        "edge_fraction": float(np.mean(a["touches_edge"] > 0)),
        "low_signal_fraction": float(np.mean(a["low_signal"] > 0)),
        "surface": bool(np.median(a["object_fraction"]) > 0.35),
        "jitter_px": jitter,
        "drift_px": drift,
        "jitter_rel": jitter / roi_diag if roi_diag else 0.0,
        "dropout_fraction": dropouts,
        "quality_mean": float(np.mean(q)),
        "quality_cv": float(np.std(q) / np.mean(q)) if np.mean(q) > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Session analysis
# ---------------------------------------------------------------------------

def score_files(files: list[FileResult], profile: Profile) -> list[str]:
    """(Re-)score files against each other; returns session recommendations."""
    assessments = assess_session([f.aggregate if f.error is None else None for f in files], profile)
    for f, a in zip(files, assessments):
        if f.error is not None:
            f.score, f.verdict, f.potential = 0.0, VERDICT_ERROR, "–"
            f.reasons = [Reason("minus", f.error)]
            f.recommendations = []
            continue
        f.components, f.score, f.verdict, f.potential = a.components, a.score, a.verdict, a.potential
        f.reasons = a.reasons
        if f.info and f.info.warnings:
            f.reasons = [Reason("info", w) for w in f.info.warnings] + f.reasons
        if f.sampled:
            f.reasons.append(Reason("info", f"Stichprobe: {f.analyzed_frames} von {f.info.frame_count} Frames analysiert."))
        f.recommendations = a.recommendations
    ranked = sorted([f for f in files if f.error is None], key=lambda f: -f.score)
    for i, f in enumerate(ranked, start=1):
        f.rank = i
    return session_recommendations(files, profile)


def analyze_session(paths: Sequence[str | os.PathLike], options: AnalysisOptions,
                    progress: ProgressCallback | None = None, cancel: threading.Event | None = None,
                    on_file: Callable[[FileResult], None] | None = None) -> SessionResult:
    profile = get_profile(options.profile)
    files = collect_files(paths, recursive=options.recursive)
    results: list[FileResult] = []
    session = SessionResult(files=results, profile=profile.key, mode=options.mode,
                            created=datetime.now(timezone.utc))
    n = len(files)
    for i, path in enumerate(files):
        if cancel is not None and cancel.is_set():
            session.cancelled = True
            break

        def file_progress(frac, _i=i, _p=path):
            if progress:
                progress(f"Analysiere {_p.name} ({_i + 1}/{n})", (_i + frac) / n)

        file_progress(0.0)
        try:
            res = analyze_file(path, options, file_progress, cancel, profile)
        except InterruptedError:
            session.cancelled = True
            break
        results.append(res)
        if on_file:
            on_file(res)
    session.recommendations = score_files(results, profile)
    if progress:
        progress("Analyse abgeschlossen" if not session.cancelled else "Analyse abgebrochen", 1.0)
    return session
