import hashlib
import io
import json

import pytest

from frameforge import updater


def test_version_compare():
    assert updater.is_newer("v0.2.0", "0.1.9")
    assert updater.is_newer("1.0.0", "1.0.0-rc.2")
    assert updater.is_newer("1.0.0-beta.2", "1.0.0-beta.1")
    assert updater.is_newer("1.0.0-rc.1", "1.0.0-beta.5")
    assert not updater.is_newer("0.1.0", "0.1.0")
    assert not updater.is_newer("v0.1", "0.1.0")
    assert updater.is_prerelease_version("2.0.0-alpha")


def test_platform_key():
    assert updater.platform_key("Windows", "AMD64") == "windows-x64"
    assert updater.platform_key("Darwin", "arm64") == "macos-arm64"
    assert updater.platform_key("Darwin", "x86_64") == "macos-x86_64"


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def make_opener(routes):
    def opener(req):
        return FakeResponse(routes[req.full_url])
    return opener


def releases_json(installer: bytes, checksum: str | None = None):
    sha = checksum or hashlib.sha256(installer).hexdigest()
    return json.dumps([
        {"tag_name": "v0.3.0-beta.1", "prerelease": True, "draft": False, "assets": []},
        {"tag_name": "v0.2.0", "name": "FrameForge 0.2.0", "body": "Neu", "prerelease": False, "draft": False,
         "published_at": "2026-11-20T10:00:00Z", "html_url": "https://example.invalid/r",
         "assets": [
             {"name": "FrameForge-0.2.0-windows-x64-setup.exe", "browser_download_url": "https://dl/win", "size": len(installer)},
             {"name": "FrameForge-0.2.0-macos-arm64.dmg", "browser_download_url": "https://dl/mac", "size": len(installer)},
             {"name": "SHA256SUMS.txt", "browser_download_url": "https://dl/sums", "size": 100},
         ]},
        {"tag_name": "v0.4.0", "draft": True, "assets": []},
    ]).encode(), f"{sha}  FrameForge-0.2.0-windows-x64-setup.exe\n{sha}  FrameForge-0.2.0-macos-arm64.dmg\n".encode()


def test_check_for_update_and_download(tmp_path):
    installer = b"installer-bytes" * 1000
    rel_json, sums = releases_json(installer)
    routes = {updater.API_URL.format(repo="o/r"): rel_json, "https://dl/win": installer, "https://dl/sums": sums}
    opener = make_opener(routes)
    rel = updater.check_for_update("0.1.0", "o/r", opener=opener)
    assert rel is not None and rel.version == "0.2.0"
    pre = updater.check_for_update("0.1.0", "o/r", include_prerelease=True, opener=opener)
    assert pre.version == "0.3.0-beta.1"
    assert updater.check_for_update("0.2.0", "o/r", opener=opener) is None
    seen = []
    path = updater.download_update(rel, tmp_path, progress=lambda d, t: seen.append((d, t)),
                                   key="windows-x64", opener=opener)
    assert path.read_bytes() == installer and seen[-1][0] == len(installer)


def test_download_rejects_bad_checksum(tmp_path):
    installer = b"x" * 5000
    rel_json, sums = releases_json(installer, checksum="0" * 64)
    routes = {updater.API_URL.format(repo="o/r"): rel_json, "https://dl/mac": installer, "https://dl/sums": sums}
    opener = make_opener(routes)
    rel = updater.check_for_update("0.1.0", "o/r", opener=opener)
    with pytest.raises(updater.UpdateError, match="Prüfsumme"):
        updater.download_update(rel, tmp_path, key="macos-arm64", opener=opener)
    assert not list(tmp_path.iterdir())


def test_missing_platform_asset(tmp_path):
    rel = updater.ReleaseInfo("1.0.0", "v1.0.0", "", "", "", "", False, [])
    with pytest.raises(updater.UpdateError):
        updater.download_update(rel, tmp_path, key="windows-x64")


def test_not_frozen_cannot_self_install():
    ok, why = updater.can_self_install()
    assert not ok and why


def test_issue_url_and_log_setup(tmp_path, monkeypatch):
    from frameforge import logs

    monkeypatch.setattr(logs, "log_dir", lambda: tmp_path / "logs")
    path = logs.setup_logging()
    logs.log.info("Testeintrag")
    for h in logs.log.handlers:
        h.flush()
    assert path is not None and "Testeintrag" in path.read_text(encoding="utf-8")
    url = logs.issue_url("Traceback: Beispiel")
    assert url.startswith("https://github.com/") and "Traceback" in url
