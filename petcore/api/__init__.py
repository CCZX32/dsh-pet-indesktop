"""API 能力：服务规格、``api.json`` 存储、钥匙串凭据与连通性探测。"""

from __future__ import annotations

from ..contracts.api import ApiMetadata, ApiRequest
from .credentials import KeyringCredentials
from .probe import probe_text
from .spec import ApiService, validate_endpoint
from .store import ApiStore

__all__ = [
    "ApiMetadata",
    "ApiRequest",
    "ApiService",
    "ApiStore",
    "KeyringCredentials",
    "probe_text",
    "validate_endpoint",
]
