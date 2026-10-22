"""歌词：LRC 解析、两源取词、磁盘缓存（纯逻辑 + ``HttpPort``，无 Qt）。

口径沿用主分支 ``pet/music_lyric.py`` 的结论（本模块不 import ``pet.*``，只搬逻辑）：

- **两个公开源**，按匹配质量排序：网易云（中文曲库，搜索 + 歌词两跳）→ 酷狗
  （同样两跳）。命中即返回；**失败不重试**（一首歌最多一轮）。
- **首选直连**：``HttpRequest.prefer_direct=True``。2026-09-22 实机事故里系统代理把
  三个歌词源拖到 20~41 秒，全部超过超时，于是每首未缓存曲目都以「0 行」收场。
  路线切换（最多一次、只对传输失败或 500/502/504）由 ``HttpPort`` 实现，mod 只声明
  「国内源直连」；404/429/503 与带 ``Retry-After`` 的响应不会换路，也不在这里重发。
- **响应体 ≤ 2 MB**：``HttpRequest.max_bytes`` 由 core 强制执行。
- **纯音乐**：平台对没有词的曲子会给一句占位文案（``纯音乐，请欣赏`` /
  ``instrumental``），必须识别出来，否则会被当成唯一一句歌词、还会放起唱歌动画。
- **缓存**：``storage.data_dir("media.music")/lyrics`` 下按 ``sha1(title|artist)``
  一到一曲一个 JSON，条目数超上限按修改时间淘汰最旧的。
- **不写日志**：歌词 URL、代理地址、响应体一律不进日志（调用方也没给日志出口）。

``parse_lrc`` / ``line_at`` / ``looks_instrumental`` 不依赖端口，可独立单测。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from petcore.contracts.http import HttpError, HttpRequest

#: 单次取词的默认预算（秒）；两个源共享同一份截止时刻，不会叠加成两倍。
DEFAULT_TIMEOUT = 8.0
#: 单个响应体的硬上限（字节）。
MAX_BYTES = 2_000_000
#: 磁盘缓存条目上限的默认值。
CACHE_LIMIT = 80
#: 剩余预算低于该值就不再发请求（注定来不及的那发只会白占连接）。
MIN_ATTEMPT_BUDGET = 0.25
#: 缓存格式版本：解析口径变更时可据此作废旧条目。
CACHE_VERSION = 1

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 形如 [mm:ss.xx] / [mm:ss:xx] / [mm:ss]，可能一行多个。
_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# 只有标签、没有时间戳的行，如 [ti:歌名] —— 按 LRC 规范跳过。
_TAG_RE = re.compile(r"^\[[a-zA-Z#]+:[^\]]*\]\s*$")
# [offset:±毫秒] 需要叠加到所有时间点上。
_OFFSET_RE = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)

# 多歌手分隔符：酷狗报「、」、歌词源多写「/」，feat./ft. 见英文曲库。
_ARTIST_SEP_RE = re.compile(r"\s*(?:[、/／&×,，;；]|\bfeat\b\.?|\bft\b\.?)\s*", re.IGNORECASE)

# 各平台给"纯音乐"的占位文案。只匹配**整句占位语**，不匹配裸关键词：
# 真歌词里完全可能出现"纯音乐"三个字。
_INSTRUMENTAL_MARKERS = (
    "纯音乐，请欣赏",
    "纯音乐,请欣赏",
    "没有填词的纯音乐",
    "此歌曲为没有填词",
    "该歌曲为纯音乐",
    "暂无歌词",
    "无歌词",
    "instrumental",
    "no lyrics",
)


@dataclass(frozen=True, slots=True)
class LyricLine:
    """一行带时间戳的歌词。"""

    at: float
    text: str


@dataclass(frozen=True, slots=True)
class Lyrics:
    """一次取词的结果。

    ``instrumental=True`` 表示**纯音乐**：曲目本身没有歌词（配乐 / OST / 演奏曲）。
    调用方据此不显示歌词、也不播唱歌动画。``source`` 是命中的源名（诊断用）。
    """

    lines: tuple[LyricLine, ...] = ()
    instrumental: bool = False
    source: str = ""

    def __bool__(self) -> bool:
        # 纯音乐（无行、instrumental=True）也是有效结果，否则缓存永远读不中。
        return bool(self.lines) or self.instrumental


class LyricsError(RuntimeError):
    """两个源都没取到可用的歌词；``str()`` 是给用户看的原因（点名每个源）。"""


# ---------------------------------------------------------------- LRC 解析


def _parse_stamp(minutes: str, seconds: str, frac: str | None) -> float:
    value = int(minutes) * 60 + int(seconds)
    if frac:
        # 两位是厘秒、三位是毫秒，一位按十分之一秒处理。
        value += int(frac) / (10 ** len(frac))
    return value


def parse_lrc(text: str) -> tuple[LyricLine, ...]:
    """把 LRC 文本解析成按时间排序的歌词行。

    - 跳过不含时间戳的标签行（``[ti:]`` / ``[ar:]`` / ``[by:]`` 等）与无法解析的行；
    - 一行多个时间戳（``[00:01][00:05]同一句``）展开成多条；
    - 应用 ``[offset:]``（毫秒）；
    - 保留空文本行（间奏），由调用方决定要不要显示。
    """
    offset_sec = 0.0
    match = _OFFSET_RE.search(text or "")
    if match:
        try:
            offset_sec = int(match.group(1)) / 1000.0
        except ValueError:
            offset_sec = 0.0

    lines: list[LyricLine] = []
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        stamps = list(_TIME_RE.finditer(stripped))
        if not stamps or _TAG_RE.match(stripped):
            continue
        body = stripped[stamps[-1].end():].strip()
        for stamp in stamps:
            at = _parse_stamp(stamp.group(1), stamp.group(2), stamp.group(3)) + offset_sec
            lines.append(LyricLine(at=max(0.0, at), text=body))
    lines.sort(key=lambda item: item.at)
    return tuple(lines)


def line_at(
    lines: tuple[LyricLine, ...] | list[LyricLine],
    position: float | None,
    *,
    lead: float = 0.0,
    offset: float = 0.0,
) -> int:
    """返回该位置对应（最后一个不晚于它）的歌词下标；无歌词/位置未知返回 -1。

    ``lead`` 是提前量（秒，正值让歌词早点出现），``offset`` 是用户用菜单
    「歌词对齐」调的手动偏移（同样是正值让歌词提前）。两者都只改比较基准，
    不改行本身的时间戳。
    """
    if position is None or not lines:
        return -1
    probe = float(position) + float(lead) + float(offset)
    low, high = 0, len(lines) - 1
    found = -1
    while low <= high:
        mid = (low + high) // 2
        if lines[mid].at <= probe:
            found = mid
            low = mid + 1
        else:
            high = mid - 1
    return found


def line_duration_ms(
    lines: tuple[LyricLine, ...] | list[LyricLine],
    index: int,
    *,
    default: int = 3000,
    minimum: int = 2000,
    maximum: int = 6000,
) -> int:
    """一句歌词的气泡时长：到下一句的间隔（夹在 2~6 秒，最后一句用默认值）。"""
    if not (0 <= index < len(lines)):
        return default
    if index + 1 >= len(lines):
        return default
    gap = float(lines[index + 1].at) - float(lines[index].at)
    if gap <= 0:
        return minimum
    return int(max(minimum, min(maximum, gap * 1000)))


def looks_instrumental(lines: tuple[LyricLine, ...] | list[LyricLine]) -> bool:
    """这些"歌词"是否只是纯音乐占位文案（整首只有一两句、且全部命中）。"""
    texts = [str(line.text or "").strip().lower() for line in lines]
    texts = [text for text in texts if text]
    if not texts or len(texts) > 3:
        return False
    return all(
        any(marker in text for marker in _INSTRUMENTAL_MARKERS) for text in texts
    )


def _lyrics_from_text(text: str, source: str) -> Lyrics | None:
    lines = parse_lrc(text)
    if not lines:
        return None
    if looks_instrumental(lines):
        return Lyrics(instrumental=True, source=source)
    return Lyrics(lines=lines, source=source)


# ---------------------------------------------------------------- 缓存


def cache_key(title: str, artist: str) -> str:
    """``sha1(title|artist)``（归一小写）——缓存文件名。"""
    raw = f"{str(title or '').strip().lower()}|{str(artist or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class LyricsCache:
    """磁盘缓存：一到一曲一个 JSON，条目数超上限按修改时间淘汰最旧的。

    ``directory=None`` 时什么也不做（测试或没有存储端口的环境）。
    """

    def __init__(self, directory: Path | str | None = None, limit: int = CACHE_LIMIT):
        self.directory = Path(directory) if directory is not None else None
        self.limit = max(1, int(limit))

    def path_for(self, title: str, artist: str) -> Path | None:
        if self.directory is None:
            return None
        return self.directory / f"{cache_key(title, artist)}.json"

    def get(self, title: str, artist: str) -> Lyrics | None:
        path = self.path_for(title, artist)
        if path is None:
            return None
        try:
            if not path.is_file():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("v") != CACHE_VERSION:
                return None
            lines = tuple(
                LyricLine(at=float(item[0]), text=str(item[1]))
                for item in data.get("lines") or []
            )
            instrumental = bool(data.get("instrumental"))
            if not lines and not instrumental:
                return None
            return Lyrics(
                lines=lines, instrumental=instrumental, source=str(data.get("source") or "")
            )
        except Exception:
            return None

    def put(self, title: str, artist: str, lyrics: Lyrics) -> None:
        path = self.path_for(title, artist)
        if path is None or not lyrics:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "v": CACHE_VERSION,
                        "title": title,
                        "artist": artist,
                        "instrumental": bool(lyrics.instrumental),
                        "source": lyrics.source,
                        "lines": [[line.at, line.text] for line in lyrics.lines],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            return
        self.prune()

    def prune(self) -> None:
        """条目超上限时删掉最旧的若干条（LRU 近似），失败不影响取词。"""
        if self.directory is None:
            return
        try:
            entries = [path for path in self.directory.glob("*.json") if path.is_file()]
            if len(entries) <= self.limit:
                return
            entries.sort(key=lambda item: item.stat().st_mtime)
            for stale in entries[: len(entries) - self.limit]:
                try:
                    stale.unlink()
                except OSError:
                    continue
        except Exception:
            return


# ---------------------------------------------------------------- 取数


def describe_error(exc: BaseException) -> str:
    """把 ``HttpError`` 的分类翻成用户可读的短句（不带 URL / 代理 / 响应体）。"""
    reason = str(getattr(exc, "reason", "") or "network")
    status = int(getattr(exc, "status", 0) or 0)
    if reason == "timeout":
        return "请求超时"
    if reason == "rate_limit":
        return "被限流" + (f"（HTTP {status}）" if status else "")
    if reason == "auth":
        return "需要登录" + (f"（HTTP {status}）" if status else "")
    if status:
        return f"HTTP {status}"
    if reason == "protocol":
        return "响应格式不对"
    return "网络连接失败"


def _get_json(
    http,
    url: str,
    params: tuple[tuple[str, str], ...],
    *,
    timeout: float,
    referer: str = "",
):
    """GET 一个 JSON 接口；非 2xx / 太大 / 解析失败都抛 ``HttpError``。"""
    headers: tuple[tuple[str, str], ...] = (("User-Agent", _UA),)
    if referer:
        headers += (("Referer", referer),)
    response = http.request(
        HttpRequest(
            url=url,
            params=tuple(params),
            headers=headers,
            timeout=max(MIN_ATTEMPT_BUDGET, float(timeout)),
            prefer_direct=True,
            max_bytes=MAX_BYTES,
        )
    )
    status = int(getattr(response, "status", 0) or 0)
    body = bytes(getattr(response, "body", b"") or b"")
    if len(body) > MAX_BYTES:
        raise HttpError("protocol", message="歌词响应超出大小上限")
    if status >= 400 or status == 0:
        raise HttpError("protocol", status=status)
    try:
        return json.loads(response.text)
    except ValueError:
        raise HttpError("protocol", message="歌词响应不是 JSON") from None


def _name_matches(candidate: str, wanted: str) -> bool:
    """歌手名匹配：大小写/空白不敏感，允许子串；两侧都是多歌手时逐段相等比对。"""
    a = re.sub(r"\s+", "", str(candidate or "").lower())
    b = re.sub(r"\s+", "", str(wanted or "").lower())
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    parts_a = [re.sub(r"\s+", "", part) for part in _ARTIST_SEP_RE.split(str(candidate or "").lower())]
    parts_b = [re.sub(r"\s+", "", part) for part in _ARTIST_SEP_RE.split(str(wanted or "").lower())]
    parts_a = [part for part in parts_a if part]
    parts_b = [part for part in parts_b if part]
    if len(parts_a) < 2 or len(parts_b) < 2:
        return False
    return any(pa == pb for pa in parts_a for pb in parts_b)


def _fetch_netease(http, title: str, artist: str, *, timeout: float) -> Lyrics | None:
    """网易云：搜索（``cloudsearch``）→ 歌词（``song/lyric``）。"""
    query = " ".join(part for part in (title, artist) if part)
    search = _get_json(
        http,
        "https://music.163.com/api/cloudsearch/pc",
        (("s", query), ("type", "1"), ("offset", "0"), ("limit", "10")),
        timeout=timeout,
        referer="https://music.163.com/",
    )
    songs = ((search.get("result") or {}).get("songs") or []) if isinstance(search, dict) else []
    song_id = None
    for song in songs:
        if not isinstance(song, dict):
            continue
        singers = "/".join(
            str(item.get("name") or "")
            for item in (song.get("ar") or song.get("artists") or [])
            if isinstance(item, dict)
        )
        if not artist or _name_matches(singers, artist):
            song_id = song.get("id")
            break
    if song_id is None:
        return None
    payload = _get_json(
        http,
        "https://music.163.com/api/song/lyric",
        (("id", str(song_id)), ("lv", "-1"), ("kv", "-1"), ("tv", "-1")),
        timeout=timeout,
        referer="https://music.163.com/",
    )
    if not isinstance(payload, dict):
        return None
    return _lyrics_from_text(str((payload.get("lrc") or {}).get("lyric") or ""), "网易云")


def _fetch_kugou(http, title: str, artist: str, *, timeout: float) -> Lyrics | None:
    """酷狗：搜索（``krcs/search``）→ 下载（``lyrics/download``，正文 base64）。"""
    keyword = " - ".join(part for part in (title, artist) if part)
    search = _get_json(
        http,
        "https://krcs.kugou.com/search",
        (
            ("ver", "1"),
            ("man", "yes"),
            ("client", "mobi"),
            ("keyword", keyword),
        ),
        timeout=timeout,
        referer="https://www.kugou.com/",
    )
    candidates = search.get("candidates") if isinstance(search, dict) else None
    if not candidates:
        return None
    lyric_id = accesskey = None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if artist and item.get("singer") and not _name_matches(str(item.get("singer")), artist):
            continue
        if item.get("id") is None or not item.get("accesskey"):
            continue
        lyric_id = item.get("id")
        accesskey = item.get("accesskey")
        break
    if lyric_id is None or accesskey is None:
        return None
    payload = _get_json(
        http,
        "https://lyrics.kugou.com/download",
        (
            ("id", str(lyric_id)),
            ("accesskey", str(accesskey)),
            ("fmt", "lrc"),
            ("charset", "utf8"),
            ("client", "pc"),
            ("ver", "1"),
        ),
        timeout=timeout,
        referer="https://www.kugou.com/",
    )
    content = str((payload or {}).get("content") or "") if isinstance(payload, dict) else ""
    if not content:
        return None
    try:
        body = base64.b64decode(content).decode("utf-8", "replace")
    except Exception:
        return None
    return _lyrics_from_text(body, "酷狗")


#: 歌词源，按匹配质量排序（靠前优先）。每个源最多两跳，失败直接换下一个。
SOURCES: tuple[tuple[str, object], ...] = (
    ("网易云", _fetch_netease),
    ("酷狗", _fetch_kugou),
)


def fetch_lyrics(
    http,
    title: str,
    artist: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    cache: LyricsCache | None = None,
) -> Lyrics:
    """取一首歌的歌词：缓存 → 网易云 → 酷狗；两源都失败抛 :class:`LyricsError`。

    一首歌最多一轮（**失败不重试**，不给后台加重复流量）。``timeout`` 是整次取词的
    预算，两个源共享同一份截止时刻：每个源只拿到剩余部分，因此源切换不会把总
    耗时翻倍。
    """
    title = str(title or "").strip()
    artist = str(artist or "").strip()
    if not title and not artist:
        raise LyricsError("没有歌名信息，无法取歌词。")

    if cache is not None:
        hit = cache.get(title, artist)
        if hit is not None:
            return hit

    deadline = time.monotonic() + max(1.0, float(timeout))
    reasons: list[str] = []
    for name, fetcher in SOURCES:
        remaining = deadline - time.monotonic()
        if remaining < MIN_ATTEMPT_BUDGET:
            reasons.append(f"{name}：时间预算不足")
            break
        try:
            found = fetcher(http, title, artist, timeout=remaining)  # type: ignore[operator]
        except HttpError as exc:
            reasons.append(f"{name}：{describe_error(exc)}")
            continue
        except (ValueError, KeyError, TypeError):
            reasons.append(f"{name}：响应格式不对")
            continue
        except Exception as exc:
            reasons.append(f"{name}：{describe_error(exc)}")
            continue
        if found is not None:
            if cache is not None:
                cache.put(title, artist, found)
            return found
        reasons.append(f"{name}：没有找到匹配的歌词")
    raise LyricsError("歌词获取失败：" + "；".join(reasons))
