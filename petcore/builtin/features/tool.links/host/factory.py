from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.ui.settings.base import SettingsPage, make_button, value_field

DEEPSEEK_WEB_URL = "https://chat.deepseek.com/"
GITHUB_URL = "https://github.com/MerZlin/dsh-pet-indesktop"
QUARK_URL = "https://pan.quark.cn/"


class LinksRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {
            "deepseek_web": self._open_deepseek,
            "github_project": self._open_github,
            "quark_download": self._open_quark,
        }

    def _open(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _open_deepseek(self) -> None:
        self._open(DEEPSEEK_WEB_URL)

    def _open_github(self) -> None:
        self._open(GITHUB_URL)

    def _open_quark(self) -> None:
        self._open(QUARK_URL)

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class LinksPage(SettingsPage):
    title = "链接与项目"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        card = self.section("打开")
        for label, url in (
            ("DeepSeek 网页版", DEEPSEEK_WEB_URL),
            ("GitHub 项目页", GITHUB_URL),
            ("夸克网盘", QUARK_URL),
        ):
            card.add_row(label, value_field(url, self))
            button = make_button("打开", self)
            button.clicked.connect(lambda _checked=False, target=url: QDesktopServices.openUrl(QUrl(target)))
            card.add_buttons([button])
        self.add_note("这些入口只打开浏览器，不发起网络请求，也不需要登录凭据。")

    def keywords(self) -> list[str]:
        return ["链接", "项目", "DeepSeek", "GitHub", "夸克", "links", "web"]


def create_host(_context):
    return FeatureDefinition(
        owner="tool.links",
        contributions=(
            Contribution(
                kind="menu",
                id="deepseek_web",
                data={"label": "打开网页版 DeepSeek", "command": "deepseek_web", "order": 80, "icon": "web"},
            ),
            Contribution(
                kind="menu",
                id="github_project",
                data={"label": "GitHub 项目页", "command": "github_project", "order": 81, "icon": "web"},
            ),
            Contribution(
                kind="menu",
                id="quark_download",
                data={"label": "夸克网盘下载", "command": "quark_download", "order": 82, "icon": "download"},
            ),
            Contribution(
                kind="settings_page",
                id="links",
                data={"host_page": "about", "title": "链接与项目", "order": 700, "icon": "web"},
            ),
        ),
        runtime_factory=LinksRuntime,
        settings_factory=LinksPage,
    )
