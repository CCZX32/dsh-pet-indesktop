"""Feature registration models and the closed official registry.

The official registry remains the Core-owned source for built-in/default packages
and formal signed release policy.  Local user-trusted packages use the same
neutral :class:`FeatureRegistration` shape, but their registration is derived
from a bounded manifest rather than discovered from this closed mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType

SCREEN_FEATURE_ID = "official.screen-understanding"
AI_FEATURE_ID = "official.ai-chat"
ACCOUNT_USAGE_FEATURE_ID = "official.account-usage"
MUSIC_FEATURE_ID = "official.music"
VOICE_CHIME_FEATURE_ID = "official.voice-chime"

#: ID 的**规范形**。这个串会变成 ``feature-data/<id>/`` 与 ``plugins/<id>/`` 下的目录名，
#: 所以"另一个拼法"必须被判成非法，而不是当成另一个 owner：
#:
#: * 只允许小写——NTFS 不区分大小写，``Official.Screen-Understanding`` 与
#:   ``official.screen-understanding`` 是**同一个目录**，放进来就能绕过官方闭集；
#: * 禁末尾 ``.`` / ``-``——Win32 折叠目录名的末尾点，``foo.`` 与 ``foo`` 同目录；
#: * 禁空段（``..``）与设备名首段（``nul`` / ``con.package`` 指向设备，不是目录）。
_FEATURE_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
_FACTORY_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}(?:/[A-Za-z0-9_.-]{1,128})?\Z")
_EXECUTION_KINDS = frozenset({"host-only", "host-worker"})
#: Windows 设备名（与 ``plugins/package_trust._DEVICE`` / ``mod_management._DEVICE_ID``
#: 同一份判据）：按首个 ``.`` 之前的段比，因为 ``nul.txt`` 同样是设备。
_DEVICE_NAME = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\Z", re.IGNORECASE)


@dataclass(frozen=True)
class FeatureRegistration:
    """Neutral package registration used by official and local package paths."""

    id: str
    factory: str
    execution_kind: str
    capabilities: frozenset[str]

    def __post_init__(self):
        if not is_valid_feature_id(self.id) or not isinstance(self.factory, str) or not _FACTORY_ID.fullmatch(self.factory):
            raise ValueError("invalid feature registration")
        if self.execution_kind not in _EXECUTION_KINDS:
            raise ValueError("invalid feature execution kind")
        capabilities = frozenset(self.capabilities)
        if any(not isinstance(capability, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}\Z", capability) for capability in capabilities):
            raise ValueError("invalid feature capabilities")
        object.__setattr__(self, "capabilities", capabilities)


# Compatibility name retained for existing official-only callers.
OfficialFeature = FeatureRegistration


def is_valid_feature_id(feature_id: object) -> bool:
    """ID 是否处于**规范形**（唯一一处判据，见 :data:`_FEATURE_ID`）。

    收口的理由：这个串同时是目录名（``feature-data/<id>/``、``plugins/<id>/``）与官方
    闭集的查表键。NTFS 不分大小写、Win32 折叠末尾点，所以"看着像另一个 ID"的拼法在
    文件系统上落进同一个目录——一处放松就等于让两个 owner 共用一份数据目录。
    """
    if not isinstance(feature_id, str) or not _FEATURE_ID.fullmatch(feature_id):
        return False
    if ".." in feature_id or feature_id.endswith((".", "-")):
        return False
    return not _DEVICE_NAME.fullmatch(feature_id.split(".", 1)[0])


def is_valid_factory_id(factory: object) -> bool:
    return isinstance(factory, str) and bool(_FACTORY_ID.fullmatch(factory))


OFFICIAL_FEATURES = MappingProxyType(
    {
        SCREEN_FEATURE_ID: FeatureRegistration(
            SCREEN_FEATURE_ID, "screen-understanding/v1", "host-worker", frozenset({"screen.capture", "network.http", "settings.contribute", "menu.contribute"})
        ),
        AI_FEATURE_ID: FeatureRegistration(
            AI_FEATURE_ID,
            "ai-chat/v1",
            "host-only",
            frozenset({"network.http", "settings.contribute", "menu.contribute", "chat.contribute", "files.user-selected.read"}),
        ),
        ACCOUNT_USAGE_FEATURE_ID: FeatureRegistration(
            ACCOUNT_USAGE_FEATURE_ID,
            "account-usage/v1",
            "host-only",
            frozenset({"network.http", "settings.contribute", "menu.contribute"}),
        ),
        MUSIC_FEATURE_ID: FeatureRegistration(
            MUSIC_FEATURE_ID,
            "music/v1",
            "host-only",
            frozenset({"settings.contribute", "menu.contribute", "process.spawn"}),
        ),
        VOICE_CHIME_FEATURE_ID: FeatureRegistration(
            VOICE_CHIME_FEATURE_ID,
            "voice-chime/v1",
            "host-only",
            frozenset({"settings.contribute", "menu.contribute", "audio.speak"}),
        ),
    }
)


def official_feature(feature_id: str) -> FeatureRegistration:
    # 闭集按**规范形**比较：非规范形（大小写 / 末尾点 / 设备名）先被 ID 校验拒掉，
    # 再查表——否则 `Official.Screen-Understanding` 在 NTFS 上会与官方
    # `official.screen-understanding` 落进同一个数据目录，闭集就白设了。
    if not is_valid_feature_id(feature_id) or feature_id not in OFFICIAL_FEATURES:
        raise ValueError("unsupported official feature")
    return OFFICIAL_FEATURES[feature_id]


# Retained public API for existing built-in distributions and screen bindings.
SCREEN_OWNER = SCREEN_FEATURE_ID
AI_OWNER = AI_FEATURE_ID

# 未移植：DLC 的 ``default_feature_host``（组装 ``FeatureHost`` + 内置识屏宿主）。
# 它是功能扩展**宿主运行时**的入口，闭包是 ``pet/feature_distribution`` +
# ``pet/plugins/feature_host`` + ``features/screen_understanding/host``，
# 均不在本片范围；本仓库没有该成员，接入时随宿主运行时一并落。
