"""ai.chat 的稳定标识与节流参数。"""

from __future__ import annotations

OWNER = "ai.chat"

#: 发给模型的历史轮数上限（按消息条数计，不是问答对数）。
MAX_HISTORY = 40

#: 快速对话只带最近几轮，气泡不是完整会话窗。
QUICK_HISTORY = 8

#: 看看屏幕的最短触发间隔，避免连续点击把额度打满（同主分支 4 秒）。
LOOK_SCREEN_COOLDOWN_S = 4.0
