"""天气的纯逻辑：城市名、地区码、两源解析、失败文案。

从主分支 `pet/weather.py` 原样搬来算法，**只删掉网络出口**：这里不 import
`urllib`，HTTP 一律经 `HostPorts.http`（在 `client.py` 里）。运行时无 Qt。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

from petcore.contracts.http import HttpError

SOURCE_CN = "中国天气网"
SOURCE_OPEN_METEO = "open-meteo"

MAX_CITIES = 12
MAX_CITY_NAME = 24

CITY_LIMIT_TEXT = f"最多只能有 {MAX_CITIES} 个城市"
CITY_EXISTS_TEXT = "这个城市已经在列表里了"
CITY_EMPTY_TEXT = "城市名不能为空"
NO_CITY_TEXT = "还没选天气城市：设置 → 扩展管理 → 天气"

CN_SEARCH_URL = "http://toy1.weather.com.cn/search"
CN_CURRENT_URL = "http://d1.weather.com.cn/sk_2d/{code}.html"
CN_REFERER = "http://www.weather.com.cn/"
OM_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
OM_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 行政区后缀只用于查询回退，绝不回写存储（剥离不是幂等的）。
_CITY_SUFFIXES = (
    "维吾尔自治区", "壮族自治区", "回族自治区", "内蒙古自治区", "特别行政区",
    "自治区", "自治州", "自治县", "开发区", "高新区", "新区", "地区", "街道",
    "省", "市", "区", "县", "镇", "乡", "旗", "盟",
)

CITY_REGION_SEPARATOR = " · "
_BASE_NAME_SEPARATORS = (" · ", "·", "（", "(")

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

_BEAUFORT_KMH = (1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118)

_REASON_TEXT = {
    "auth": "需要授权",
    "rate_limit": "请求过于频繁",
    "network": "网络连接失败",
    "timeout": "请求超时",
    "protocol": "返回数据无效",
}


class WeatherError(RuntimeError):
    """取数失败（单源或两源都失败）。``failures`` = ((源名, 原因), ...)。"""

    def __init__(self, message: str, failures: tuple[tuple[str, str], ...] = ()) -> None:
        super().__init__(message)
        self.failures = failures


@dataclass(frozen=True)
class CityCandidate:
    code: str
    name: str
    region: str = ""


@dataclass(frozen=True)
class WeatherReading:
    city: str
    condition: str
    temperature: str
    wind: str = ""
    humidity: str = ""
    source: str = ""
    observed_at: str = ""
    detail: str = ""

    def bubble_text(self) -> str:
        head = " ".join(part for part in (self.city, self.condition, self.temperature) if part)
        extras = [
            part
            for part in (self.wind, f"湿度 {self.humidity}" if self.humidity else "")
            if part
        ]
        if extras:
            head += "，" + "，".join(extras)
        return f"{head}（{self.source}）" if self.source else head


# ---------------------------------------------------------------- 城市名与列表


def normalize_city_name(raw) -> str:
    """存储层归一化：NFKC、去空白、截断。**不剥后缀**，必须幂等。"""
    name = unicodedata.normalize("NFKC", str(raw or "")).strip()
    return name[:MAX_CITY_NAME]


def strip_city_suffix(raw) -> str:
    name = normalize_city_name(raw)
    for suffix in _CITY_SUFFIXES:
        if len(name) > len(suffix) and name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def city_name_variants(raw) -> tuple[str, ...]:
    name = normalize_city_name(raw)
    if not name:
        return ()
    stripped = strip_city_suffix(name)
    return (name,) if stripped == name else (name, stripped)


def base_city_name(label) -> str:
    name = normalize_city_name(label)
    for separator in _BASE_NAME_SEPARATORS:
        head = name.split(separator, 1)[0].strip()
        if head and head != name:
            return head
    return name


def city_label(name, region: str = "", *, ambiguous: bool = False) -> str:
    base = normalize_city_name(name)
    area = normalize_city_name(region)
    if not (ambiguous and base and area):
        return base
    if area == base or base in area or area in base:
        return base
    return normalize_city_name(f"{base}{CITY_REGION_SEPARATOR}{area}")


def _read(source, key, default=None):
    """同时支持 ConfigPort（``get``）与普通 dict。"""
    getter = getattr(source, "get", None)
    if callable(getter):
        return getter(key, default)
    if isinstance(source, dict):
        return source.get(key, default)
    return default


def normalize_city_codes(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    codes: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        label = normalize_city_name(key)
        code = value.strip()
        if label and code:
            codes[label] = code
    return codes


def city_code_for(config, city) -> str:
    codes = normalize_city_codes(_read(config, "weather_city_codes", {}))
    name = normalize_city_name(city)
    return codes.get(name) or codes.get(base_city_name(name)) or ""


def same_city(left, right) -> bool:
    return bool(set(city_name_variants(left)) & set(city_name_variants(right)))


def normalize_city_list(raw) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    cities: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = normalize_city_name(item)
        if name and not any(same_city(name, city) for city in cities):
            cities.append(name)
        if len(cities) >= MAX_CITIES:
            break
    return cities


def current_city(config) -> str:
    selected = normalize_city_name(_read(config, "weather_city", "") or "")
    if selected:
        return selected
    cities = normalize_city_list(_read(config, "weather_city_list", []))
    return cities[0] if cities else ""


def add_city(cities, name) -> tuple[list[str], str]:
    current = normalize_city_list(cities)
    candidate = normalize_city_name(name)
    if not candidate:
        return current, CITY_EMPTY_TEXT
    if any(same_city(candidate, city) for city in current):
        return current, CITY_EXISTS_TEXT
    if len(current) >= MAX_CITIES:
        return current, CITY_LIMIT_TEXT
    return current + [candidate], ""


def remove_city(cities, name, current: str = "") -> tuple[list[str], str]:
    listed = normalize_city_list(cities)
    if not any(same_city(city, name) for city in listed):
        return listed, current or ""
    remaining = [city for city in listed if not same_city(city, name)]
    if not same_city(current, name):
        return remaining, current or ""
    return remaining, (remaining[0] if remaining else "")


# ---------------------------------------------------------------- 码表


def wmo_text(code) -> str:
    try:
        return _WMO_TEXT.get(int(code), "未知")
    except (TypeError, ValueError):
        return "未知"


def wind_direction_text(degrees) -> str:
    try:
        value = float(degrees) % 360.0
    except (TypeError, ValueError):
        return ""
    names = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
    return names[int((value + 22.5) // 45) % 8]


def beaufort_text(kmh) -> str:
    try:
        value = max(0.0, float(kmh))
    except (TypeError, ValueError):
        return ""
    force = 12
    for index, upper in enumerate(_BEAUFORT_KMH):
        if value < upper:
            force = index
            break
    return f"{force}级"


def describe_error(exc: BaseException) -> str:
    """异常 → 一句中文原因（气泡里给用户看的那一种）。"""
    if isinstance(exc, WeatherError):
        return str(exc)
    if isinstance(exc, HttpError):
        text = _REASON_TEXT.get(exc.reason, exc.reason)
        return f"{text}（HTTP {exc.status}）" if exc.status else text
    if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
        return "请求超时"
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return "返回数据无效"
    return f"{type(exc).__name__}: {str(exc)[:60]}"


# ---------------------------------------------------------------- 响应解析


def parse_search_payload(text: str) -> list[CityCandidate]:
    """解析源 A 城市检索 ``([{"ref":"code~省~名称~..."}])``；剔除景点码（``A`` 结尾）。"""
    raw = str(text or "").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(raw[start : end + 1])
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
        candidates.append(
            CityCandidate(code=code, name=name, region=parts[-1].strip())
        )
    return candidates


def _match_rank(candidate: CityCandidate, query: str, *, exact_only: bool = False) -> int:
    targets = city_name_variants(query) or (query,)
    primary = [normalize_city_name(candidate.name)]
    primary.extend(normalize_city_name(part) for part in candidate.name.split())
    if exact_only:
        return 0 if any(name == target for name in primary for target in targets) else 3
    names = list(primary)
    for part in candidate.name.split():
        names.extend(city_name_variants(part))
    rank = 3
    for name in names:
        for target in targets:
            if name == target:
                return 0
            if name.startswith(target):
                rank = min(rank, 1)
            elif target in name:
                rank = min(rank, 2)
    return rank


def pick_candidate(candidates, query, *, exact_only: bool = False) -> CityCandidate | None:
    target = normalize_city_name(query)
    if not target:
        return None
    best: tuple[int, int, CityCandidate] | None = None
    for index, candidate in enumerate(candidates):
        rank = _match_rank(candidate, target, exact_only=exact_only)
        if rank >= 3:
            continue
        key = (rank, index)
        if best is None or key < (best[0], best[1]):
            best = (rank, index, candidate)
    return best[2] if best is not None else None


def parse_cn_reading(text: str, fallback_city: str = "") -> WeatherReading:
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise WeatherError("返回数据无效")
    try:
        data = json.loads(raw[start : end + 1])
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


def failure_text(city: str, failures) -> str:
    details = "；".join(f"{source}：{reason}" for source, reason in failures)
    head = f"天气获取失败（{city}）" if city else "天气获取失败"
    return f"{head}：{details}" if details else head
