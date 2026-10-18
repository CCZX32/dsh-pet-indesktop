# -*- coding: utf-8 -*-
"""账户用量包的设置面板（MOD 中心 ``settings.contribute`` 通道）。

字段只有四项：自动刷新开关、服务地址、刷新周期、TLS 校验；API Key 单独进
凭据库，输入框只写不回显。草稿/保存/放弃按 MOD 中心的五方法协议实现。
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from pet.settings_widgets import SettingRow

from .balance import DEFAULT_BASE_URL
from .config import AccountConfig


class AccountUsageSettings(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self._context = context
        self.config = AccountConfig(context)
        self._disposed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("账户用量（包）", self)
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel("独立于内置余额查询：自带服务地址与 Key，结果以气泡显示在桌宠上。", self)
        intro.setObjectName("settingHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.enabled = QCheckBox("按周期自动刷新", self)
        self.base_url = QLineEdit(self)
        self.base_url.setPlaceholderText(DEFAULT_BASE_URL)
        self.refresh = QSpinBox(self)
        self.refresh.setRange(0, 1440)
        self.refresh.setSuffix(" 分钟")
        self.refresh.setSpecialValueText("关闭")
        self.verify_ssl = QCheckBox("校验 TLS 证书", self)
        self.key = QLineEdit(self)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("留空则沿用已保存的 Key")
        self.key_status = QLabel("", self)
        self.key_status.setObjectName("settingHint")
        self.error = QLabel("", self)
        self.error.setObjectName("settingHint")
        self.error.setWordWrap(True)

        layout.addWidget(SettingRow("account_usage_enabled", "自动刷新", "关闭后仍可从右键菜单手动查询。", self.enabled))
        layout.addWidget(SettingRow("account_usage_base_url", "服务地址", "余额接口的根地址，例如 https://api.deepseek.com。", self.base_url))
        layout.addWidget(SettingRow("account_usage_refresh", "刷新周期", "0 表示不自动刷新；最小 1 分钟。", self.refresh))
        layout.addWidget(SettingRow("account_usage_verify_ssl", "TLS 校验", "自签证书的内网网关可以关闭。", self.verify_ssl))
        layout.addWidget(SettingRow("account_usage_key", "API Key", "只写入系统凭据库，不回显、不写配置文件。", self.key))
        layout.addWidget(self.key_status)
        layout.addWidget(self.error)
        layout.addStretch(1)

        self.reload()
        self.hide()

    # ------------------------------------------------------------ 五方法协议
    def dirty(self) -> bool:
        return not self._disposed and (bool(self.key.text()) or self._values() != self._baseline)

    def draft(self):
        return {"values": self._values(), "key_pending": bool(self.key.text())}

    def confirm_save(self) -> bool:
        if self._disposed:
            return False
        values = self._values()
        if not values["base_url"].startswith(("http://", "https://")):
            self.error.setText("服务地址必须以 http:// 或 https:// 开头。")
            return False
        self.error.setText("")
        credential_ref = self._baseline["credential_ref"]
        if self.key.text():
            try:
                credential_ref = self.config.store_secret(self.key.text(), base_url=values["base_url"])
            except Exception:
                self.error.setText("Key 写入系统凭据库失败。")
                return False
        elif values["base_url"] != self._baseline["base_url"]:
            # 旧引用绑定的是旧 endpoint，换地址后必须重新输入 Key。
            credential_ref = ""
        if not self.config.save(
            enabled=values["enabled"],
            base_url=values["base_url"],
            refresh_minutes=values["refresh_minutes"],
            verify_ssl=values["verify_ssl"],
            credential_ref=credential_ref,
        ):
            self.error.setText("配置写入失败。")
            return False
        self.key.clear()
        self.reload()
        return True

    def discard_changes(self) -> bool:
        if self._disposed:
            return False
        self.key.clear()
        self.error.setText("")
        self.reload()
        return True

    def dispose(self) -> None:
        self._disposed = True
        self.hide()
        self.deleteLater()

    # ------------------------------------------------------------ 内部
    def reload(self) -> None:
        self.config.reload()
        self.enabled.setChecked(self.config.enabled)
        self.base_url.setText(self.config.base_url)
        self.refresh.setValue(self.config.refresh_minutes)
        self.verify_ssl.setChecked(self.config.verify_ssl)
        self.key_status.setText("Key：已保存（不可回显）" if self.config.credential_ref else "Key：未保存")
        self._baseline = self._values()

    def _values(self) -> dict:
        return {
            "enabled": bool(self.enabled.isChecked()),
            "base_url": self.base_url.text().strip().rstrip("/") or DEFAULT_BASE_URL,
            "refresh_minutes": int(self.refresh.value()),
            "verify_ssl": bool(self.verify_ssl.isChecked()),
            "credential_ref": self.config.credential_ref,
        }
