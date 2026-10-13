# -*- coding: utf-8 -*-
"""Optional generic API ABI. Metadata carries no credential references or secrets.

Ported from the DLC branch ``pet/api_ports.py``.  **本仓库只落地 ABI，不落地实现**
（DLC 融合 D2-d）：DLC 侧 ``CoreApiConfiguration`` 把该端口接到凭据解析与供应商
配置上，这条链要动凭据存储与网络策略，不与 MOD 运行时同批交付。因此
:func:`unsupported_api_port` 返回的端口**每一个方法都抛固定码
``unsupported_capability``**——不返回半成品对象、不静默 ``None``、不带路径或凭据。

未验证项：本仓库没有任何一处发起过该端口背后的真实请求，也没有凭据解析实现。
"""

from dataclasses import dataclass, field
from typing import Callable, NoReturn

#: 端口不可用时的固定码（诊断白名单口径：只有码，没有路径/凭据/服务名）。
UNSUPPORTED_CAPABILITY = "unsupported_capability"


@dataclass(frozen=True, slots=True)
class ApiMetadata:
    service_id: str
    name: str
    base_url: str
    chat_path: str
    model: str
    verify_ssl: bool
    timeout: int
    balance_protocol: str
    version: str
    authorization_version: str = ""
    credential_source: str = ""
    fallback_model: str = ""


@dataclass(frozen=True, slots=True)
class ApiRequest:
    metadata: ApiMetadata
    api_key: str = field(repr=False)

    @property
    def base_url(self):
        return self.metadata.base_url

    @property
    def model(self):
        return self.metadata.model


@dataclass(frozen=True, slots=True)
class FeatureApiPort:
    metadata: Callable[[str], ApiMetadata]
    effective_version: Callable[[str], str]
    resolve: Callable[[str], ApiRequest]
    subscribe: Callable[[Callable], Callable]
    open_settings: Callable[[], None]


class CapabilityUnsupported(RuntimeError):
    """本拓扑未接上的端口：固定码，消息里不带服务名、路径或凭据。"""

    def __init__(self) -> None:
        self.code = UNSUPPORTED_CAPABILITY
        super().__init__(UNSUPPORTED_CAPABILITY)


def unsupported_api_port() -> FeatureApiPort:
    """一个**不会**假装可用的 api 端口（D2-d 未落地：调用即失败，不是空对象）。"""

    def _refuse(*_args, **_kwargs) -> NoReturn:
        raise CapabilityUnsupported()

    return FeatureApiPort(_refuse, _refuse, _refuse, _refuse, _refuse)
