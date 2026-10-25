from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from petcore.update import UpdateAsset, UpdateResult, UpdateService, parse_manifest


class _Response:
    def __init__(self, body: bytes = b"", *, status: int = 200, headers=None, url: str | None = None):
        self._body = body
        self.status = status
        self.headers = headers or {}
        self._url = url
        self.closed = False

    def read(self, _limit=-1):
        value, self._body = self._body, b""
        return value

    def geturl(self):
        return self._url or "https://api.github.com/releases/latest"

    def close(self):
        self.closed = True


def _manifest(data: bytes, *, version: str = "9.0.0") -> tuple[dict, UpdateAsset]:
    digest = hashlib.sha256(data).hexdigest()
    asset = UpdateAsset("petcore-setup.exe", "https://github.com/example/petcore-setup.exe", len(data), digest)
    return {
        "version": version,
        "release_url": "https://github.com/example/releases/9.0.0",
        "assets": [asset.__dict__ if hasattr(asset, "__dict__") else {
            "name": asset.name, "url": asset.url, "size": asset.size, "sha256": asset.sha256,
            "platform": asset.platform, "architecture": asset.architecture, "variant": asset.variant,
        }],
    }, asset


def test_parse_manifest_rejects_untrusted_urls_and_keeps_valid_assets() -> None:
    raw, asset = _manifest(b"installer")
    raw["assets"].append({"name": "bad.exe", "url": "http://example.com/bad.exe", "size": 1, "sha256": "0" * 64})
    parsed = parse_manifest(raw)
    assert parsed.version == "9.0.0"
    assert parsed.assets == (asset,)
    with pytest.raises(ValueError):
        parse_manifest({"version": "1.0.0", "release_url": "file:///tmp/release", "assets": []})


def test_update_check_uses_etag_cache_and_304(tmp_path: Path) -> None:
    raw, _asset = _manifest(b"installer")
    calls = []

    def first(request):
        calls.append(dict(request.header_items()))
        return _Response(json.dumps(raw).encode(), headers={"ETag": '"abc"'})

    service = UpdateService(tmp_path, current_version="1.0.0", fetcher=first)
    assert service.check(force=True).state == "available"
    assert service.check().state == "available"

    def second(request):
        calls.append(dict(request.header_items()))
        return _Response(status=304, headers={"ETag": '"abc"'})

    service.fetcher = second
    assert service.check(force=True).state == "available"
    assert any(key.lower() == "if-none-match" and value == '"abc"' for key, value in calls[-1].items())


def test_download_resumes_206_and_verifies_digest(tmp_path: Path) -> None:
    body = b"0123456789"
    raw, asset = _manifest(body)
    service = UpdateService(tmp_path, fetcher=lambda request: _Response(json.dumps(raw).encode()))
    service._manifest = parse_manifest(raw)
    service.update_dir.mkdir(parents=True)
    part = service.update_dir / (asset.name + ".part")
    part.write_bytes(body[:4])
    (service.update_dir / (asset.name + ".part.json")).write_text(json.dumps({
        "url": asset.url, "size": asset.size, "sha256": asset.sha256, "name": asset.name,
    }), encoding="utf-8")

    def fetch(request):
        assert request.get_header("Range") == "bytes=4-"
        return _Response(body[4:], status=206, headers={"Content-Range": "bytes 4-9/10"}, url=asset.url)

    service.fetcher = fetch
    result = service.download(asset)
    assert result.read_bytes() == body
    assert service.status().state == "downloaded"


def test_download_cancel_preserves_partial_state(tmp_path: Path) -> None:
    body = b"0123456789"
    _raw, asset = _manifest(body)

    class _Chunked(_Response):
        def __init__(self):
            super().__init__(body, url=asset.url)
            self.calls = 0

        def read(self, _limit=-1):
            self.calls += 1
            if self.calls == 1:
                return body[:4]
            return body[4:]

    service = UpdateService(tmp_path, fetcher=lambda request: _Chunked())
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(InterruptedError):
        service.download(asset, cancel=cancel)
    assert (tmp_path / "updates" / (asset.name + ".part")).exists()
    assert (tmp_path / "updates" / (asset.name + ".part.json")).exists()


def test_download_transport_failure_preserves_resume_state(tmp_path: Path) -> None:
    body = b"0123456789"
    _raw, asset = _manifest(body)
    service = UpdateService(tmp_path, fetcher=lambda request: (_ for _ in ()).throw(OSError("offline")))
    service.update_dir.mkdir(parents=True)
    part = service.update_dir / (asset.name + ".part")
    part.write_bytes(body[:4])

    with pytest.raises(ConnectionError):
        service.download(asset)

    assert part.read_bytes() == body[:4]
    assert (tmp_path / "updates" / (asset.name + ".part.json")).exists()
    assert service.status().state == "download_failed"


def test_static_manifest_dictionary_and_cdn_fallback_are_supported(tmp_path: Path) -> None:
    body = b"installer"
    digest = hashlib.sha256(body).hexdigest()
    raw = {
        "version": "v2.0.0",
        "html_url": "https://github.com/MerZlin/dsh-pet-indesktop/releases/tag/v2.0.0",
        "assets": {
            "petcore-setup.exe": {
                "urls": [
                    "https://github.com/MerZlin/dsh-pet-indesktop/releases/download/v2.0.0/petcore-setup.exe",
                    "https://cdn.jsdelivr.net/gh/MerZlin/dsh-pet-indesktop@main/petcore-setup.exe",
                ],
                "size": len(body),
                "sha256": digest,
            }
        },
    }
    parsed = parse_manifest(raw)
    assert parsed.version == "2.0.0"
    assert parsed.assets[0].candidate_urls()[1].startswith("https://cdn.jsdelivr.net/")

    calls = []
    payload = json.dumps(raw).encode()

    def fetch(request):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise OSError("primary unavailable")
        return _Response(payload, url=calls[-1])

    service = UpdateService(
        tmp_path,
        current_version="1.0.0",
        fetcher=fetch,
        fallback_manifest_urls=("https://cdn.jsdelivr.net/gh/MerZlin/dsh-pet-indesktop@main/update.json",),
    )
    result = service.check(force=True)
    assert result.ok is True
    assert result.state == "available"
    assert calls == [service.manifest_url, service.fallback_manifest_urls[0]]


def test_download_tries_trusted_asset_mirror_after_transport_failure(tmp_path: Path) -> None:
    body = b"mirror-installer"
    digest = hashlib.sha256(body).hexdigest()
    primary = "https://github.com/example/petcore-setup.exe"
    mirror = "https://cdn.jsdelivr.net/gh/example/petcore-setup.exe"
    asset = UpdateAsset("petcore-setup.exe", primary, len(body), digest, urls=(primary, mirror))
    calls: list[str] = []

    def fetch(request):
        calls.append(request.full_url)
        if request.full_url == primary:
            raise OSError("primary unavailable")
        return _Response(body, url=mirror)

    service = UpdateService(tmp_path, fetcher=fetch)
    result = service.download(asset)
    assert result.read_bytes() == body
    assert calls == [primary, mirror]
    assert service.status().state == "downloaded"


def test_update_install_is_source_safe_and_frozen_windows_only(tmp_path: Path) -> None:
    package = tmp_path / "updates" / "petcore-setup.exe"
    package.parent.mkdir()
    package.write_bytes(b"candidate")

    source_service = UpdateService(tmp_path / "source", platform="windows", frozen=False)
    source_result = source_service.install(package)
    assert source_result.state == "unsupported_runtime"

    launched: list[Path] = []
    frozen_service = UpdateService(
        tmp_path / "frozen",
        platform="windows",
        frozen=True,
        launcher=launched.append,
    )
    frozen_package = tmp_path / "frozen" / "updates" / package.name
    frozen_package.parent.mkdir(parents=True)
    frozen_package.write_bytes(b"candidate")
    frozen_service._status = UpdateResult(True, "downloaded", path=frozen_package)
    result = frozen_service.install(frozen_package)
    assert result.ok is True
    assert result.state == "installer_started"
    assert launched == [frozen_package]
