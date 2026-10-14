# -*- coding: utf-8 -*-
"""共享的 HTTP/TLS 传输原语（零 Qt、零聊天业务、零凭据解析）。

从 ``pet/chat/providers.py`` 整体搬出，唯一理由是**依赖方向**：这些原语
（SSL 上下文、浏览器特征头、OpenAI 兼容端点拼接）本身就是「无业务」的，
而 ``pet/chat/providers.py`` 属于 ``pet.chat`` 包——导入它必然先执行
``pet/chat/__init__.py``，连带把 ``pet.chat.service``（Qt）拉进任何调用方。

主动识屏 worker 跑在**独立子进程**里，它要用视觉请求的传输路径但绝不能
把 Qt 拉进子进程（S3 的硬约束，见 ``tests/test_workers_entry.py`` 的导入探针）。
搬出之后 ``pet/vision.py`` 只依赖本模块即可完成一次视觉请求。

``pet/chat/providers.py`` 原样再导出这几个名字，既有调用点不受影响。
"""

from __future__ import annotations

import functools
import re as _re
import ssl

try:
    import certifi
except Exception:  # 未安装/未打进包时回退系统默认 CA 库
    certifi = None


def _make_ssl_context(verify: bool):
    """按配置构造 SSL 上下文：verify=False 跳过证书校验（本地网关/自签名）；
    verify=True 优先使用 certifi 的 CA 包（PyInstaller 需 --collect-all certifi）。

    构造结果按 ``verify`` 缓存：SSLContext 建好后只读复用是安全的，而
    ``create_default_context(cafile=...)`` 每次新建实测要 ~0.5 s（certifi 加载，
    2026-10-14 本机实测）——截图翻译/视觉问答这种"点一下就等"的短调用不该
    每次都付这笔钱。
    """
    if not verify:
        return ssl._create_unverified_context()
    return _verified_ssl_context()


@functools.lru_cache(maxsize=1)
def _verified_ssl_context():
    try:
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ssl.create_default_context()


def _is_cert_verify_error(reason) -> bool:
    text = str(reason).lower()
    return 'ssl' in text or 'certificate' in text or 'tls' in text


_CERT_HINT = '；如为代理/梯子拦截或自签名证书，可在 AI 设置中勾选"跳过 SSL 证书验证"后重试'


def build_browser_headers(extra: dict | None = None) -> dict[str, str]:
    """构造带浏览器特征的请求头，降低 Cloudflare 等 WAF 的机器人误判。

    urllib 默认 User-Agent 是 Python-urllib/3.x，容易被识别为脚本机器人
    （如 Cloudflare error 1010）。这里提供常见浏览器头，业务头经 extra 覆盖。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    }
    if extra:
        headers.update(extra)
    return headers


def normalize_chat_endpoint(base_url, chat_path='/v1/chat/completions'):
    base = str(base_url or '').strip().rstrip('/')
    path = str(chat_path or '/v1/chat/completions').strip()
    path = path if path.startswith('/') else '/' + path
    if base.endswith('/chat/completions'):
        return base
    # base 已带版本段（/v1、/v4 等 OpenAI 兼容路径，如智谱 /api/paas/v4）→ 只补 /chat/completions
    if path == '/v1/chat/completions' and _re.search(r'/v\d+$', base):
        return base + '/chat/completions'
    return base + path


__all__ = [
    "_CERT_HINT",
    "_is_cert_verify_error",
    "_make_ssl_context",
    "build_browser_headers",
    "normalize_chat_endpoint",
]
