from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..net.http import is_https_url


@dataclass(frozen=True, slots=True)
class UpdateAsset:
    name: str
    url: str
    size: int
    sha256: str
    platform: str = "windows"
    architecture: str = "x64"
    variant: str = "installer"
    kind: str = "installer"
    urls: tuple[str, ...] = ()

    def candidate_urls(self) -> tuple[str, ...]:
        """返回按发布者顺序去重后的可信候选 URL。"""
        values = self.urls or (self.url,)
        return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


@dataclass(frozen=True, slots=True)
class UpdateManifest:
    version: str
    release_url: str
    notes: str
    assets: tuple[UpdateAsset, ...]


@dataclass(frozen=True, slots=True)
class UpdateResult:
    ok: bool
    state: str
    message: str = ""
    version: str = ""
    path: Path | None = None
    manifest: UpdateManifest | None = None


def _clean_sha(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return text if re.fullmatch(r"[0-9a-f]{64}", text) else ""


def _asset_from_dict(raw: Any, *, fallback_name: str = "") -> UpdateAsset | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or raw.get("fileName") or fallback_name or "").strip()[:160]
    explicit_urls = raw.get("urls") or raw.get("mirrors")
    raw_urls = explicit_urls or raw.get("url") or raw.get("browser_download_url")
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    if not isinstance(raw_urls, (list, tuple)):
        raw_urls = []
    parsed_urls = tuple(str(url).strip() for url in raw_urls if str(url).strip())
    url = str(raw.get("url") or raw.get("browser_download_url") or (parsed_urls[0] if parsed_urls else "")).strip()
    # Keep the legacy single-url value structurally equal to UpdateAsset created
    # by older callers; candidate_urls() still exposes it for validation/download.
    urls = parsed_urls if explicit_urls else ()
    try:
        size = int(raw.get("size"))
    except (TypeError, ValueError):
        size = 0
    digest = _clean_sha(raw.get("sha256") or raw.get("digest"))
    if not name or not _safe_asset_name(name) or not url or size <= 0 or not digest:
        return None
    if not any(is_https_url(candidate) for candidate in (url, *urls)):
        return None
    return UpdateAsset(
        name=name,
        url=url,
        size=size,
        sha256=digest,
        platform=_normalize_platform(raw.get("platform") or "windows"),
        architecture=_normalize_architecture(raw.get("architecture") or raw.get("arch") or "x64"),
        variant=str(raw.get("variant") or "installer").strip().lower(),
        kind=str(raw.get("kind") or "installer").strip().lower(),
        urls=urls,
    )


def _safe_asset_name(name: str) -> bool:
    """更新资产只能落在 updates/ 根目录，不能借文件名逃逸。"""
    path = PurePosixPath(str(name).replace("\\", "/"))
    return (
        path.name == str(name).replace("\\", "/")
        and path.name not in {"", ".", ".."}
        and not path.is_absolute()
        and ".." not in path.parts
    )


def _normalize_platform(value: Any) -> str:
    text = str(value or "").strip().lower()
    return {"win32": "windows", "win": "windows", "darwin": "macos", "mac": "macos"}.get(text, text)


def _normalize_architecture(value: Any) -> str:
    text = str(value or "").strip().lower()
    return {
        "amd64": "x64",
        "x86_64": "x64",
        "x86-64": "x64",
        "x86": "x86",
        "i386": "x86",
        "i686": "x86",
        "aarch64": "arm64",
    }.get(text, text)


def parse_manifest(raw: Any) -> UpdateManifest:
    """解析静态 manifest 或 GitHub Release JSON。

    接受结构化 ``assets`` 列表，也兼容旧发布手册中 ``name -> {urls,...}``
    的静态字典格式。没有摘要的 Release 资产仍不会成为可信下载资产。
    """
    if not isinstance(raw, dict):
        raise ValueError("update manifest must be an object")
    version = str(raw.get("version") or raw.get("tag_name") or "").strip()
    if version.startswith(("v", "V")):
        version = version[1:]
    release_url = str(raw.get("release_url") or raw.get("html_url") or "").strip()
    notes = str(raw.get("notes") or raw.get("body") or "")[:4000]
    assets_raw = raw.get("assets")
    if assets_raw is None:
        assets_raw = raw.get("artifacts")
    assets: list[UpdateAsset] = []
    if isinstance(assets_raw, dict):
        iterable = (
            dict(value, name=str(value.get("name") or value.get("fileName") or name))
            if isinstance(value, dict)
            else {"name": name, "url": value}
            for name, value in assets_raw.items()
        )
    else:
        iterable = assets_raw or ()
    for item in iterable:
        asset = _asset_from_dict(item)
        if asset is not None:
            assets.append(asset)
    if not version or not release_url or not is_https_url(release_url):
        raise ValueError("update manifest has invalid version or release_url")
    return UpdateManifest(version, release_url, notes, tuple(assets))


def _version_key(value: str) -> tuple[tuple[int, ...], int, str]:
    text = str(value or "").strip().lstrip("v")
    base, _, suffix = text.partition("-")
    numbers = tuple(int(item) for item in re.findall(r"\d+", base)) or (0,)
    return numbers, 1 if not suffix else 0, suffix


def compare_versions(left: str, right: str) -> int:
    a, b = _version_key(left), _version_key(right)
    return (a > b) - (a < b)


#: 状态码 → 中文短标签（界面文案不直接外露内部状态码）。
STATE_LABELS: dict[str, str] = {
    "idle": "未检查",
    "checking": "检查中",
    "available": "有新版本",
    "up_to_date": "已是最新版本",
    "check_failed": "检查失败",
    "downloading": "下载中",
    "downloaded": "已下载",
    "download_failed": "下载失败",
    "installer_started": "安装器已启动",
    "installer_failed": "安装器启动失败",
    "unsupported_runtime": "当前运行方式不支持自动更新",
    "invalid_package": "更新包无效",
    "cancelled": "已取消",
}


def describe_state(state: str) -> str:
    return STATE_LABELS.get(str(state or ""), "更新状态未知")


__all__ = [
    "STATE_LABELS",
    "UpdateAsset",
    "UpdateManifest",
    "UpdateResult",
    "compare_versions",
    "describe_state",
    "parse_manifest",
]
