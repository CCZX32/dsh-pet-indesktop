# -*- coding: utf-8 -*-
"""「快速识屏」三个动作的编排：截图 → 引擎 → 展示（本片的全部产品面）。

三条链路的差别只在中间那一步，前后两端共用同一套收口：

    截图提取文字：capture → 本地 OCR            → 结果浮层（可复制，纯本地）
    截图翻译    ：capture → OCR(原文) + 翻译引擎 → 结果浮层（双语对照位）
    截图问答    ：capture → 显式确认 → vision/chat 通道 → 岛 / 结果浮层

为什么编排单独立一层（而不是塞进窗口类）：宿主有两条（``PetWindow`` 单窗拓扑与
``OverlayShell`` sprite 拓扑），窗口类里各写一遍必然漂移；这里只认一个 duck-typed
宿主面（``cfg`` / ``show_bubble`` / ``proactive_watcher`` / ``screen_capture_island``），
两条宿主各自只挂三个零参回调。整个文件不 import 任何窗口模块。

五条纪律（每条都有对应用例）：

1. **隐私红线**：提取文字纯本地（不确认、不联网）；问答把像素发出本机之前
   **必须**过一次显式确认，拒绝即丢图（不缓存、不留观感上的"稍后再发"）。
2. **物理隔离**：采集会话期间暂停主动识屏 watcher，会话结束**只恢复到此前配置
   允许的状态**——此前没在跑就不许被这次截图唤醒（对称，不是无条件 resume）。
3. **失败也收口**：采集中途取消/失败/引擎抛错，watcher 与 busy 位都必须回到起点，
   不许留下"此后每次触发都被拒"的中间态。
4. **阻塞步骤不占 GUI 线程**：OCR 与网络都在后台线程跑，结果经 Qt 信号回到
   GUI 线程再动界面（Qt 对象只在拥有它的线程里碰）。
5. **用完就丢**：会话收口（交付 / 取消 / 失败）时把本地 OCR 引擎还回去
   （``ocr.release_engine``）——它那 ~110 MB 常驻是明确不想长期背的代价；
   归还放后台线程（实测 unload 约 48 ms，正好压在结果浮层弹出的那一刻）。
   释放后再次触发会**重新加载**，不是"一次性"。所有出口都汇到 ``_finish()``，
   释放只挂在那里一处。
"""

from __future__ import annotations

import functools
import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .controller import ScreenCaptureController, _weak_slot
from .reasons import OCR_PENDING_REASON, TRANSLATION_PENDING_REASON
from .result_panel import SHORT_RESULT_LIMIT, ScreenResult, ScreenResultPanel
from .vision_bridge import ChatVisionChannel

# ``_weak_slot``：slice-1 的 Qt 生命周期小工具（信号槽只持弱引用，避免
# ``controller ↔ actions`` 引用环把 Qt 销毁推到解释器退出期）。同包内复用一份，
# 不再抄第二遍。

log = logging.getLogger("dsh-pet-standalone")

__all__ = [
    "ACTION_ASK",
    "ACTION_OCR",
    "ACTION_TRANSLATE",
    "ACTIONS",
    "OCR_PENDING_REASON",
    "TRANSLATION_PENDING_REASON",
    "ScreenCaptureActions",
    "ScreenCapturePresenter",
    "actions_for",
    "confirm_cloud_send",
    "ocr_engine_available",
    "resolve_ocr_engine",
    "resolve_ocr_release",
    "resolve_translator",
    "translation_engine_available",
]

ACTION_OCR = "ocr"
ACTION_TRANSLATE = "translate"
ACTION_ASK = "ask"
ACTIONS = (ACTION_OCR, ACTION_TRANSLATE, ACTION_ASK)

TITLE_OCR = "截图提取文字"
TITLE_TRANSLATE = "截图翻译"
TITLE_ASK = "截图问答"

#: 引擎缺席时的如实说明（不是"暂时没有数据"，也不摆假结果）。文案的真值在
#: ``pet/screen_capture/reasons.py``——菜单里那两条置灰 tooltip 用的是同一份
#: （本模块顶部 import 进来，这里只做转发，见 ``__all__``）。

#: 本地 OCR 引擎 seam 的契约：模块级 ``recognize(image: QImage) -> str``——同步、
#: 纯本地、不联网，没识别到文字返回空串，失败抛异常（``str(exc)`` 可直接展示给
#: 用户）。引擎模块（切片 2 的 ``ocr.py``）不在时解析结果为空，动作如实说明。
OCR_MODULE = "ocr"
OCR_ENTRY = "recognize"
#: 「用完就丢」的释放入口：``release_engine() -> bool``（同步、幂等；没加载过是
#: 零成本 no-op）。每次会话收口都调它——引擎那 ~110 MB 常驻是明确不想长期背的
#: 代价，由编排层在收口处归还，而不是靠后台定时器去猜"用户不再用了"。
OCR_RELEASE_ENTRY = "release_engine"
#: 翻译引擎 seam 的契约：``translate_selection(image: QImage, source: str) -> str``。
#: 本片一律解析为空（入口与双语对照位就位，引擎是后续片）。
TRANSLATOR_MODULE = "translate"
TRANSLATOR_ENTRY = "translate_selection"


# ---------------------------------------------------------------- seam 解析


def _resolve_engine(module_name: str, entry: str) -> Callable | None:
    """惰性解析同包内的引擎模块入口；不在/加载失败一律返回 None。"""
    import importlib

    try:
        module = importlib.import_module(f"{__package__}.{module_name}")
    except Exception as exc:  # 引擎缺失或它自己的依赖没装好，都不是本片的崩溃点
        log.debug("快速识屏：引擎 %s 不可用 (%s)", module_name, exc)
        return None
    entry_fn = getattr(module, entry, None)
    return entry_fn if callable(entry_fn) else None


def resolve_ocr_engine() -> Callable | None:
    """本地 OCR 引擎（``pet/screen_capture/ocr.py::recognize``），缺席返回 None。"""
    return _resolve_engine(OCR_MODULE, OCR_ENTRY)


def resolve_translator() -> Callable | None:
    """翻译引擎（``pet/screen_capture/translate.py::translate_selection``），本片恒 None。"""
    return _resolve_engine(TRANSLATOR_MODULE, TRANSLATOR_ENTRY)


def resolve_ocr_release() -> Callable | None:
    """本地 OCR 的释放入口（``ocr.py::release_engine``），缺席返回 None。

    缺席（旧版引擎模块）不是错误：没有它只是"不归还"，识别链路照常工作——
    所以调用点对 None 与异常一律静默放行，绝不因为归还失败而影响一次已经成功
    的识屏。
    """
    return _resolve_engine(OCR_MODULE, OCR_RELEASE_ENTRY)


def ocr_engine_available() -> bool:
    """菜单项可用性的判据：**引擎模块在不在**（切片 2 的 ``ocr.py``）。

    刻意只判"模块 + 入口可调用"，不在这里探模型文件/依赖装没装全：

    - 模型缺失、rapidocr 没装好这类问题只有真加载时才知道，而引擎自己抛的
      ``OcrError`` 文案是**面向用户写的**（"缺少本地 OCR 模型文件 … 请重新安装"）
      ——那条理由由动作的错误出口原样展示在结果浮层里，比在这里猜一个置灰理由准；
    - 这里若去 ``resolve_model_dir()`` 之类做深探，会把 rapidocr 的厚重导入搬到
      "每次开右键菜单"这条路径上（菜单卡顿换一个更准的置灰，不值）。
    """
    return resolve_ocr_engine() is not None


def translation_engine_available() -> bool:
    return resolve_translator() is not None


def confirm_cloud_send(purpose: str, parent=None) -> bool:
    """显式确认：把选区像素发到云端 AI 服务之前问一次（设计红线）。

    **失败即不发**：拿不到用户明确的"是"（点了否、关掉对话框、弹窗失败）一律按
    拒绝处理。用静态 ``QMessageBox.question`` 而不是自造对话框：默认按钮是「否」，
    且在无人值守环境（测试/CI 已全局打桩返回 No）不会把进程挂住。
    """
    from PySide6.QtWidgets import QMessageBox

    why = {
        ACTION_ASK: "让 AI 看图并回答这次提问",
    }.get(str(purpose), "完成这次操作")
    text = (
        f"要把框选的这块图发到你在设置里配置的 AI 服务，{why}吗？\n\n"
        "截图全程只在内存里处理、不会存到磁盘；但内容会发送到该服务。\n"
        "点「否」则什么都不会发出去。"
    )
    answer = QMessageBox.question(
        parent,
        "发送截图到 AI 服务",
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


# ---------------------------------------------------------------- watcher 隔离


class _WatcherGate:
    """截图会话期间的主动识屏物理隔离（对称暂停/恢复）。

    "对称"是这一层唯一的难点：无条件 ``resume()`` 会把用户此前显式暂停/配置
    不允许的 watcher 唤醒——一次截图就改了主人没让它改的东西。因此只在
    **此前确实在跑**时才走恢复路径，而恢复本身仍交给 ``resume()``
    （= 按最新配置重评估启停），不在这里直接起定时器。

    取用方式在 2026-10-13 交叉审查 m9 改过：watcher **不在构造期定死**，构造期只挂
    一个零参取用回调，``pause()`` 那一刻才问"现在是谁"——壳的共享 watcher 可能晚建、
    也可能被重建，构造期抓到的那一个可能早就不是当值的那一个（与
    ``ScreenCapturePresenter`` 现取岛同一条纪律）。恢复则落在**确实被暂停的那一个**
    实例上：现取到别的对象就恢复别的对象＝我们暂停的那个永远醒不过来。
    """

    def __init__(self, provider: Callable[[], Any] | None = None) -> None:
        self._provider = provider
        self._paused_watcher: Any = None
        self._was_running = False

    def _current(self):
        provider = self._provider
        if provider is None:
            return None
        try:
            return provider()
        except Exception:  # 取用回调本身出错＝这条面不可用，不是截图失败
            log.debug("快速识屏：取主动识屏 watcher 失败", exc_info=True)
            return None

    def pause(self) -> None:
        if self._paused_watcher is not None:
            return  # 已经在隔离中：同一轮里只暂停一次，不叠第二次
        watcher = self._current()
        if watcher is None:
            return
        try:
            self._was_running = bool(watcher.is_running())
            watcher.pause()
        except Exception:  # 隔离失败不能连累截图本身
            log.exception("快速识屏：暂停主动识屏失败")
            self._was_running = False
            return
        self._paused_watcher = watcher

    def restore(self) -> None:
        watcher, self._paused_watcher = self._paused_watcher, None
        was_running, self._was_running = self._was_running, False
        if watcher is None:
            return  # 没暂停成功过（或已经恢复过）：不留残余状态
        if not was_running:
            return  # 此前没在跑：绝不被这次截图唤醒（配置/用户才是启动者）
        try:
            watcher.resume()
        except Exception:
            log.exception("快速识屏：恢复主动识屏失败")


# ---------------------------------------------------------------- 宿主解析
#
# 宿主有两条拓扑（PetWindow / OverlayShell），面不完全一样；这里把"从宿主取
# 某样东西"的探测收成一小组函数，属性名按各自主流的写法依次尝试，缺就返回 None。
# 测试替身同样吃这套探测（给任一形态即可）。


def _host_config(host):
    for name in ("cfg", "_config", "config"):
        value = getattr(host, name, None)
        if value is not None and callable(getattr(value, "get", None)):
            return value
    return None


def _host_watcher(host):
    watcher = getattr(host, "proactive_watcher", None)
    if watcher is not None:
        return watcher
    shared = getattr(getattr(getattr(host, "_instance", None), "shell", None), "_shared", None)
    return getattr(shared, "proactive", None)


def _host_island(host):
    provider = getattr(host, "screen_capture_island", None)
    if callable(provider):
        try:
            island = provider()
        except Exception:
            log.debug("快速识屏：取灵动岛失败", exc_info=True)
            island = None
        if island is not None:
            return island
    island = getattr(host, "island", None) or getattr(host, "dynamic_island", None)
    if island is None:
        island = getattr(getattr(getattr(host, "_instance", None), "shell", None), "island", None)
    return island


def _host_bubble(host):
    fn = getattr(host, "show_bubble", None)
    return fn if callable(fn) else None


def _host_dialog_parent(host):
    from PySide6.QtWidgets import QWidget

    if isinstance(host, QWidget):
        return host
    return getattr(host, "overlay", None)


def _host_theme(host) -> str | None:
    """宿主主题（``"light"`` / ``"dark"``；跟随系统时返回 ``None``）。

    来源就是菜单那一条真值：主配置的 ``context_menu_appearance.theme``
    （``{"system", "light", "dark"}``，见 ``pet/config.py::_clean_menu_appearance``）。
    既然菜单是这一个键渲染的，结果浮层就不该自己猜一遍——两处口径不同的话，用户
    会看到"菜单是浅色的、浮层是深色的"。``system`` 与读不到配置一律返回 ``None``：
    那表示"跟着宿主调色板现判"，由 ``ScreenResultPanel`` 自己按调色板定。
    """
    config = _host_config(host)
    if config is None:
        return None
    appearance = config.get("context_menu_appearance")
    theme = appearance.get("theme") if isinstance(appearance, dict) else None
    return theme if theme in ("light", "dark") else None


# ---------------------------------------------------------------- 展示落点


class ScreenCapturePresenter:
    """状态与结果的落点：短的上灵动岛，长的落在岛旁的结果浮层。

    岛的用法只取既有两个入口（``set_last_message`` + ``notify_event``），
    不为本片给岛加新 API——岛是"一眼"面，本片没有非它不可的新状态通道。
    岛不可用（关掉/隐藏/纯桌宠变体）时回落到桌宠气泡，用户至少看得到反馈。

    ``style`` 是结果浮层的主题（``None`` = 跟着宿主调色板现判）。默认那一条由
    ``ScreenCaptureActions`` 从宿主配置里读出来（与菜单同一个键），所以浅色宿主
    上不会再弹出一块写死深色的浮层。
    """

    def __init__(self, *, island=None, bubble=None,
                 panel_factory=ScreenResultPanel, panel_parent=None,
                 style: str | None = None) -> None:
        self._island = island
        self._bubble = bubble
        self._panel_factory = panel_factory
        self._panel_parent = panel_parent
        self._style = style
        self._panel: ScreenResultPanel | None = None

    # ------------------------------------------------------------ 对外
    def status(self, text: str) -> None:
        """过程状态（"正在识别…"）：只借岛的动效/消息槽，不上面板。"""
        self._notify(str(text), "generic")

    def show(self, result: ScreenResult) -> ScreenResultPanel | None:
        """结果落地：岛永远拿到一句短文案；长结果/双语结果/强制件再开面板。"""
        self._notify(result.summary or result.status, "reply")
        long_text = len(result.primary.strip()) > SHORT_RESULT_LIMIT
        if not (result.force_panel or long_text or result.secondary.strip()):
            return None
        panel = self.panel()
        if panel is None:
            return None
        panel.show_result(result, self.island_widget())
        return panel

    def panel(self) -> ScreenResultPanel | None:
        """当前面板（懒造；造不出来返回 None，绝不阻断动作本身）。"""
        if self._panel is not None:
            return self._panel
        factory = self._panel_factory
        if factory is None:
            return None
        # 主题只在造面板那一刻定（面板是复用件，一次会话里不换色）；``None``
        # 表示"跟着宿主调色板现判"，由面板自己 resolve。
        style = {} if self._style is None else {"style": self._style}
        try:
            self._panel = factory(self._panel_parent, **style)
        except Exception:
            log.exception("快速识屏：结果浮层创建失败")
            return None
        return self._panel

    def island_widget(self):
        """可达且可见的岛（岛可能被关掉/重建，所以每次都现取）。"""
        island = self._island
        if callable(island):
            try:
                island = island()
            except Exception:
                return None
        if island is None:
            return None
        try:
            import shiboken6

            if not shiboken6.isValid(island):
                return None
        except TypeError:  # 非 Qt 对象（测试替身）
            pass
        except Exception:
            return None
        visible = getattr(island, "isVisible", None)
        if callable(visible) and not visible():
            return None
        return island

    # ------------------------------------------------------------ 内部
    def _notify(self, text: str, kind: str) -> None:
        island = self.island_widget()
        if island is not None:
            try:
                island.set_last_message(text)
                island.notify_event(kind)
                return
            except Exception:
                log.debug("快速识屏：灵动岛展示失败，回落气泡", exc_info=True)
        if self._bubble is not None:
            try:
                self._bubble(text, duration_ms=6000)
            except Exception:
                log.debug("快速识屏：气泡展示失败", exc_info=True)


# ---------------------------------------------------------------- 编排


class ScreenCaptureActions(QObject):
    """三个截图动作的编排宿主（一次一条，宿主长期持有）。

    依赖全部可注入（``controller`` / ``ocr`` / ``translator`` / ``ask`` /
    ``confirm`` / ``presenter`` / ``watcher``），默认走真实实现；测试用假件即可
    在 offscreen 下把三条链路与所有出口钉死。

    ``watcher`` 传的是**取用回调的原料**：注入替身时它被包成"每次都返回这一个"的
    回调，不注入时用的是"每次从宿主现取"（见 :class:`_WatcherGate`）。
    """

    result_ready = Signal(object)     # ScreenResult
    failed = Signal(str)              # 采集或引擎失败理由

    _stage_done = Signal(object, object)   # 私有：后台线程 → GUI 线程

    def __init__(self, host=None, *, controller=None, ocr=None, translator=None,
                 ask=None, confirm=None, presenter=None, watcher=None, release=None,
                 run_inline: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._config = _host_config(host)
        self._ocr = ocr
        self._translator = translator
        self._ask = ask
        self._confirm = confirm
        self._release = release
        self._run_inline = bool(run_inline)
        self._watcher_gate = _WatcherGate(
            functools.partial(_host_watcher, host) if watcher is None else (lambda: watcher)
        )
        self._presenter = presenter if presenter is not None else self._default_presenter()
        self._controller = controller if controller is not None else ScreenCaptureController(self)
        self._busy = False
        self._action = ""
        self._pending: tuple[Callable, Callable] | None = None
        self._stage_done.connect(self._on_stage_done)
        # 两处连接的**判据**不同，别混着读（2026-10-13 交叉审查 nit 要的就是这条区分）：
        #
        # - 上面那条是**自连**（发出者与接收者是同一个对象）：不存在 ``宿主 ↔ 发出者``
        #   引用环，直接连绑定方法没有代价，也不需要弱引用；
        # - 下面三条是**跨对象**（controller → actions）：controller 被本对象强持有，
        #   直连绑定方法就形成 ``controller ↔ actions`` 环，把 Qt 对象的销毁推到解释器
        #   退出期（那条路径实测以原生崩溃收场）。所以跨对象一律走 ``_weak_slot``，
        #   不自作聪明地分"哪条安全"。
        self._controller.captured.connect(_weak_slot(self, "_on_captured"))
        self._controller.cancelled.connect(_weak_slot(self, "_on_cancelled"))
        self._controller.failed.connect(_weak_slot(self, "_on_failed"))

    # ------------------------------------------------------------ 只读视图

    @property
    def busy(self) -> bool:
        """是否正在一次截图动作里（采集中或引擎/网络在跑）。"""
        return self._busy

    # ---------------------------------------------------------------- 入口

    def run(self, action: str) -> bool:
        """启动一次动作；已在采集中或 host 不支持时返回 False。"""
        key = str(action)
        if key not in ACTIONS:
            raise ValueError(f"未知的截图动作 {action!r}（可选：{', '.join(ACTIONS)}）")
        if self._busy:
            log.debug("快速识屏：上一轮还没收口，忽略本次触发 (%s)", key)
            self.status("上一张还没看完呢…")
            return False

        self._busy = True
        self._action = key
        self._watcher_gate.pause()
        try:
            started = bool(self._controller.start())
        except Exception as exc:  # 采集宿主千奇百怪，闭环不许因此塌掉
            log.exception("快速识屏：启动采集失败")
            self._watcher_gate.restore()   # 隔离必须对称：异常出口也要把 watcher 放回去
            self._finish()
            self.status(f"没能开始截图（{exc}）")
            self.failed.emit(str(exc))
            return False
        if not started:
            # 采集没起来：覆盖层/抓帧失败时 controller 会先发 failed（那条出口已经把
            # 理由给到用户了，busy 也收了），这里只兜"纯 false 没回调"的情况。
            if self._busy:
                self._watcher_gate.restore()
                self._finish()
                self.status("没能开始截图，稍后再试")
            return False
        return True

    # ------------------------------------------------------------ 采集回调

    def _on_captured(self, image, _selection) -> None:
        if not self._busy:
            log.debug("快速识屏：忽略迟到的采集结果")
            return
        # 采集期到这一刻结束：窗口已还原、冻结帧已裁出，watcher 可以回岗。
        self._watcher_gate.restore()
        if self._action == ACTION_OCR:
            self._run_ocr(image)
        elif self._action == ACTION_TRANSLATE:
            self._run_translate(image)
        else:
            self._run_ask(image)

    def _on_cancelled(self, reason) -> None:
        if not self._busy:
            return
        self._watcher_gate.restore()
        self._finish()
        log.debug("快速识屏：用户取消 (%s)", reason)
        self.status("已取消")

    def _on_failed(self, reason) -> None:
        if not self._busy:
            return
        self._watcher_gate.restore()
        self._finish()
        self.status(f"这张没截成（{reason}）")
        self.failed.emit(str(reason))

    # ---------------------------------------------------------------- 三条链路

    def _run_ocr(self, image) -> None:
        engine = self._ocr if self._ocr is not None else resolve_ocr_engine()
        if engine is None:
            self._finish()
            self._emit_result(ScreenResult(
                title=TITLE_OCR, status=OCR_PENDING_REASON, force_panel=True,
            ))
            return
        self.status("正在本地识别文字…")
        self._submit(lambda: engine(image),
                     self._on_ocr_done,
                     functools.partial(self._on_stage_error, stage="本地识别"))

    def _on_ocr_done(self, text) -> None:
        self._finish()
        value = str(text or "").strip()
        if not value:
            self._emit_result(ScreenResult(title=TITLE_OCR, status="没有识别到文字"))
            return
        self._emit_result(ScreenResult(
            title=TITLE_OCR, primary=value, force_panel=True,
            status=f"本地识别 · {len(value)} 字",
        ))

    def _run_translate(self, image) -> None:
        ocr = self._ocr if self._ocr is not None else resolve_ocr_engine()
        translator = self._translator if self._translator is not None else resolve_translator()

        def work() -> tuple[str, str]:
            source = str(ocr(image) or "").strip() if ocr is not None else ""
            translated = (
                str(translator(image, source) or "").strip() if translator is not None else ""
            )
            return source, translated

        self.status("正在翻译…" if translator is not None else "正在识别原文…")
        self._submit(
            work,
            functools.partial(self._on_translate_done, translator=translator is not None),
            functools.partial(self._on_stage_error, stage="翻译"),
        )

    def _on_translate_done(self, value, *, translator: bool) -> None:
        self._finish()
        source, translated = value if isinstance(value, tuple) else (str(value or ""), "")
        source = str(source or "").strip()
        translated = str(translated or "").strip()
        if translator and not translated:
            status = "没有拿到译文"
        elif translator:
            status = f"已翻译 · {len(translated)} 字"
        else:
            status = TRANSLATION_PENDING_REASON
        self._emit_result(ScreenResult(
            title=TITLE_TRANSLATE, primary=source, secondary=translated,
            force_panel=True, status=status, primary_label="原文" if translated else "",
        ))

    def _run_ask(self, image) -> None:
        if not self._confirm_send(ACTION_ASK):
            self._finish()
            self.status("已取消，这张图没有发出去")
            return
        channel = self._ask if self._ask is not None else self._build_ask_channel()
        if channel is None:
            self._finish()
            self._emit_result(ScreenResult(
                title=TITLE_ASK, status="AI 对话通道不可用（未配置或已关闭）",
                force_panel=True,
            ))
            return
        self.status("正在看图…")
        self._submit(lambda: channel(image),
                     self._on_ask_done,
                     functools.partial(self._on_stage_error, stage="看图"))

    def _on_ask_done(self, reply) -> None:
        self._finish()
        value = str(reply or "").strip()
        if not value:
            self._emit_result(ScreenResult(title=TITLE_ASK, status="模型没说话，再试一次？",
                                           force_panel=True))
            return
        self._emit_result(ScreenResult(
            title=TITLE_ASK, primary=value, status="来自你在设置里配置的 AI 服务",
        ))

    def _on_stage_error(self, message, *, stage: str) -> None:
        self._finish()
        self.status(f"{stage}失败：{message}")
        self.failed.emit(str(message))

    # ---------------------------------------------------------------- 线程纪律

    def _submit(self, work: Callable, on_ok: Callable, on_err: Callable) -> None:
        """把可能阻塞的一步放到后台线程，完成后经 ``_stage_done`` 回到 GUI 线程。

        ``run_inline`` 是给测试用的直通开关（同步跑、异常同样走到 ``on_err``）：
        编排本身与线程无关，两条路径共用同一组回调。
        """
        if self._run_inline:
            try:
                value = work()
            except Exception as exc:
                log.exception("快速识屏：本步失败")
                on_err(str(exc) or type(exc).__name__)
            else:
                on_ok(value)
            return
        self._pending = (on_ok, on_err)
        threading.Thread(
            target=self._stage_worker, args=(work,), daemon=True,
            name="pet-screen-capture",
        ).start()

    def _stage_worker(self, work: Callable) -> None:
        try:
            value = work()
        except Exception as exc:
            log.exception("快速识屏：本步失败")
            self._stage_done.emit(None, str(exc) or type(exc).__name__)
            return
        self._stage_done.emit(value, None)

    def _on_stage_done(self, value, error) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        on_ok, on_err = pending
        if error is not None:
            on_err(str(error))
            return
        on_ok(value)

    # ---------------------------------------------------------------- 收口

    def _finish(self) -> None:
        self._busy = False
        self._action = ""
        self._pending = None
        # 「用完就丢」的调用点：本方法是**所有**出口的唯一收口（成功交付 / 取消 /
        # 失败 / 引擎缺席），所以这里放一次就覆盖了全部终态，不必在每条链路上
        # 各写一遍（漏一处就是"引擎悄悄常驻到下次重启"）。
        self._release_engine()

    def _release_engine(self) -> None:
        """把本地 OCR 引擎还回去（后台线程；详见 :meth:`_release_worker`）。"""
        release = self._release
        if release is None:
            release = resolve_ocr_release()
            if release is None:
                return  # 引擎模块没有释放入口（旧版）：不还而已，不影响已交付的结果
        if self._run_inline:
            self._release_worker(release)
            return
        threading.Thread(target=self._release_worker, args=(release,), daemon=True,
                         name="pet-screen-capture-unload").start()

    @staticmethod
    def _release_worker(release: Callable) -> None:
        """在后台线程里执行释放。

        不占 GUI 线程的理由是**实测**的：`unload()` 一次约 48 ms（本机，
        见 ``.scratch/screen-capture/probe_ocr_unload_rss.txt``），而它正好落在
        "结果浮层即将弹出"这一刻——放 GUI 线程就是一次可见的掉帧。释放失败
        只记日志：图已经拿到了，归还失败不该变成用户可见的错误。
        """
        try:
            release()
        except Exception:
            log.exception("快速识屏：归还本地 OCR 引擎失败（不影响本次结果）")

    def _emit_result(self, result: ScreenResult) -> None:
        self._presenter.show(result)
        self.result_ready.emit(result)

    def status(self, text: str) -> None:
        self._presenter.status(text)

    # ---------------------------------------------------------------- 依赖

    def _default_presenter(self) -> ScreenCapturePresenter:
        host = self._host
        # 岛/气泡现取现用（岛会被重建、气泡面可能迟到）：构造期只挂取用回调。
        # 主题（结果浮层的浅色/深色）也从宿主现取：与菜单同一个配置键，读不到就是
        # "跟着宿主调色板判"（None），不再让浮层自己写死深色。
        return ScreenCapturePresenter(
            island=lambda: _host_island(host),
            bubble=_host_bubble(host),
            panel_factory=ScreenResultPanel,
            panel_parent=_host_dialog_parent(host),
            style=_host_theme(host),
        )

    def _confirm_send(self, purpose: str) -> bool:
        """云端发送确认；确认环节本身出错时**按拒绝处理**（fail-closed）。"""
        confirm = self._confirm
        if confirm is None:
            confirm = functools.partial(
                confirm_cloud_send, parent=_host_dialog_parent(self._host),
            )
            self._confirm = confirm
        try:
            return bool(confirm(purpose))
        except Exception:
            log.exception("快速识屏：发送确认环节失败，按拒绝处理")
            return False

    def _build_ask_channel(self):
        if self._config is None:
            return None
        try:
            return ChatVisionChannel(self._config)
        except Exception:
            log.exception("快速识屏：问答通道构建失败")
            return None


# ---------------------------------------------------------------- 宿主接线


def actions_for(host) -> ScreenCaptureActions:
    """按宿主取（并缓存）编排件：宿主长期持有它，采集会话才长得过菜单寿命。

    缓存落在宿主自己身上（``_screen_capture_actions``）：右键菜单是每次重建的
    对象，把编排件挂在菜单对象上会在菜单一关就丢——而一次截图会话横跨菜单关闭。
    """
    existing = getattr(host, "_screen_capture_actions", None)
    if isinstance(existing, ScreenCaptureActions):
        return existing
    actions = ScreenCaptureActions(host, parent=host if isinstance(host, QObject) else None)
    try:
        host._screen_capture_actions = actions
    except Exception:
        log.debug("快速识屏：编排件无法挂在宿主上，改为局部持有", exc_info=True)
    return actions
