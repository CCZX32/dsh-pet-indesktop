"""DeepSeek 峰谷提示：档位判定、下一档位扫描、文案与颜色。

口径来自主分支 `pet/balance.py`：北京时间、周末与法定节假日全天空闲、
工作日 09–12 / 14–18 高峰；颜色高峰 `#e5484d`、空闲 `#30a46c`。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from petcore.account import pricing

BJ = timezone(timedelta(hours=8))


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BJ)


def test_weekday_hour_boundaries() -> None:
    """09:00 进高峰、12:00 出高峰、14:00 进、18:00 出（左闭右开）。"""
    monday = (2026, 10, 26)
    assert _at(*monday, 8, 59).weekday() == 0  # 断言选的是周一
    assert pricing.pricing_tier(_at(*monday, 8, 59)) == pricing.TIER_IDLE
    assert pricing.pricing_tier(_at(*monday, 9, 0)) == pricing.TIER_PEAK
    assert pricing.pricing_tier(_at(*monday, 11, 59)) == pricing.TIER_PEAK
    assert pricing.pricing_tier(_at(*monday, 12, 0)) == pricing.TIER_IDLE
    assert pricing.pricing_tier(_at(*monday, 13, 59)) == pricing.TIER_IDLE
    assert pricing.pricing_tier(_at(*monday, 14, 0)) == pricing.TIER_PEAK
    assert pricing.pricing_tier(_at(*monday, 17, 59)) == pricing.TIER_PEAK
    assert pricing.pricing_tier(_at(*monday, 18, 0)) == pricing.TIER_IDLE
    assert pricing.pricing_tier(_at(*monday, 23, 30)) == pricing.TIER_IDLE


def test_weekend_is_idle_all_day() -> None:
    for day in (31, 1):
        month = 10 if day == 31 else 11
        for hour in (9, 10, 15, 17):
            assert pricing.pricing_tier(_at(2026, month, day, hour)) == pricing.TIER_IDLE


def test_statutory_holiday_lookup_overrides_weekday_peak() -> None:
    """节假日按官方口径全天空闲：注入 lookups 后工作日 10:00 也算低谷。"""
    holidays = {date(2026, 10, 26): "测试节"}
    tier = pricing.pricing_tier(
        _at(2026, 10, 26, 10), holiday_lookup=lambda day: holidays.get(day)
    )
    assert tier == pricing.TIER_IDLE
    # 未命中的日子仍按星期/小时规则。
    assert (
        pricing.pricing_tier(
            _at(2026, 10, 27, 10), holiday_lookup=lambda day: holidays.get(day)
        )
        == pricing.TIER_PEAK
    )


def test_broken_holiday_lookup_degrades_to_weekday_rules() -> None:
    def boom(_day):
        raise RuntimeError("历法后端坏了")

    assert pricing.pricing_tier(_at(2026, 10, 26, 10), holiday_lookup=boom) == pricing.TIER_PEAK


def test_naive_datetime_is_read_as_beijing_time() -> None:
    naive = datetime(2026, 10, 26, 10, 30)
    assert pricing.pricing_tier(naive) == pricing.TIER_PEAK
    aware = datetime(2026, 10, 26, 2, 30, tzinfo=timezone.utc)  # = 北京 10:30
    assert pricing.pricing_tier(aware) == pricing.TIER_PEAK


def test_next_switch_finds_the_same_day_boundary() -> None:
    tier, when = pricing.next_pricing_switch(_at(2026, 10, 26, 10, 30))
    assert tier == pricing.TIER_IDLE
    assert when == _at(2026, 10, 26, 12, 0)


def test_next_switch_skips_the_weekend_and_uses_iso_week_wording() -> None:
    # 周五 19:00 → 下一个高峰在周一 09:00；跨 ISO 周，措辞用「下周一」。
    friday_evening = _at(2026, 10, 30, 19, 0)
    tier, when = pricing.next_pricing_switch(friday_evening)
    assert tier == pricing.TIER_PEAK
    assert when == _at(2026, 11, 2, 9, 0)
    assert pricing.format_switch_time(pricing.beijing_now(friday_evening), when) == "下周一 09:00"


def test_switch_time_wording_covers_today_tomorrow_and_next_week() -> None:
    today = _at(2026, 10, 26, 8, 0)
    assert pricing.format_switch_time(today, _at(2026, 10, 26, 9, 0)) == "09:00"
    assert pricing.format_switch_time(today, _at(2026, 10, 27, 9, 0)) == "明天 09:00"
    # 同一 ISO 周内不写「下」：周一 → 周四。
    assert pricing.format_switch_time(today, _at(2026, 10, 29, 9, 0)) == "周四 09:00"
    assert pricing.format_switch_time(today, _at(2026, 11, 2, 9, 0)) == "下周一 09:00"


def test_tier_labels_modes() -> None:
    assert pricing.resolve_tier_labels("default") == ("高峰", "空闲")
    assert pricing.resolve_tier_labels("liangwen") == ("梁文峰", "梁文谷")
    assert pricing.resolve_tier_labels("custom", "忙", "闲") == ("忙", "闲")
    assert pricing.resolve_tier_labels("custom", "", "") == ("高峰", "空闲")
    # 未知模式回退默认，不抛异常。
    assert pricing.resolve_tier_labels("nonsense") == ("高峰", "空闲")


def test_plain_hint_text_matches_the_main_branch_wording() -> None:
    hint = pricing.format_hint(_at(2026, 10, 26, 10, 30))
    assert hint == "DeepSeek 当前高峰 · 下一空闲 12:00"
    hint_html = pricing.format_hint_html(_at(2026, 10, 26, 10, 30))
    assert "当前<span style=\"color:#e5484d\">高峰</span>" in hint_html
    assert "下一<span style=\"color:#30a46c\">空闲</span>" in hint_html


def test_custom_labels_are_html_escaped() -> None:
    html = pricing.format_hint_html(
        _at(2026, 10, 26, 10, 30), peak_label="<峰>", idle_label="&谷"
    )
    assert "&lt;峰&gt;" in html
    assert "&amp;谷" in html
    assert "<峰>" not in html


def test_subtitle_for_honours_the_colour_switch() -> None:
    class FakeConfig(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    config = FakeConfig(balance_tier_color_enabled=True)
    colored = pricing.subtitle_for(config, _at(2026, 10, 26, 10, 30))
    assert "<span" in colored

    config["balance_tier_color_enabled"] = False
    plain = pricing.subtitle_for(config, _at(2026, 10, 26, 10, 30))
    assert "<span" not in plain
    assert plain == "DeepSeek 当前高峰 · 下一空闲 12:00"


def test_subtitle_for_uses_configured_label_mode() -> None:
    class FakeConfig(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    config = FakeConfig(
        balance_tier_labels_mode="liangwen", balance_tier_color_enabled=False
    )
    assert "梁文峰" in pricing.subtitle_for(config, _at(2026, 10, 26, 10, 30))
