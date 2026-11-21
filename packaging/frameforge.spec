# PyInstaller spec – builds a windowed app (onedir) for Windows and macOS.
# Usage:  pyinstaller --noconfirm packaging/frameforge.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from frameforge import APP_NAME, __version__  # noqa: E402

ICONS = ROOT / "packaging" / "icons"
datas = [(str(ROOT / "frameforge" / "resources"), "frameforge/resources")]
datas += collect_data_files("certifi")
binaries = collect_dynamic_libs("rawpy")
# imagecodecs ships ~60 codecs; TIFF files from astro/photo software only need a few
# (LZW, Deflate/ZIP, PackBits, LZMA, Zstd, JPEG, predictors).
KEEP_CODECS = {"_imcd", "_shared", "_shared_cython", "_zlib", "_zlibng", "_deflate", "_lzma", "_zstd",
               "_jpeg8", "_jpeg", "_imagecodecs", "_numpy", "imagecodecs", "numcodecs"}
hiddenimports = [f"imagecodecs.{m}" for m in sorted(KEEP_CODECS) if m.startswith("_")] + ["rawpy._rawpy"]


def keep_entry(dest: str) -> bool:
    parts = dest.replace("\\", "/").split("/")
    if len(parts) == 2 and parts[0] == "imagecodecs":
        return parts[1].split(".")[0] in KEEP_CODECS
    return True

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "astropy", "scipy", "pandas", "IPython", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
a.binaries = [b for b in a.binaries if keep_entry(b[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=str(ICONS / ("frameforge.icns" if sys.platform == "darwin" else "frameforge.ico")),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ICONS / "frameforge.icns"),
        bundle_identifier="io.github.frameforge",
        version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "FrameForge",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "FrameForge-Projekt",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Owner",
                    "CFBundleTypeExtensions": ["ffproj"],
                    "CFBundleTypeIconFile": "frameforge.icns",
                },
                {
                    "CFBundleTypeName": "Astro-Aufnahme",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "CFBundleTypeExtensions": ["ser", "avi", "mp4", "mov", "fits", "fit", "fts", "tif", "tiff"],
                },
            ],
        },
    )
