# -*- coding: utf-8 -*-
"""非 Windows 逐像素输入穿透 —— Qt 属性 + 原生输入穿透标志的轮询实现。

背景（发布阻断级）：新架构默认拓扑是全屏 overlay（``pet/overlay_window.py``：
一个全屏透明窗承载全部 sprite）。逐像素穿透此前只有 Windows 实现
（``pet/platform_win.py`` 的 ``WindowsPerPixelInputController``：WS_EX_TRANSPARENT
扩展样式位 + 光标轮询）；Linux/macOS 上整屏 overlay 就是一个整屏输入区，桌面
点击被整块吞掉。本模块把**同一套轮询协议**落到非 Windows 平台：

- **轮询档位**与 Windows 控制器逐值相同（盒内 10ms / 盒外 50ms / 拖拽 100ms）；
- **判定输入**相同（``window.mouse_through``、``window._press_global``、
  ``isVisible()``、``mapFromGlobal`` + ``window._is_transparent_at(local)``）；
- **落点**不同：Windows 写扩展样式位，这里写 Qt 窗口的
  ``WA_TransparentForMouseEvents`` 属性 + ``Qt::WindowTransparentForInput`` 标志。

为什么两处都要写（Qt 6.8 源码证据 + 本机 offscreen 实测）：

1. ``QWidget::setAttribute(WA_TransparentForMouseEvents)`` 只翻 QWidget 自己的
   属性位（qwidget.cpp:11516 的 case 是空实现）。属性转成窗口标志的
   ``QWidgetPrivate::adjustFlags``（qwidget.cpp:933）只在**窗口创建**时
   （``QWidgetPrivate::init``，qwidget.cpp:995）与 ``setWindowFlags``
   （qwidget.cpp:11020）各跑一次——窗口已创建后再设属性**不会**下发到平台层
   （本机 offscreen 实测：``windowHandle().flags()`` 不变）；属性本身只保证
   应用内事件不再投给该窗口（qapplication.cpp:744-760 ``pickMouseReceiver``）。
2. 跨应用穿透由平台层执行，入口都是窗口标志 ``Qt::WindowTransparentForInput``：
   X11 在 ``QXcbWindow::create`` / ``setWindowFlags`` 里翻成 XFixes 输入形状
   （qxcbwindow.cpp:978、943、1278），macOS 在 ``QCocoaWindow::setWindowFlags``
   里翻成 ``[NSWindow setIgnoresMouseEvents:]``（qcocoawindow.mm:733-742）。
   两条路径都支持 ``QWindow::setFlag`` **原地更新**（qwindow.cpp:979-988 →
   ``platformWindow->setWindowFlags``），不重建原生窗口——这正是 10ms 级切换
   能用的原因（``QWidget::setWindowFlag`` 走 ``setParent`` 会重建原生窗口，
   全屏 overlay 上必然频闪）。

分层：**该不该穿透**是纯函数 ``passthrough_decision``（离线可穷举），Qt 层只
负责把窗口事实摊平喂进去、把结论落到窗口上。

未在本机验证（诚实登记）：X11/macOS 的真实跨应用穿透行为本机（Windows）无法
执行。已知边界：X11 缺 XFixes 扩展时 ``QXcbWindow::setTransparentForMouseEvents``
会静默早退（qxcbwindow.cpp:1279-1281）；Wayland 原生会话（非 XWayland）下
Qt 是否处理该标志未验证。见交付报告「未实测项」。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QCursor

if TYPE_CHECKING:
    from .overlay_window import OverlayWindow

_TRANSPARENT_ATTR = Qt.WidgetAttribute.WA_TransparentForMouseEvents
_TRANSPARENT_FLAG = Qt.WindowType.WindowTransparentForInput


def passthrough_decision(*, mouse_through: bool, press_active: bool,
                         visible: bool, inside_bounds: bool,
                         transparent_pixel: bool) -> bool:
    """该不该把窗口设成输入穿透（纯函数：与 Windows 控制器同一真值表）。

    分支顺序即语义，与 ``platform_win.WindowsPerPixelInputController.
    should_click_through`` 逐条对应：

    1. ``mouse_through``（用户手动穿透开关）→ 恒穿透；
    2. 拖拽中（``_press_global`` 非 None）或窗口不可见 → 恒不穿透
       （拖拽期必须持续收到鼠标事件；隐藏窗口不收事件）；
    3. 光标在窗口包围盒外 → 不穿透（那里的样式没有意义，且盒内判定要付
       逐像素命中查询的钱）；
    4. 否则看逐像素命中：光标处没有任何 sprite 的不透明像素 = 穿透到下层应用。
    """
    if mouse_through:
        return True
    if press_active or not visible:
        return False
    if not inside_bounds:
        return False
    return bool(transparent_pixel)


class QtPerPixelInputController:
    """非 Windows 逐像素输入穿透：Qt 属性 + 原生输入穿透标志 + 光标轮询。

    单独成类而不是改 ``WindowsPerPixelInputController``：Windows 侧已经生产
    验证（扩展样式位、句柄变化重放、低频校正都有实机依据），两边真正共用的只有
    「轮询档位 + 判定真值表」，抽公共基类要动它，风险大于收益。跨平台一致性由
    测试钉住（``tests/test_platform_passthrough.py`` 的真值表对齐用例）。
    """

    NORMAL_POLL_INTERVAL_MS = 10
    #: 光标在窗口包围盒外：逐像素判定必然「无命中 → 穿透」，低频空转即可
    #: （overlay 铺满整屏时，盒内判定还要每 tick 走一遍全部 sprite 的 alpha 查询）。
    IDLE_POLL_INTERVAL_MS = 50
    DRAG_POLL_INTERVAL_MS = 100

    # 类级默认值：测试可以 ``object.__new__`` 绕过 __init__ 拼控制器（同
    # platform_win 惯例）。None = 还没写过窗口，第一次必然真写。
    _applied_through: bool | None = None
    _applied_win_id: int | None = None

    def __init__(self, window: "OverlayWindow") -> None:
        self._window = window
        self._timer = QTimer(window)
        self._timer.setInterval(self.NORMAL_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ---------------------------------------------------------------- 判定（协议入口）
    def should_click_through(self, global_pos: QPoint) -> bool:
        win = self._window
        mouse_through = bool(getattr(win, "mouse_through", False))
        press_active = getattr(win, "_press_global", None) is not None
        visible = bool(win.isVisible())
        # 廉价事实先短路：命中判定要遍历全部 sprite 的粗筛+alpha 查询，只在
        # 前三条都不短路时才算（顺序与 platform_win 相同）。
        inside_bounds = False
        transparent_pixel = False
        if not mouse_through and not press_active and visible:
            local = win.mapFromGlobal(global_pos)
            inside_bounds = QRect(0, 0, win.width(), win.height()).contains(local)
            if inside_bounds:
                transparent_pixel = bool(win._is_transparent_at(local))
        return passthrough_decision(
            mouse_through=mouse_through, press_active=press_active,
            visible=visible, inside_bounds=inside_bounds,
            transparent_pixel=transparent_pixel)

    def _cursor_inside_window(self, global_pos: QPoint) -> bool:
        """光标是否落在窗口包围盒内（两段式轮询的定档判据）。"""
        win = self._window
        local = win.mapFromGlobal(global_pos)
        return QRect(0, 0, win.width(), win.height()).contains(local)

    def _sync_poll_interval(self, inside: bool) -> None:
        """按光标位置切档：盒内 10ms（逐像素跟手），盒外 50ms（低频）。

        拖拽中（``_press_global`` 非 None）不参与定档：100ms 档由
        ``set_drag_active`` 独占（拖拽期判定恒 False，轮询只是保活）。
        """
        if getattr(self._window, "_press_global", None) is not None:
            return
        target = (self.NORMAL_POLL_INTERVAL_MS if inside
                  else self.IDLE_POLL_INTERVAL_MS)
        if self._timer.interval() != target:
            self._timer.setInterval(target)

    def refresh(self) -> None:
        try:
            pos = QCursor.pos()
            self._sync_poll_interval(self._cursor_inside_window(pos))
            self._apply_through(self.should_click_through(pos))
        except (AttributeError, OSError, RuntimeError):
            logging.debug("更新 Qt 逐像素鼠标穿透失败", exc_info=True)

    # ---------------------------------------------------------------- 落点（薄 Qt 层）
    def _apply_through(self, enabled: bool) -> bool:
        """把目标穿透态落到窗口：Qt 属性 + 原生输入穿透标志。

        状态已是目标态时直接跳过（返回 False）——10ms 档下这必须是纯内存比较，
        否则每 tick 都要改一次窗口。跳过条件三条同时成立：属性是目标态、原生
        标志是目标态、**原生窗口句柄未变**。句柄变化必须重放：``setWindowFlags``
        （on_top 开关、捕获模式开关）会重建原生窗口，新窗口的输入穿透标志可能
        归零（``platform_win`` 对扩展样式位有同款防御）。重放要真写两次——
        ``QWindow::setFlag`` 对相同标志早退（qwindow.cpp:979-988），单写 True
        落不到新原生窗口。

        读属性/读标志都是纯 Qt 内存读（无系统调用），所以不需要 Windows 侧那种
        「每 N 次 refresh 才校正一次」的低频窗口：属性被外部改写会在一个 tick
        内被收敛回来。
        """
        win = self._window
        win_id = int(win.winId())
        handle = win.windowHandle()
        attribute_ok = bool(win.testAttribute(_TRANSPARENT_ATTR)) == enabled
        flag_ok = (handle is None
                   or bool(handle.flags() & _TRANSPARENT_FLAG) == enabled)
        if attribute_ok and flag_ok and self._applied_win_id == win_id:
            return False
        win.setAttribute(_TRANSPARENT_ATTR, enabled)
        if handle is not None:
            if (enabled and self._applied_win_id is not None
                    and self._applied_win_id != win_id):
                handle.setFlag(_TRANSPARENT_FLAG, False)
            handle.setFlag(_TRANSPARENT_FLAG, enabled)
        self._applied_through = enabled
        self._applied_win_id = win_id
        return True

    def resume(self) -> None:
        """隐藏后恢复（与 ``stop()`` 对称）：重开轮询表并立即收敛一次穿透态。

        「显示即立刻写正确穿透态」是硬要求：显示后不能有一段时间按陈旧状态吞掉
        点击。所以先作废缓存、同步 refresh 一次，再开表。
        """
        self._applied_through = None
        self._applied_win_id = None
        self.refresh()
        self._timer.start()

    def set_drag_active(self, active: bool) -> None:
        """拖拽按下/松手时切换轮询频率。

        拖拽（``_press_global`` 非 None）期间判定恒 False，每 10ms 轮询纯属空转：
        降频到 100ms。松手后立即按光标位置重新定档（盒内 10ms / 盒外 50ms）并
        强制刷新一次穿透态；非拖拽状态重复调用是 no-op。
        """
        if active:
            if self._timer.interval() != self.DRAG_POLL_INTERVAL_MS:
                self._timer.setInterval(self.DRAG_POLL_INTERVAL_MS)
            return
        if self._timer.interval() == self.NORMAL_POLL_INTERVAL_MS:
            return
        self._timer.setInterval(self.NORMAL_POLL_INTERVAL_MS)
        self.refresh()

    def stop(self) -> None:
        """停表（隐藏/关闭），并清掉穿透态（``mouse_through`` 除外）。

        缓存作废的理由同 Windows 侧：停表期间窗口可能被外部改写/重建，下次
        refresh 必须重新读一遍真实状态。清穿透态是因为隐藏窗口留着穿透态时，
        下次显示到第一次 refresh 之间会是一个「整屏吞点击」的窗口。
        """
        self._timer.stop()
        self._applied_through = None
        self._applied_win_id = None
        if not bool(getattr(self._window, "mouse_through", False)):
            try:
                self._apply_through(False)
            except (AttributeError, OSError, RuntimeError):
                pass
