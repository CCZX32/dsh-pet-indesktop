"""ai.chat 的 prompt 与消息组装（纯函数，无 Qt、无网络）。

运行时的职责只剩「什么时候发」；这里负责「发什么」，便于单独测试文案与历史形状。
"""

from __future__ import annotations

DEFAULT_PROMPT = (
    "你是「{name}」，一只住在主人桌面上的鲸鱼娘。用简短、口语化的中文回答，"
    "一次最多三句话；不确定就直说，不要编造。"
)

LOOK_SCREEN_PROMPT = "看看我的屏幕，用一两句话说说你现在看到什么。"
SCREEN_QUESTION_PROMPT = "看看这块区域里是什么，说清内容，能给出判断或建议时就直接给。"


def system_prompt(configured: str, character_name: str) -> str:
    text = str(configured or "").strip()
    return text or DEFAULT_PROMPT.format(name=character_name)


def _text_turns(history, limit: int) -> list[dict]:
    turns: list[dict] = []
    for item in list(history or [])[-max(1, int(limit)) :]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        content = str(item.get("content") or "")
        if content.strip():
            turns.append({"role": role, "content": content})
    return turns


def look_screen_messages(system: str, png_b64: str, app_info: str = "") -> list[dict]:
    prompt = LOOK_SCREEN_PROMPT
    if app_info:
        prompt += f"\n（前台应用：{app_info}）"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + str(png_b64)},
                },
            ],
        },
    ]


def chat_messages(
    system: str,
    history,
    text: str,
    image_urls: list[str] | None = None,
    *,
    limit: int = 40,
) -> list[dict]:
    """主对话消息：历史 + 本轮问题；带图时本轮改成多模态消息。"""
    turns = _text_turns(history, limit)
    images = [url for url in (image_urls or []) if url]
    messages = [{"role": "system", "content": system}]
    if not images:
        messages.extend(turns)
        return messages
    # controller 在回调前已把本轮问题追加进会话；带图时会重发多模态版本，
    # 先去掉最后那条同文纯文本，避免同一句话出现两次。
    if (
        turns
        and turns[-1].get("role") == "user"
        and str(turns[-1].get("content") or "").strip() == str(text or "").strip()
    ):
        turns = turns[:-1]
    messages.extend(turns)
    messages.append(
        {
            "role": "user",
            "content": [{"type": "text", "text": str(text or "")}]
            + [{"type": "image_url", "image_url": {"url": url}} for url in images],
        }
    )
    return messages


def ask_messages(
    system: str,
    history,
    question: str,
    image_url: str,
    *,
    limit: int = 40,
) -> list[dict]:
    """截图问答消息：图只挂在本会话第一条 user 历史（或本轮问题）上。"""
    turns = _text_turns(history, limit)
    messages = [{"role": "system", "content": system}]
    attached = False
    for item in turns:
        if item["role"] == "user" and not attached:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": item["content"]},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            )
            attached = True
        else:
            messages.append(item)
    text = str(question or "").strip() or SCREEN_QUESTION_PROMPT
    if attached:
        messages.append({"role": "user", "content": text})
    else:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        )
    return messages
