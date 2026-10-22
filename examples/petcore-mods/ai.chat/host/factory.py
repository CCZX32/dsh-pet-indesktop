"""AI 对话扩展：prompt/人格/路由在 mod，窗口/传输/密钥在 core。

Core 提供三块能力：

- ``ports.chat``：主对话窗口与按宠会话；
- ``ports.screen``：整屏截图与框选截图；
- ``ports.screen_ask``：截图提问窗口（窗口归 core，模型调用由这里的回调完成）。

后台线程里不碰 Qt：需要气泡/窗口的收尾一律经 ``_run_on_ui`` 排队回 GUI 线程。
"""

from __future__ import annotations

import base64
import threading
import time

from petcore.contracts.contributions import Contribution
from petcore.contracts.feature import FeatureDefinition
from petcore.contracts.screen import ScreenSelectionCancelled
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit

from petcore.ui.settings.base import SettingsPage, make_checkbox

OWNER = "ai.chat"

DEFAULT_PROMPT = (
    "你是「{name}」，一只住在主人桌面上的鲸鱼娘。用简短、口语化的中文回答，"
    "一次最多三句话；不确定就直说，不要编造。"
)

LOOK_SCREEN_PROMPT = "看看我的屏幕，用一两句话说说你现在看到什么。"
SCREEN_QUESTION_PROMPT = "看看这块区域里是什么，说清内容，能给出判断或建议时就直接给。"

MAX_HISTORY = 40
LOOK_SCREEN_COOLDOWN_S = 4.0


class _UiBridge(QObject):
    """worker → GUI 的单向队列；worker 线程只发信号，不碰控件。"""

    invoke = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.invoke.connect(self._call, Qt.ConnectionType.QueuedConnection)

    def _call(self, callback) -> None:
        try:
            callback()
        except Exception:
            pass


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
        self._bridge = _UiBridge()
        self._look_busy: set[int] = set()
        self._last_look: dict[int, float] = {}

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

    def _screen(self):
        return getattr(self.context.ports, "screen", None)

    def _screen_ask(self):
        return getattr(self.context.ports, "screen_ask", None)

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

    def _auto_open_after_look(self) -> bool:
        return bool(self._config_value("ai_look_screen_auto_open", False))

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

    def _slot(self, slot: int | None) -> int:
        if slot is None:
            return self._active_slot()
        try:
            return max(0, int(slot))
        except (TypeError, ValueError):
            return self._active_slot()

    def _run_on_ui(self, callback) -> None:
        """GUI 线程直接执行；worker 线程排队回 GUI。"""
        bridge = getattr(self, "_bridge", None)
        if bridge is None:
            callback()
            return
        if QThread.currentThread() == bridge.thread():
            callback()
            return
        bridge.invoke.emit(callback)

    # ---------------------------------------------------------------- 入口
    def open_chat(self, slot: int | None = None) -> None:
        chat = self._chat()
        target = self._slot(slot)
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
        chat.open(OWNER, pet_slot=target, title=f"AI 对话 · {self._character_name()}")

    def look_screen(self, slot: int | None = None) -> None:
        """截屏 → 视觉问答 → 气泡答复，并静默同步进该宠的对话记录。"""
        target = self._slot(slot)
        screen = self._screen()
        if screen is None:
            self._say("这个安装没有开放截屏能力")
            return
        if target in self._look_busy:
            self._say("上一张还没看完呢…", duration_ms=3200)
            return
        now = time.monotonic()
        last = self._last_look.get(target, 0.0)
        if now - last < LOOK_SCREEN_COOLDOWN_S:
            self._say("喘口气嘛，刚看过啦…", duration_ms=3200)
            return
        if not self._service_id():
            self._say("还没有可用的 API 服务，请先在「设置 → API 与账户」里填写")
            return
        if not self._vision_enabled():
            self._say("设置里关掉了视觉模型，先开启再让我看屏幕")
            return
        self._last_look[target] = now
        self._look_busy.add(target)
        self._say("让我看看…", duration_ms=6000)
        QTimer.singleShot(0, lambda: self._look_capture(target))

    def _look_capture(self, slot: int) -> None:
        screen = self._screen()
        try:
            capture = screen.capture(pet_slot=slot)
        except Exception as exc:  # noqa: BLE001 - 稳定 reason 已在端口里分类
            self._look_failed(slot, getattr(exc, "reason", "") or type(exc).__name__)
            return
        app_info = str(getattr(capture, "app_info", "") or "")
        if not app_info:
            getter = getattr(screen, "foreground_app", None)
            if callable(getter):
                try:
                    app_info = str(getter() or "")
                except Exception:
                    app_info = ""
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": LOOK_SCREEN_PROMPT
                        + (f"\n（前台应用：{app_info}）" if app_info else ""),
                    },
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
        self._start_vision(slot, messages, on_done=lambda text: self._look_done(slot, text, app_info))

    def screen_capture(self, slot: int | None = None) -> None:
        """框选区域 → 截图提问窗口；模型调用由 ``_on_ask`` 接管。"""
        target = self._slot(slot)
        screen = self._screen()
        ask = self._screen_ask()
        if screen is None or ask is None:
            self._say("这个安装没有开放截图提问能力")
            return
        if not self._vision_enabled():
            self._say("设置里关掉了视觉模型，先开启再截图提问")
            return
        try:
            capture = screen.capture_region(pet_slot=target)
        except ScreenSelectionCancelled:
            return
        except Exception as exc:  # noqa: BLE001
            self._say(f"截屏失败：{getattr(exc, 'reason', '') or type(exc).__name__}")
            return
        if not self._service_id():
            self._say("还没有可用的 API 服务，请先在「设置 → API 与账户」里填写")
            return
        ask.open(OWNER, capture, pet_slot=target, title="截图问答")

    # ---------------------------------------------------------------- 对话
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
        attachments: list[dict] = []
        taker = getattr(chat, "take_attachments", None)
        if callable(taker):
            try:
                attachments = list(taker(OWNER, pet_slot=slot))
            except Exception:
                attachments = []
        try:
            history = chat.history(OWNER, pet_slot=slot) if chat is not None else []
        except Exception:
            history = []
        turns = [
            {
                "role": str(item.get("role") or "user"),
                "content": str(item.get("content") or ""),
            }
            for item in history[-MAX_HISTORY:]
            if str(item.get("content") or "").strip()
        ]
        images = [
            item.get("image_data_url")
            for item in attachments
            if item.get("image_data_url")
        ]
        if images:
            # 当前问题会以多模态消息重发；先去掉会话里刚追加的那条纯文本，
            # 否则同一句话会连着出现两次。
            if (
                turns
                and turns[-1].get("role") == "user"
                and str(turns[-1].get("content") or "").strip() == text
            ):
                turns = turns[:-1]
            messages.extend(turns)
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}]
                    + [
                        {"type": "image_url", "image_url": {"url": url}}
                        for url in images
                    ],
                }
            )
        else:
            messages.extend(turns)
        self._start(slot, messages)

    def _on_ask(self, question: str, image_png: bytes, history: list[dict], slot: int) -> str:
        """截图提问窗口的回调（在 core 的后台线程里执行，同步返回整段答复）。"""
        api = self._api()
        service_id = self._service_id()
        if api is None or not service_id:
            raise RuntimeError("还没有可用的 API 服务，请先在「设置 → API 与账户」里填写")
        image_url = (
            "data:image/png;base64," + base64.b64encode(bytes(image_png or b"")).decode("ascii")
        )
        messages = [{"role": "system", "content": self._system_prompt()}]
        text_turns = [
            {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
            for item in (history or [])
            if str(item.get("content") or "").strip()
        ]
        attached = False
        for item in text_turns:
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
        if not attached:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question or SCREEN_QUESTION_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": question or SCREEN_QUESTION_PROMPT})
        result = api.stream_chat(
            service_id,
            messages,
            model=str(self._config_value("ai_model", "") or ""),
            temperature=self._temperature(),
        )
        if getattr(result, "cancelled", False):
            return ""
        return str(getattr(result, "text", "") or "").strip()

    def _on_stop(self, slot: int) -> None:
        cancel = self._cancels.get(int(slot))
        if cancel is not None:
            cancel.set()

    def _start(self, slot: int, messages) -> None:
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
            partial: list[str] = []

            def delta(value: str) -> None:
                partial.append(value)
                # ChatPort 的 token/done/error 由 core 自己跨线程排队。
                chat.token(OWNER, value, pet_slot=slot)

            try:
                result = api.stream_chat(
                    service_id,
                    messages,
                    model=model,
                    temperature=temperature,
                    on_delta=delta,
                    cancel=cancel,
                )
            except Exception as exc:  # noqa: BLE001 - 网络/传输错误只认 reason
                reason = str(getattr(exc, "reason", "") or "network")
                if cancel.is_set():
                    chat.done(OWNER, "".join(partial), pet_slot=slot)
                else:
                    detail = str(exc)
                    chat.error(OWNER, reason, detail, pet_slot=slot)
                    self._say(f"AI 请求失败：{detail}")
            else:
                if getattr(result, "cancelled", False):
                    chat.done(OWNER, "".join(partial), pet_slot=slot)
                else:
                    final = getattr(result, "text", "") or "".join(partial)
                    chat.done(OWNER, final, pet_slot=slot)
            finally:
                self._cancels.pop(slot, None)

        thread = threading.Thread(target=run, name=f"ai-chat-{slot}", daemon=True)
        self._threads[slot] = thread
        thread.start()

    def _start_vision(self, slot: int, messages, *, on_done) -> None:
        api = self._api()
        if api is None:
            self._look_failed(slot, "no_api")
            return
        service_id = self._service_id()
        model = str(self._config_value("ai_model", "") or "")
        temperature = self._temperature()

        def run() -> None:
            try:
                result = api.stream_chat(
                    service_id,
                    messages,
                    model=model,
                    temperature=temperature,
                )
            except Exception as exc:  # noqa: BLE001
                reason = str(getattr(exc, "reason", "") or exc)
                self._run_on_ui(lambda: self._look_failed(slot, reason))
                return
            text = str(getattr(result, "text", "") or "").strip()
            if not text:
                self._run_on_ui(lambda: self._look_failed(slot, "empty_reply"))
                return
            self._run_on_ui(lambda: on_done(text))

        threading.Thread(
            target=run, name=f"ai-look-{slot}", daemon=True
        ).start()

    # ---------------------------------------------------------------- 看看屏幕收尾
    def _look_done(self, slot: int, text: str, app_info: str) -> None:
        self._look_busy.discard(slot)
        self._say(text, duration_ms=max(4000, min(12000, len(text) * 150)))
        chat = self._chat()
        record = getattr(chat, "record", None) if chat is not None else None
        if callable(record):
            try:
                record(
                    OWNER,
                    "user",
                    f"（看看屏幕）{app_info}" if app_info else "（看看屏幕）",
                    pet_slot=slot,
                )
                record(OWNER, "assistant", text, pet_slot=slot)
            except Exception:
                pass
        if self._auto_open_after_look():
            self.open_chat(slot)

    def _look_failed(self, slot: int, reason: str) -> None:
        self._look_busy.discard(slot)
        message = "看不清啊…"
        if reason and reason != "empty_reply":
            message += str(reason)[:60]
        self._say(message, duration_ms=5000)

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        chat = self._chat()
        ask = self._screen_ask()
        self._unsubs = []
        if chat is not None:
            self._unsubs.append(chat.on_submit(OWNER, self._on_submit))
            self._unsubs.append(chat.on_stop(OWNER, self._on_stop))
        if ask is not None:
            self._unsubs.append(ask.on_ask(OWNER, self._on_ask))

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

    def _say(self, text: str, *, duration_ms: int = 6000) -> None:
        presentation = getattr(self.context.ports, "presentation", None)
        if presentation is None:
            return

        def speak() -> None:
            try:
                presentation.say(text, duration_ms=duration_ms)
            except Exception:
                pass

        self._run_on_ui(speak)


class AiChatPage(SettingsPage):
    title = "AI 对话"

    _KEYS = (
        "ai_service",
        "ai_model",
        "ai_system_prompt",
        "ai_vision_enabled",
        "ai_temperature",
        "ai_look_screen_auto_open",
    )

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self._initial = {key: self.config().get(key) for key in self._KEYS}
        card = self.section("模型")
        self.service_combo = QComboBox(self)
        self.service_combo.addItem("自动（第一个服务）", "")
        try:
            for meta in self.api().services():
                self.service_combo.addItem(meta.name or meta.service_id, meta.service_id)
        except Exception:
            pass
        index = self.service_combo.findData(str(self._initial.get("ai_service") or ""))
        self.service_combo.setCurrentIndex(index if index >= 0 else 0)
        self.service_combo.currentIndexChanged.connect(self._on_changed)
        card.add_row("对话服务", self.service_combo, "留空自动用「API 与账户」里的第一个服务。")

        self.model_edit = QLineEdit(self)
        self.model_edit.setPlaceholderText("留空用服务里的默认模型")
        self.model_edit.setText(str(self._initial.get("ai_model") or ""))
        self.model_edit.editingFinished.connect(self._on_changed)
        card.add_row("模型覆盖", self.model_edit, "只影响对话；截图提问会优先用视觉模型。")

        self.temperature_spin = QDoubleSpinBox(self)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(1)
        try:
            self.temperature_spin.setValue(float(self._initial.get("ai_temperature") or 0.7))
        except (TypeError, ValueError):
            self.temperature_spin.setValue(0.7)
        self.temperature_spin.valueChanged.connect(self._on_changed)
        card.add_row("温度", self.temperature_spin, "越高越发散，0.7 适合日常聊天。")

        card2 = self.section("人格与视觉")
        self.prompt_edit = QPlainTextEdit(self)
        self.prompt_edit.setPlaceholderText("留空使用默认人格")
        self.prompt_edit.setPlainText(str(self._initial.get("ai_system_prompt") or ""))
        self.prompt_edit.textChanged.connect(self._on_changed)
        card2.add_row("系统提示词", self.prompt_edit, "每次对话开头发给模型；支持 {name} 占位。")

        self.vision_check = make_checkbox(self)
        self.vision_check.setChecked(bool(self._initial.get("ai_vision_enabled", True)))
        self.vision_check.toggled.connect(self._on_changed)
        card2.add_row(
            "允许截图提问",
            self.vision_check,
            "截图只读取当前屏幕并直接发给模型，不写入磁盘。",
        )

        self.auto_open_check = make_checkbox(self)
        self.auto_open_check.setChecked(
            bool(self._initial.get("ai_look_screen_auto_open", False))
        )
        self.auto_open_check.toggled.connect(self._on_changed)
        card2.add_row(
            "看看屏幕后自动打开对话",
            self.auto_open_check,
            "默认只把结果同步进对话记录并用气泡回答；勾选后才主动唤出对话窗口。",
        )
        self.add_note(
            "对话内容按桌宠 + 角色分别保存在本机 sessions/ 目录；密钥只在系统钥匙串。"
            "截图提问是独立的框选窗口，图片只在内存中流转。"
        )

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
        config.set("ai_temperature", float(self.temperature_spin.value()))
        config.set("ai_look_screen_auto_open", bool(self.auto_open_check.isChecked()))
        self.changed.emit()

    def dirty(self) -> bool:
        config = self.config()
        return any(
            str(config.get(key)) != str(value)
            for key, value in self._initial.items()
        )

    def _snapshot(self) -> dict:
        return {key: self.config().get(key) for key in self._KEYS}

    def confirm_save(self) -> None:
        self._on_changed()
        self._initial = self._snapshot()

    def discard_changes(self) -> None:
        self._initial = self._snapshot()
        self.changed.emit()

    def keywords(self) -> list[str]:
        return [
            "AI",
            "对话",
            "聊天",
            "模型",
            "提示词",
            "温度",
            "截图",
            "视觉",
            "识屏",
            "看看屏幕",
            "截图提问",
            "自动打开",
            "chat",
        ]


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
