"""天气取数客户端：只经 `HttpPort`，不做自己的传输。

两源双出口照主分支口径：

- 中国天气网：``prefer_direct=True``（国内源，代理下实测慢 7~11 倍）；
- open-meteo：``prefer_direct=False``（海外源，跟随系统代理）。

单请求 6 秒、整次取数 15 秒预算；预算耗尽不再发请求。两源都失败抛
`WeatherError`，文案点名每个源的原因，绝不静默。
"""

from __future__ import annotations

import json
import time

from petcore.contracts.http import HttpRequest

from .logic import (
    CN_CURRENT_URL,
    CN_REFERER,
    CN_SEARCH_URL,
    OM_FORECAST_URL,
    OM_GEOCODE_URL,
    SOURCE_CN,
    SOURCE_OPEN_METEO,
    UA,
    CityCandidate,
    WeatherError,
    WeatherReading,
    base_city_name,
    city_name_variants,
    describe_error,
    failure_text,
    parse_cn_reading,
    parse_open_meteo_reading,
    parse_search_payload,
    pick_candidate,
)

HTTP_TIMEOUT = 6.0
TOTAL_BUDGET_SECONDS = 15.0


class WeatherClient:
    """按「国内源 → 国外源」顺序取数；HTTP 端口与时钟可注入（测试用）。"""

    def __init__(self, http, *, timeout: float = HTTP_TIMEOUT, budget: float = TOTAL_BUDGET_SECONDS, clock=time.monotonic) -> None:
        if http is None:
            raise WeatherError("取数端口不可用（core 未提供 HttpPort）")
        self._http = http
        self._timeout = float(timeout)
        self._budget = float(budget)
        self._clock = clock

    # ---------------------------------------------------------------- 出口辅助

    def _deadline(self) -> float:
        return self._clock() + self._budget

    def _request_timeout(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise WeatherError("请求超时：已超过本次取数的时间预算")
        return min(self._timeout, remaining)

    def _headers(self, *, referer: str = "") -> tuple[tuple[str, str], ...]:
        headers = [("User-Agent", UA), ("Accept", "*/*")]
        if referer:
            headers.append(("Referer", referer))
        return tuple(headers)

    def _text(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...] = (),
        prefer_direct: bool,
        deadline: float,
        referer: str = "",
    ) -> str:
        response = self._http.request(
            HttpRequest(
                url=url,
                params=params,
                headers=self._headers(referer=referer),
                prefer_direct=prefer_direct,
                timeout=self._request_timeout(deadline),
            )
        )
        if int(getattr(response, "status", 0) or 0) >= 400:
            raise WeatherError(f"HTTP {response.status}")
        return response.text

    def _json(self, url: str, *, params=(), prefer_direct: bool, deadline: float) -> object:
        text = self._text(
            url, params=params, prefer_direct=prefer_direct, deadline=deadline
        )
        try:
            return json.loads(text)
        except ValueError as exc:
            raise WeatherError(f"返回数据无效：{describe_error(exc)}") from exc

    # ---------------------------------------------------------------- 城市检索

    def search_cities(self, query: str, *, deadline: float | None = None) -> tuple[list[CityCandidate], str]:
        """城市检索（源 A 独有）：返回 ``(候选列表, 失败原因)``；失败不抛。"""
        deadline = deadline or self._deadline()
        for index, name in enumerate(city_name_variants(base_city_name(query))):
            try:
                text = self._text(
                    CN_SEARCH_URL,
                    params=(("cityname", name),),
                    prefer_direct=True,
                    deadline=deadline,
                    referer=CN_REFERER,
                )
            except Exception as exc:  # noqa: BLE001 - 网络/解析异常都转成原因文案
                return [], describe_error(exc)
            candidates = parse_search_payload(text)
            picked = pick_candidate(candidates, name, exact_only=index > 0)
            if picked is not None:
                return [picked] + [item for item in candidates if item is not picked], ""
        return [], ""

    # ---------------------------------------------------------------- 两源取数

    def _fetch_cn(self, city: str, deadline: float, code: str = "") -> WeatherReading:
        if code:
            try:
                text = self._text(
                    CN_CURRENT_URL.format(code=code),
                    prefer_direct=True,
                    deadline=deadline,
                    referer=CN_REFERER,
                )
                return parse_cn_reading(text, fallback_city=base_city_name(city))
            except Exception:  # noqa: BLE001 - 地区码失配就回落检索
                pass
        candidates, reason = self.search_cities(city, deadline=deadline)
        if reason:
            raise WeatherError(f"城市检索失败：{reason}")
        picked = pick_candidate(candidates, base_city_name(city)) or (
            candidates[0] if candidates else None
        )
        if picked is None:
            raise WeatherError("没有找到这个城市")
        text = self._text(
            CN_CURRENT_URL.format(code=picked.code),
            prefer_direct=True,
            deadline=deadline,
            referer=CN_REFERER,
        )
        return parse_cn_reading(text, fallback_city=picked.name)

    def _fetch_open_meteo(self, city: str, deadline: float) -> WeatherReading:
        name = base_city_name(city)
        payload = self._json(
            OM_GEOCODE_URL,
            params=(("name", name), ("count", "1"), ("language", "zh"), ("format", "json")),
            prefer_direct=False,
            deadline=deadline,
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            raise WeatherError("没有找到这个城市")
        first = results[0] if isinstance(results, list) else {}
        if not isinstance(first, dict) or "latitude" not in first or "longitude" not in first:
            raise WeatherError("返回数据里没有坐标")
        display = str(first.get("name") or name)
        forecast = self._json(
            OM_FORECAST_URL,
            params=(
                ("latitude", str(first["latitude"])),
                ("longitude", str(first["longitude"])),
                (
                    "current",
                    "temperature_2m,weather_code,wind_speed_10m,"
                    "wind_direction_10m,relative_humidity_2m",
                ),
                ("timezone", "auto"),
            ),
            prefer_direct=False,
            deadline=deadline,
        )
        return parse_open_meteo_reading(forecast, display)

    # ---------------------------------------------------------------- 对外

    def fetch(self, city: str, *, code: str = "") -> WeatherReading:
        failures: list[tuple[str, str]] = []
        deadline = self._deadline()
        for source, worker in (
            (SOURCE_CN, lambda name, until: self._fetch_cn(name, until, code)),
            (SOURCE_OPEN_METEO, self._fetch_open_meteo),
        ):
            try:
                return worker(city, deadline)
            except Exception as exc:  # noqa: BLE001 - 单源失败必须落到下一个源
                failures.append((source, describe_error(exc)))
                continue
        raise WeatherError(failure_text(city, failures), tuple(failures))
