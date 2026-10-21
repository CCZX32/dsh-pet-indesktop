from __future__ import annotations

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_button, make_checkbox


def _summary() -> str:
    """本机网络信息（不联网）：累计流量 + 前两条 IPv4/IPv6 地址。"""
    try:
        import psutil
    except Exception:
        return "网络信息：本机缺少 psutil，暂时读不到网卡与流量。"
    try:
        counters = psutil.net_io_counters()
        addresses = []
        for name, values in psutil.net_if_addrs().items():
            for value in values:
                if value.family.name in {"AF_INET", "AF_INET6"}:
                    addresses.append(f"{name} {value.address}")
        head = (
            f"网络信息：发送 {counters.bytes_sent / 1024 / 1024:.1f} MB / "
            f"接收 {counters.bytes_recv / 1024 / 1024:.1f} MB"
        )
        body = "；".join(addresses[:2]) if addresses else "没有可用网卡地址"
        return "\n".join([head, body, "（本机信息，不联网）"])
    except Exception:
        return "网络信息：读取失败，请稍后再试。"


class NetworkRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {"show": self.show}

    def show(self) -> None:
        config = getattr(self.context.host, "config", None)
        if config is not None and not bool(config.get("network_info_enabled", True)):
            return
        presentation = self.context.ports.presentation
        if presentation is not None:
            # 用户主动点的命令：免打扰期间也要给反馈。
            presentation.say(_summary(), duration_ms=7000, force=True)

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class NetworkPage(SettingsPage):
    title = "网络信息"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = bool(self.config().get("network_info_enabled", True))
        card = self.section("本机")
        self.enabled = make_checkbox(self)
        self.enabled.setChecked(self._initial)
        self.enabled.toggled.connect(self._on_changed)
        card.add_row("启用网络信息", self.enabled, "在气泡里显示本机网卡地址与累计流量；不发起外部请求。")
        self.preview_button = make_button("现在查看一次", self)
        self.preview_button.clicked.connect(self._preview)
        card.add_row("立即查看", self.preview_button, "等同右键菜单「扩展 → 网络信息」，结果显示在气泡里。")

    def config(self):
        return self.host.config

    def _on_changed(self, _checked=False) -> None:
        self.config().set("network_info_enabled", self.enabled.isChecked())
        self.changed.emit()

    def _preview(self) -> None:
        provider = getattr(self.host, "presentation_port", None)
        if not callable(provider):
            return
        try:
            provider().say(_summary(), duration_ms=7000, force=True)
        except Exception:
            pass

    def dirty(self) -> bool:
        return self.enabled.isChecked() != self._initial

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self.enabled.isChecked()

    def discard_changes(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._initial)
        self.enabled.blockSignals(False)
        self.config().set("network_info_enabled", self._initial)
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["网络", "网卡", "流量", "地址", "network", "info"]


def create_host(_context):
    return FeatureDefinition(
        owner="tool.network-info",
        contributions=(
            Contribution(
                kind="menu",
                id="show",
                data={"label": "网络信息", "command": "show", "order": 85, "icon": "web"},
            ),
            Contribution(
                kind="settings_page",
                id="network",
                data={"host_page": "about", "title": "网络信息", "order": 730, "icon": "web"},
            ),
        ),
        runtime_factory=NetworkRuntime,
        settings_factory=NetworkPage,
    )
