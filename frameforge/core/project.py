"""FrameForge projects (*.ffproj): an analysed session saved for later.

A project is a ZIP archive with
  project.json      – session, settings and all scores/reasons (human readable)
  files/<n>.npz     – per-file arrays (frame quality, metrics, preview)
so that results can be reopened instantly without re-analysing the data.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import __version__
from .analyzer import FileResult, SessionResult
from .io.base import SourceInfo
from .scoring import Reason

PROJECT_EXTENSION = ".ffproj"
FORMAT_VERSION = 1

_ARRAY_FIELDS = ("indices", "quality", "times", "positions", "local_maps", "preview", "preview_local")


def _file_state(f: FileResult) -> dict:
    return {
        "path": str(f.path),
        "info": f.info.to_dict() if f.info else None,
        "profile": f.profile,
        "sampled": f.sampled,
        "aggregate": f.aggregate,
        "components": f.components,
        "score": f.score,
        "verdict": f.verdict,
        "potential": f.potential,
        "rank": f.rank,
        "reasons": [r.to_dict() for r in f.reasons],
        "recommendations": f.recommendations,
        "summary": f.summary,
        "best_index": f.best_index,
        "preview_roi": list(f.preview_roi) if f.preview_roi else None,
        "timeline_start": f.timeline_start,
        "error": f.error,
        "elapsed_s": f.elapsed_s,
        "array_keys": sorted(f.arrays),
    }


def _json_default(value):
    if isinstance(value, (np.floating,)):
        v = float(value)
        return v if np.isfinite(v) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value))


def save_project(session: SessionResult, destination: str | os.PathLike, queue: list | None = None) -> Path:
    dest = Path(destination)
    if dest.suffix.lower() != PROJECT_EXTENSION:
        dest = dest.with_suffix(PROJECT_EXTENSION)
    state = {
        "format": FORMAT_VERSION,
        "generator": f"FrameForge {__version__}",
        "saved": datetime.now().isoformat(timespec="seconds"),
        "created": session.created.isoformat(),
        "profile": session.profile,
        "mode": session.mode,
        "cancelled": session.cancelled,
        "elapsed_s": session.elapsed_s,
        "recommendations": session.recommendations,
        "queue": [str(p) for p in (queue or [f.path for f in session.files])],
        "files": [_file_state(f) for f in session.files],
    }
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(state, ensure_ascii=False, indent=1, default=_json_default))
        for n, f in enumerate(session.files):
            arrays = {f"a_{k}": v for k, v in f.arrays.items()}
            for key in _ARRAY_FIELDS:
                value = getattr(f, key)
                if value is not None:
                    arrays[key] = np.asarray(value)
            buf = io.BytesIO()
            np.savez_compressed(buf, **arrays)
            zf.writestr(f"files/{n}.npz", buf.getvalue())
    tmp.replace(dest)
    return dest


def load_project(source: str | os.PathLike) -> tuple[SessionResult, list[Path]]:
    path = Path(source)
    with zipfile.ZipFile(path) as zf:
        state = json.loads(zf.read("project.json").decode("utf-8"))
        if int(state.get("format", 0)) > FORMAT_VERSION:
            raise ValueError("Das Projekt wurde mit einer neueren FrameForge-Version erstellt.")
        files: list[FileResult] = []
        for n, fs in enumerate(state["files"]):
            f = FileResult(path=Path(fs["path"]))
            info = fs.get("info")
            if info:
                info = dict(info)
                info["path"] = Path(info["path"])
                f.info = SourceInfo(**info)
            for key in ("profile", "sampled", "aggregate", "score", "verdict", "potential", "rank",
                        "recommendations", "summary", "best_index", "timeline_start", "error", "elapsed_s"):
                if key in fs:
                    setattr(f, key, fs[key])
            f.components = fs.get("components") or {}
            f.reasons = [Reason(r["kind"], r["text"]) for r in fs.get("reasons", [])]
            f.preview_roi = tuple(fs["preview_roi"]) if fs.get("preview_roi") else None
            name = f"files/{n}.npz"
            if name in zf.namelist():
                with np.load(io.BytesIO(zf.read(name)), allow_pickle=False) as data:
                    for key in data.files:
                        if key.startswith("a_"):
                            f.arrays[key[2:]] = data[key]
                        elif key in _ARRAY_FIELDS:
                            setattr(f, key, data[key])
            files.append(f)
    created = datetime.fromisoformat(state["created"])
    session = SessionResult(files=files, profile=state["profile"], mode=state["mode"], created=created,
                            recommendations=state.get("recommendations", []), cancelled=state.get("cancelled", False),
                            elapsed_s=state.get("elapsed_s", 0.0))
    queue = [Path(p) for p in state.get("queue", [f.path for f in files])]
    return session, queue
