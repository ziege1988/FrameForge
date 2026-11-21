"""Command line interface: ``frameforge analyze <ordner|dateien> …``"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__


def build_parser() -> argparse.ArgumentParser:
    from .core.analyzer import MODES
    from .core.profiles import PROFILES

    p = argparse.ArgumentParser(prog="frameforge", description=f"{APP_NAME} {__version__} – Astrofoto-Qualitätsanalyse")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="command")
    a = sub.add_parser("analyze", help="Dateien oder Ordner analysieren")
    a.add_argument("paths", nargs="+", help="Dateien oder Ordner")
    a.add_argument("-p", "--profile", choices=list(PROFILES), default="planet")
    a.add_argument("-m", "--mode", choices=list(MODES), default="standard")
    a.add_argument("-t", "--threads", type=int, default=None)
    a.add_argument("--no-recursive", action="store_true", help="Unterordner nicht durchsuchen")
    a.add_argument("--json", type=Path, help="Bericht als JSON speichern")
    a.add_argument("--csv", type=Path, help="Rangliste als CSV speichern")
    a.add_argument("--frames", action="store_true", help="Frame-Werte in den JSON-Bericht aufnehmen")
    a.add_argument("--export-best", type=Path, metavar="ORDNER",
                   help="Beste Frames jedes Videos als SER in diesen Ordner schreiben")
    a.add_argument("-q", "--quiet", action="store_true")
    sub.add_parser("gui", help="Grafische Oberfläche starten")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in (None, "gui"):
        from .gui.app import main as gui_main
        return gui_main()

    from .core.analyzer import AnalysisOptions, analyze_session
    from .core.export import export_best_frames, export_csv, export_json

    opts = AnalysisOptions(profile=args.profile, mode=args.mode, recursive=not args.no_recursive)
    if args.threads:
        opts.threads = max(1, args.threads)

    def progress(msg, frac):
        if not args.quiet:
            print(f"\r[{frac * 100:5.1f} %] {msg:<70}", end="", file=sys.stderr, flush=True)

    session = analyze_session(args.paths, opts, progress)
    if not args.quiet:
        print(file=sys.stderr)
    if not session.files:
        print("Keine unterstützten Dateien gefunden.", file=sys.stderr)
        return 2

    print(f"{'Rang':>4}  {'Score':>5}  {'Urteil':<17} Datei")
    for f in session.ranked():
        print(f"{f.rank or '-':>4}  {f.score:5.1f}  {f.verdict:<17} {f.path.name}")
    print()
    for r in session.recommendations:
        print(f"• {r}")

    if args.json:
        export_json(session, args.json, args.frames)
    if args.csv:
        export_csv(session, args.csv)
    if args.export_best:
        args.export_best.mkdir(parents=True, exist_ok=True)
        for f in session.ranked():
            if f.error is None and f.info.is_video and f.verdict != "Abgelehnt":
                dest, n = export_best_frames(f, args.export_best / f"{f.path.stem}_best.ser", options=opts)
                print(f"→ {dest.name}: {n} Frames")
    return 0
