"""流式对话传输：core 唯一的 chat HTTP/SSE 出口。

mod 只看到 :class:`petcore.contracts.api.ApiPort`；代理兜底、取消、超时和错误分类
都在这里，``petcore/chat/`` 与会话存储保持零网络依赖（架构守卫）。
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..contracts.api import ApiRequest, WebSearchOptions
from ..net import errors
from ..net import websearch
from ..net.http import urlopen

STREAM_DONE = "[DONE]"
DEFAULT_MODEL = "deepseek-chat"

#: 联网检索阶段最多几轮 planner / 每轮最多几次工具调用（同主分支）。
_MAX_RESEARCH_ROUNDS = 3
_MAX_CALLS_PER_ROUND = 4
_MAX_NOTES_CHARS = 24_000

_PLANNER_PROMPT = (
    "你是联网检索助手，当前时间：{today}。请判断：回答用户最后一条消息，是否需要联网"
    "获取最新、实时或你不确定的事实信息（新闻、天气、价格、版本、赛事、政策、具体数据、"
    "某个人/产品/事件的现状等）。\n"
    "- 需要：调用 web_search 搜索，关键词要精炼，必要时换角度多搜几次；摘要信息不足时，"
    "可调用 fetch_url 阅读最相关的网页。\n"
    "- 不需要（闲聊、常识、写作、翻译、代码、情感陪伴等）：不要调用任何工具，直接回复"
    "「无需搜索」。\n"
    "你只负责收集资料，不要直接回答用户的问题。"
)
_CONTEXT_PROMPT = (
    "【联网搜索结果】（当前时间：{today}；以下资料是刚刚联网获取的）\n\n{notes}\n\n"
    "请结合以上资料回答用户最新的问题：优先采用资料中的最新信息；资料与你已有知识冲突时"
    "以资料为准；资料不足以回答时如实说明。如果引用了资料，在回答末尾用「参考来源」"
    "简短列出对应链接。"
)
_WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "用搜索引擎联网搜索，获取最新/实时信息。返回若干条标题、链接和摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "精炼的搜索关键词"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "读取指定网页的正文内容，用于搜索摘要不够详细时深入阅读。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要读取的网页地址（http/https）"}
                },
                "required": ["url"],
            },
        },
    },
]


class ChatCancelled(RuntimeError):
    """调用方主动取消；不算错误，界面显示「已停止」。"""


class ChatTruncated(RuntimeError):
    """只输出思维链就撞上 max_tokens，没来得及给出回答（同主分支提示）。"""

    reason = errors.PROTOCOL


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    chunks: int = 0
    finish_reason: str = ""
    cancelled: bool = False
    reasoning: str = ""


def _sends_thinking_param(request: ApiRequest, mode: str) -> bool:
    """auto 模式只对 DeepSeek 官方地址发送 thinking，避免严格校验的服务报错。"""
    return mode != "auto" or "deepseek.com" in str(request.base_url or "").lower()


def thinking_payload(
    request: ApiRequest,
    mode: str = "auto",
    effort: str = "",
    *,
    force_disable: bool = False,
) -> dict[str, Any]:
    """DeepSeek V4 格式：``thinking={'type': enabled}`` + ``reasoning_effort``。"""
    mode = str(mode or "auto")
    if force_disable:
        return {"thinking": {"type": "disabled"}} if _sends_thinking_param(request, mode) else {}
    if mode == "enabled":
        level = str(effort or "high")
        if level not in {"low", "high", "max"}:
            level = "high"
        return {"thinking": {"type": "enabled"}, "reasoning_effort": level}
    if mode == "disabled":
        return {"thinking": {"type": "disabled"}}
    return {}


def _extract_delta(data: Mapping[str, Any]) -> tuple[str, str, str]:
    """(增量文本, 思维链增量, finish_reason)；兼容流式与一次性返回两种形状。"""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", "", ""
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    delta = first.get("delta") if isinstance(first.get("delta"), Mapping) else {}
    message = first.get("message") if isinstance(first.get("message"), Mapping) else {}
    text = delta.get("content") or message.get("content") or ""
    if not isinstance(text, str):
        text = ""
    # reasoning_content：DeepSeek/智谱等思考模型；reasoning：OpenRouter 等网关的同义字段。
    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
    if not isinstance(reasoning, str):
        reasoning = ""
    finish = first.get("finish_reason") or ""
    return text, reasoning, str(finish or "")


def build_payload(
    request: ApiRequest,
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str = "",
    temperature: float | None = None,
    stream: bool = True,
    thinking: str = "auto",
    reasoning_effort: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": str(model or request.metadata.model or DEFAULT_MODEL),
        "messages": [dict(item) for item in messages],
        "stream": bool(stream),
    }
    if temperature is not None:
        payload["temperature"] = max(0.0, min(2.0, float(temperature)))
    payload.update(thinking_payload(request, thinking, reasoning_effort))
    return payload


def _build_request(
    request: ApiRequest, payload: dict[str, Any], *, accept: str = "text/event-stream"
) -> urllib.request.Request:
    url = request.base_url.rstrip("/") + request.metadata.chat_path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
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


def _status(on_status, text: str) -> None:
    if on_status is not None:
        on_status(str(text))


def _cancelled(cancel) -> bool:
    return cancel is not None and bool(getattr(cancel, "is_set", lambda: False)())


def _today_text() -> str:
    return time.strftime("%Y-%m-%d")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, Mapping) and item.get("type") == "image_url":
                parts.append("[图片]")
        return "\n".join(parts)
    return str(content or "")


def _recent_dialogue(
    messages: Sequence[Mapping[str, Any]], limit: int = 6, max_chars: int = 2000
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, Mapping) or message.get("role") not in ("user", "assistant"):
            continue
        text = _text_of(message.get("content")).strip()
        if text:
            out.append({"role": message["role"], "content": text[-max_chars:]})
    out = out[-limit:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def inject_search_context(
    messages: Sequence[Mapping[str, Any]], notes: str
) -> list[dict[str, Any]]:
    """把检索资料并入首条 system 消息（无 system 时插到最前），不改动原列表。"""
    block = _CONTEXT_PROMPT.format(today=_today_text(), notes=notes)
    prepared = [dict(item) if isinstance(item, Mapping) else item for item in messages]
    if (
        prepared
        and isinstance(prepared[0], Mapping)
        and prepared[0].get("role") == "system"
        and isinstance(prepared[0].get("content"), str)
    ):
        prepared[0]["content"] = (
            str(prepared[0]["content"]).rstrip() + "\n\n" + block
        ).strip()
    else:
        prepared.insert(0, {"role": "system", "content": block})
    return prepared


def _post_json(
    request: ApiRequest,
    payload: dict[str, Any],
    *,
    timeout: float,
    opener=None,
) -> Mapping[str, Any]:
    """非流式 JSON 请求（联网检索的 planner 用）。"""
    http_request = _build_request(request, payload, accept="application/json")
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
    try:
        raw = response.read(4 * 1024 * 1024)
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise errors.NetworkError(reason=errors.PROTOCOL) from None
    if not isinstance(data, Mapping):
        raise errors.NetworkError(reason=errors.PROTOCOL)
    return data


def _run_tool(
    name: str,
    args: Mapping[str, Any],
    *,
    options: WebSearchOptions,
    search_key: str,
    timeout: float,
    verify_ssl: bool,
    opener=None,
) -> tuple[str, bool, list[str]]:
    """执行一次工具调用 → (给模型的结果文本, 是否成功, 状态提示列表)。"""
    if name == "web_search":
        query = str(args.get("query", "")).strip()
        lines = [f"🔍 正在搜索：{query}"]
        try:
            results = websearch.search(
                query,
                engine=options.engine,
                api_key=search_key,
                limit=options.max_results,
                timeout=timeout,
                verify_ssl=verify_ssl,
                opener=opener,
            )
        except Exception as exc:  # noqa: BLE001 - 检索失败不打断回答
            text = f"搜索「{query}」失败：{exc}"
            return text, False, lines + ["　" + text]
        return (
            websearch.format_results(query, results),
            bool(results),
            lines + [f"　找到 {len(results)} 条结果"],
        )
    if name == "fetch_url":
        url = str(args.get("url", "")).strip()
        lines = [f"📄 正在阅读：{url}"]
        try:
            text = websearch.fetch_page_text(
                url, timeout=timeout, verify_ssl=verify_ssl, opener=opener
            )
        except Exception as exc:  # noqa: BLE001
            text = f"读取网页 {url} 失败：{exc}"
            return text, False, lines + ["　" + text]
        return f"网页 {url} 的内容：\n{text}", True, lines
    return f"未知工具：{name}", False, []


def research(
    request: ApiRequest,
    messages: Sequence[Mapping[str, Any]],
    *,
    options: WebSearchOptions,
    search_key: str = "",
    model: str = "",
    timeout: float = 60.0,
    on_status: Callable[[str], None] | None = None,
    cancel: Any | None = None,
    opener=None,
) -> str:
    """检索阶段：非思考模式 + 工具调用，让模型决定搜什么；返回资料文本。

    单独走一轮非思考请求，而不是在正式回答里挂 tools：DeepSeek 思考模式带 tools 时
    要求回传历史所有轮次的 ``reasoning_content``（缺失即 400），而会话历史不保存
    思维链。任何检索失败都降级成状态行，绝不阻断正式回答。
    """
    dialogue = _recent_dialogue(messages)
    if not dialogue:
        return ""
    tools = list(_WEB_TOOLS) if options.fetch_pages else _WEB_TOOLS[:1]
    planner: list[dict[str, Any]] = [
        {"role": "system", "content": _PLANNER_PROMPT.format(today=_today_text())},
        *dialogue,
    ]
    notes: list[str] = []
    used = 0
    searched = False
    net_timeout = max(5.0, min(float(timeout), 20.0))
    _status(on_status, "正在判断是否需要联网…")
    for round_no in range(_MAX_RESEARCH_ROUNDS):
        if _cancelled(cancel):
            return ""
        payload: dict[str, Any] = {
            "model": str(model or request.metadata.model or DEFAULT_MODEL),
            "messages": planner,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
            "max_tokens": 1024,
            "temperature": 0.3,
        }
        payload.update(thinking_payload(request, "auto", "", force_disable=True))
        try:
            data = _post_json(request, payload, timeout=timeout, opener=opener)
        except Exception as exc:  # noqa: BLE001 - 检索不可用不影响回答
            if _cancelled(cancel):
                return ""
            if round_no == 0:
                _status(on_status, f"联网检索不可用（{exc}），将直接回答")
                return ""
            break
        choices = data.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, Mapping) else None
        if not isinstance(message, Mapping):
            if round_no == 0:
                _status(on_status, "联网检索返回了无法识别的响应，将直接回答")
                return ""
            break
        calls = [
            call
            for call in (message.get("tool_calls") or [])
            if isinstance(call, Mapping) and isinstance(call.get("function"), Mapping)
        ][:_MAX_CALLS_PER_ROUND]
        if not calls:
            break
        searched = True
        assistant: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": calls,
        }
        if message.get("reasoning_content"):
            assistant["reasoning_content"] = message["reasoning_content"]
        planner.append(assistant)
        for call in calls:
            if _cancelled(cancel):
                return ""
            function = call.get("function") or {}
            try:
                args = json.loads(function.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            text, ok, lines = _run_tool(
                str(function.get("name", "")),
                args if isinstance(args, Mapping) else {},
                options=options,
                search_key=search_key,
                timeout=net_timeout,
                verify_ssl=request.metadata.verify_ssl,
                opener=opener,
            )
            for line in lines:
                _status(on_status, line)
            if ok and used < _MAX_NOTES_CHARS:
                note = text[: _MAX_NOTES_CHARS - used]
                notes.append(note)
                used += len(note)
            planner.append(
                {"role": "tool", "tool_call_id": str(call.get("id", "")), "content": text}
            )
    if not searched:
        _status(on_status, "无需联网，直接回答")
    return "\n\n---\n\n".join(notes)


def stream_chat(
    request: ApiRequest,
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str = "",
    temperature: float | None = None,
    timeout: float = 60.0,
    on_delta: Callable[[str], None] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    thinking: str = "auto",
    reasoning_effort: str = "",
    web_search: WebSearchOptions | None = None,
    search_key: str = "",
    cancel: Any | None = None,
    opener=None,
) -> ChatResult:
    """POST ``chat_path`` 并把 SSE 增量逐段回调；返回完整文本。

    ``cancel`` 只要有 ``is_set()`` 即可（``threading.Event``）；每收到一行检查一次。
    失败统一抛 :class:`petcore.net.errors.NetworkError` 的子类，界面只认 ``reason``。
    联网开启时先跑 :func:`research`（资料并入 system），再走正式回答。
    """
    conversation = [dict(item) if isinstance(item, Mapping) else item for item in messages]
    if web_search is not None and not _cancelled(cancel):
        notes = research(
            request,
            conversation,
            options=web_search,
            search_key=search_key,
            model=model,
            timeout=timeout,
            on_status=on_status,
            cancel=cancel,
            opener=opener,
        )
        if _cancelled(cancel):
            return ChatResult(text="", cancelled=True)
        if notes:
            conversation = inject_search_context(conversation, notes)
            _status(on_status, "已获取联网资料，正在组织回答…")

    payload = build_payload(
        request,
        conversation,
        model=model,
        temperature=temperature,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
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
    reasoning_parts: list[str] = []
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
            delta, reasoning, finish = _extract_delta(data)
            if finish:
                finish_reason = finish
            if reasoning:
                reasoning_parts.append(reasoning)
                if on_reasoning is not None:
                    on_reasoning(reasoning)
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
        text, reasoning, finish = _extract_delta(data)
        if reasoning:
            reasoning_parts.append(reasoning)
            if on_reasoning is not None:
                on_reasoning(reasoning)
        if text:
            parts.append(text)
            chunks += 1
            if on_delta is not None:
                on_delta(text)
        if finish:
            finish_reason = finish

    if (
        reasoning_parts
        and not parts
        and finish_reason == "length"
        and not cancelled
        and not _cancelled(cancel)
    ):
        raise ChatTruncated(
            "深度思考用完了「最大输出 Token」，还没来得及给出回答。"
            "请换一个更小的思考强度或在服务端调大输出上限。"
        )

    return ChatResult(
        text="".join(parts),
        chunks=chunks,
        finish_reason=finish_reason,
        cancelled=cancelled,
        reasoning="".join(reasoning_parts),
    )
