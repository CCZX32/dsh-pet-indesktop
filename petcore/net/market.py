"""市场索引与 artifact 的唯一 HTTP 实现。

架构约束：联网库只允许出现在 ``net/``。``market/`` 通过本模块注入的
``IndexFetcher`` / ``ArtifactFetcher`` 协议使用它，不直接 import urllib。
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .. import __version__
from ..net import errors
from ..net import http
from ..market.errors import TransferCancelled
from ..market.source import IndexFetch, IndexFetchError

MAX_INDEX_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
USER_AGENT = f"dsh-pet-core/{__version__}"

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


def _decode_github_contents(body: bytes) -> bytes:
    try:
        raw: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return body
    if not isinstance(raw, dict):
        return body
    if raw.get("encoding") != "base64" or not isinstance(raw.get("content"), str):
        return body
    try:
        return base64.b64decode(raw["content"])
    except (ValueError, TypeError):
        return body


def _header(response, name: str) -> str:
    try:
        value = response.headers.get(name)
    except AttributeError:
        return ""
    return str(value or "")


def fetch_index(
    url: str,
    *,
    etag: str = "",
    timeout: float = 8.0,
    opener=None,
) -> IndexFetch:
    """读取索引；304 返回 ``not_modified``，任何传输失败抛 ``IndexFetchError``。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    request = urllib.request.Request(str(url), headers=headers)
    try:
        response = http.urlopen(request, timeout=timeout, opener=opener)
    except urllib.error.HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) == 304:
            return IndexFetch(body=b"", not_modified=True)
        raise IndexFetchError(f"HTTP {exc.code}", str(url)) from exc
    except Exception as exc:  # noqa: BLE001 - 稳定分类由 IndexFetchError 承担
        raise IndexFetchError(type(exc).__name__, str(url)) from exc

    try:
        with response:
            body = response.read(MAX_INDEX_BYTES + 1)
            new_etag = _header(response, "ETag")
    except Exception as exc:  # noqa: BLE001
        raise IndexFetchError(f"读取失败：{type(exc).__name__}", str(url)) from exc
    if len(body) > MAX_INDEX_BYTES:
        raise IndexFetchError(f"索引超过 {MAX_INDEX_BYTES} 字节上限", str(url))
    return IndexFetch(body=_decode_github_contents(body), etag=new_etag)


def download_to(
    url: str,
    part_path: Path,
    *,
    expected_size: int | None = None,
    timeout: float = 15.0,
    chunk_size: int = CHUNK_BYTES,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
    opener=None,
) -> int:
    """下载到 ``.part``；已有内容时用 Range 续传。返回最终字节数。"""
    part_path = Path(part_path)
    part_path.parent.mkdir(parents=True, exist_ok=True)
    existing = part_path.stat().st_size if part_path.is_file() else 0

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(str(url), headers=headers)
    try:
        response = http.urlopen(request, timeout=timeout, opener=opener)
    except urllib.error.HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) == 416 and existing > 0:
            if expected_size is None or existing == expected_size:
                return existing
        raise errors.http_error(exc) from exc
    except errors.NetworkError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise errors.NetworkUnreachable(type(exc).__name__) from exc

    status = int(getattr(response, "status", 200) or 200)
    if status == 206 and existing > 0:
        mode = "ab"
        done = existing
    else:
        mode = "wb"
        done = 0
    total = int(expected_size or 0)
    if not total:
        length = _header(response, "Content-Length")
        try:
            total = done + int(length) if length else 0
        except ValueError:
            total = 0

    try:
        with response, part_path.open(mode) as stream:
            while True:
                if cancel is not None and cancel():
                    raise TransferCancelled("download cancelled")
                block = response.read(chunk_size)
                if not block:
                    break
                stream.write(block)
                done += len(block)
                if progress is not None:
                    progress(done, total)
    except TransferCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, OSError):
            raise
        raise errors.NetworkUnreachable(type(exc).__name__) from exc
    return done


class HttpFetcher:
    """把模块函数包成 market 层使用的协议对象（便于测试替换）。"""

    def fetch_index(
        self, url: str, *, etag: str = "", timeout: float = 8.0
    ) -> IndexFetch:
        return fetch_index(url, etag=etag, timeout=timeout)

    def download(
        self,
        url: str,
        part_path: Path,
        *,
        expected_size: int | None = None,
        timeout: float = 15.0,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
    ) -> int:
        return download_to(
            url,
            part_path,
            expected_size=expected_size,
            timeout=timeout,
            progress=progress,
            cancel=cancel,
        )
