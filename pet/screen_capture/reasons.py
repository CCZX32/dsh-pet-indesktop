# -*- coding: utf-8 -*-
"""「快速识屏」三条功能的不可用说明——两份消费面共用的**单一真相源**。

同一句话有两个出口，措辞必须一致：

- **菜单**：``pet/context_menus/shared.py`` 把那三条叶子置灰时写进 tooltip；
- **结果浮层**：``pet/screen_capture/actions.py`` 发现引擎缺席时写进状态行。

它们曾经各写一份字面量（内容相同、各管各的）。同一句话两处维护，改一处漏一处就会
出现"菜单说引擎还没接入、点下去浮层说的是另一句"这种自相矛盾；所以文案搬进本模块。

本模块**零 import**（不拖 Qt、不拖截图栈）：菜单层在启动期就装载，它可以把这里的
import 放在模块级而不付实质代价（本机实测：暖缓存下 import 0.6–0.8 ms，首次含字节码
编译约 3 ms；要避开的整条截图栈是另一个量级）。
"""

from __future__ import annotations

__all__ = ["OCR_PENDING_REASON", "TRANSLATION_PENDING_REASON"]

#: 本地 OCR 引擎缺席时那条如实说明（不是"暂时没有数据"，也不摆假结果）。
OCR_PENDING_REASON = "本地文字识别引擎尚未接入"

#: 翻译引擎缺席时那条如实说明（入口与双语对照位已就位，引擎是后续片）。
TRANSLATION_PENDING_REASON = "翻译引擎将在后续片接入"
