"""API 能力的公开契约。

mod 只看见「服务元数据 + 一次解析结果」，**永远拿不到也不该拿到密钥**：
``ApiRequest.api_key`` 不参与 ``repr``，``ApiMetadata`` 里没有任何凭据字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True, slots=True)
class ApiMetadata:
    service_id: str
    name: str
    base_url: str
    chat_path: str = "/v1/chat/completions"
    model: str = ""
    vision_model: str = ""
    verify_ssl: bool = True
    timeout: int = 60
    balance_protocol: str = "none"
    version: str = ""


@dataclass(frozen=True, slots=True)
class ApiRequest:
    metadata: ApiMetadata
    api_key: str = field(repr=False)

    @property
    def base_url(self) -> str:
        return self.metadata.base_url

    @property
    def model(self) -> str:
        return self.metadata.model


class ApiPort(Protocol):
    def services(self) -> tuple[ApiMetadata, ...]: ...
    def metadata(self, service_id: str) -> ApiMetadata: ...
    def resolve(self, service_id: str) -> ApiRequest: ...
    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]: ...
    def open_settings(self) -> None: ...
    def fetch_balance(self, service_id: str, *, force: bool = False) -> Any: ...
