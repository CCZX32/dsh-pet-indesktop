"""本地 OCR 扩展的运行时：只把自己注册成「提取文字」的优先处理者。

Core 在框选动作条上按下「提取文字」后，会按注册优先级依次调用处理者；这里
priority=10（先于 AI 的 100）。识别失败或引擎缺失时返回空串，Core 会自动回退到
下一个处理者（AI 视觉模型），错误不弹给用户。
"""

from __future__ import annotations

import logging

from . import engine

logger = logging.getLogger("petcore.mod.ocr")

OWNER = "tool.ocr"


class OcrRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {}
        self._unsubs: list = []

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        ask = getattr(self.context.ports, "screen_ask", None)
        register = getattr(ask, "on_action", None) if ask is not None else None
        if not callable(register):
            logger.info("screen_ask 不支持 on_action；本地 OCR 未注册")
            return
        self._unsubs.append(
            register(OWNER, self._on_action, priority=10, actions=("ocr",))
        )

    def stop(self) -> None:
        for unsubscribe in self._unsubs:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubs = []

    def close(self) -> None:
        self.stop()

    # ---------------------------------------------------------------- 动作
    def _on_action(self, action, source_text, png, slot) -> str:
        if action != "ocr":
            return ""
        ports = self.context.ports
        if not engine.available(ports):
            logger.info("本地 OCR 不可用，交给 AI 回退")
            return ""
        try:
            text = engine.recognize(png, ports)
        except engine.OcrUnavailable as exc:
            logger.warning("本地 OCR 失败，交给 AI 回退：%s", exc)
            return ""
        except Exception as exc:  # noqa: BLE001 - 任何异常都只降级，不打断动作条
            logger.warning("本地 OCR 异常：%s", type(exc).__name__)
            return ""
        return str(text or "").strip()
