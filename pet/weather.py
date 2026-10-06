# -*- coding: utf-8 -*-
"""天气取数：国内源优先 + 国外源兜底（纯逻辑，不依赖 Qt）。

**两个源，按顺序试，命中即返回**

1. **中国天气网**（`toy1.weather.com.cn` 城市检索 → `d1.weather.com.cn/sk_2d/<code>.html`
   实况）——国内源，一个接口就带齐温度 / 天气状况 / 风向风力 / 湿度 / 观测时间，
   城市名也是中文语境（实测「鹿城」直接命中 `101210710`）。
2. **open-meteo**（geocoding → forecast）——国外源兜底，走 WMO 天气码，中文文案
   由本模块的码表给出。

两源都失败抛 :class:`WeatherError`，消息里**点名两个源各自的失败原因**——气泡
照实说「天气获取失败」，绝不静默（见 ``docs/NETWORK-PROXY-AND-VPN-2026-09-22.md``
的教训：静默降级会让"功能坏了"变成唯一可见的现象）。

**网络出口：国内源直连，国外源跟随系统代理。** 决策依据见
:func:`_default_http` 与 ``docs/NETWORK-PROXY-AND-VPN-2026-09-22.md``：本机实测
中国天气网直连 0.08~0.46s、走系统代理 2.06~2.85s（慢 5~26 倍，且第一次点击就要
等两个请求），与歌词取词同一族问题；而 open-meteo 是海外端点，直连/代理实测相当，
对"只有代理能出网"的用户必须保留代理这条路。分流而不是全局绕代理，正是该文档
推荐的口径。

**超时与预算**：单请求 ``HTTP_TIMEOUT``，整次取数另有 ``TOTAL_BUDGET_SECONDS``
总预算（点击到冒泡的用户等待有上界）；每个请求的超时取「剩余预算」与单请求超时
的较小值。

**测试边界**：HTTP 出口通过 ``http=`` 注入（签名 ``(url, headers, *, use_proxy,
timeout) -> str``），单测不真发外网请求。
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

#: 单次 HTTP 请求超时（秒）。天气是"点一下看结果"的交互，宁可失败也不要挂住。
HTTP_TIMEOUT = 6.0
#: 一次取数的总预算（秒）：源 A 最多 2 个请求、源 B 最多 2 个请求，最坏 4×6=24s，
#: 用户等不了；超预算后直接按失败冒泡。
TOTAL_BUDGET_SECONDS = 15.0
#: 城市上限（issue #209 规格：12 个）。
MAX_CITIES = 12
#: 单个城市名的长度上限（防手改配置塞超长串撑爆菜单）。
MAX_CITY_NAME = 24

SOURCE_CN = "中国天气网"
SOURCE_OPEN_METEO = "open-meteo"

CITY_LIMIT_TEXT = f"最多只能有 {MAX_CITIES} 个城市"
CITY_EXISTS_TEXT = "这个城市已经在列表里了"
CITY_EMPTY_TEXT = "城市名不能为空"
NO_CITY_TEXT = "还没选天气城市：右键菜单 → 天气城市 → 添加城市…"

CN_SEARCH_URL = "http://toy1.weather.com.cn/search?cityname={query}"
CN_CURRENT_URL = "http://d1.weather.com.cn/sk_2d/{code}.html"
CN_REFERER = "http://www.weather.com.cn/"
OM_GEOCODE_URL = (
    "https://geocoding-api.open-meteo.com/v1/search"
    "?name={query}&count=1&language=zh&format=json"
)
OM_FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,"
    "relative_humidity_2m&timezone=auto"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 行政区/地名后缀：源 A 的城市检索对带后缀的名字**搜不到**（2026-10-07 实测
# 「鹿城区」返回空数组，而「鹿城」命中），所以查询前先剥后缀、原名命中不了再用
# 剥过的名字重试一次。顺序 = 从长到短，避免「自治区」被「区」先吃掉。
_CITY_SUFFIXES = (
    "维吾尔自治区", "壮族自治区", "回族自治区", "内蒙古自治区", "特别行政区",
    "自治区", "自治州", "自治县", "开发区", "高新区", "新区", "地区", "街道",
    "省", "市", "区", "县", "镇", "乡", "旗", "盟",
)

# WMO 天气码 → 中文（open-meteo 的 weather_code，即 WMO 4677 子集）。
_WMO_TEXT = {
    0: "晴", 1: "多云", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷阵雨", 96: "雷阵雨伴小冰雹", 99: "雷阵雨伴大冰雹",
}

# Beaufort 风级上界（km/h）：索引 = 级数。0→0级 … 12→12级。
_BEAUFORT_KMH = (1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118)


class WeatherError(RuntimeError):
    """取数失败（单源或两源都失败）。``failures`` = ((源名, 原因), ...)。"""

    def __init__(self, message: str, failures: tuple[tuple[str, str], ...] = ()) -> None:
        super().__init__(message)
        self.failures = failures


@dataclass(frozen=True)
class CityCandidate:
    """源 A 城市检索的一条候选（``code`` 是天气接口要的地区码）。"""

    code: str
    name: str
    region: str = ""


@dataclass(frozen=True)
class WeatherReading:
    """一次取数的结果（两个源统一成同一形状）。"""

    city: str
    condition: str
    temperature: str
    wind: str = ""
    humidity: str = ""
    source: str = ""
    observed_at: str = ""
    detail: str = ""

    def bubble_text(self) -> str:
        """气泡文案（单行：气泡渲染会把换行折成空格，见 speech_bubble_text）。"""
        head = " ".join(part for part in (self.city, self.condition, self.temperature) if part)
        extras = [part for part in (self.wind, f"湿度 {self.humidity}" if self.humidity else "") if part]
        if extras:
            head += "，" + "，".join(extras)
        return f"{head}（{self.source}）" if self.source else head


# ---------------------------------------------------------------- 城市名与列表
def normalize_city_name(raw) -> str:
    """城市名归一化：全角转半角、去空白、剥行政区后缀（「鹿城区」→「鹿城」）。

    剥成空串时保留原名（只有「市」「区」这种输入会走到），避免把用户输入
    退化成"没有城市"。
    """
    name = unicodedata.normalize("NFKC", str(raw or "")).strip()
    for suffix in _CITY_SUFFIXES:
        if len(name) > len(suffix) and name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def city_name_variants(raw) -> tuple[str, ...]:
    """查询用的候选名字：原名在前（「市中区」「三亚市」这类真名不能被剥坏），
    归一化名兜底。"""
    name = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not name:
        return ()
    normalized = normalize_city_name(name)
    return (name,) if normalized == name else (name, normalized)


def normalize_city_list(raw) -> list[str]:
    """城市列表清洗：逐项做城市名归一化（剥行政区后缀）、去空、去重、截断、上限 12。

    列表里存的是**归一化形式**（「鹿城区」存成「鹿城」），设置页/右键菜单/气泡
    三处显示才一致；带后缀的名字照样能取到数——源 A 的城市检索本身是模糊匹配，
    归一化后的名字（如「市中」）仍能命中「市中区」那条候选，取数侧另有
    ``city_name_variants`` 对**存量**带后缀的值兜底。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    cities: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = normalize_city_name(item)[:MAX_CITY_NAME]
        if name and name not in cities:
            cities.append(name)
        if len(cities) >= MAX_CITIES:
            break
    return cities


def current_city(config) -> str:
    """当前城市：``weather_city`` 优先，为空退回列表首项（列表非空时）。"""
    getter = getattr(config, "get", None)
    if callable(getter):
        selected = getter("weather_city", "") or ""
        listed = getter("weather_city_list", [])
    elif isinstance(config, dict):
        selected = config.get("weather_city", "") or ""
        listed = config.get("weather_city_list", [])
    else:
        return ""
    name = unicodedata.normalize("NFKC", str(selected)).strip()
    if name:
        return name
    cities = normalize_city_list(listed)
    return cities[0] if cities else ""


def add_city(cities, name) -> tuple[list[str], str]:
    """往列表加城市，返回 ``(新列表, 错误文案)``；错误时列表原样返回。"""
    current = normalize_city_list(cities)
    candidate = normalize_city_name(name)
    if not candidate:
        return current, CITY_EMPTY_TEXT
    if candidate in current:
        return current, CITY_EXISTS_TEXT
    if len(current) >= MAX_CITIES:
        return current, CITY_LIMIT_TEXT
    return current + [candidate], ""


def remove_city(cities, name, current: str = "") -> tuple[list[str], str]:
    """删城市，返回 ``(新列表, 新的当前城市)``。

    删掉的正好是当前城市时，当前切到剩下的第一个；列表空了则当前城市清空
    （而不是留一个不在列表里的悬空值）。
    """
    listed = normalize_city_list(cities)
    target = normalize_city_name(name)
    remaining = [city for city in listed if city != target]
    if remaining == listed:
        return listed, current or ""
    if normalize_city_name(current) != target:
        return remaining, current or ""
    return remaining, (remaining[0] if remaining else "")


# ---------------------------------------------------------------- 码表
def wmo_text(code) -> str:
    """WMO 天气码 → 中文；未知码返回「未知」（不猜、不空着）。"""
    try:
        return _WMO_TEXT.get(int(code), "未知")
    except (TypeError, ValueError):
        return "未知"


def wind_direction_text(degrees) -> str:
    """风向角度 → 八个方位；无角度返回空串。"""
    try:
        value = float(degrees) % 360.0
    except (TypeError, ValueError):
        return ""
    names = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
    return names[int((value + 22.5) // 45) % 8]


def beaufort_text(kmh) -> str:
    """风速 km/h → Beaufort 风级中文（「4级」）；无速度返回空串。"""
    try:
        value = max(0.0, float(kmh))
    except (TypeError, ValueError):
        return ""
    force = 0
    for index, upper in enumerate(_BEAUFORT_KMH):
        if value < upper:
            force = index
            break
    else:
        force = 12
    return f"{force}级"


def describe_error(exc: BaseException) -> str:
    """异常 → 一句中文原因（气泡/对话框里给用户看的那一种）。"""
    if isinstance(exc, (TimeoutError,)) or "timed out" in str(exc).lower():
        return "请求超时"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", "") or exc)
        return "请求超时" if "timed out" in reason.lower() else f"网络连接失败：{reason[:60]}"
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return "返回数据无效"
    return f"{type(exc).__name__}: {str(exc)[:60]}"


# ---------------------------------------------------------------- 响应解析
def parse_search_payload(text: str) -> list[CityCandidate]:
    """解析源 A 城市检索的响应 ``([{"ref":"code~...~名称~..."}])``。

    字段位（2026-10-07 实测）：``code~省~名称~拼音~城市~城市拼音~区号~邮编~缩写~省份``。
    末尾带 ``A`` 的地区码是景点（如 ``10102020001A``），会盖掉同名的真城市，剔除。
    """
    raw = str(text or "").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(raw[start: end + 1])
    except (ValueError, TypeError):
        return []
    candidates: list[CityCandidate] = []
    for item in items if isinstance(items, list) else ():
        ref = str(item.get("ref") or "") if isinstance(item, dict) else ""
        parts = ref.split("~")
        if len(parts) < 3:
            continue
        code = parts[0].strip()
        name = parts[2].strip()
        if not code or not name or code.endswith("A"):
            continue
        region = parts[-1].strip()
        candidates.append(CityCandidate(code=code, name=name, region=region))
    return candidates


def _match_rank(candidate: CityCandidate, query: str) -> int:
    names = [normalize_city_name(candidate.name)]
    parts = candidate.name.split()
    names.extend(normalize_city_name(part) for part in parts)
    for name in names:
        if name == query:
            return 0
        if name.startswith(query):
            return 1
        if query in name:
            return 2
    return 3


def pick_candidate(candidates, query) -> CityCandidate | None:
    """从候选里挑最匹配的一条：精确 > 前缀 > 包含；同档保持接口原顺序。"""
    target = normalize_city_name(query)
    if not target:
        return None
    best: tuple[int, int, CityCandidate] | None = None
    for index, candidate in enumerate(candidates):
        rank = _match_rank(candidate, target)
        if rank >= 3:
            continue
        key = (rank, index)
        if best is None or key < (best[0], best[1]):
            best = (rank, index, candidate)
    return best[2] if best is not None else None


def parse_cn_reading(text: str, fallback_city: str = "") -> WeatherReading:
    """解析源 A 实况响应（``var dataSK={...}``）。缺温度视为不可用。"""
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise WeatherError("返回数据无效")
    try:
        data = json.loads(raw[start: end + 1])
    except (ValueError, TypeError) as exc:
        raise WeatherError(f"返回数据无效：{describe_error(exc)}") from exc
    if not isinstance(data, dict):
        raise WeatherError("返回数据无效")
    temperature = str(data.get("temp") or "").strip()
    if not temperature:
        raise WeatherError("返回数据里没有温度")
    try:
        temperature = f"{float(temperature):.1f}℃"
    except (TypeError, ValueError) as exc:
        raise WeatherError("返回数据里没有温度") from exc
    wind_parts = [str(data.get("WD") or "").strip(), str(data.get("WS") or "").strip()]
    return WeatherReading(
        city=str(data.get("cityname") or "").strip() or str(fallback_city or "").strip(),
        condition=str(data.get("weather") or "").strip(),
        temperature=temperature,
        wind=" ".join(part for part in wind_parts if part),
        humidity=str(data.get("SD") or "").strip(),
        source=SOURCE_CN,
        observed_at=str(data.get("time") or "").strip(),
        detail=str(data.get("date") or "").strip(),
    )


def parse_open_meteo_reading(payload, city: str = "") -> WeatherReading:
    """解析源 B 实况（geocoding 选的坐标 → forecast 的 ``current`` 块）。"""
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        raise WeatherError("返回数据里没有实况")
    temperature = current.get("temperature_2m")
    if temperature is None:
        raise WeatherError("返回数据里没有温度")
    try:
        temperature_text = f"{float(temperature):.1f}℃"
    except (TypeError, ValueError) as exc:
        raise WeatherError("返回数据里没有温度") from exc
    direction = wind_direction_text(current.get("wind_direction_10m"))
    force = beaufort_text(current.get("wind_speed_10m"))
    wind = f"{direction}风 {force}".strip() if direction else force
    humidity = current.get("relative_humidity_2m")
    return WeatherReading(
        city=str(city or "").strip(),
        condition=wmo_text(current.get("weather_code")),
        temperature=temperature_text,
        wind=wind,
        humidity=f"{int(round(float(humidity)))}%" if humidity is not None else "",
        source=SOURCE_OPEN_METEO,
        observed_at=str(current.get("time") or "").strip(),
        detail=str(payload.get("timezone") or "").strip(),
    )


# ---------------------------------------------------------------- HTTP 出口
HttpGetter = Callable[..., str]


def _default_http(url: str, headers: dict, *, use_proxy: bool, timeout: float) -> str:
    """真实 HTTP GET。

    ``use_proxy=False`` 显式绕过系统代理（``ProxyHandler({})``，与
    ``pet/music_lyric.py::_build_opener`` 同一手法）；``True`` 走
    ``urllib.request.urlopen`` 的默认行为（自动读 Windows 注册表/环境变量的系统代理）。

    为什么国内源必须直连：2026-10-07 本机实测（系统代理 ``http://127.0.0.1:7890``）
    城市检索直连 0.46s / 走代理 2.06s，实况直连 0.08s / 走代理 2.09s——第一次点击
    就要连发两个请求，走代理会把"点一下等结果"的用户体验直接拖到 4 秒以上，慢
    代理下更容易撞上超时，重演歌词取词那次的"功能像是坏了"。
    为什么国外源跟随代理：open-meteo 直连/代理实测相当（0.71s vs 0.98s），而
    "只有代理能出网"的用户（文档 §四 的已知缺口）需要这条路兜底。
    """
    request = urllib.request.Request(url, headers=headers)
    if use_proxy:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- 取数客户端
class WeatherClient:
    """按「国内源 → 国外源」顺序取数；HTTP 出口与时钟可注入（测试用）。"""

    def __init__(self, *, http: HttpGetter | None = None, timeout: float = HTTP_TIMEOUT,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._http = http or _default_http
        self._timeout = float(timeout)
        self._clock = clock

    # ---- 出口辅助
    def _request_timeout(self, deadline: float | None) -> float:
        if deadline is None:
            return self._timeout
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise WeatherError("请求超时：已超过本次取数的时间预算")
        return min(self._timeout, remaining)

    def _get(self, url: str, *, use_proxy: bool, deadline: float | None = None,
             referer: str = "") -> str:
        headers = {"User-Agent": _UA, "Accept": "*/*"}
        if referer:
            headers["Referer"] = referer
        return self._http(url, headers, use_proxy=use_proxy,
                          timeout=self._request_timeout(deadline))

    # ---- 源 A：中国天气网（直连）
    def search_cities(self, query: str, *, deadline: float | None = None
                      ) -> tuple[list[CityCandidate], str]:
        """城市检索（源 A 独有）：返回 ``(候选列表, 失败原因)``；失败不抛。

        添加城市的对话框要的是"搜不到就说搜不到"，而不是异常。
        """
        for name in city_name_variants(query):
            url = CN_SEARCH_URL.format(query=urllib.parse.quote(name))
            try:
                payload = self._get(url, use_proxy=False, deadline=deadline,
                                    referer=CN_REFERER)
            except Exception as exc:  # noqa: BLE001 - 网络类异常统一转成原因文案
                reason = describe_error(exc)
                log.warning("天气城市检索失败 %s：%s", url, reason)
                return [], reason
            candidates = parse_search_payload(payload)
            picked = pick_candidate(candidates, name)
            if picked is not None:
                return [picked] + [c for c in candidates if c is not picked], ""
        return [], ""

    def _fetch_cn(self, city: str, deadline: float | None) -> WeatherReading:
        candidates, reason = self.search_cities(city, deadline=deadline)
        if reason:
            raise WeatherError(f"城市检索失败：{reason}")
        picked = pick_candidate(candidates, normalize_city_name(city)) or (
            candidates[0] if candidates else None
        )
        if picked is None:
            raise WeatherError("没有找到这个城市")
        url = CN_CURRENT_URL.format(code=picked.code)
        payload = self._get(url, use_proxy=False, deadline=deadline, referer=CN_REFERER)
        return parse_cn_reading(payload, fallback_city=picked.name)

    # ---- 源 B：open-meteo（跟随系统代理）
    def _fetch_open_meteo(self, city: str, deadline: float | None) -> WeatherReading:
        geocode_url = OM_GEOCODE_URL.format(query=urllib.parse.quote(str(city)))
        payload = json.loads(self._get(geocode_url, use_proxy=True, deadline=deadline))
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            raise WeatherError("没有找到这个城市")
        first = results[0] if isinstance(results, list) else {}
        if not isinstance(first, dict) or "latitude" not in first or "longitude" not in first:
            raise WeatherError("返回数据里没有坐标")
        display = str(first.get("name") or city)
        forecast_url = OM_FORECAST_URL.format(
            lat=first["latitude"], lon=first["longitude"]
        )
        forecast = json.loads(self._get(forecast_url, use_proxy=True, deadline=deadline))
        return parse_open_meteo_reading(forecast, display)

    # ---- 对外
    def fetch(self, city: str, *, deadline: float | None = None) -> WeatherReading:
        """取当前天气：源 A → 源 B，都失败抛 :class:`WeatherError`（点名两个源）。"""
        failures: list[tuple[str, str]] = []
        for source, worker in ((SOURCE_CN, self._fetch_cn),
                               (SOURCE_OPEN_METEO, self._fetch_open_meteo)):
            try:
                reading = worker(city, deadline)
            except Exception as exc:  # noqa: BLE001 - 单源失败必须落到下一个源
                reason = describe_error(exc) if not isinstance(exc, WeatherError) else str(exc)
                failures.append((source, reason))
                log.warning("天气取数失败 %s（%s）：%s", city, source, reason)
                continue
            log.info("天气取数成功：%s（%s）%s %s", reading.city, source,
                     reading.condition, reading.temperature)
            return reading
        raise WeatherError(failure_text(city, failures), tuple(failures))


def failure_text(city: str, failures) -> str:
    """两源都失败时的气泡文案（点名每个源的原因，不静默）。"""
    details = "；".join(f"{source}：{reason}" for source, reason in failures)
    head = f"天气获取失败（{city}）" if city else "天气获取失败"
    return f"{head}：{details}" if details else head
