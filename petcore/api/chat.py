"""流式对话传输：core 唯一的 chat HTTP/SSE 出口。

mod 只看到 :class:`petcore.contracts.api.ApiPort`；代理兜底、取消、超时和错误分类
都在这里，``petcore/chat/`` 与会话存储保持零网络依赖（架构守卫）。
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..contracts.api import ApiRequest
from ..net import errors
from ..net.http import urlopen

STREAM_DONE = "[DONE]"
DEFAULT_MODEL = "deepseek-chat"


class ChatCancelled(RuntimeError):
    """调用方主动取消；不算错误，界面显示「已停止」。"""


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    chunks: int = 0
    finish_reason: str = ""
    cancelled: bool = False


def _extract_delta(data: Mapping[str, Any]) -> tuple[str, str]:
    """(增量文本, finish_reason)；兼容流式与一次性返回两种形状。"""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", ""
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    delta = first.get("delta") if isinstance(first.get("delta"), Mapping) else {}
    message = first.get("message") if isinstance(first.get("message"), Mapping) else {}
    text = delta.get("content") or message.get("content") or ""
    if not isinstance(text, str):
        text = ""
    finish = first.get("finish_reason") or ""
    return text, str(finish or "")


def build_payload(
    request: ApiRequest,
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str = "",
    temperature: float | None = None,
    stream: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": str(model or request.metadata.model or DEFAULT_MODEL),
        "messages": [dict(item) for item in messages],
        "stream": bool(stream),
    }
    if temperature is not None:
        payload["temperature"] = max(0.0, min(2.0, float(temperature)))
    return payload


def _build_request(request: ApiRequest, payload: dict[str, Any]) -> urllib.request.Request:
    url = request.base_url.rstrip("/") + request.metadata.chat_path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if request.api_key:
        headers["Authorization"] = f"Bearer {request.api_key}"
    return urllib.request.Request(url, data=body, headers=headers, method="POST")


def _context(request: ApiRequest):
    if request.metadata.verify_ssl:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def stream_chat(
    request: ApiRequest,
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str = "",
    temperature: float | None = None,
    timeout: float = 60.0,
    on_delta: Callable[[str], None] | None = None,
    cancel: Any | None = None,
    opener=None,
) -> ChatResult:
    """POST ``chat_path`` 并把 SSE 增量逐段回调；返回完整文本。

    ``cancel`` 只要有 ``is_set()`` 即可（``threading.Event``）；每收到一行检查一次。
    失败统一抛 :class:`petcore.net.errors.NetworkError` 的子类，界面只认 ``reason``。
    """
    payload = build_payload(request, messages, model=model, temperature=temperature)
    http_request = _build_request(request, payload)
    try:
        response = urlopen(
            http_request,
            timeout=max(1.0, float(timeout)),
            context=_context(request),
            opener=opener,
        )
    except urllib.error.HTTPError as exc:
        raise errors.http_error(exc) from None
    except Exception as exc:  # noqa: BLE001 - 传输失败交给统一分类
        reason = errors.classify_exception(exc)
        if reason is None:
            raise
        raise errors.NetworkError(reason=reason) from exc

    parts: list[str] = []
    chunks = 0
    finish_reason = ""
    plain_lines: list[str] = []
    saw_sse = False
    cancelled = False
    try:
        for raw in response:
            if cancel is not None and getattr(cancel, "is_set", lambda: False)():
                cancelled = True
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            if line.startswith(":"):
                continue
            if not line.startswith("data:"):
                plain_lines.append(line)
                continue
            saw_sse = True
            data_text = line[5:].strip()
            if data_text == STREAM_DONE:
                break
            try:
                data = json.loads(data_text)
            except json.JSONDecodeError:
                raise errors.NetworkError(reason=errors.PROTOCOL) from None
            if not isinstance(data, Mapping):
                raise errors.NetworkError(reason=errors.PROTOCOL)
            delta, finish = _extract_delta(data)
            if finish:
                finish_reason = finish
            if delta:
                parts.append(delta)
                chunks += 1
                if on_delta is not None:
                    on_delta(delta)
    except errors.NetworkError:
        raise
    except Exception as exc:  # noqa: BLE001 - 读流中断也归入稳定分类
        reason = errors.classify_exception(exc)
        if reason is None:
            raise
        raise errors.NetworkError(reason=reason) from exc
    finally:
        try:
            response.close()
        except Exception:
            pass

    if not saw_sse and plain_lines:
        try:
            data = json.loads("\n".join(plain_lines))
        except json.JSONDecodeError:
            raise errors.NetworkError(reason=errors.PROTOCOL) from None
        if not isinstance(data, Mapping):
            raise errors.NetworkError(reason=errors.PROTOCOL)
        text, finish = _extract_delta(data)
        if text:
            parts.append(text)
            chunks += 1
            if on_delta is not None:
                on_delta(text)
        if finish:
            finish_reason = finish

    return ChatResult(
        text="".join(parts),
        chunks=chunks,
        finish_reason=finish_reason,
        cancelled=cancelled,
    )
