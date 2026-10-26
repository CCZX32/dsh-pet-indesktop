"""余额气泡的峰谷副标题：从配置到 `say(..., subtitle=...)` 的那一跳。

覆盖三件事：
1. `CoreHost._balance_subtitle` 按配置产出 HTML（开颜色）或纯文本（关颜色）；
2. `CoreHost._notify` 把副标题透传给气泡的 `say`；
3. 老签名（没有 `subtitle` 形参）的窗口不许让提示消失。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from petcore.config import Config
from petcore.ui.app import CoreHost


class _Window:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def say(self, text: str, duration_ms: int = 4000, *, subtitle: str = "") -> bool:
        self.calls.append((text, duration_ms, subtitle))
        return True


class _LegacyWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def say(self, text: str, duration_ms: int = 4000) -> bool:  # 没有 subtitle
        self.calls.append(text)
        return True


class _Host:
    """只带 `_notify` 需要的四个属性：window / pets / _active_window / island。"""

    _notify = CoreHost._notify

    def __init__(self, window) -> None:
        self.window = window
        self.pets = None
        self._active_window = window
        self.island = None


def _config(tmp_path: Path, **overrides) -> Config:
    data = {"balance_tier_color_enabled": True}
    data.update(overrides)
    return Config(tmp_path, data)


def test_subtitle_is_enabled_by_default(tmp_path: Path) -> None:
    host = CoreHost.__new__(CoreHost)
    host.config = _config(tmp_path)
    subtitle = CoreHost._balance_subtitle(host, window=None)
    assert "#e5484d" in subtitle or "#30a46c" in subtitle
    assert subtitle.startswith("DeepSeek 当前")


def test_subtitle_drops_colour_when_switched_off(tmp_path: Path) -> None:
    host = CoreHost.__new__(CoreHost)
    host.config = _config(tmp_path, balance_tier_color_enabled=False)
    subtitle = CoreHost._balance_subtitle(host, window=None)
    assert "<span" not in subtitle
    assert "DeepSeek 当前" in subtitle


def test_subtitle_honours_the_liangwen_labels(tmp_path: Path) -> None:
    host = CoreHost.__new__(CoreHost)
    host.config = _config(
        tmp_path, balance_tier_labels_mode="liangwen", balance_tier_color_enabled=False
    )
    subtitle = CoreHost._balance_subtitle(host, window=None)
    assert "梁文峰" in subtitle or "梁文谷" in subtitle


def test_notify_passes_the_subtitle_to_the_bubble() -> None:
    window = _Window()
    host = _Host(window)
    host._notify(None, "余额 ¥1.00", subtitle="DeepSeek 当前高峰 · 下一空闲 12:00")
    assert window.calls == [("余额 ¥1.00", 6000, "DeepSeek 当前高峰 · 下一空闲 12:00")]


def test_notify_still_shows_the_message_for_legacy_say_signatures() -> None:
    window = _LegacyWindow()
    host = _Host(window)
    host._notify(None, "余额 ¥1.00", subtitle="DeepSeek 当前高峰")
    assert window.calls == ["余额 ¥1.00"]
