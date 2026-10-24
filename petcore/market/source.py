"""索引源：有序备用源、内存 TTL、磁盘缓存与离线降级。

本模块不做任何网络请求；``fetch`` 由 :mod:`petcore.net.market` 注入。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .model import MarketIndex, normalize_index_url, parse_index_text

DEFAULT_INDEX_URLS = (
    "https://raw.githubusercontent.com/MerZlin/dsh-pet-extensions/main/index.json",
    "https://api.github.com/repos/MerZlin/dsh-pet-extensions/contents/index.json",
)
CACHE_FILE = "index-cache.json"
META_FILE = "index-cache.meta.json"
CACHE_TTL_SECONDS = 300.0
INDEX_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class IndexFetch:
    body: bytes
    etag: str = ""
    not_modified: bool = False


class IndexFetchError(RuntimeError):
    def __init__(self, message: str, url: str = ""):
        self.url = url
        super().__init__(message)


class IndexFetcher(Protocol):
    def fetch_index(self, url: str, *, etag: str = "", timeout: float = INDEX_TIMEOUT_SECONDS) -> IndexFetch:
        ...


@dataclass(frozen=True, slots=True)
class SourceResult:
    index: MarketIndex
    origin: str = ""
    fetched_at: float = 0.0
    stale: bool = False
    problems: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        if not self.origin:
            return "无可用索引"
        if self.stale:
            return f"索引可能过期（{self.origin}）"
        return self.origin


def _cache_paths(root: Path) -> tuple[Path, Path]:
    base = Path(root) / "market"
    return base / CACHE_FILE, base / META_FILE


def _read_meta(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


class MarketSource:
    def __init__(
        self,
        root: Path,
        fetch: IndexFetcher,
        *,
        urls: Sequence[str] = DEFAULT_INDEX_URLS,
        clock: Callable[[], float] = time.time,
        ttl: float = CACHE_TTL_SECONDS,
    ):
        self.root = Path(root)
        self.fetch = fetch
        self.base_urls = tuple(str(url) for url in urls if str(url).strip())
        self.clock = clock
        self.ttl = float(ttl)
        self._memory: SourceResult | None = None

    def urls(self, custom_url: str = "") -> tuple[str, ...]:
        custom = normalize_index_url(custom_url)
        if not custom:
            return self.base_urls
        if custom.lower().startswith("file://"):
            # 显式本地索引 = 离线选择：失败就报错，不偷偷回落到公网源。
            return (custom,)
        return tuple(dict.fromkeys((custom, *self.base_urls)))

    def load(self, *, custom_url: str = "", force: bool = False) -> SourceResult:
        problems: list[str] = []
        now = self.clock()
        if not force and self._memory is not None and now - self._memory.fetched_at < self.ttl:
            return self._memory

        cache_path, meta_path = _cache_paths(self.root)
        meta = _read_meta(meta_path)
        cache_body = self._read_cache(cache_path, problems)

        for url in self.urls(custom_url):
            etag = str(meta.get("etag") or "") if meta.get("url") == url else ""
            try:
                fetched = self.fetch.fetch_index(
                    url, etag=etag, timeout=INDEX_TIMEOUT_SECONDS
                )
            except IndexFetchError as exc:
                problems.append(f"{url}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - 任何传输失败都只换下一个源
                problems.append(f"{url}: {type(exc).__name__}: {exc}")
                continue

            if fetched.not_modified:
                if cache_body is None:
                    problems.append(f"{url}: 304 但没有可用的本地缓存")
                    continue
                parsed, parse_problems = parse_index_text(cache_body)
                if parsed is None:
                    problems.append(f"{url}: 本地缓存无法解析")
                    continue
                problems.extend(parse_problems)
                result = SourceResult(
                    index=parsed,
                    origin=url,
                    fetched_at=now,
                    stale=False,
                    problems=tuple(problems),
                )
                self._remember(result, cache_path, meta_path, url, etag, cache_body)
                return result

            text = fetched.body.decode("utf-8", errors="replace")
            parsed, parse_problems = parse_index_text(text)
            if parsed is None:
                problems.extend(parse_problems)
                problems.append(f"{url}: 索引内容无效")
                continue

            problems.extend(parse_problems)
            result = SourceResult(
                index=parsed,
                origin=url,
                fetched_at=now,
                stale=False,
                problems=tuple(problems),
            )
            self._remember(
                result, cache_path, meta_path, url, str(fetched.etag or ""), text
            )
            return result

        if cache_body is not None:
            parsed, parse_problems = parse_index_text(cache_body)
            if parsed is not None:
                problems.extend(parse_problems)
                problems.append("索引可能过期：所有索引源都不可用，正在使用本地缓存")
                result = SourceResult(
                    index=parsed,
                    origin=str(meta.get("url") or ""),
                    fetched_at=float(meta.get("fetched_at") or 0.0),
                    stale=True,
                    problems=tuple(problems),
                )
                self._memory = result
                return result
            problems.append("本地索引缓存无法解析")

        problems.append("没有可用的市场索引：所有索引源都不可用，且没有本地缓存")
        result = SourceResult(
            index=MarketIndex(packages=()), stale=True, problems=tuple(problems)
        )
        self._memory = result
        return result

    def _read_cache(self, path: Path, problems: list[str]) -> str | None:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            problems.append(f"读取本地缓存失败：{exc}")
            return None
        if not text.strip():
            problems.append("本地索引缓存为空")
            return None
        return text

    def _remember(
        self,
        result: SourceResult,
        cache_path: Path,
        meta_path: Path,
        url: str,
        etag: str,
        body: str,
    ) -> None:
        self._memory = result
        payload = {
            "url": url,
            "etag": etag,
            "fetched_at": result.fetched_at,
            "generated_at": result.index.generated_at,
        }
        try:
            _write_atomic(cache_path, body if body.endswith("\n") else body + "\n")
            _write_atomic(
                meta_path,
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as exc:
            # 缓存写不进去不影响本次结果，只丢下一次的离线能力。
            result = SourceResult(
                index=result.index,
                origin=result.origin,
                fetched_at=result.fetched_at,
                stale=result.stale,
                problems=(
                    *result.problems,
                    f"写入本地索引缓存失败：{exc}",
                ),
            )
            self._memory = result
