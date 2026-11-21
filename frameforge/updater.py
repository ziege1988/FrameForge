"""In-app updater based on GitHub Releases (free, no own server required).

Release convention (created automatically by ``.github/workflows/release.yml``):

* Tag ``vX.Y.Z`` (pre-releases e.g. ``v1.2.0-beta.1`` are marked as such)
* Assets
    - ``FrameForge-X.Y.Z-windows-x64-setup.exe``
    - ``FrameForge-X.Y.Z-macos-arm64.dmg``
    - ``FrameForge-X.Y.Z-macos-x86_64.dmg``
    - ``SHA256SUMS.txt`` (checksums of all assets, verified before installing)

The module has no Qt dependency so it can be tested headless.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import UPDATE_REPOSITORY, __version__

API_URL = "https://api.github.com/repos/{repo}/releases?per_page=15"
_VERSION_RE = re.compile(
    r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(alpha|beta|rc|a|b|pre)[.-]?(\d+)?)?", re.IGNORECASE
)
_PRE_ORDER = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "pre": 2, "rc": 3}


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple:
    m = _VERSION_RE.match(text or "")
    if not m:
        raise ValueError(f"Ungültige Versionsangabe: {text!r}")
    major, minor, patch = (int(g) if g else 0 for g in m.groups()[:3])
    pre, pre_num = m.group(4), m.group(5)
    if pre:
        return (major, minor, patch, 0, _PRE_ORDER[pre.lower()], int(pre_num or 0))
    return (major, minor, patch, 1, 0, 0)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def is_prerelease_version(text: str) -> bool:
    return parse_version(text)[3] == 0


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "windows":
        return "windows-x64"
    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x86_64"
    return "linux"


_ASSET_PATTERNS = {
    "windows-x64": re.compile(r"windows.*\.exe$", re.IGNORECASE),
    "macos-arm64": re.compile(r"macos-arm64.*\.dmg$", re.IGNORECASE),
    "macos-x86_64": re.compile(r"macos-(x86_64|intel|x64).*\.dmg$", re.IGNORECASE),
}


@dataclass
class Asset:
    name: str
    url: str
    size: int


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    name: str
    notes: str
    published: str
    html_url: str
    prerelease: bool
    assets: list[Asset] = field(default_factory=list)

    def asset_for(self, key: str | None = None) -> Asset | None:
        pattern = _ASSET_PATTERNS.get(key or platform_key())
        if pattern is None:
            return None
        for a in self.assets:
            if pattern.search(a.name):
                return a
        return None

    def checksum_asset(self) -> Asset | None:
        for a in self.assets:
            if a.name.lower() in ("sha256sums.txt", "sha256sums", "checksums.txt"):
                return a
        return None


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # bundled CA certificates – required in frozen macOS builds
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover
        return ssl.create_default_context()


def _request(url: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"FrameForge-Updater/{__version__}"})


def _parse_release(data: dict) -> ReleaseInfo | None:
    if data.get("draft"):
        return None
    tag = data.get("tag_name") or ""
    try:
        parse_version(tag)
    except ValueError:
        return None
    assets = [Asset(a.get("name", ""), a.get("browser_download_url", ""), int(a.get("size", 0)))
              for a in data.get("assets", [])]
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=data.get("name") or tag,
        notes=data.get("body") or "",
        published=(data.get("published_at") or "")[:10],
        html_url=data.get("html_url") or "",
        prerelease=bool(data.get("prerelease")) or is_prerelease_version(tag),
        assets=assets,
    )


def fetch_releases(repo: str = UPDATE_REPOSITORY, timeout: float = 10.0, opener=None) -> list[ReleaseInfo]:
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()))
    try:
        with opener(_request(API_URL.format(repo=repo))) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Update-Server nicht erreichbar (Repository nicht gefunden oder privat).") from exc
        if exc.code == 403:
            raise UpdateError("Zu viele Update-Abfragen – bitte später erneut versuchen.") from exc
        raise UpdateError(f"Update-Prüfung fehlgeschlagen (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Keine Verbindung zum Update-Server. Internetverbindung prüfen.") from exc
    releases = [r for r in (_parse_release(d) for d in payload if isinstance(d, dict)) if r is not None]
    return sorted(releases, key=lambda r: parse_version(r.tag), reverse=True)


def check_for_update(current: str = __version__, repo: str = UPDATE_REPOSITORY, include_prerelease: bool = False,
                     timeout: float = 10.0, opener=None) -> ReleaseInfo | None:
    """Return the newest applicable release if it is newer than ``current``."""
    for rel in fetch_releases(repo, timeout, opener):
        if rel.prerelease and not include_prerelease:
            continue
        return rel if is_newer(rel.tag, current) else None
    return None


# ---------------------------------------------------------------------------
# Download & installation
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            result[parts[-1].lstrip("*")] = parts[0].lower()
    return result


def download_update(release: ReleaseInfo, dest_dir: str | os.PathLike | None = None,
                    progress: Callable[[int, int], None] | None = None,
                    cancel: threading.Event | None = None, key: str | None = None,
                    timeout: float = 30.0, opener=None) -> Path:
    """Download the installer for this platform and verify its SHA-256 checksum."""
    asset = release.asset_for(key)
    if asset is None:
        raise UpdateError("Für dieses Betriebssystem ist in diesem Release kein Installationspaket verfügbar.")
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()))
    dest_dir = Path(dest_dir or tempfile.mkdtemp(prefix="frameforge-update-"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / asset.name
    partial = target.with_suffix(target.suffix + ".part")

    expected = None
    sums = release.checksum_asset()
    if sums is not None:
        try:
            with opener(_request(sums.url, "application/octet-stream")) as resp:
                expected = parse_checksums(resp.read().decode("utf-8", errors="replace")).get(asset.name)
        except Exception as exc:
            raise UpdateError("Prüfsummen konnten nicht geladen werden.") from exc

    try:
        with opener(_request(asset.url, "application/octet-stream")) as resp, open(partial, "wb") as out:
            total = int(resp.headers.get("Content-Length") or asset.size or 0)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Download abgebrochen.")
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Download fehlgeschlagen: {exc}") from exc

    if expected is not None and sha256_of(partial) != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError("Prüfsumme stimmt nicht – Download beschädigt oder manipuliert. Update abgebrochen.")
    partial.replace(target)
    return target


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def can_self_install() -> tuple[bool, str]:
    """Whether the running build can replace itself."""
    if not is_frozen():
        return False, "Automatische Installation ist nur in der installierten Version möglich."
    key = platform_key()
    if key == "linux":
        return False, "Für Linux gibt es keine automatische Installation."
    if key.startswith("macos"):
        bundle = current_app_bundle()
        if bundle is None:
            return False, "App-Bundle nicht gefunden."
        if not os.access(bundle.parent, os.W_OK):
            return False, f"Keine Schreibrechte für {bundle.parent} – das Update wird stattdessen geöffnet."
    return True, ""


def current_app_bundle() -> Path | None:
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


_MAC_SCRIPT = """#!/bin/sh
# FrameForge update helper – waits for the app to quit, replaces the bundle, restarts it.
PID={pid}; DMG={dmg}; TARGET={target}
while kill -0 "$PID" 2>/dev/null; do sleep 0.5; done
MNT=$(mktemp -d /tmp/frameforge-mnt.XXXXXX)
if ! hdiutil attach -nobrowse -quiet -mountpoint "$MNT" "$DMG"; then open "$DMG"; exit 1; fi
APP=$(find "$MNT" -maxdepth 1 -name "*.app" | head -n 1)
if [ -n "$APP" ]; then
  rm -rf "$TARGET.old"
  if mv "$TARGET" "$TARGET.old" && ditto "$APP" "$TARGET"; then
    rm -rf "$TARGET.old"
  else
    rm -rf "$TARGET"; mv "$TARGET.old" "$TARGET"
  fi
fi
hdiutil detach -quiet "$MNT"
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
open "$TARGET"
rm -f "$0"
"""


def launch_installer(installer: Path) -> None:
    """Start the installation. The caller must quit the application afterwards."""
    key = platform_key()
    if key == "windows-x64":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         creationflags=flags, close_fds=True)
        return
    if key.startswith("macos"):
        ok, _ = can_self_install()
        bundle = current_app_bundle()
        if not ok or bundle is None:
            subprocess.Popen(["open", str(installer)])
            return
        script = installer.parent / "frameforge-update.sh"
        script.write_text(_MAC_SCRIPT.format(pid=os.getpid(), dmg=shlex.quote(str(installer)),
                                             target=shlex.quote(str(bundle))))
        script.chmod(0o755)
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True)
        return
    raise UpdateError("Automatische Installation wird auf diesem System nicht unterstützt.")
