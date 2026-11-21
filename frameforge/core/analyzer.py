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
from .trace import fmt
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
    #: Optional live trace sink (see core/trace.py); not part of the analysis result
    trace: Callable[[str], None] | None = field(default=None, repr=False, compare=False)

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
    summary: str = ""
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
            "summary": self.summary,
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
    elapsed_s: float = 0.0

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
            "elapsed_s": round(self.elapsed_s, 2),
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
    tr = options.trace
    t0 = time.perf_counter()
    try:
        if tr:
            tr("")
            tr(f"# ── {Path(path).name} " + "─" * max(4, 52 - len(Path(path).name)))
            tr(f">>> source = open_source({Path(path).name!r})")
        with open_source(path) as source:
            info = source.info
            result.info = info
            indices = sample_indices(info.frame_count, options.max_frames)
            result.sampled = indices.size < info.frame_count
            if tr:
                tr(f"    {info.format} · {info.width}×{info.height} px · {info.bit_depth} bit · {info.color} · "
                   f"{info.frame_count} Frame(s)" + (f" · {fmt(info.fps, 1)} fps" if info.fps else ""))
                tr(f">>> indices = sample_indices({info.frame_count}, max_frames={options.max_frames})"
                   f"   # {indices.size} Frames" + (" (Stichprobe)" if result.sampled else ""))

            # Reference detection fixes the analysis scale for the whole file
            ref_idx = int(indices[indices.size // 2])
            ref = source.read_frame(ref_idx)
            ref_det = detect_object(ref, profile)
            scale = 1.0
            if options.max_size:
                scale = min(1.0, options.max_size / max(ref_det.roi[2], ref_det.roi[3], 1))
            if tr:
                x, y, w, h = ref_det.roi
                kind = "Oberfläche/Feld" if ref_det.surface else "Objekt"
                tr(f">>> det = detect_object(frame[{ref_idx}], profile={profile.key!r})")
                tr(f"    roi=({x},{y},{w}×{h}) · {kind} · Füllgrad={fmt(ref_det.object_fraction, 3)} · scale={fmt(scale, 3)}")
                tr(f">>> for i in indices: m = {'compute_star_metrics' if profile.key == 'deepsky' else 'compute_metrics'}"
                   f"(frame[i])   # {options.threads} Threads")

            metrics, positions = _process_frames(source, indices, profile, scale, options.threads, progress,
                                                 cancel, ref.shape, tr)
            if not metrics:
                raise RuntimeError("Es konnten keine Frames gelesen werden.")
            result.indices = np.array([m.index for m in metrics], dtype=np.int64)
            result.arrays = {k: np.array([float(getattr(m, k)) for m in metrics], dtype=np.float64)
                             for k in SCALAR_FIELDS}
            result.local_maps = np.stack([m.local_map for m in metrics])
            result.positions = positions
            result.quality = frame_quality(result.arrays, profile.key)
            if tr:
                q = result.quality
                if profile.key == "deepsky":
                    tr(">>> q = 100·(0.55·FWHM_best/FWHM + 0.25·Sterne/Sterne_p99 + 0.20·(0.75−ecc)/0.35)")
                else:
                    tr(">>> q = 100·(0.85·S/S_p99 + 0.10·K/K_p99 + 0.05·U) · Helligkeits-/Rand-Korrektur")
                tr(f"    quality: min={fmt(q.min(), 1)} median={fmt(float(np.median(q)), 1)} max={fmt(q.max(), 1)}")

            ts = source.timestamps()
            if ts is not None and ts.size == info.frame_count:
                result.times = ts[result.indices]
            md = info.metadata or {}
            start = md.get("start_utc") or md.get("date_obs")
            result.timeline_start = _parse_start(start) or result.path.stat().st_mtime

            best_pos = int(np.argmax(result.quality))
            result.best_index = int(result.indices[best_pos])
            best = ref if result.best_index == ref_idx else source.read_frame(result.best_index)
            result.preview, pf = stretch_to_uint8(best)
            bx, by, bw, bh = metrics[best_pos].roi
            result.preview_roi = (int(bx * pf), int(by * pf), int(bw * pf), int(bh * pf))
            result.preview_local = metrics[best_pos].local_map
            result.aggregate = _aggregate(result, metrics, info, ref.shape)
            if tr:
                a = result.aggregate
                tr(">>> recommend_selection(quality)")
                tr(f"    # {a['selection_reason']}")
                tr(f"    → beste {fmt(a['recommended_fraction'] * 100, 1)} % = {a['recommended_frames']} Frames · "
                   f"bester Frame #{result.best_index}")
                if profile.key == "deepsky":
                    tr(f"    aggregate: fwhm={fmt(a['fwhm'], 3)} px · ecc={fmt(a['eccentricity'], 3)} · "
                       f"stars={a['star_count']} · bg={fmt(a['background'])} · snr={fmt(a['snr'], 1)}")
                else:
                    tr(f"    aggregate: sharp={fmt(a['sharp_combined'])} · contrast={fmt(a['contrast'])} · "
                       f"snr_stack={fmt(a['snr_stack'], 1)} · peak={fmt(a['peak'], 3)} · jitter={fmt(a['jitter_px'], 2)} px")
    except InterruptedError:
        raise
    except Exception as exc:  # report and continue with the next file
        result.error = f"{type(exc).__name__}: {exc}"
        result.verdict = VERDICT_ERROR
        if tr:
            tr(f"!!! Fehler: {result.error}")
    result.elapsed_s = time.perf_counter() - t0
    if tr and result.error is None:
        n = result.analyzed_frames
        tr(f"    ✓ {n} Frame(s) in {fmt(result.elapsed_s, 2)} s ({fmt(n / max(result.elapsed_s, 1e-6), 1)} Frames/s)")
    return result


def _parse_start(text) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except ValueError:
        return None


def _process_frames(source, indices, profile, scale, threads, progress, cancel,
                    frame_shape, trace=None) -> tuple[list[FrameMetrics], np.ndarray]:
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
        if trace:
            trace(_frame_line(m, profile.key, state["pos"]))
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


def _nanmedian(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(np.median(finite)) if finite.size else float("nan")


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
        "fwhm": _nanmedian(a["fwhm"][top]),
        "eccentricity": _nanmedian(a["eccentricity"][top]),
        "star_count": int(np.median(a["star_count"][top])),
        "background": _nanmedian(a["background"][top]),
        "quality_mean": float(np.mean(q)),
        "quality_cv": float(np.std(q) / np.mean(q)) if np.mean(q) > 0 else 0.0,
    }


def _frame_line(m: FrameMetrics, profile_key: str, pos) -> str:
    if profile_key == "deepsky":
        return (f"    frame[{m.index:05d}] stars={m.star_count:<4d} fwhm={fmt(m.fwhm, 3):<5} ecc={fmt(m.eccentricity, 3):<5} "
                f"bg={fmt(m.background):<6} σ={fmt(m.noise_sigma)}")
    return (f"    frame[{m.index:05d}] sharp={fmt(m.sharpness):<6} σ={fmt(m.noise_sigma):<6} "
            f"snr={fmt(m.snr, 1):<5} peak={fmt(m.peak, 3):<5} Δ=({fmt(pos[0], 1)},{fmt(pos[1], 1)})"
            + ("  ⚠ Rand" if m.touches_edge else "") + ("  ⚠ kein Signal" if m.low_signal else ""))


# ---------------------------------------------------------------------------
# Session analysis
# ---------------------------------------------------------------------------

def score_files(files: list[FileResult], profile: Profile, trace=None) -> list[str]:
    """(Re-)score files against each other; returns session recommendations."""
    assessments = assess_session([f.aggregate if f.error is None else None for f in files], profile)
    if trace:
        _trace_scoring(trace, files, assessments, profile)
    for f, a in zip(files, assessments):
        if f.error is not None:
            f.score, f.verdict, f.potential = 0.0, VERDICT_ERROR, "–"
            f.reasons = [Reason("minus", f.error)]
            f.recommendations = []
            continue
        f.components, f.score, f.verdict, f.potential = a.components, a.score, a.verdict, a.potential
        f.summary = a.summary
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


def _trace_scoring(tr, files, assessments, profile: Profile) -> None:
    from .scoring import component_label

    ok = sum(1 for f in files if f.error is None)
    tr("")
    tr("# ── Session-Bewertung " + "─" * 36)
    tr(f">>> assess_session({ok} Dateien, profile={profile.key!r})")
    tr("    # relativ: c = 50 + 50·tanh(ln(Wert/Median)/Skala) · absolut: Belichtung, Stabilität, Form")
    for f, a in zip(files, assessments):
        if f.error is not None:
            continue
        tr(f"  {f.path.name}")
        used = [(k, v) for k, v in a.components.items() if v is not None and k in profile.weights]
        for k, v in a.components.items():
            label = component_label(k, profile)
            tr(f"    c[{k:<9}] = {'n. b.' if v is None else fmt(v, 1):>6}   # {label}")
        if used:
            terms = " + ".join(f"{profile.weights[k]:.2f}·{v:.1f}" for k, v in used)
            den = sum(profile.weights[k] for k, _ in used)
            tr(f"    score = ({terms}) / {den:.2f} = {a.score:.1f}  → {a.verdict}")


def analyze_session(paths: Sequence[str | os.PathLike], options: AnalysisOptions,
                    progress: ProgressCallback | None = None, cancel: threading.Event | None = None,
                    on_file: Callable[[FileResult], None] | None = None) -> SessionResult:
    profile = get_profile(options.profile)
    files = collect_files(paths, recursive=options.recursive)
    results: list[FileResult] = []
    session = SessionResult(files=results, profile=profile.key, mode=options.mode,
                            created=datetime.now(timezone.utc))
    n = len(files)
    t0 = time.perf_counter()
    tr = options.trace
    if tr:
        tr(f"# FrameForge · Profil {profile.name} · Modus {options.mode} · {options.threads} Threads")
        tr(f">>> files = collect_files({len(paths)} Pfad(e))   # {n} unterstützte Datei(en)")
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
    session.recommendations = score_files(results, profile, tr)
    session.elapsed_s = time.perf_counter() - t0
    if tr:
        ranked = session.ranked()
        tr("")
        tr(f">>> ranking   # {len(results)} Dateien in {fmt(session.elapsed_s, 2)} s")
        for f in ranked[:10]:
            if f.error is None:
                tr(f"    #{f.rank:<2} {f.score:5.1f} {f.verdict:<16} {f.path.name}")
        tr("# ✓ Analyse " + ("abgebrochen" if session.cancelled else "abgeschlossen"))
    if progress:
        progress("Analyse abgeschlossen" if not session.cancelled else "Analyse abgebrochen", 1.0)
    return session
