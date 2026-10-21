"""带「系统代理不通就直连」兜底的 urlopen（移植自 `pet/http_util.py`）。

背景：Windows 的系统代理常被加速器/VPN 打开，进程退出后代理解析仍然生效，
`urllib.request.urlopen` 会照着死代理走 ⇒ 所有请求 `ConnectionRefused`。
这里的口径与主分支逐条一致：

- 先按系统代理试一次（尊重用户的加速器/VPN）；
- 只在**传输失败**时改直连重试，并把结论固化在进程内；
- 服务器明确答复（`HTTPError` 4xx/5xx）不重试也不换路——链路本来就是通的。
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from typing import Any, Callable

logger = logging.getLogger("petcore.net.http")

_force_direct = False
_direct_opener: urllib.request.OpenerDirector | None = None

OpenerFactory = Callable[[bool, Any], urllib.request.OpenerDirector]


def _opener(use_proxy: bool, context=None) -> urllib.request.OpenerDirector:
    """取 opener：``use_proxy=False`` 强制直连；``context`` 为 SSL 上下文。"""
    handlers: list[Any] = []
    if not use_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    if not handlers:
        return urllib.request.build_opener()
    if not use_proxy and context is None:
        global _direct_opener
        if _direct_opener is None:
            _direct_opener = urllib.request.build_opener(*handlers)
        return _direct_opener
    return urllib.request.build_opener(*handlers)


def force_direct() -> bool:
    """本进程是否已确定「系统代理不可用、固定直连」（诊断/测试用）。"""
    return _force_direct


def reset_transport() -> None:
    """复位传输层结论（测试隔离；网络环境变化后可显式重试代理）。"""
    global _force_direct, _direct_opener
    _force_direct = False
    _direct_opener = None


def urlopen(
    request,
    *,
    timeout: float,
    context=None,
    opener: OpenerFactory | None = None,
    **kwargs,
):
    """同 :func:`urllib.request.urlopen`，但代理连不上时自动改直连重试一次。

    ``opener`` 是测试接缝：给定时用它构造 opener，且不固化进程级结论。
    ``HTTPError`` 原样抛出；两种方式都失败时抛最后一次的传输异常。
    """
    global _force_direct
    attempts = (False,) if _force_direct else (True, False)
    build = opener or _opener
    last_exc: Exception | None = None
    for use_proxy in attempts:
        try:
            response = build(use_proxy, context).open(request, timeout=timeout, **kwargs)
        except urllib.error.HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001 - 传输失败：换下一种方式再试
            last_exc = exc
            continue
        if opener is None and not use_proxy and not _force_direct:
            _force_direct = True
            logger.info(
                "网络请求改走直连：系统代理不可用（%s）", type(last_exc).__name__
            )
        return response
    assert last_exc is not None
    raise last_exc
