"""更新安装的信任锚：安装包必须与清单登记条目一致。

对应审计 AUD-02——侧车（`.verify.json`）与包同目录、同一用户可写，它不能自证；
真正的锚是下载时校验过的那份清单。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from petcore.update import UpdateAsset, UpdateManifest, UpdateService


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self, _limit: int = -1) -> bytes:
        value, self._body = self._body, b""
        return value

    def geturl(self) -> str:
        return "https://api.github.com/repos/example/releases/latest"

    def close(self) -> None:
        return None


def _manifest_payload(data: bytes, *, name: str = "petcore-setup.exe") -> dict:
    return {
        "version": "9.0.0",
        "release_url": "https://github.com/example/releases/9.0.0",
        "assets": [
            {
                "name": name,
                "url": f"https://github.com/example/{name}",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "platform": "windows",
                "architecture": "x64",
                "variant": "installer",
            }
        ],
    }


def _service(root: Path, launched: list[Path]) -> UpdateService:
    return UpdateService(
        root,
        platform="windows",
        frozen=True,
        launcher=lambda path: launched.append(Path(path)),
    )


def _stage(root: Path, payload: bytes, *, name: str = "petcore-setup.exe") -> Path:
    updates = root / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    package = updates / name
    package.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (updates / f"{name}.verify.json").write_text(
        json.dumps({"name": name, "size": len(payload), "sha256": digest}),
        encoding="utf-8",
    )
    return package


def _checked_service(root: Path, payload: bytes, launched: list[Path]) -> UpdateService:
    service = _service(root, launched)
    body = json.dumps(_manifest_payload(payload)).encode()
    service.fetcher = lambda request: _Response(body)  # type: ignore[assignment]
    result = service.check(force=True)
    assert result.ok, result.message
    return service


def test_matching_package_installs(tmp_path: Path) -> None:
    payload = b"installer-bytes"
    launched: list[Path] = []
    service = _checked_service(tmp_path, payload, launched)
    package = _stage(tmp_path, payload)
    result = service.install(package)
    assert result.ok is True, result.message
    assert launched == [package]


def test_forged_package_and_sidecar_are_rejected(tmp_path: Path) -> None:
    """换包 + 同步改侧车：侧车自洽也不再放行，因为清单里登记的是旧摘要。"""
    good = b"installer-bytes"
    evil = b"EVIL-PAYLOAD"
    launched: list[Path] = []
    service = _checked_service(tmp_path, good, launched)
    package = _stage(tmp_path, evil)
    result = service.install(package)
    assert result.ok is False
    assert result.state == "invalid_package"
    assert launched == []


def test_package_name_must_match_the_manifest(tmp_path: Path) -> None:
    payload = b"installer-bytes"
    launched: list[Path] = []
    service = _checked_service(tmp_path, payload, launched)
    package = _stage(tmp_path, payload, name="other-setup.exe")
    result = service.install(package)
    assert result.ok is False
    assert result.state == "invalid_package"
    assert launched == []


def test_missing_manifest_rejects_installation(tmp_path: Path) -> None:
    payload = b"installer-bytes"
    launched: list[Path] = []
    service = _service(tmp_path, launched)
    package = _stage(tmp_path, payload)
    result = service.install(package)
    assert result.ok is False
    assert result.state == "invalid_package"
    assert launched == []


def test_manifest_is_recovered_from_cache_after_restart(tmp_path: Path) -> None:
    """重启后没有内存里的清单，但下载时写下的缓存清单能还原判定。"""
    payload = b"installer-bytes"
    launched: list[Path] = []
    first = _checked_service(tmp_path, payload, launched)
    assert first.manifest is not None
    package = _stage(tmp_path, payload)

    restarted = _service(tmp_path, launched)
    assert restarted.manifest is None
    result = restarted.install(package)
    assert result.ok is True, result.message
    assert launched == [package]


def test_manifest_without_matching_asset_is_rejected(tmp_path: Path) -> None:
    payload = b"installer-bytes"
    launched: list[Path] = []
    service = _service(tmp_path, launched)
    service._manifest = UpdateManifest(  # noqa: SLF001 - 直接构造一个"没有本平台资产"的清单
        version="9.0.0",
        release_url="https://github.com/example/releases/9.0.0",
        notes="",
        assets=(UpdateAsset("linux.tar.gz", "https://github.com/example/linux.tar.gz", 10, "a" * 64, platform="linux", variant="portable", kind="package"),),
    )
    package = _stage(tmp_path, payload)
    result = service.install(package)
    assert result.ok is False
    assert result.state == "invalid_package"
