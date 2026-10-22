"""AI 对话扩展：prompt/人格/路由在 mod，传输/窗口/密钥在 core。

Core 提供 ``ports.chat``（ChatPort）与 ``ports.api``（流式对话）；这里只做三件事：
组装消息、发起请求、把增量推回窗口。后台线程里不碰 Qt——ChatPort 自己负责跨线程。
"""

from __future__ import annotations

import base64
import threading

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit

from petcore.ui.settings.base import SettingsPage, make_checkbox

OWNER = "ai.chat"

DEFAULT_PROMPT = (
    "你是「{name}」，一只住在主人桌面上的鲸鱼娘。用简短、口语化的中文回答，"
    "一次最多三句话；不确定就直说，不要编造。"
)

LOOK_SCREEN_PROMPT = "看看我的屏幕，用一两句话说说你现在看到什么。"
SCREEN_QUESTION_PROMPT = "这是我当前的屏幕截图。请指出最需要注意的内容，并给出下一步建议。"

MAX_HISTORY = 40


class AiChatRuntime:
    def __init__(self, context):
        self.context = context
        self.commands = {
            "open": self.open_chat,
            "look_screen": self.look_screen,
            "screen_capture": self.screen_capture,
        }
        self._cancels: dict[int, threading.Event] = {}
        self._threads: dict[int, threading.Thread] = {}
        self._unsubs: list = []

    # ---------------------------------------------------------------- 配置
    def _host_config(self):
        return getattr(self.context.host, "config", None)

    def _config_value(self, key: str, default=None):
        config = self._host_config()
        if config is None:
            return default
        try:
            return config.get(key, default)
        except Exception:
            return default

    def _api(self):
        return getattr(self.context.ports, "api", None)

    def _chat(self):
        return getattr(self.context.ports, "chat", None)

    def _service_id(self) -> str:
        api = self._api()
        if api is None:
            return ""
        try:
            services = list(api.services())
        except Exception:
            services = []
        if not services:
            return ""
        configured = str(self._config_value("ai_service", "") or "")
        if configured and any(item.service_id == configured for item in services):
            return configured
        return services[0].service_id

    def _character_name(self) -> str:
        host = getattr(self.context, "host", None)
        config = self._host_config()
        character_id = ""
        if config is not None:
            try:
                character_id = str(config.get("character") or "")
            except Exception:
                character_id = ""
        getter = getattr(host, "character_for", None)
        if callable(getter) and character_id:
            try:
                spec = getter(character_id)
                return str(getattr(spec, "name", "") or character_id)
            except Exception:
                pass
        return character_id or "桌宠"

    def _system_prompt(self) -> str:
        configured = str(self._config_value("ai_system_prompt", "") or "").strip()
        return configured or DEFAULT_PROMPT.format(name=self._character_name())

    def _vision_enabled(self) -> bool:
        return bool(self._config_value("ai_vision_enabled", True))

    def _temperature(self):
        try:
            return float(self._config_value("ai_temperature", 0.7) or 0.7)
        except (TypeError, ValueError):
            return 0.7

    # ---------------------------------------------------------------- 宠物定位
    def _active_slot(self) -> int:
        pets = getattr(self.context.ports, "pets", None)
        if pets is None:
            return 0
        try:
            handle = pets.active() or pets.primary()
        except Exception:
            handle = None
        try:
            return int(getattr(handle, "slot", 0) or 0)
        except (TypeError, ValueError):
            return 0

    # ---------------------------------------------------------------- 入口
    def open_chat(self) -> None:
        chat = self._chat()
        slot = self._active_slot()
        if chat is None:
            self._say("聊天端口不可用，无法打开 AI 对话")
            return
        if not self._service_id():
            self._say("还没有可用的 API 服务，请先在「设置 → API 与账户」里填写")
            api = self._api()
            opener = getattr(api, "open_settings", None) if api is not None else None
            if callable(opener):
                try:
                    opener()
                except Exception:
                    pass
            return
        chat.open(OWNER, pet_slot=slot, title=f"AI 对话 · {self._character_name()}")

    def look_screen(self) -> None:
        self._capture_and_ask(LOOK_SCREEN_PROMPT, label="（看看屏幕）")

    def screen_capture(self) -> None:
        self._capture_and_ask(SCREEN_QUESTION_PROMPT, label="（截图提问）")

    # ---------------------------------------------------------------- 流程
    def _capture_and_ask(self, prompt: str, *, label: str) -> None:
        chat = self._chat()
        screen = getattr(self.context.ports, "screen", None)
        if chat is None:
            self._say("聊天端口不可用")
            return
        if screen is None:
            self._say("这个安装没有开放截屏能力")
            return
        if not self._vision_enabled():
            self._say("设置里关掉了视觉模型，先开启再截图提问")
            return
        slot = self._active_slot()
        try:
            capture = screen.capture(pet_slot=slot)
        except Exception as exc:
            self._say(f"截屏失败：{getattr(exc, 'reason', '') or type(exc).__name__}")
            return
        if not self._service_id():
            self._say("还没有可用的 API 服务，请先在「设置 → API 与账户」里填写")
            return
        chat.open(OWNER, pet_slot=slot, title=f"AI 对话 · {self._character_name()}")
        chat.append(OWNER, "user", label, pet_slot=slot)
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(capture.png).decode("ascii")
                        },
                    },
                ],
            }
        )
        self._start(slot, messages, vision=True)

    def _on_submit(self, text: str, slot: int) -> None:
        text = str(text or "").strip()
        if not text:
            return
        chat = self._chat()
        if chat is None:
            return
        if not self._service_id():
            chat.error(OWNER, "no_service", "还没有可用的 API 服务", pet_slot=slot)
            self._say("还没有可用的 API 服务，请先在「设置 → API 与账户」里填写")
            return
        messages = [{"role": "system", "content": self._system_prompt()}]
        try:
            history = chat.history(OWNER, pet_slot=slot) if chat is not None else []
        except Exception:
            history = []
        messages.extend(
            {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
            for item in history[-MAX_HISTORY:]
            if str(item.get("content") or "").strip()
        )
        self._start(slot, messages, vision=False)

    def _on_stop(self, slot: int) -> None:
        cancel = self._cancels.get(int(slot))
        if cancel is not None:
            cancel.set()

    def _start(self, slot: int, messages, *, vision: bool) -> None:
        chat = self._chat()
        api = self._api()
        if chat is None or api is None:
            return
        previous = self._cancels.get(slot)
        if previous is not None:
            previous.set()
        cancel = threading.Event()
        self._cancels[slot] = cancel
        service_id = self._service_id()
        model = str(self._config_value("ai_model", "") or "")
        temperature = self._temperature()

        def run() -> None:
            partial = []
            try:
                result = api.stream_chat(
                    service_id,
                    messages,
                    model=model,
                    temperature=temperature,
                    on_delta=lambda delta: (
                        partial.append(delta),
                        chat.token(OWNER, delta, pet_slot=slot),
                    ),
                    cancel=cancel,
                )
            except Exception as exc:  # noqa: BLE001 - 网络/传输错误只认 reason
                reason = str(getattr(exc, "reason", "") or "network")
                if cancel.is_set():
                    chat.done(OWNER, "".join(partial), pet_slot=slot)
                else:
                    chat.error(OWNER, reason, str(exc), pet_slot=slot)
                    self._say(f"AI 请求失败：{exc}")
            else:
                if getattr(result, "cancelled", False):
                    chat.done(OWNER, "".join(partial), pet_slot=slot)
                else:
                    chat.done(OWNER, getattr(result, "text", "") or "".join(partial), pet_slot=slot)
            finally:
                self._cancels.pop(slot, None)

        thread = threading.Thread(target=run, name=f"ai-chat-{slot}", daemon=True)
        self._threads[slot] = thread
        thread.start()

    def _say(self, text: str) -> None:
        presentation = getattr(self.context.ports, "presentation", None)
        if presentation is None:
            return
        try:
            presentation.say(text, duration_ms=6000)
        except Exception:
            pass

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        chat = self._chat()
        if chat is None:
            return
        self._unsubs = [
            chat.on_submit(OWNER, self._on_submit),
            chat.on_stop(OWNER, self._on_stop),
        ]

    def stop(self) -> None:
        for cancel in list(self._cancels.values()):
            cancel.set()
        self._cancels.clear()
        for unsubscribe in self._unsubs:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubs = []


class AiChatPage(SettingsPage):
    title = "AI 对话"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = {
            "ai_service": str(self.config().get("ai_service") or ""),
            "ai_model": str(self.config().get("ai_model") or ""),
            "ai_system_prompt": str(self.config().get("ai_system_prompt") or ""),
            "ai_vision_enabled": bool(self.config().get("ai_vision_enabled", True)),
        }
        card = self.section("模型")
        self.service_combo = QComboBox(self)
        self.service_combo.addItem("自动（第一个服务）", "")
        try:
            for meta in self.api().services():
                self.service_combo.addItem(meta.name or meta.service_id, meta.service_id)
        except Exception:
            pass
        index = self.service_combo.findData(self._initial["ai_service"])
        self.service_combo.setCurrentIndex(index if index >= 0 else 0)
        self.service_combo.currentIndexChanged.connect(self._on_changed)
        card.add_row("对话服务", self.service_combo, "留空自动用「API 与账户」里的第一个服务。")

        self.model_edit = QLineEdit(self)
        self.model_edit.setPlaceholderText("留空用服务里的默认模型")
        self.model_edit.setText(self._initial["ai_model"])
        self.model_edit.editingFinished.connect(self._on_changed)
        card.add_row("模型覆盖", self.model_edit, "只影响对话；截图提问会优先用视觉模型。")

        card2 = self.section("人格与视觉")
        self.prompt_edit = QPlainTextEdit(self)
        self.prompt_edit.setPlaceholderText("留空使用默认人格")
        self.prompt_edit.setPlainText(self._initial["ai_system_prompt"])
        self.prompt_edit.textChanged.connect(self._on_changed)
        card2.add_row("系统提示词", self.prompt_edit, "每次对话开头发给模型；支持 {name} 占位。")

        self.vision_check = make_checkbox(self)
        self.vision_check.setChecked(self._initial["ai_vision_enabled"])
        self.vision_check.toggled.connect(self._on_changed)
        card2.add_row(
            "允许截图提问",
            self.vision_check,
            "截图只读取当前屏幕并直接发给模型，不写入磁盘。",
        )
        self.add_note("对话内容按桌宠 + 角色分别保存在本机 sessions/ 目录；密钥只在系统钥匙串。")

    def api(self):
        features = getattr(self.host, "features", None)
        ports = getattr(features, "ports", None)
        return getattr(ports, "api", None) if ports is not None else None

    def config(self):
        return self.host.config

    def _on_changed(self, *_args) -> None:
        config = self.config()
        config.set("ai_service", str(self.service_combo.currentData() or ""))
        config.set("ai_model", self.model_edit.text().strip())
        config.set("ai_system_prompt", self.prompt_edit.toPlainText().strip())
        config.set("ai_vision_enabled", bool(self.vision_check.isChecked()))
        self.changed.emit()

    def dirty(self) -> bool:
        config = self.config()
        return any(
            str(config.get(key)) != str(value)
            for key, value in self._initial.items()
        )

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = {
            "ai_service": str(self.config().get("ai_service") or ""),
            "ai_model": str(self.config().get("ai_model") or ""),
            "ai_system_prompt": str(self.config().get("ai_system_prompt") or ""),
            "ai_vision_enabled": bool(self.config().get("ai_vision_enabled", True)),
        }

    def discard_changes(self) -> None:
        self._initial = {
            "ai_service": str(self.config().get("ai_service") or ""),
            "ai_model": str(self.config().get("ai_model") or ""),
            "ai_system_prompt": str(self.config().get("ai_system_prompt") or ""),
            "ai_vision_enabled": bool(self.config().get("ai_vision_enabled", True)),
        }
        self.changed.emit()

    def keywords(self) -> list[str]:
        return ["AI", "对话", "聊天", "模型", "提示词", "截图", "视觉", "chat"]


def create_host(_context):
    return FeatureDefinition(
        owner=OWNER,
        contributions=(
            Contribution(
                kind="settings_page",
                id="chat",
                data={"title": "AI 对话", "order": 640, "icon": "chat"},
            ),
        ),
        runtime_factory=AiChatRuntime,
        settings_factory=AiChatPage,
    )
