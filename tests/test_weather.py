# -*- coding: utf-8 -*-
"""天气取数纯逻辑（无 Qt、无真实网络）。

覆盖四块领域规则：
1. **城市名容错**（「鹿城区」→「鹿城」）与城市列表操作（去重/上限 12/删除当前城市）；
2. **WMO 天气码 / 风向 / 风力等级**的中文映射（国外源缺中文文案时全靠这三张表）；
3. **源切换与失败口径**：源 A（中国天气网）失败走源 B（open-meteo），都失败抛
   ``WeatherError`` 且消息里两个源都点名——绝不静默；
4. **HTTP 出口可注入**：每个请求都记录 ``use_proxy``，钉住「国内源直连、国外源
   跟随系统代理」的分流决策（依据 docs/NETWORK-PROXY-AND-VPN-2026-09-22.md）。

测试样本取自 2026-10-07 的真机响应（见报告 §源与代理决策），不真发外网请求。
"""

from __future__ import annotations

import json
import time

import pytest

from pet import weather as W

# ---------------------------------------------------------------- 真机样本
CN_SEARCH_鹿城 = (
    '([{"ref":"101210710~zhejiang~鹿城~Lucheng~鹿城~Lucheng~577~325600~LC~浙江"},'
    '{"ref":"101210701009~zhejiang~滨江街道~binjiangjiedao~鹿城~lucheng~0577~325600~LC~浙江"},'
    '{"ref":"10121070101A~zhejiang~温州动物园~Wenzhou Zoo~温州~Wenzhou~null~325000~null~浙江省景点"}])'
)
CN_CURRENT_鹿城 = (
    'var dataSK={"nameen":"lucheng","cityname":"鹿城","city":"101210710","temp":"16.6",'
    '"tempf":"61.9","WD":"北风","wde":"N","WS":"1级","wse":"1km\\/h","SD":"67%","sd":"67%",'
    '"qy":"1019","njd":"30km","time":"03:10","rain":"0","rain24h":"0","aqi":"35",'
    '"aqi_pm25":"35","weather":"晴","weathere":"Sunny","weathercode":"d00",'
    '"limitnumber":"","date":"10月07日(星期三)"}'
)
OM_GEOCODE_北京 = json.dumps(
    {"results": [{"id": 1816670, "name": "北京", "latitude": 39.9075,
                  "longitude": 116.39723, "country_code": "CN"}]},
    ensure_ascii=False,
)
OM_CURRENT_北京 = json.dumps(
    {
        "latitude": 39.9,
        "longitude": 116.4,
        "timezone": "Asia/Shanghai",
        "current": {
            "time": "2026-10-07T03:15",
            "interval": 900,
            "temperature_2m": 9.5,
            "relative_humidity_2m": 78,
            "wind_speed_10m": 5.2,
            "wind_direction_10m": 181,
            "weather_code": 2,
        },
    },
    ensure_ascii=False,
)


class _FakeHttp:
    """可注入 HTTP 出口：按 URL 关键字给响应，并记录每次调用的出口选择。"""

    def __init__(self, routes, *, clock=None, advance: float = 0.0):
        self.routes = routes  # [(关键字, 文本 或 Exception)]
        self.calls: list[dict] = []
        self._clock = clock
        self._advance = advance

    def __call__(self, url, headers, *, use_proxy, timeout):
        self.calls.append({"url": url, "headers": headers, "use_proxy": use_proxy,
                           "timeout": timeout})
        if self._clock is not None and self._advance:
            self._clock.now += self._advance
        for key, value in self.routes:
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"未预期的请求：{url}")

    def urls(self):
        return [call["url"] for call in self.calls]


def _client(http, *, clock=time.monotonic):
    return W.WeatherClient(http=http, clock=clock)


# ---------------------------------------------------------------- 1. 城市名容错
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("鹿城区", "鹿城"),
        ("  北京市  ", "北京"),
        ("浙江省", "浙江"),
        ("温州市", "温州"),
        ("鹿城", "鹿城"),
        ("", ""),
        (None, ""),
        ("市", "市"),          # 剥后缀会剥空 → 保留原样，不退化成空串
        ("乌鲁木齐县", "乌鲁木齐"),
        ("New York", "New York"),  # 非中文无后缀，原样
    ],
)
def test_normalize_city_name_strips_administrative_suffix(raw, expected):
    assert W.normalize_city_name(raw) == expected


def test_city_name_variants_keeps_original_first_and_dedups():
    assert W.city_name_variants("鹿城区") == ("鹿城区", "鹿城")
    assert W.city_name_variants("鹿城") == ("鹿城",)
    assert W.city_name_variants("") == ()
    # 手填时用归一化名存储（见 normalize_city_name 用例），这里只保证顺序语义
    assert W.city_name_variants("  杭州市 ") == ("杭州市", "杭州")


def test_normalize_city_list_trims_dedups_and_caps():
    assert W.normalize_city_list([" 北京 ", "北京", "", "   ", "上海"]) == ["北京", "上海"]
    assert W.normalize_city_list(None) == []
    assert W.normalize_city_list("北京") == []
    assert W.normalize_city_list(["北京", 42, None]) == ["北京"]
    assert len(W.normalize_city_list([f"城市{i}" for i in range(30)])) == W.MAX_CITIES
    # 名字过长按上限截断，避免手改配置塞进超长串
    assert W.normalize_city_list(["北" * 40]) == ["北" * W.MAX_CITY_NAME]


def test_add_city_appends_normalizes_and_rejects_duplicates():
    cities, error = W.add_city(["北京"], " 鹿城区 ")
    assert cities == ["北京", "鹿城"] and error == ""

    cities, error = W.add_city(["北京", "鹿城"], "鹿城")
    assert cities == ["北京", "鹿城"] and error == W.CITY_EXISTS_TEXT

    cities, error = W.add_city([], "   ")
    assert cities == [] and error == W.CITY_EMPTY_TEXT

    full = [f"城市{i}" for i in range(W.MAX_CITIES)]
    cities, error = W.add_city(full, "新城市")
    assert cities == full and error == W.CITY_LIMIT_TEXT


def test_remove_city_reassigns_current_when_removing_the_current_one():
    cities, current = W.remove_city(["北京", "上海", "鹿城"], "上海", "上海")
    assert cities == ["北京", "鹿城"] and current == "北京"

    cities, current = W.remove_city(["北京"], "北京", "北京")
    assert cities == [] and current == ""

    # 删的不是当前城市 → 当前不动
    cities, current = W.remove_city(["北京", "上海"], "上海", "北京")
    assert cities == ["北京"] and current == "北京"


def test_current_city_falls_back_to_first_list_entry():
    assert W.current_city({"weather_city": "鹿城", "weather_city_list": ["北京"]}) == "鹿城"
    assert W.current_city({"weather_city": "", "weather_city_list": ["北京", "上海"]}) == "北京"
    assert W.current_city({"weather_city": "  ", "weather_city_list": []}) == ""
    assert W.current_city({}) == ""


# ---------------------------------------------------------------- 2. 码表映射
@pytest.mark.parametrize(
    "code,expected",
    [(0, "晴"), (1, "多云"), (2, "局部多云"), (3, "阴"), (45, "雾"), (48, "雾凇"),
     (61, "小雨"), (63, "中雨"), (65, "大雨"), (71, "小雪"), (75, "大雪"),
     (80, "小阵雨"), (95, "雷阵雨"), (96, "雷阵雨伴小冰雹"), (123, "未知"), (None, "未知")],
)
def test_wmo_code_maps_to_chinese(code, expected):
    assert W.wmo_text(code) == expected


@pytest.mark.parametrize(
    "degrees,expected",
    [(0, "北"), (20, "北"), (45, "东北"), (90, "东"), (135, "东南"), (180, "南"),
     (225, "西南"), (270, "西"), (315, "西北"), (359, "北"), (None, "")],
)
def test_wind_direction_degrees_map_to_eight_points(degrees, expected):
    assert W.wind_direction_text(degrees) == expected


@pytest.mark.parametrize(
    "kmh,expected",
    [(0, "0级"), (0.5, "0级"), (3, "1级"), (10, "2级"), (23, "4级"), (45, "6级"),
     (70, "8级"), (95, "10级"), (130, "12级"), (None, "")],
)
def test_wind_speed_maps_to_beaufort_force(kmh, expected):
    assert W.beaufort_text(kmh) == expected


# ---------------------------------------------------------------- 3. 响应解析
def test_parse_search_payload_reads_candidates_and_drops_scenic_spots():
    candidates = W.parse_search_payload(CN_SEARCH_鹿城)
    assert [c.code for c in candidates] == ["101210710", "101210701009"]
    assert candidates[0].name == "鹿城"
    assert candidates[0].region == "浙江"


def test_parse_search_payload_tolerates_empty_and_garbage():
    assert W.parse_search_payload("([])") == []
    assert W.parse_search_payload("") == []
    assert W.parse_search_payload("not json") == []


def test_pick_candidate_prefers_exact_name_match():
    candidates = W.parse_search_payload(CN_SEARCH_鹿城)
    picked = W.pick_candidate(candidates, "鹿城")
    assert picked is not None and picked.code == "101210710"

    # 归一化后的查询同样是精确命中（鹿城区 → 鹿城 由调用方剥后缀，这里再兜一层）
    assert W.pick_candidate(candidates, "鹿城区").code == "101210710"
    assert W.pick_candidate([], "鹿城") is None


def test_parse_cn_reading_extracts_current_conditions():
    reading = W.parse_cn_reading(CN_CURRENT_鹿城)
    assert reading.city == "鹿城"
    assert reading.condition == "晴"
    assert reading.temperature == "16.6℃"
    assert reading.wind == "北风 1级"
    assert reading.humidity == "67%"
    assert reading.source == W.SOURCE_CN
    assert reading.observed_at == "03:10"
    assert "鹿城" in reading.bubble_text() and "16.6℃" in reading.bubble_text()


def test_parse_cn_reading_rejects_response_without_temperature():
    with pytest.raises(W.WeatherError):
        W.parse_cn_reading('var dataSK={"cityname":"鹿城"}')
    with pytest.raises(W.WeatherError):
        W.parse_cn_reading("<html>not json</html>")


def test_parse_open_meteo_reading_maps_wmo_wind_and_humidity():
    reading = W.parse_open_meteo_reading(json.loads(OM_CURRENT_北京), "北京")
    assert reading.city == "北京"
    assert reading.source == W.SOURCE_OPEN_METEO
    assert reading.condition == "局部多云"
    assert reading.temperature == "9.5℃"
    assert reading.wind == "南风 1级"
    assert reading.humidity == "78%"


def test_parse_open_meteo_reading_rejects_payload_without_current_block():
    with pytest.raises(W.WeatherError):
        W.parse_open_meteo_reading({"error": True, "reason": "nope"}, "北京")


def test_describe_error_names_the_failure_kind():
    assert W.describe_error(TimeoutError("timed out")) == "请求超时"
    assert W.describe_error(ValueError("bad json")) == "返回数据无效"


# ---------------------------------------------------------------- 4. 源切换
def test_fetch_uses_china_source_directly_and_never_touches_proxy():
    http = _FakeHttp([("toy1.weather.com.cn", CN_SEARCH_鹿城),
                      ("d1.weather.com.cn", CN_CURRENT_鹿城)])
    reading = _client(http).fetch("鹿城")
    assert reading.source == W.SOURCE_CN and reading.temperature == "16.6℃"
    assert [call["use_proxy"] for call in http.calls] == [False, False]
    assert all(call["headers"].get("Referer") for call in http.calls)


def test_fetch_retries_with_suffix_stripped_name_before_falling_back():
    """「鹿城区」在源 A 搜不到（真机实测空数组），必须用「鹿城」重搜。"""
    http = _FakeHttp([("cityname=%E9%B9%BF%E5%9F%8E%E5%8C%BA", "([])"),
                      ("cityname=%E9%B9%BF%E5%9F%8E", CN_SEARCH_鹿城),
                      ("d1.weather.com.cn", CN_CURRENT_鹿城)])
    reading = _client(http).fetch("鹿城区")
    assert reading.city == "鹿城"
    assert reading.source == W.SOURCE_CN


def test_fetch_falls_back_to_open_meteo_through_the_system_proxy():
    http = _FakeHttp([("toy1.weather.com.cn", TimeoutError("timed out")),
                      ("geocoding-api.open-meteo.com", OM_GEOCODE_北京),
                      ("api.open-meteo.com", OM_CURRENT_北京)])
    reading = _client(http).fetch("北京")
    assert reading.source == W.SOURCE_OPEN_METEO
    assert reading.condition == "局部多云"
    # 国内源一律直连、海外源跟随系统代理（真机实测：直连 2s+ 慢于代理，且
    # 只有代理能出网的用户靠这条路兜底）
    assert [(call["url"].split("/")[2], call["use_proxy"]) for call in http.calls] == [
        ("toy1.weather.com.cn", False),
        ("geocoding-api.open-meteo.com", True),
        ("api.open-meteo.com", True),
    ]


def test_fetch_raises_naming_both_sources_when_every_source_fails():
    http = _FakeHttp([("toy1.weather.com.cn", TimeoutError("timed out")),
                      ("geocoding-api.open-meteo.com", OSError("no route"))])
    with pytest.raises(W.WeatherError) as info:
        _client(http).fetch("北京")
    message = str(info.value)
    assert W.SOURCE_CN in message and W.SOURCE_OPEN_METEO in message
    assert "失败" in message
    assert "超时" in message


def test_fetch_never_fires_a_request_with_an_exhausted_budget():
    """预算已耗尽 → 直接按失败收场，一次请求都不发（用户等待有上界）。"""
    clock = _Clock()
    http = _FakeHttp([("toy1.weather.com.cn", CN_SEARCH_鹿城),
                      ("d1.weather.com.cn", CN_CURRENT_鹿城)], clock=clock)
    with pytest.raises(W.WeatherError):
        _client(http, clock=clock).fetch("鹿城", deadline=clock.now - 1.0)
    assert http.calls == []


def test_each_request_timeout_is_capped_by_the_remaining_budget():
    clock = _Clock()
    http = _FakeHttp([("toy1.weather.com.cn", CN_SEARCH_鹿城),
                      ("d1.weather.com.cn", CN_CURRENT_鹿城)], clock=clock)
    _client(http, clock=clock).fetch("鹿城", deadline=clock.now + 1.5)
    assert http.calls[0]["timeout"] == pytest.approx(1.5)


def test_budget_spent_mid_flight_blocks_the_fallback_source():
    """源 A 把预算耗光后不再试源 B——总耗时必须有上界，不是两源各自撞满超时。"""
    clock = _Clock()
    http = _FakeHttp([("toy1.weather.com.cn", "([])")], clock=clock, advance=9.0)
    with pytest.raises(W.WeatherError):
        _client(http, clock=clock).fetch("鹿城", deadline=clock.now + 8.0)
    assert all("open-meteo" not in call["url"] for call in http.calls)


def test_search_cities_returns_ranked_candidates_and_reason():
    ok = _FakeHttp([("toy1.weather.com.cn", CN_SEARCH_鹿城)])
    results, error = _client(ok).search_cities("鹿城")
    # 精确命中排第一，其余候选保留供用户改选
    assert [c.code for c in results] == ["101210710", "101210701009"] and error == ""

    bad = _FakeHttp([("toy1.weather.com.cn", TimeoutError("timed out"))])
    results, error = _client(bad).search_cities("鹿城")
    assert results == [] and "超时" in error


class _Clock:
    """可控时钟：推进时间以便确定性地测总预算。"""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_timeout_and_city_limit_constants_are_the_documented_ones():
    assert W.HTTP_TIMEOUT == 6.0
    assert W.MAX_CITIES == 12
    assert W.TOTAL_BUDGET_SECONDS > W.HTTP_TIMEOUT
