"""tool.weather：纯逻辑、两源取数、运行时候与设置页（P4-a）。"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from petcore.contracts.http import HttpError, HttpResponse
from petcore.contracts.host import HostPorts
from petcore.mods import feature as feature_mod
from petcore.mods.manifest import load_manifest

from pathlib import Path

MOD_DIR = Path(__file__).resolve().parents[1] / "examples" / "petcore-mods" / "tool.weather"
HOST_PKG = "petcore_weather_test_host"


def _host_package():
    if HOST_PKG in sys.modules:
        return sys.modules[HOST_PKG]
    spec = importlib.util.spec_from_file_location(
        HOST_PKG,
        MOD_DIR / "host" / "__init__.py",
        submodule_search_locations=[str(MOD_DIR / "host")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[HOST_PKG] = module
    spec.loader.exec_module(module)
    return module


_host_package()
logic = importlib.import_module(f"{HOST_PKG}.logic")
client_mod = importlib.import_module(f"{HOST_PKG}.client")
runtime_mod = importlib.import_module(f"{HOST_PKG}.runtime")


class FakeHttpPort:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def request(self, request):
        self.requests.append(request)
        outcome = self.handler(request)
        if isinstance(outcome, BaseException):
            raise outcome
        status, body, headers = outcome
        return HttpResponse(
            status=status, url=request.url, headers=tuple(headers), body=body
        )


CN_SEARCH_BODY = (
    '([{"ref":"101210710~浙江~鹿城~lucheng~温州~wenzhou~0577~325000~lc~浙江"}])'
).encode("utf-8")
CN_CURRENT_BODY = (
    'var dataSK={"cityname":"鹿城","weather":"多云","temp":"21.5",'
    '"WD":"东南风","WS":"2级","SD":"66%","time":"10:20","date":"2026-10-22"}'
).encode("utf-8")
GEOCODE_BODY = json.dumps(
    {"results": [{"name": "鹿城", "latitude": 28.0, "longitude": 120.6}]}
).encode("utf-8")
FORECAST_BODY = json.dumps(
    {
        "timezone": "Asia/Shanghai",
        "current": {
            "temperature_2m": 22.4,
            "weather_code": 1,
            "wind_speed_10m": 12.0,
            "wind_direction_10m": 135.0,
            "relative_humidity_2m": 58,
        },
    }
).encode("utf-8")


def _cn_source(request):
    if "search" in request.url:
        return (200, CN_SEARCH_BODY, ())
    return (200, CN_CURRENT_BODY, ())


# ---------------------------------------------------------------- 纯逻辑


def test_city_normalization_is_idempotent_and_keeps_suffixes():
    assert logic.normalize_city_name("  鹿城区 ") == "鹿城区"
    assert logic.normalize_city_name(logic.normalize_city_name("鹿城区")) == "鹿城区"
    assert logic.city_name_variants("鹿城区") == ("鹿城区", "鹿城")


def test_add_and_remove_city_use_display_names():
    cities, error = logic.add_city([], "鹿城区")
    assert (cities, error) == (["鹿城区"], "")
    cities, error = logic.add_city(cities, "鹿城")
    assert error == logic.CITY_EXISTS_TEXT
    assert logic.remove_city(cities, "鹿城", "鹿城区") == ([], "")


def test_parse_search_payload_drops_sight_codes():
    candidates = logic.parse_search_payload(
        '([{"ref":"10102020001A~北京~朝阳~chaoyang~北京~beijing~010~100000~cy~北京"},'
        '{"ref":"101070201~辽宁~朝阳~chaoyang~朝阳~chaoyang~0421~122000~cy~辽宁"}])'
    )
    assert [item.code for item in candidates] == ["101070201"]
    assert candidates[0].region == "辽宁"


def test_parse_cn_reading_formats_temperature_and_wind():
    reading = logic.parse_cn_reading(CN_CURRENT_BODY.decode("utf-8"))
    assert reading.temperature == "21.5℃"
    assert reading.wind == "东南风 2级"
    assert reading.source == logic.SOURCE_CN


def test_parse_open_meteo_maps_wmo_and_beaufort():
    reading = logic.parse_open_meteo_reading(json.loads(FORECAST_BODY), "鹿城")
    assert reading.condition == "多云"
    assert reading.temperature == "22.4℃"
    assert reading.wind == "东南风 3级"
    assert reading.humidity == "58%"


def test_failure_text_names_every_source():
    text = logic.failure_text("鹿城", (("中国天气网", "网络连接失败"), ("open-meteo", "请求超时")))
    assert "中国天气网" in text and "open-meteo" in text and "鹿城" in text


def test_describe_error_maps_http_reason():
    assert "请求超时" in logic.describe_error(HttpError("timeout"))
    assert "HTTP 502" in logic.describe_error(HttpError("network", status=502))


# ---------------------------------------------------------------- 客户端


def test_fetch_cn_searches_then_reads_current():
    port = FakeHttpPort(_cn_source)
    reading = client_mod.WeatherClient(port).fetch("鹿城")

    assert reading.city == "鹿城"
    assert reading.source == logic.SOURCE_CN
    assert [request.prefer_direct for request in port.requests] == [True, True]
    assert port.requests[0].params == (("cityname", "鹿城"),)


def test_fetch_cn_uses_region_code_without_search():
    port = FakeHttpPort(_cn_source)
    reading = client_mod.WeatherClient(port).fetch("鹿城", code="101210710")

    assert reading.source == logic.SOURCE_CN
    assert len(port.requests) == 1
    assert "101210710" in port.requests[0].url


def test_fetch_falls_back_to_open_meteo_when_cn_fails():
    def handler(request):
        if "weather.com.cn" in request.url:
            return HttpError("network")
        if "geocoding" in request.url:
            return (200, GEOCODE_BODY, ())
        return (200, FORECAST_BODY, ())

    port = FakeHttpPort(handler)
    reading = client_mod.WeatherClient(port).fetch("鹿城")

    assert reading.source == logic.SOURCE_OPEN_METEO
    assert [request.prefer_direct for request in port.requests] == [True, False, False]


def test_fetch_failure_names_both_sources():
    port = FakeHttpPort(lambda request: HttpError("network"))
    with pytest.raises(logic.WeatherError) as caught:
        client_mod.WeatherClient(port).fetch("鹿城")

    text = str(caught.value)
    assert "中国天气网" in text and "open-meteo" in text


def test_budget_exhaustion_sends_no_further_requests():
    port = FakeHttpPort(_cn_source)
    values = [0.0, 0.0, 100.0, 100.0, 100.0, 100.0]

    def clock():
        return values.pop(0) if values else 100.0

    client = client_mod.WeatherClient(port, budget=15.0, clock=clock)
    with pytest.raises(logic.WeatherError) as caught:
        client.fetch("鹿城")

    assert "请求超时" in str(caught.value)
    assert len(port.requests) == 1


# ---------------------------------------------------------------- 运行时


class _Presentation:
    def __init__(self):
        self.said = []

    def say(self, text, *, duration_ms=4000, force=False):
        self.said.append(text)

    def show_image(self, *args, **kwargs):
        return False

    def play_animation(self, name):
        return False

    def play_event(self, group, variant=None):
        return False

    def notify(self, *args, **kwargs):
        return None


class _Config(dict):
    def set(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return dict.get(self, key, default)


def _context(config=None, http=None):
    presentation = _Presentation()
    ports = HostPorts(
        presentation=presentation,
        config=_Config(config or {}),
        http=http,
    )
    return SimpleNamespace(ports=ports), presentation


def test_show_refuses_when_disabled():
    context, presentation = _context({"weather_enabled": False})
    runtime = runtime_mod.WeatherRuntime(context)
    runtime.show()
    assert "已关闭" in presentation.said[-1]


def test_show_asks_for_city_when_unset():
    context, presentation = _context({"weather_city": ""})
    runtime = runtime_mod.WeatherRuntime(context)
    runtime.show()
    assert presentation.said[-1] == logic.NO_CITY_TEXT


def test_show_uses_reading_bubble():
    context, presentation = _context(
        {"weather_city": "鹿城", "weather_city_list": ["鹿城"]},
        http=FakeHttpPort(_cn_source),
    )
    runtime = runtime_mod.WeatherRuntime(context)
    runtime.show()
    runtime._threads[0].join(5)

    assert "鹿城" in presentation.said[-1]
    assert "21.5℃" in presentation.said[-1]
    assert runtime._busy is False


def test_show_reports_failure_in_bubble():
    context, presentation = _context(
        {"weather_city": "鹿城"}, http=FakeHttpPort(lambda request: HttpError("network"))
    )
    runtime = runtime_mod.WeatherRuntime(context)
    runtime.show()
    runtime._threads[0].join(5)

    assert "天气获取失败" in presentation.said[-1]


# ---------------------------------------------------------------- 设置页


class _Host:
    def __init__(self, config, http=None):
        self.config = _Config(config)
        self.ports = SimpleNamespace(http=http)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_settings_page_round_trips_cities(app):
    manager = feature_mod.FeatureManager(HostPorts())
    manifest, _ = load_manifest(MOD_DIR)
    manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    page_class = manager.settings_pages()[0].factory

    host = _Host({"weather_enabled": True, "weather_city_list": [], "weather_city": ""})
    page = page_class(host)

    page.name_edit.setText("鹿城区")
    page._add_city()
    assert host.config["weather_city_list"] == ["鹿城区"]
    assert host.config["weather_city"] == "鹿城区"
    assert page.dirty() is True

    page.confirm_save()
    assert page.dirty() is False

    page.enabled.setChecked(False)
    page.discard_changes()
    assert page.enabled.isChecked() is True
    assert host.config["weather_enabled"] is True


def test_mod_manifest_and_contributions_load():
    manifest, problems = load_manifest(MOD_DIR)
    assert problems == []
    assert manifest.id == "tool.weather"
    manager = feature_mod.FeatureManager(HostPorts())
    diagnostics = manager.load(
        pack=MOD_DIR, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
    )
    assert diagnostics == []
    menu_ids = {contribution.id for _, contribution in manager.menu_contributions()}
    assert "show" in menu_ids
    assert manager.settings_pages()


@pytest.mark.parametrize("failure", [False, True])
def test_stop_discards_queued_result(app, tmp_path, failure):
    from dataclasses import replace
    from PySide6.QtCore import QEventLoop, QTimer
    from petcore.ui.ports import QtScheduler

    scheduler = QtScheduler()
    context, presentation = _context(
        {"weather_city": "鹿城"},
        http=FakeHttpPort((lambda request: HttpError("network")) if failure else _cn_source),
    )
    context.ports = replace(context.ports, scheduler=scheduler)
    runtime = runtime_mod.WeatherRuntime(context)
    runtime.show()
    runtime._threads[-1].join(10)
    assert not runtime._threads[-1].is_alive()
    before = list(presentation.said)
    runtime.stop()
    loop = QEventLoop()
    delivered = []
    scheduler.call_later(0, lambda: (delivered.append(True), loop.quit()))
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(10000)
    loop.exec()
    timeout.stop()
    assert delivered
    assert presentation.said == before


def test_repeated_requests_prune_finished_workers(tmp_path):
    context, _ = _context({"weather_city": "鹿城"}, http=FakeHttpPort(_cn_source))
    runtime = runtime_mod.WeatherRuntime(context)
    for _ in range(30):
        runtime.show()
        assert len(runtime._threads) == 1
        runtime._threads[0].join(10)
        assert not runtime._threads[0].is_alive()
    runtime.stop()
